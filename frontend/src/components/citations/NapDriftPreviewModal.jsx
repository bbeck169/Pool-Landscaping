import React from "react";
import { AlertTriangle, ExternalLink, X } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

/**
 * Feb-2026 · Phase 22 — NAP drift preview modal.
 *
 * Before an admin saves their business_card, this modal calls
 *   GET /api/citations/tenant/nap-drift-preview?<changed fields>
 * and shows every currently-live citation whose data_snapshot will
 * fall out of NAP alignment after the save.  The admin can Confirm
 * (proceeds with the outer Save) or Cancel (aborts the save).
 *
 * The preview is READ-ONLY on the backend — no state is mutated by
 * opening this modal.  Actual drift bookkeeping happens the next time
 * the seed-and-drift sweep runs.
 */
export default function NapDriftPreviewModal({
  open,
  proposed,           // { company_name?, service_area?, phone?, website_url? }
  onConfirm,          // called when admin clicks "Save anyway"
  onCancel,           // called when admin clicks "Cancel" / clicks outside
  confirmLabel = "Save anyway",
}) {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!open) return;
    setData(null); setError("");
    const params = new URLSearchParams();
    Object.entries(proposed || {}).forEach(([k, v]) => {
      if (v !== undefined && v !== null) params.set(k, v);
    });
    const qs = params.toString();
    api.get(`/citations/tenant/nap-drift-preview${qs ? `?${qs}` : ""}`)
       .then(setData)
       .catch((e) => setError(e?.message || "Failed to load drift preview"));
  }, [open, proposed]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[75] flex items-center justify-center p-4"
      style={{ background: "rgba(15,23,42,0.72)" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="nap-drift-preview-title"
      data-testid="nap-drift-preview-modal"
      onMouseDown={onCancel}
    >
      <div
        onMouseDown={(e) => e.stopPropagation()}
        className="w-full max-w-lg rounded-2xl shadow-2xl flex flex-col overflow-hidden max-h-[92vh]"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div
          className="px-5 py-4 flex items-center gap-3"
          style={{
            borderBottom: `1px solid ${colors.border}`,
            background: brandGradientCss,
            color: "#fff",
          }}
        >
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
            style={{ backgroundColor: "rgba(255,255,255,0.18)" }}
            aria-hidden="true"
          >
            <AlertTriangle size={18} />
          </div>
          <div className="flex-1 min-w-0">
            <h2
              id="nap-drift-preview-title"
              className="text-lg font-bold leading-tight"
              data-testid="nap-drift-preview-title"
            >
              Preview: NAP drift impact
            </h2>
            <p className="text-xs opacity-90">
              Which citations will flip to "Needs update" after saving?
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Close"
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: "rgba(255,255,255,0.18)" }}
            data-testid="nap-drift-preview-close"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          {error ? (
            <div
              className="rounded-lg p-3 text-sm flex items-start gap-2"
              style={{ backgroundColor: "#FEF3C7", color: "#92400E", border: "1px solid #FDE68A" }}
              data-testid="nap-drift-preview-error"
            >
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <div><b>Could not load preview.</b> {error} — you can still save,
                but drift will be recomputed on the next boot pass.</div>
            </div>
          ) : null}

          {data === null && !error ? (
            <div
              className="h-24 rounded-xl animate-pulse"
              style={{ backgroundColor: colors.surfaceSecondary }}
              data-testid="nap-drift-preview-loading"
            />
          ) : data ? (
            <>
              {(data.changed_fields || []).length === 0 ? (
                <div
                  className="rounded-lg p-3 text-sm"
                  style={{ backgroundColor: "#DCFCE7", color: "#166534", border: "1px solid #86EFAC" }}
                  data-testid="nap-drift-preview-no-changes"
                >
                  No NAP fields are actually changing — you're safe to save.
                </div>
              ) : (
                <div
                  className="rounded-lg p-3 text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                  data-testid="nap-drift-preview-changed-fields"
                >
                  Fields changing: <b>{(data.changed_fields || []).join(", ")}</b>
                </div>
              )}

              {(data.affected_count || 0) > 0 ? (
                <>
                  <div
                    className="text-sm"
                    style={{ color: colors.onSurface }}
                    data-testid="nap-drift-preview-summary"
                  >
                    Updating your business info will flag{" "}
                    <b>{data.affected_count}</b> live listing
                    {data.affected_count === 1 ? "" : "s"} as needing updates.
                    You'll need to manually update each directory.
                  </div>
                  <ul
                    className="space-y-1"
                    data-testid="nap-drift-preview-list"
                  >
                    {(data.affected || []).map((a) => (
                      <li
                        key={a.directory_id}
                        className="rounded-lg p-2 flex items-center gap-2"
                        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                        data-testid={`nap-drift-preview-item-${a.directory_slug}`}
                      >
                        <div className="flex-1 min-w-0">
                          <div className="font-semibold text-sm truncate" style={{ color: colors.onSurface }}>
                            {a.directory_name}
                          </div>
                          {a.listing_url ? (
                            <a
                              href={a.listing_url}
                              target="_blank"
                              rel="noreferrer noopener"
                              className="text-[11px] underline truncate block"
                              style={{ color: colors.brand }}
                              data-testid={`nap-drift-preview-listing-${a.directory_slug}`}
                            >
                              {a.listing_url}
                            </a>
                          ) : null}
                        </div>
                        {a.directory_url ? (
                          <a
                            href={a.directory_url}
                            target="_blank"
                            rel="noreferrer noopener"
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold"
                            style={{
                              backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.border}`,
                            }}
                            data-testid={`nap-drift-preview-open-${a.directory_slug}`}
                          >
                            <ExternalLink size={11} /> Open
                          </a>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <div
                  className="rounded-lg p-3 text-sm"
                  style={{ backgroundColor: "#DCFCE7", color: "#166534", border: "1px solid #86EFAC" }}
                  data-testid="nap-drift-preview-none-affected"
                >
                  No live citations will be affected — proceed with the save.
                </div>
              )}
            </>
          ) : null}
        </div>

        <div
          className="px-5 py-3 flex items-center justify-end gap-2"
          style={{ borderTop: `1px solid ${colors.border}`, backgroundColor: colors.surfaceSecondary }}
        >
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-2 rounded-lg text-sm font-semibold"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="nap-drift-preview-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="inline-flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-bold text-white"
            style={{ backgroundColor: colors.brand }}
            data-testid="nap-drift-preview-confirm"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
