// Phase G5c · Feb-2026 — Shared route-data hook.
//
// Both `RouteMapPanel` (G3) and `RouteReplayPanel` (G5c) render off the
// same `/api/gps/route` payload. This hook dedupes by (techId, day) so
// we only fetch once per combo per mount tree.
//
// We keep it deliberately small — no react-query, no context.  A tiny
// in-flight promise + last-value memo covers the two-consumer case.
import React from "react";
import { api } from "@/api";

const _cache = new Map(); // key = `${techId}::${day}` -> { promise, data }

// Test-only helper — clears the in-memory dedupe cache between tests.
export function _resetCacheForTest() { _cache.clear(); }

function _key(techId, day) { return `${techId || ""}::${day || ""}`; }

async function _fetch(techId, day, extra) {
  const from = `${day}T00:00:00Z`;
  const to   = `${day}T23:59:59Z`;
  const qs = new URLSearchParams({ user_id: techId, from, to });
  if (extra?.q_customer) qs.set("q_customer", extra.q_customer);
  if (extra?.q_address)  qs.set("q_address",  extra.q_address);
  return api.get(`/gps/route?${qs.toString()}`);
}

export default function useGpsRoute({ techId, day,
                                       q_customer = "",
                                       q_address = "" } = {}) {
  const [route, setRoute] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    if (!techId || !day) {
      setRoute(null); setLoading(false); setError(null);
      return () => { cancelled = true; };
    }
    setLoading(true); setError(null);
    // Cache key includes filters so a filtered fetch doesn't overwrite
    // the unfiltered one (matters for the replay panel which always
    // wants the unfiltered timeline).
    const k = `${_key(techId, day)}::${q_customer}::${q_address}`;
    let entry = _cache.get(k);
    if (!entry) {
      const p = _fetch(techId, day, { q_customer, q_address })
        .catch((e) => { throw e; });
      entry = { promise: p, data: null };
      _cache.set(k, entry);
      p.then((data) => { entry.data = data; })
       .catch(() => { _cache.delete(k); });
    }
    entry.promise
      .then((data) => {
        if (cancelled) return;
        setRoute(data); setLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e?.message || "failed"); setLoading(false);
      });
    return () => { cancelled = true; };
  }, [techId, day, q_customer, q_address]);

  const invalidate = React.useCallback(() => {
    for (const k of Array.from(_cache.keys())) {
      if (k.startsWith(_key(techId, day))) _cache.delete(k);
    }
  }, [techId, day]);

  return { route, loading, error, invalidate };
}
