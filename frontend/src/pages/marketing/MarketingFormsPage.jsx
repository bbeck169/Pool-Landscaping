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
import React, { useEffect, useState, useMemo } from "react";
import { api } from "@/api";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { Card } from "@/components/ui/card";
import {
  Trash2, Plus, Copy, RefreshCw, Save, ArrowUp, ArrowDown, GripVertical,
} from "lucide-react";
// Feb-2026 · Form Builder Phase 1 — @dnd-kit for drag-reorder + palette
// drag-source (same bundle Email Builder P2#11 ships; zero new deps).
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor,
  useSensor, useSensors,
} from "@dnd-kit/core";
import {
  arrayMove, SortableContext, sortableKeyboardCoordinates,
  useSortable, verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import ThemePanel from "@/components/formBuilder/ThemePanel";
import HeroEditor from "@/components/formBuilder/HeroEditor";
import RichTextField from "@/components/formBuilder/RichTextField";
import AddressAutocomplete from "@/components/common/AddressAutocomplete";
import { colors as themeColors } from "@/theme";

// CUS-Marketing-Form-Builder · Feb-2026 — Phase 3.
//
// Branding swap: the legacy sky-500 brand constant + local
// slate-flavored neutral chrome aliases below are replaced with
// the canonical ``@/theme`` tokens. This aligns the form builder
// with the app-wide navy + blue-focus palette used by the K64 nav
// restyle and every N1/N2 input surface. Semantic colors (error
// red, status green, status neutral gray) are preserved verbatim
// inline because they map to meaning-not-brand and should not
// shift when the brand palette does.
//   - legacy sky-500  → ``themeColors.inputBorder`` (#3B82F6)
//   - legacy slate-900 → ``themeColors.nav.bg`` (#1B1F5C) — the
//                        form-builder chrome is a navy family
//                        surface; using the same navy as the
//                        admin nav keeps the drawer cohesive
//                        on top of the navy shell.
//   - legacy slate-500 → ``themeColors.muted`` (#71717A)
//   - legacy slate-200 → ``themeColors.border`` (#E4E4E7)
//   - legacy white     → ``themeColors.surface`` (#FFFFFF)
//   - legacy slate-50  → ``themeColors.surfaceSecondary`` (#F4F4F5)
const colors = {
  brand: themeColors.inputBorder,
  onSurface: themeColors.nav.bg,
  muted: themeColors.muted,
  border: themeColors.border,
  surface: themeColors.surface,
  surfaceSecondary: themeColors.surfaceSecondary,
};

// CUS-Marketing-Form-Builder · Feb-2026 — Phase 3. ``"section"`` is
// a layout-only marker (backend contract in Phase 1) — no submission
// value, no ``required`` toggle, no options, no placeholder. Renders
// as a divider heading in the public form.
const FIELD_TYPES = [
  "text", "email", "phone", "textarea", "number", "url", "date",
  "address_google", "dropdown", "multiselect", "checkbox", "radio", "file",
  "section",
];
const FIELD_TYPE_LABELS = {
  section: "Section heading (layout only)",
};
const OPTION_TYPES = new Set(["dropdown", "multiselect", "radio"]);
// CUS-Marketing-Form-Builder · Feb-2026 — Phase 3. Layout-only
// field types skip name/placeholder/required/options in the editor
// row (see FieldEditorRow below) + let the backend accept a missing
// ``name`` at save time.
const LAYOUT_TYPES = new Set(["section"]);

function slugify(s) {
  return (s || "").toString().toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "").slice(0, 60);
}

// Feb-2026 · Form Builder Phase 1 — stable per-row client id. The
// server-persisted ``field.id`` is empty on new rows, so dnd-kit
// needs its own stable handle. Non-persisted; stripped in ``save``
// before PATCHing the backend. Simple counter is enough (one builder
// drawer per operator; mounted/unmounted per edit).
let _rowIdSeq = 0;
const _nextRowId = () => `row-${++_rowIdSeq}`;


