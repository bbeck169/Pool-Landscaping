/**
 * Admin editor for `service_report_templates`.
 * Tabs: Pool | Landscape | Generic. PUT-with-full-payload for simplicity;
 * per-field endpoints are available on the backend but not needed for MVP.
 */
import React, { useEffect, useState } from 'react';
import { api } from "@/api";
import { colors, gradients } from "@/theme";
import {
  Save, RotateCcw, Plus, Trash2, ClipboardCheck, FlaskConical, Beaker, Tag,
} from "lucide-react";

const KINDS = [
  { key: "pool", label: "Pool" },
  { key: "landscape", label: "Landscape" },
  { key: "generic", label: "Generic" },
];

const nid = () => Math.random().toString(36).slice(2, 10);

function ChipRow({ items, onAdd, onRemove, placeholder }) {
  const [draft, setDraft] = useState("");
  return (
    <div className="flex flex-wrap gap-2 items-center">
      {items.map((v) => (
        <span key={v} className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-bold"
              style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
              data-testid={`chip-${v}`}>
          {v}
          <button onClick={() => onRemove(v)} className="opacity-70 hover:opacity-100">×</button>
        </span>
      ))}
      <input value={draft} onChange={(e) => setDraft(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === "Enter" && draft.trim()) {
                 onAdd(draft.trim()); setDraft("");
               }
             }}
             placeholder={placeholder} className="px-2 py-1 rounded-lg text-sm"
             style={{ border: `1px solid ${colors.border}`, minWidth: 120 }}/>
    </div>
  );
}

