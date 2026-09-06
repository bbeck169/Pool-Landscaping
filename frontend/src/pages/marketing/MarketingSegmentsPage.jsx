import React, { useEffect, useState } from "react";
import { Plus, Users, RefreshCcw, Trash2, X as XIcon, Save } from "lucide-react";
import { api } from "@/api";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { colors, brandGradientCss } from "@/theme";

/**
 * Feb-2026 · Marketing Slice M4 — Segments admin page.
 *
 * v1 AND-only condition builder. Field / op / value inputs dynamically
 * driven by the /marketing/audience-segments/schema endpoint so
 * adding a new predicate on the backend automatically surfaces here.
 */
export default function MarketingSegmentsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = () => {
    setLoading(true);
    api
      .get("/marketing/audience-segments")
      .then((r) => setRows(r.segments || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const refreshCount = async (sid) => {
    try {
      const r = await api.post(
        `/marketing/audience-segments/${sid}/preview?refresh=true`,
        {},
      );
      setRows((prev) =>
        prev.map((s) => (s.id === sid ? { ...s, match_count_cached: r.count } : s)),
      );
    } catch {}
  };

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="marketing-segments-page">
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Segments
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            {rows.length} segment{rows.length === 1 ? "" : "s"} — build audiences that campaigns and drips can target.
          </p>
        </div>
        <button
          onClick={() => setEditing({})}
          className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
          style={{ background: brandGradientCss }}
          data-testid="segment-create-btn"
        >
          <Plus size={16} /> New segment
        </button>
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        {loading ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>
            No segments yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
                {["Name", "Description", "Match count", "Updated"].map((h) => (
                  <th key={h}
                      className="text-left py-2 px-3 text-xs font-bold uppercase tracking-wide"
                      style={{ color: colors.muted }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => setEditing(r)}
                  className="cursor-pointer hover:brightness-95"
                  style={{ borderBottom: `1px solid ${colors.divider}` }}
                  data-testid={`segment-row-${r.id}`}
                >
                  <td className="py-3 px-3" style={{ color: colors.onSurface }}>
                    {r.name}
                    {r.system ? (
                      <span className="ml-2 text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                            style={{ backgroundColor: "#DBEAFE", color: "#1E3A8A" }}>
                        SEED
                      </span>
                    ) : null}
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.onSurfaceSecondary }}>
                    {r.description || "—"}
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.onSurface }}>
                    {r.match_count_cached ?? "—"}
                    <button
                      onClick={(e) => { e.stopPropagation(); refreshCount(r.id); }}
                      className="ml-2 p-0.5 rounded"
                      style={{ color: colors.muted }}
                      title="Refresh count"
                    >
                      <RefreshCcw size={11} />
                    </button>
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.muted }}>
                    {String(r.updated_at || "").slice(0, 10)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing !== null ? (
        <SegmentEditor initial={editing} onClose={() => setEditing(null)}
                       onSaved={() => { setEditing(null); load(); }} />
      ) : null}
    </div>
  );
}


