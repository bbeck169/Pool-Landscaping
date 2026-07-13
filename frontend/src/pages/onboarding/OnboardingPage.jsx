import React, { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import { Check, ChevronRight, ChevronLeft, ExternalLink, X, Sparkles, Rocket } from "lucide-react";

const STEPS = [
  { key: "welcome",       title: "Welcome",              blurb: "Tell us about your business." },
  { key: "integrations",  title: "Connect integrations", blurb: "Which providers are you already on?" },
  { key: "customers",     title: "Import customers",     blurb: "Bring your existing book of business." },
  { key: "price_book",    title: "Configure price book", blurb: "Start with a template you can edit later." },
  { key: "brand_memory",  title: "Brand memory",         blurb: "Teach the AI marketing studio your voice." },
  { key: "team",          title: "Invite team",          blurb: "Onboard your techs and dispatchers." },
  { key: "campaign",      title: "Schedule campaign",    blurb: "Pick your first marketing send." },
];

const Card = ({ children, className = "", testId }) => (
  <div className={"rounded-2xl " + className}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);
const Input = ({ label, value, onChange, placeholder, testId, type = "text" }) => (
  <label className="block mb-3">
    <div className="text-xs font-semibold tracking-wide mb-1" style={{ color: colors.onSurfaceSecondary }}>{label}</div>
    <input value={value || ""} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} type={type}
           className="w-full px-3 py-2 rounded-lg text-sm outline-none"
           style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
           data-testid={testId} />
  </label>
);

