/**
 * Feb-2026 · Marketing Slice M5b — Admin Sequences UI.
 *
 * Consumes the M5a backend contract at /api/marketing/sequences.
 * Renders the sequence list, a full editor drawer (header + step
 * builder + stop conditions + preview), an Enrolments panel, and an
 * "Enrol customers" modal that hits POST /:sid/enrol.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Plus, X as XIcon, Save, Trash2, Users, Play, Pause, ArrowUp, ArrowDown, Send, Eye, ChevronRight, Zap } from "lucide-react";
import { api } from "@/api";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { colors, brandGradientCss } from "@/theme";

const TRIGGER_LABELS = {
  service_completed: "Service completed",
  invoice_sent: "Invoice sent",
  invoice_past_due_N_days: "Invoice past due (N days)",
  customer_created: "New customer",
  birthday: "Birthday",
  review_left: "Review left",
  estimate_accepted: "Estimate accepted",
  // Feb-2026 · Day-before scheduled-job reminder — fires 24h before
  // the visit for both service AND repair jobs. Config-less.
  job_scheduled_reminder_1d: "Job scheduled reminder (1 day before)",
  manual: "Manual only",
  segment_join: "Segment join",
};

// Triggers that have no live event hook wired yet (empty after M5c —
// every trigger fires either instantly via the event bus or via the
// daily sweep).
const NOT_YET_WIRED_TRIGGERS = new Set();


export default function MarketingSequencesPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);

  const load = () => {
    setLoading(true);
    api.get("/marketing/sequences")
      .then((r) => setRows(r.sequences || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const toggleActive = async (row) => {
    try {
      await api.patch(`/marketing/sequences/${row.id}`, { active: !row.active });
      load();
    } catch {}
  };

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="marketing-sequences-page">
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Sequences
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            {rows.length} sequence{rows.length === 1 ? "" : "s"} — automate multi-step email & SMS follow-ups triggered by system events.
          </p>
        </div>
        <button
          onClick={() => setEditing({})}
          className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
          style={{ background: brandGradientCss }}
          data-testid="sequence-create-btn"
        >
          <Plus size={16} /> New sequence
        </button>
      </div>

      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        {loading ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center">
            <Zap size={28} className="mx-auto mb-3" style={{ color: colors.muted }} />
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
              No sequences yet
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Click "New sequence" to build your first drip.
            </div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
                {["Name", "Trigger", "Steps", "Active enrolments", "Updated", "Active", ""].map((h) => (
                  <th key={h}
                      className="text-left py-2 px-3 text-xs font-bold uppercase tracking-wide"
                      style={{ color: colors.muted }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}
                    onClick={() => setEditing(r)}
                    className="cursor-pointer hover:brightness-95"
                    style={{ borderBottom: `1px solid ${colors.divider}` }}
                    data-testid={`sequence-row-${r.id}`}>
                  <td className="py-3 px-3" style={{ color: colors.onSurface }}>
                    <div className="font-semibold">{r.name}</div>
                    {r.system ? (
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full mr-2"
                            style={{ backgroundColor: "#DBEAFE", color: "#1E3A8A" }}>
                        SEED
                      </span>
                    ) : null}
                    <span className="text-xs" style={{ color: colors.muted }}>
                      {r.description || ""}
                    </span>
                  </td>
                  <td className="py-3 px-3">
                    <TriggerBadge type={r.trigger_type} />
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.onSurface }}>
                    {(r.steps || []).length}
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.onSurface }}>
                    {r.active_enrolment_count ?? 0}
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.muted }}>
                    {String(r.updated_at || "").slice(0, 10)}
                  </td>
                  <td className="py-3 px-3">
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleActive(r); }}
                      className="px-2 py-0.5 rounded-full text-xs font-bold"
                      style={{
                        backgroundColor: r.active ? "#DCFCE7" : colors.surfaceTertiary,
                        color: r.active ? "#16A34A" : colors.muted,
                      }}
                      data-testid={`sequence-activate-toggle-${r.id}`}
                    >
                      {r.active ? "active" : "paused"}
                    </button>
                  </td>
                  <td className="py-3 px-3">
                    <ChevronRight size={16} style={{ color: colors.muted }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing !== null ? (
        <SequenceEditor initial={editing}
                        onClose={() => setEditing(null)}
                        onSaved={() => { setEditing(null); load(); }} />
      ) : null}
    </div>
  );
}


function TriggerBadge({ type }) {
  const label = TRIGGER_LABELS[type] || type;
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold"
          style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}>
      <Zap size={10} /> {label}
    </span>
  );
}


/* ─────────────────────────────────────────────────────────────────────
   Editor drawer
   ────────────────────────────────────────────────────────────────── */
