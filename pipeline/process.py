"""Correlation analysis, anomaly detection, and crop health scoring.

Consumes fetched data (satellites, weather, crops, futures, geopolitical)
from the cache directory and produces cross-dataset signals, anomaly
alerts, and per-commodity crop quality assessments.

Currently implemented:
  - Crop health scoring via NDVI + soil moisture z-scores (score_crop_health)
  - Seasonal baseline computation with circular DOY windowing
  - Condition classification (excellent -> very_poor, USDA-style bins)
  - Trend detection (improving/declining/stable)

Planned additions:
  - Weather anomaly summarization per region
  - Futures price correlation with weather and crop conditions
  - Geopolitical event impact scoring
  - Composite signal generation for the dashboard
"""

import json
import logging
from datetime import datetime

import numpy as np

from pipeline.config import CACHE_DIR, REGIONS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Crop condition bins (modeled after USDA Crop Condition reports)
# ---------------------------------------------------------------------------

CONDITION_BINS = [
    {"label": "excellent", "min_z": 1.0, "max_z": float("inf")},
    {"label": "good", "min_z": 0.5, "max_z": 1.0},
    {"label": "normal", "min_z": -0.5, "max_z": 0.5},
    {"label": "poor", "min_z": -1.0, "max_z": -0.5},
    {"label": "very_poor", "min_z": float("-inf"), "max_z": -1.0},
]


def _z_score_label(z):
    """Map a z-score to a crop condition label.

    Args:
        z: Z-score float (deviation from seasonal mean in std units).

    Returns:
        Condition label string.
    """
    for bin_def in CONDITION_BINS:
        if bin_def["min_z"] <= z < bin_def["max_z"]:
            return bin_def["label"]
    # Edge case: z exactly equals the upper boundary of "excellent"
    return "excellent" if z >= 1.0 else "very_poor"


# ---------------------------------------------------------------------------
# Seasonal baseline computation
# ---------------------------------------------------------------------------


def _compute_seasonal_baselines(dates, values_2d, region_index, window_days=48):
    """Compute a smoothed seasonal baseline for each date using nearby DOYs.

    With only a few years of data, each DOY has very few samples.
    To produce meaningful z-scores, we pool values from neighboring DOYs
    (within ±window_days) across all years to compute a smoothed seasonal
    mean and standard deviation.

    Args:
        dates: List of ISO date strings.
        values_2d: 2D list [time_index][region_index].
        region_index: Integer index into the region dimension.
        window_days: Half-width of the DOY window (default 48 days, ~3 composites).

    Returns:
        Dict mapping DOY (int) -> {"mean": float, "std": float}.
    """
    # Collect all (doy, value) pairs
    doy_val_pairs = []
    for t, date_str in enumerate(dates):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        doy = dt.timetuple().tm_yday
        val = values_2d[t][region_index]
        if val is not None:
            doy_val_pairs.append((doy, val))

    all_doys = np.array([p[0] for p in doy_val_pairs])
    all_vals = np.array([p[1] for p in doy_val_pairs])

    # Get unique DOYs that appear in the data
    unique_doys = sorted(set(all_doys))

    baselines = {}
    for target_doy in unique_doys:
        # Circular DOY distance (handles year boundary)
        doy_dist = np.minimum(
            np.abs(all_doys - target_doy),
            365 - np.abs(all_doys - target_doy),
        )
        mask = doy_dist <= window_days
        nearby = all_vals[mask]

        if len(nearby) >= 3:
            baselines[target_doy] = {
                "mean": float(nearby.mean()),
                "std": float(nearby.std(ddof=1)),
            }
        else:
            baselines[target_doy] = {
                "mean": float(nearby.mean()) if len(nearby) > 0 else 0.0,
                "std": 0.05,
            }

    return baselines


# ---------------------------------------------------------------------------
# Crop health scoring
# ---------------------------------------------------------------------------


