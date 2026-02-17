// ui.js — Creación y actualización de cards y componentes DOM

const cards = {};
const gauges = {};

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

// --- Card Creation ---

function createGaugeCard(topic, parsed) {
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
        <canvas id="gauge-${topic.replace(/\//g, "-")}"></canvas>
      </div>
      <div class="gauge-value" id="value-${topic.replace(/\//g, "-")}">--${parsed.sensorType.unit}</div>
    </div>
  `;

  document.getElementById("dashboard").appendChild(card);
  cards[topic] = card;

  // Init Gauge.js
  const canvas = card.querySelector("canvas");
  const opts = parsed.sensorType.gaugeOpts;
  const gauge = new Gauge(canvas).setOptions({
    angle: -0.25,
    lineWidth: 0.15,
    radiusScale: 0.9,
    pointer: {
      length: 0.55,
      strokeWidth: 0.035,
      color: "#eee",
    },
    staticZones: opts.zones.map(z => ({
      strokeStyle: z.color,
      min: z.min,
      max: z.max,
    })),
    staticLabels: {
      font: "11px monospace",
      labels: [opts.min, 10, 20, 30, 40, opts.max],
      color: "#8892b0",
      fractionDigits: 0,
    },
    limitMax: true,
    limitMin: true,
    highDpiSupport: true,
    renderTicks: {
      divisions: 5,
      divWidth: 1,
      divLength: 0.5,
      divColor: "#8892b044",
    },
  });

  gauge.maxValue = opts.max;
  gauge.setMinValue(opts.min);
  gauge.animationSpeed = 20;
  gauge.set(opts.min);
  gauges[topic] = gauge;
}

function createBinaryCard(topic, parsed) {
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
      <div class="binary-status" id="binary-${topic.replace(/\//g, "-")}">
        <div class="binary-icon">${ICONS.doorClosed}</div>
        <div class="binary-label">--</div>
      </div>
    </div>
  `;

  document.getElementById("dashboard").appendChild(card);
  cards[topic] = card;
}

// --- Card Updates ---

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

  // Update header icon too
  const card = cards[topic];
  if (card) {
    card.querySelector(".card-icon").innerHTML = icon;
    card.style.borderLeftColor = stateConfig.color;
  }
}

// --- Public API ---

export function createOrUpdateCard(topic, parsed, payload) {
  const sensorType = parsed.sensorType;
  if (!sensorType) return;

  const value = sensorType.parseValue(payload);

  if (!cards[topic]) {
    if (sensorType.renderer === "gauge") {
      createGaugeCard(topic, parsed);
    } else if (sensorType.renderer === "binary") {
      createBinaryCard(topic, parsed);
    }
  }

  if (sensorType.renderer === "gauge") {
    updateGaugeCard(topic, parsed, value);
  } else if (sensorType.renderer === "binary") {
    updateBinaryCard(topic, parsed, value);
  }
}
