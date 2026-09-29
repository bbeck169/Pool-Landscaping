/**
 * Phase Feb-2026 — Customer portal · Warranties (read-only).
 *
 * Uses GET /api/customers/me/warranties which returns the standard
 * ``{items, page, page_size, total, total_pages}`` envelope with
 * ``linked_summary`` hydrated per row.
 */
import React, { useCallback, useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { api } from "@/api";
// DTP-2 · Feb-2026 — swap the local warm-slate ``c`` const to the
// portal-dark palette via the shared theme export.  Names preserved
// so every downstream ``c.X`` read still resolves.
import { portalColors as c } from "@/theme";

export default function PortalWarranties() {
  const [state, setState] = useState({ items: [], loading: true, error: "" });

  const load = useCallback(async () => {
    try {
      const r = await api.get("/customers/me/warranties");
      setState({ items: r.items || [], loading: false, error: "" });
    } catch (e) {
      setState({ items: [], loading: false, error: e?.message || "Failed to load warranties" });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="portal-warranties-section">
      <div className="mb-4">
        <div className="flex items-center gap-2 text-lg font-bold" style={{ color: c.onSurface }}>
          <ShieldCheck size={18} color={c.brand} />
          Warranties
        </div>
        <div className="text-sm mt-1" style={{ color: c.muted }}>
          Your active warranty contracts and coverage windows.
        </div>
      </div>

      {state.loading ? (
        <div className="text-sm" style={{ color: c.muted }} data-testid="portal-warranty-loading">Loading…</div>
      ) : state.error ? (
        <div className="text-sm" style={{ color: "#DC2626" }} data-testid="portal-warranty-error">{state.error}</div>
      ) : state.items.length === 0 ? (
        <div
          className="text-sm p-4 rounded-lg text-center"
          style={{ color: c.muted, background: c.surface, border: `1px dashed ${c.border}` }}
          data-testid="portal-warranty-empty"
        >
          No warranties on file yet.
        </div>
      ) : (
        <div className="space-y-2" data-testid="portal-warranty-list">
          {state.items.map((w, i) => (
            <div
              key={w.id}
              className="rounded-lg p-3"
              style={{ border: `1px solid ${c.border}`, background: "#fff" }}
              data-testid={`portal-warranty-card-${i}`}
            >
              <div
                className="text-sm font-bold"
                style={{ color: c.onSurface }}
                data-testid={`portal-warranty-card-name-${i}`}
              >
                {w.plan_name_snapshot || "Warranty"}
              </div>
              <div
                className="mt-1 text-xs"
                style={{ color: c.muted }}
                data-testid={`portal-warranty-card-window-${i}`}
              >
                Coverage: {w.start_date} → {w.end_date}
                {w.status ? (
                  <span
                    className="ml-2 uppercase text-[10px] px-1 py-0.5 rounded"
                    style={{ background: c.surface, border: `1px solid ${c.border}` }}
                  >{w.status}</span>
                ) : null}
              </div>
              {w.linked_summary ? (
                <div
                  className="mt-2 text-xs px-2 py-1 rounded"
                  style={{ background: c.surface, border: `1px solid ${c.border}` }}
                  data-testid={`portal-warranty-card-link-${i}`}
                >
                  <span className="font-semibold">
                    Linked {w.linked_summary.type}:
                  </span>{" "}
                  {w.linked_summary.label}
                </div>
              ) : null}
              {w.notes ? (
                <div
                  className="mt-2 text-xs"
                  style={{ color: c.onSurface, whiteSpace: "pre-wrap" }}
                  data-testid={`portal-warranty-card-notes-${i}`}
                >{w.notes}</div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
