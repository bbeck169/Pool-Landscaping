/**
 * Feb-2026 · C3 · REI countdown hook.
 *
 * Consumed by ``ChemicalApplicationsList`` (list-page badges) and
 * planned for the C5 Customer Detail chemical-applications tab.
 * Ticks every 60 s so a locked row flips to unlocked without a
 * page refresh when its ``rei_unlock_at`` timestamp passes.
 *
 * Semantics:
 *   - ``isLocked``       → true while ``rei_unlock_at`` is in the future.
 *   - ``hoursRemaining`` → floor of remaining hours (0 when unlocked).
 *   - ``minutesRemaining`` → floor of remaining whole minutes MOD 60
 *                             so callers can format ``4h 12m``.
 *   - ``msRemaining``    → raw ms for callers that need finer granularity.
 *
 * Null / empty / malformed ``reiUnlockAtIso`` → returns the unlocked
 * shape without scheduling a timer.  Callers can safely pass legacy
 * rows without a REI value.
 */
import { useEffect, useMemo, useState } from "react";


function _parseIso(iso) {
  if (!iso || typeof iso !== "string") return NaN;
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : NaN;
}


function _snapshot(unlockMs, nowMs) {
  if (!Number.isFinite(unlockMs)) {
    return { isLocked: false, hoursRemaining: 0, minutesRemaining: 0, msRemaining: 0 };
  }
  const delta = unlockMs - nowMs;
  if (delta <= 0) {
    return { isLocked: false, hoursRemaining: 0, minutesRemaining: 0, msRemaining: 0 };
  }
  const totalMinutes = Math.floor(delta / 60000);
  return {
    isLocked: true,
    hoursRemaining: Math.floor(totalMinutes / 60),
    minutesRemaining: totalMinutes % 60,
    msRemaining: delta,
  };
}


export function useReiCountdown(reiUnlockAtIso, tickMs = 60000) {
  const unlockMs = useMemo(() => _parseIso(reiUnlockAtIso), [reiUnlockAtIso]);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    // No timer required for legacy / unlocked rows — the initial
    // snapshot is already correct and won't change.
    if (!Number.isFinite(unlockMs)) return undefined;
    // Set an interval regardless of locked/unlocked so a row that
    // *starts* the render already-unlocked doesn't spin up timers,
    // but a locked row transitions to unlocked exactly on the next
    // tick after its unlock timestamp passes.
    const id = setInterval(() => setNow(Date.now()), tickMs);
    return () => clearInterval(id);
  }, [unlockMs, tickMs]);

  return useMemo(() => _snapshot(unlockMs, now), [unlockMs, now]);
}


export default useReiCountdown;
