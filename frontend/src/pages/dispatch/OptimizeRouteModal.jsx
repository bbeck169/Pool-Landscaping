// Phase 3 · Feb-2026 — Optimize Route modal for Dispatch Board.
//
// Fetches a nearest-neighbor preview from
//   POST /api/dispatch/route/optimize
// and, on confirmation, persists the new order via
//   POST /api/dispatch/route/apply
//
// Side-by-side layout: current hand-order (left) vs proposed (right),
// with per-leg + cumulative distance and a savings figure. Skipped
// jobs (no coords) surface at the bottom so the dispatcher can see
// what won't be reordered.
import React from "react";
import { toast } from "sonner";
import { X, Route as RouteIcon, ChevronRight, ArrowRight } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function _fmtKm(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${Number(n).toFixed(2)} km`;
}

export default function OptimizeRouteModal({ open, onClose, onApplied,
                                                techUserId, techName, day }) {
  const [loading, setLoading] = React.useState(true);
  const [applying, setApplying] = React.useState(false);
  const [preview, setPreview] = React.useState(null);
  const [error, setError] = React.useState(null);

  const load = React.useCallback(async () => {
    if (!techUserId || !day) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.post("/dispatch/route/optimize",
                                    { tech_user_id: techUserId, route_date: day });
      setPreview(res);
    } catch (e) {
      setError(e?.body?.detail || e?.message || "Failed to compute route");
    } finally {
      setLoading(false);
    }
  }, [techUserId, day]);

  React.useEffect(() => { if (open) load(); }, [open, load]);

  if (!open) return null;

  const apply = async () => {
    if (!preview) return;
    setApplying(true);
    try {
      const ids = (preview.ordered_jobs || []).map((j) => j.job_id);
      const r = await api.post("/dispatch/route/apply",
                                  { tech_user_id: techUserId, route_date: day,
                                    ordered_job_ids: ids });
      toast.success(`${r.updated} stops reordered`);
      onApplied?.();
      onClose?.();
    } catch (e) {
      toast.error(e?.body?.detail || e?.message || "Apply failed");
    } finally {
      setApplying(false);
    }
  };

  const ordered = preview?.ordered_jobs || [];
  const skipped = preview?.skipped || [];

  return (
    <div data-testid="optimize-route-modal"
          role="dialog"
          style={{ position: "fixed", inset: 0, zIndex: 5000,
                    background: "rgba(15,23,42,0.6)",
                    display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}>
      <div style={{
        background: colors.surface || "#FFFFFF", borderRadius: 14,
        width: "min(880px, 96vw)", maxHeight: "90vh", overflow: "auto",
        padding: 24, boxShadow: "0 20px 48px rgba(15,23,42,0.24)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "flex-start", marginBottom: 16 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <RouteIcon size={18} color={colors.brand || "#0284C7"} />
              <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
                Optimize route
              </h2>
            </div>
            <div style={{ fontSize: 13, color: colors.muted, marginTop: 4 }}>
              {techName || techUserId} · {day}
            </div>
          </div>
          <button data-testid="optimize-route-close" onClick={onClose}
                   aria-label="Close"
                   style={{ background: "transparent", border: "none",
                             cursor: "pointer", color: colors.muted }}>
            <X size={18} />
          </button>
        </div>

        {loading && (
          <div data-testid="optimize-route-loading"
                style={{ padding: 40, textAlign: "center", color: colors.muted }}>
            Computing nearest-neighbor tour…
          </div>
        )}

        {error && (
          <div data-testid="optimize-route-error"
                style={{ padding: 14, background: "#FEF2F2",
                          border: "1px solid #FECACA", borderRadius: 10,
                          color: "#B91C1C", fontSize: 13 }}>{error}</div>
        )}

        {!loading && preview && (
          <>
            {/* Totals strip */}
            <div style={{ display: "flex", alignItems: "center",
                            gap: 16, flexWrap: "wrap", marginBottom: 16 }}>
              <div style={{ flex: 1, minWidth: 160, padding: 12,
                              background: colors.surfaceMuted || "#F1F5F9",
                              borderRadius: 10 }}>
                <div style={{ fontSize: 11, color: colors.muted,
                                textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Current
                </div>
                <div data-testid="optimize-route-hand-distance"
                      style={{ fontSize: 20, fontWeight: 700 }}>
                  {_fmtKm(preview.hand_ordered_distance_km)}
                </div>
              </div>
              <ArrowRight size={20} color={colors.muted} />
              <div style={{ flex: 1, minWidth: 160, padding: 12,
                              background: "#DBEAFE", borderRadius: 10 }}>
                <div style={{ fontSize: 11, color: "#1D4ED8",
                                textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Proposed
                </div>
                <div data-testid="optimize-route-new-distance"
                      style={{ fontSize: 20, fontWeight: 700, color: "#1D4ED8" }}>
                  {_fmtKm(preview.total_distance_km)}
                </div>
              </div>
              <div style={{ flex: 1, minWidth: 160, padding: 12,
                              background: preview.savings_km >= 0 ? "#DCFCE7" : "#FEF2F2",
                              borderRadius: 10 }}>
                <div style={{ fontSize: 11, color: preview.savings_km >= 0 ? "#166534" : "#B91C1C",
                                textTransform: "uppercase", letterSpacing: 0.5 }}>
                  Savings
                </div>
                <div data-testid="optimize-route-savings"
                      style={{ fontSize: 20, fontWeight: 700,
                                color: preview.savings_km >= 0 ? "#166534" : "#B91C1C" }}>
                  {_fmtKm(preview.savings_km)}
                </div>
              </div>
            </div>

            {/* Origin line */}
            <div style={{ fontSize: 12, color: colors.muted, marginBottom: 12 }}>
              Origin: <b>{preview.origin.source}</b>
              {" · "}
              {preview.origin.lat.toFixed(4)}, {preview.origin.lon.toFixed(4)}
            </div>

            {/* Ordered list */}
            <div data-testid="optimize-route-ordered-list"
                  style={{ border: `1px solid ${colors.border || "#E2E8F0"}`,
                            borderRadius: 10, overflow: "hidden", marginBottom: 12 }}>
              <div style={{ padding: "10px 14px",
                              background: colors.surfaceMuted || "#F8FAFC",
                              fontSize: 12, fontWeight: 600, color: colors.muted,
                              textTransform: "uppercase", letterSpacing: 0.5 }}>
                Proposed order
              </div>
              {ordered.map((j) => (
                <div key={j.job_id}
                      data-testid={`optimize-route-stop-${j.sequence}`}
                      style={{ display: "flex", alignItems: "center", gap: 12,
                                padding: "10px 14px",
                                borderTop: `1px solid ${colors.border || "#E2E8F0"}` }}>
                  <div style={{ width: 24, height: 24, borderRadius: 12,
                                  background: "#0284C7", color: "#FFFFFF",
                                  display: "flex", alignItems: "center",
                                  justifyContent: "center", fontSize: 12, fontWeight: 700 }}>
                    {j.sequence + 1}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600 }}>
                      {j.address || j.job_id}
                    </div>
                    <div style={{ fontSize: 11, color: colors.muted }}>
                      Leg {_fmtKm(j.leg_distance_km)} · Cum {_fmtKm(j.cumulative_distance_km)}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {skipped.length > 0 && (
              <div data-testid="optimize-route-skipped"
                    style={{ background: "#FEF3C7", border: "1px solid #FDE68A",
                              borderRadius: 10, padding: 12, marginBottom: 12,
                              fontSize: 12, color: "#92400E" }}>
                <b>{skipped.length}</b> job(s) skipped (no coords available):
                <ul style={{ margin: "6px 0 0 18px" }}>
                  {skipped.map((s) => (
                    <li key={s.job_id}>{s.job_id} — {s.reason}</li>
                  ))}
                </ul>
              </div>
            )}

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button data-testid="optimize-route-cancel" onClick={onClose}
                       style={{ padding: "10px 16px", background: "transparent",
                                 color: colors.muted, border: `1px solid ${colors.border || "#E2E8F0"}`,
                                 borderRadius: 10, cursor: "pointer",
                                 fontSize: 13, fontWeight: 600 }}>
                Cancel
              </button>
              <button data-testid="optimize-route-apply" onClick={apply}
                       disabled={applying || ordered.length === 0}
                       style={{ padding: "10px 20px",
                                 background: applying ? "#94A3B8" : (colors.brand || "#0284C7"),
                                 color: "#FFFFFF", border: "none", borderRadius: 10,
                                 cursor: applying ? "wait" : "pointer",
                                 fontSize: 13, fontWeight: 600,
                                 display: "flex", alignItems: "center", gap: 6 }}>
                {applying ? "Applying…" : <>Apply new order <ChevronRight size={14} /></>}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
