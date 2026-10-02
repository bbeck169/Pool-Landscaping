/**
 * Phase 4-landscape · Feb-2026 — Full-screen clock-in gate.
 *
 * Reused one source of truth: the ``useClockInStatus`` hook from
 * ``@/hooks/useClockInGate``.  ``isGated`` returns ``true`` ONLY when
 *   • user.role === "technician"
 *   • user.department ∈ {landscaping, landscape_tech, landscaper, both}
 *   • user is NOT clocked in
 * so admin / super_admin / manager / owner and pool-only techs
 * short-circuit through to ``children`` immediately.
 */
import React, { useState } from "react";
import { api } from "@/api";
import { useClockInStatus } from "@/hooks/useClockInGate";


export default function LandscapeTechClockInGate({ children }) {
  const { isGated, refresh } = useClockInStatus();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [geoDenied, setGeoDenied] = useState(null);

  if (!isGated) return children;

  async function handleClockIn() {
    setBusy(true);
    setError("");
    try {
      const coords = await new Promise((resolve) => {
        if (!navigator?.geolocation) {
          return resolve({ denied: true });
        }
        navigator.geolocation.getCurrentPosition(
          (pos) => resolve({
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy_m: pos.coords.accuracy,
            denied: false,
          }),
          () => resolve({ denied: true }),
          { enableHighAccuracy: false, timeout: 10000 },
        );
      });
      setGeoDenied(!!coords.denied);
      await api.post("/timeclock/punch", {
        punch_type: "in",
        source: "web",
        lat: coords.lat ?? null,
        lng: coords.lng ?? null,
        accuracy_m: coords.accuracy_m ?? null,
        geo_denied: !!coords.denied,
      });
      await refresh();
    } catch (e) {
      setError(e?.message || "Failed to clock in. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      data-testid="landscape-clock-gate"
      className="w-full flex items-center justify-center px-4"
      style={{ minHeight: "calc(100vh - 180px)" }}
    >
      <div
        className="rounded-2xl p-8 max-w-md w-full shadow-xl text-center"
        style={{ background: "#FFFFFF", border: "1px solid #E5E7EB" }}
      >
        <h2
          className="text-2xl font-bold mb-2"
          style={{ color: "#0F172A" }}
        >
          Clock in to start your day
        </h2>
        <p
          className="text-sm mb-6"
          style={{ color: "#334155" }}
        >
          You need to clock in before you can access the app.
        </p>
        {error ? (
          <div
            data-testid="landscape-clock-gate-error"
            className="text-xs mb-4 px-3 py-2 rounded-md"
            style={{
              background: "#FEF2F2",
              border: "1px solid #FECACA",
              color: "#B91C1C",
            }}
          >
            {error}
          </div>
        ) : null}
        {geoDenied !== null ? (
          <div
            data-testid="landscape-clock-gate-geo-status"
            className="text-xs mb-4"
            style={{ color: geoDenied ? "#B45309" : "#166534" }}
          >
            {geoDenied
              ? "GPS unavailable - punched without location."
              : "GPS captured."}
          </div>
        ) : null}
        <button
          type="button"
          onClick={handleClockIn}
          disabled={busy}
          data-testid="landscape-clock-gate-in-btn"
          className="w-full px-6 py-4 rounded-lg text-base font-bold"
          style={{
            background: busy ? "#86EFAC" : "#16A34A",
            color: "#FFFFFF",
            border: 0,
            cursor: busy ? "not-allowed" : "pointer",
          }}
        >
          {busy ? "Clocking in..." : "Clock In"}
        </button>
      </div>
    </div>
  );
}