def score_crop_health(satellite_data):
    """Score crop health per commodity per 16-day period using NDVI z-scores.

    For each region, computes how the current NDVI deviates from the
    seasonal baseline (same day-of-year across all available years).
    Each commodity inherits the score from its growing region.

    Soil moisture is used as a secondary indicator: low soil moisture
    combined with below-average NDVI strengthens the stress signal.

    Args:
        satellite_data: Dict from fetch_satellite_data() with keys:
            dates, regions, ndvi, soil_moisture.

    Returns:
        Dict mapping commodity -> list of period assessments:
        {
            "corn": [
                {
                    "date": "2023-01-01",
                    "ndvi": 0.134,
                    "ndvi_z": -0.82,
                    "soil_moisture": 0.339,
                    "soil_z": 0.15,
                    "composite_z": -0.53,
                    "condition": "poor",
                    "region": "us_corn_belt"
                },
                ...
            ],
            ...
        }
    """
    dates = satellite_data["dates"]
    ndvi_2d = satellite_data["ndvi"]
    soil_2d = satellite_data["soil_moisture"]
    region_keys = list(satellite_data["regions"].keys())

    # Build baselines per region
    ndvi_baselines = {}
    soil_baselines = {}
    for r_idx, r_key in enumerate(region_keys):
        ndvi_baselines[r_key] = _compute_seasonal_baselines(dates, ndvi_2d, r_idx)
        soil_baselines[r_key] = _compute_seasonal_baselines(dates, soil_2d, r_idx)

    # Score each commodity via its region
    crop_scores = {}

    for r_idx, r_key in enumerate(region_keys):
        region_cfg = REGIONS.get(r_key, {})
        commodities = region_cfg.get("commodities", [])
        ndvi_bl = ndvi_baselines[r_key]
        soil_bl = soil_baselines[r_key]

        for commodity in commodities:
            if commodity not in crop_scores:
                crop_scores[commodity] = []

            for t, date_str in enumerate(dates):
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                doy = dt.timetuple().tm_yday

                ndvi_val = ndvi_2d[t][r_idx]
                soil_val = soil_2d[t][r_idx]

                if ndvi_val is None or doy not in ndvi_bl:
                    continue

                # NDVI z-score
                bl = ndvi_bl[doy]
                ndvi_std = bl["std"] if bl["std"] > 0.01 else 0.05
                ndvi_z = (ndvi_val - bl["mean"]) / ndvi_std

                # Soil moisture z-score
                soil_z = 0.0
                if soil_val is not None and doy in soil_bl:
                    s_bl = soil_bl[doy]
                    soil_std = s_bl["std"] if s_bl["std"] > 0.01 else 0.02
                    soil_z = (soil_val - s_bl["mean"]) / soil_std

                # Composite score: 70% NDVI, 30% soil moisture
                composite_z = 0.7 * ndvi_z + 0.3 * soil_z

                crop_scores[commodity].append(
                    {
                        "date": date_str,
                        "ndvi": round(ndvi_val, 3),
                        "ndvi_z": round(ndvi_z, 2),
                        "soil_moisture": round(soil_val, 3)
                        if soil_val is not None
                        else None,
                        "soil_z": round(soil_z, 2),
                        "composite_z": round(composite_z, 2),
                        "condition": _z_score_label(composite_z),
                        "region": r_key,
                    }
                )

    # Sort each commodity's scores by date
    for commodity in crop_scores:
        crop_scores[commodity].sort(key=lambda x: x["date"])

    return crop_scores