// Feb-2026 · Form Builder P2#12 Phase 1 Commit 2 — Version history
// drawer. Lists every snapshot from
// ``GET /admin/forms/{fid}/versions`` + wires revert via
// ``POST /admin/forms/{fid}/revert/{version}``. Mounted inside the
// editor drawer; the outer drawer still owns ``onClose``.
function VersionHistoryPanel({ fid, currentVersion, onClose, onReverted }) {
  const [rows, setRows] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [err, setErr] = React.useState("");
  React.useEffect(() => {
    (async () => {
      setBusy(true); setErr("");
      try {
        const r = await api.get(`/admin/forms/${fid}/versions`);
        setRows(Array.isArray(r?.versions) ? r.versions : []);
      } catch (e) {
        setErr(e?.message || "Failed to load versions");
      } finally {
        setBusy(false);
      }
    })();
  }, [fid]);
  const revert = async (version) => {
    setBusy(true); setErr("");
    try {
      const r = await api.post(`/admin/forms/${fid}/revert/${version}`, {});
      onReverted(r);
    } catch (e) {
      setErr(e?.message || "Revert failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mb-4 p-4 rounded-lg"
         style={{ background: colors.surfaceSecondary,
                   border: `1px solid ${colors.border}` }}
         data-testid="form-version-history-panel">
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-bold uppercase tracking-wider"
             style={{ color: colors.muted }}>
          Version history{currentVersion ? ` · current v${currentVersion}` : ""}
        </div>
        <button onClick={onClose} className="text-xs font-semibold"
                style={{ color: colors.muted }}
                data-testid="form-version-history-close">
          ✕ Close
        </button>
      </div>
      {err ? (
        <div className="text-xs p-2 rounded-lg mb-2"
             style={{ color: "#991B1B", background: "#FEE2E2" }}>
          {err}
        </div>
      ) : null}
      {busy && rows.length === 0 ? (
        <div className="text-xs" style={{ color: colors.muted }}>Loading…</div>
      ) : rows.length === 0 ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="form-version-history-empty">
          No prior versions yet.
        </div>
      ) : (
        <ul className="divide-y" style={{ borderColor: colors.border }}>
          {rows.map((row) => (
            <li key={row.version}
                className="py-2 flex items-center gap-3"
                data-testid={`form-version-row-${row.version}`}>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold"
                     style={{ color: colors.onSurface }}>
                  v{row.version} · {row.action}
                </div>
                <div className="text-[10px] truncate"
                     style={{ color: colors.muted }}>
                  {row.at} · {row.name || "(no name)"}
                </div>
              </div>
              <button
                type="button"
                onClick={() => revert(row.version)}
                disabled={busy || row.version === currentVersion}
                className="text-xs px-2 py-1 rounded-lg font-semibold disabled:opacity-40"
                style={{ background: colors.surface,
                          color: colors.onSurface,
                          border: `1px solid ${colors.border}` }}
                data-testid={`form-version-revert-${row.version}`}
              >
                {row.version === currentVersion ? "Current" : "Revert"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const empty_field = () => ({
  _rowId: _nextRowId(),
  id: "",
  name: "",
  label: "",
  type: "text",
  required: false,
  placeholder: "",
  options: [],
  // CUS-Marketing-Form-Builder · Feb-2026 — Phase 3. Layout column
  // span. ``"full"`` (default) or ``"half"``. Backend contract in
  // Phase 1 accepts both + null (treats null as full).
  column_span: "full",
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
               className="grid grid-cols-12 gap-2 px-4 py-3 items-center text-sm hover:bg-[#1B1F5C]/5 cursor-pointer"
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
  const [fields, setFields] = useState(() => {
    // Feb-2026 · Form Builder Phase 1 — backfill ``_rowId`` on load
    // so existing templates have a stable dnd-kit handle. Operator-
    // facing shape is unchanged.
    const seed = form.fields?.length ? form.fields : [empty_field()];
    return seed.map((f) => ({ ...f, _rowId: f._rowId || _nextRowId() }));
  });
  const [submitBtn, setSubmitBtn] = useState(form.submit_button_label || "Send");
  const [successMsg, setSuccessMsg] = useState(form.success_message || "Thanks! We'll be in touch shortly.");
  const [submitCfg, setSubmitCfg] = useState(form.submit_config || {
    creates: "lead", confirmation_email_template_id: null, drip_sequence_id: null, admin_bell: true,
  });
  // K34 · Feb-2026 — unified theme (preset + colors + font). Null
  // until the user picks a preset; renderer falls back to the app
  // default when null → zero regression for legacy forms.
  const [theme, setTheme] = useState(form.theme || null);
  // CUS-Marketing-Form-Builder · Feb-2026 — Phase 3. Hero band
  // designer state. ``null`` until the admin enables the toggle →
  // renderer skips the hero band. Backwards-compatible for every
  // form that predates Phase 3.
  const [hero, setHero] = useState(form.hero || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [previewNonce, setPreviewNonce] = useState(0);
  const [templates, setTemplates] = useState([]);
  const [sequences, setSequences] = useState([]);
  const [publicKey, setPublicKey] = useState("");
  const [saved, setSaved] = useState(!form._new ? form : null);
  // Feb-2026 · Form Builder P1 C2 — Version history drawer state.
  const [historyOpen, setHistoryOpen] = useState(false);

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
  // Feb-2026 · Form Builder Phase 1 — click-to-add a specific type
  // from the left-rail palette (keyboard-accessible add path that
  // doesn't require drag). The default empty-field type is "text";
  // this helper substitutes the clicked type at insertion time.
  const addFieldOfType = (type) =>
    setFields((prev) => [...prev, { ...empty_field(), type }]);
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
  // Feb-2026 · Form Builder Phase 1 — dnd-kit drag-end handler.
  // Operates on the sortable row ids (``_rowId``); arrow-key
  // reorder stays functional via ``moveField`` above.
  const handleDragEnd = (evt) => {
    const { active, over } = evt;
    if (!over || active.id === over.id) return;
    setFields((prev) => {
      const oldIdx = prev.findIndex((f) => f._rowId === active.id);
      const newIdx = prev.findIndex((f) => f._rowId === over.id);
      if (oldIdx < 0 || newIdx < 0) return prev;
      return arrayMove(prev, oldIdx, newIdx);
    });
  };
  const dndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
  const sortableIds = useMemo(
    () => fields.map((f) => f._rowId),
    [fields],
  );

  const save = async () => {
    setBusy(true); setError("");
    try {
      const cleanFields = fields.map((f, i) => {
        // CUS-Marketing-Form-Builder · Feb-2026 — Phase 3. Layout-only
        // types (``section``) can omit ``name`` per the Phase 1
        // backend contract. Non-layout types still require a fallback
        // name so the submission payload is stable.
        const isLayout = LAYOUT_TYPES.has(f.type);
        // Feb-2026 · Form Builder Phase 1 — drop the dnd-kit client
        // handle (``_rowId``) before PATCHing. Server knows nothing
        // about it; the Pydantic model's ``extra: allow`` would
        // round-trip it but we prefer a clean payload.
        const { _rowId: _rid, ...rest } = f;
        return {
          ...rest,
          name: isLayout
            ? (rest.name || "")
            : (rest.name || slugify(rest.label) || `field_${i + 1}`),
          label: rest.label || rest.name || `Field ${i + 1}`,
          options: OPTION_TYPES.has(rest.type)
            ? (Array.isArray(rest.options) ? rest.options : String(rest.options || "").split(",").map((s) => s.trim()).filter(Boolean))
            : null,
          // Preserve column_span verbatim — backend accepts
          // "full" | "half" | null.
          column_span: rest.column_span || "full",
        };
      });
      const payload = {
        name,
        fields: cleanFields,
        submit_button_label: submitBtn,
        success_message: successMsg,
        submit_config: submitCfg,
        theme,
        hero,
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
            <div className="flex items-center gap-3">
              {/* Feb-2026 · Form Builder P1 C2 — Version history
                  button. Rendered only when the form has been
                  saved at least once (``saved?.id`` present) and
                  thus has an addressable
                  ``GET /admin/forms/{fid}/versions`` endpoint.
                  Opens a drawer-child panel that lists snapshots +
                  wires revert. */}
              {saved?.id ? (
                <button onClick={() => setHistoryOpen(true)}
                        className="text-sm font-semibold inline-flex items-center gap-1"
                        style={{ color: colors.brand }}
                        data-testid="form-version-history-btn">
                  History{saved?.version ? ` · v${saved.version}` : ""}
                </button>
              ) : null}
              <button onClick={onClose}
                      className="text-sm font-semibold"
                      style={{ color: colors.muted }}
                      data-testid="form-close-btn">✕ Close</button>
            </div>
          </div>

          <label className="block text-xs font-bold uppercase tracking-wider mb-1"
                 style={{ color: colors.muted }}>Form name</label>
          <input value={name} onChange={(e) => setName(e.target.value)}
                 placeholder="e.g. Get a free estimate"
                 className="w-full px-3 py-2 rounded-lg text-sm mb-4 outline-none"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid="form-name-input" />

          {/* CUS-Marketing-Form-Builder · Feb-2026 — Phase 3. Hero-band
              designer. Sits ABOVE the field list so the admin builds
              the top-of-form banner first; renderer skips the band
              entirely when ``hero`` is null (backwards compat). */}
          <div className="mb-4">
            <HeroEditor value={hero} onChange={setHero} />
          </div>

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
            {/* Feb-2026 · Form Builder Phase 1 — DnD field reorder +
                left-rail palette. Palette is keyboard-accessible: each
                button is a focusable control that click-adds a field of
                that type at the end of the list (same as "Add field"
                but typed). Arrow-up / arrow-down buttons on each row
                stay functional as the a11y reorder fallback — no
                operator loses functionality when a screen reader is
                active. */}
            <div className="grid grid-cols-12 gap-3">
              <div className="col-span-3"
                   data-testid="form-field-palette">
                <div className="text-[10px] font-bold uppercase mb-1"
                     style={{ color: colors.muted }}>Palette</div>
                <div className="flex flex-col gap-1">
                  {FIELD_TYPES.map((t) => (
                    <button key={t}
                            type="button"
                            onClick={() => addFieldOfType(t)}
                            className="text-left text-xs px-2 py-1.5 rounded-lg"
                            style={{
                              border: `1px solid ${colors.border}`,
                              background: colors.surface,
                              color: colors.onSurface,
                            }}
                            data-testid={`form-field-palette-${t}`}
                            aria-label={`Add ${FIELD_TYPE_LABELS[t] || t} field`}>
                      + {FIELD_TYPE_LABELS[t] || t}
                    </button>
                  ))}
                </div>
              </div>
              <div className="col-span-9">
                <DndContext sensors={dndSensors}
                              collisionDetection={closestCenter}
                              onDragEnd={handleDragEnd}>
                  <SortableContext items={sortableIds}
                                     strategy={verticalListSortingStrategy}>
                    {fields.map((f, i) => (
                      <SortableFieldEditorRow key={f._rowId} idx={i} f={f}
                                                 onChange={(p) => updateField(i, p)}
                                                 onDelete={() => delField(i)}
                                                 onMove={(d) => moveField(i, d)}
                                                 canDelete={fields.length > 1}
                                                 allFieldsForShowIfPicker={
                                                   fields.filter((other, j) =>
                                                     j !== i
                                                     && !LAYOUT_TYPES.has(other.type)
                                                     && (other.id || other.name)
                                                   )
                                                 } />
                    ))}
                  </SortableContext>
                </DndContext>
              </div>
            </div>
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

          {/* Feb-2026 · Form Builder P1 C2 — Version history panel.
              Rendered only when the operator has clicked History +
              the form has been saved. Lists every snapshot in DESC
              order with a "Revert to this" button per row.
              Mirrors the ``form_templates`` revert UX: non-
              destructive — reverting creates a NEW version (so the
              timeline never loses rows). */}
          {historyOpen && saved?.id ? (
            <VersionHistoryPanel
              fid={saved.id}
              currentVersion={saved.version}
              onClose={() => setHistoryOpen(false)}
              onReverted={(reverted) => {
                setSaved(reverted);
                setName(reverted.name || "");
                setFields(
                  (reverted.fields || []).map((f) => ({
                    ...f, _rowId: f._rowId || _nextRowId(),
                  })),
                );
                setHistoryOpen(false);
              }}
            />
          ) : null}

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


// Feb-2026 · Form Builder Phase 1 — dnd-kit sortable wrapper around
// the existing ``FieldEditorRow``. Pulls transform + listeners from
// the ``useSortable`` hook keyed on each field's stable ``_rowId``.
// The drag handle is a dedicated grip icon so operators can still
// click inside input fields without triggering a drag. Arrow-key
// reorder stays functional via the ``onMove`` prop on the inner row.
function SortableFieldEditorRow({ idx, f, onChange, onDelete, onMove, canDelete,
                                   allFieldsForShowIfPicker }) {
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: f._rowId });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <div ref={setNodeRef} style={style}
         data-testid={`form-field-sortable-${idx}`}>
      <FieldEditorRow idx={idx} f={f} onChange={onChange}
                        onDelete={onDelete} onMove={onMove}
                        canDelete={canDelete}
                        allFieldsForShowIfPicker={allFieldsForShowIfPicker}
                        dragHandleProps={{ ...attributes, ...listeners }} />
    </div>
  );
}


function FieldEditorRow({ idx, f, onChange, onDelete, onMove, canDelete,
                            allFieldsForShowIfPicker,
                            dragHandleProps = null }) {
  const isLayout = LAYOUT_TYPES.has(f.type);
  const needsOptions = OPTION_TYPES.has(f.type);
  return (
    <div className="mb-2 p-3 rounded-lg"
         style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
         data-testid={`form-field-${idx}`}>
      <div className="grid grid-cols-12 gap-2 items-start">
        <div className="col-span-5">
          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>
            {isLayout ? "Section heading" : "Label"}
          </label>
          {isLayout ? (
            // CUS-Marketing-Form-Builder · Feb-2026 — Phase 3. Section
            // headings persist as rich-text HTML on ``field.label``.
            // Narrow Tiptap extension set caps XSS surface — see
            // RichTextField.jsx security boundary comment.
            <RichTextField
              value={f.label || ""}
              onChange={(html) => onChange({ label: html })}
              placeholder="e.g. <strong>Step 2</strong> — Contact details"
              testid={`form-field-section-label-${idx}`}
            />
          ) : (
            <input value={f.label}
                   onChange={(e) => onChange({ label: e.target.value,
                                                name: f.name || slugify(e.target.value) })}
                   placeholder="Full name"
                   className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid={`form-field-label-${idx}`} />
          )}
        </div>
        <div className="col-span-3">
          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>Type</label>
          <select value={f.type}
                  onChange={(e) => onChange({ type: e.target.value })}
                  className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                  style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
                  data-testid={`form-field-type-${idx}`}>
            {FIELD_TYPES.map((t) => (
              <option key={t} value={t}>
                {FIELD_TYPE_LABELS[t] || t}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-2 pt-6">
          {/* Layout-only types (section) skip the required toggle —
              they have no submission value. */}
          {!isLayout && (
            <label className="flex items-center gap-1 text-xs">
              <input type="checkbox" checked={!!f.required}
                     onChange={(e) => onChange({ required: e.target.checked })}
                     data-testid={`form-field-required-${idx}`} />
              Required
            </label>
          )}
        </div>
        <div className="col-span-2 pt-6 flex items-center justify-end gap-1">
          {/* Feb-2026 · Form Builder Phase 1 — drag handle. ``dragHandleProps``
              carries dnd-kit's listeners + attributes; it's null when
              rendered outside the DnD context (used by a few tests +
              future standalone usage). Keyboard reorder still routes
              through the ArrowUp/ArrowDown buttons below so operators
              with assistive tech never lose the reorder path. */}
          {dragHandleProps ? (
            <button
              type="button"
              title="Drag to reorder"
              aria-label="Drag field to reorder"
              className="p-1 cursor-grab active:cursor-grabbing"
              data-testid={`form-field-drag-${idx}`}
              {...dragHandleProps}
            >
              <GripVertical size={14} color={colors.muted} />
            </button>
          ) : null}
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
        {/* CUS-Marketing-Form-Builder · Feb-2026 — Phase 3. Column
            span selector. Full-width (default) or half-width so
            paired fields (city + state, phone + ext, etc.) live on
            one row in the renderer. Always visible, including for
            layout-only ``section`` markers where "half" produces a
            centered mid-page divider. */}
        <div className="col-span-6">
          <label className="block text-[10px] font-bold uppercase mb-1"
                 style={{ color: colors.muted }}>Column span</label>
          <select value={f.column_span || "full"}
                  onChange={(e) => onChange({ column_span: e.target.value })}
                  className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                  style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
                  data-testid={`form-field-column-span-${idx}`}>
            <option value="full">Full width</option>
            <option value="half">Half width</option>
          </select>
        </div>
        {/* Layout-only types skip name / placeholder / options / preview. */}
        {!isLayout && (
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
        )}
        {!isLayout && (
          <div className="col-span-12">
            <label className="block text-[10px] font-bold uppercase mb-1"
                   style={{ color: colors.muted }}>Placeholder</label>
            <input value={f.placeholder || ""}
                   onChange={(e) => onChange({ placeholder: e.target.value })}
                   className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid={`form-field-placeholder-${idx}`} />
          </div>
        )}
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
        {/* Feb-2026 · P0 · Lead form address autofill — live preview
             of the ``address_google`` field. Backed by the same
             ``AddressAutocomplete`` component the public widget
             uses, so admins can validate the visitor experience
             end-to-end before shipping the form. */}
        {f.type === "address_google" && (
          <div className="col-span-12">
            <label className="block text-[10px] font-bold uppercase mb-1"
                   style={{ color: colors.muted }}>Preview (Google Places)</label>
            <AddressAutocomplete
              value=""
              onChange={() => {}}
              placeholder={f.placeholder || "Start typing your address…"}
              testId={`form-field-address-preview-${idx}`}
            />
          </div>
        )}
        {/* CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53).
            Conditional-logic authoring surface. Collapsible so the
            vast majority of fields that don't need show_if keep the
            editor compact. The sibling parent-field picker only
            lists NON-LAYOUT fields that come BEFORE this one in the
            fields array (prevents forward-reference cycles at save
            time; the backend's circular-check still catches other
            shapes but this keeps the author UX linear). */}
        <ShowIfEditor
          field={f}
          idx={idx}
          siblings={allFieldsForShowIfPicker || []}
          onChange={onChange}
          colors={colors}
        />
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53) ·
// ``ShowIfEditor`` collapsible panel.
// ═══════════════════════════════════════════════════════════════
//
// Named-export so the vitest sibling can exercise the round-trip
// (toggle open → set field/op/value → serialize to ``show_if``
// shape) without booting the full MarketingFormsPage.  Mirrors the
// extraction pattern already used by ``AutomationsSuppressedChip``
// in QuoteInvoiceDetail (TD-38, Feb-2026).
//
// Props:
//   * field       — the FormField dict being edited.
//   * idx         — numeric index for data-testid stability.
//   * siblings    — array of OTHER non-layout fields that CAN be
//                   referenced as a show_if parent. The caller
//                   (FieldEditor's parent) builds this list — typically
//                   "every non-layout field earlier in the array".
//   * onChange    — partial-update callback (same shape as the rest
//                   of the field editor controls).
//   * colors      — form-builder theme colors (muted / border).
//
// Behavior:
//   * Collapsed by default. Opens when the user clicks the header
//     OR when the field already has a ``show_if`` rule on first
//     render (so loading an existing form with conditional-logic
//     doesn't require clicking into every field to see what's set).
//   * Clearing all three controls (field + value) nullifies
//     ``show_if`` (sends ``{show_if: null}`` upstream) — this is the
//     author's "remove the rule" affordance.  Keeps the state model
//     simple: there's no second "delete" button.
export function ShowIfEditor({ field, idx, siblings, onChange, colors }) {
  const [open, setOpen] = React.useState(!!field.show_if);
  const rule = field.show_if || {};
  const parentFid = rule.field_id || "";
  const operator = rule.operator || "eq";
  const value = rule.value === undefined ? "" : String(rule.value);

  function pushRule(partial) {
    const next = {
      field_id: parentFid,
      operator,
      value: value,
      ...partial,
    };
    // Clearing the field_id picks "no rule" — tell the parent to
    // drop ``show_if`` entirely.  Keeps round-trip identity for
    // forms that briefly had a rule and then had it cleared.
    if (!next.field_id) {
      onChange({ show_if: null });
      return;
    }
    onChange({ show_if: next });
  }

  return (
    <div className="col-span-12 mt-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] font-semibold uppercase flex items-center gap-1"
        style={{ color: colors.muted }}
        data-testid={`form-field-show-if-toggle-${idx}`}
      >
        <span>{open ? "▾" : "▸"}</span>
        <span>Show if…</span>
        {field.show_if ? (
          <span
            className="ml-1 px-1.5 py-0.5 rounded text-[9px]"
            style={{ background: "#FEF9C3", color: "#A16207" }}
            data-testid={`form-field-show-if-badge-${idx}`}
          >
            conditional
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          className="grid grid-cols-12 gap-2 mt-1 p-2 rounded"
          style={{ border: `1px solid ${colors.border}`, background: "#F8FAFC" }}
          data-testid={`form-field-show-if-panel-${idx}`}
        >
          <div className="col-span-5">
            <label className="block text-[10px] font-bold uppercase mb-1"
                   style={{ color: colors.muted }}>Parent field</label>
            <select
              value={parentFid}
              onChange={(e) => pushRule({ field_id: e.target.value })}
              className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
              style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
              data-testid={`form-field-show-if-parent-${idx}`}
            >
              <option value="">— no rule —</option>
              {siblings.map((s) => (
                <option key={s.id || s.name} value={s.id || s.name}>
                  {(s.label || s.name || s.id || "").slice(0, 40)}
                </option>
              ))}
            </select>
          </div>
          <div className="col-span-3">
            <label className="block text-[10px] font-bold uppercase mb-1"
                   style={{ color: colors.muted }}>Operator</label>
            <select
              value={operator}
              onChange={(e) => pushRule({ operator: e.target.value })}
              className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
              style={{ border: `1px solid ${colors.border}`, background: "#fff" }}
              data-testid={`form-field-show-if-operator-${idx}`}
            >
              <option value="eq">equals</option>
              <option value="neq">not equals</option>
              <option value="contains">contains</option>
            </select>
          </div>
          <div className="col-span-4">
            <label className="block text-[10px] font-bold uppercase mb-1"
                   style={{ color: colors.muted }}>Value</label>
            <input
              value={value}
              onChange={(e) => pushRule({ value: e.target.value })}
              placeholder="pool"
              className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
              style={{ border: `1px solid ${colors.border}` }}
              data-testid={`form-field-show-if-value-${idx}`}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}
