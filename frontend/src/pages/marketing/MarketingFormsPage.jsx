// Feb-2026 · Slice H2 — Form Builder admin UI.
//
// List page + editor drawer. Editor has:
//   • Field builder (add / reorder / delete / edit)
//   • Submit-config panel (creates target, confirmation email
//     template, drip sequence, admin bell)
//   • Live preview via /widget-demo?key=…&form_id=… iframe
//   • Embed snippet section with copy button
//
// Backend contract lives in /app/backend/routers/marketing_forms.py.
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { Card } from "@/components/ui/card";
import { Trash2, Plus, Copy, RefreshCw, Save, ArrowUp, ArrowDown } from "lucide-react";
import ThemePanel from "@/components/formBuilder/ThemePanel";

const colors = {
  brand: "#0EA5E9",
  onSurface: "#0F172A",
  muted: "#64748B",
  border: "#E2E8F0",
  surface: "#FFFFFF",
  surfaceSecondary: "#F8FAFC",
};

const FIELD_TYPES = [
  "text", "email", "phone", "textarea", "number", "url", "date",
  "address_google", "dropdown", "multiselect", "checkbox", "radio", "file",
];
const OPTION_TYPES = new Set(["dropdown", "multiselect", "radio"]);

function slugify(s) {
  return (s || "").toString().toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "").slice(0, 60);
}

const empty_field = () => ({
  id: "",
  name: "",
  label: "",
  type: "text",
  required: false,
  placeholder: "",
  options: [],
});

export default function MarketingFormsPage() {
  const [forms, setForms] = useState([]);
  const [editing, setEditing] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = () => {
    setLoading(true);
    api.get("/admin/forms")
      .then((r) => setForms(r || []))
      .catch((e) => setError(e?.message || "Failed to load"))
      .finally(() => setLoading(false));
  };
  useEffect(() => { refresh(); }, []);

  const createNew = () => {
    setEditing({
      _new: true,
      name: "",
      slug: "",
      fields: [empty_field()],
      submit_button_label: "Send",
      success_message: "Thanks! We'll be in touch shortly.",
      submit_config: {
        creates: "lead",
        confirmation_email_template_id: null,
        drip_sequence_id: null,
        admin_bell: true,
      },
      active: true,
    });
  };

  const toggleActive = async (form) => {
    try {
      await api.patch(`/admin/forms/${form.id}`, { active: !form.active });
      refresh();
    } catch (e) { setError(e?.message || "Toggle failed"); }
  };
  const remove = async (form) => {
    const ok = await mustConfirm({
      title: `Delete "${form.name}"?`,
      description: "The form URL will stop accepting submissions. Existing submissions stay in the leads log.",
      tone: "danger", confirmText: "Delete", requireTypeConfirm: true,
    });
    if (!ok) return;
    try { await api.delete(`/admin/forms/${form.id}`); refresh(); }
    catch (e) { setError(e?.message || "Delete failed"); }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto" data-testid="admin-forms-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Forms
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Build embeddable web forms. Every submission becomes a lead
            (or customer) with optional auto-confirmation email + drip enrolment.
          </p>
        </div>
        <button onClick={createNew}
                className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
                style={{ background: colors.brand }}
                data-testid="form-create-btn">
          <Plus size={14} /> New form
        </button>
      </div>

      {error && <div className="mb-3 text-sm p-2 rounded-lg"
                     style={{ color: "#991B1B", background: "#FEE2E2" }}>{error}</div>}

      <Card className="p-0 overflow-hidden">
        <div className="grid grid-cols-12 gap-2 px-4 py-2 text-[11px] uppercase font-semibold"
             style={{ color: colors.muted, background: colors.surfaceSecondary,
                      borderBottom: `1px solid ${colors.border}` }}>
          <div className="col-span-4">Name</div>
          <div className="col-span-2">Fields</div>
          <div className="col-span-2">Submissions</div>
          <div className="col-span-2">Active</div>
          <div className="col-span-2 text-right">Actions</div>
        </div>
        {loading && <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>}
        {!loading && forms.length === 0 && (
          <div className="p-8 text-sm text-center" style={{ color: colors.muted }}
               data-testid="admin-forms-empty">
            No forms yet. Click "New form" above to build your first one.
          </div>
        )}
        {forms.map((f) => (
          <div key={f.id}
               data-testid={`form-row-${f.id}`}
               className="grid grid-cols-12 gap-2 px-4 py-3 items-center text-sm hover:bg-slate-50 cursor-pointer"
               style={{ borderBottom: `1px solid ${colors.border}` }}
               onClick={() => setEditing(f)}>
            <div className="col-span-4 font-semibold" style={{ color: colors.onSurface }}>
              {f.name}
              <div className="text-[10px]" style={{ color: colors.muted }}>{f.slug}</div>
            </div>
            <div className="col-span-2" style={{ color: colors.muted }}>{(f.fields || []).length}</div>
            <div className="col-span-2" style={{ color: colors.muted }}>
              {f.submission_count || 0}
            </div>
            <div className="col-span-2">
              <button data-testid={`form-active-toggle-${f.id}`}
                      className="text-xs font-semibold px-2 py-1 rounded-full"
                      style={{ background: f.active ? "#DCFCE7" : "#F3F4F6",
                               color: f.active ? "#166534" : "#6B7280" }}
                      onClick={(e) => { e.stopPropagation(); toggleActive(f); }}>
                {f.active ? "Active" : "Inactive"}
              </button>
            </div>
            <div className="col-span-2 text-right">
              <button onClick={(e) => { e.stopPropagation(); remove(f); }}
                      className="p-1 rounded hover:bg-red-50" title="Delete"
                      data-testid={`form-delete-${f.id}`}>
                <Trash2 size={14} color="#DC2626" />
              </button>
            </div>
          </div>
        ))}
      </Card>

      {editing && (
        <FormEditorDrawer
          form={editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); refresh(); }}
        />
      )}
    </div>
  );
}