def _summarize_crop_health(crop_scores):
    """Generate summary statistics from crop health scores.

    Args:
        crop_scores: Output of score_crop_health().

    Returns:
        Dict mapping commodity -> summary dict with condition distribution,
        latest assessment, and trend.
    """
    summaries = {}
    for commodity, periods in crop_scores.items():
        if not periods:
            continue

        # Condition distribution across all periods
        condition_counts = {}
        for p in periods:
            cond = p["condition"]
            condition_counts[cond] = condition_counts.get(cond, 0) + 1
        total = len(periods)
        distribution = {k: round(v / total, 3) for k, v in condition_counts.items()}

        # Latest assessment
        latest = periods[-1]

        # Trend: compare last 3 periods' composite_z to previous 3
        recent = [p["composite_z"] for p in periods[-3:]]
        prior = [p["composite_z"] for p in periods[-6:-3]]
        if recent and prior:
            trend_val = np.mean(recent) - np.mean(prior)
            if trend_val > 0.3:
                trend = "improving"
            elif trend_val < -0.3:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        summaries[commodity] = {
            "latest_condition": latest["condition"],
            "latest_composite_z": latest["composite_z"],
            "latest_date": latest["date"],
            "trend": trend,
            "condition_distribution": distribution,
            "region": latest["region"],
        }

    return summaries


# ---------------------------------------------------------------------------
# Price-vs-NDVI correlation
# ---------------------------------------------------------------------------

def compute_price_ndvi_correlation(crop_health, futures_data):
    """Compute rolling correlation between futures prices and NDVI z-scores.

    Aligns daily price data to 16-day NDVI composite periods, then computes
    Pearson correlation over a trailing window. A negative correlation means
    poor crop conditions (low NDVI) coincide with rising prices — the
    expected fundamental relationship.

    Args:
        crop_health: Dict from score_crop_health(), commodity -> period list.
        futures_data: Cached futures price dict, commodity -> OHLCV.

    Returns:
        Dict mapping commodity -> correlation analysis:
        {
            "overall_r": float,      # Full-period Pearson r
            "trailing_6m_r": float,  # Last ~6 months
            "interpretation": str,   # Human-readable
            "aligned_points": int,   # Number of aligned data points
        }
    """
    import pandas as pd

    results = {}
    for commodity, periods in crop_health.items():
        if commodity not in (futures_data or {}):
            continue

        fdata = futures_data[commodity]
        # Build price series
        price_series = pd.Series(
            fdata["close"],
            index=pd.to_datetime(fdata["dates"]),
        )

        # Build NDVI z-score series from crop health periods
        ndvi_dates = []
        ndvi_z_vals = []
        for p in periods:
            ndvi_dates.append(p["date"])
            ndvi_z_vals.append(p["composite_z"])

        ndvi_series = pd.Series(ndvi_z_vals, index=pd.to_datetime(ndvi_dates))

        # Resample prices to 16-day means aligned to NDVI dates
        aligned_prices = []
        for dt in ndvi_series.index:
            window = price_series.loc[
                (price_series.index >= dt) & (price_series.index < dt + pd.Timedelta(days=16))
            ]
            if len(window) > 0:
                aligned_prices.append(float(window.mean()))
            else:
                aligned_prices.append(float("nan"))

        price_aligned = pd.Series(aligned_prices, index=ndvi_series.index)

        # Drop NaNs
        valid = pd.DataFrame({"price": price_aligned, "ndvi_z": ndvi_series}).dropna()
        if len(valid) < 5:
            continue

        # Overall correlation
        overall_r = float(valid["price"].corr(valid["ndvi_z"]))

        # Trailing 6 months (~12 composites)
        recent = valid.iloc[-12:]
        trailing_r = float(recent["price"].corr(recent["ndvi_z"])) if len(recent) >= 5 else None

        # Interpretation
        if overall_r < -0.3:
            interp = "Strong inverse: poor crops → higher prices (expected)"
        elif overall_r < -0.1:
            interp = "Weak inverse: some price response to crop stress"
        elif overall_r > 0.3:
            interp = "Positive: prices follow crop conditions (demand-driven)"
        elif overall_r > 0.1:
            interp = "Weak positive: limited fundamental linkage"
        else:
            interp = "No significant correlation"

        results[commodity] = {
            "overall_r": round(overall_r, 3),
            "trailing_6m_r": round(trailing_r, 3) if trailing_r is not None else None,
            "interpretation": interp,
            "aligned_points": len(valid),
        }

    return results


# ---------------------------------------------------------------------------
# Weather impact on yields
# ---------------------------------------------------------------------------

