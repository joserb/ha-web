import { useEffect, useState } from "react";
import { fetchSensors } from "@/lib/api";
import type { Sensor } from "@/types/sensors";

interface SocketMessage {
  topic: string;
  payload: string;
  updated_at?: string;
  source?: string;
}

export function useDashboardData() {
  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

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
    let retry: number | undefined;
    let socket: WebSocket | undefined;
    let stopped = false;

    const connect = () => {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(`${protocol}//${location.host}/ws`);
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as SocketMessage;
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
      };
      socket.onclose = () => {
        setConnected(false);
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

  return { sensors, loading, error, connected };
}