function FormEditorDrawer({ form, onClose, _onSaved }) {
  const [name, setName] = useState(form.name || "");
  const [fields, setFields] = useState(form.fields?.length ? form.fields : [empty_field()]);
  const [submitBtn, setSubmitBtn] = useState(form.submit_button_label || "Send");
  const [successMsg, setSuccessMsg] = useState(form.success_message || "Thanks! We'll be in touch shortly.");
  const [submitCfg, setSubmitCfg] = useState(form.submit_config || {
    creates: "lead", confirmation_email_template_id: null, drip_sequence_id: null, admin_bell: true,
  });
  // K34 · Feb-2026 — unified theme (preset + colors + font). Null
  // until the user picks a preset; renderer falls back to the app
  // default when null → zero regression for legacy forms.
  const [theme, setTheme] = useState(form.theme || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previewNonce, setPreviewNonce] = useState(0);
  const [templates, setTemplates] = useState([]);
  const [sequences, setSequences] = useState([]);
  const [publicKey, setPublicKey] = useState("");
  const [saved, setSaved] = useState(!form._new ? form : null);

  useEffect(() => {
    api.get("/marketing/templates").then((r) =>
      setTemplates((r || []).filter((t) => t.channel === "email"))
    ).catch(() => {});
    api.get("/marketing/sequences").then((r) => {
      const arr = Array.isArray(r) ? r : (r?.sequences || []);
      setSequences(arr);
    }).catch(() => {});
    api.get("/tenants/mine/widget-config").then((r) => setPublicKey(r.public_widget_key || ""))
      .catch(() => {});
  }, []);

  const updateField = (idx, patch) => {
    setFields((prev) => prev.map((f, i) => i === idx ? { ...f, ...patch } : f));
  };
  const addField = () => setFields((prev) => [...prev, empty_field()]);
  const delField = (idx) => setFields((prev) => prev.filter((_, i) => i !== idx));
  const moveField = (idx, dir) => {
    setFields((prev) => {
      const target = idx + dir;
      if (target < 0 || target >= prev.length) return prev;
      const next = prev.slice();
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };

  const save = async () => {
    setBusy(true); setError("");
    try {
      const cleanFields = fields.map((f, i) => ({
        ...f,
        name: f.name || slugify(f.label) || `field_${i + 1}`,
        label: f.label || f.name || `Field ${i + 1}`,
        options: OPTION_TYPES.has(f.type)
          ? (Array.isArray(f.options) ? f.options : String(f.options || "").split(",").map((s) => s.trim()).filter(Boolean))
          : null,
      }));
      const payload = {
        name,
        fields: cleanFields,
        submit_button_label: submitBtn,
        success_message: successMsg,
        submit_config: submitCfg,
        theme,
      };
      let out;
      if (form._new) out = await api.post("/admin/forms", payload);
      else           out = await api.patch(`/admin/forms/${form.id}`, payload);
      setSaved(out);
      setPreviewNonce((n) => n + 1);
      // Keep drawer open so user can copy snippet / preview live.
    } catch (e) {
      setError(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  const canPreview = !!saved?.id && !!publicKey;
  const snippet = saved && publicKey ?
    `<script async defer\n  src="${window.location.origin}/widget/form.js"\n  data-widget-key="${publicKey}"\n  data-form-id="${saved.id}"></script>` : "";

  const [copied, setCopied] = useState(false);
  const copySnippet = () => {
    try { navigator.clipboard?.writeText(snippet); } catch {}
    setCopied(true); setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-40 flex justify-end"
         style={{ background: "rgba(15,23,42,.35)" }}
         onClick={onClose}
         data-testid="form-edit-drawer">
      <div className="bg-white w-full max-w-3xl overflow-y-auto"
           style={{ height: "100vh" }}
           onClick={(e) => e.stopPropagation()}>
        <div className="p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-bold" style={{ color: colors.onSurface }}>
              {form._new ? "New form" : "Edit form"}
            </h2>
            <button onClick={onClose}
                    className="text-sm font-semibold"
                    style={{ color: colors.muted }}
                    data-testid="form-close-btn">✕ Close</button>
          </div>

          <label className="block text-xs font-bold uppercase tracking-wider mb-1"
                 style={{ color: colors.muted }}>Form name</label>
          <input value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="e.g. Get a free estimate"
                 className="w-full px-3 py-2 rounded-lg text-sm mb-4 outline-none"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid="form-name-input" />

          <div className="mb-4">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-bold uppercase tracking-wider"
                   style={{ color: colors.muted }}>Fields</div>
              <button onClick={addField}
                      className="text-xs font-semibold flex items-center gap-1"
                      style={{ color: colors.brand }}
                      data-testid="form-add-field-btn">
                <Plus size={12} /> Add field
              </button>
            </div>
            {fields.map((f, i) => (
              <FieldEditorRow key={i} idx={i} f={f}
                              onChange={(p) => updateField(i, p)}
                              onDelete={() => delField(i)}
                              onMove={(d) => moveField(i, d)}
                              canDelete={fields.length > 1} />
            ))}
          </div>

          <div className="mb-4 p-4 rounded-lg"
               style={{ background: colors.surfaceSecondary,
                        border: `1px solid ${colors.border}` }}
               data-testid="form-submit-config-panel">
            <div className="text-xs font-bold uppercase tracking-wider mb-2"
                 style={{ color: colors.muted }}>Submit action</div>

            <div className="flex items-center gap-4 mb-3 flex-wrap">
              {["lead", "customer", "both"].map((v) => (
                <label key={v} className="flex items-center gap-2 text-sm">
                  <input type="radio" name="creates"
                         checked={submitCfg.creates === v}
                         onChange={() => setSubmitCfg({ ...submitCfg, creates: v })}
                         data-testid={`form-submit-config-creates-${v}`} />
                  Create {v}
                </label>
              ))}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-[10px] font-bold uppercase mb-1"
                       style={{ color: colors.muted }}>Confirmation email (M3)</label>
                <select value={submitCfg.confirmation_email_template_id || ""}
                        onChange={(e) => setSubmitCfg({
                          ...submitCfg,
                          confirmation_email_template_id: e.target.value || null,
                        })}
                        className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                        style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
                        data-testid="form-submit-config-email-select">
                  <option value="">— none —</option>
                  {templates.map((t) => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[10px] font-bold uppercase mb-1"
                       style={{ color: colors.muted }}>Drip automation (M5)</label>
                <select value={submitCfg.drip_sequence_id || ""}
                        onChange={(e) => setSubmitCfg({
                          ...submitCfg,
                          drip_sequence_id: e.target.value || null,
                        })}
                        className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                        style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
                        data-testid="form-submit-config-drip-select">
                  <option value="">— none —</option>
                  {sequences.map((s) => (
                    <option key={s.id} value={s.id}>{s.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox"
                     checked={!!submitCfg.admin_bell}
                     onChange={(e) => setSubmitCfg({ ...submitCfg, admin_bell: e.target.checked })}
                     data-testid="form-submit-config-bell-toggle" />
              Ring the admin bell on new submissions
            </label>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4">
            <div>
              <label className="block text-[10px] font-bold uppercase mb-1"
                     style={{ color: colors.muted }}>Submit button label</label>
              <input value={submitBtn} onChange={(e) => setSubmitBtn(e.target.value)}
                     className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                     style={{ border: `1px solid ${colors.border}` }}
                     data-testid="form-submit-btn-label-input" />
            </div>
            <div>
              <label className="block text-[10px] font-bold uppercase mb-1"
                     style={{ color: colors.muted }}>Success message</label>
              <input value={successMsg} onChange={(e) => setSuccessMsg(e.target.value)}
                     className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                     style={{ border: `1px solid ${colors.border}` }}
                     data-testid="form-success-msg-input" />
            </div>
          </div>

          {/* K34 · Feb-2026 — Unified theme picker. Renders 5 presets +
              Customize expand + font stacks. Emits a ``theme`` object
              that persists on save + is read by every public renderer. */}
          <div className="mb-4">
            <ThemePanel value={theme} onChange={setTheme} />
          </div>

          {error && <div className="mb-3 text-sm p-2 rounded-lg"
                         style={{ color: "#991B1B", background: "#FEE2E2" }}>{error}</div>}

          <div className="flex justify-end gap-2 mb-6">
            <button onClick={save} disabled={busy || !name.trim()}
                    className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                    style={{ background: colors.brand }}
                    data-testid="form-save-btn">
              <Save size={14} /> {busy ? "Saving…" : "Save form"}
            </button>
          </div>

          {saved && publicKey && (
            <>
              <div className="pt-4" style={{ borderTop: `1px solid ${colors.border}` }}>
                <div className="text-xs font-bold uppercase tracking-wider mb-1"
                     style={{ color: colors.muted }}>Embed snippet</div>
                <pre className="text-xs font-mono p-3 rounded-lg overflow-x-auto"
                     style={{ background: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}` }}
                     data-testid="form-embed-snippet-code">
{snippet}
                </pre>
                <div className="flex items-center gap-2 mt-2">
                  <button onClick={copySnippet}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                          style={{ background: colors.surfaceSecondary,
                                   border: `1px solid ${colors.border}` }}
                          data-testid="form-embed-copy-btn">
                    <Copy size={12} className="inline mr-1" />
                    {copied ? "Copied ✓" : "Copy"}
                  </button>
                  <button onClick={() => setPreviewNonce((n) => n + 1)}
                          className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                          style={{ background: colors.surfaceSecondary,
                                   border: `1px solid ${colors.border}` }}
                          data-testid="form-embed-preview-refresh-btn">
                    <RefreshCw size={12} className="inline mr-1" />
                    Refresh
                  </button>
                </div>
                <div className="mt-4">
                  <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
                       style={{ color: colors.muted }}>Live preview</div>
                  {canPreview && (
                    <iframe key={previewNonce}
                            src={`/widget-demo?key=${encodeURIComponent(publicKey)}&form_id=${saved.id}&t=${previewNonce}`}
                            title="Form live preview"
                            data-testid="form-embed-preview-iframe"
                            style={{
                              width: "100%",
                              height: 520,
                              border: `1px solid ${colors.border}`,
                              borderRadius: 12,
                              background: "#fff",
                            }} />
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}


function FieldEditorRow({ idx, f, onChange, onDelete, onMove, canDelete }) {
  const needsOptions = OPTION_TYPES.has(f.type);
  return (
    <div className="mb-2 p-3 rounded-lg"
         style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
         data-testid={`form-field-${idx}`}>
      <div className="grid grid-cols-12 gap-2 items-start">
        <div className="col-span-5">
          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>Label</label>
          <input value={f.label}
                 onChange={(e) => onChange({ label: e.target.value,
                                              name: f.name || slugify(e.target.value) })}
                 placeholder="Full name"
                 className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid={`form-field-label-${idx}`} />
        </div>
        <div className="col-span-3">
          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>Type</label>
          <select value={f.type}
                  onChange={(e) => onChange({ type: e.target.value })}
                  className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                  style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
                  data-testid={`form-field-type-${idx}`}>
            {FIELD_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="col-span-2 pt-6">
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={!!f.required}
                   onChange={(e) => onChange({ required: e.target.checked })}
                   data-testid={`form-field-required-${idx}`} />
            Required
          </label>
        </div>
        <div className="col-span-2 pt-6 flex items-center justify-end gap-1">
          <button onClick={() => onMove(-1)} title="Move up" className="p-1"
                  data-testid={`form-field-up-${idx}`}>
            <ArrowUp size={14} />
          </button>
          <button onClick={() => onMove(1)} title="Move down" className="p-1"
                  data-testid={`form-field-down-${idx}`}>
            <ArrowDown size={14} />
          </button>
          {canDelete && (
            <button onClick={onDelete} title="Delete field" className="p-1"
                    data-testid={`form-field-delete-${idx}`}>
              <Trash2 size={14} color="#DC2626" />
            </button>
          )}
        </div>
      </div>
      <div className="grid grid-cols-12 gap-2 mt-2">
        <div className="col-span-6">
          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>Field name (slug)</label>
          <input value={f.name || ""}
                 onChange={(e) => onChange({ name: slugify(e.target.value) })}
                 placeholder="full_name"
                 className="w-full px-2 py-1.5 rounded-lg text-sm outline-none font-mono"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid={`form-field-name-${idx}`} />
        </div>
        <div className="col-span-6">
          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>Placeholder</label>
          <input value={f.placeholder || ""}
                 onChange={(e) => onChange({ placeholder: e.target.value })}
                 className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid={`form-field-placeholder-${idx}`} />
        </div>
        {needsOptions && (
          <div className="col-span-12">
            <label className="block text-[10px] font-bold uppercase mb-1"
                   style={{ color: colors.muted }}>Options (comma-separated)</label>
            <input value={(f.options || []).join(", ")}
                   onChange={(e) => onChange({
                     options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                   })}
                   placeholder="Pool, Landscape, Both"
                   className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid={`form-field-options-${idx}`} />
          </div>
        )}
      </div>
    </div>
  );
}
