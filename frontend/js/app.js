// app.js — WebSocket connection, message dispatch

import { loadSensorCatalog, shouldIgnore, parseTopic } from "./sensors.js";
import { createOrUpdateCard, setConnectionStatus } from "./ui.js";
import { initTimeRangeControl } from "./time-range.js";

let ws;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => setConnectionStatus(true);

  ws.onclose = () => {
    setConnectionStatus(false);
    setTimeout(connect, 3000);
  };

  ws.onmessage = (e) => {
    const { topic, payload, updated_at, source } = JSON.parse(e.data);
    if (shouldIgnore(topic)) return;

    const parsed = parseTopic(topic);
    if (!parsed.sensorType) return;

    const readingTime = updated_at || new Date().toISOString();
    const ageSeconds = Math.max(
      0,
      Math.floor((Date.now() - new Date(readingTime).getTime()) / 1000),
    );

    createOrUpdateCard(topic, parsed, payload, {
      updated_at: readingTime,
      source: source || "mqtt",
      age_seconds: ageSeconds,
      stale: ageSeconds > parsed.sensorType.stale_after_seconds,
    });
  };
}

export function sendCommand(topic, payload) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ topic, payload }));
  }
}

async function start() {
  initTimeRangeControl();
  try {
    const sensors = await loadSensorCatalog();
    for (const sensor of sensors) {
      if (!sensor.current) continue;
      createOrUpdateCard(
        sensor.topic,
        parseTopic(sensor.topic),
        sensor.current.payload,
        sensor.current,
      );
    }
  } catch (error) {
    console.error(error);
  }
  connect();
}

start();
