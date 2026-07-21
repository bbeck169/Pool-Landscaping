/**
 * Feb-2026 · Marketing Slice M6 — Automated Review Requests admin.
 *
 * Two panels stacked:
 *   1. Config card (enable, channel, delay, quiet hours, templates,
 *      expire days). Persists via PATCH /marketing/review-requests/config.
 *   2. Requests table (filters, statuses, cancel action).
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  Save, Send, Star, Ban, Clock, Zap, Mail, MessageSquare,
} from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

const STATUS_STYLES = {
  queued:   { bg: "#FEF3C7", fg: "#92400E", label: "queued" },
  sent:     { bg: colors.brandTertiary, fg: colors.brand, label: "sent" },
  opened:   { bg: "#E0E7FF", fg: "#4338CA", label: "opened" },
  reviewed: { bg: "#DCFCE7", fg: "#16A34A", label: "reviewed" },
  expired:  { bg: colors.surfaceTertiary, fg: colors.muted, label: "expired" },
  failed:   { bg: "#FEE2E2", fg: colors.error, label: "failed" },
};

export default function MarketingReviewRequestsPage() {
  const [cfg, setCfg] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [savingCfg, setSavingCfg] = useState(false);
  const [cfgError, setCfgError] = useState("");

  const loadCfg = () =>
    api.get("/marketing/review-requests/config")
      .then(setCfg)
      .catch(() => setCfg({ ...DEFAULTS }));

  const loadTemplates = () =>
    api.get("/marketing/templates?active=true")
      .then((r) => setTemplates(r.templates || []))
      .catch(() => setTemplates([]));

  const loadList = () => {
    const qs = statusFilter ? `?status=${statusFilter}` : "";
    api.get(`/marketing/review-requests${qs}`)
      .then((r) => { setRows(r.review_requests || []); setTotal(r.total || 0); })
      .catch(() => { setRows([]); setTotal(0); });
  };

  useEffect(() => { loadCfg(); loadTemplates(); }, []);
  useEffect(() => { loadList(); }, [statusFilter]);

  const templatesByChannel = useMemo(() => ({
    email: templates.filter((t) => t.channel === "email"),
    sms: templates.filter((t) => t.channel === "sms"),
  }), [templates]);

  const saveConfig = async () => {
    setSavingCfg(true); setCfgError("");
    try {
      const updated = await api.patch(
        "/marketing/review-requests/config", cfg,
      );
      setCfg(updated);
    } catch (e) { setCfgError(e?.message || "Save failed"); }
    finally { setSavingCfg(false); }
  };

  const cancel = async (rid) => {
    if (!window.confirm("Cancel this review request?")) return;
    try {
      await api.post(`/marketing/review-requests/${rid}/cancel`, {});
      loadList();
    } catch (e) { alert(e?.message || "Cancel failed"); }
  };

  if (!cfg) {
    return (
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="review-requests-page">
      <div className="mb-4">
        <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
          Review Requests
        </h1>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          Automated post-service review nudges. Deep-linked to your portal review page so customers don't need to log in.
        </p>
      </div>

      {/* ── Config card ─────────────────────────────────────────── */}
      <div className="rounded-2xl p-5 mb-6"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
           data-testid="review-requests-config-card">
        <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
          <div>
            <h2 className="text-base font-bold" style={{ color: colors.onSurface }}>
              Configuration
            </h2>
            <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
              Fires when a service report is submitted for an opted-in tenant.
            </p>
          </div>
          <label className="inline-flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={!!cfg.enabled}
                   onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
                   data-testid="review-requests-enabled-toggle" />
            <span className="text-sm font-semibold"
                  style={{ color: cfg.enabled ? colors.brand : colors.muted }}>
              {cfg.enabled ? "Enabled" : "Disabled"}
            </span>
          </label>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Channel">
            <select value={cfg.channel || "email"}
                    onChange={(e) => setCfg({ ...cfg, channel: e.target.value })}
                    className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                    style={inputStyle}
                    data-testid="review-requests-channel-select">
              <option value="email">Email</option>
              <option value="sms">SMS</option>
              <option value="both">Both (email primary)</option>
            </select>
          </Field>

          <Field label="Delay hours (from service completion)">
            <input type="number" min={0} value={cfg.delay_hours ?? 72}
                   onChange={(e) =>
                     setCfg({ ...cfg, delay_hours: Number(e.target.value) })}
                   className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                   style={inputStyle}
                   data-testid="review-requests-delay-input" />
          </Field>

          <Field label="Email template">
            <select value={cfg.email_template_id || ""}
                    onChange={(e) =>
                      setCfg({ ...cfg, email_template_id: e.target.value || null })}
                    className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                    style={inputStyle}
                    data-testid="review-requests-email-template-select">
              <option value="">— pick an email template —</option>
              {templatesByChannel.email.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.category})</option>
              ))}
            </select>
          </Field>

          <Field label="SMS template">
            <select value={cfg.sms_template_id || ""}
                    onChange={(e) =>
                      setCfg({ ...cfg, sms_template_id: e.target.value || null })}
                    className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                    style={inputStyle}
                    data-testid="review-requests-sms-template-select">
              <option value="">— pick an SMS template —</option>
              {templatesByChannel.sms.map((t) => (
                <option key={t.id} value={t.id}>{t.name} ({t.category})</option>
              ))}
            </select>
          </Field>

          <Field label="Quiet hours start (SMS)">
            <input type="time" value={cfg.quiet_hours_start || "18:00"}
                   onChange={(e) =>
                     setCfg({ ...cfg, quiet_hours_start: e.target.value })}
                   className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                   style={inputStyle} />
          </Field>

          <Field label="Quiet hours end (SMS)">
            <input type="time" value={cfg.quiet_hours_end || "09:00"}
                   onChange={(e) =>
                     setCfg({ ...cfg, quiet_hours_end: e.target.value })}
                   className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                   style={inputStyle} />
          </Field>

          <Field label="Expire after (days)">
            <input type="number" min={1} max={365} value={cfg.expire_days ?? 30}
                   onChange={(e) =>
                     setCfg({ ...cfg, expire_days: Number(e.target.value) })}
                   className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                   style={inputStyle} />
          </Field>
        </div>

        {/* ── Slice A · A/B test toggle ─────────────────────────── */}
        <div className="mt-4 rounded-xl p-3"
             style={{ backgroundColor: colors.surfaceSecondary,
                      border: `1px solid ${colors.divider}` }}>
          <label className="flex items-center gap-2 cursor-pointer mb-2">
            <input type="checkbox" checked={!!cfg.ab_test_enabled}
                   onChange={(e) =>
                     setCfg({ ...cfg, ab_test_enabled: e.target.checked })}
                   data-testid="review-requests-ab-toggle" />
            <span className="text-sm font-bold" style={{ color: colors.onSurface }}>
              A/B test
            </span>
            <span className="text-xs" style={{ color: colors.muted }}>
              Randomly send variant B to <b>{cfg.ab_split_pct ?? 50}%</b> of review requests.
              Stats appear in Marketing Analytics.
            </span>
          </label>
          {cfg.ab_test_enabled ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-2">
              <Field label="Email template · variant B">
                <select value={cfg.email_template_id_variant || ""}
                        onChange={(e) =>
                          setCfg({ ...cfg,
                                    email_template_id_variant: e.target.value || null })}
                        className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                        style={inputStyle}
                        data-testid="review-requests-email-variant-select">
                  <option value="">— pick a variant template —</option>
                  {templatesByChannel.email.map((t) => (
                    <option key={t.id} value={t.id}>{t.name} ({t.category})</option>
                  ))}
                </select>
              </Field>
              <Field label="SMS template · variant B">
                <select value={cfg.sms_template_id_variant || ""}
                        onChange={(e) =>
                          setCfg({ ...cfg,
                                    sms_template_id_variant: e.target.value || null })}
                        className="w-full px-2 py-1.5 rounded-lg text-sm outline-none"
                        style={inputStyle}
                        data-testid="review-requests-sms-variant-select">
                  <option value="">— pick a variant template —</option>
                  {templatesByChannel.sms.map((t) => (
                    <option key={t.id} value={t.id}>{t.name} ({t.category})</option>
                  ))}
                </select>
              </Field>
              <Field label={`Split % to variant B — ${cfg.ab_split_pct ?? 50}%`}>
                <input type="range" min={0} max={100}
                       value={cfg.ab_split_pct ?? 50}
                       onChange={(e) =>
                         setCfg({ ...cfg, ab_split_pct: Number(e.target.value) })}
                       className="w-full"
                       data-testid="review-requests-ab-split-slider" />
              </Field>
            </div>
          ) : null}
        </div>

        {cfgError ? (
          <div className="text-sm mt-3" style={{ color: colors.error }}>{cfgError}</div>
        ) : null}

        <div className="mt-4 flex items-center justify-end gap-2">
          <button onClick={saveConfig} disabled={savingCfg}
                  className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                  style={{ background: brandGradientCss }}
                  data-testid="review-requests-save-btn">
            <Save size={14} /> {savingCfg ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* ── Requests table ─────────────────────────────────────── */}
      <div className="rounded-2xl overflow-hidden"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between p-4 flex-wrap gap-3"
             style={{ borderBottom: `1px solid ${colors.divider}` }}>
          <div>
            <h2 className="text-base font-bold" style={{ color: colors.onSurface }}>
              Requests ({total})
            </h2>
          </div>
          <select value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="px-2 py-1.5 rounded-lg text-xs outline-none"
                  style={inputStyle}
                  data-testid="review-requests-status-filter">
            <option value="">All statuses</option>
            {Object.keys(STATUS_STYLES).map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>

        {rows.length === 0 ? (
          <div className="p-10 text-center">
            <Star size={22} className="mx-auto mb-3" style={{ color: colors.muted }} />
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
              No requests yet
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              {cfg.enabled
                ? "Complete a service report to fire the first automated review request."
                : "Enable Review Requests above to start collecting reviews automatically."}
            </div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
                {["Requested", "Customer", "Channel", "Status", "Rating", ""].map((h) => (
                  <th key={h}
                      className="text-left py-2 px-3 text-xs font-bold uppercase tracking-wide"
                      style={{ color: colors.muted }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}
                    style={{ borderBottom: `1px solid ${colors.divider}` }}
                    data-testid={`review-request-row-${r.id}`}>
                  <td className="py-2 px-3" style={{ color: colors.muted }}>
                    {String(r.requested_at || "").slice(0, 16).replace("T", " ")}
                  </td>
                  <td className="py-2 px-3" style={{ color: colors.onSurface }}>
                    {r.customer_name || r.customer_id}
                    {r.variant ? (
                      <span
                        className="ml-2 inline-block px-1.5 py-0.5 rounded-full text-[10px] font-bold"
                        style={{ backgroundColor: r.variant === "B"
                                   ? "#DBEAFE" : "#E0E7FF",
                                 color: r.variant === "B"
                                   ? "#1E3A8A" : "#4338CA" }}
                        data-testid={`review-request-variant-badge-${r.id}`}>
                        {r.variant}
                      </span>
                    ) : null}
                  </td>
                  <td className="py-2 px-3" style={{ color: colors.onSurface }}>
                    {r.channel === "email"
                      ? <Mail size={13} className="inline mr-1" />
                      : <MessageSquare size={13} className="inline mr-1" />}
                    {r.channel}
                  </td>
                  <td className="py-2 px-3">
                    <StatusPill status={r.status} />
                  </td>
                  <td className="py-2 px-3" style={{ color: colors.onSurface }}>
                    {r.review_rating ? (
                      <span className="inline-flex items-center gap-0.5">
                        {r.review_rating} <Star size={12} className="fill-current" />
                      </span>
                    ) : "—"}
                  </td>
                  <td className="py-2 px-3 text-right">
                    {["queued", "sent", "opened"].includes(r.status) ? (
                      <button onClick={() => cancel(r.id)}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-semibold"
                              style={{ backgroundColor: colors.surfaceSecondary,
                                       color: colors.error }}
                              data-testid={`review-request-cancel-btn-${r.id}`}>
                        <Ban size={11} /> Cancel
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}


const DEFAULTS = {
  enabled: false, channel: "email", delay_hours: 72,
  email_template_id: null, sms_template_id: null,
  quiet_hours_start: "18:00", quiet_hours_end: "09:00",
  expire_days: 30,
  // Slice A · A/B testing.
  ab_test_enabled: false, ab_split_pct: 50,
  email_template_id_variant: null, sms_template_id_variant: null,
};

const inputStyle = {
  backgroundColor: colors.surface,
  color: colors.onSurface,
  border: `1px solid ${colors.border}`,
};


function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-bold uppercase tracking-wider"
            style={{ color: colors.muted }}>{label}</span>
      {children}
    </label>
  );
}


function StatusPill({ status }) {
  const cfg = STATUS_STYLES[status] || {
    bg: colors.surfaceTertiary, fg: colors.muted, label: status,
  };
  return (
    <span className="inline-block px-2 py-0.5 rounded-full text-[11px] font-bold"
          style={{ backgroundColor: cfg.bg, color: cfg.fg }}>
      {cfg.label}
    </span>
  );
}
