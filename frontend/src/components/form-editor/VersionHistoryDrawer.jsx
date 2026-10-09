// Phase 7B · Feb-2026 — Version history drawer.
//
// Lists prior ``form_templates`` versions returned by GET
// ``/form-templates/{form_type}/versions``.  Each row has a
// "Revert to this version" button that fires POST ``/revert/{v}``
// behind a confirm dialog.
import React, { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { History, RotateCcw } from "lucide-react";
import { colors } from "@/theme";


function _fmt(ts) {
  if (!ts) return "—";
  try {
    const d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return d.toLocaleString();
  } catch { return ts; }
}


export default function VersionHistoryDrawer({
  open, versions, onClose, onRevert, onRefresh, readOnly,
}) {
  const [confirmV, setConfirmV] = useState(null);

  useEffect(() => {
    if (open && typeof onRefresh === "function") onRefresh();
    if (!open) setConfirmV(null);
  }, [open, onRefresh]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-end"
      data-testid="version-history-drawer"
    >
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        data-testid="version-history-backdrop"
      />
      <aside className="relative w-full max-w-md h-full bg-white border-l shadow-2xl overflow-y-auto">
        <header className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-2 font-semibold">
            <History size={16} />
            Version History
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-slate-500 hover:text-slate-700"
            data-testid="version-history-close"
          >Close</button>
        </header>
        <ul className="divide-y">
          {versions.length === 0 ? (
            <li className="p-4 text-sm text-slate-500">
              No versions yet.
            </li>
          ) : versions.map((v) => (
            <li
              key={`${v.form_type}-${v.version}`}
              className="p-4 flex items-center justify-between gap-3"
              data-testid={`version-row-${v.version}`}
            >
              <div className="min-w-0">
                <div className="font-semibold text-sm flex items-center gap-2"
                     style={{ color: colors.onSurface }}>
                  v{v.version}
                  {v.is_current ? (
                    <span
                      className="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded-full"
                      style={{ background: "#DCFCE7", color: "#166534" }}
                      data-testid={`version-current-${v.version}`}
                    >Current</span>
                  ) : null}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">
                  {_fmt(v.updated_at)}
                </div>
              </div>
              {v.is_current || readOnly ? (
                <span className="text-xs text-slate-400">—</span>
              ) : (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => setConfirmV(v.version)}
                  data-testid={`version-revert-btn-${v.version}`}
                >
                  <RotateCcw size={12} className="mr-1" />
                  Revert
                </Button>
              )}
            </li>
          ))}
        </ul>
      </aside>

      {confirmV != null ? (
        <div
          className="absolute inset-0 flex items-center justify-center bg-black/40"
          data-testid="version-revert-confirm"
        >
          <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-sm">
            <div className="font-semibold mb-2">Revert to v{confirmV}?</div>
            <p className="text-sm text-slate-600 mb-4">
              The current version will be flagged non-current.  You can
              revert back at any time from this drawer.
            </p>
            <div className="flex justify-end gap-2">
              <Button
                type="button" variant="outline" size="sm"
                onClick={() => setConfirmV(null)}
                data-testid="version-revert-cancel"
              >Cancel</Button>
              <Button
                type="button" size="sm"
                onClick={() => {
                  const v = confirmV;
                  setConfirmV(null);
                  onRevert(v);
                }}
                data-testid="version-revert-confirm-ok"
              >Revert</Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