def compute_weather_yield_impact(crops_data, weather_data):
    """Assess how temperature and precipitation anomalies relate to yields.

    For each crop commodity, compares the growing season weather anomalies
    (April-September) with the annual yield for each year.

    Args:
        crops_data: Cached USDA crop data dict.
        weather_data: Cached weather data dict.

    Returns:
        Dict mapping commodity -> weather impact analysis:
        {
            "years": [int],
            "growing_season_temp_anomaly": [float],  # °C deviation
            "growing_season_precip_anomaly": [float],  # mm deviation
            "yields": [float],
            "assessment": str,
        }
    """
    if not crops_data or not weather_data:
        return {}

    weather_regions = weather_data.get("weather", {})
    results = {}

    # Map commodities to their primary region
    commodity_region = {}
    for region_key, cfg in REGIONS.items():
        for commodity in cfg.get("commodities", []):
            if commodity not in commodity_region:
                commodity_region[commodity] = region_key

    for commodity, cdata in crops_data.items():
        region_key = commodity_region.get(commodity)
        if not region_key or region_key not in weather_regions:
            continue

        w = weather_regions[region_key]
        years = cdata.get("yield_history", {}).get("years", [])
        yields = cdata.get("yield_history", {}).get("yields", [])

        if not years or not yields:
            continue

        # Extract growing season (Apr-Sep) anomalies per year
        w_dates = w.get("dates", [])
        temp_anom = w.get("temp_anomaly", [])
        precip_anom = w.get("precip_anomaly", [])

        gs_temp = []
        gs_precip = []
        for year in years:
            # Find months April (04) through September (09) for this year
            temp_vals = []
            precip_vals = []
            for i, d in enumerate(w_dates):
                if d.startswith(str(year)) and i < len(temp_anom):
                    month = int(d[5:7])
                    if 4 <= month <= 9:
                        temp_vals.append(temp_anom[i])
                        precip_vals.append(precip_anom[i])

            gs_temp.append(round(float(np.mean(temp_vals)), 2) if temp_vals else None)
            gs_precip.append(round(float(np.mean(precip_vals)), 1) if precip_vals else None)

        # Simple assessment
        assessments = []
        for i, year in enumerate(years):
            if gs_temp[i] is not None and yields[i] is not None:
                temp = gs_temp[i]
                if temp > 1.5:
                    assessments.append(f"{year}: hot growing season (+{temp}°C)")
                elif temp < -1.5:
                    assessments.append(f"{year}: cool growing season ({temp}°C)")

        results[commodity] = {
            "years": years,
            "growing_season_temp_anomaly": gs_temp,
            "growing_season_precip_anomaly": gs_precip,
            "yields": yields,
            "assessment": "; ".join(assessments) if assessments else "Normal growing conditions",
        }

    return results


# ---------------------------------------------------------------------------
# COT sentiment scoring
# ---------------------------------------------------------------------------

