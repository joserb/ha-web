// sensors.js — Registro de tipos de sensor, parser de topics, filtros

export const SENSOR_TYPES = {
  temp: {
    label: "Temperatura",
    unit: "°C",
    renderer: "gauge",
    gaugeOpts: {
      min: -5,
      max: 50,
      zones: [
        { min: -5, max: 10, color: "#3498db" },
        { min: 10, max: 18, color: "#2ecc71" },
        { min: 18, max: 24, color: "#4ecca3" },
        { min: 24, max: 30, color: "#f39c12" },
        { min: 30, max: 50, color: "#e23e57" },
      ],
    },
    parseValue(payload) {
      try {
        const obj = JSON.parse(payload);
        return typeof obj === "object" ? parseFloat(obj.value) : parseFloat(obj);
      } catch {
        return parseFloat(payload);
      }
    },
  },

  door: {
    label: "Puerta",
    unit: "",
    renderer: "binary",
    states: {
      open:   { label: "Abierta",  color: "#e23e57" },
      closed: { label: "Cerrada",  color: "#4ecca3" },
    },
    parseValue(payload) {
      const val = payload.toLowerCase().trim();
      return (val === "on" || val === "open" || val === "1") ? "open" : "closed";
    },
  },
};

export const LOCATION_LABELS = {
  "home/salon":      "Salón",
  "home/terraza":    "Terraza",
  "home/habitacion": "Habitación",
  "home/estudio":    "Estudio",
  "home/entrada":    "Entrada",
};

const IGNORED_TOPICS = ["/test", "test"];

export function shouldIgnore(topic) {
  return IGNORED_TOPICS.some(t => topic === t || topic.endsWith("/" + t));
}

export function parseTopic(topic) {
  const lastSlash = topic.lastIndexOf("/");
  const location = topic.substring(0, lastSlash);
  const measurement = topic.substring(lastSlash + 1);
  return {
    location,
    measurement,
    locationLabel: LOCATION_LABELS[location] || location,
    sensorType: SENSOR_TYPES[measurement] || null,
  };
}
