// Phase MI1 · Feb 2026 — Admin · Checklist Templates settings.
//
// Tab per industry (Pool + the six new ones). Each tab shows the
// current resolved template with an inline editor:
//   * Reorder items (move up / move down — no drag-and-drop dep)
//   * Toggle ``required``
//   * Edit label inline
//   * Add / remove items
//   * Reset to default (DELETE endpoint)
//   * Save changes (PUT endpoint) — disabled until dirty
//
// Admin + Super Admin only.  The route wrapper in ``App.js`` uses
// ``<AdminOnly>`` — this page trusts that guard and never re-checks
// role client-side.
import React, { useEffect, useMemo, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";
import { Card } from "@/components/ui/card";
import { Trash2, Plus, ArrowUp, ArrowDown, RotateCcw, Save } from "lucide-react";
import { colors } from "@/theme";
import { INDUSTRY_LABELS } from "@/components/checklist/IndustryChecklistForm";

const INDUSTRY_ORDER = [
  "pool", "landscaping", "hvac", "pest_control",
  "cleaning", "solar", "handyman",
];


export default function ChecklistTemplatesSettings() {
  const [active, setActive] = useState("pool");
  const [template, setTemplate] = useState(null);   // resolved from API
  const [draft, setDraft] = useState([]);           // editable items
  const [source, setSource] = useState("default");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = (slug) => {
    setLoading(true); setError("");
    api.get(`/checklists/industry/${slug}`)
      .then((body) => {
        setTemplate(body);
        setDraft((body.items || []).map((i) => ({ ...i })));
        setSource(body.source || "default");
      })
      .catch((e) => setError(e?.message || "Failed to load"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(active); }, [active]);

  const dirty = useMemo(() => {
    if (!template) return false;
    const a = JSON.stringify(template.items || []);
    const b = JSON.stringify(draft || []);
    return a !== b;
  }, [template, draft]);

  const move = (idx, dir) => {
    setDraft((prev) => {
      const next = prev.slice();
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      const [row] = next.splice(idx, 1);
      next.splice(target, 0, row);
      return next;
    });
  };

  const toggleRequired = (idx) => {
    setDraft((prev) => prev.map(
      (r, i) => (i === idx ? { ...r, required: !r.required } : r),
    ));
  };

  const editLabel = (idx, label) => {
    setDraft((prev) => prev.map(
      (r, i) => (i === idx ? { ...r, label } : r),
    ));
  };

  const remove = (idx) => {
    setDraft((prev) => prev.filter((_, i) => i !== idx));
  };

  const addItem = () => {
    setDraft((prev) => [...prev, {
      key: `custom_${Date.now()}`,
      label: "New checklist item",
      required: false,
    }]);
  };

  const save = async () => {
    setBusy(true);
    try {
      // Guarantee unique keys before we send — the backend accepts
      // duplicates by silently dropping them, we'd rather surface
      // the collision here.
      const seen = new Set();
      for (const row of draft) {
        if (seen.has(row.key)) {
          toast.error(`Duplicate key "${row.key}" — rename before saving`);
          setBusy(false);
          return;
        }
        seen.add(row.key);
      }
      const body = await api.put(
        `/checklists/industry/${active}`, { items: draft },
      );
      setTemplate(body);
      setDraft((body.items || []).map((i) => ({ ...i })));
      setSource(body.source || "override");
      toast.success(`${INDUSTRY_LABELS[active]} checklist saved`);
    } catch (e) {
      toast.error(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  const reset = async () => {
    setBusy(true);
    try {
      const body = await api.del(`/checklists/industry/${active}`);
      setTemplate(body);
      setDraft((body.items || []).map((i) => ({ ...i })));
      setSource(body.source || "default");
      toast.success(`${INDUSTRY_LABELS[active]} reverted to default`);
    } catch (e) {
      toast.error(e?.message || "Reset failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto"
         data-testid="admin-checklist-templates-page">
      <div className="mb-5">
        <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
          Checklist templates
        </h1>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          Customize the checklist your techs see per industry. Changes
          apply the next time a tech opens a job of that industry — the
          default template is used until you save an override.
        </p>
      </div>

      {/* Tabs */}
      <div
        className="flex items-center gap-1 mb-4 flex-wrap rounded-xl p-1"
        style={{ background: colors.surfaceSecondary,
                  border: `1px solid ${colors.border}` }}
        data-testid="checklist-industry-tabs"
        role="tablist"
      >
        {INDUSTRY_ORDER.map((slug) => (
          <button
            key={slug}
            type="button"
            role="tab"
            aria-selected={active === slug}
            onClick={() => setActive(slug)}
            className="px-3 py-1.5 text-sm font-semibold rounded-lg transition-colors"
            style={{
              backgroundColor: active === slug ? "#FFFFFF" : "transparent",
              color: active === slug ? colors.onSurface : colors.muted,
              border: active === slug ? `1px solid ${colors.border}` : "1px solid transparent",
            }}
            data-testid={`checklist-industry-tab-${slug}`}
          >
            {INDUSTRY_LABELS[slug]}
          </button>
        ))}
      </div>

      {/* Source badge + actions */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-semibold uppercase"
              style={{ color: colors.muted }}
              data-testid="checklist-source-badge">
          Source: {source}
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={reset}
            disabled={busy || source !== "override"}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg disabled:opacity-50"
            style={{ background: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="checklist-reset-button"
          >
            <RotateCcw size={13} /> Reset to default
          </button>
          <button
            type="button"
            onClick={save}
            disabled={busy || !dirty}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold rounded-lg text-white disabled:opacity-40"
            style={{ background: "#1D4ED8" }}
            data-testid="checklist-save-button"
          >
            <Save size={13} /> Save changes
          </button>
        </div>
      </div>

      {error ? (
        <div className="mb-3 text-sm p-2 rounded-lg"
             style={{ color: "#991B1B", background: "#FEE2E2" }}>
          {error}
        </div>
      ) : null}

      <Card className="p-4">
        {loading ? (
          <div className="text-sm" style={{ color: colors.muted }}
               data-testid="checklist-loading">Loading…</div>
        ) : (
          <ul className="space-y-2" data-testid="checklist-editor-list">
            {draft.map((row, idx) => (
              <li
                key={row.key}
                className="flex items-center gap-2 p-2 rounded-lg"
                style={{ border: `1px solid ${colors.border}`,
                          background: colors.surface }}
                data-testid={`checklist-editor-row-${row.key}`}
              >
                <div className="flex flex-col gap-1">
                  <button
                    type="button"
                    onClick={() => move(idx, -1)}
                    disabled={idx === 0}
                    className="p-0.5 disabled:opacity-30"
                    style={{ color: colors.muted }}
                    aria-label="Move up"
                    data-testid={`checklist-editor-up-${row.key}`}
                  ><ArrowUp size={14} /></button>
                  <button
                    type="button"
                    onClick={() => move(idx, 1)}
                    disabled={idx === draft.length - 1}
                    className="p-0.5 disabled:opacity-30"
                    style={{ color: colors.muted }}
                    aria-label="Move down"
                    data-testid={`checklist-editor-down-${row.key}`}
                  ><ArrowDown size={14} /></button>
                </div>
                <input
                  type="text"
                  value={row.label}
                  onChange={(e) => editLabel(idx, e.target.value)}
                  className="flex-1 px-2 py-1.5 text-sm rounded-md outline-none"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid={`checklist-editor-label-${row.key}`}
                />
                <label
                  className="inline-flex items-center gap-1.5 text-xs font-semibold cursor-pointer select-none px-2"
                  style={{ color: colors.onSurface }}
                >
                  <input
                    type="checkbox"
                    checked={!!row.required}
                    onChange={() => toggleRequired(idx)}
                    data-testid={`checklist-editor-required-${row.key}`}
                  />
                  Required
                </label>
                <button
                  type="button"
                  onClick={() => remove(idx)}
                  className="p-1"
                  style={{ color: "#DC2626" }}
                  aria-label="Remove item"
                  data-testid={`checklist-editor-remove-${row.key}`}
                ><Trash2 size={14} /></button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3">
          <button
            type="button"
            onClick={addItem}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg"
            style={{ background: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="checklist-editor-add"
          >
            <Plus size={13} /> Add item
          </button>
        </div>
      </Card>
    </div>
  );
}