def compute_cot_sentiment(cot_data):
    """Score managed money positioning as a sentiment indicator.

    Computes a z-score of the current net position relative to the
    historical distribution. Extreme positioning often precedes
    price reversals (contrarian signal).

    Args:
        cot_data: Cached COT positioning data dict.

    Returns:
        Dict mapping commodity -> sentiment analysis:
        {
            "net_position": int,
            "z_score": float,
            "percentile": float,        # 0-100
            "sentiment": str,           # very_bearish → very_bullish
            "contrarian_signal": str,   # potential reversal direction
            "weeks_at_extreme": int,    # consecutive weeks beyond ±1.5 std
        }
    """
    if not cot_data:
        return {}

    results = {}
    for commodity, cdata in cot_data.items():
        net = cdata.get("managed_money_net", [])
        if len(net) < 20:
            continue

        valid_net = [v for v in net if v is not None]
        if not valid_net:
            continue

        current = valid_net[-1]
        mean_net = float(np.mean(valid_net))
        std_net = float(np.std(valid_net))

        if std_net == 0:
            continue

        z = (current - mean_net) / std_net

        # Percentile rank
        sorted_net = sorted(valid_net)
        rank = sum(1 for v in sorted_net if v <= current)
        percentile = round(rank / len(sorted_net) * 100, 1)

        # Sentiment label
        if z > 2.0:
            sentiment = "very_bullish"
        elif z > 1.0:
            sentiment = "bullish"
        elif z > -1.0:
            sentiment = "neutral"
        elif z > -2.0:
            sentiment = "bearish"
        else:
            sentiment = "very_bearish"

        # Contrarian signal: extreme positioning suggests crowded trade
        if z > 1.5:
            contrarian = "bearish_reversal_risk"
        elif z < -1.5:
            contrarian = "bullish_reversal_risk"
        else:
            contrarian = "none"

        # Count consecutive weeks at extreme
        weeks_extreme = 0
        for v in reversed(valid_net):
            vz = (v - mean_net) / std_net
            if abs(vz) > 1.5:
                weeks_extreme += 1
            else:
                break

        results[commodity] = {
            "net_position": int(current),
            "z_score": round(z, 2),
            "percentile": percentile,
            "sentiment": sentiment,
            "contrarian_signal": contrarian,
            "weeks_at_extreme": weeks_extreme,
        }

    return results


# ---------------------------------------------------------------------------
# Cross-commodity correlation matrix
# ---------------------------------------------------------------------------

def compute_cross_commodity_correlations(futures_data):
    """Compute pairwise price correlation matrix across all commodities.

    Uses monthly returns (not raw prices) to remove trend bias.
    Also identifies the strongest positive and negative correlations.

    Args:
        futures_data: Cached futures price data dict.

    Returns:
        Dict with correlation matrix and notable pairs:
        {
            "matrix": {commodity -> {commodity -> float}},
            "strongest_positive": [{"pair": [str, str], "r": float}],
            "strongest_negative": [{"pair": [str, str], "r": float}],
            "commodities": [str],
        }
    """
    import pandas as pd

    if not futures_data:
        return {}

    # Build a DataFrame of daily close prices
    price_frames = {}
    for commodity, fdata in futures_data.items():
        close = fdata.get("close", [])
        dates = fdata.get("dates", [])
        if close and dates:
            price_frames[commodity] = pd.Series(
                close, index=pd.to_datetime(dates), name=commodity
            )

    if len(price_frames) < 2:
        return {}

    prices_df = pd.DataFrame(price_frames)

    # Resample to monthly returns for cleaner correlation
    monthly = prices_df.resample("MS").last()
    returns = monthly.pct_change().dropna()

    if len(returns) < 6:
        return {}

    # Correlation matrix
    corr = returns.corr()
    matrix = {}
    for c1 in corr.columns:
        matrix[c1] = {c2: round(float(corr.loc[c1, c2]), 3) for c2 in corr.columns}

    # Find notable pairs
    pairs = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = float(corr.loc[cols[i], cols[j]])
            pairs.append({"pair": [cols[i], cols[j]], "r": round(r, 3)})

    pairs.sort(key=lambda p: p["r"], reverse=True)
    strongest_pos = [p for p in pairs if p["r"] > 0.3][:5]
    strongest_neg = [p for p in pairs if p["r"] < -0.3][:5]

    return {
        "matrix": matrix,
        "strongest_positive": strongest_pos,
        "strongest_negative": strongest_neg,
        "commodities": cols,
        "months_analyzed": len(returns),
    }


