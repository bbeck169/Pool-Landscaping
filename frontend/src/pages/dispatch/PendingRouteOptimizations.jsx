// Feb-2026 · Optimize Route (sub-phase C) — dispatcher board pending section.
//
// Renders a compact card at the top of the dispatch board listing all
// pending tech-suggested route optimizations for the tenant. Auto-hides
// when the pending count is zero. Non-admins never see this card (belt-
// and-suspenders vs the backend admin gate on GET /pending).
//
// Deep-link support:
//   The NotificationBell writes each row's ``href`` to
//   ``/dispatch?optimize={request_id}``. On mount we read that query
//   param and, if it matches a pending row, auto-open the modal.
//
// Reused:
//   • useAuth (@/auth)     — admin role gate
//   • api (@/api)          — GET /jobs/route-optimization/pending
//   • toast (sonner)       — success/error surfaced by the modal
//   • RouteOptimizationApprovalModal — the actual approval UI
import React from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Route as RouteIcon, ChevronRight } from "lucide-react";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import RouteOptimizationApprovalModal from "@/pages/dispatch/RouteOptimizationApprovalModal";

function _isAdmin(role) {
  const r = (role || "").toLowerCase();
  return r === "admin" || r === "super_admin";
}

export default function PendingRouteOptimizations() {
  const { user } = useAuth();
  const isAdmin = _isAdmin(user?.role);
  const location = useLocation();
  const nav = useNavigate();

  const [rows, setRows] = React.useState([]);
  const [selected, setSelected] = React.useState(null);

  const load = React.useCallback(async () => {
    if (!isAdmin) return;
    try {
      const res = await api.get("/jobs/route-optimization/pending");
      setRows(Array.isArray(res?.pending) ? res.pending : []);
    } catch {
      setRows([]);
    }
  }, [isAdmin]);

  React.useEffect(() => { load(); }, [load]);

  // Poll every 30 s so a dispatcher watching this page sees new suggestions
  // land without needing a manual refresh.
  React.useEffect(() => {
    if (!isAdmin) return;
    const t = setInterval(load, 30_000);
    return () => clearInterval(t);
  }, [isAdmin, load]);

  // Deep-link handler — ``/dispatch?optimize={id}`` auto-opens the modal.
  React.useEffect(() => {
    if (!isAdmin) return;
    const q = new URLSearchParams(location.search);
    const rid = q.get("optimize");
    if (!rid) return;
    const hit = rows.find((r) => r.id === rid);
    if (hit) setSelected(hit);
  }, [isAdmin, location.search, rows]);

  const onResolved = React.useCallback(() => {
    // Drop the resolved row optimistically so the card refreshes cleanly.
    setRows((prev) => prev.filter((r) => r.id !== selected?.id));
    setSelected(null);
    // Strip the ``?optimize=...`` param so a reload doesn't re-open the modal.
    if (location.search.includes("optimize=")) {
      nav(location.pathname, { replace: true });
    }
    // Kick a fresh fetch to sync with backend state (approve may have created
    // an ``applied`` row that isn't pending — refetch nukes any drift).
    load();
  }, [selected, location, nav, load]);

  if (!isAdmin) return null;
  if (rows.length === 0) return null;

  return (
    <>
      <div
        className="rounded-lg border p-3 mb-3"
        style={{
          borderColor: colors.brand,
          backgroundColor: "#EFF6FF",
        }}
        data-testid="pending-route-optimizations-card"
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <RouteIcon size={16} style={{ color: colors.brand }} />
            <span className="text-sm font-bold" style={{ color: colors.onSurface }}>
              Pending route optimizations
            </span>
            <span
              className="text-xs px-2 py-0.5 rounded-full font-bold"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="pending-route-optimizations-count"
            >
              {rows.length}
            </span>
          </div>
        </div>
        <ul className="mt-2 divide-y" style={{ borderColor: colors.border }}>
          {rows.map((r) => (
            <li
              key={r.id}
              className="flex items-center justify-between py-2"
              data-testid={`pending-route-optimizations-row-${r.id}`}
            >
              <div className="min-w-0 flex-1">
                <div
                  className="text-sm font-semibold truncate"
                  style={{ color: colors.onSurface }}
                >
                  {r.tech_name || r.tech_user_id}
                  <span className="ml-2 text-xs" style={{ color: colors.muted }}>
                    · {r.route_date}
                  </span>
                </div>
                <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                  {(r.stops_affected ?? 0)} stops · {Number(r.estimated_miles_saved ?? 0).toFixed(1)} mi
                  · {Math.round(Number(r.estimated_minutes_saved ?? 0))} min saved
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelected(r)}
                className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 rounded-md hover:brightness-95"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid={`pending-route-optimizations-open-${r.id}`}
              >
                Review <ChevronRight size={12} />
              </button>
            </li>
          ))}
        </ul>
      </div>

      <RouteOptimizationApprovalModal
        request={selected}
        open={!!selected}
        onClose={() => {
          setSelected(null);
          if (location.search.includes("optimize=")) {
            nav(location.pathname, { replace: true });
          }
        }}
        onResolved={onResolved}
      />
    </>
  );
}
