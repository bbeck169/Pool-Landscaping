import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";
import { TOKEN_KEY } from "@/api";

/**
 * Phase 15A — Realtime notification socket.
 *
 * Attempts WS → falls back to SSE → falls back to poll (30s).
 * Exposes { connected, transport, lastMessage, subscribe(type, cb) }.
 */
const RealtimeCtx = createContext(null);

const BASE = process.env.REACT_APP_BACKEND_URL || "";
const WS_BASE = BASE.replace(/^http/, "ws");

export function useRealtime() {
  const ctx = useContext(RealtimeCtx);
  if (!ctx) return { connected: false, transport: null, lastMessage: null, subscribe: () => () => {} };
  return ctx;
}

export function RealtimeProvider({ children, enabled = true }) {
  const [connected, setConnected] = useState(false);
  const [transport, setTransport] = useState(null); // "ws" | "sse" | "poll" | null
  const [lastMessage, setLastMessage] = useState(null);

  const listenersRef = useRef(new Map()); // type -> Set(cb)
  const socketRef = useRef(null);
  const evtSourceRef = useRef(null);
  const pollTimerRef = useRef(null);
  const attemptRef = useRef(0);
  const closedRef = useRef(false);

  const dispatch = useCallback((msg) => {
    setLastMessage(msg);
    const t = msg?.type || "notification";
    const all = listenersRef.current.get("*");
    if (all) all.forEach((cb) => { try { cb(msg); } catch {} });
    const typed = listenersRef.current.get(t);
    if (typed) typed.forEach((cb) => { try { cb(msg); } catch {} });
  }, []);

  const subscribe = useCallback((type, cb) => {
    const key = type || "*";
    const set = listenersRef.current.get(key) || new Set();
    set.add(cb);
    listenersRef.current.set(key, set);
    return () => set.delete(cb);
  }, []);

  const teardown = useCallback(() => {
    if (socketRef.current) {
      try { socketRef.current.close(); } catch {}
      socketRef.current = null;
    }
    if (evtSourceRef.current) {
      try { evtSourceRef.current.close(); } catch {}
      evtSourceRef.current = null;
    }
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    teardown();
    setTransport("poll");
    setConnected(true);
    const tick = async () => {
      const token = localStorage.getItem(TOKEN_KEY);
      if (!token) return;
      try {
        const r = await fetch(`${BASE}/api/notifications`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!r.ok) return;
        const rows = await r.json();
        // Emit each new notification (client dedupes by id).
        rows.slice(0, 20).forEach((n) => dispatch({
          type: "notification",
          id: n.id,
          payload: n,
          created_at: n.created_at,
        }));
      } catch {}
    };
    tick();
    pollTimerRef.current = setInterval(tick, 30000);
  }, [dispatch, teardown]);

  const startSSE = useCallback((token) => {
    teardown();
    try {
      const es = new EventSource(`${BASE}/api/sse/notifications?token=${encodeURIComponent(token)}`);
      evtSourceRef.current = es;
      es.onopen = () => { setConnected(true); setTransport("sse"); attemptRef.current = 0; };
      es.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          dispatch(msg);
        } catch {}
      };
      es.onerror = () => {
        es.close();
        evtSourceRef.current = null;
        setConnected(false);
        if (!closedRef.current) startPolling();
      };
    } catch {
      startPolling();
    }
  }, [dispatch, startPolling, teardown]);

  const startWS = useCallback((token) => {
    teardown();
    try {
      const ws = new WebSocket(`${WS_BASE}/api/ws/notifications?token=${encodeURIComponent(token)}`);
      socketRef.current = ws;
      const openTimer = setTimeout(() => {
        // if not opened within 5s treat as failure
        if (ws.readyState !== WebSocket.OPEN) {
          try { ws.close(); } catch {}
        }
      }, 5000);
      ws.onopen = () => {
        clearTimeout(openTimer);
        setConnected(true); setTransport("ws"); attemptRef.current = 0;
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          dispatch(msg);
        } catch {}
      };
      ws.onclose = () => {
        clearTimeout(openTimer);
        setConnected(false);
        socketRef.current = null;
        if (closedRef.current) return;
        // Reconnect logic with exponential backoff, cap at 10 attempts then fallback.
        attemptRef.current += 1;
        if (attemptRef.current > 10) {
          startSSE(token);
          return;
        }
        const delay = Math.min(30000, 1000 * Math.pow(2, attemptRef.current - 1));
        setTimeout(() => {
          if (!closedRef.current) startWS(token);
        }, delay);
      };
      ws.onerror = () => {
        // let onclose handle reconnect
      };
    } catch {
      startSSE(token);
    }
  }, [dispatch, startSSE, teardown]);

  useEffect(() => {
    if (!enabled) return;
    closedRef.current = false;
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) return;
    startWS(token);
    return () => {
      closedRef.current = true;
      teardown();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  const value = { connected, transport, lastMessage, subscribe };
  return <RealtimeCtx.Provider value={value}>{children}</RealtimeCtx.Provider>;
}
