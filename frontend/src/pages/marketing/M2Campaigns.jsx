import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Plus, Pause, Play, Copy, X, ChevronLeft, ChevronRight, BarChart3, Users, Mail, AlertTriangle, Sparkles, Clock, MousePointerClick, ExternalLink } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { PageHeader, Button, Chip, StatusPill, EmptyState, Skeleton, Toast, TextInput } from "@/components/ui-kit";

/**
 * Marketing M2 UI — Campaigns list / detail / wizard (Feb-2026 ship).
 *
 * The three named exports match the routes already wired in ``App.js``
 * (``/marketing/campaigns``, ``/marketing/campaigns/new``,
 * ``/marketing/campaigns/:id``) so the switch-over is a one-line edit.
 */

// ─── Shared helpers ───────────────────────────────────────────────────

const CHANNEL_LABELS = { email: "Email", sms: "SMS", both: "Email + SMS" };
const STATUS_TONES = {
  draft: "muted",
  scheduled: "warning",
  sending: "warning",
  sent: "success",
  paused: "muted",
  cancelled: "danger",
};

function _pct(n) {
  return `${(Number(n) || 0).toFixed(1)}%`;
}
function _num(n) {
  return (Number(n) || 0).toLocaleString();
}
function _fmt(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// ─── CampaignsList ────────────────────────────────────────────────────

export function CampaignsList() {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [toast, setToast] = useState(null);

  const load = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (status) params.append("status", status);
      if (channel) params.append("channel", channel);
      if (q) params.append("q", q);
      const r = await api.get(`/marketing/campaigns?${params.toString()}`);
      setRows(r?.campaigns || r || []);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, channel]);

  const duplicate = async (cid) => {
    try {
      const r = await api.post(`/marketing/campaigns/${cid}/duplicate`, {});
      setToast({ tone: "success", message: "Campaign duplicated" });
      navigate(`/marketing/campaigns/${r.id}`);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const cancel = async (cid) => {
    if (!window.confirm("Cancel this campaign? Sending will stop.")) return;
    try {
      await api.post(`/marketing/campaigns/${cid}/cancel`, {});
      setToast({ tone: "success", message: "Campaign cancelled" });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  return (
    <div className="space-y-6" data-testid="m2-campaigns-list">
      <PageHeader
        title="Campaigns"
        subtitle="Email + SMS marketing broadcasts with A/B testing"
        right={
          <Button onClick={() => navigate("/marketing/campaigns/new")} testid="m2-new-campaign">
            <Plus size={14} /> New campaign
          </Button>
        }
      />

      <div className="flex flex-wrap gap-2">
        <TextInput
          label=""
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load()}
          placeholder="Search campaigns…"
          testid="m2-search"
          wrapperClass="w-64"
        />
        <select
          className="px-3 py-2 rounded-lg text-sm"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          data-testid="m2-filter-status"
        >
          <option value="">All statuses</option>
          {Object.keys(STATUS_TONES).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          className="px-3 py-2 rounded-lg text-sm"
          style={{
            backgroundColor: colors.surface,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
          data-testid="m2-filter-channel"
        >
          <option value="">All channels</option>
          <option value="email">Email</option>
          <option value="sms">SMS</option>
          <option value="both">Email + SMS</option>
        </select>
      </div>

      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Mail}
          title="No campaigns yet"
          hint="Start with the auto-seeded VIP Monthly Digest, or create a fresh campaign from scratch."
          action={
            <Button onClick={() => navigate("/marketing/campaigns/new")}>
              <Plus size={14} /> New campaign
            </Button>
          }
        />
      ) : (
        <div
          className="rounded-xl overflow-hidden"
          style={{ border: `1px solid ${colors.border}` }}
        >
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: colors.surfaceSecondary }}>
              <tr className="text-left" style={{ color: colors.muted }}>
                {[
                  "Name",
                  "Channel",
                  "Status",
                  "Sent",
                  "Opened",
                  "Clicked",
                  "Last sent",
                  "",
                ].map((h) => (
                  <th key={h} className="px-3 py-2 font-semibold uppercase text-xs">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr
                  key={c.id}
                  className="cursor-pointer hover:opacity-90 transition"
                  style={{ borderTop: `1px solid ${colors.border}` }}
                  onClick={() => navigate(`/marketing/campaigns/${c.id}`)}
                  data-testid={`m2-row-${c.id}`}
                >
                  <td className="px-3 py-3">
                    <div className="font-semibold" style={{ color: colors.onSurface }}>
                      {c.name}
                    </div>
                    {c.is_system_template ? (
                      <Chip label="Stock template" tone="muted" />
                    ) : null}
                  </td>
                  <td className="px-3 py-3" style={{ color: colors.onSurface }}>
                    {CHANNEL_LABELS[c.channel] || c.channel}
                  </td>
                  <td className="px-3 py-3">
                    <StatusPill status={c.status} />
                  </td>
                  <td className="px-3 py-3" style={{ color: colors.onSurface }}>
                    {_num(c.stats?.sent)}
                  </td>
                  <td className="px-3 py-3" style={{ color: colors.onSurface }}>
                    {_num(c.stats?.opened)}{" "}
                    <span style={{ color: colors.muted }} className="text-xs">
                      ({_pct(c.stats?.open_rate_pct)})
                    </span>
                  </td>
                  <td className="px-3 py-3" style={{ color: colors.onSurface }}>
                    {_num(c.stats?.clicked)}{" "}
                    <span style={{ color: colors.muted }} className="text-xs">
                      ({_pct(c.stats?.click_rate_pct)})
                    </span>
                  </td>
                  <td className="px-3 py-3" style={{ color: colors.muted }}>
                    {_fmt(c.sent_at || c.scheduled_at)}
                  </td>
                  <td className="px-3 py-3" onClick={(e) => e.stopPropagation()}>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        onClick={() => duplicate(c.id)}
                        testid={`m2-row-${c.id}-dup`}
                      >
                        <Copy size={12} />
                      </Button>
                      {["scheduled", "sending", "draft"].includes(c.status) ? (
                        <Button
                          variant="danger"
                          onClick={() => cancel(c.id)}
                          testid={`m2-row-${c.id}-cancel`}
                        >
                          <X size={12} />
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ─── CampaignNew (wizard) ─────────────────────────────────────────────

const WIZARD_STEPS = [
  { k: 1, label: "Details" },
  { k: 2, label: "Content" },
  { k: 3, label: "Audience" },
  { k: 4, label: "A/B" },
  { k: 5, label: "Schedule" },
];

export function CampaignNew() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lists, setLists] = useState([]);
  const [segments, setSegments] = useState([]);
  const [audienceEstimate, setAudienceEstimate] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [lintResult, setLintResult] = useState(null);
  const [overrideUnresolved, setOverrideUnresolved] = useState(false);

  const [form, setForm] = useState({
    name: "",
    channel: "email",
    from_name: "",
    from_email: "",
    reply_to: "",
    subject: "",
    preheader: "",
    email_html: "",
    sms_body: "",
    audience: { list_ids: [], segment_ids: [], exclude_list_ids: [], exclude_segment_ids: [] },
    ab_enabled: false,
    ab_variants: [
      { id: "A", subject: "", weight: 50 },
      { id: "B", subject: "", weight: 50 },
    ],
    schedule_mode: "now", // now | scheduled | draft
    scheduled_at: "",
  });

  useEffect(() => {
    api.get("/marketing/lists").then((r) => setLists(r?.lists || r || [])).catch(() => {});
    api.get("/marketing/segments").then((r) => setSegments(r?.segments || r || [])).catch(() => {});
  }, []);

  // Live lint as the user types content
  useEffect(() => {
    const t = setTimeout(async () => {
      try {
        const r = await api.post("/marketing/templates/lint", {
          subject: form.subject,
          preheader: form.preheader,
          email_html: form.email_html,
          sms_body: form.sms_body,
        });
        setLintResult(r);
      } catch { /* ignore */ }
    }, 500);
    return () => clearTimeout(t);
  }, [form.subject, form.preheader, form.email_html, form.sms_body]);

  const estimateAudience = async () => {
    try {
      const r = await api.post("/marketing/campaigns/estimate-audience", {
        audience: form.audience,
      });
      setAudienceEstimate(r);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const runPreview = async () => {
    try {
      const r = await api.post("/marketing/templates/preview", {
        subject: form.subject,
        content: { email_html: form.email_html, sms_body: form.sms_body },
      });
      setPreviewData(r);
    } catch (_e) {
      // Fall back to a local dry render if the preview endpoint has a
      // different shape — the linter output is enough to unblock.
      setPreviewData({ subject: form.subject, email_html: form.email_html, warnings: [] });
    }
  };

  const buildPayload = () => ({
    name: form.name.trim(),
    channel: form.channel,
    from_name: form.from_name.trim() || undefined,
    from_email: form.from_email.trim() || undefined,
    reply_to: form.reply_to.trim() || undefined,
    subject: form.subject,
    preheader: form.preheader,
    content: { email_html: form.email_html, sms_body: form.sms_body },
    audience: form.audience,
    ab_test: form.ab_enabled
      ? { enabled: true, variants: form.ab_variants.map((v) => ({
          id: v.id, subject: v.subject, weight: v.weight,
        })) }
      : { enabled: false },
  });

  const submit = async () => {
    if (!form.name.trim()) {
      setToast({ tone: "error", message: "Name is required" });
      return;
    }
    if (lintResult?.unresolved_tokens?.length && !overrideUnresolved) {
      setToast({
        tone: "error",
        message: "Fix unresolved tokens (or check override) before scheduling.",
      });
      return;
    }
    setBusy(true);
    try {
      const created = await api.post("/marketing/campaigns", buildPayload());
      if (form.schedule_mode === "now") {
        await api.post(`/marketing/campaigns/${created.id}/send-now`, {});
        setToast({ tone: "success", message: "Campaign sent" });
      } else if (form.schedule_mode === "scheduled" && form.scheduled_at) {
        await api.post(`/marketing/campaigns/${created.id}/schedule`, {
          scheduled_at: new Date(form.scheduled_at).toISOString(),
        });
        setToast({ tone: "success", message: "Campaign scheduled" });
      } else {
        setToast({ tone: "success", message: "Draft saved" });
      }
      navigate(`/marketing/campaigns/${created.id}`);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    } finally {
      setBusy(false);
    }
  };

  const canNext =
    (step === 1 && form.name.trim() && form.channel) ||
    (step === 2 && (form.subject || form.channel === "sms") &&
      (form.email_html || form.sms_body)) ||
    step === 3 || step === 4 || step === 5;

  const stepPct = useMemo(() => ((step - 1) / (WIZARD_STEPS.length - 1)) * 100, [step]);

  return (
    <div className="space-y-6" data-testid="m2-campaign-wizard">
      <PageHeader
        title="New campaign"
        subtitle={`Step ${step} of ${WIZARD_STEPS.length} — ${WIZARD_STEPS[step - 1].label}`}
        right={
          <Button variant="ghost" onClick={() => navigate("/marketing/campaigns")}>
            Cancel
          </Button>
        }
      />

      <div
        className="h-2 rounded-full overflow-hidden"
        style={{ backgroundColor: colors.surfaceSecondary }}
      >
        <div
          className="h-full transition-all"
          style={{ width: `${stepPct}%`, backgroundColor: colors.brand }}
        />
      </div>

      <div
        className="rounded-xl p-6 space-y-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        {step === 1 ? (
          <>
            <TextInput
              label="CAMPAIGN NAME"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              testid="m2-w-name"
            />
            <div>
              <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
                CHANNEL
              </div>
              <div className="flex gap-2">
                {["email", "sms", "both"].map((ch) => (
                  <button
                    key={ch}
                    onClick={() => setForm((f) => ({ ...f, channel: ch }))}
                    className="px-4 py-2 rounded-lg text-sm font-semibold transition"
                    style={{
                      backgroundColor: form.channel === ch ? colors.brand : colors.surfaceSecondary,
                      color: form.channel === ch ? colors.onBrand : colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid={`m2-w-channel-${ch}`}
                  >
                    {CHANNEL_LABELS[ch]}
                  </button>
                ))}
              </div>
            </div>
            <TextInput
              label="FROM NAME (optional)"
              value={form.from_name}
              onChange={(e) => setForm((f) => ({ ...f, from_name: e.target.value }))}
              testid="m2-w-from-name"
            />
            <TextInput
              label="FROM EMAIL (optional)"
              value={form.from_email}
              onChange={(e) => setForm((f) => ({ ...f, from_email: e.target.value }))}
              testid="m2-w-from-email"
            />
            <TextInput
              label="REPLY-TO (optional)"
              value={form.reply_to}
              onChange={(e) => setForm((f) => ({ ...f, reply_to: e.target.value }))}
              testid="m2-w-reply-to"
            />
          </>
        ) : null}

        {step === 2 ? (
          <>
            <TextInput
              label="SUBJECT"
              value={form.subject}
              onChange={(e) => setForm((f) => ({ ...f, subject: e.target.value }))}
              placeholder="Hi {{first_name}}, an update from {{tenant_name}}"
              testid="m2-w-subject"
            />
            <TextInput
              label="PREHEADER (optional)"
              value={form.preheader}
              onChange={(e) => setForm((f) => ({ ...f, preheader: e.target.value }))}
              testid="m2-w-preheader"
            />
            <div>
              <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
                EMAIL HTML (supports {"{{first_name}}, {{tenant_name}}, {{unsubscribe_url}}"})
              </div>
              <textarea
                value={form.email_html}
                onChange={(e) => setForm((f) => ({ ...f, email_html: e.target.value }))}
                className="w-full min-h-[220px] px-3 py-2 rounded-lg text-sm font-mono"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="m2-w-html"
              />
            </div>
            {(form.channel === "sms" || form.channel === "both") ? (
              <div>
                <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
                  SMS BODY ({form.sms_body.length}/160)
                </div>
                <textarea
                  value={form.sms_body}
                  onChange={(e) => setForm((f) => ({ ...f, sms_body: e.target.value }))}
                  className="w-full min-h-[100px] px-3 py-2 rounded-lg text-sm"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="m2-w-sms"
                />
              </div>
            ) : null}
            {/* Linter warnings */}
            {lintResult && !lintResult.clean ? (
              <div
                className="rounded-lg p-3 text-sm space-y-1"
                style={{
                  backgroundColor: "#FEF3C7",
                  color: "#92400E",
                  border: "1px solid #F59E0B",
                }}
                data-testid="m2-w-lint-warnings"
              >
                <div className="font-semibold flex items-center gap-1">
                  <AlertTriangle size={14} /> Template check
                </div>
                {(lintResult.unresolved_tokens || []).map((t, i) => (
                  <div key={`u-${i}`} data-testid={`m2-w-lint-unresolved-${i}`}>
                    · Unresolved <code>{t.token}</code> in <em>{t.field}</em>
                  </div>
                ))}
                {(lintResult.deprecated_single_brace || []).map((t, i) => (
                  <div key={`d-${i}`} data-testid={`m2-w-lint-deprecated-${i}`}>
                    · Single-brace <code>{"{" + t.token + "}"}</code> in <em>{t.field}</em> — will render but the canonical shape is <code>{"{{" + t.token + "}}"}</code>.
                  </div>
                ))}
              </div>
            ) : null}
            <Button variant="ghost" onClick={runPreview} testid="m2-w-preview">
              <Sparkles size={12} /> Preview with test subscriber
            </Button>
            {previewData ? (
              <div
                className="rounded-lg p-3"
                style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
              >
                <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
                  PREVIEW · SUBJECT
                </div>
                <div className="text-sm" style={{ color: colors.onSurface }}>
                  {previewData.subject}
                </div>
                {previewData.email_html ? (
                  <>
                    <div className="text-xs font-semibold mt-2 mb-1" style={{ color: colors.muted }}>
                      EMAIL BODY
                    </div>
                    <div
                      className="text-sm border rounded p-2"
                      style={{
                        backgroundColor: colors.surface,
                        color: colors.onSurface,
                        borderColor: colors.border,
                      }}
                      dangerouslySetInnerHTML={{ __html: previewData.email_html }}
                    />
                  </>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}

        {step === 3 ? (
          <>
            <AudiencePicker
              title="Include lists"
              items={lists}
              selected={form.audience.list_ids}
              onChange={(v) => setForm((f) => ({ ...f, audience: { ...f.audience, list_ids: v } }))}
              testid="m2-w-lists"
            />
            <AudiencePicker
              title="Include segments"
              items={segments}
              selected={form.audience.segment_ids}
              onChange={(v) => setForm((f) => ({ ...f, audience: { ...f.audience, segment_ids: v } }))}
              testid="m2-w-segments"
            />
            <AudiencePicker
              title="Exclude lists"
              items={lists}
              selected={form.audience.exclude_list_ids}
              onChange={(v) => setForm((f) => ({ ...f, audience: { ...f.audience, exclude_list_ids: v } }))}
              testid="m2-w-exc-lists"
            />
            <AudiencePicker
              title="Exclude segments"
              items={segments}
              selected={form.audience.exclude_segment_ids}
              onChange={(v) => setForm((f) => ({ ...f, audience: { ...f.audience, exclude_segment_ids: v } }))}
              testid="m2-w-exc-segments"
            />
            <div className="flex items-center gap-3">
              <Button onClick={estimateAudience} testid="m2-w-estimate">
                <Users size={12} /> Estimate audience
              </Button>
              {audienceEstimate ? (
                <div className="text-sm" style={{ color: colors.onSurface }} data-testid="m2-w-audience-count">
                  <strong>{_num(audienceEstimate.count || audienceEstimate.matched_count)}</strong>{" "}
                  subscribers
                </div>
              ) : null}
            </div>
          </>
        ) : null}

        {step === 4 ? (
          <>
            <label className="flex items-center gap-2 text-sm" style={{ color: colors.onSurface }}>
              <input
                type="checkbox"
                checked={form.ab_enabled}
                onChange={(e) => setForm((f) => ({ ...f, ab_enabled: e.target.checked }))}
                data-testid="m2-w-ab-toggle"
              />
              Enable A/B testing
            </label>
            {form.ab_enabled ? (
              <div className="space-y-2">
                {form.ab_variants.map((v, i) => (
                  <div
                    key={v.id}
                    className="grid grid-cols-1 md:grid-cols-4 gap-2 p-2 rounded-lg"
                    style={{ backgroundColor: colors.surfaceSecondary }}
                    data-testid={`m2-w-ab-row-${v.id}`}
                  >
                    <div className="text-sm font-semibold self-center" style={{ color: colors.onSurface }}>
                      Variant {v.id}
                    </div>
                    <div className="md:col-span-2">
                      <TextInput
                        label=""
                        value={v.subject}
                        onChange={(e) => setForm((f) => {
                          const nv = [...f.ab_variants];
                          nv[i] = { ...nv[i], subject: e.target.value };
                          return { ...f, ab_variants: nv };
                        })}
                        placeholder={`Variant ${v.id} subject`}
                        testid={`m2-w-ab-subject-${v.id}`}
                      />
                    </div>
                    <TextInput
                      label="WEIGHT"
                      type="number"
                      value={v.weight}
                      onChange={(e) => setForm((f) => {
                        const nv = [...f.ab_variants];
                        nv[i] = { ...nv[i], weight: Number(e.target.value) };
                        return { ...f, ab_variants: nv };
                      })}
                      testid={`m2-w-ab-weight-${v.id}`}
                    />
                  </div>
                ))}
                <div className="text-xs" style={{ color: colors.muted }}>
                  Weights don't need to sum to 100 — the send engine normalizes automatically.
                </div>
              </div>
            ) : (
              <div className="text-sm" style={{ color: colors.muted }}>
                A/B testing is off. Enable it to try two subject variants against your audience.
              </div>
            )}
          </>
        ) : null}

        {step === 5 ? (
          <>
            <div>
              <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
                WHEN TO SEND
              </div>
              <div className="flex gap-2">
                {[
                  { k: "now", label: "Send now" },
                  { k: "scheduled", label: "Schedule" },
                  { k: "draft", label: "Save draft" },
                ].map((m) => (
                  <button
                    key={m.k}
                    onClick={() => setForm((f) => ({ ...f, schedule_mode: m.k }))}
                    className="px-4 py-2 rounded-lg text-sm font-semibold transition"
                    style={{
                      backgroundColor:
                        form.schedule_mode === m.k ? colors.brand : colors.surfaceSecondary,
                      color:
                        form.schedule_mode === m.k ? colors.onBrand : colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid={`m2-w-schedule-${m.k}`}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
            </div>
            {form.schedule_mode === "scheduled" ? (
              <TextInput
                label="SEND AT"
                type="datetime-local"
                value={form.scheduled_at}
                onChange={(e) => setForm((f) => ({ ...f, scheduled_at: e.target.value }))}
                testid="m2-w-scheduled-at"
              />
            ) : null}
            {lintResult?.unresolved_tokens?.length ? (
              <label className="flex items-center gap-2 text-sm" style={{ color: "#92400E" }}>
                <input
                  type="checkbox"
                  checked={overrideUnresolved}
                  onChange={(e) => setOverrideUnresolved(e.target.checked)}
                  data-testid="m2-w-override-unresolved"
                />
                I understand there are unresolved tokens — send anyway
              </label>
            ) : null}
          </>
        ) : null}

        <div className="flex justify-between pt-2" style={{ borderTop: `1px solid ${colors.border}` }}>
          <Button
            variant="ghost"
            onClick={() => setStep((s) => Math.max(1, s - 1))}
            disabled={step === 1}
            testid="m2-w-back"
          >
            <ChevronLeft size={14} /> Back
          </Button>
          {step < WIZARD_STEPS.length ? (
            <Button
              onClick={() => setStep((s) => Math.min(WIZARD_STEPS.length, s + 1))}
              disabled={!canNext}
              testid="m2-w-next"
            >
              Next <ChevronRight size={14} />
            </Button>
          ) : (
            <Button onClick={submit} disabled={busy} testid="m2-w-submit">
              {busy ? "Sending…" : (
                form.schedule_mode === "now" ? "Send now" :
                form.schedule_mode === "scheduled" ? "Schedule" : "Save draft"
              )}
            </Button>
          )}
        </div>
      </div>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ─── CampaignDetail ───────────────────────────────────────────────────

export function CampaignDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [campaign, setCampaign] = useState(null);
  const [stats, setStats] = useState(null);
  const [timeline, setTimeline] = useState([]);
  const [topLinks, setTopLinks] = useState([]);
  const [tab, setTab] = useState("stats");
  const [toast, setToast] = useState(null);

  const load = async () => {
    try {
      const [c, s, tl, tp] = await Promise.all([
        api.get(`/marketing/campaigns/${id}`),
        api.get(`/marketing/campaigns/${id}/stats`),
        api.get(`/marketing/campaigns/${id}/timeline?limit=100`),
        api.get(`/marketing/campaigns/${id}/top-links`).catch(() => ({ links: [] })),
      ]);
      setCampaign(c);
      setStats(s);
      setTimeline(tl?.events || []);
      setTopLinks(tp?.links || []);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  useEffect(() => { load(); }, [id]); // eslint-disable-line

  const doAction = async (action) => {
    try {
      await api.post(`/marketing/campaigns/${id}/${action}`, {});
      setToast({ tone: "success", message: `Campaign ${action}` });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  if (!campaign) {
    return <div className="p-6"><Skeleton className="h-40" /></div>;
  }

  return (
    <div className="space-y-6" data-testid="m2-campaign-detail">
      <div className="flex items-center gap-2">
        <Button variant="ghost" onClick={() => navigate("/marketing/campaigns")} testid="m2-detail-back">
          <ChevronLeft size={14} /> Campaigns
        </Button>
      </div>
      <PageHeader
        title={campaign.name}
        subtitle={
          <div className="flex items-center gap-2 flex-wrap">
            <StatusPill status={campaign.status} />
            <Chip label={CHANNEL_LABELS[campaign.channel] || campaign.channel} tone="muted" />
            {campaign.ab_test?.enabled ? <Chip label="A/B enabled" tone="success" /> : null}
            {campaign.is_system_template ? <Chip label="Stock template" tone="muted" /> : null}
          </div>
        }
        right={
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => doAction("duplicate")} testid="m2-detail-dup">
              <Copy size={12} /> Duplicate
            </Button>
            {campaign.status === "scheduled" || campaign.status === "sending" ? (
              <>
                <Button variant="ghost" onClick={() => doAction("pause")} testid="m2-detail-pause">
                  <Pause size={12} /> Pause
                </Button>
                <Button variant="danger" onClick={() => doAction("cancel")} testid="m2-detail-cancel">
                  <X size={12} /> Cancel
                </Button>
              </>
            ) : null}
            {campaign.status === "paused" ? (
              <Button onClick={() => doAction("resume")} testid="m2-detail-resume">
                <Play size={12} /> Resume
              </Button>
            ) : null}
          </div>
        }
      />

      {/* Stats card grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3">
        {[
          { k: "sent", label: "Sent", tone: colors.brand },
          { k: "delivered", label: "Delivered", tone: colors.brand },
          { k: "opened", label: "Opened", tone: colors.success, pct: stats?.open_rate_pct },
          { k: "clicked", label: "Clicked", tone: colors.success, pct: stats?.click_rate_pct },
          { k: "not_yet_engaged", label: "No engagement yet", tone: colors.muted },
          { k: "bounced", label: "Bounced", tone: colors.danger, pct: stats?.bounce_rate_pct },
          { k: "unsubscribed", label: "Unsub", tone: colors.danger, pct: stats?.unsubscribe_rate_pct },
          { k: "failed", label: "Failed", tone: colors.danger },
        ].map((s) => (
          <div
            key={s.k}
            className="p-3 rounded-lg"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid={`m2-stat-${s.k}`}
          >
            <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>
              {s.label}
            </div>
            <div className="text-2xl font-bold" style={{ color: s.tone }}>
              {_num(stats?.[s.k])}
            </div>
            {s.pct != null ? (
              <div className="text-xs" style={{ color: colors.muted }}>
                {_pct(s.pct)}
              </div>
            ) : null}
          </div>
        ))}
      </div>

      {/* Per-variant stats if A/B */}
      {stats?.variants ? (
        <div
          className="rounded-xl p-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="m2-variant-stats"
        >
          <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>
            A/B — Per variant
          </div>
          <table className="w-full text-sm">
            <thead style={{ color: colors.muted }}>
              <tr>
                {["Variant", "Sent", "Opened", "Clicked", "Open %", "Click %"].map((h) => (
                  <th key={h} className="text-left px-2 py-1 font-semibold uppercase text-xs">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.variants).map(([vid, v]) => (
                <tr key={vid} style={{ borderTop: `1px solid ${colors.border}` }} data-testid={`m2-variant-${vid}`}>
                  <td className="px-2 py-2 font-semibold" style={{ color: colors.onSurface }}>{vid}</td>
                  <td className="px-2 py-2" style={{ color: colors.onSurface }}>{_num(v.sent)}</td>
                  <td className="px-2 py-2" style={{ color: colors.onSurface }}>{_num(v.opened)}</td>
                  <td className="px-2 py-2" style={{ color: colors.onSurface }}>{_num(v.clicked)}</td>
                  <td className="px-2 py-2" style={{ color: colors.onSurface }}>{_pct(v.open_rate_pct)}</td>
                  <td className="px-2 py-2" style={{ color: colors.onSurface }}>{_pct(v.click_rate_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {/* Tabs */}
      <div className="flex gap-2 border-b" style={{ borderColor: colors.border }}>
        {[
          { k: "stats", label: "Overview", icon: BarChart3 },
          { k: "timeline", label: "Timeline", icon: Clock },
          { k: "links", label: "Top links", icon: MousePointerClick },
        ].map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.k}
              onClick={() => setTab(t.k)}
              className="px-3 py-2 text-sm font-semibold inline-flex items-center gap-1 border-b-2 transition"
              style={{
                borderColor: tab === t.k ? colors.brand : "transparent",
                color: tab === t.k ? colors.brand : colors.muted,
              }}
              data-testid={`m2-detail-tab-${t.k}`}
            >
              <Icon size={12} /> {t.label}
            </button>
          );
        })}
      </div>

      {tab === "stats" ? (
        <div
          className="rounded-xl p-4 space-y-1 text-sm"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
        >
          <div><strong>Subject:</strong> {campaign.subject}</div>
          <div><strong>Sent at:</strong> {_fmt(campaign.sent_at)}</div>
          <div><strong>Scheduled at:</strong> {_fmt(campaign.scheduled_at)}</div>
          <div><strong>CTOR:</strong> {_pct(stats?.ctor_pct)}</div>
        </div>
      ) : null}

      {tab === "timeline" ? (
        <ul
          className="rounded-xl divide-y"
          style={{ border: `1px solid ${colors.border}`, borderColor: colors.border }}
          data-testid="m2-timeline"
        >
          {timeline.length === 0 ? (
            <li className="p-4 text-sm" style={{ color: colors.muted }}>
              No events yet.
            </li>
          ) : (
            timeline.map((e, i) => (
              <li
                key={i}
                className="p-3 flex items-center gap-3 text-sm"
                style={{ color: colors.onSurface, backgroundColor: colors.surface, borderColor: colors.border }}
                data-testid={`m2-timeline-row-${i}`}
              >
                <span
                  className="px-2 py-0.5 rounded-full text-xs font-semibold uppercase"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    color: colors.muted,
                  }}
                >
                  {e.type}
                </span>
                <span className="flex-1 truncate">
                  {e.subscriber_id ? `sub ${e.subscriber_id.slice(-6)}` : "system"}
                  {e.url ? <> — <a href={e.url} target="_blank" rel="noopener noreferrer" style={{ color: colors.brand }}>{e.url.slice(0, 60)}</a></> : null}
                  {e.variant_id ? <Chip label={`var ${e.variant_id}`} tone="muted" /> : null}
                </span>
                <span className="text-xs" style={{ color: colors.muted }}>
                  {_fmt(e.at)}
                </span>
              </li>
            ))
          )}
        </ul>
      ) : null}

      {tab === "links" ? (
        <ul
          className="rounded-xl divide-y"
          style={{ border: `1px solid ${colors.border}`, borderColor: colors.border }}
          data-testid="m2-top-links"
        >
          {topLinks.length === 0 ? (
            <li className="p-4 text-sm" style={{ color: colors.muted }}>
              No click activity yet.
            </li>
          ) : (
            topLinks.map((l, i) => (
              <li
                key={i}
                className="p-3 flex items-center gap-3 text-sm"
                style={{ color: colors.onSurface, backgroundColor: colors.surface }}
                data-testid={`m2-top-link-${i}`}
              >
                <MousePointerClick size={14} color={colors.brand} />
                <a
                  href={l.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex-1 truncate"
                  style={{ color: colors.onSurface }}
                >
                  {l.url}
                </a>
                <span className="text-xs font-semibold" style={{ color: colors.brand }}>
                  {_num(l.clicks || l.count)}
                </span>
                <ExternalLink size={12} color={colors.muted} />
              </li>
            ))
          )}
        </ul>
      ) : null}

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ─── Small helpers ────────────────────────────────────────────────────

function AudiencePicker({ title, items, selected, onChange, testid }) {
  const toggle = (id) => {
    if (selected.includes(id)) onChange(selected.filter((x) => x !== id));
    else onChange([...selected, id]);
  };
  return (
    <div>
      <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>
        {title.toUpperCase()}
      </div>
      {items.length === 0 ? (
        <div className="text-sm" style={{ color: colors.muted }}>
          None available.
        </div>
      ) : (
        <div className="flex flex-wrap gap-1" data-testid={testid}>
          {items.map((it) => {
            const on = selected.includes(it.id);
            return (
              <button
                key={it.id}
                onClick={() => toggle(it.id)}
                className="px-2 py-1 rounded-full text-xs font-semibold transition"
                style={{
                  backgroundColor: on ? colors.brand : colors.surfaceSecondary,
                  color: on ? colors.onBrand : colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid={`${testid}-item-${it.id}`}
              >
                {it.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
