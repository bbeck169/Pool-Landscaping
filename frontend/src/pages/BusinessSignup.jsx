/**
 * Feb-2026 · Business Signup — public self-serve tenant signup.
 *
 * Route: ``/business-signup`` (unauthenticated).
 *
 * SP3 · Feb-2026 gaps closed:
 *   1. Industry slug drift fix — INDUSTRIES imports from
 *      ``@/lib/deriveIndustry`` (single source of truth, 23 slugs).
 *   2. Stripe Elements card widget wired via
 *      ``stripe.createPaymentMethod``. Falls back to placeholder
 *      when ``REACT_APP_STRIPE_PUBLISHABLE_KEY`` is unset (local
 *      dev / sandbox).
 *   3. i18n labels via ``signup.*`` namespace; card errors
 *      surface under the card element.
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { loadStripe } from "@stripe/stripe-js";
import {
  Elements,
  useStripe,
  useElements,
  CardElement,
} from "@stripe/react-stripe-js";

import { api_base } from "@/api";
import { TimezoneSelect } from "@/components/settings/TimezoneSelect";
import { CANONICAL_INDUSTRIES } from "../lib/deriveIndustry";


// SP3 · Feb-2026 — INDUSTRIES mirrors the D1 canonical set exactly.
// Storage layer normalizes the plural alias ``"pools"`` → ``"pool"``
// but the picker only offers canonical slugs.
const INDUSTRIES = CANONICAL_INDUSTRIES;
const COUNTRIES = [
  "US", "CA", "GB", "AU", "IE", "NZ", "DE", "FR", "ES", "MX",
  "IN", "BR", "ZA", "SG", "HK", "JP", "KR", "AE", "SA", "PH",
  "PT", "IT", "NL", "SE", "NO",
];


function _passwordStrength(pw) {
  const okLen = (pw || "").length >= 12;
  const okLetter = /[A-Za-z]/.test(pw || "");
  const okDigit = /\d/.test(pw || "");
  const ok = okLen && okLetter && okDigit;
  return { okLen, okLetter, okDigit, ok };
}


// ── Inner form (renders inside <Elements> when Stripe key is set) ──
function SignupFormInner({ stripeKeyLoaded, cardFieldRef }) {
  const { t } = useTranslation("common");
  const nav = useNavigate();
  const [form, setForm] = React.useState({
    business_name: "",
    admin_name: "",
    admin_email: "",
    admin_password: "",
    admin_phone: "",
    // SP3 · Feb-2026 — canonical singular.
    primary_industry: "pool",
    timezone: "America/Phoenix",
    country: "US",
  });
  const [submitting, setSubmitting] = React.useState(false);
  const [err, setErr] = React.useState("");
  const [cardErr, setCardErr] = React.useState("");

  const set = (k) => (e) =>
    setForm({ ...form, [k]: e && e.target ? e.target.value : e });
  const pwStrength = _passwordStrength(form.admin_password);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    setCardErr("");
    if (!pwStrength.ok) {
      setErr(t("signup.errors.weak_password",
                "Password must be at least 12 characters with a letter and a digit."));
      return;
    }
    setSubmitting(true);
    let payment_method_id = "pm_pending_frontend_ship";
    try {
      // ═══════════════════════════════════════════════════════════
      // SP3-hotfix · Feb-2026 — Stripe hooks are OWNED by the child
      // ``SignupCardField`` component (rendered only inside the
      // <Elements> provider). We pull the stripe/elements refs
      // via ``cardFieldRef.current`` here so this parent form is
      // hook-free and never crashes when the publishable key is
      // absent (preview pod today). The child hands us its live
      // refs after mount; if it never mounted (no key), refs are
      // null and we submit the placeholder token.
      // ═══════════════════════════════════════════════════════════
      const cardHandle = cardFieldRef && cardFieldRef.current;
      if (stripeKeyLoaded && cardHandle && cardHandle.stripe && cardHandle.elements) {
        const cardEl = cardHandle.elements.getElement(CardElement);
        const { error, paymentMethod } = await cardHandle.stripe.createPaymentMethod({
          type: "card",
          card: cardEl,
          billing_details: {
            name: form.admin_name || undefined,
            email: (form.admin_email || "").trim().toLowerCase() || undefined,
          },
        });
        if (error) {
          // Prefer Stripe's specific decline message when present;
          // fall back to the locale-scoped generic. Never show
          // both because Stripe's message is already localized by
          // stripe.js when a locale hint is provided.
          setCardErr(
            error.message ||
            t("signup.card_error",
                { defaultValue: "Card error. Please try again." }),
          );
          setSubmitting(false);
          return;
        }
        payment_method_id = paymentMethod?.id || payment_method_id;
      } else {
        // eslint-disable-next-line no-console
        console.warn(
          "[signup] Stripe publishable key not configured — " +
          "submitting placeholder token. Set REACT_APP_STRIPE_PUBLISHABLE_KEY " +
          "to enable real card capture.",
        );
      }

      const r = await fetch(`${api_base()}/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          admin_email: form.admin_email.trim().toLowerCase(),
          stripe_payment_method_id: payment_method_id,
        }),
      });
      const j = await r.json();
      if (!r.ok) {
        const code = j?.detail?.code || j?.detail || "signup_failed";
        setErr(t(`signup.errors.${code}`,
                    j?.detail?.hint || j?.detail?.message || String(code)));
        return;
      }
      toast.success(t("signup.submitted",
                          "Check your email to verify your account."));
      nav(`/business-signup/verify-email-sent?email=${encodeURIComponent(
        form.admin_email.trim().toLowerCase())}`);
    } catch (ex) {
      setErr(String(ex && ex.message ? ex.message : ex));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ maxWidth: 640, margin: "40px auto", padding: 24,
                    fontFamily: "system-ui" }}
          data-testid="business-signup-page">
      <h1 style={{ fontSize: 28, marginBottom: 8 }}>
        {t("signup.title", "Start your 14-day trial")}
      </h1>
      <p style={{ color: "#64748B", marginBottom: 24 }}>
        {t("signup.subtitle",
             "Card required upfront · No charge until day 15 · Cancel anytime.")}
      </p>
      {err ? (
        <div data-testid="business-signup-error" style={{
          padding: 12, border: "1px solid #DC2626",
          background: "#FEF2F2", color: "#991B1B", borderRadius: 6,
          marginBottom: 16,
        }}>{err}</div>
      ) : null}
      <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
        <label>{t("signup.fields.business_name", "Business name")}
          <input required data-testid="signup-business-name"
                  value={form.business_name} onChange={set("business_name")} />
        </label>
        <label>{t("signup.fields.admin_name", "Your full name")}
          <input required data-testid="signup-admin-name"
                  value={form.admin_name} onChange={set("admin_name")} />
        </label>
        <label>{t("signup.fields.admin_email", "Email")}
          <input required type="email" data-testid="signup-admin-email"
                  value={form.admin_email} onChange={set("admin_email")} />
        </label>
        <label>{t("signup.fields.admin_password", "Password (min 12 chars)")}
          <input required type="password" data-testid="signup-admin-password"
                  value={form.admin_password}
                  onChange={set("admin_password")} />
          <div style={{ fontSize: 12, color: pwStrength.ok ? "#065F46" : "#B45309" }}
                data-testid="signup-password-strength">
            {pwStrength.okLen ? "✓" : "○"} 12+ chars ·{" "}
            {pwStrength.okLetter ? "✓" : "○"} letter ·{" "}
            {pwStrength.okDigit ? "✓" : "○"} digit
          </div>
        </label>
        <label>{t("signup.fields.admin_phone", "Phone (E.164 preferred)")}
          <input required type="tel" data-testid="signup-admin-phone"
                  value={form.admin_phone} onChange={set("admin_phone")}
                  placeholder="+15551234567" />
        </label>
        <label>{t("signup.fields.primary_industry", "Primary industry")}
          <select required data-testid="signup-primary-industry"
                    value={form.primary_industry}
                    onChange={set("primary_industry")}>
            {INDUSTRIES.map((s) => (
              <option key={s} value={s}>
                {t(`industries.${s}`, s.replace(/_/g, " "))}
              </option>
            ))}
          </select>
        </label>
        <TimezoneSelect value={form.timezone}
                          testid="signup-timezone-picker"
                          label={t("timezone.label", "Timezone")}
                          onChange={(e) => set("timezone")(e)} />
        <label>{t("signup.fields.country", "Country")}
          <select required data-testid="signup-country"
                    value={form.country} onChange={set("country")}>
            {COUNTRIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
            <option value="OTHER" disabled>
              {t("signup.fields.country_other",
                  "Other — contact us")}
            </option>
          </select>
        </label>
        {stripeKeyLoaded ? (
          <SignupCardField cardFieldRef={cardFieldRef} cardErr={cardErr}
                              t={t} />
        ) : (
          // Sandbox / local-dev fallback — see the console.warn in
          // submit(). Preserves the SP2 test flow (placeholder token
          // still submits) without requiring a Stripe key. NO hook
          // calls in this branch — that's what makes the preview
          // pod render safely.
          <div style={{ padding: 12, border: "1px dashed #94A3B8",
                          borderRadius: 6, color: "#475569", fontSize: 13 }}
                data-testid="signup-card-placeholder">
            {t("signup.card_placeholder",
                "Card widget will render here when Stripe is configured.")}
          </div>
        )}
        <button type="submit" data-testid="signup-submit"
                  disabled={submitting || !pwStrength.ok}
                  style={{
                    padding: "12px 16px", background: "#2563EB",
                    color: "#fff", border: 0, borderRadius: 6,
                    fontWeight: 600, cursor: submitting ? "wait" : "pointer",
                    opacity: submitting || !pwStrength.ok ? 0.6 : 1,
                  }}>
          {submitting
            ? t("signup.submitting", "Creating your account…")
            : t("signup.submit", "Start my 14-day trial")}
        </button>
      </form>
    </div>
  );
}


// ═════════════════════════════════════════════════════════════════
// SP3-hotfix · Feb-2026 — Card field child.
//
// This is the ONLY component in this file that calls ``useStripe()``
// / ``useElements()``. It is rendered strictly inside the
// ``<Elements>`` provider (see ``BusinessSignup`` default export
// below). Publishes its live stripe/elements handles up to the
// parent form via ``cardFieldRef`` so the parent can call
// ``createPaymentMethod`` on submit without ever touching a hook.
//
// Root cause of the preview-pod crash it fixes:
//   The previous SP3 revision called ``useStripe()`` unconditionally
//   at the top of ``SignupFormInner``. When
//   ``REACT_APP_STRIPE_PUBLISHABLE_KEY`` was unset (preview pod
//   today), the outer component returned ``<SignupFormInner />``
//   WITHOUT the ``<Elements>`` provider, and the hook threw
//   "Could not find Elements context" — which surfaced as the red
//   React overlay + entirely blank form the tester saw.
// ═════════════════════════════════════════════════════════════════
function SignupCardField({ cardFieldRef, cardErr, t }) {
  const stripe = useStripe();
  const elements = useElements();
  React.useEffect(() => {
    if (cardFieldRef) {
      cardFieldRef.current = { stripe, elements };
    }
  }, [cardFieldRef, stripe, elements]);
  return (
    <div data-testid="signup-card-element-wrap">
      <div style={{ marginBottom: 4, fontSize: 13, color: "#475569" }}>
        {t("signup.card_label", "Payment card")}
      </div>
      <div style={{
        padding: 12, border: "1px solid #CBD5E1",
        borderRadius: 6, background: "#fff",
      }}>
        <CardElement options={{ hidePostalCode: false }} />
      </div>
      {cardErr ? (
        <div data-testid="signup-card-error"
              style={{ color: "#B91C1C", fontSize: 13, marginTop: 6 }}>
          {cardErr}
        </div>
      ) : null}
    </div>
  );
}


// ── Outer component: always wraps in <Elements> ─────────────────
//
// ``<Elements stripe={null}>`` is a supported "loading" state per
// Stripe React docs — it provides the context so any child hook
// call resolves to ``null`` instead of throwing. That gives us
// belt-and-suspenders safety: even if ``SignupCardField`` is
// somehow rendered with a null stripe promise, hooks won't crash.
export default function BusinessSignup() {
  const publishableKey = process.env.REACT_APP_STRIPE_PUBLISHABLE_KEY || "";
  const stripePromise = React.useMemo(
    () => (publishableKey ? loadStripe(publishableKey) : null),
    [publishableKey],
  );
  const cardFieldRef = React.useRef(null);
  return (
    <Elements stripe={stripePromise}>
      <SignupFormInner
        stripeKeyLoaded={!!stripePromise}
        cardFieldRef={cardFieldRef} />
    </Elements>
  );
}
