/**
 * useTenantLocation — Feb-2026.
 *
 * Deduplicated hook for the tenant's HQ geocode. All consumers on
 * the same page (weather widget + JobRainFlag badges on every job
 * card) share a single in-flight request and a single cached
 * response. If the tenant hasn't set an HQ yet, returns ``null``
 * and callers should fall back to their own default.
 */
import React from "react";
import { api } from "@/api";

let _cache = null;      // { lat, lon } | null
let _inflight = null;   // Promise
const _subs = new Set();

async function _fetch() {
  if (_inflight) return _inflight;
  _inflight = (async () => {
    try {
      const r = await api.get("/tenants/mine/location");
      if (r && typeof r.hq_lat === "number" && typeof r.hq_lng === "number") {
        _cache = { lat: r.hq_lat, lon: r.hq_lng };
      } else {
        _cache = null;
      }
    } catch {
      _cache = null;
    }
    _inflight = null;
    _subs.forEach((s) => s(_cache));
    return _cache;
  })();
  return _inflight;
}

/** Force the module-level cache back to unresolved state. Only
 *  used by the admin Settings save flow so a fresh geocode is
 *  picked up without a full page reload. */
export function invalidateTenantLocation() {
  _cache = null;
  _fetch();
}

export default function useTenantLocation({ enabled = true } = {}) {
  const [coords, setCoords] = React.useState(_cache);
  React.useEffect(() => {
    if (!enabled) return undefined;
    _subs.add(setCoords);
    if (_cache) setCoords(_cache);
    else _fetch();
    return () => { _subs.delete(setCoords); };
  }, [enabled]);
  return coords;
}