function SegmentEditor({ initial, onClose, onSaved }) {
  const isNew = !initial?.id;
  const [name, setName] = useState(initial?.name || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [conditions, setConditions] = useState(initial?.conditions || []);
  const [schema, setSchema] = useState([]);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/marketing/audience-segments/schema")
      .then((r) => setSchema(r.fields || []));
  }, []);

  const addCondition = () => {
    if (!schema.length) return;
    const first = schema[0];
    setConditions((c) => [
      ...c,
      { field: first.field, op: first.ops[0], value: _defaultValue(first) },
    ]);
  };

  const updateCondition = (i, patch) =>
    setConditions((c) => c.map((cc, idx) => (idx === i ? { ...cc, ...patch } : cc)));

  const removeCondition = (i) =>
    setConditions((c) => c.filter((_, idx) => idx !== i));

  const runPreview = async () => {
    setBusy(true); setError("");
    try {
      const r = await api.post("/marketing/audience-segments/preview-adhoc",
                                { conditions });
      setPreview(r);
    } catch (e) { setError(e?.message || "Preview failed"); }
    finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true); setError("");
    try {
      if (isNew) {
        await api.post("/marketing/audience-segments",
                        { name, description, conditions });
      } else {
        await api.patch(`/marketing/audience-segments/${initial.id}`,
                         { name, description, conditions });
      }
      onSaved?.();
    } catch (e) { setError(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const del = async () => {
    if (!initial?.id) return;
    const ok = await mustConfirm({
      title: "Deactivate this segment?",
      description: "Existing enrolments halt. Automations using this segment will no-op.",
      tone: "danger", confirmText: "Deactivate", requireTypeConfirm: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.delete(`/marketing/audience-segments/${initial.id}`);
      onSaved?.();
    } catch (e) { setError(e?.message || "Delete failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end"
         style={{ background: "rgba(15,23,42,0.55)" }}
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
         data-testid="segment-edit-modal">
      <div className="w-full sm:w-[720px] h-full shadow-2xl flex flex-col"
           style={{ backgroundColor: colors.surface, borderLeft: `1px solid ${colors.border}` }}
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 pt-4 pb-3"
             style={{ borderBottom: `1px solid ${colors.divider}` }}>
          <div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {isNew ? "New segment" : "Edit segment"}
            </div>
            <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              {name || "Untitled"}
            </h2>
          </div>
          <button onClick={onClose} className="p-1" style={{ color: colors.muted }}>
            <XIcon size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <input
            type="text" value={name} onChange={(e) => setName(e.target.value)}
            placeholder="Segment name"
            className="w-full px-3 py-2 rounded-lg text-sm outline-none"
            style={{ backgroundColor: colors.surface, color: colors.onSurface,
                     border: `1px solid ${colors.border}` }}
            data-testid="segment-name-input"
          />
          <input
            type="text" value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            className="w-full px-3 py-2 rounded-lg text-sm outline-none"
            style={{ backgroundColor: colors.surface, color: colors.onSurface,
                     border: `1px solid ${colors.border}` }}
          />

          <div>
            <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
                 style={{ color: colors.muted }}>
              CONDITIONS (all must match)
            </div>
            <div className="space-y-2">
              {conditions.map((c, i) => (
                <ConditionRow key={i} index={i} condition={c} schema={schema}
                              onChange={(patch) => updateCondition(i, patch)}
                              onRemove={() => removeCondition(i)} />
              ))}
            </div>
            <button
              onClick={addCondition}
              className="mt-2 inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold"
              style={{ backgroundColor: colors.surfaceSecondary,
                       color: colors.onSurface,
                       border: `1px solid ${colors.border}` }}
              data-testid="segment-add-condition-btn"
            >
              <Plus size={12} /> Add condition
            </button>
          </div>

          {preview ? (
            <div className="rounded-xl p-3"
                 style={{ backgroundColor: colors.surfaceSecondary,
                          border: `1px solid ${colors.divider}` }}>
              <div className="flex items-center gap-2 mb-2">
                <Users size={14} style={{ color: colors.brand }} />
                <span className="text-sm font-bold" style={{ color: colors.onSurface }}
                      data-testid="segment-preview-count">
                  {preview.count} customer{preview.count === 1 ? "" : "s"} match
                </span>
              </div>
              {preview.sample?.length ? (
                <ul className="space-y-1">
                  {preview.sample.map((s) => (
                    <li key={s.id} className="text-xs"
                        style={{ color: colors.onSurfaceSecondary }}>
                      {s.name} {s.email ? `· ${s.email}` : ""}
                      {s.vip ? " · VIP" : ""}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="text-xs" style={{ color: colors.muted }}>
                  No sample rows to display.
                </div>
              )}
            </div>
          ) : null}

          {error ? (
            <div className="text-sm" style={{ color: colors.error }}>{error}</div>
          ) : null}
        </div>

        <div className="p-4 flex items-center justify-between gap-2"
             style={{ borderTop: `1px solid ${colors.divider}` }}>
          <div>
            {!isNew ? (
              <button onClick={del} disabled={busy}
                      className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
                      style={{ backgroundColor: colors.surfaceSecondary,
                               color: colors.error }}>
                <Trash2 size={14} /> Deactivate
              </button>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={runPreview} disabled={busy}
                    className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
                    style={{ backgroundColor: colors.surfaceSecondary,
                             color: colors.onSurface }}
                    data-testid="segment-preview-btn">
              <Users size={14} /> Preview matches
            </button>
            <button onClick={onClose}
                    className="px-4 py-2 rounded-xl text-sm font-semibold"
                    style={{ backgroundColor: colors.surfaceSecondary,
                             color: colors.onSurface }}>
              Cancel
            </button>
            <button onClick={save} disabled={busy || !name.trim()}
                    className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                    style={{ background: colors.brand }}
                    data-testid="segment-save-btn">
              <Save size={14} /> {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


function ConditionRow({ index, condition, schema, onChange, onRemove }) {
  const meta = schema.find((s) => s.field === condition.field) || null;
  const ops = meta?.ops || ["eq"];
  const shape = meta?.value_shape || "string";
  return (
    <div className="flex items-center gap-2 flex-wrap"
         data-testid={`segment-condition-${index}`}>
      <select value={condition.field}
              onChange={(e) => {
                const next = schema.find((s) => s.field === e.target.value);
                onChange({
                  field: e.target.value,
                  op: next?.ops[0] || "eq",
                  value: _defaultValue(next),
                });
              }}
              className="px-2 py-1.5 rounded-lg text-xs outline-none"
              style={{ backgroundColor: colors.surface,
                       color: colors.onSurface,
                       border: `1px solid ${colors.border}` }}>
        {schema.map((s) => <option key={s.field} value={s.field}>{s.field}</option>)}
      </select>
      <select value={condition.op}
              onChange={(e) => onChange({ op: e.target.value })}
              className="px-2 py-1.5 rounded-lg text-xs outline-none"
              style={{ backgroundColor: colors.surface,
                       color: colors.onSurface,
                       border: `1px solid ${colors.border}` }}>
        {ops.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
      <ValueInput shape={shape} op={condition.op} value={condition.value}
                  onChange={(v) => onChange({ value: v })} />
      <button onClick={onRemove}
              className="p-1 rounded"
              style={{ color: colors.muted }}
              aria-label="Remove condition">
        <XIcon size={14} />
      </button>
    </div>
  );
}


function ValueInput({ shape, op, value, onChange }) {
  const st = {
    backgroundColor: colors.surface, color: colors.onSurface,
    border: `1px solid ${colors.border}`,
  };
  if (shape === "boolean") {
    return (
      <select value={String(value)}
              onChange={(e) => onChange(e.target.value === "true")}
              className="px-2 py-1.5 rounded-lg text-xs outline-none" style={st}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    );
  }
  if (shape === "string_list") {
    return (
      <input type="text"
             value={Array.isArray(value) ? value.join(", ") : String(value || "")}
             onChange={(e) =>
               onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))
             }
             placeholder="comma-separated"
             className="px-2 py-1.5 rounded-lg text-xs outline-none flex-1 min-w-[180px]"
             style={st} />
    );
  }
  if (op === "between") {
    const arr = Array.isArray(value) ? value : [0, 0];
    return (
      <>
        <input type="number" value={arr[0] ?? 0}
               onChange={(e) => onChange([Number(e.target.value), arr[1] ?? 0])}
               className="w-24 px-2 py-1.5 rounded-lg text-xs outline-none" style={st} />
        <span className="text-xs" style={{ color: colors.muted }}>to</span>
        <input type="number" value={arr[1] ?? 0}
               onChange={(e) => onChange([arr[0] ?? 0, Number(e.target.value)])}
               className="w-24 px-2 py-1.5 rounded-lg text-xs outline-none" style={st} />
      </>
    );
  }
  return (
    <input type="number" value={value ?? 0}
           onChange={(e) => onChange(Number(e.target.value))}
           className="w-32 px-2 py-1.5 rounded-lg text-xs outline-none" style={st} />
  );
}


function _defaultValue(meta) {
  if (!meta) return null;
  switch (meta.value_shape) {
    case "boolean": return true;
    case "string_list": return [];
    default: return 0;
  }
}
