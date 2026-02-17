// app.js — WebSocket connection, message dispatch

import { shouldIgnore, parseTopic } from "./sensors.js";
import { createOrUpdateCard, setConnectionStatus } from "./ui.js";

let ws;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);

  ws.onopen = () => setConnectionStatus(true);

  ws.onclose = () => {
    setConnectionStatus(false);
    setTimeout(connect, 3000);
  };

  ws.onmessage = (e) => {
    const { topic, payload } = JSON.parse(e.data);
    if (shouldIgnore(topic)) return;

    const parsed = parseTopic(topic);
    if (!parsed.sensorType) return;

    createOrUpdateCard(topic, parsed, payload);
  };
}

export function sendCommand(topic, payload) {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ topic, payload }));
  }
}

connect();
