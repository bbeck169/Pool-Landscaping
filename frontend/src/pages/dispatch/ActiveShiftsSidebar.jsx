// Phase 17 · Feb-2026 — Active Shifts sidebar panel.
//
// Lists every active ``route_assignment_overrides`` row for the
// tenant, ordered newest-first, with a Cancel button per row.
// Renders NOTHING when there are zero active shifts (keeps the
// sidebar quiet by default).
import React from "react";
import { toast } from "sonner";
import { AlertTriangle, RotateCcw, X, ChevronDown, ChevronUp } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function formatEnds(iso) {
  try {
    return new Date(iso).toLocaleString("en-US", {
      weekday: "short", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    });
  } catch { return iso; }
}

export default function ActiveShiftsSidebar({
  items = [], onRefresh = () => {},
}) {
  const [open, setOpen] = React.useState(true);
  const [cancelingId, setCancelingId] = React.useState(null);

  if (!items.length) return null; // hidden when nothing active

  const cancel = async (id) => {
    setCancelingId(id);
    try {
      await api.post(`/dispatch/reassign/${id}/cancel`);
      toast.success("Shift canceled.");
      onRefresh();
    } catch (e) {
      toast.error(`Cancel failed: ${e.message || e}`);
    } finally {
      setCancelingId(null);
    }
  };

  return (
    <div
      className="rounded-xl p-3 space-y-2"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="active-shifts-sidebar"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between text-xs uppercase tracking-wide font-semibold"
        style={{ color: colors.muted }}
        data-testid="active-shifts-toggle"
      >
        <span className="flex items-center gap-1">
          <RotateCcw size={12} /> Active shifts this week
          <span
            className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold"
            style={{ backgroundColor: colors.brand, color: "#fff" }}
            data-testid="active-shifts-badge"
          >
            {items.length}
          </span>
        </span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <ul className="space-y-1.5" data-testid="active-shifts-list">
          {items.map((it) => (
            <li
              key={it.id}
              className="rounded-lg p-2"
              style={{
                backgroundColor: colors.surfaceSecondary,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={`active-shift-row-${it.id}`}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-semibold truncate"
                       style={{ color: colors.onSurface }}>
                    {it.source_tech_name || "—"} → {it.target_tech_name || "—"}
                  </div>
                  <div className="text-[11px] flex items-center gap-1"
                       style={{ color: colors.muted }}>
                    <span>{it.stop_count} stop(s)</span>
                    <span>·</span>
                    <span>ends {formatEnds(it.end_at)}</span>
                  </div>
                  {it.notes ? (
                    <div className="text-[11px] italic mt-0.5 truncate"
                         style={{ color: colors.muted }}
                         data-testid={`active-shift-notes-${it.id}`}>
                      “{it.notes}”
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => cancel(it.id)}
                  disabled={cancelingId === it.id}
                  className="px-2 py-1 rounded-md text-[11px] font-semibold hover:brightness-95 disabled:opacity-60"
                  style={{
                    backgroundColor: "#FEF2F2",
                    color: "#991B1B",
                    border: "1px solid #FECACA",
                  }}
                  data-testid={`active-shift-cancel-${it.id}`}
                >
                  {cancelingId === it.id ? "…" : (<><X size={10} className="inline mr-1" />Cancel</>)}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
