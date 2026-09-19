import type { NotificationState } from "@/components/door-alert-control";
import { useEffect, useMemo, useState } from "react";
import { fetchSensors } from "@/lib/api";
import type { ConnectionChain, PiAvailability, Sensor } from "@/types/sensors";

interface SensorMessage {
  type?: "sensor";
  topic: string;
  payload: string;
  updated_at?: string;
  source?: string;
}

interface LinkMessage {
  type: "link";
  mqtt_connected: boolean;
  bridge_connected: boolean | null;
  pi_availability: PiAvailability | null;
}

type SocketMessage = SensorMessage | LinkMessage | ({ type: "notification_rule" } & NotificationState);

// Ages are recomputed from the real reading timestamp on this tick, so a dead
// sensor keeps ageing while the tab is open.
const AGE_TICK_MS = 30_000;

const DISCONNECTED: ConnectionChain = {
  socket: "disconnected",
  mqttConnected: null,
  bridgeConnected: null,
  piAvailability: null,
};

function withAge(sensor: Sensor, now: number): Sensor {
  if (!sensor.current) return sensor;
  const readAt = new Date(sensor.current.updated_at).getTime();
  if (!Number.isFinite(readAt)) return sensor;
  const age = Math.max(0, Math.round((now - readAt) / 1000));
  return {
    ...sensor,
    current: { ...sensor.current, age_seconds: age, stale: age > sensor.stale_after_seconds },
  };
}

export function useDashboardData() {
  const [notifications, setNotifications] = useState<NotificationState | null>(null);
  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chain, setChain] = useState<ConnectionChain>({ ...DISCONNECTED, socket: "connecting" });
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const controller = new AbortController();
    fetchSensors(controller.signal)
      .then(setSensors)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to load sensors");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), AGE_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let retry: number | undefined;
    let socket: WebSocket | undefined;
    let stopped = false;

    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${location.host}/ws`);
      socket.onopen = () => setChain((current) => ({ ...current, socket: "connected" }));
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as SocketMessage;
        if (message.type === "notification_rule") {
          setNotifications(message);
          return;
        }
        if (message.type === "link") {
          setChain((current) => ({
            ...current,
            mqttConnected: message.mqtt_connected,
            bridgeConnected: message.bridge_connected,
            piAvailability: message.pi_availability,
          }));
          return;
        }
        // The reading's own timestamp, never "now": a reconnect must not make a
        // dead sensor look fresh. Age and staleness are derived from it below.
        setSensors((current) => current.map((sensor) => sensor.topic === message.topic ? {
          ...sensor,
          current: {
            payload: message.payload,
            updated_at: message.updated_at ?? new Date().toISOString(),
            source: message.source ?? "mqtt",
            age_seconds: 0,
            stale: false,
          },
        } : sensor));
        setNow(Date.now());
      };
      socket.onclose = () => {
        // Everything beyond our own socket becomes unknown: the broker and the
        // bridge were only observable through it. A closed socket reads as
        // disconnected even though we retry — an eternal "connecting…" would be
        // the same lie the old binary indicator told.
        setChain(DISCONNECTED);
        if (!stopped) retry = window.setTimeout(connect, 3000);
      };
    };
    connect();
    return () => {
      stopped = true;
      if (retry) clearTimeout(retry);
      socket?.close();
    };
  }, []);

  const aged = useMemo(() => sensors.map((sensor) => withAge(sensor, now)), [sensors, now]);

  return { sensors: aged, loading, error, chain, notifications, setNotifications };
}
