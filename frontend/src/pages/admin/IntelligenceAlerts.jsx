/**
 * Phase A1 · Feb-2026 · Proactive Intelligence — full-list page.
 *
 * Route: ``/admin/intelligence/alerts``. Admin+super_admin only —
 * the router shell already role-gates this path, and the API
 * itself returns 403 for any other caller.
 *
 * Features
 * --------
 * * Category filter chips (All / Missed Service / Chemistry Upsell
 *   / Churn Risk / Renewal Due). Inactive categories still render
 *   with a ``0`` count.
 * * Tab strip: Unread / Read / Dismissed. Unread is the default.
 * * Bulk "Mark all read" button — scoped to the active category
 *   when set (falls through to the endpoint's optional
 *   ``category`` body param).
 * * Cursor pagination via ``before=`` for older pages. First page
 *   uses no cursor; each response's ``next_before`` drives the
 *   next click.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertCircle, CheckCheck, X as XIcon, ExternalLink,
          Info as InfoIcon, Loader2, ArrowRight, Sparkles,
          Receipt, MessageSquare, RefreshCw, Send } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";
import { toast } from "sonner";


const _CATEGORY_META = {
  missed_service:    { label: "Missed Service" },
  chemistry_upsell:  { label: "Chemistry" },
  churn_risk:        { label: "Churn Risk" },
  renewal_due:       { label: "Renewal Due" },
};
const _CATEGORY_ORDER = [
  "missed_service", "chemistry_upsell",
  "churn_risk", "renewal_due",
];
const _TABS = [
  { key: "unread",    label: "Unread" },
  { key: "read",      label: "Read" },
  { key: "dismissed", label: "Dismissed" },
];
const _SEV_META = {
  urgent:      { color: "#DC2626", icon: AlertCircle },
  recommended: { color: "#D97706", icon: AlertCircle },
  info:        { color: "#6B7280", icon: InfoIcon },
};
const _PAGE_SIZE = 25;


function _relative(iso) {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const d = Date.now() - t;
  if (d < 60_000) return "just now";
  if (d < 3_600_000) return `${Math.floor(d / 60_000)}m ago`;
  if (d < 86_400_000) return `${Math.floor(d / 3_600_000)}h ago`;
  if (d < 604_800_000) return `${Math.floor(d / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString();
}


// Phase A2 · Feb-2026 — chemistry-upsell inline "reading sequence"
// summary. Renders ``"4200 → 4400 → 4600 ppm (target 2700-3400 ppm)"``
// straight from ``actor_context``. Everything is best-effort text
// formatting; if any field is missing we render null and let the
// generic ``body`` copy speak for the row.
function _fmtNum(v) {
  if (v === null || v === undefined) return "";
  if (typeof v !== "number") return String(v);
  return Number.isInteger(v) ? String(v) : String(+v.toFixed(2));
}
function ChemistryReadingSequence({ ctx }) {
  if (!ctx || !Array.isArray(ctx.readings) || ctx.readings.length !== 3) {
    return null;
  }
  const unit = ctx.unit ? ` ${ctx.unit}` : "";
  const tmin = _fmtNum(ctx.target_min);
  const tmax = _fmtNum(ctx.target_max);
  // Server writes ``readings`` newest → oldest; render oldest →
  // newest so operators read the trend left-to-right.
  const seq = [...ctx.readings].reverse();
  return (
    <div
      className="mt-2 text-[11px] font-mono inline-flex items-center gap-1 rounded px-2 py-1"
      style={{ background: colors.surfaceSecondary,
                color: colors.onSurface }}
      data-testid="chemistry-reading-sequence"
    >
      <span data-testid="chemistry-reading-seq-oldest">
        {_fmtNum(seq[0])}
      </span>
      <ArrowRight size={10} className="opacity-60" />
      <span>{_fmtNum(seq[1])}</span>
      <ArrowRight size={10} className="opacity-60" />
      <span data-testid="chemistry-reading-seq-newest">
        {_fmtNum(seq[2])}
      </span>
      <span className="ml-1 opacity-80">
        {unit ? unit.trim() : ""}
      </span>
      {tmin && tmax ? (
        <span className="ml-2 opacity-70"
              data-testid="chemistry-reading-target-band">
          (target {tmin}-{tmax}{unit})
        </span>
      ) : null}
    </div>
  );
}


// Phase A3 · Feb-2026 — churn-risk inline summary chip. Two shapes
// depending on ``actor_context.signal``:
//   * missed_payments      →  "$350.00 across 2 invoices • oldest 30d overdue"
//   * recurring_cancelled  →  "Weekly Pool Cleaning • cancelled 2026-02-14"
// Everything is best-effort; if a field is missing the chip either
// omits the sub-clause or renders null.
function _fmtDollars(cents) {
  if (cents === null || cents === undefined) return "";
  const dollars = Number(cents) / 100;
  return `$${dollars.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function ChurnRiskSummary({ ctx }) {
  if (!ctx || !ctx.signal) return null;
  if (ctx.signal === "missed_payments") {
    const total = _fmtDollars(ctx.total_amount_cents);
    const cnt = ctx.invoice_count;
    const oldest = ctx.oldest_days_overdue;
    if (!cnt) return null;
    return (
      <div
        className="mt-2 text-[11px] font-mono inline-flex items-center gap-2 rounded px-2 py-1"
        style={{ background: colors.surfaceSecondary,
                  color: colors.onSurface }}
        data-testid="churn-risk-summary-missed-payments"
      >
        <span data-testid="churn-risk-total">{total}</span>
        <span className="opacity-60">·</span>
        <span data-testid="churn-risk-count">
          {cnt} invoice{cnt === 1 ? "" : "s"}
        </span>
        {oldest ? (
          <>
            <span className="opacity-60">·</span>
            <span data-testid="churn-risk-oldest">
              oldest {oldest}d overdue
            </span>
          </>
        ) : null}
      </div>
    );
  }
  if (ctx.signal === "recurring_cancelled") {
    const service = ctx.service_type || "recurring service";
    const when = ctx.cancelled_at_short
                 || String(ctx.cancelled_at || "").slice(0, 10);
    return (
      <div
        className="mt-2 text-[11px] font-mono inline-flex items-center gap-2 rounded px-2 py-1"
        style={{ background: colors.surfaceSecondary,
                  color: colors.onSurface }}
        data-testid="churn-risk-summary-recurring-cancelled"
      >
        <span data-testid="churn-risk-service">{service}</span>
        {when ? (
          <>
            <span className="opacity-60">·</span>
            <span data-testid="churn-risk-when">cancelled {when}</span>
          </>
        ) : null}
      </div>
    );
  }
  return null;
}


// Phase A4 · Feb-2026 — renewal_due inline summary chip.
// Two visual variants driven by ``actor_context.auto_renew``:
//   * manual → "{plan_name} · $89.00/mo · expires 2026-03-14"
//   * auto   → "{plan_name} · $79.00/mo · AUTO-RENEW 2026-03-14"
function RenewalDueSummary({ ctx }) {
  if (!ctx || !ctx.plan_name) return null;
  const monthly = _fmtDollars(ctx.monthly_amount_cents);
  const when = ctx.expires_at_short
               || String(ctx.expires_at || "").slice(0, 10);
  return (
    <div
      className="mt-2 text-[11px] font-mono inline-flex items-center gap-2 rounded px-2 py-1"
      style={{ background: colors.surfaceSecondary,
                color: colors.onSurface }}
      data-testid="renewal-due-summary"
    >
      <span data-testid="renewal-plan">{ctx.plan_name}</span>
      {monthly ? (
        <>
          <span className="opacity-60">·</span>
          <span data-testid="renewal-price">{monthly}/mo</span>
        </>
      ) : null}
      {ctx.auto_renew ? (
        <>
          <span className="opacity-60">·</span>
          <span
            data-testid="renewal-auto-badge"
            className="rounded px-1 font-bold uppercase"
            style={{ background: colors.brand || "#0284C7",
                      color: colors.onBrandPrimary || "#FFFFFF" }}
          >
            AUTO-RENEW
          </span>
          {when ? (
            <span data-testid="renewal-when">{when}</span>
          ) : null}
        </>
      ) : (
        when ? (
          <>
            <span className="opacity-60">·</span>
            <span data-testid="renewal-when">expires {when}</span>
          </>
        ) : null
      )}
    </div>
  );
}


export default function IntelligenceAlerts() {
  const navigate = useNavigate();
  // Phase C · Feb-2026 — consume deep-link params from the Sales
  // Pipeline risk-swimlane. ``?category=`` seeds the category chip
  // filter; ``?highlight=<alert_id>`` marks the target row with a
  // ``data-highlight="true"`` attribute so operators can spot it
  // after the click-through.
  const [searchParams] = useSearchParams();
  const initialCategory = searchParams.get("category") || "all";
  const highlightAlertId = searchParams.get("highlight") || "";
  const [tab, setTab]                     = useState("unread");
  const [activeCategory, setActiveCategory] = useState(initialCategory);
  const [items, setItems]                 = useState([]);
  const [loading, setLoading]             = useState(true);
  const [before, setBefore]               = useState(null);
  const [nextBefore, setNextBefore]       = useState(null);
  const [unreadCount, setUnreadCount]     = useState(0);

  const query = useMemo(() => {
    const qs = new URLSearchParams({ limit: String(_PAGE_SIZE) });
    if (tab === "unread")    qs.set("unread_only", "true");
    if (tab === "dismissed") qs.set("include_dismissed", "true");
    if (activeCategory !== "all") qs.set("category", activeCategory);
    if (before) qs.set("before", before);
    return qs.toString();
  }, [tab, activeCategory, before]);

  const fetchPage = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get(`/intelligence/alerts?${query}`);
      let list = r?.items || [];
      // Server returns unread by default (dismissed excluded).
      // For the "read" and "dismissed" tabs we post-filter to keep
      // the API surface minimal — the counts are still small enough
      // per tenant that this is fine for A1.
      if (tab === "read") {
        list = list.filter((a) => a.read_at && !a.dismissed_at);
      } else if (tab === "dismissed") {
        list = list.filter((a) => !!a.dismissed_at);
      }
      setItems(list);
      setUnreadCount(r?.unread_count || 0);
      setNextBefore(r?.next_before || null);
    } catch (e) {
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [query, tab]);

  useEffect(() => { fetchPage(); }, [fetchPage]);
  useEffect(() => { setBefore(null); }, [tab, activeCategory]);

  const onMarkAllRead = useCallback(async () => {
    const body = activeCategory !== "all"
      ? { category: activeCategory }
      : {};
    try {
      await api.post("/intelligence/alerts/mark-all-read", body);
    } finally {
      setBefore(null);
      fetchPage();
    }
  }, [activeCategory, fetchPage]);

  const onMarkRead = useCallback(async (alertId) => {
    await api.post(`/intelligence/alerts/${alertId}/read`);
    fetchPage();
  }, [fetchPage]);

  const onDismiss = useCallback(async (alertId) => {
    await api.post(`/intelligence/alerts/${alertId}/dismiss`);
    fetchPage();
  }, [fetchPage]);

  const onView = useCallback((a) => {
    if (a.job_id) navigate(`/jobs/${a.job_id}`);
    else if (a.customer_id) navigate(`/customers/${a.customer_id}`);
    onMarkRead(a.id);
  }, [navigate, onMarkRead]);

  return (
    <div className="max-w-3xl mx-auto p-4"
          data-testid="intelligence-alerts-page">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold"
             style={{ color: colors.onSurface }}>
          Proactive Intelligence
        </h1>
        <span className="text-sm" style={{ color: colors.muted }}
              data-testid="intelligence-alerts-unread-count">
          {unreadCount} unread
        </span>
      </div>

      {/* Category chips */}
      <div className="flex flex-wrap gap-2 mb-3"
            data-testid="intelligence-alerts-category-chips">
        {["all", ..._CATEGORY_ORDER].map((k) => {
          const on = activeCategory === k;
          const label = k === "all"
            ? "All"
            : _CATEGORY_META[k].label;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setActiveCategory(k)}
              className="text-xs font-semibold rounded-full px-3 py-1"
              style={{
                background: on ? (colors.brand || colors.onSurface) : colors.surface,
                color: on ? (colors.onBrand || "#fff") : colors.onSurface,
                border: `1px solid ${on ? "transparent" : colors.border}`,
              }}
              data-testid={`intelligence-alerts-cat-${k}`}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Tab strip + bulk action */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex gap-1" data-testid="intelligence-alerts-tabs">
          {_TABS.map((t) => {
            const on = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className="text-xs font-semibold rounded-lg px-3 py-1"
                style={{
                  background: on ? colors.surfaceSecondary : "transparent",
                  color: colors.onSurface,
                  border: `1px solid ${on ? colors.border : "transparent"}`,
                }}
                data-testid={`intelligence-alerts-tab-${t.key}`}
              >
                {t.label}
              </button>
            );
          })}
        </div>
        <button
          type="button"
          onClick={onMarkAllRead}
          className="text-xs font-semibold rounded-lg px-3 py-1"
          style={{ background: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}` }}
          data-testid="intelligence-alerts-mark-all-read"
        >
          <CheckCheck size={12} className="inline mr-1" />
          Mark all read
        </button>
      </div>

      {/* List */}
      {loading ? (
        <div className="flex items-center justify-center py-12"
              style={{ color: colors.muted }}
              data-testid="intelligence-alerts-loading">
          <Loader2 size={20} className="animate-spin mr-2" /> Loading…
        </div>
      ) : items.length === 0 ? (
        <div className="text-sm text-center py-12 rounded-lg"
              style={{ background: colors.surfaceSecondary,
                        color: colors.muted,
                        border: `1px solid ${colors.border}` }}
              data-testid="intelligence-alerts-empty">
          Nothing here.
        </div>
      ) : (
        <ul className="space-y-2"
             data-testid="intelligence-alerts-list">
          {items.map((a, i) => {
            const meta = _SEV_META[a.severity] || _SEV_META.info;
            const SevIcon = meta.icon;
            const isChem = a.category === "chemistry_upsell";
            const isChurn = a.category === "churn_risk";
            const ctx    = a.actor_context || {};
            const upsellHref = isChem && a.customer_id ? (() => {
              const qs = new URLSearchParams({
                customer_id: a.customer_id,
                source:      "intelligence_alert",
                alert_id:    a.id || "",
              });
              if (ctx.suggested_service_type) {
                qs.set("service_type", ctx.suggested_service_type);
              }
              return `/quotes/new?${qs.toString()}`;
            })() : null;
            // Phase A3 · Feb-2026 — churn-risk deep-links.
            //   missed_payments      → invoices tab on customer detail
            //                          with ``status=past_due,overdue``
            //   recurring_cancelled  → customer detail with compose
            //                          modal pre-hint via query
            const churnHref = (() => {
              if (!isChurn || !a.customer_id) return null;
              if (ctx.signal === "missed_payments") {
                const qs = new URLSearchParams({
                  tab:            "invoices",
                  status:         "past_due,overdue",
                  source:         "intelligence_alert",
                  alert_id:       a.id || "",
                });
                return `/customers/${a.customer_id}?${qs.toString()}`;
              }
              if (ctx.signal === "recurring_cancelled") {
                const qs = new URLSearchParams({
                  compose:  "email",
                  subject:  "We noticed you cancelled — how can we help?",
                  source:   "intelligence_alert",
                  alert_id: a.id || "",
                });
                return `/customers/${a.customer_id}?${qs.toString()}`;
              }
              return null;
            })();
            const churnCtaLabel = (() => {
              if (!isChurn) return null;
              if (ctx.signal === "missed_payments")     return "View invoices";
              if (ctx.signal === "recurring_cancelled") return "Contact customer";
              return null;
            })();
            const churnCtaIcon = (() => {
              if (!isChurn) return null;
              if (ctx.signal === "missed_payments")     return Receipt;
              if (ctx.signal === "recurring_cancelled") return MessageSquare;
              return null;
            })();
            // Phase A4 · Feb-2026 — renewal_due deep-links.
            //   View agreement       → customer detail warranties tab
            //   Resend renewal email → POST to admin endpoint, toast
            const isRenewal = a.category === "renewal_due";
            const renewalAgreementId = isRenewal
              ? (ctx.agreement_id || "")
              : "";
            const renewalViewHref = (isRenewal && a.customer_id
                                       && renewalAgreementId) ? (() => {
              const qs = new URLSearchParams({
                tab:       "warranties",
                highlight: renewalAgreementId,
                source:    "intelligence_alert",
                alert_id:  a.id || "",
              });
              return `/customers/${a.customer_id}?${qs.toString()}`;
            })() : null;
            return (
              <li
                key={a.id}
                className="rounded-xl p-3"
                style={{ background: colors.surface,
                          border: (highlightAlertId && a.id === highlightAlertId)
                                    ? `2px solid ${colors.brand}`
                                    : `1px solid ${colors.border}` }}
                data-testid={`intelligence-alerts-row-${i}`}
                data-category={a.category}
                data-signal={ctx.signal || ""}
                data-highlight={
                  (highlightAlertId && a.id === highlightAlertId)
                    ? "true" : "false"
                }
              >
                <div className="flex items-start gap-2">
                  <SevIcon size={18} color={meta.color}
                            className="mt-1 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold"
                             style={{ color: colors.onSurface }}>
                        {a.title}
                      </span>
                      <span className="text-[10px] font-semibold uppercase rounded-full px-2 py-0.5"
                             style={{ background: colors.surfaceSecondary,
                                      color: colors.muted }}>
                        {a.category}
                      </span>
                    </div>
                    <div className="text-xs mt-1"
                          style={{ color: colors.muted }}>
                      {a.body}
                    </div>
                    {isChem ? (
                      <ChemistryReadingSequence ctx={ctx} />
                    ) : null}
                    {isChurn ? (
                      <ChurnRiskSummary ctx={ctx} />
                    ) : null}
                    {isRenewal ? (
                      <RenewalDueSummary ctx={ctx} />
                    ) : null}
                    {isChem && upsellHref ? (
                      <div className="mt-2">
                        <button
                          type="button"
                          onClick={() => navigate(upsellHref)}
                          className="text-[11px] font-semibold rounded-lg px-2 py-1 inline-flex items-center gap-1"
                          style={{ background: colors.brand || colors.onSurface,
                                    color: colors.onBrandPrimary || "#FFFFFF" }}
                          data-testid={`intelligence-alerts-upsell-${i}`}
                        >
                          <Sparkles size={10} />
                          Create upsell quote
                        </button>
                      </div>
                    ) : null}
                    {isChurn && churnHref && churnCtaLabel ? (
                      <div className="mt-2">
                        <button
                          type="button"
                          onClick={() => navigate(churnHref)}
                          className="text-[11px] font-semibold rounded-lg px-2 py-1 inline-flex items-center gap-1"
                          style={{ background: colors.brand || colors.onSurface,
                                    color: colors.onBrandPrimary || "#FFFFFF" }}
                          data-testid={`intelligence-alerts-churn-cta-${i}`}
                          data-signal={ctx.signal}
                        >
                          {churnCtaIcon
                            ? React.createElement(churnCtaIcon, { size: 10 })
                            : null}
                          {churnCtaLabel}
                        </button>
                      </div>
                    ) : null}
                    {isRenewal && renewalAgreementId ? (
                      <div className="mt-2 flex items-center gap-2">
                        {renewalViewHref ? (
                          <button
                            type="button"
                            onClick={() => navigate(renewalViewHref)}
                            className="text-[11px] font-semibold rounded-lg px-2 py-1 inline-flex items-center gap-1"
                            style={{ background: colors.brand || colors.onSurface,
                                      color: colors.onBrandPrimary || "#FFFFFF" }}
                            data-testid={`intelligence-alerts-renewal-view-${i}`}
                          >
                            <ExternalLink size={10} />
                            View agreement
                          </button>
                        ) : null}
                        <button
                          type="button"
                          onClick={async () => {
                            try {
                              const r = await api.post(
                                `/agreements/${renewalAgreementId}/resend-renewal-email`,
                              );
                              if (r && r.ok) {
                                toast.success(
                                  r.sent_to
                                    ? `Renewal email sent to ${r.sent_to}`
                                    : "Renewal email sent",
                                );
                              } else {
                                toast.error(
                                  (r && r.reason) || "Send failed",
                                );
                              }
                            } catch (e) {
                              toast.error("Send failed");
                            }
                          }}
                          className="text-[11px] font-semibold rounded-lg px-2 py-1 inline-flex items-center gap-1"
                          style={{ background: colors.surfaceSecondary,
                                    color: colors.onSurface,
                                    border: `1px solid ${colors.border}` }}
                          data-testid={`intelligence-alerts-renewal-resend-${i}`}
                        >
                          <Send size={10} />
                          Resend renewal email
                        </button>
                      </div>
                    ) : null}
                    <div className="text-[10px] mt-1"
                          style={{ color: colors.muted }}>
                      {_relative(a.created_at)}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() => onView(a)}
                      disabled={!(a.job_id || a.customer_id)}
                      className="text-[11px] font-semibold rounded-full px-2 py-1 disabled:opacity-40"
                      style={{ background: colors.surfaceSecondary,
                                color: colors.onSurface,
                                border: `1px solid ${colors.border}` }}
                      data-testid={`intelligence-alerts-view-${i}`}
                    >
                      <ExternalLink size={10} className="inline mr-1" />
                      View
                    </button>
                    {!a.read_at ? (
                      <button
                        type="button"
                        onClick={() => onMarkRead(a.id)}
                        className="text-[11px] font-semibold rounded-full px-2 py-1"
                        style={{ background: colors.surfaceSecondary,
                                  color: colors.onSurface,
                                  border: `1px solid ${colors.border}` }}
                        data-testid={`intelligence-alerts-mark-read-${i}`}
                      >
                        <CheckCheck size={10} className="inline mr-1" />
                        Mark read
                      </button>
                    ) : null}
                    {!a.dismissed_at ? (
                      <button
                        type="button"
                        onClick={() => onDismiss(a.id)}
                        className="text-[11px] font-semibold rounded-full px-2 py-1"
                        style={{ background: colors.surfaceSecondary,
                                  color: colors.onSurface,
                                  border: `1px solid ${colors.border}` }}
                        data-testid={`intelligence-alerts-dismiss-${i}`}
                      >
                        <XIcon size={10} className="inline mr-1" />
                        Dismiss
                      </button>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* Cursor pagination */}
      <div className="flex justify-center mt-4">
        {nextBefore ? (
          <button
            type="button"
            onClick={() => setBefore(nextBefore)}
            className="text-xs font-semibold rounded-lg px-3 py-2"
            style={{ background: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}` }}
            data-testid="intelligence-alerts-next-page"
          >
            Load older →
          </button>
        ) : null}
      </div>
    </div>
  );
}
