const DATA_DIR = "data";

const COLORS = {
  corn: "#fbbf24",
  wheat: "#fb923c",
  soybeans: "#34d399",
  cotton: "#a78bfa",
  sugar: "#f472b6",
  coffee: "#92400e",
  crude_oil: "#64748b",
  natural_gas: "#38bdf8",
};

const plotlyLayout = {
  paper_bgcolor: "transparent",
  plot_bgcolor: "transparent",
  font: { family: "Inter, sans-serif", color: "#e4e6ed", size: 12 },
  margin: { t: 32, r: 16, b: 40, l: 56 },
  xaxis: { gridcolor: "#2a2e3b", linecolor: "#2a2e3b" },
  yaxis: { gridcolor: "#2a2e3b", linecolor: "#2a2e3b" },
  legend: { orientation: "h", y: -0.18, font: { size: 11 } },
};

const plotlyConfig = { responsive: true, displayModeBar: false };

async function fetchJSON(filename) {
  const res = await fetch(`${DATA_DIR}/${filename}`);
  if (!res.ok) throw new Error(`Failed to load ${filename}`);
  return res.json();
}

function formatDate(dateStr) {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function capitalize(s) {
  return s.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Summary metrics
// ---------------------------------------------------------------------------

function renderSummary(summary) {
  const el = document.getElementById("last-updated");
  if (summary.last_updated) {
    el.textContent = `Updated ${formatDate(summary.last_updated)}`;
  }

  const set = (id, val) => {
    const card = document.getElementById(id);
    if (card) card.querySelector(".metric-value").textContent = val ?? "--";
  };

  set("metric-commodities", summary.commodities_tracked);
  set("metric-signals", summary.active_signals);
  set("metric-regions", summary.regions_tracked);
  set("metric-sources", 6); // satellites, weather, crops, futures, COT, geopolitical
}

// ---------------------------------------------------------------------------
// Commodity table
// ---------------------------------------------------------------------------

function renderCommodityTable(commodities, signals) {
  const tbody = document.getElementById("commodity-tbody");
  if (!tbody) return;
  tbody.innerHTML = "";

  const signalMap = {};
  (signals.signals || []).forEach(s => {
    if (!signalMap[s.commodity]) signalMap[s.commodity] = s;
  });

  Object.entries(commodities).forEach(([name, data]) => {
    const close = data.price_history?.close;
    const lastPrice = close ? close[close.length - 1] : null;
    const prevPrice = close && close.length > 20 ? close[close.length - 21] : null;
    const changePct = lastPrice && prevPrice ? ((lastPrice - prevPrice) / prevPrice * 100) : 0;
    const changeClass = changePct >= 0 ? "change-positive" : "change-negative";

    const corr = data.price_ndvi_correlation?.overall_r;
    const sig = signalMap[name];
    const sentiment = data.cot_sentiment?.sentiment;

    const row = document.createElement("tr");
    row.innerHTML = `
      <td><span style="color:${COLORS[name] || '#e4e6ed'}">${capitalize(name)}</span></td>
      <td>${lastPrice != null ? `$${lastPrice.toFixed(2)}` : "--"}</td>
      <td class="${changeClass}">${changePct >= 0 ? "+" : ""}${changePct.toFixed(1)}%</td>
      <td>${corr != null ? corr.toFixed(3) : "--"}</td>
      <td>${sentiment ? capitalize(sentiment) : "--"}</td>
      <td>${sig ? sig.message.substring(0, 40) + "..." : "None"}</td>
    `;
    tbody.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// Price chart
// ---------------------------------------------------------------------------

function renderPriceChart(commodities) {
  const el = document.getElementById("chart-prices");
  if (!el) return;

  const traces = Object.entries(commodities)
    .filter(([, d]) => d.price_history?.close)
    .map(([name, d]) => ({
      x: d.price_history.dates,
      y: d.price_history.close,
      name: capitalize(name),
      type: "scatter",
      mode: "lines",
      line: { color: COLORS[name], width: 1.5 },
    }));

  if (!traces.length) {
    el.innerHTML = '<div class="loading">No price data available</div>';
    return;
  }

  // Normalize to % change from start for comparability
  const normTraces = traces.map(t => ({
    ...t,
    y: t.y.map(v => ((v - t.y[0]) / t.y[0]) * 100),
  }));

  Plotly.newPlot(el, normTraces, {
    ...plotlyLayout,
    yaxis: { ...plotlyLayout.yaxis, title: "% Change", zeroline: true, zerolinecolor: "#4a4e5a" },
  }, plotlyConfig);
}

// ---------------------------------------------------------------------------
// Weather anomalies chart
// ---------------------------------------------------------------------------

function renderWeatherChart(weather) {
  const el = document.getElementById("chart-weather");
  if (!el) return;

  const regions = weather.regions || {};
  if (!Object.keys(regions).length) {
    el.innerHTML = '<div class="loading">No weather data available</div>';
    return;
  }

  const regionColors = {
    us_corn_belt: "#fbbf24",
    great_plains: "#fb923c",
    california_central_valley: "#34d399",
    gulf_coast: "#38bdf8",
  };

  const traces = Object.entries(regions).map(([name, d]) => ({
    x: d.dates,
    y: d.temp_anomaly,
    name: capitalize(name),
    type: "bar",
    marker: { color: regionColors[name] || "#4f8ff7", opacity: 0.7 },
  }));

  Plotly.newPlot(el, traces, {
    ...plotlyLayout,
    yaxis: { ...plotlyLayout.yaxis, title: "Temp Anomaly (°C)" },
    barmode: "group",
    bargap: 0.15,
  }, plotlyConfig);
}

// ---------------------------------------------------------------------------
// Crop yields chart
// ---------------------------------------------------------------------------

function renderCropChart(crops) {
  const el = document.getElementById("chart-crops");
  if (!el) return;

  const traces = Object.entries(crops)
    .filter(([, d]) => d.yield_history?.years?.length)
    .map(([name, d]) => ({
      x: d.yield_history.years,
      y: d.yield_history.yields,
      name: `${capitalize(name)} (${d.unit || "bu/acre"})`,
      type: "scatter",
      mode: "lines+markers",
      line: { color: COLORS[name], width: 2 },
      marker: { size: 8 },
    }));

  if (!traces.length) {
    el.innerHTML = '<div class="loading">No crop data available</div>';
    return;
  }

  Plotly.newPlot(el, traces, {
    ...plotlyLayout,
    yaxis: { ...plotlyLayout.yaxis, title: "Yield" },
  }, plotlyConfig);
}

// ---------------------------------------------------------------------------
// Correlation chart (Price-NDVI + COT sentiment)
// ---------------------------------------------------------------------------

function renderCorrelationChart(commodities) {
  const el = document.getElementById("chart-correlations");
  if (!el) return;

  const names = [];
  const ndviCorr = [];
  const cotZ = [];

  Object.entries(commodities).forEach(([name, d]) => {
    const corr = d.price_ndvi_correlation?.overall_r;
    const cz = d.cot_sentiment?.z_score;
    if (corr != null || cz != null) {
      names.push(capitalize(name));
      ndviCorr.push(corr ?? 0);
      cotZ.push(cz ?? 0);
    }
  });

  if (!names.length) {
    el.innerHTML = '<div class="loading">No correlation data available</div>';
    return;
  }

  Plotly.newPlot(el, [
    {
      x: names, y: ndviCorr, name: "Price-NDVI Corr",
      type: "bar", marker: { color: "#34d399" },
    },
    {
      x: names, y: cotZ, name: "COT Sentiment (z)",
      type: "bar", marker: { color: "#f472b6" },
    },
  ], {
    ...plotlyLayout,
    yaxis: { ...plotlyLayout.yaxis, title: "Score", zeroline: true, zerolinecolor: "#4a4e5a" },
    barmode: "group",
  }, plotlyConfig);
}

// ---------------------------------------------------------------------------
// Signals list
// ---------------------------------------------------------------------------

function renderSignals(signals) {
  const list = document.getElementById("signals-list");
  if (!list) return;
  list.innerHTML = "";

  const items = signals.signals || [];
  if (!items.length) {
    list.innerHTML = '<li class="signal-item"><span class="signal-message">No active signals</span></li>';
    return;
  }

  items.forEach(s => {
    const sevClass = s.severity >= 4 ? "high" : s.severity >= 3 ? "medium" : "low";
    const li = document.createElement("li");
    li.className = "signal-item";
    li.innerHTML = `
      <span class="signal-dot ${sevClass}"></span>
      <span class="signal-commodity">${capitalize(s.commodity)}</span>
      <span class="signal-type">[${capitalize(s.type)}]</span>
      <span class="signal-message">${s.message}</span>
    `;
    list.appendChild(li);
  });
}

// ---------------------------------------------------------------------------
// Error state
// ---------------------------------------------------------------------------

function showError(message) {
  document.getElementById("dashboard-content").innerHTML = `
    <div class="error-message">${message}</div>
  `;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

async function init() {
  try {
    const [summary, commodities, weather, crops, signals] = await Promise.all([
      fetchJSON("summary.json"),
      fetchJSON("commodities.json"),
      fetchJSON("weather.json"),
      fetchJSON("crops.json"),
      fetchJSON("signals.json"),
    ]);

    renderSummary(summary);
    renderCommodityTable(commodities, signals);
    renderPriceChart(commodities);
    renderWeatherChart(weather);
    renderCropChart(crops);
    renderCorrelationChart(commodities);
    renderSignals(signals);
  } catch (err) {
    console.error("Dashboard init error:", err);
    showError("Failed to load dashboard data. Run the pipeline to generate data files.");
  }
}

document.addEventListener("DOMContentLoaded", init);
