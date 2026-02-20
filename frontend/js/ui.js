// ui.js — Creación y actualización de cards y componentes DOM

const cards = {};
const gauges = {};
const charts = {};
const doorEvents = {};    // {topic: [{time, value}]} — eventos históricos + en vivo
const lastDoorState = {}; // {topic: "open"|"closed"} — para evitar duplicados

// --- SVG Icons ---

const ICONS = {
  thermometer: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="icon">
    <path d="M14 14.76V3.5a2.5 2.5 0 0 0-5 0v11.26a4.5 4.5 0 1 0 5 0z"/>
  </svg>`,

  doorClosed: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="icon">
    <path d="M18 20V6a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v14"/><path d="M2 20h20"/><path d="M14 12v.01"/>
  </svg>`,

  doorOpen: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="icon">
    <path d="M13 4h3a2 2 0 0 1 2 2v14"/><path d="M2 20h3"/><path d="M13 20h7"/>
    <path d="M10 12v.01"/><path d="M13 4.562v16.157a1 1 0 0 1-1.242.97L5 20V5.562a2 2 0 0 1 1.515-1.94l4-1A2 2 0 0 1 13 4.561z"/>
  </svg>`,
};

// --- Connection Status ---

export function setConnectionStatus(connected) {
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  if (connected) {
    dot.className = "status-dot connected";
    text.textContent = "conectado";
  } else {
    dot.className = "status-dot disconnected";
    text.textContent = "desconectado";
  }
}

// --- Helpers de tiempo ---

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
}

function fmtDuration(tOpen, tClose) {
  const mins = Math.round((new Date(tClose) - new Date(tOpen)) / 60000);
  return mins < 1 ? "<1min" : `${mins}min`;
}

// --- Historial de puerta ---

function pairDoorEvents(events) {
  const pairs = [];
  let openEv = null;
  for (const ev of events) {
    if (ev.value === "open") {
      if (openEv) pairs.push({ open: openEv, close: null }); // anterior sin cerrar
      openEv = ev;
    } else if (ev.value === "closed") {
      pairs.push({ open: openEv, close: ev });
      openEv = null;
    }
  }
  if (openEv) pairs.push({ open: openEv, close: null });
  return pairs.reverse(); // más reciente primero
}

function renderDoorHistory(topic, events) {
  const safeId = topic.replace(/\//g, "-");
  const listEl = document.getElementById(`door-history-${safeId}`);
  if (!listEl) return;

  const pairs = pairDoorEvents(events).slice(0, 8);
  if (pairs.length === 0) {
    listEl.innerHTML = `<div class="h-empty">sin eventos hoy</div>`;
    return;
  }

  listEl.innerHTML = pairs.map(({ open, close }) => {
    const openStr = open ? fmtTime(open.time) : "?";
    const closeStr = close ? fmtTime(close.time) : "...";
    const closeClass = close ? "" : "h-open-now";
    const dur = open && close
      ? `<span class="h-dur">${fmtDuration(open.time, close.time)}</span>`
      : "";
    return `<div class="history-item">
      <span class="h-time">${openStr}</span>
      <span class="h-sep">→</span>
      <span class="h-time ${closeClass}">${closeStr}</span>
      ${dur}
    </div>`;
  }).join("");
}

function appendDoorEvent(topic, value) {
  if (lastDoorState[topic] === value) return; // sin cambio de estado
  lastDoorState[topic] = value;
  if (!doorEvents[topic]) doorEvents[topic] = [];
  doorEvents[topic].push({ time: new Date().toISOString(), value });
  renderDoorHistory(topic, doorEvents[topic]);
}

// --- Gráfica de temperatura ---

function renderTempChart(topic, data) {
  const safeId = topic.replace(/\//g, "-");
  const canvas = document.getElementById(`chart-${safeId}`);
  if (!canvas || !data.length) return;

  charts[topic] = new Chart(canvas, {
    type: "line",
    data: {
      labels: data.map(d => fmtTime(d.time)),
      datasets: [{
        data: data.map(d => d.value),
        borderColor: "#4ecca3",
        backgroundColor: "#4ecca318",
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        borderWidth: 1.5,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: "#8892b0", maxTicksLimit: 5, font: { size: 10 } },
          grid: { color: "#ffffff08" },
          border: { display: false },
        },
        y: {
          ticks: { color: "#8892b0", maxTicksLimit: 4, font: { size: 10 } },
          grid: { color: "#ffffff08" },
          border: { display: false },
        },
      },
    },
  });
}

function appendToChart(topic, value) {
  const chart = charts[topic];
  if (!chart) return;
  chart.data.labels.push(fmtTime(new Date().toISOString()));
  chart.data.datasets[0].data.push(value);
  if (chart.data.labels.length > 300) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  chart.update("none");
}

// --- Creación de cards ---

function createGaugeCard(topic, parsed) {
  const safeId = topic.replace(/\//g, "-");
  const card = document.createElement("div");
  card.className = "sensor-card";
  card.innerHTML = `
    <div class="card-header">
      <span class="card-icon">${ICONS.thermometer}</span>
      <div>
        <div class="card-title">${parsed.locationLabel}</div>
        <div class="card-subtitle">${parsed.sensorType.label}</div>
      </div>
    </div>
    <div class="card-body">
      <div class="gauge-container">
        <canvas id="gauge-${safeId}"></canvas>
      </div>
      <div class="gauge-value" id="value-${safeId}">--${parsed.sensorType.unit}</div>
      <div class="chart-wrapper">
        <div class="chart-label">últimas 24h</div>
        <div class="chart-container">
          <canvas id="chart-${safeId}"></canvas>
        </div>
      </div>
    </div>
  `;

  document.getElementById("dashboard").appendChild(card);
  cards[topic] = card;

  // Gauge.js
  const opts = parsed.sensorType.gaugeOpts;
  const gauge = new Gauge(card.querySelector(`#gauge-${safeId}`)).setOptions({
    angle: -0.25,
    lineWidth: 0.15,
    radiusScale: 0.9,
    pointer: { length: 0.55, strokeWidth: 0.035, color: "#eee" },
    staticZones: opts.zones.map(z => ({ strokeStyle: z.color, min: z.min, max: z.max })),
    staticLabels: {
      font: "11px monospace",
      labels: [opts.min, 10, 20, 30, 40, opts.max],
      color: "#8892b0",
      fractionDigits: 0,
    },
    limitMax: true,
    limitMin: true,
    highDpiSupport: true,
    renderTicks: { divisions: 5, divWidth: 1, divLength: 0.5, divColor: "#8892b044" },
  });
  gauge.maxValue = opts.max;
  gauge.setMinValue(opts.min);
  gauge.animationSpeed = 20;
  gauge.set(opts.min);
  gauges[topic] = gauge;

  // Cargar histórico
  const params = new URLSearchParams({ location: parsed.location, measurement: parsed.measurement });
  fetch(`/api/history?${params}`)
    .then(r => r.json())
    .then(data => renderTempChart(topic, data))
    .catch(() => {});
}

