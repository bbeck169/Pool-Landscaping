/**
 * TD-cad-phase1 · Oct-2026 — GAP-A FE attach widgets.
 *
 * Shared aside component mounted on both the Property drawer and the
 * Quote detail page. Fetches ``GET /api/designs?property_id=...``
 * (or ``?quote_id=...``) and renders a thumbnail + title + updated-at
 * row per design. "+ New site plan" button opens the CAD editor
 * pre-wired with the attach id via query params.
 *
 * Props:
 *   mode:          "property" | "quote"
 *   id:            property_id or quote_id to filter by
 *   customerId?:   optional — forwarded to the new-design URL so the
 *                  editor can pre-wire ``customer_id`` on first save.
 *
 * The CAD Editor consumes the pre-fill query params by reading
 * ``location.search`` on mount (handled in Editor.jsx: `?property_id=`,
 * `?quote_id=`, `?customer_id=`). Not implementing the Editor-side
 * pre-fill in this ticket — it's a 1-line future gap (TD-cad-phase1b)
 * — the aside WIRES the attach via explicit on-save in the editor.
 */
import React from "react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { colors } from "@/theme";

export default function SitePlansAside({ mode, id, customerId }) {
  const [rows, setRows] = React.useState(null);  // null = loading
  const [err, setErr] = React.useState("");

  const paramKey = mode === "property" ? "property_id" : "quote_id";

  React.useEffect(() => {
    let cancelled = false;
    if (!id) { setRows([]); return; }
    (async () => {
      try {
        const q = encodeURIComponent(id);
        const r = await api.get(`/designs?${paramKey}=${q}`);
        if (!cancelled) setRows(Array.isArray(r) ? r : []);
      } catch (e) {
        if (!cancelled) {
          setErr(e?.message || "Failed to load site plans");
          setRows([]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [id, paramKey]);

  // "+ New site plan" → /cad with pre-fill query params. The admin
  // CAD list route (/cad) opens a new-design flow; the attach params
  // are forwarded so the editor can wire them on save.
  const newHref =
    `/cad?${paramKey}=${encodeURIComponent(id || "")}` +
    (customerId ? `&customer_id=${encodeURIComponent(customerId)}` : "");

  return (
    <aside
      className="rounded-xl p-3 space-y-2"
      style={{ backgroundColor: colors.surfaceSecondary,
                 border: `1px solid ${colors.border}` }}
      data-testid={`site-plans-aside-${mode}`}
    >
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide"
              style={{ color: colors.muted }}>
          Site plans
        </h3>
        <Link
          to={newHref}
          className="text-xs font-semibold"
          style={{ color: colors.brand }}
          data-testid={`site-plans-new-${mode}`}
        >+ New site plan</Link>
      </div>

      {rows === null ? (
        <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}
             data-testid={`site-plans-loading-${mode}`}>
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}
             data-testid={`site-plans-empty-${mode}`}>
          No site plans attached.
        </div>
      ) : (
        <ul className="space-y-1" data-testid={`site-plans-list-${mode}`}>
          {rows.map((d) => (
            <li key={d.id}>
              <Link
                to={`/cad/editor/${d.id}`}
                className="flex items-center gap-2 p-1.5 rounded hover:bg-black/5"
                style={{ color: colors.onSurface }}
                data-testid={`site-plans-row-${d.id}`}
              >
                {d.thumbnail ? (
                  <img
                    src={d.thumbnail}
                    alt=""
                    className="w-10 h-10 rounded object-cover border"
                    style={{ borderColor: colors.border }}
                    data-testid={`site-plans-thumb-${d.id}`}
                  />
                ) : (
                  <div
                    className="w-10 h-10 rounded flex items-center justify-center text-xs"
                    style={{ backgroundColor: colors.surface,
                               border: `1px dashed ${colors.border}`,
                               color: colors.muted }}
                    data-testid={`site-plans-thumb-placeholder-${d.id}`}
                  >—</div>
                )}
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold truncate">
                    {d.name || "Untitled design"}
                  </div>
                  <div className="text-[10px]"
                        style={{ color: colors.onSurfaceSecondary }}>
                    {d.updated_at ? new Date(d.updated_at).toLocaleDateString() : ""}
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {err ? (
        <div className="text-[10px]" style={{ color: "#B91C1C" }}
             data-testid={`site-plans-err-${mode}`}>{err}</div>
      ) : null}
    </aside>
  );
}