export default function ServiceTemplatesEditor() {
  const [kind, setKind] = useState("pool");
  const [tpl, setTpl] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  const isPool = kind === "pool";

  const load = async () => {
    const all = await api.get("/settings/service-templates");
    setTpl(all);
    setDirty(false);
  };
  useEffect(() => { load(); }, []);

  const current = tpl?.[kind];
  const upd = (patch) => {
    setTpl({ ...tpl, [kind]: { ...current, ...patch } });
    setDirty(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      // Normalize checklist to include labels only + required flags.
      const checklist_items = (current.checklist_items || []).map((c) =>
        typeof c === "string" ? { id: nid(), label: c, required: false } : c);
      const payload = {
        kind,
        checklist_items,
        chemical_reading_fields: current.chemical_reading_fields || [],
        chemicals_catalog: current.chemicals_catalog || [],
        chemical_units: current.chemical_units || [],
      };
      await api.put("/settings/service-templates", payload);
      setToast("Saved"); setTimeout(() => setToast(""), 2500);
      await load();
    } catch (e) { alert(e.message); }
    finally { setSaving(false); }
  };

  const resetDefaults = async () => {
    if (!confirm(`Restore built-in defaults for the ${kind} template? Your customizations will be lost.`)) return;
    await api.post(`/settings/service-templates/${kind}/reset-defaults`);
    setToast("Defaults restored"); setTimeout(() => setToast(""), 2500);
    await load();
  };

  if (!tpl || !current) return (
    <div className="p-8" style={{ color: colors.muted }} data-testid="tpl-loading">Loading templates…</div>
  );

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="service-templates-editor">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>Service Report Templates</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Customize checklists, chemical readings, chemicals, and units per template kind.
            Changes apply to <b>your tenant only</b>.
          </p>
          {current.updated_by && (
            <p className="text-xs mt-1" style={{ color: colors.muted }}>
              Last edited by {current.updated_by} · {current.updated_at ? new Date(current.updated_at).toLocaleString() : ""}
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <button onClick={resetDefaults} className="px-3 py-2 rounded-xl text-sm font-semibold flex items-center gap-1"
                  style={{ backgroundColor: colors.surface, color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                  data-testid="tpl-reset-btn">
            <RotateCcw size={13}/> Reset to Defaults
          </button>
          <button onClick={save} disabled={!dirty || saving}
                  className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50 flex items-center gap-1"
                  style={{ background: gradients.navyToGreen.css }}
                  data-testid="tpl-save-btn">
            <Save size={13}/> {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>

      {toast && (
        <div className="mb-4 px-3 py-2 rounded-lg text-sm font-semibold inline-block"
             style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
             data-testid="tpl-toast">{toast}</div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 mb-6" data-testid="tpl-tabs">
        {KINDS.map((k) => (
          <button key={k.key} onClick={() => setKind(k.key)}
                  className="px-4 py-2 rounded-xl text-sm font-bold transition-colors"
                  style={{
                    backgroundColor: kind === k.key ? colors.brand : colors.surface,
                    color: kind === k.key ? "#fff" : colors.onSurface,
                    border: `1px solid ${kind === k.key ? colors.brand : colors.border}`,
                  }}
                  data-testid={`tpl-tab-${k.key}`}>
            {k.label}
          </button>
        ))}
      </div>

      {/* Checklist Items */}
      <SectionCard title="Checklist Items" icon={<ClipboardCheck size={16}/>} testId="tpl-checklist">
        <div className="space-y-2">
          {(current.checklist_items || []).map((it, i) => {
            const item = typeof it === "string" ? { id: nid(), label: it, required: false } : it;
            return (
              <div key={item.id || i} className="grid grid-cols-12 gap-2 items-center"
                   data-testid={`tpl-checklist-row-${i}`}>
                <input value={item.label || ""}
                       onChange={(e) => {
                         const next = [...current.checklist_items];
                         next[i] = { ...item, label: e.target.value };
                         upd({ checklist_items: next });
                       }}
                       className="col-span-9 px-2 py-2 rounded-lg text-sm"
                       style={{ border: `1px solid ${colors.border}` }}
                       data-testid={`tpl-checklist-label-${i}`}/>
                <label className="col-span-2 flex items-center gap-1 text-xs" style={{ color: colors.muted }}>
                  <input type="checkbox" checked={!!item.required}
                         onChange={(e) => {
                           const next = [...current.checklist_items];
                           next[i] = { ...item, required: e.target.checked };
                           upd({ checklist_items: next });
                         }}
                         data-testid={`tpl-checklist-req-${i}`}/>
                  Required
                </label>
                <button onClick={() => {
                          const next = current.checklist_items.filter((_, x) => x !== i);
                          upd({ checklist_items: next });
                        }}
                        className="col-span-1 p-2 rounded"
                        style={{ color: colors.error }}
                        data-testid={`tpl-checklist-del-${i}`}>
                  <Trash2 size={14}/>
                </button>
              </div>
            );
          })}
        </div>
        <button onClick={() => {
                  const next = [...(current.checklist_items || []),
                    { id: nid(), label: "", required: false }];
                  upd({ checklist_items: next });
                }}
                className="mt-3 px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1"
                style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
                data-testid="tpl-checklist-add">
          <Plus size={13}/> Add checklist item
        </button>
      </SectionCard>

      {isPool && (
        <>
          <SectionCard title="Chemical Readings" icon={<FlaskConical size={16}/>} testId="tpl-readings">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
                    {["Name", "Unit", "Type", "Ideal", "Min", "Max", "Step", "Options", ""].map((h) => (
                      <th key={h} className="p-2 text-left font-semibold text-xs uppercase">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(current.chemical_reading_fields || []).map((f, i) => {
                    const arr = current.chemical_reading_fields;
                    const setField = (patch) => {
                      const next = [...arr]; next[i] = { ...f, ...patch };
                      upd({ chemical_reading_fields: next });
                    };
                    return (
                      <tr key={f.key || i} style={{ borderBottom: `1px solid ${colors.border}` }}
                          data-testid={`tpl-reading-row-${i}`}>
                        <td className="p-1"><input value={f.name || ""} onChange={(e) => setField({ name: e.target.value })}
                                                    className="w-32 px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1"><input value={f.unit || ""} onChange={(e) => setField({ unit: e.target.value })}
                                                    className="w-16 px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1">
                          <select value={f.type || "number"} onChange={(e) => setField({ type: e.target.value })}
                                  className="px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}>
                            <option value="number">number</option>
                            <option value="select">select</option>
                          </select>
                        </td>
                        <td className="p-1"><input value={f.ideal || ""} onChange={(e) => setField({ ideal: e.target.value })}
                                                    className="w-20 px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1"><input type="number" value={f.min ?? ""} onChange={(e) => setField({ min: e.target.value === "" ? null : parseFloat(e.target.value) })}
                                                    className="w-14 px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1"><input type="number" value={f.max ?? ""} onChange={(e) => setField({ max: e.target.value === "" ? null : parseFloat(e.target.value) })}
                                                    className="w-14 px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1"><input type="number" step="any" value={f.step ?? ""} onChange={(e) => setField({ step: e.target.value === "" ? null : parseFloat(e.target.value) })}
                                                    className="w-14 px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1"><input value={(f.options || []).join(", ")}
                                                    onChange={(e) => setField({ options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                                                    className="w-40 px-1 py-1 text-xs rounded"
                                                    style={{ border: `1px solid ${colors.border}` }}
                                                    placeholder="6.0, 6.1, ..."/></td>
                        <td className="p-1">
                          <button onClick={() => upd({ chemical_reading_fields: arr.filter((_, x) => x !== i) })}
                                  style={{ color: colors.error }}
                                  data-testid={`tpl-reading-del-${i}`}>
                            <Trash2 size={13}/>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <button onClick={() => upd({ chemical_reading_fields: [
                        ...(current.chemical_reading_fields || []),
                        { key: `custom_${nid()}`, name: "", unit: "", type: "number",
                          ideal: "", min: null, max: null, step: null, options: [] }
                      ]})}
                    className="mt-3 px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1"
                    style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
                    data-testid="tpl-reading-add">
              <Plus size={13}/> Add reading field
            </button>
          </SectionCard>

          <SectionCard title="Chemicals Catalog" icon={<Beaker size={16}/>} testId="tpl-catalog">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
                    {["Name", "Default Unit", "Common Units", "Amount Options", ""].map((h) => (
                      <th key={h} className="p-2 text-left font-semibold text-xs uppercase">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {(current.chemicals_catalog || []).map((c, i) => {
                    const arr = current.chemicals_catalog;
                    const setC = (patch) => {
                      const next = [...arr]; next[i] = { ...c, ...patch };
                      upd({ chemicals_catalog: next });
                    };
                    return (
                      <tr key={c.name + i} style={{ borderBottom: `1px solid ${colors.border}` }}
                          data-testid={`tpl-chem-row-${i}`}>
                        <td className="p-1"><input value={c.name || ""} onChange={(e) => setC({ name: e.target.value })}
                                                    className="w-40 px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1">
                          <select value={c.default_unit || ""} onChange={(e) => setC({ default_unit: e.target.value })}
                                  className="px-1 py-1 text-xs rounded" style={{ border: `1px solid ${colors.border}` }}>
                            <option value="">—</option>
                            {(current.chemical_units || []).map((u) => <option key={u} value={u}>{u}</option>)}
                          </select>
                        </td>
                        <td className="p-1"><input value={(c.common_units || []).join(", ")}
                                                    onChange={(e) => setC({ common_units: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                                                    className="w-40 px-1 py-1 text-xs rounded"
                                                    style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1"><input value={(c.amount_options || []).join(", ")}
                                                    onChange={(e) => setC({ amount_options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                                                    className="w-56 px-1 py-1 text-xs rounded"
                                                    style={{ border: `1px solid ${colors.border}` }}/></td>
                        <td className="p-1">
                          <button onClick={() => upd({ chemicals_catalog: arr.filter((_, x) => x !== i) })}
                                  style={{ color: colors.error }}
                                  data-testid={`tpl-chem-del-${i}`}>
                            <Trash2 size={13}/>
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <button onClick={() => upd({ chemicals_catalog: [
                        ...(current.chemicals_catalog || []),
                        { name: "", default_unit: (current.chemical_units || [])[0] || "lbs",
                          common_units: [], amount_options: [] }
                      ]})}
                    className="mt-3 px-3 py-1.5 rounded-lg text-xs font-bold flex items-center gap-1"
                    style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
                    data-testid="tpl-chem-add">
              <Plus size={13}/> Add chemical
            </button>
          </SectionCard>

          <SectionCard title="Global Chemical Units" icon={<Tag size={16}/>} testId="tpl-units">
            <ChipRow items={current.chemical_units || []}
                     placeholder="add unit + Enter"
                     onAdd={(v) => {
                       if ((current.chemical_units || []).includes(v)) return;
                       upd({ chemical_units: [...(current.chemical_units || []), v] });
                     }}
                     onRemove={(v) => upd({ chemical_units: current.chemical_units.filter((x) => x !== v) })}/>
          </SectionCard>
        </>
      )}
    </div>
  );
}

function SectionCard({ title, icon, children, testId }) {
  return (
    <div className="mb-5 rounded-2xl p-5"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid={testId}>
      <div className="flex items-center gap-2 mb-3">
        {icon}
        <h2 className="text-base font-bold" style={{ color: colors.onSurface }}>{title}</h2>
      </div>
      {children}
    </div>
  );
}