def compute_yield_price_correlation(crops_data, futures_data):
    """Compute correlation between annual crop yields and average annual prices.

    This is the core fundamental analysis: do years with lower yields
    correspond to higher prices?

    Args:
        crops_data: Cached USDA crop data dict.
        futures_data: Cached futures price data dict.

    Returns:
        Dict mapping commodity -> yield-price correlation:
        {
            "years": [int],
            "yields": [float],
            "avg_annual_price": [float],
            "correlation": float,
            "interpretation": str,
        }
    """
    import pandas as pd

    if not crops_data or not futures_data:
        return {}

    results = {}
    for commodity, cdata in crops_data.items():
        if commodity not in futures_data:
            continue

        years = cdata.get("yield_history", {}).get("years", [])
        yields = cdata.get("yield_history", {}).get("yields", [])
        if not years or not yields:
            continue

        # Compute average annual price from daily data
        fdata = futures_data[commodity]
        price_series = pd.Series(
            fdata["close"], index=pd.to_datetime(fdata["dates"])
        )
        annual_prices = price_series.resample("YS").mean()

        # Align years
        aligned_years = []
        aligned_yields = []
        aligned_prices = []
        for i, year in enumerate(years):
            yr_dt = pd.Timestamp(f"{year}-01-01")
            if yr_dt in annual_prices.index and yields[i] is not None:
                aligned_years.append(year)
                aligned_yields.append(yields[i])
                aligned_prices.append(round(float(annual_prices.loc[yr_dt]), 2))

        if len(aligned_years) < 3:
            continue

        arr_y = np.array(aligned_yields)
        arr_p = np.array(aligned_prices)
        r = float(np.corrcoef(arr_y, arr_p)[0, 1])

        if r < -0.4:
            interp = "Strong inverse: low yields → high prices (classic supply shock)"
        elif r < -0.2:
            interp = "Moderate inverse: yields influence prices"
        elif r > 0.4:
            interp = "Positive: high yields and high prices (demand era)"
        elif r > 0.2:
            interp = "Weak positive: demand outweighs supply effects"
        else:
            interp = "Weak linkage: other factors dominate"

        results[commodity] = {
            "years": aligned_years,
            "yields": aligned_yields,
            "avg_annual_price": aligned_prices,
            "correlation": round(r, 3),
            "interpretation": interp,
        }

    return results


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------