export default function OnboardingPage() {
  const navigate = useNavigate();
  const [state, setState] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const load = () => api.get("/onboarding").then(setState).catch((e) => setError(e.message || "Failed"));
  useEffect(() => { load(); }, []);

  if (!state) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  const step = Math.min(state.current_step, STEPS.length - 1);
  const isLast = step === STEPS.length - 1;
  const pct = Math.round(((state.current_step) / STEPS.length) * 100);

  const patch = async (upd) => {
    setSaving(true);
    try {
      const next = await api.post("/onboarding/progress", upd);
      setState(next);
    } catch (e) { setError(e.message || "Failed"); }
    finally { setSaving(false); }
  };

  const setData = (k, v) => patch({ data: { [k]: v } });
  const advance = () => patch({ current_step: Math.min(STEPS.length, state.current_step + 1) });
  const goBack = () => patch({ current_step: Math.max(0, state.current_step - 1) });
  const skipAll = () => patch({ skipped: true });
  const finish = () => patch({ completed: true }).then(() => setTimeout(() => navigate("/"), 800));

  if (state.completed) {
    return (
      <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="onboarding-done">
        <Card className="p-10 text-center">
          <div className="text-6xl mb-4">🎉</div>
          <h1 className="text-3xl font-bold mb-2" style={{ color: colors.onSurface }}>You're all set!</h1>
          <p className="text-sm mb-6" style={{ color: colors.muted }}>
            Onboarding complete. You can revisit these steps any time from Settings.
          </p>
          <div className="flex gap-2 justify-center">
            <button onClick={() => navigate("/")}
                    className="px-5 py-2.5 rounded-xl text-sm font-bold text-white"
                    style={{ background: brandGradientCss }}
                    data-testid="onboarding-explore">Explore the dashboard</button>
            <button onClick={() => api.post("/onboarding/restart", {}).then(setState)}
                    className="px-5 py-2.5 rounded-xl text-sm font-semibold"
                    style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                    data-testid="onboarding-restart">Restart onboarding</button>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="onboarding-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="text-xs uppercase tracking-wide" style={{ color: colors.muted }}>Onboarding</div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>{STEPS[step].title}</h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>{STEPS[step].blurb}</p>
        </div>
        <button onClick={skipAll}
                className="text-xs font-semibold px-3 py-1.5 rounded-lg"
                style={{ backgroundColor: colors.surfaceSecondary, color: colors.muted }}
                data-testid="onboarding-skip-all">Skip for now</button>
      </div>

      {/* Progress bar */}
      <div className="mb-6" data-testid="onboarding-progress">
        <div className="h-2 rounded-full overflow-hidden" style={{ backgroundColor: colors.surfaceSecondary }}>
          <div className="h-full transition-all duration-500"
               style={{ width: `${pct}%`, background: brandGradientCss }} />
        </div>
        <div className="flex justify-between mt-2 text-[10px] uppercase tracking-wide" style={{ color: colors.muted }}>
          {STEPS.map((s, i) => (
            <div key={s.key} className={i === step ? "font-bold" : ""}
                 style={{ color: i < state.current_step ? "#16A34A" : (i === step ? colors.brand : colors.muted) }}
                 data-testid={`step-label-${s.key}`}>
              {i < state.current_step ? "✓" : i + 1}. {s.title}
            </div>
          ))}
        </div>
      </div>

      <Card className="p-6">
        {step === 0 && <StepWelcome data={state.data} setData={setData} />}
        {step === 1 && <StepIntegrations data={state.data} setData={setData} />}
        {step === 2 && <StepCustomers data={state.data} setData={setData} />}
        {step === 3 && <StepPriceBook data={state.data} setData={setData} />}
        {step === 4 && <StepBrandMemory data={state.data} setData={setData} />}
        {step === 5 && <StepTeam data={state.data} setData={setData} />}
        {step === 6 && <StepCampaign data={state.data} setData={setData} />}
      </Card>

      {error && <div className="mt-3 text-sm text-center" style={{ color: colors.error }}>{error}</div>}

      <div className="flex items-center justify-between mt-4">
        <button onClick={goBack} disabled={step === 0}
                className="flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-semibold"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`,
                         color: colors.onSurface, opacity: step === 0 ? 0.4 : 1 }}
                data-testid="onboarding-back">
          <ChevronLeft size={14} /> Back
        </button>
        {isLast ? (
          <button onClick={finish} disabled={saving}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold text-white"
                  style={{ background: brandGradientCss, opacity: saving ? 0.7 : 1 }}
                  data-testid="onboarding-finish">
            <Rocket size={14} /> Finish setup
          </button>
        ) : (
          <button onClick={advance} disabled={saving}
                  className="flex items-center gap-1 px-5 py-2.5 rounded-xl text-sm font-bold text-white"
                  style={{ background: brandGradientCss, opacity: saving ? 0.7 : 1 }}
                  data-testid="onboarding-next">
            Continue <ChevronRight size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

/* ─── Steps ────────────────────────────────────────────────── */
function StepWelcome({ data, setData }) {
  return (
    <div data-testid="step-welcome">
      <Input label="BUSINESS NAME" value={data?.business_name || "AquaTerra"} onChange={(v) => setData("business_name", v)} testId="in-business-name" />
      <div className="grid grid-cols-2 gap-3">
        <Input label="SERVICE RADIUS (MILES)" type="number" value={data?.service_radius || 25}
               onChange={(v) => setData("service_radius", parseInt(v || "0", 10))} testId="in-service-radius" />
        <Input label="TIMEZONE" value={data?.timezone || "America/Phoenix"} onChange={(v) => setData("timezone", v)} testId="in-timezone" />
      </div>
    </div>
  );
}

function StepIntegrations({ data, setData }) {
  const [live, setLive] = useState({});
  useEffect(() => {
    api.get("/settings/integrations").then(setLive).catch(() => setLive({}));
  }, []);
  const providers = [
    { key: "stripe", label: "Stripe (Payments)" },
    { key: "google", label: "Google (Maps + Places)" },
    { key: "resend", label: "Resend (Email)" },
    { key: "twilio", label: "Twilio (SMS)" },
    { key: "openweb", label: "OpenWeb Ninja (Search)" },
  ];
  return (
    <div data-testid="step-integrations">
      <p className="text-sm mb-3" style={{ color: colors.muted }}>
        Connect providers now, or later from Settings → Integrations.
      </p>
      {providers.map((p) => {
        const status = live?.[p.key]?.status || live?.[p.key] || "";
        const isLive = status === "live" || status === "connected" || status === true;
        return (
          <div key={p.key} className="flex items-center justify-between px-3 py-2 rounded-lg mb-2"
               style={{ backgroundColor: colors.surfaceSecondary }}
               data-testid={`integration-${p.key}`}>
            <div className="text-sm" style={{ color: colors.onSurface }}>{p.label}</div>
            <span className="text-xs font-bold px-2 py-1 rounded"
                  style={{
                    backgroundColor: isLive ? "#DCFCE7" : colors.surface,
                    color: isLive ? "#166534" : colors.muted,
                  }}>
              {isLive ? "LIVE" : "Not connected"}
            </span>
          </div>
        );
      })}
      <a href="/settings/integrations" target="_blank" rel="noreferrer"
         className="inline-flex items-center gap-1 mt-2 text-sm font-semibold"
         style={{ color: colors.brand }}
         data-testid="integration-hub-link">
        Open integrations hub <ExternalLink size={12} />
      </a>
    </div>
  );
}

function StepCustomers({ data, setData }) {
  const choice = data?.customers_choice || "seed";
  const set = (v) => setData("customers_choice", v);
  return (
    <div data-testid="step-customers">
      <p className="text-sm mb-3" style={{ color: colors.muted }}>Bring your existing customers now — you can also do it later.</p>
      {[
        { k: "csv", label: "Upload a CSV", sub: "We'll walk you through import → /customers/import" },
        { k: "seed", label: "Start with seed data", sub: "Ready-made demo customers to explore the app" },
        { k: "skip", label: "Skip for now", sub: "Add customers later from the Customers screen" },
      ].map((o) => (
        <label key={o.k} className="flex items-start gap-3 p-3 rounded-lg mb-2 cursor-pointer"
               style={{ backgroundColor: choice === o.k ? colors.brandTertiary : colors.surfaceSecondary,
                        border: `1px solid ${choice === o.k ? colors.brand : colors.border}` }}
               data-testid={`customers-choice-${o.k}`}>
          <input type="radio" checked={choice === o.k} onChange={() => set(o.k)} />
          <div>
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{o.label}</div>
            <div className="text-xs" style={{ color: colors.muted }}>{o.sub}</div>
          </div>
        </label>
      ))}
    </div>
  );
}

function StepPriceBook({ data, setData }) {
  const choice = data?.price_book_choice;
  const templates = [
    { k: "pool_weekly",  label: "Pool Weekly",    sub: "Chemistry balance + 8-point cleaning" },
    { k: "landscape",    label: "Landscape Weekly", sub: "Mow, blow, trim, weed" },
    { k: "full_service", label: "Full Service",   sub: "Combined pool + landscape package" },
    { k: "manual",       label: "Add manually later", sub: "" },
  ];
  return (
    <div data-testid="step-price-book">
      <p className="text-sm mb-3" style={{ color: colors.muted }}>Pick a template to seed a starter price book.</p>
      {templates.map((t) => (
        <label key={t.k} className="flex items-start gap-3 p-3 rounded-lg mb-2 cursor-pointer"
               style={{ backgroundColor: choice === t.k ? colors.brandTertiary : colors.surfaceSecondary,
                        border: `1px solid ${choice === t.k ? colors.brand : colors.border}` }}
               data-testid={`price-book-${t.k}`}>
          <input type="radio" checked={choice === t.k} onChange={() => setData("price_book_choice", t.k)} />
          <div>
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{t.label}</div>
            {t.sub && <div className="text-xs" style={{ color: colors.muted }}>{t.sub}</div>}
          </div>
        </label>
      ))}
    </div>
  );
}

function StepBrandMemory({ data, setData }) {
  return (
    <div data-testid="step-brand-memory">
      <label className="block mb-3">
        <div className="text-xs font-semibold tracking-wide mb-1" style={{ color: colors.onSurfaceSecondary }}>BUSINESS DESCRIPTION</div>
        <textarea value={data?.brand_description || ""} onChange={(e) => setData("brand_description", e.target.value)} rows={3}
                  placeholder="Full-service pool + landscaping for Vistancia and surrounding neighborhoods."
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                  style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                  data-testid="in-brand-description" />
      </label>
      <div className="grid grid-cols-2 gap-3">
        <label>
          <div className="text-xs font-semibold tracking-wide mb-1" style={{ color: colors.onSurfaceSecondary }}>TONE PRESET</div>
          <select value={data?.tone || "warm"} onChange={(e) => setData("tone", e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                  style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                  data-testid="in-tone">
            {["warm", "professional", "witty", "energetic", "formal"].map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <Input label="TARGET CUSTOMER" value={data?.target_customer} onChange={(v) => setData("target_customer", v)}
               placeholder="Homeowners in gated communities" testId="in-target-customer" />
      </div>
    </div>
  );
}

function StepTeam({ data, setData }) {
  const invites = data?.team_invites || [{ email: "", role: "technician" }, { email: "", role: "technician" }, { email: "", role: "technician" }];
  const set = (i, k, v) => {
    const next = invites.map((row, ri) => ri === i ? { ...row, [k]: v } : row);
    setData("team_invites", next);
  };
  return (
    <div data-testid="step-team">
      <p className="text-sm mb-3" style={{ color: colors.muted }}>Invite up to 3 teammates now. You can add more later.</p>
      {invites.map((row, i) => (
        <div key={i} className="grid grid-cols-3 gap-2 mb-2" data-testid={`team-row-${i}`}>
          <input value={row.email} onChange={(e) => set(i, "email", e.target.value)}
                 placeholder="teammate@example.com"
                 className="col-span-2 px-3 py-2 rounded-lg text-sm outline-none"
                 style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                 data-testid={`team-email-${i}`} />
          <select value={row.role} onChange={(e) => set(i, "role", e.target.value)}
                  className="px-3 py-2 rounded-lg text-sm outline-none"
                  style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                  data-testid={`team-role-${i}`}>
            <option value="technician">Technician</option>
            <option value="admin">Admin</option>
            <option value="dispatcher">Dispatcher</option>
          </select>
        </div>
      ))}
      <p className="text-xs mt-2" style={{ color: colors.muted }}>
        Invites are queued; you can fire them from Team &amp; Roles when ready.
      </p>
    </div>
  );
}

function StepCampaign({ data, setData }) {
  const choice = data?.campaign_choice || "";
  const templates = [
    { k: "spring-tune-up", label: "Spring Tune-up", sub: "Owner outreach for filter + salt cell service" },
    { k: "review-nudge", label: "Review Nudge", sub: "Ask happy customers to leave a Google review" },
    { k: "hoa-outreach", label: "HOA Outreach", sub: "Pitch community-scale contracts" },
    { k: "skip", label: "Skip for now", sub: "" },
  ];
  return (
    <div data-testid="step-campaign">
      <p className="text-sm mb-3" style={{ color: colors.muted }}>Pick a seeded campaign template to schedule your first send.</p>
      {templates.map((t) => (
        <label key={t.k} className="flex items-start gap-3 p-3 rounded-lg mb-2 cursor-pointer"
               style={{ backgroundColor: choice === t.k ? colors.brandTertiary : colors.surfaceSecondary,
                        border: `1px solid ${choice === t.k ? colors.brand : colors.border}` }}
               data-testid={`campaign-${t.k}`}>
          <input type="radio" checked={choice === t.k} onChange={() => setData("campaign_choice", t.k)} />
          <div>
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{t.label}</div>
            {t.sub && <div className="text-xs" style={{ color: colors.muted }}>{t.sub}</div>}
          </div>
        </label>
      ))}
      <label className="block mt-3">
        <div className="text-xs font-semibold tracking-wide mb-1" style={{ color: colors.onSurfaceSecondary }}>LAUNCH DATE</div>
        <input type="date" value={data?.campaign_launch || ""} onChange={(e) => setData("campaign_launch", e.target.value)}
               className="px-3 py-2 rounded-lg text-sm outline-none"
               style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
               data-testid="in-campaign-launch" />
      </label>
    </div>
  );
}

/* ─── First-login modal ─────────────────────────────────────── */
export function OnboardingLoginModal() {
  const navigate = useNavigate();
  const location = useLocation();
  const [state, setState] = useState(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    // Don't fire on the onboarding page itself.
    if (location.pathname.startsWith("/onboarding") || location.pathname.startsWith("/settings/onboarding")) return;
    // Only show once per browser session.
    if (sessionStorage.getItem("onboarding_modal_seen") === "1") return;
    api.get("/onboarding").then((s) => {
      if (!s.completed && !s.skipped) setState(s);
    }).catch(() => {});
  }, [location.pathname]);

  if (!state || dismissed) return null;
  const close = () => { sessionStorage.setItem("onboarding_modal_seen", "1"); setDismissed(true); };
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4"
         style={{ backgroundColor: "rgba(0,0,0,0.55)" }}
         data-testid="onboarding-modal">
      <div className="rounded-2xl max-w-md w-full p-6"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="text-4xl mb-3">👋</div>
        <h2 className="text-xl font-bold mb-2" style={{ color: colors.onSurface }}>Welcome to AquaTerra</h2>
        <p className="text-sm mb-6" style={{ color: colors.muted }}>
          Let's get you set up in 3 minutes.
        </p>
        <div className="flex gap-2">
          <button onClick={() => { close(); navigate("/onboarding"); }}
                  className="flex-1 px-4 py-2.5 rounded-xl text-sm font-bold text-white"
                  style={{ background: brandGradientCss }}
                  data-testid="onboarding-modal-start">
            <Sparkles size={14} className="inline mr-1" /> Start setup
          </button>
          <button onClick={close}
                  className="px-4 py-2.5 rounded-xl text-sm font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                  data-testid="onboarding-modal-skip">Skip for now</button>
        </div>
      </div>
    </div>
  );
}
