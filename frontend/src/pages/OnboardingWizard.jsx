/**
 * Feb-2026 · Business Signup SP2 — 4-step onboarding wizard.
 *
 * Route: ``/onboarding-wizard`` (auth-gated by the standard
 * app-level route guard — an unauthenticated visit lands on /login
 * via the guard installed in App.js).
 *
 * Redirects to ``/dashboard?welcome=1`` when the wizard completes
 * OR when ``onboarding_completed_at`` is already stamped on the
 * tenant (so a returning admin never re-enters the wizard).
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { api } from "@/api";
import { TimezoneSelect } from "@/components/settings/TimezoneSelect";
import { CANONICAL_INDUSTRIES } from "../lib/deriveIndustry";


// SP3 · Feb-2026 — single source of truth for industry slugs; see
// ``routers/industry_checklists.INDUSTRY_SLUGS`` backend-side.
const INDUSTRIES = CANONICAL_INDUSTRIES;


export default function OnboardingWizard() {
  const { t } = useTranslation("common");
  const nav = useNavigate();
  const [state, setState] = React.useState({
    step: 1, completed: false, data: {},
  });
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [err, setErr] = React.useState("");

  React.useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/signup-onboarding/state");
        if (r?.completed) {
          nav("/dashboard?welcome=1", { replace: true });
          return;
        }
        setState(r);
      } catch (ex) {
        setErr(String(ex && ex.message ? ex.message : ex));
      } finally {
        setLoading(false);
      }
    })();
  }, [nav]);

  const advance = async (path, payload) => {
    setSaving(true); setErr("");
    try {
      const r = await api.patch(`/signup-onboarding/step/${path}`, payload);
      setState((s) => ({
        ...s, step: r.step, data: s.data,
        completed: !!r.completed,
      }));
      if (r.completed) {
        toast.success(t("onboarding.completed",
                            "Onboarding complete. Welcome!"));
        nav("/dashboard?welcome=1", { replace: true });
      }
    } catch (ex) {
      const raw = String(ex && ex.message ? ex.message : ex);
      setErr(raw);
      toast.error(raw);
    } finally {
      setSaving(false);
    }
  };

  const skipAll = async () => {
    setSaving(true);
    try {
      await api.post("/signup-onboarding/complete");
      nav("/dashboard?welcome=1", { replace: true });
    } catch (ex) {
      toast.error(String(ex && ex.message ? ex.message : ex));
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div data-testid="onboarding-wizard-loading"
            style={{ maxWidth: 640, margin: "60px auto", padding: 24 }}>
        {t("onboarding.loading", "Loading…")}
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 640, margin: "40px auto", padding: 24,
                    fontFamily: "system-ui" }}
          data-testid="onboarding-wizard-page">
      <h1 style={{ fontSize: 24, marginBottom: 8 }}>
        {t("onboarding.title", "Let's get you set up")}
      </h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 24 }}
            data-testid="onboarding-progress-bar">
        {[1, 2, 3, 4].map((n) => (
          <div key={n} data-testid={`onboarding-step-dot-${n}`}
                style={{ flex: 1, height: 6, borderRadius: 3,
                          background: state.step >= n ? "#2563EB" : "#E2E8F0" }} />
        ))}
      </div>
      {err ? (
        <div data-testid="onboarding-error" style={{
          padding: 12, border: "1px solid #DC2626",
          background: "#FEF2F2", color: "#991B1B",
          borderRadius: 6, marginBottom: 16,
        }}>{err}</div>
      ) : null}
      {state.step === 1 && <Step1 data={state.data}
                                       onNext={(p) => advance("1", p)}
                                       saving={saving} t={t} />}
      {state.step === 2 && <Step2 data={state.data}
                                       onNext={(p) => advance("2", p)}
                                       saving={saving} t={t} />}
      {state.step === 3 && <Step3 onNext={(p) => advance("3", p)}
                                       saving={saving} t={t} />}
      {state.step === 4 && <Step4 data={state.data}
                                       onNext={(p) => advance("4", p)}
                                       saving={saving} t={t} />}
      <div style={{ marginTop: 24, textAlign: "right" }}>
        <button onClick={skipAll} disabled={saving}
                  data-testid="onboarding-skip-all"
                  style={{ padding: "6px 10px", background: "transparent",
                            border: "1px solid #94A3B8", borderRadius: 6,
                            fontSize: 12, cursor: "pointer" }}>
          {t("onboarding.skip_all", "Skip everything")}
        </button>
      </div>
    </div>
  );
}


function Step1({ data, onNext, saving, t }) {
  const [f, setF] = React.useState({
    business_name: data.business_name || "",
    phone:         data.phone || "",
    address:       data.address || "",
  });
  return (
    <div data-testid="onboarding-step-1">
      <h2>{t("onboarding.step_1.title", "Confirm your business profile")}</h2>
      <label>{t("onboarding.step_1.business_name", "Business name")}
        <input value={f.business_name}
                data-testid="onboarding-step-1-business-name"
                onChange={(e) => setF({ ...f, business_name: e.target.value })} />
      </label>
      <label>{t("onboarding.step_1.phone", "Phone")}
        <input value={f.phone}
                data-testid="onboarding-step-1-phone"
                onChange={(e) => setF({ ...f, phone: e.target.value })} />
      </label>
      <label>{t("onboarding.step_1.address", "Address")}
        <input value={f.address}
                data-testid="onboarding-step-1-address"
                onChange={(e) => setF({ ...f, address: e.target.value })} />
      </label>
      <button onClick={() => onNext(f)} disabled={saving}
                data-testid="onboarding-step-1-next"
                style={{ marginTop: 16, padding: "10px 14px",
                          background: "#2563EB", color: "#fff", border: 0,
                          borderRadius: 6, fontWeight: 600 }}>
        {t("onboarding.next", "Continue")}
      </button>
    </div>
  );
}


function Step2({ data, onNext, saving, t }) {
  const [tz, setTz] = React.useState(data.timezone || "America/Phoenix");
  return (
    <div data-testid="onboarding-step-2">
      <h2>{t("onboarding.step_2.title", "Confirm your timezone")}</h2>
      <TimezoneSelect value={tz}
                        testid="onboarding-step-2-timezone"
                        onChange={(e) => setTz(e.target.value)}
                        label={t("timezone.label", "Timezone")} />
      <button onClick={() => onNext({ timezone: tz })} disabled={saving}
                data-testid="onboarding-step-2-next"
                style={{ marginTop: 16, padding: "10px 14px",
                          background: "#2563EB", color: "#fff", border: 0,
                          borderRadius: 6, fontWeight: 600 }}>
        {t("onboarding.next", "Continue")}
      </button>
    </div>
  );
}


function Step3({ onNext, saving, t }) {
  const [invites, setInvites] = React.useState([
    { email: "", role: "tech" },
  ]);
  return (
    <div data-testid="onboarding-step-3">
      <h2>{t("onboarding.step_3.title", "Invite your team")}</h2>
      {invites.map((inv, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <input placeholder="teammate@company.com" value={inv.email}
                  data-testid={`onboarding-step-3-invite-${i}-email`}
                  onChange={(e) => setInvites(invites.map((x, j) =>
                    j === i ? { ...x, email: e.target.value } : x))} />
          <select value={inv.role}
                    data-testid={`onboarding-step-3-invite-${i}-role`}
                    onChange={(e) => setInvites(invites.map((x, j) =>
                      j === i ? { ...x, role: e.target.value } : x))}>
            <option value="tech">Tech</option>
            <option value="manager">Manager</option>
            <option value="admin">Admin</option>
          </select>
        </div>
      ))}
      <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
        <button onClick={() => onNext({
                    invites: invites.filter((i) => i.email.trim()),
                  })}
                  disabled={saving}
                  data-testid="onboarding-step-3-next"
                  style={{ padding: "10px 14px", background: "#2563EB",
                            color: "#fff", border: 0, borderRadius: 6,
                            fontWeight: 600 }}>
          {t("onboarding.next", "Continue")}
        </button>
        <button onClick={() => onNext({ invites: [] })} disabled={saving}
                  data-testid="onboarding-step-3-skip"
                  style={{ padding: "10px 14px", background: "#F1F5F9",
                            color: "#0F172A", border: "1px solid #94A3B8",
                            borderRadius: 6, fontWeight: 600 }}>
          {t("onboarding.skip_step", "Skip for now")}
        </button>
      </div>
    </div>
  );
}


function Step4({ data, onNext, saving, t }) {
  const primary = data.primary_industry;
  const [selected, setSelected] = React.useState(
    Array.isArray(data.active_industries) && data.active_industries.length
      ? Array.from(new Set([primary, ...data.active_industries]))
        .filter(Boolean)
      : (primary ? [primary] : []),
  );
  const toggle = (slug) => {
    if (slug === primary) return;  // primary is locked in
    setSelected((s) => s.includes(slug)
      ? s.filter((x) => x !== slug)
      : [...s, slug]);
  };
  return (
    <div data-testid="onboarding-step-4">
      <h2>{t("onboarding.step_4.title", "Choose your active industries")}</h2>
      <p style={{ color: "#64748B", fontSize: 13 }}>
        {t("onboarding.step_4.primary_hint",
            "Your primary industry is locked in — you can add more.")}
      </p>
      <div style={{ display: "grid",
                     gridTemplateColumns: "repeat(2, 1fr)", gap: 8,
                     marginTop: 12 }}>
        {INDUSTRIES.map((slug) => {
          const isPrimary = slug === primary;
          const isSel = selected.includes(slug);
          return (
            <label key={slug}
                    data-testid={`onboarding-step-4-industry-${slug}`}
                    data-primary={isPrimary ? "true" : "false"}
                    data-selected={isSel ? "true" : "false"}
                    style={{ padding: 8, borderRadius: 6,
                              border: isSel ? "2px solid #2563EB"
                                              : "1px solid #E2E8F0",
                              background: isPrimary ? "#EFF6FF" : "#fff",
                              cursor: isPrimary ? "not-allowed" : "pointer",
                              opacity: isPrimary ? 0.85 : 1 }}>
              <input type="checkbox" checked={isSel} disabled={isPrimary}
                      onChange={() => toggle(slug)}
                      data-testid={`onboarding-step-4-checkbox-${slug}`} />
              {" "}
              {t(`industries.${slug}`, slug.replace(/_/g, " "))}
              {isPrimary && (
                <span style={{ marginLeft: 6, fontSize: 11,
                                 color: "#2563EB", fontWeight: 600 }}>
                  {t("onboarding.step_4.primary_badge", "PRIMARY")}
                </span>
              )}
            </label>
          );
        })}
      </div>
      <button onClick={() => onNext({ industries: selected })}
                disabled={saving || !selected.length}
                data-testid="onboarding-step-4-next"
                style={{ marginTop: 16, padding: "10px 14px",
                          background: "#10B981", color: "#fff", border: 0,
                          borderRadius: 6, fontWeight: 600,
                          opacity: !selected.length ? 0.6 : 1 }}>
        {t("onboarding.finish", "Finish onboarding")}
      </button>
    </div>
  );
}
