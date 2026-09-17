/**
 * Feb-2026 · Business Signup SP2 — public self-serve tenant signup.
 *
 * Route: ``/business-signup`` (unauthenticated).
 *
 * NOTE ON STRIPE.JS — the SP1 backend accepts a ``stripe_payment_method_id``
 * on the signup payload but for the SP2 web ship we send a placeholder
 * token (``pm_pending_frontend_ship``). Real Stripe Elements wiring
 * follows the same pattern as ``AddCardPage.jsx`` (K42 Add-Card portal
 * flow) and is called out as an SP2 deviation to be closed by SP3.
 *
 * i18n: labels/errors route through the shared ``signup`` namespace
 * (added to ``locales/{en,es,fr}/common.json`` under key ``signup``).
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api_base } from "@/api";
import { TimezoneSelect } from "@/components/settings/TimezoneSelect";


const INDUSTRIES = [
  "pools", "landscaping", "hvac", "pest_control", "cleaning",
  "solar", "handyman", "roofing", "plumbing", "electrical",
  "carpentry", "flooring", "painting", "window_cleaning",
  "gutter_cleaning", "pressure_washing", "carpet_cleaning",
  "chimney_sweep", "appliance_repair", "locksmith", "moving",
  "junk_removal", "general_services",
];
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


export default function BusinessSignup() {
  const { t } = useTranslation("common");
  const nav = useNavigate();
  const [form, setForm] = React.useState({
    business_name: "",
    admin_name: "",
    admin_email: "",
    admin_password: "",
    admin_phone: "",
    primary_industry: "pools",
    timezone: "America/Phoenix",
    country: "US",
  });
  const [submitting, setSubmitting] = React.useState(false);
  const [err, setErr] = React.useState("");

  const set = (k) => (e) =>
    setForm({ ...form, [k]: e && e.target ? e.target.value : e });
  const pwStrength = _passwordStrength(form.admin_password);

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (!pwStrength.ok) {
      setErr(t("signup.errors.weak_password",
                "Password must be at least 12 characters with a letter and a digit."));
      return;
    }
    setSubmitting(true);
    try {
      const r = await fetch(`${api_base}/api/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          admin_email: form.admin_email.trim().toLowerCase(),
          stripe_payment_method_id: "pm_pending_frontend_ship",
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
        {/* Stripe Elements card widget — SP3 wire-up. Uses a
            placeholder token in SP2 so the backend accepts the
            signup and the flow can be smoke-tested end-to-end. */}
        <div style={{ padding: 12, border: "1px dashed #94A3B8",
                        borderRadius: 6, color: "#475569", fontSize: 13 }}
              data-testid="signup-card-placeholder">
          {t("signup.card_placeholder",
              "Card widget will render here (Stripe Elements wire-up in SP3).")}
        </div>
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
