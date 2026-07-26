// sensors.js — Catálogo de sensores, parser de topics y filtros

const catalogByTopic = new Map();
const IGNORED_TOPICS = ["/test", "test"];

function parseNumeric(payload) {
  try {
    const value = JSON.parse(payload);
    return typeof value === "object" ? parseFloat(value.value) : parseFloat(value);
  } catch {
    return parseFloat(payload);
  }
}

function buildSensorType(sensor) {
  if (sensor.kind === "door") {
    return {
      ...sensor,
      renderer: "timeline",
      states: {
        open: { label: "Abierta", color: "#e23e57" },
        closed: { label: "Cerrada", color: "#4ecca3" },
      },
      parseValue(payload) {
        const value = payload.toLowerCase().trim();
        return ["on", "open", "1"].includes(value) ? "open" : "closed";
      },
    };
  }

  return {
    ...sensor,
    renderer: sensor.card,
    parseValue: parseNumeric,
  };
}

export async function loadSensorCatalog() {
  const response = await fetch("/api/sensors");
  if (!response.ok) throw new Error(`No se pudo cargar el catálogo (${response.status})`);

  const sensors = await response.json();
  catalogByTopic.clear();
  for (const sensor of sensors) catalogByTopic.set(sensor.topic, sensor);
  return sensors;
}

export function shouldIgnore(topic) {
  return IGNORED_TOPICS.some(t => topic === t || topic.endsWith("/" + t));
}

export function parseTopic(topic) {
  const sensor = catalogByTopic.get(topic);
  if (!sensor) return { sensorType: null };

  return {
    location: sensor.location,
    measurement: sensor.measurement,
    locationLabel: sensor.location_label,
    sensorType: buildSensorType(sensor),
  };
}
