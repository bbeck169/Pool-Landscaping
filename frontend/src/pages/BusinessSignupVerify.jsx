/**
 * Feb-2026 · Business Signup SP2 — verification landing +
 * check-your-inbox panel.
 *
 * Routes:
 *   /business-signup/verify?token=…     — auto-redeems token on mount
 *   /business-signup/verify-email-sent  — check-your-inbox panel
 */
import React from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api_base } from "@/api";


export function BusinessSignupVerify() {
  const { t } = useTranslation("common");
  const nav = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [state, setState] = React.useState(
    token ? "loading" : "no-token",
  );
  const [msg, setMsg] = React.useState("");

  React.useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const r = await fetch(
          `${api_base}/api/signup/verify?token=${encodeURIComponent(token)}`,
          { method: "POST" },
        );
        if (r.ok) {
          setState("ok");
          toast.success(t("signup.verify.success",
                              "Email verified. Redirecting…"));
          setTimeout(() => nav("/onboarding-wizard", { replace: true }), 800);
        } else {
          const j = await r.json().catch(() => ({}));
          setState("fail");
          setMsg(j?.detail?.message || j?.detail
                    || t("signup.verify.failed",
                          "Verification link is invalid or expired."));
        }
      } catch (ex) {
        setState("fail");
        setMsg(String(ex && ex.message ? ex.message : ex));
      }
    })();
  }, [token, nav, t]);

  return (
    <div style={{ maxWidth: 480, margin: "60px auto", padding: 24,
                    textAlign: "center", fontFamily: "system-ui" }}
          data-testid="business-signup-verify-page">
      <h1 style={{ fontSize: 24, marginBottom: 12 }}>
        {t("signup.verify.title", "Verifying your account")}
      </h1>
      {state === "loading" && (
        <p data-testid="verify-loading">
          {t("signup.verify.loading", "Hang tight — verifying your email…")}
        </p>
      )}
      {state === "ok" && (
        <p data-testid="verify-ok">
          {t("signup.verify.ok", "You're verified. Redirecting to onboarding…")}
        </p>
      )}
      {state === "no-token" && (
        <p data-testid="verify-no-token">
          {t("signup.verify.no_token",
              "Missing verification token. Click the link in your email.")}
        </p>
      )}
      {state === "fail" && (
        <div data-testid="verify-fail">
          <p style={{ color: "#B91C1C" }}>{msg}</p>
          <p style={{ marginTop: 16 }}>
            {t("signup.verify.resend_hint",
                "Log in to resend the verification link.")}
          </p>
          <a href="/login" data-testid="verify-fail-login-link"
              style={{ display: "inline-block", marginTop: 12,
                        padding: "8px 12px", background: "#2563EB",
                        color: "#fff", textDecoration: "none",
                        borderRadius: 6 }}>
            {t("signup.verify.login_cta", "Log in")}
          </a>
        </div>
      )}
    </div>
  );
}


export function BusinessSignupVerifyEmailSent() {
  const { t } = useTranslation("common");
  const [params] = useSearchParams();
  const email = params.get("email") || "";
  const [resending, setResending] = React.useState(false);
  const [msg, setMsg] = React.useState("");

  const resend = async () => {
    setResending(true); setMsg("");
    try {
      // Requires auth. The user is unauthenticated at this point
      // (we redirect here from the signup form), so the resend
      // button prompts them to log in first. Documented UX gap —
      // SP3 will auto-login on signup so resend works instantly.
      setMsg(t("signup.resend.login_first",
                  "Log in with the credentials you just created to resend."));
    } finally {
      setResending(false);
    }
  };

  return (
    <div style={{ maxWidth: 480, margin: "60px auto", padding: 24,
                    textAlign: "center", fontFamily: "system-ui" }}
          data-testid="business-signup-verify-email-sent-page">
      <h1 style={{ fontSize: 24, marginBottom: 12 }}>
        {t("signup.email_sent.title", "Check your inbox")}
      </h1>
      <p style={{ color: "#475569", marginBottom: 16 }}>
        {t("signup.email_sent.body",
            "We sent a verification link to")}{" "}
        <strong data-testid="verify-email-sent-address">{email}</strong>.{" "}
        {t("signup.email_sent.expiry_note",
            "The link expires in 48 hours.")}
      </p>
      <button onClick={resend} disabled={resending}
                data-testid="verify-resend-button"
                style={{ padding: "8px 12px", background: "#F1F5F9",
                          border: "1px solid #94A3B8", borderRadius: 6,
                          cursor: "pointer" }}>
        {t("signup.email_sent.resend", "Resend link")}
      </button>
      {msg && (
        <p data-testid="verify-resend-msg"
            style={{ marginTop: 12, color: "#475569" }}>{msg}</p>
      )}
    </div>
  );
}