function createBinaryCard(topic, parsed) {
  const safeId = topic.replace(/\//g, "-");
  const card = document.createElement("div");
  card.className = "sensor-card";
  card.innerHTML = `
    <div class="card-header">
      <span class="card-icon">${ICONS.doorClosed}</span>
      <div>
        <div class="card-title">${parsed.locationLabel}</div>
        <div class="card-subtitle">${parsed.sensorType.label}</div>
      </div>
    </div>
    <div class="card-body">
      <div class="binary-status" id="binary-${safeId}">
        <div class="binary-icon">${ICONS.doorClosed}</div>
        <div class="binary-label">--</div>
      </div>
      <div class="door-history">
        <div class="history-title">historial (24h)</div>
        <div class="history-list" id="door-history-${safeId}">
          <div class="h-empty">cargando...</div>
        </div>
      </div>
    </div>
  `;

  document.getElementById("dashboard").appendChild(card);
  cards[topic] = card;

  // Cargar eventos
  const params = new URLSearchParams({ location: parsed.location, measurement: parsed.measurement });
  fetch(`/api/events?${params}`)
    .then(r => r.json())
    .then(evs => {
      doorEvents[topic] = evs;
      renderDoorHistory(topic, evs);
    })
    .catch(() => {
      const listEl = document.getElementById(`door-history-${safeId}`);
      if (listEl) listEl.innerHTML = `<div class="h-empty">sin datos</div>`;
    });
}

// --- Actualización de cards ---

function updateGaugeCard(topic, parsed, value) {
  const safeId = topic.replace(/\//g, "-");
  const valueEl = document.getElementById(`value-${safeId}`);
  if (valueEl && !isNaN(value)) {
    valueEl.textContent = `${value.toFixed(1)}${parsed.sensorType.unit}`;
    gauges[topic]?.set(value);
  }
}

function updateBinaryCard(topic, parsed, state) {
  const safeId = topic.replace(/\//g, "-");
  const container = document.getElementById(`binary-${safeId}`);
  if (!container) return;

  const stateConfig = parsed.sensorType.states[state] || parsed.sensorType.states.closed;
  const icon = state === "open" ? ICONS.doorOpen : ICONS.doorClosed;

  container.querySelector(".binary-icon").innerHTML = icon;
  container.querySelector(".binary-label").textContent = stateConfig.label;
  container.style.color = stateConfig.color;

  const card = cards[topic];
  if (card) {
    card.querySelector(".card-icon").innerHTML = icon;
    card.style.borderLeftColor = stateConfig.color;
  }
}

// --- API pública ---

export function createOrUpdateCard(topic, parsed, payload) {
  const sensorType = parsed.sensorType;
  if (!sensorType) return;

  const value = sensorType.parseValue(payload);
  const isNew = !cards[topic];

  if (isNew) {
    if (sensorType.renderer === "gauge") createGaugeCard(topic, parsed);
    else if (sensorType.renderer === "binary") createBinaryCard(topic, parsed);
  }

  if (sensorType.renderer === "gauge") {
    updateGaugeCard(topic, parsed, value);
    if (!isNew) appendToChart(topic, value);
  } else if (sensorType.renderer === "binary") {
    updateBinaryCard(topic, parsed, value);
    if (isNew) {
      lastDoorState[topic] = value; // estado inicial, no contar como evento
    } else {
      appendDoorEvent(topic, value); // evento en tiempo real
    }
  }
}
