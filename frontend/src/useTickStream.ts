import { useEffect, useRef, useState } from "react";

import { WS_URL } from "./config";
import type { ConnectionStatus, TickRecord } from "./types";

const MAX_TICKS = 200; // enough for the chart's rolling window, mirrors backend's own history cap
const BASE_DELAY_MS = 500;
const MAX_DELAY_MS = 8000;
const LOST_AFTER_ATTEMPTS = 5; // still retries after this, just badges as "lost" rather than "reconnecting"

// Native WebSocket does not auto-reconnect on drop -- this hook is 9b's
// answer to that gap. Connect once on mount; any close (dropped connection,
// backend restart, refused first attempt) schedules a retry with capped
// exponential backoff, until the component unmounts.
export function useTickStream() {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [ticks, setTicks] = useState<TickRecord[]>([]);
  const attemptsRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const unmountedRef = useRef(false);

  useEffect(() => {
    unmountedRef.current = false;

    const connect = () => {
      const ws = new WebSocket(WS_URL);
      socketRef.current = ws;

      ws.onopen = () => {
        attemptsRef.current = 0;
        setStatus("open");
      };

      ws.onmessage = (event) => {
        const record = JSON.parse(event.data) as TickRecord;
        setTicks((prev) => [...prev.slice(-(MAX_TICKS - 1)), record]);
      };

      ws.onclose = () => {
        if (unmountedRef.current) return;
        attemptsRef.current += 1;
        setStatus(attemptsRef.current >= LOST_AFTER_ATTEMPTS ? "lost" : "reconnecting");
        const delay = Math.min(BASE_DELAY_MS * 2 ** (attemptsRef.current - 1), MAX_DELAY_MS);
        timerRef.current = setTimeout(connect, delay);
      };

      ws.onerror = (event) => {
        // React StrictMode's dev-only double-mount aborts a phantom first
        // connection while it's still CONNECTING -- expected noise, not a
        // real failure, so don't log it. onclose (fires right after,
        // either way) owns all reconnect logic.
        if (!unmountedRef.current) console.error("tick stream websocket error", event);
      };
    };

    connect();

    return () => {
      unmountedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, []);

  return { status, ticks, latest: ticks.length > 0 ? ticks[ticks.length - 1] : null };
}
