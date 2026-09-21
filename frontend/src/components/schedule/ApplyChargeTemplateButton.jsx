/**
 * Phase F2 · Feb-2026 — "Add from template" dropdown for the job
 * line-items editor.
 *
 * Lists active charge templates for the current tenant and, on pick,
 * calls ``POST /api/charge-templates/{tid}/apply-to-job/{jid}``. The
 * caller passes ``onApplied()`` so the surrounding editor can refresh
 * its line-items view after a successful append.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LayoutTemplate, Search } from "lucide-react";
import { toast } from "sonner";
import { api } from "../../api";
import { colors } from "../../theme";

export default function ApplyChargeTemplateButton({
  jobId,
  onApplied,
  disabled = false,
}) {
  const [open, setOpen] = useState(false);
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [applyingId, setApplyingId] = useState(null);
  const containerRef = useRef(null);

  // Lazy-load on first open so admins that never expand the dropdown
  // don't spend a request on it.
  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const res = await api.get("/charge-templates");
      setTemplates(res?.templates || []);
    } catch (e) {
      setErr(e?.message || "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && templates.length === 0 && !loading && !err) {
      load();
    }
  }, [open, templates.length, loading, err, load]);

  // Outside-click to close.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const filtered = useMemo(() => {
    const needle = (q || "").trim().toLowerCase();
    if (!needle) return templates;
    return templates.filter((t) =>
      (t.name || "").toLowerCase().includes(needle) ||
      (t.category || "").toLowerCase().includes(needle),
    );
  }, [templates, q]);

  const apply = async (tpl) => {
    setApplyingId(tpl.id);
    try {
      const res = await api.post(
        `/charge-templates/${tpl.id}/apply-to-job/${jobId}`,
      );
      const count = res?.added_count ?? (tpl.line_items || []).length;
      toast.success(`Applied "${tpl.name}" — ${count} item${count === 1 ? "" : "s"} added`);
      setOpen(false);
      onApplied?.(res);
    } catch (e) {
      toast.error(e?.message || "Apply failed");
    } finally {
      setApplyingId(null);
    }
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className="inline-flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold"
        style={{
          background: colors.surfaceSecondary,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
          opacity: disabled ? 0.6 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        data-testid="apply-charge-template-btn"
      >
        <LayoutTemplate size={14} /> Add from template
      </button>
      {open ? (
        <div
          className="absolute right-0 mt-2 w-80 rounded-xl shadow-xl z-30"
          style={{ background: colors.surface,
                   border: `1px solid ${colors.border}` }}
          data-testid="apply-charge-template-dropdown"
        >
          <div className="p-2"
               style={{ borderBottom: `1px solid ${colors.border}` }}>
            <div
              className="flex items-center gap-2 px-2 py-1 rounded-md"
              style={{ background: colors.surfaceSecondary,
                       border: `1px solid ${colors.border}` }}
            >
              <Search size={12} style={{ color: colors.searchIcon }} />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search templates…"
                className="bg-transparent outline-none flex-1 text-xs"
                style={{ color: colors.onSurface }}
                data-testid="apply-charge-template-search"
              />
            </div>
          </div>
          <div className="max-h-64 overflow-y-auto py-1">
            {loading ? (
              <div className="px-3 py-4 text-xs text-center"
                   style={{ color: colors.muted }}
                   data-testid="apply-charge-template-loading">
                Loading…
              </div>
            ) : err ? (
              <div className="px-3 py-4 text-xs text-center"
                   style={{ color: colors.error }}
                   data-testid="apply-charge-template-error">
                {err}
              </div>
            ) : filtered.length === 0 ? (
              <div className="px-3 py-4 text-xs text-center"
                   style={{ color: colors.muted }}
                   data-testid="apply-charge-template-empty">
                {templates.length === 0
                  ? "No charge templates yet."
                  : "No matches."}
              </div>
            ) : filtered.map((tpl) => (
              <button
                key={tpl.id}
                type="button"
                onClick={() => apply(tpl)}
                disabled={applyingId === tpl.id}
                className="w-full text-left px-3 py-2 hover:bg-slate-50"
                style={{ color: colors.onSurface,
                         background: applyingId === tpl.id
                           ? colors.surfaceSecondary
                           : "transparent" }}
                data-testid={`apply-charge-template-option-${tpl.id}`}
              >
                <div className="text-sm font-semibold">{tpl.name}</div>
                <div className="text-[11px]" style={{ color: colors.muted }}>
                  {(tpl.category || "custom")} · {(tpl.line_items || []).length} item{(tpl.line_items || []).length === 1 ? "" : "s"}
                  {applyingId === tpl.id ? " · Applying…" : ""}
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
