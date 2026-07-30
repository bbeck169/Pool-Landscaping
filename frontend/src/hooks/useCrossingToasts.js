// Phase G5a · Feb-2026 — Dispatch board crossing-toast helper.
//
// Given a stream of `recent_crossings` from GET /api/gps/live-positions,
// fire a Sonner toast for each event whose id we haven't seen before.
// We persist the last 200 seen ids in localStorage so a page reload
// during a 60s window doesn't re-toast the same crossing.
import React from "react";
import { toast } from "sonner";

const STORAGE_KEY = "dispatch.seenCrossings";
const MAX_REMEMBERED = 200;

function loadSeen() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return new Set(Array.isArray(parsed) ? parsed : []);
  } catch { return new Set(); }
}

function saveSeen(set) {
  try {
    const arr = Array.from(set).slice(-MAX_REMEMBERED);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
  } catch { /* non-fatal */ }
}

export default function useCrossingToasts(recentCrossings, { enabled = true } = {}) {
  const seenRef = React.useRef(null);
  if (seenRef.current === null) seenRef.current = loadSeen();

  React.useEffect(() => {
    if (!enabled) return;
    if (!Array.isArray(recentCrossings) || recentCrossings.length === 0) return;
    const seen = seenRef.current;
    let anyNew = false;
    // Iterate oldest→newest so toasts stack chronologically.
    const chronological = [...recentCrossings].sort(
      (a, b) => String(a.detected_at || "").localeCompare(b.detected_at || "")
    );
    for (const c of chronological) {
      if (!c || !c.id || seen.has(c.id)) continue;
      seen.add(c.id);
      anyNew = true;
      const who = c.user_name || "Technician";
      const where = c.geofence_name || "geofence";
      const verb = c.crossing === "enter" ? "entered" : "exited";
      const description = `${verb} ${where}`;
      const testId = `dispatch-crossing-toast-${c.id}`;
      try {
        if (c.crossing === "enter") {
          toast.success(who, {
            description,
            duration: 6000,
            id: `crossing-${c.id}`,
            classNames: { toast: testId },
          });
        } else {
          toast.warning(who, {
            description,
            duration: 6000,
            id: `crossing-${c.id}`,
            classNames: { toast: testId },
          });
        }
      } catch {
        // Sonner not mounted (e.g., under Vitest) — silent.
      }
    }
    if (anyNew) saveSeen(seen);
  }, [recentCrossings, enabled]);
}