def _generate_signals(
    crop_summary, weather_data, futures_data, cot_data, geopolitical_data
):
    """Generate cross-dataset correlation signals and anomaly alerts.

    Combines five data dimensions into actionable signals:
      1. Crop stress — poor/very_poor satellite-based condition scores
      2. Drought alerts — severe+ drought covering >10% of a region
      3. Price momentum — 20-day vs 60-day moving average crossover >5%
      4. COT extremes — managed money net position >1.5 std from mean
      5. Geopolitical — elevated count of high-severity events

    Args:
        crop_summary: Output of _summarize_crop_health(), or empty dict.
        weather_data: Cached weather data dict, or None.
        futures_data: Cached futures price data dict, or None.
        cot_data: Cached COT positioning data dict, or None.
        geopolitical_data: Cached geopolitical events dict, or None.

    Returns:
        List of signal dicts sorted by severity (5=highest, 1=lowest)::

            [{"type": str, "commodity": str, "severity": int,
              "message": str, "trend": str, "date": str}, ...]
    """
    signals = []

    # 1. Crop stress signals from satellite data
    for commodity, summary in crop_summary.items():
        condition = summary.get("latest_condition", "normal")
        z = summary.get("latest_composite_z", 0)
        if condition in ("poor", "very_poor"):
            signals.append(
                {
                    "type": "crop_stress",
                    "commodity": commodity,
                    "severity": 4 if condition == "very_poor" else 3,
                    "message": f"{commodity.title()} crop conditions are {condition.replace('_', ' ')} (z={z:.2f})",
                    "trend": summary.get("trend", "stable"),
                    "date": summary.get("latest_date", ""),
                }
            )

    # 2. Drought alerts from weather data
    if weather_data and "drought" in weather_data:
        for region_key, records in weather_data["drought"].items():
            if not records:
                continue
            latest = records[-1]
            severe_pct = (
                latest.get("severe_drought", 0)
                + latest.get("extreme_drought", 0)
                + latest.get("exceptional_drought", 0)
            )
            if severe_pct > 10:
                region_name = REGIONS.get(region_key, {}).get("name", region_key)
                signals.append(
                    {
                        "type": "drought",
                        "commodity": ", ".join(
                            REGIONS.get(region_key, {}).get("commodities", [])
                        ),
                        "severity": 5
                        if severe_pct > 50
                        else 4
                        if severe_pct > 25
                        else 3,
                        "message": f"{region_name}: {severe_pct:.0f}% area in severe+ drought",
                        "trend": "worsening",
                        "date": latest.get("date", ""),
                    }
                )

    # 3. Price momentum signals from futures
    if futures_data:
        for commodity, fdata in futures_data.items():
            close = fdata.get("close", [])
            if len(close) < 20:
                continue
            # 20-day vs 60-day moving average crossover
            recent_20 = np.mean(close[-20:])
            recent_60 = np.mean(close[-60:]) if len(close) >= 60 else np.mean(close)
            pct_diff = (recent_20 - recent_60) / recent_60 * 100

            if abs(pct_diff) > 5:
                direction = "bullish" if pct_diff > 0 else "bearish"
                signals.append(
                    {
                        "type": "price_momentum",
                        "commodity": commodity,
                        "severity": 3 if abs(pct_diff) > 10 else 2,
                        "message": f"{commodity.title()} 20d MA is {pct_diff:+.1f}% vs 60d MA ({direction})",
                        "trend": direction,
                        "date": fdata["dates"][-1] if fdata["dates"] else "",
                    }
                )

    # 4. COT positioning extremes
    if cot_data:
        for commodity, cdata in cot_data.items():
            net = cdata.get("managed_money_net", [])
            if len(net) < 10:
                continue
            current_net = net[-1] if net[-1] is not None else 0
            avg_net = float(np.mean([v for v in net if v is not None]))
            std_net = float(np.std([v for v in net if v is not None]))
            if std_net > 0:
                z_pos = (current_net - avg_net) / std_net
                if abs(z_pos) > 1.5:
                    direction = "extremely long" if z_pos > 0 else "extremely short"
                    signals.append(
                        {
                            "type": "cot_extreme",
                            "commodity": commodity,
                            "severity": 3 if abs(z_pos) > 2 else 2,
                            "message": f"Managed money {direction} {commodity} (z={z_pos:.1f})",
                            "trend": "bullish" if z_pos > 0 else "bearish",
                            "date": cdata["dates"][-1] if cdata["dates"] else "",
                        }
                    )

    # 5. Geopolitical event count (high activity = elevated risk)
    if geopolitical_data:
        events = geopolitical_data.get("events", [])
        high_severity = [e for e in events if e.get("severity", 0) >= 4]
        if len(high_severity) >= 5:
            signals.append(
                {
                    "type": "geopolitical",
                    "commodity": "all",
                    "severity": 3,
                    "message": f"{len(high_severity)} high-severity geopolitical events in recent coverage",
                    "trend": "elevated_risk",
                    "date": high_severity[0]["date"] if high_severity else "",
                }
            )

    # Sort by severity descending
    signals.sort(key=lambda s: s["severity"], reverse=True)
    return signals