function SequenceEditor({ initial, onClose, onSaved }) {
  const isNew = !initial?.id;
  const [name, setName] = useState(initial?.name || "");
  const [description, setDescription] = useState(initial?.description || "");
  const [triggerType, setTriggerType] = useState(initial?.trigger_type || "manual");
  const [triggerConfig, setTriggerConfig] = useState(initial?.trigger_config || {});
  const [steps, setSteps] = useState(
    (initial?.steps || []).map((s, i) => ({ ...s, order: s.order ?? i })),
  );
  const [stopOnReply, setStopOnReply] = useState(initial?.stop_on_reply ?? true);
  const [stopOnUnsubscribe, setStopOnUnsubscribe] = useState(initial?.stop_on_unsubscribe ?? true);

  const [triggersRegistry, setTriggersRegistry] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [segments, setSegments] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("editor");
  const [enroling, setEnroling] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    api.get("/marketing/sequences/triggers/registry")
      .then((r) => setTriggersRegistry(r.triggers || []))
      .catch(() => setTriggersRegistry([]));
    api.get("/marketing/templates?active=true")
      .then((r) => setTemplates(r.templates || []))
      .catch(() => setTemplates([]));
    api.get("/marketing/audience-segments")
      .then((r) => setSegments(r.segments || []))
      .catch(() => setSegments([]));
  }, []);

  const templatesByChannel = useMemo(() => ({
    email: templates.filter((t) => t.channel === "email"),
    sms: templates.filter((t) => t.channel === "sms"),
  }), [templates]);

  const addStep = () => {
    setSteps((s) => [
      ...s,
      {
        order: s.length,
        channel: "email",
        template_id: "",
        delay_from: s.length === 0 ? "trigger" : "previous_step",
        delay_hours: 24,
        condition: null,
      },
    ]);
  };

  const updateStep = (idx, patch) =>
    setSteps((s) => s.map((st, i) => (i === idx ? { ...st, ...patch } : st)));

  const removeStep = (idx) =>
    setSteps((s) =>
      s.filter((_, i) => i !== idx).map((st, i) => ({ ...st, order: i })),
    );

  const moveStep = (idx, dir) => {
    setSteps((s) => {
      const next = s.slice();
      const swap = idx + dir;
      if (swap < 0 || swap >= next.length) return s;
      [next[idx], next[swap]] = [next[swap], next[idx]];
      return next.map((st, i) => ({ ...st, order: i }));
    });
  };

  // ─ Client-side validation ─────────────────────────────────────────
  const stepErrors = steps.map((s) => {
    if (!s.template_id) return "Pick a template.";
    const tpl = templates.find((t) => t.id === s.template_id);
    if (tpl && tpl.channel !== s.channel) {
      return `Channel mismatch: template is ${tpl.channel}, step is ${s.channel}.`;
    }
    return null;
  });
  const canSave = !!name.trim() && !stepErrors.some(Boolean);

  const buildPayload = () => ({
    name: name.trim(),
    description: description.trim(),
    trigger_type: triggerType,
    trigger_config: triggerConfig,
    steps: steps.map((s, i) => ({
      order: i,
      channel: s.channel,
      template_id: s.template_id,
      delay_from: s.delay_from || "previous_step",
      delay_hours: Number(s.delay_hours) || 0,
      condition: s.condition || null,
    })),
    stop_on_reply: stopOnReply,
    stop_on_unsubscribe: stopOnUnsubscribe,
  });

  const save = async ({ activate = false } = {}) => {
    setBusy(true); setError("");
    try {
      const payload = { ...buildPayload(), active: activate ? true : (initial?.active ?? false) };
      if (isNew) {
        await api.post("/marketing/sequences", payload);
      } else {
        await api.patch(`/marketing/sequences/${initial.id}`, payload);
      }
      onSaved?.();
    } catch (e) { setError(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const del = async () => {
    if (!initial?.id) return;
    const ok = await mustConfirm({
      title: "Deactivate this sequence?",
      description: "Every active enrolment is halted immediately. No further steps will fire.",
      tone: "danger", confirmText: "Deactivate", requireTypeConfirm: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.del(`/marketing/sequences/${initial.id}`);
      onSaved?.();
    } catch (e) { setError(e?.message || "Delete failed"); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end"
         style={{ background: "rgba(15,23,42,0.55)" }}
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
         data-testid="sequence-edit-modal">
      <div className="w-full sm:w-[820px] h-full shadow-2xl flex flex-col"
           style={{ backgroundColor: colors.surface, borderLeft: `1px solid ${colors.border}` }}
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 pt-4 pb-3"
             style={{ borderBottom: `1px solid ${colors.divider}` }}>
          <div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {isNew ? "New sequence" : "Edit sequence"}
            </div>
            <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              {name || "Untitled"}
            </h2>
          </div>
          <button onClick={onClose} className="p-1" style={{ color: colors.muted }}>
            <XIcon size={18} />
          </button>
        </div>

        {!isNew ? (
          <div className="flex items-center gap-2 px-5 pt-3">
            <TabBtn active={tab === "editor"} onClick={() => setTab("editor")}
                    testId="sequence-editor-tab">Editor</TabBtn>
            <TabBtn active={tab === "enrolments"} onClick={() => setTab("enrolments")}
                    testId="sequence-enrolments-tab">Enrolments</TabBtn>
          </div>
        ) : null}

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {tab === "editor" ? (
            <>
              <input type="text" value={name} onChange={(e) => setName(e.target.value)}
                     placeholder="Sequence name"
                     className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                     style={{ backgroundColor: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                     data-testid="sequence-name-input" />
              <input type="text" value={description}
                     onChange={(e) => setDescription(e.target.value)}
                     placeholder="Description (optional)"
                     className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                     style={{ backgroundColor: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }} />

              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
                     style={{ color: colors.muted }}>TRIGGER</div>
                <select value={triggerType}
                        onChange={(e) => { setTriggerType(e.target.value); setTriggerConfig({}); }}
                        className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                        style={{ backgroundColor: colors.surface, color: colors.onSurface,
                                 border: `1px solid ${colors.border}` }}
                        data-testid="sequence-trigger-select"
                        data-e2e-testid="id-sequence-trigger-select">
                  {triggersRegistry.map((t) => (
                    <option key={t.type} value={t.type}>
                      {TRIGGER_LABELS[t.type] || t.type}
                      {NOT_YET_WIRED_TRIGGERS.has(t.type) ? "  (coming soon)" : ""}
                    </option>
                  ))}
                </select>
                {NOT_YET_WIRED_TRIGGERS.has(triggerType) ? (
                  <div className="mt-2 text-xs inline-flex items-center gap-1 px-2 py-1 rounded-md"
                       style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
                       data-testid="sequence-trigger-not-wired">
                    Coming soon — this trigger's event hook isn't wired yet; you can still design and manually enrol.
                  </div>
                ) : null}
                <TriggerConfigPanel type={triggerType} config={triggerConfig}
                                    onChange={setTriggerConfig} segments={segments} />
              </div>

              <div>
                <div className="flex items-center justify-between mb-2">
                  <div className="text-[10px] font-bold uppercase tracking-wider"
                       style={{ color: colors.muted }}>STEPS</div>
                  <button onClick={addStep}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold"
                          style={{ backgroundColor: colors.surfaceSecondary,
                                   color: colors.onSurface,
                                   border: `1px solid ${colors.border}` }}
                          data-testid="sequence-add-step-btn">
                    <Plus size={12} /> Add step
                  </button>
                </div>
                {steps.length === 0 ? (
                  <div className="text-xs p-3 rounded-lg"
                       style={{ color: colors.muted,
                                backgroundColor: colors.surfaceSecondary,
                                border: `1px dashed ${colors.border}` }}>
                    No steps yet. Add your first email or SMS above.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {steps.map((s, i) => (
                      <StepCard key={i} index={i} step={s}
                                templates={templatesByChannel}
                                error={stepErrors[i]}
                                onChange={(patch) => updateStep(i, patch)}
                                onRemove={() => removeStep(i)}
                                onUp={() => moveStep(i, -1)}
                                onDown={() => moveStep(i, +1)}
                                isFirst={i === 0}
                                isLast={i === steps.length - 1} />
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-xl p-3"
                   style={{ backgroundColor: colors.surfaceSecondary,
                            border: `1px solid ${colors.divider}` }}>
                <div className="text-[10px] font-bold uppercase tracking-wider mb-2"
                     style={{ color: colors.muted }}>STOP CONDITIONS</div>
                <label className="flex items-center gap-2 text-sm cursor-pointer">
                  <input type="checkbox" checked={stopOnReply}
                         onChange={(e) => setStopOnReply(e.target.checked)}
                         data-testid="sequence-stop-on-reply" />
                  <span style={{ color: colors.onSurface }}>Stop if customer replies</span>
                </label>
                <label className="flex items-center gap-2 text-sm cursor-pointer mt-1">
                  <input type="checkbox" checked={stopOnUnsubscribe}
                         onChange={(e) => setStopOnUnsubscribe(e.target.checked)}
                         data-testid="sequence-stop-on-unsub" />
                  <span style={{ color: colors.onSurface }}>Stop if customer unsubscribes</span>
                </label>
              </div>

              {error ? (
                <div className="text-sm" style={{ color: colors.error }}
                     data-testid="sequence-editor-error">{error}</div>
              ) : null}
            </>
          ) : (
            <EnrolmentsPanel sequenceId={initial.id} />
          )}
        </div>

        <div className="p-4 flex items-center justify-between gap-2 flex-wrap"
             style={{ borderTop: `1px solid ${colors.divider}` }}>
          <div className="flex items-center gap-2">
            {!isNew ? (
              <>
                <button onClick={del} disabled={busy}
                        className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
                        style={{ backgroundColor: colors.surfaceSecondary, color: colors.error }}
                        data-testid="sequence-delete-btn">
                  <Trash2 size={14} /> Delete
                </button>
                <button onClick={() => setEnroling(true)} disabled={busy}
                        className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
                        style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                        data-testid="sequence-enrol-btn">
                  <Users size={14} /> Enrol customers
                </button>
              </>
            ) : null}
            {steps.length > 0 && steps[0].template_id ? (
              <button onClick={() => setPreviewOpen(true)}
                      className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
                      style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                      data-testid="sequence-preview-step-btn">
                <Eye size={14} /> Preview step 1
              </button>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <button onClick={onClose}
                    className="px-4 py-2 rounded-xl text-sm font-semibold"
                    style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}>
              Cancel
            </button>
            <button onClick={() => save({ activate: false })}
                    disabled={busy || !canSave}
                    className="px-4 py-2 rounded-xl text-sm font-bold disabled:opacity-50"
                    style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                    data-testid="sequence-save-btn">
              <Save size={14} className="inline mr-1" />
              {busy ? "Saving…" : "Save"}
            </button>
            <button onClick={() => save({ activate: true })}
                    disabled={busy || !canSave}
                    className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                    style={{ background: brandGradientCss }}
                    data-testid="sequence-activate-toggle">
              <Play size={14} /> Save + Activate
            </button>
          </div>
        </div>
      </div>

      {enroling ? (
        <EnrolModal sequenceId={initial.id}
                    segments={segments}
                    onClose={() => setEnroling(false)}
                    onDone={() => setEnroling(false)} />
      ) : null}
      {previewOpen && steps[0]?.template_id ? (
        <TemplatePreviewModal templateId={steps[0].template_id}
                               onClose={() => setPreviewOpen(false)} />
      ) : null}
    </div>
  );
}


function TabBtn({ active, onClick, children, testId }) {
  return (
    <button onClick={onClick} data-testid={testId}
            className="px-3 py-1.5 rounded-lg text-xs font-bold"
            style={{
              backgroundColor: active ? colors.brandTertiary : "transparent",
              color: active ? colors.brand : colors.muted,
              border: `1px solid ${active ? colors.brand : "transparent"}`,
            }}>
      {children}
    </button>
  );
}


function TriggerConfigPanel({ type, config, onChange, segments }) {
  if (type === "invoice_past_due_N_days") {
    return (
      <div className="mt-2">
        <label className="text-xs" style={{ color: colors.muted }}>
          Days past due
        </label>
        <input type="number" min={0}
               value={config.days_past_due ?? 3}
               onChange={(e) =>
                 onChange({ ...config, days_past_due: Number(e.target.value) || 0 })
               }
               className="w-24 mt-1 ml-2 px-2 py-1.5 rounded-lg text-sm outline-none"
               style={{ backgroundColor: colors.surface, color: colors.onSurface,
                        border: `1px solid ${colors.border}` }}
               data-testid="sequence-trigger-cfg-days" />
      </div>
    );
  }
  if (type === "segment_join") {
    return (
      <div className="mt-2">
        <label className="text-xs" style={{ color: colors.muted }}>Segment</label>
        <select value={config.segment_id || ""}
                onChange={(e) => onChange({ ...config, segment_id: e.target.value })}
                className="w-full mt-1 px-2 py-1.5 rounded-lg text-sm outline-none"
                style={{ backgroundColor: colors.surface, color: colors.onSurface,
                         border: `1px solid ${colors.border}` }}
                data-testid="sequence-trigger-cfg-segment">
          <option value="">— pick a segment —</option>
          {segments.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </div>
    );
  }
  return null;
}


function StepCard({ index, step, templates, error, onChange, onRemove,
                    onUp, onDown, isFirst, isLast }) {
  const list = templates[step.channel] || [];
  return (
    <div className="rounded-xl p-3"
         style={{ backgroundColor: colors.surface,
                  border: `1px solid ${error ? colors.error : colors.border}` }}
         data-testid={`sequence-step-${index}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}>
            STEP {index + 1}
          </span>
          <select value={step.channel}
                  onChange={(e) => onChange({ channel: e.target.value, template_id: "" })}
                  className="px-2 py-1 rounded-lg text-xs outline-none"
                  style={{ backgroundColor: colors.surface, color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                  data-testid={`sequence-step-${index}-channel`}>
            <option value="email">email</option>
            <option value="sms">sms</option>
          </select>
        </div>
        <div className="flex items-center gap-1">
          <IconBtn disabled={isFirst} onClick={onUp} aria="Move up">
            <ArrowUp size={12} />
          </IconBtn>
          <IconBtn disabled={isLast} onClick={onDown} aria="Move down">
            <ArrowDown size={12} />
          </IconBtn>
          <IconBtn onClick={onRemove} aria="Remove"
                    testId={`sequence-step-${index}-remove`}>
            <Trash2 size={12} />
          </IconBtn>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div>
          <label className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>Template</label>
          <select value={step.template_id}
                  onChange={(e) => onChange({ template_id: e.target.value })}
                  className="w-full mt-1 px-2 py-1.5 rounded-lg text-xs outline-none"
                  style={{ backgroundColor: colors.surface, color: colors.onSurface,
                           border: `1px solid ${colors.border}` }}
                  data-testid={`sequence-step-${index}-template`}>
            <option value="">— pick a template —</option>
            {list.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.category})
              </option>
            ))}
          </select>
        </div>
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-[10px] font-bold uppercase tracking-wider"
                   style={{ color: colors.muted }}>Delay from</label>
            <select value={step.delay_from || "previous_step"}
                    onChange={(e) => onChange({ delay_from: e.target.value })}
                    className="w-full mt-1 px-2 py-1.5 rounded-lg text-xs outline-none"
                    style={{ backgroundColor: colors.surface, color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                    data-testid={`sequence-step-${index}-delayfrom`}>
              <option value="trigger">the trigger</option>
              <option value="previous_step">previous step</option>
            </select>
          </div>
          <div className="w-28">
            <label className="text-[10px] font-bold uppercase tracking-wider"
                   style={{ color: colors.muted }}>Hours</label>
            <input type="number" min={0} value={step.delay_hours ?? 24}
                   onChange={(e) =>
                     onChange({ delay_hours: Number(e.target.value) || 0 })
                   }
                   className="w-full mt-1 px-2 py-1.5 rounded-lg text-xs outline-none"
                   style={{ backgroundColor: colors.surface, color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                   data-testid={`sequence-step-${index}-delayhrs`} />
          </div>
        </div>
      </div>

      <div className="mt-2">
        <label className="text-[10px] font-bold uppercase tracking-wider"
               style={{ color: colors.muted }}>Condition (optional JSON)</label>
        <input type="text"
               value={step.condition ? JSON.stringify(step.condition) : ""}
               placeholder='e.g. {"if_engaged": true} — leave blank for none'
               onChange={(e) => {
                 const val = e.target.value.trim();
                 if (!val) return onChange({ condition: null });
                 try { onChange({ condition: JSON.parse(val) }); }
                 catch { /* keep typing */ }
               }}
               className="w-full mt-1 px-2 py-1.5 rounded-lg text-xs font-mono outline-none"
               style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                        border: `1px solid ${colors.border}` }}
               data-testid={`sequence-step-${index}-condition`} />
      </div>

      {error ? (
        <div className="mt-2 text-xs" style={{ color: colors.error }}
             data-testid={`sequence-step-${index}-error`}>{error}</div>
      ) : null}
    </div>
  );
}


function IconBtn({ children, onClick, disabled, aria, testId }) {
  return (
    <button onClick={onClick} disabled={disabled} aria-label={aria}
            data-testid={testId}
            className="p-1 rounded-md disabled:opacity-30"
            style={{ color: colors.muted,
                     border: `1px solid ${colors.border}`,
                     backgroundColor: colors.surface }}>
      {children}
    </button>
  );
}


/* ─────────────────────────────────────────────────────────────────────
   Enrolments panel — reads GET /:sid/enrolments, allows halt
   ────────────────────────────────────────────────────────────────── */
function EnrolmentsPanel({ sequenceId }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [customerNames, setCustomerNames] = useState({});

  const load = () => {
    setLoading(true);
    api.get(`/marketing/sequences/${sequenceId}/enrolments`)
      .then(async (r) => {
        const enrolments = r.enrolments || [];
        setRows(enrolments);
        // Hydrate customer names in bulk
        const ids = [...new Set(enrolments.map((e) => e.customer_id))];
        const map = {};
        await Promise.all(ids.map(async (cid) => {
          try {
            const c = await api.get(`/customers/${cid}`);
            map[cid] = c?.name || c?.first_name || cid;
          } catch { map[cid] = cid; }
        }));
        setCustomerNames(map);
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(load, [sequenceId]);

  const halt = async (eid) => {
    try {
      await api.post(`/marketing/sequences/${sequenceId}/halt/${eid}`);
      load();
    } catch {}
  };

  if (loading) {
    return <div className="text-sm text-center py-4" style={{ color: colors.muted }}>Loading enrolments…</div>;
  }
  if (!rows.length) {
    return (
      <div className="rounded-xl p-6 text-center"
           style={{ backgroundColor: colors.surfaceSecondary,
                    border: `1px dashed ${colors.border}` }}>
        <Users size={20} className="mx-auto mb-2" style={{ color: colors.muted }} />
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          No enrolments yet
        </div>
        <div className="text-xs mt-1" style={{ color: colors.muted }}>
          Use "Enrol customers" below to add people to this sequence.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl overflow-hidden"
         style={{ border: `1px solid ${colors.border}` }}>
      <table className="w-full text-sm">
        <thead>
          <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
            {["Customer", "Status", "Step", "Next send", "Trigger", ""].map((h) => (
              <th key={h}
                  className="text-left py-2 px-3 text-xs font-bold uppercase tracking-wide"
                  style={{ color: colors.muted }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => (
            <tr key={e.id} style={{ borderBottom: `1px solid ${colors.divider}` }}
                data-testid={`sequence-enrolment-row-${e.id}`}>
              <td className="py-2 px-3" style={{ color: colors.onSurface }}>
                {customerNames[e.customer_id] || e.customer_id}
              </td>
              <td className="py-2 px-3">
                <StatusPill status={e.status} />
              </td>
              <td className="py-2 px-3" style={{ color: colors.onSurface }}>
                {e.current_step ?? 0}
              </td>
              <td className="py-2 px-3" style={{ color: colors.muted }}>
                {e.next_send_at ? String(e.next_send_at).slice(0, 16).replace("T", " ") : "—"}
              </td>
              <td className="py-2 px-3" style={{ color: colors.muted }}>
                {e.trigger_source || "manual"}
              </td>
              <td className="py-2 px-3 text-right">
                {e.status === "active" ? (
                  <button onClick={() => halt(e.id)}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold"
                          style={{ backgroundColor: colors.surfaceSecondary,
                                   color: colors.error }}
                          data-testid={`sequence-halt-btn-${e.id}`}>
                    <Pause size={11} /> Halt
                  </button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function StatusPill({ status }) {
  const map = {
    active:    { bg: "#DCFCE7", fg: "#16A34A", label: "active" },
    completed: { bg: colors.brandTertiary, fg: colors.brand, label: "completed" },
    halted:    { bg: "#FEE2E2", fg: colors.error, label: "halted" },
    failed:    { bg: "#FEE2E2", fg: colors.error, label: "failed" },
  };
  const cfg = map[status] || { bg: colors.surfaceTertiary, fg: colors.muted, label: status };
  return (
    <span className="inline-block px-2 py-0.5 rounded-full text-[11px] font-bold"
          style={{ backgroundColor: cfg.bg, color: cfg.fg }}>
      {cfg.label}
    </span>
  );
}


/* ─────────────────────────────────────────────────────────────────────
   Enrol Modal
   ────────────────────────────────────────────────────────────────── */
function EnrolModal({ sequenceId, segments, onClose, _onDone }) {
  const [tab, setTab] = useState("customers");
  const [query, setQuery] = useState("");
  const [candidates, setCandidates] = useState([]);
  const [picked, setPicked] = useState([]);
  const [segmentId, setSegmentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (tab !== "customers" || !query.trim()) { setCandidates([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await api.get(`/customers?search=${encodeURIComponent(query)}&limit=15`);
        const rows = Array.isArray(r) ? r : (r.customers || r.items || []);
        setCandidates(rows);
      } catch { setCandidates([]); }
    }, 250);
    return () => clearTimeout(t);
  }, [query, tab]);

  const submit = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      const payload = tab === "customers"
        ? { customer_ids: picked.map((p) => p.id) }
        : { segment_id: segmentId };
      const r = await api.post(`/marketing/sequences/${sequenceId}/enrol`, payload);
      setResult(r);
    } catch (e) { setError(e?.message || "Enrol failed"); }
    finally { setBusy(false); }
  };

  const canSubmit = tab === "customers" ? picked.length > 0 : !!segmentId;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
         style={{ background: "rgba(15,23,42,0.65)" }}
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
         data-testid="sequence-enrol-modal">
      <div className="w-full max-w-lg rounded-2xl shadow-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between px-5 pt-4 pb-3"
             style={{ borderBottom: `1px solid ${colors.divider}` }}>
          <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
            Enrol customers
          </h3>
          <button onClick={onClose} className="p-1" style={{ color: colors.muted }}>
            <XIcon size={16} />
          </button>
        </div>

        <div className="p-5 space-y-3">
          <div className="flex items-center gap-2">
            <TabBtn active={tab === "customers"} onClick={() => setTab("customers")}
                    testId="sequence-enrol-tab-customers">Individual customers</TabBtn>
            <TabBtn active={tab === "segment"} onClick={() => setTab("segment")}
                    testId="sequence-enrol-tab-segment">Segment</TabBtn>
          </div>

          {tab === "customers" ? (
            <>
              <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
                     placeholder="Search customers by name…"
                     className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                     style={{ backgroundColor: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                     data-testid="sequence-enrol-search" />
              {picked.length ? (
                <div className="flex flex-wrap gap-1">
                  {picked.map((p) => (
                    <span key={p.id}
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold"
                          style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}>
                      {p.name || p.id}
                      <button onClick={() => setPicked((prev) => prev.filter((x) => x.id !== p.id))}
                              className="p-0.5" aria-label="Remove">
                        <XIcon size={10} />
                      </button>
                    </span>
                  ))}
                </div>
              ) : null}
              {candidates.length ? (
                <div className="rounded-lg max-h-56 overflow-y-auto"
                     style={{ border: `1px solid ${colors.border}` }}>
                  {candidates.map((c) => (
                    <button key={c.id}
                            onClick={() => {
                              if (picked.find((p) => p.id === c.id)) return;
                              setPicked((prev) => [...prev, c]);
                              setQuery(""); setCandidates([]);
                            }}
                            className="w-full text-left px-3 py-2 text-sm hover:brightness-95"
                            style={{ color: colors.onSurface,
                                     borderBottom: `1px solid ${colors.divider}` }}>
                      {c.name || c.id}
                      <span className="text-xs ml-2" style={{ color: colors.muted }}>
                        {c.email || c.phone || ""}
                      </span>
                    </button>
                  ))}
                </div>
              ) : null}
            </>
          ) : (
            <select value={segmentId}
                    onChange={(e) => setSegmentId(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                    style={{ backgroundColor: colors.surface, color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                    data-testid="sequence-enrol-segment-select">
              <option value="">— pick a segment —</option>
              {segments.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          )}

          {result ? (
            <div className="text-xs p-3 rounded-lg"
                 style={{ backgroundColor: "#DCFCE7", color: "#16A34A" }}
                 data-testid="sequence-enrol-result">
              Enrolled <b>{result.enrolled_count}</b>, skipped <b>{result.skipped_count}</b>.
            </div>
          ) : null}
          {error ? (
            <div className="text-xs" style={{ color: colors.error }}>{error}</div>
          ) : null}
        </div>

        <div className="p-4 flex items-center justify-end gap-2"
             style={{ borderTop: `1px solid ${colors.divider}` }}>
          <button onClick={onClose}
                  className="px-4 py-2 rounded-xl text-sm font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}>
            Close
          </button>
          <button onClick={submit} disabled={busy || !canSubmit}
                  className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                  style={{ background: brandGradientCss }}
                  data-testid="sequence-enrol-submit">
            <Send size={14} /> {busy ? "Enroling…" : "Enrol"}
          </button>
        </div>
      </div>
    </div>
  );
}


/* ─────────────────────────────────────────────────────────────────────
   Template Preview Modal — reuses M3 preview endpoint
   ────────────────────────────────────────────────────────────────── */
function TemplatePreviewModal({ templateId, onClose }) {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.post(`/marketing/templates/${templateId}/preview`, {})
      .then(setPreview)
      .catch((e) => setErr(e?.message || "Preview failed"))
      .finally(() => setLoading(false));
  }, [templateId]);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
         style={{ background: "rgba(15,23,42,0.65)" }}
         onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
         data-testid="sequence-preview-modal">
      <div className="w-full max-w-xl rounded-2xl shadow-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between px-5 pt-4 pb-3"
             style={{ borderBottom: `1px solid ${colors.divider}` }}>
          <h3 className="text-base font-bold" style={{ color: colors.onSurface }}>
            Step 1 preview
          </h3>
          <button onClick={onClose} className="p-1" style={{ color: colors.muted }}>
            <XIcon size={16} />
          </button>
        </div>
        <div className="p-5 space-y-3 max-h-[70vh] overflow-y-auto">
          {loading ? (
            <div className="text-sm text-center" style={{ color: colors.muted }}>Rendering…</div>
          ) : err ? (
            <div className="text-sm" style={{ color: colors.error }}>{err}</div>
          ) : preview ? (
            <>
              {preview.subject_rendered ? (
                <div>
                  <div className="text-[10px] font-bold uppercase tracking-wider mb-1"
                       style={{ color: colors.muted }}>SUBJECT</div>
                  <div className="text-sm font-semibold"
                       style={{ color: colors.onSurface }}>
                    {preview.subject_rendered}
                  </div>
                </div>
              ) : null}
              <div>
                <div className="text-[10px] font-bold uppercase tracking-wider mb-1"
                     style={{ color: colors.muted }}>BODY</div>
                <pre className="text-xs p-3 rounded-lg whitespace-pre-wrap"
                     style={{ backgroundColor: colors.surfaceSecondary,
                              color: colors.onSurface,
                              border: `1px solid ${colors.divider}`,
                              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}>
                  {preview.body_rendered}
                </pre>
              </div>
              {preview.missing_vars?.length ? (
                <div className="text-xs" style={{ color: "#92400E" }}>
                  Missing vars: {preview.missing_vars.join(", ")}
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
