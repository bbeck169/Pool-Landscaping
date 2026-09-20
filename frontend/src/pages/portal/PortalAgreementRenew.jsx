/**
 * Phase F1.2 · Feb-2026 — Customer-portal agreement renewal page.
 *
 * Route: ``/customer-portal/agreements/:agreement_id/renew?token=…``
 * (public — no auth guard; the HMAC token is the auth).
 *
 * Flow
 * ----
 *   1. Mount → GET /api/portal/agreements/{id}/summary?token=… →
 *      render the plan card with plan_name, current expiry,
 *      next expiry, and price.
 *   2. Click "Renew Now" → POST /api/portal/agreements/{id}/renew
 *      → success state OR error state per response.
 *
 * Error mapping
 * -------------
 *   * 410 → "This renewal link has expired."
 *   * 403 → "This link is invalid — please contact us."
 *   * 409 → "This agreement is no longer available for renewal."
 *   * default → "Something went wrong. Please try again."
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { CheckCircle2, AlertTriangle, Loader2, Calendar,
          DollarSign, Sparkles } from "lucide-react";
import { api } from "@/api";
import { pickLocale, t } from "./portalRenewMessages";


function _currencySymbol(code) {
  const map = { USD: "$", EUR: "€", GBP: "£", CAD: "$", AUD: "$" };
  return map[(code || "USD").toUpperCase()] || "$";
}


function _fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  return d.toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}


function _errorMessage(code, locale) {
  // G1.5 · localised — falls back to English if the code isn't
  // recognised.
  const key = ({
    "token_expired":            "portal.renew.error.token_expired",
    "token_invalid":            "portal.renew.error.token_invalid",
    "agreement_state_invalid":  "portal.renew.error.agreement_state_invalid",
  })[code] || "portal.renew.error.generic";
  return t(locale, key);
}


export default function PortalAgreementRenew() {
  const { agreement_id } = useParams();
  const [search] = useSearchParams();
  const token = search.get("token") || "";
  const queryLocale = search.get("locale") || "";

  const [state, setState] = useState("loading"); // loading | ready | success | error
  const [summary, setSummary] = useState(null);
  const [error, setError]   = useState(null);
  const [renewing, setRenewing] = useState(false);
  const [success, setSuccess] = useState(null);

  const locale = useMemo(() => pickLocale({
    queryLocale,
    customerLocale: summary?.customer_locale,
  }), [queryLocale, summary]);

  const loadSummary = useCallback(async () => {
    if (!token) {
      setState("error");
      setError("token_invalid");
      return;
    }
    try {
      const r = await api.get(
        `/portal/agreements/${agreement_id}/summary?token=${encodeURIComponent(token)}`,
      );
      setSummary(r);
      setState("ready");
    } catch (e) {
      const detail = e?.data?.detail || e?.detail || e?.message;
      setError(typeof detail === "string" ? detail : "token_invalid");
      setState("error");
    }
  }, [agreement_id, token]);

  useEffect(() => { loadSummary(); }, [loadSummary]);

  const onRenew = async () => {
    if (renewing) return;
    setRenewing(true);
    try {
      const r = await api.post(
        `/portal/agreements/${agreement_id}/renew`, { token });
      setSuccess(r);
      setState("success");
    } catch (e) {
      const detail = e?.data?.detail || e?.detail || e?.message;
      setError(typeof detail === "string" ? detail : "unknown");
      setState("error");
    } finally { setRenewing(false); }
  };

  // ── Layout tokens (self-contained; no theme dependency) ────────
  const page = {
    minHeight: "100vh", background: "#F4F4F5",
    display: "flex", alignItems: "flex-start", justifyContent: "center",
    padding: "4rem 1rem",
  };
  const card = {
    width: "100%", maxWidth: 520, background: "#FFFFFF",
    border: "1px solid #E4E4E7", borderRadius: 16,
    padding: "2rem", boxShadow: "0 10px 24px rgba(15,23,42,0.06)",
  };
  const label = {
    fontSize: 11, fontWeight: 700, textTransform: "uppercase",
    letterSpacing: "0.05em", color: "#71717A",
  };
  const value = { fontSize: 16, fontWeight: 600, color: "#18181B" };

  if (state === "loading") {
    return (
      <div style={page} data-testid="portal-renewal-page">
        <div style={card}>
          <div className="flex items-center gap-2 text-sm"
                style={{ color: "#71717A" }}
                data-testid="portal-renewal-loading">
            <Loader2 size={16} className="animate-spin" />
            {t(locale, "portal.renew.summary.loading")}
          </div>
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div style={page} data-testid="portal-renewal-page">
        <div style={card} data-testid="portal-renewal-error">
          <div className="flex items-center gap-2 mb-3"
                style={{ color: "#B45309" }}>
            <AlertTriangle size={18} />
            <span style={{ fontWeight: 700 }}>
              {t(locale, "portal.renew.error.title")}
            </span>
          </div>
          <p style={{ color: "#3F3F46", lineHeight: 1.5 }}
              data-testid={`portal-renewal-error-${error || "unknown"}`}
              data-locale={locale}>
            {_errorMessage(error, locale)}
          </p>
        </div>
      </div>
    );
  }

  if (state === "success" && success) {
    return (
      <div style={page} data-testid="portal-renewal-page">
        <div style={card} data-testid="portal-renewal-success">
          <div className="flex items-center gap-2 mb-3"
                style={{ color: "#166534" }}>
            <CheckCircle2 size={20} />
            <span style={{ fontWeight: 700, fontSize: 18 }}>
              {t(locale, "portal.renew.success.title")}
            </span>
          </div>
          <p style={{ color: "#3F3F46", lineHeight: 1.6, marginBottom: 20 }}
              dangerouslySetInnerHTML={{ __html: t(locale,
                "portal.renew.success.body",
                { plan_name: success.plan_name || "" }) }} />
          <div style={{
            background: "#F0FDF4", border: "1px solid #BBF7D0",
            borderRadius: 12, padding: "1rem",
          }}>
            <div style={label}>{t(locale, "portal.renew.success.next_label")}</div>
            <div style={value} data-testid="portal-renewal-success-next">
              {_fmtDate(success.next_expires_at)}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ready
  if (!summary) return null;
  const sym = _currencySymbol(summary.currency);
  return (
    <div style={page} data-testid="portal-renewal-page">
      <div style={card} data-testid="portal-renewal-ready">
        <div className="flex items-center gap-2 mb-1"
              style={{ color: "#0284C7" }}>
          <Sparkles size={16} />
          <span style={{ fontSize: 12, fontWeight: 700,
                          letterSpacing: "0.05em", textTransform: "uppercase" }}>
            {t(locale, "portal.renew.summary.headline")}
          </span>
        </div>
        <h1 style={{ fontSize: 28, fontWeight: 800, color: "#18181B",
                      marginBottom: 24 }}
            data-testid="portal-renewal-plan-name">
          {summary.plan_name || "Service plan"}
        </h1>

        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16,
          marginBottom: 24,
        }}>
          <div>
            <div style={label}>{t(locale, "portal.renew.current_expires")}</div>
            <div style={{ ...value, display: "flex", alignItems: "center", gap: 6 }}
                  data-testid="portal-renewal-current-expires">
              <Calendar size={14} style={{ color: "#71717A" }} />
              {_fmtDate(summary.current_expires_at)}
            </div>
          </div>
          <div>
            <div style={label}>{t(locale, "portal.renew.new_expires")}</div>
            <div style={{ ...value, display: "flex", alignItems: "center", gap: 6, color: "#0284C7" }}
                  data-testid="portal-renewal-next-expires">
              <Calendar size={14} style={{ color: "#0284C7" }} />
              {_fmtDate(summary.next_expires_at)}
            </div>
          </div>
        </div>

        <div style={{
          background: "#F4F4F5", borderRadius: 12,
          padding: "1rem", marginBottom: 24,
        }}>
          <div style={label}>{t(locale, "portal.renew.price_label")}</div>
          <div style={{ ...value, fontSize: 22, display: "flex",
                          alignItems: "center", gap: 4, color: "#18181B" }}
                data-testid="portal-renewal-price">
            <DollarSign size={16} style={{ color: "#71717A" }} />
            {sym}{Number(summary.price_paid || 0).toFixed(2)}
            <span style={{ fontSize: 12, fontWeight: 500, color: "#71717A" }}>
              /month · {summary.currency}
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={onRenew}
          disabled={renewing || summary.already_renewed}
          data-testid="portal-renewal-cta"
          style={{
            width: "100%", padding: "14px 20px", borderRadius: 12,
            background: (renewing || summary.already_renewed) ? "#86EFAC" : "#16A34A",
            color: "#FFFFFF", fontWeight: 700, fontSize: 16,
            border: "none", cursor: (renewing || summary.already_renewed) ? "not-allowed" : "pointer",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
          }}
        >
          {renewing ? <Loader2 size={16} className="animate-spin" /> : null}
          {summary.already_renewed
            ? t(locale, "portal.renew.cta.already_renewed")
            : renewing
              ? t(locale, "portal.renew.cta.renewing")
              : t(locale, "portal.renew.cta")}
        </button>

        <p style={{
          marginTop: 16, fontSize: 12, textAlign: "center",
          color: "#71717A", lineHeight: 1.5,
        }}>
          {t(locale, "portal.renew.confirmation_hint")}
        </p>
      </div>
    </div>
  );
}