def process_all():
    """Run all processing steps on cached fetcher data.

    Loads all available cached data (satellites, weather, futures, crops,
    COT, geopolitical) and produces crop health scores, cross-dataset
    signals, and anomaly alerts. Missing caches are handled gracefully.

    Returns:
        Dict with all processing results::

            {
                "crop_health": {<commodity>: [period assessments]},
                "crop_health_summary": {<commodity>: summary dict},
                "signals": [signal dicts, sorted by severity desc],
                "weather": cached weather data or None,
                "futures": cached futures data or None,
                "crops": cached crops data or None,
                "cot": cached COT data or None,
                "geopolitical": cached geopolitical data or None,
            }
    """
    results = {}

    # Load all cached data (each is optional)
    def _load_cache(name):
        path = CACHE_DIR / f"{name}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            logger.info("Loaded %s cache", name)
            return data
        logger.info("No %s cache found", name)
        return None

    satellite_data = _load_cache("satellites")
    weather_data = _load_cache("weather")
    futures_data = _load_cache("futures")
    crops_data = _load_cache("crops")
    cot_data = _load_cache("cot")
    geopolitical_data = _load_cache("geopolitical")
    fred_data = _load_cache("fred")

    # Crop health scoring (requires satellite data)
    crop_scores = {}
    crop_summary = {}
    if satellite_data:
        crop_scores = score_crop_health(satellite_data)
        crop_summary = _summarize_crop_health(crop_scores)
        for commodity, summary in crop_summary.items():
            logger.info(
                "  %s: %s (z=%.2f, trend=%s)",
                commodity,
                summary["latest_condition"],
                summary["latest_composite_z"],
                summary["trend"],
            )

    # Price-vs-NDVI correlation
    price_ndvi = {}
    if crop_scores and futures_data:
        price_ndvi = compute_price_ndvi_correlation(crop_scores, futures_data)
        for commodity, corr in price_ndvi.items():
            logger.info(
                "  %s price-NDVI r=%.3f (%s)",
                commodity, corr["overall_r"], corr["interpretation"],
            )

    # Weather impact on yields
    weather_impact = compute_weather_yield_impact(crops_data, weather_data)
    for commodity, impact in weather_impact.items():
        logger.info("  %s weather: %s", commodity, impact["assessment"])

    # COT sentiment scoring
    cot_sentiment = compute_cot_sentiment(cot_data)
    for commodity, sent in cot_sentiment.items():
        logger.info(
            "  %s COT: %s (z=%.2f, %dp, contrarian=%s)",
            commodity, sent["sentiment"], sent["z_score"],
            sent["percentile"], sent["contrarian_signal"],
        )

    # Cross-commodity correlation matrix
    cross_corr = compute_cross_commodity_correlations(futures_data)
    if cross_corr:
        logger.info(
            "Cross-commodity: %d months analyzed, %d commodities",
            cross_corr.get("months_analyzed", 0), len(cross_corr.get("commodities", [])),
        )
        for p in cross_corr.get("strongest_positive", [])[:3]:
            logger.info("  Strong +: %s ↔ %s r=%.3f", p["pair"][0], p["pair"][1], p["r"])
        for p in cross_corr.get("strongest_negative", [])[:3]:
            logger.info("  Strong -: %s ↔ %s r=%.3f", p["pair"][0], p["pair"][1], p["r"])

    # Yield-price correlation (annual, long history)
    yield_price = compute_yield_price_correlation(crops_data, futures_data)
    for commodity, yp in yield_price.items():
        logger.info(
            "  %s yield-price r=%.3f over %d years (%s)",
            commodity, yp["correlation"], len(yp["years"]), yp["interpretation"],
        )

    # Generate cross-dataset signals
    signals = _generate_signals(
        crop_summary, weather_data, futures_data, cot_data, geopolitical_data
    )
    logger.info("Generated %d signals", len(signals))
    for sig in signals[:5]:
        logger.info("  [%d] %s: %s", sig["severity"], sig["type"], sig["message"])

    results["crop_health"] = crop_scores
    results["crop_health_summary"] = crop_summary
    results["price_ndvi_correlation"] = price_ndvi
    results["weather_impact"] = weather_impact
    results["cot_sentiment"] = cot_sentiment
    results["cross_commodity_correlations"] = cross_corr
    results["yield_price_correlation"] = yield_price
    results["signals"] = signals
    results["weather"] = weather_data
    results["futures"] = futures_data
    results["crops"] = crops_data
    results["cot"] = cot_data
    results["geopolitical"] = geopolitical_data
    results["fred"] = fred_data

    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    results = process_all()
    if results:
        scores = results["crop_health"]
        summary = results["crop_health_summary"]
        logger.info("Processed %d commodities", len(scores))
        for commodity, periods in scores.items():
            conditions = [p["condition"] for p in periods]
            logger.info(
                "  %s: %d periods, conditions: %s",
                commodity,
                len(periods),
                {c: conditions.count(c) for c in set(conditions)},
            )
