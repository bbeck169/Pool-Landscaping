/**
 * Phase K75 · Step B · Feb-2026 — quick-pin CRUD hook.
 *
 * Fetches ``/api/users/me/quick-pins`` once on mount, then
 * exposes:
 *   ``pins``           — server-persisted pin list (or the seeded
 *                        defaults for the role on first-run — see
 *                        ``defaultQuickPinsForRole`` for the seed
 *                        source of truth).
 *   ``setPins(next)``  — optimistically updates local state, then
 *                        PUTs. Rolls back + surfaces the error on
 *                        failure so the rail stays in sync with the
 *                        server.
 *   ``addPin``, ``removePin``, ``reorderPins`` — sugar helpers
 *                        composing on top of ``setPins``.
 *   ``loading``, ``saving``, ``error``, ``atCap``, ``cap``.
 *
 * Every returned pin is hydrated with the resolved lucide ``Icon``
 * component so consumers can render directly without another
 * ``resolveIcon`` call.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { defaultQuickPinsForRole, QUICK_PINS_CAP } from "@/nav/defaultQuickPins";
import { resolveIcon } from "@/nav/lucideIcons";


function _stripToShipShape(p) {
  return { to: p.to, label: p.label, iconKey: p.iconKey };
}
function _hydrate(list) {
  return (list || []).map((p) => ({
    ...p,
    Icon: resolveIcon(p.iconKey),
  }));
}


export function useQuickPins(role) {
  const [pins, _setPins] = useState(() => defaultQuickPinsForRole(role));
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [seeded, setSeeded] = useState(false); // true when running on defaults

  // Initial fetch.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await api.get("/users/me/quick-pins");
        if (cancelled) return;
        const arr = Array.isArray(res?.pins) ? res.pins : [];
        if (arr.length === 0) {
          _setPins(defaultQuickPinsForRole(role));
          setSeeded(true);
        } else {
          _setPins(_hydrate(arr));
          setSeeded(false);
        }
        setError(null);
      } catch (e) {
        if (cancelled) return;
        // Non-blocking — fall back to defaults so the rail keeps
        // rendering even if the endpoint is momentarily unhealthy.
        _setPins(defaultQuickPinsForRole(role));
        setSeeded(true);
        setError(e?.message || "quickpins_load_failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [role]);

  const persist = useCallback(async (next) => {
    setSaving(true);
    setError(null);
    const prev = pins;
    _setPins(_hydrate(next.map(_stripToShipShape)));
    setSeeded(false);
    try {
      const res = await api.put("/users/me/quick-pins", {
        pins: next.map(_stripToShipShape),
      });
      _setPins(_hydrate(res.pins || []));
      return { ok: true, pins: res.pins };
    } catch (e) {
      // Rollback optimistic update.
      _setPins(prev);
      const code = e?.data?.detail?.code || e?.detail?.code || "put_failed";
      setError(code);
      return { ok: false, code, error: e };
    } finally {
      setSaving(false);
    }
  }, [pins]);

  const addPin = useCallback((pin) => {
    if (pins.length >= QUICK_PINS_CAP) {
      return Promise.resolve({ ok: false, code: "pin_cap_exceeded" });
    }
    if (pins.some((p) => p.to === pin.to)) {
      return Promise.resolve({ ok: false, code: "duplicate_pin" });
    }
    return persist([...pins, pin]);
  }, [pins, persist]);

  const removePin = useCallback((to) => {
    return persist(pins.filter((p) => p.to !== to));
  }, [pins, persist]);

  const reorderPins = useCallback((nextOrder) => {
    // ``nextOrder`` = array of ``to`` values in the new order.
    const byTo = Object.fromEntries(pins.map((p) => [p.to, p]));
    const next = nextOrder.map((to) => byTo[to]).filter(Boolean);
    return persist(next);
  }, [pins, persist]);

  const setPins = useCallback((next) => persist(next), [persist]);

  const atCap = pins.length >= QUICK_PINS_CAP;
  const pinnedRoutes = useMemo(() => new Set(pins.map((p) => p.to)), [pins]);

  return {
    pins,
    setPins,
    addPin,
    removePin,
    reorderPins,
    loading,
    saving,
    error,
    seeded,
    atCap,
    cap: QUICK_PINS_CAP,
    pinnedRoutes,
  };
}
