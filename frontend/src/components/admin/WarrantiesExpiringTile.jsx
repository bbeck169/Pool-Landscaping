/**
 * WarrantiesExpiringTile · Feb-2026 · Polish bundle Item 3
 *
 * Admin-dashboard tile showing the top-5 warranty contracts whose
 * ``coverage_end`` falls within the next 30 days. Reads
 * ``GET /api/warranties/expiring-soon?days=30``. Each row is a
 * click-through to the customer's warranties tab, plus a "Renew"
 * shortcut that lands on the same tab (no auto-renewal flow in v1).
 * See FIX_POLISH_BUNDLE_FEB_2026.md.
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";
import { ShieldCheck } from "lucide-react";
import { CustomerLink } from "@/components/customer";

function _daysBadgeColor(days) {
  if (days == null) return colors.muted;
  if (days <= 7) return "#DC2626";     // red — urgent
  if (days <= 14) return "#CA8A04";    // amber — soon
  return colors.brand;                  // blue — informational
}

export default function WarrantiesExpiringTile() {
  const navigate = useNavigate();
  const [loading, setLoading] = React.useState(true);
  const [items, setItems] = React.useState([]);
  const [err, setErr] = React.useState(null);

  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api.get("/warranties/expiring-soon?days=30")
      .then((r) => { if (!cancelled) setItems((r?.items || []).slice(0, 5)); })
      .catch((e) => { if (!cancelled) setErr(e?.message || "Failed to load"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const go = (customerId) => {
    if (!customerId) return;
    navigate(`/customers/${customerId}?tab=warranties`);
  };

  return (
    <div
      className="bg-white rounded-lg border p-4"
      style={{ borderColor: colors.border }}
      data-testid="warranties-expiring-tile"
    >
      <div className="flex items-center gap-2 mb-3">
        <ShieldCheck size={16} style={{ color: colors.brand }} />
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Warranties nearing expiration
        </div>
      </div>

      {loading ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="warranties-expiring-loading">Loading…</div>
      ) : err ? (
        <div className="text-xs text-red-600"
             data-testid="warranties-expiring-error">{String(err)}</div>
      ) : items.length === 0 ? (
        <div className="text-sm" style={{ color: colors.muted }}
             data-testid="warranties-expiring-empty">
          No warranties expiring in the next 30 days.
        </div>
      ) : (
        <div className="space-y-2 text-sm">
          {items.map((it, i) => {
            const days = it.days_remaining;
            const badge = _daysBadgeColor(days);
            return (
              <div
                key={it.id || i}
                className="flex items-start gap-3 rounded-md p-2 hover:brightness-95 cursor-pointer"
                style={{ backgroundColor: colors.surfaceSecondary }}
                onClick={() => go(it.customer_id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    go(it.customer_id);
                  }
                }}
                data-testid={`warranties-expiring-row-${i}`}
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium"
                       style={{ color: colors.onSurface }}
                       title={it.contract_name}>
                    {it.contract_name}
                  </div>
                  <div className="text-[11px] truncate"
                       style={{ color: colors.muted }}
                       title={it.customer_name}>
                    <CustomerLink customerId={it.customer_id} name={it.customer_name || "—"} />
                    {it.linked_summary ? ` · ${it.linked_summary}` : ""}
                  </div>
                </div>
                <div className="text-right shrink-0 flex flex-col items-end gap-1">
                  <div className="text-xs font-semibold"
                       style={{ color: badge }}>
                    {days == null
                      ? "—"
                      : days === 0
                      ? "today"
                      : `${days}d`}
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      go(it.customer_id);
                    }}
                    className="text-[11px] font-semibold px-2 py-0.5 rounded hover:brightness-95"
                    style={{
                      backgroundColor: colors.brandTertiary,
                      color: colors.onBrandTertiary,
                    }}
                    data-testid={`warranties-expiring-row-${i}-renew`}
                  >
                    Renew
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
