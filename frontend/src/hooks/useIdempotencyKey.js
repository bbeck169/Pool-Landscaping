/**
 * Phase P45 · Feb-2026 — Client-side idempotency-key generator.
 *
 * Belt to the atomic-stamp gate in
 * ``backend/services/service_report_submit_gate.py``.  The backend
 * gate catches SERVER-side races (concurrent tech-submit +
 * admin-status-flip); this hook catches CLIENT-side double POSTs
 * (browser double-clicks, network-retry loops on flaky links).
 *
 * Contract:
 *   • Generates a stable ``crypto.randomUUID()`` on mount.
 *   • Same key persists across the entire form session — including
 *     across submit retries after a network error.  A network flake
 *     followed by a retry MUST reuse the same key so the server
 *     recognises the second POST as a replay of the first.
 *   • ``regenerate()`` mints a fresh UUID — called by the consumer
 *     on SUCCESS so if the user reopens the form (edit-and-resubmit
 *     scenario) the next submit is treated as a NEW action.
 *   • Fallback for jsdom / older browsers where ``crypto.randomUUID``
 *     is unavailable: build a v4-shaped UUID from ``getRandomValues``.
 *     No external ``uuid`` npm dep — the format is not cryptographically
 *     load-bearing (server-side we hash + tenant-scope it anyway).
 */
import { useCallback, useMemo, useState } from "react";

function _mintUuid() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // v4 fallback via getRandomValues.
  if (typeof crypto !== "undefined" && typeof crypto.getRandomValues === "function") {
    const buf = new Uint8Array(16);
    crypto.getRandomValues(buf);
    buf[6] = (buf[6] & 0x0f) | 0x40; // version 4
    buf[8] = (buf[8] & 0x3f) | 0x80; // variant 10
    const hex = Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  // Last-resort (jsdom without crypto.getRandomValues).  Non-random
  // but shape-valid — the header still lets the server dedupe within
  // one JS process.
  const rnd = () => Math.random().toString(16).slice(2, 10).padStart(8, "0");
  return `${rnd()}-${rnd().slice(0, 4)}-4${rnd().slice(0, 3)}-a${rnd().slice(0, 3)}-${rnd()}${rnd().slice(0, 4)}`;
}

export function useIdempotencyKey() {
  const [key, setKey] = useState(() => _mintUuid());
  const regenerate = useCallback(() => setKey(_mintUuid()), []);
  // ``headers`` returns the exact header object callers should pass
  // as ``options.headers`` to the ``api.request(...)`` wrapper.
  const headers = useMemo(() => ({ "X-Idempotency-Key": key }), [key]);
  return { key, headers, regenerate };
}

export default useIdempotencyKey;
