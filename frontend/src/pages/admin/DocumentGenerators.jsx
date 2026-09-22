/**
 * Phase T4 — Document Generators (admin only).
 * 2 tabs: Checklist Template Creator + Quick Service Report.
 */
import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, FileText, Wrench, Download, Save, Trash2 } from "lucide-react";
import { api, api_base } from "@/api";
import { colors } from "@/theme";

const TABS = [
  { key: "checklist", label: "Checklist Template", icon: Wrench },
  { key: "quick",     label: "Quick Service Report", icon: FileText },
];

async function downloadPdf(url, filename) {
  const token = localStorage.getItem("token");
  const r = await fetch(`${api_base()}${url}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}

async function postPdf(url, body, filename) {
  const token = localStorage.getItem("token");
  const r = await fetch(`${api_base()}${url}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}

// ── T4.1 Checklist Template ──────────────────────────────────────────
function ChecklistPanel() {
  const [canonical, setCanonical] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [t, setT] = useState({
    name: "Weekly Pool Checklist",
    visit_type: "pool",
    readings_rows: ["pH", "Chlorine", "Alkalinity", "Calcium Hardness", "CYA"],
    checklist_items: [],
    include_photos_section: true,
    include_customer_signature_line: true,
    include_tech_signature_line: true,
    include_notes_section: true,
    include_notes_internal: true,
    include_notes_customer: true,
  });
  const [err, setErr] = useState(null);
  const [flash, setFlash] = useState(null);

  useEffect(() => {
    api.get("/documents/canonical-lists").then(setCanonical).catch(() => {});
    api.get("/documents/checklist-templates").then(r => setTemplates(r.rows || [])).catch(() => {});
  }, []);

  const save = async () => {
    setErr(null);
    try {
      const saved = await api.post("/documents/checklist-template/save", t);
      setT({ ...t, id: saved.id });
      setFlash({ ok: true, msg: `Saved ✓ (${saved.id.slice(0, 8)})` });
      const r = await api.get("/documents/checklist-templates");
      setTemplates(r.rows || []);
    } catch (e) { setErr(e.message); }
    setTimeout(() => setFlash(null), 3000);
  };

  const dl = async () => {
    if (!t.id) { await save(); }
    try {
      await downloadPdf(`/documents/checklist-template/${t.id}/pdf`,
                        `checklist-${(t.name || "template").replace(/\s+/g, "-").toLowerCase()}.pdf`);
    } catch (e) { setErr(e.message); }
  };

  const del = async (id) => {
    try {
      await api.delete(`/documents/checklist-templates/${id}`);
      const r = await api.get("/documents/checklist-templates");
      setTemplates(r.rows || []);
      if (t.id === id) setT({ ...t, id: undefined });
    } catch (e) { setErr(e.message); }
  };

  const cloneToEdit = async (id) => {
    setErr(null);
    try {
      const clone = await api.post(`/documents/checklist-templates/${id}/clone`, {});
      const r = await api.get("/documents/checklist-templates");
      setTemplates(r.rows || []);
      // Load the fresh tenant-scoped clone into the editor.
      const {is_system, cloned_from_id, cloned_from_code, created_by, created_at, updated_at, tenant_id, ...editable} = clone;
      setT(editable);
      setFlash({ ok: true, msg: `Cloned ✓ — now editable` });
    } catch (e) { setErr(e.message); }
    setTimeout(() => setFlash(null), 3000);
  };

  const toggleReading = (k) => {
    setT({...t, readings_rows: t.readings_rows.includes(k)
        ? t.readings_rows.filter(r => r !== k)
        : [...t.readings_rows, k]});
  };

  return (
    <div className="grid md:grid-cols-2 gap-4">
      <div className="rounded-2xl p-6 space-y-4"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="checklist-form">
        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Template name</span>
          <input value={t.name} onChange={(e) => setT({...t, name: e.target.value})}
                 className="mt-1 w-full rounded-lg px-3 py-2"
                 style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                 data-testid="cl-name" />
        </label>
        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Visit type</span>
          <select value={t.visit_type} onChange={(e) => setT({...t, visit_type: e.target.value})}
                  className="mt-1 w-full rounded-lg px-3 py-2"
                  style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                  data-testid="cl-vt">
            <option value="pool">Pool</option>
            <option value="landscape">Landscape</option>
            <option value="both">Both</option>
          </select>
        </label>

        {canonical ? (
          <>
            <div>
              <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>Readings rows</div>
              <div className="flex flex-wrap gap-1">
                {canonical.standard_reading_keys.map(k => (
                  <button key={k} onClick={() => toggleReading(k)}
                          className="px-2 py-1 rounded-lg text-xs font-semibold"
                          style={{
                            backgroundColor: t.readings_rows.includes(k) ? colors.brand : colors.surface,
                            color: t.readings_rows.includes(k) ? "#fff" : colors.onSurface,
                            border: `1px solid ${t.readings_rows.includes(k) ? colors.brand : colors.border}`,
                          }}
                          data-testid={`cl-reading-${k}`}>{k}</button>
                ))}
              </div>
            </div>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <div className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Checklist items</div>
                <button onClick={() => setT({...t, checklist_items: canonical.pool_checklist})}
                        className="text-xs font-semibold" style={{color: colors.brand}}
                        data-testid="cl-load-pool">Load pool</button>
                <button onClick={() => setT({...t, checklist_items: canonical.landscape_checklist})}
                        className="text-xs font-semibold" style={{color: colors.brand}}
                        data-testid="cl-load-landscape">Load landscape</button>
              </div>
              <textarea value={t.checklist_items.join("\n")}
                        onChange={(e) => setT({...t, checklist_items: e.target.value.split("\n").filter(Boolean)})}
                        rows={7}
                        className="w-full rounded-lg px-3 py-2 text-sm"
                        style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                        data-testid="cl-items"
                        placeholder="One item per line" />
            </div>
          </>
        ) : null}

        <div className="space-y-2 text-sm">
          {[
            {k: "include_photos_section", label: "Photos section"},
            {k: "include_notes_section", label: "Notes section"},
            {k: "include_notes_customer", label: "  ↳ Customer Notes"},
            {k: "include_notes_internal", label: "  ↳ Internal Notes"},
            {k: "include_tech_signature_line", label: "Tech signature"},
            {k: "include_customer_signature_line", label: "Customer signature"},
          ].map(o => (
            <label key={o.k} className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={!!t[o.k]}
                     onChange={(e) => setT({...t, [o.k]: e.target.checked})}
                     data-testid={`cl-${o.k}`} />
              <span style={{ color: colors.onSurface }}>{o.label}</span>
            </label>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <button onClick={save} className="flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-semibold"
                  style={{backgroundColor: colors.brand, color: "#fff"}}
                  data-testid="cl-save">
            <Save size={14} /> Save
          </button>
          <button onClick={dl} className="flex items-center gap-1 rounded-lg px-3 py-2 text-sm font-semibold"
                  style={{backgroundColor: colors.surface, color: colors.brand, border: `1px solid ${colors.brand}`}}
                  data-testid="cl-download">
            <Download size={14} /> Download PDF
          </button>
          {flash ? <span className="text-xs" style={{color: flash.ok ? "#166534" : "#991B1B"}}>{flash.msg}</span> : null}
        </div>
        {err ? <div className="text-sm" style={{color: "#991B1B"}}>{err}</div> : null}
      </div>

      <div className="rounded-2xl p-6"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
           data-testid="checklist-preview">
        <div className="text-xs font-bold uppercase tracking-wider mb-3" style={{ color: colors.muted }}>Preview (simplified)</div>
        <div className="rounded-lg p-4" style={{backgroundColor: "#fff", border: `1px solid ${colors.border}`, color: "#000"}}>
          <div className="text-lg font-bold">{t.name}</div>
          <div className="text-xs mt-1">Visit type: {t.visit_type}</div>
          <div className="text-sm mt-3">Property: __________________</div>
          <div className="text-sm">Date: __________________ Tech: __________________</div>
          {t.readings_rows.length > 0 && (
            <>
              <div className="text-sm font-bold mt-3">Chemistry Readings</div>
              <div className="text-xs">{t.readings_rows.map(r => `${r}: ______`).join(" · ")}</div>
            </>
          )}
          {t.checklist_items.length > 0 && (
            <>
              <div className="text-sm font-bold mt-3">Checklist</div>
              <ul className="text-xs list-none">
                {t.checklist_items.map((it, i) => <li key={i}>☐ {it}</li>)}
              </ul>
            </>
          )}
          {t.include_notes_section && t.include_notes_customer && <div className="text-xs mt-3"><b>Customer Notes:</b> ______</div>}
          {t.include_notes_section && t.include_notes_internal && <div className="text-xs"><b>Internal Notes:</b> ______</div>}
          {t.include_tech_signature_line && <div className="text-xs mt-3">Tech signature: __________________ Date: ______</div>}
          {t.include_customer_signature_line && <div className="text-xs">Customer signature: __________________ Date: ______</div>}
        </div>

        <div className="mt-4">
          <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>Saved templates ({templates.length})</div>
          <ul className="text-sm space-y-1">
            {templates.map(tpl => {
              const isSystem = !!tpl.is_system;
              return (
                <li key={tpl.id} className="flex items-center gap-2" data-testid={`cl-tpl-${tpl.id}`}>
                  {!isSystem ? (
                    <button onClick={() => setT(tpl)} className="flex-1 text-left font-semibold"
                            style={{color: colors.brand}}
                            data-testid={`cl-tpl-open-${tpl.id}`}>{tpl.name}</button>
                  ) : (
                    <span className="flex-1 text-left font-semibold" style={{color: colors.onSurface}}>
                      {tpl.name}
                    </span>
                  )}
                  {isSystem ? (
                    <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full"
                          style={{ backgroundColor: `${colors.brand}22`, color: colors.brand, border: `1px solid ${colors.brand}55` }}
                          data-testid={`cl-tpl-system-badge-${tpl.id}`}>
                      System
                    </span>
                  ) : null}
                  {isSystem ? (
                    <button onClick={() => cloneToEdit(tpl.id)}
                            className="text-xs font-semibold rounded-lg px-2 py-1"
                            style={{ backgroundColor: colors.brand, color: "#fff" }}
                            data-testid={`cl-tpl-clone-${tpl.id}`}>
                      Clone to Edit
                    </button>
                  ) : (
                    <button onClick={() => del(tpl.id)} data-testid={`cl-tpl-delete-${tpl.id}`}>
                      <Trash2 size={14} color="#991B1B" />
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
}

// ── T4.2 Quick Service Report ─────────────────────────────────────────
function QuickPanel() {
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({
    customer_name: "",
    property_address: "",
    visit_date: today,
    tech_name: "",
    visit_type: "pool",
    chemical_readings: [{label: "pH", value: ""}, {label: "Chlorine", value: ""}],
    chemicals_added: [],
    checklist_items: [],
    customer_notes: "",
    include_signatures: true,
  });
  const [err, setErr] = useState(null);

  const generate = async () => {
    setErr(null);
    try {
      await postPdf("/documents/quick-service-report", {
        ...f,
        chemical_readings: f.chemical_readings.filter(r => r.value),
      }, `service-report-${f.visit_date}.pdf`);
    } catch (e) { setErr(e.message); }
  };

  return (
    <div className="rounded-2xl p-6 space-y-3"
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid="quick-form">
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Customer name</span>
          <input value={f.customer_name} onChange={(e) => setF({...f, customer_name: e.target.value})}
                 className="mt-1 w-full rounded-lg px-3 py-2"
                 style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                 data-testid="qsr-customer" />
        </label>
        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Property address</span>
          <input value={f.property_address} onChange={(e) => setF({...f, property_address: e.target.value})}
                 className="mt-1 w-full rounded-lg px-3 py-2"
                 style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                 data-testid="qsr-address" />
        </label>
        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Visit date</span>
          <input type="date" value={f.visit_date} onChange={(e) => setF({...f, visit_date: e.target.value})}
                 className="mt-1 w-full rounded-lg px-3 py-2"
                 style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                 data-testid="qsr-date" />
        </label>
        <label className="block">
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Tech name</span>
          <input value={f.tech_name} onChange={(e) => setF({...f, tech_name: e.target.value})}
                 className="mt-1 w-full rounded-lg px-3 py-2"
                 style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                 data-testid="qsr-tech" />
        </label>
      </div>

      <div>
        <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>Chemistry readings</div>
        {f.chemical_readings.map((cr, i) => (
          <div key={i} className="flex gap-2 mb-1">
            <input value={cr.label} onChange={(e) => {
              const nx = [...f.chemical_readings]; nx[i].label = e.target.value; setF({...f, chemical_readings: nx});
            }} placeholder="pH" className="flex-1 rounded-lg px-2 py-1"
              style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
              data-testid={`qsr-cr-label-${i}`} />
            <input value={cr.value} onChange={(e) => {
              const nx = [...f.chemical_readings]; nx[i].value = e.target.value; setF({...f, chemical_readings: nx});
            }} placeholder="value" className="flex-1 rounded-lg px-2 py-1"
              style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
              data-testid={`qsr-cr-value-${i}`} />
          </div>
        ))}
        <button onClick={() => setF({...f, chemical_readings: [...f.chemical_readings, {label: "", value: ""}]})}
                className="text-xs font-semibold" style={{color: colors.brand}} data-testid="qsr-add-cr">+ Add reading</button>
      </div>

      <label className="block">
        <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Checklist items completed (one per line)</span>
        <textarea value={f.checklist_items.join("\n")}
                  onChange={(e) => setF({...f, checklist_items: e.target.value.split("\n").filter(Boolean)})}
                  rows={4}
                  className="mt-1 w-full rounded-lg px-3 py-2 text-sm"
                  style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                  data-testid="qsr-checklist" />
      </label>

      <label className="block">
        <span className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Customer notes</span>
        <textarea value={f.customer_notes} onChange={(e) => setF({...f, customer_notes: e.target.value})}
                  rows={3}
                  className="mt-1 w-full rounded-lg px-3 py-2 text-sm"
                  style={{backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface}}
                  data-testid="qsr-notes" />
      </label>

      <label className="flex items-center gap-2 cursor-pointer">
        <input type="checkbox" checked={f.include_signatures}
               onChange={(e) => setF({...f, include_signatures: e.target.checked})}
               data-testid="qsr-sigs" />
        <span className="text-sm" style={{ color: colors.onSurface }}>Include signature lines</span>
      </label>

      <button onClick={generate}
              className="w-full py-2 rounded-xl font-bold flex items-center justify-center gap-1"
              style={{ backgroundColor: colors.brand, color: "#fff" }}
              data-testid="qsr-generate">
        <Download size={14} /> Generate &amp; Download PDF
      </button>
      {err ? <div className="text-sm" style={{color: "#991B1B"}}>{err}</div> : null}
    </div>
  );
}

export default function DocumentGenerators() {
  const nav = useNavigate();
  const [tab, setTab] = useState("checklist");
  const Panel = { checklist: ChecklistPanel, quick: QuickPanel }[tab];
  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="document-generators-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="docs-back-btn">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
            <FileText size={22} style={{ color: colors.brand }} />
            Document Generators
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Admin-only. Printable checklist templates · Quick service report PDF.
          </p>
        </div>
      </div>
      <div className="flex gap-2 mb-4 overflow-x-auto pb-1">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
                    className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold whitespace-nowrap"
                    style={{
                      backgroundColor: active ? colors.brand : colors.surface,
                      color: active ? "#fff" : colors.onSurface,
                      border: `1px solid ${active ? colors.brand : colors.border}`,
                    }}
                    data-testid={`docs-tab-${t.key}`}>
              <Icon size={14} /> {t.label}
            </button>
          );
        })}
      </div>
      <Panel />
    </div>
  );
}
