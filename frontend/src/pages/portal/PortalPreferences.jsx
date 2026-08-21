/**
 * Feb-2026 · Marketing Slice F — Customer preference center.
 *
 * Two entry paths:
 *   1. Logged-in customer → uses /customer-portal/preferences
 *   2. Magic-link         → reads ?token=… and uses the public
 *                           /portal/preferences/{token/verify,via-token}
 */
import React, { useEffect, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Save, Lock, ShieldCheck, MailX } from "lucide-react";
import { api } from "@/api";
import { brandGradientCss, colors } from "@/theme";
import { useAuth } from "@/auth";
import PortalWalkthrough from "@/pages/portal/PortalWalkthrough";
// Feb-2026 · P11b — App Store consumer-account guideline blockers 3 + 4.
import DeleteAccountDangerCard from "@/components/portal/DeleteAccountDangerCard";


const CHANNEL_LABELS = {
  email_marketing: "Email · marketing",
  email_transactional: "Email · transactional (invoices, receipts, service reports)",
  sms_marketing: "SMS · marketing",
  sms_transactional: "SMS · transactional",
};
const CATEGORY_LABELS = {
  review_requests: "Review requests",
  sequences: "Service reminders / drip sequences",
  campaigns: "Promotional campaigns",
};


export default function PortalPreferences() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");

  const [prefs, setPrefs] = useState(null);
  const [tokenChecked, setTokenChecked] = useState(!token);
  const [tokenErr, setTokenErr] = useState("");
  const [tokenCtx, setTokenCtx] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (token) {
      api.get(`/portal/preferences/token/verify?token=${encodeURIComponent(token)}`)
        .then((r) => {
          setTokenCtx(r);
          setPrefs({ channel_opt_in: r.channel_opt_in,
                      category_opt_in: r.category_opt_in });
        })
        .catch((e) => setTokenErr(e?.message || "This link has expired."))
        .finally(() => setTokenChecked(true));
      return;
    }
    if (!user || user.role !== "customer") return;
    api.get("/customer-portal/preferences")
      .then(setPrefs)
      .catch(() => setPrefs({
        channel_opt_in: { email_marketing: true, email_transactional: true,
                           sms_marketing: true, sms_transactional: true },
        category_opt_in: { review_requests: true, sequences: true, campaigns: true },
      }));
  }, [token, user?.id]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: deps 'user' intentionally omitted (mount-only or stable-ref)

  const flipChannel = (key, val) => {
    setPrefs((p) => ({ ...p,
      channel_opt_in: { ...p.channel_opt_in, [key]: val } }));
    setSaved(false);
  };
  const flipCategory = (key, val) => {
    setPrefs((p) => ({ ...p,
      category_opt_in: { ...p.category_opt_in, [key]: val } }));
    setSaved(false);
  };

  const save = async () => {
    setBusy(true); setError(""); setSaved(false);
    try {
      const payload = {
        channel_opt_in: prefs.channel_opt_in,
        category_opt_in: prefs.category_opt_in,
      };
      const updated = token
        ? await api.post("/portal/preferences/via-token", { token, ...payload })
        : await api.patch("/customer-portal/preferences", payload);
      setPrefs(updated);
      setSaved(true);
    } catch (e) { setError(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  if (!token && user && user.role !== "customer") {
    return <Navigate to="/" replace />;
  }
  if (token && !tokenChecked) {
    return (
      <div className="max-w-lg mx-auto p-6 text-sm" style={{ color: colors.muted }}>
        Verifying your link…
      </div>
    );
  }
  if (token && tokenErr) {
    return (
      <div className="max-w-lg mx-auto p-6"
           data-testid="portal-preferences-token-expired">
        <div className="rounded-2xl p-6 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <MailX size={22} className="mx-auto mb-2" style={{ color: "#92400E" }} />
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            This link has expired
          </h2>
          <p className="text-sm mt-2" style={{ color: colors.muted }}>
            {tokenErr} Please log in to your customer portal to update your preferences.
          </p>
        </div>
      </div>
    );
  }
  if (!prefs) {
    return (
      <div className="max-w-lg mx-auto p-6 text-sm" style={{ color: colors.muted }}>
        Loading…
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="portal-preferences-page">
      {!token ? (
        <button onClick={() => navigate("/portal/home")}
                className="flex items-center gap-1 text-sm font-semibold mb-4"
                style={{ color: colors.muted }}>
          <ArrowLeft size={14} /> Home
        </button>
      ) : null}

      <div className="mb-5">
        <h1 className="text-2xl font-bold tracking-tight" style={{ color: colors.onSurface }}>
          Communication preferences
        </h1>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          {tokenCtx?.customer_name
            ? `Hi ${tokenCtx.customer_name.split(" ")[0]} — control what we send you.`
            : "Control which marketing messages we send you. Transactional emails (invoices, receipts, service reports) are always sent."}
        </p>
      </div>

      <Section title="Channels">
        {Object.entries(prefs.channel_opt_in).map(([k, v]) => {
          const locked = k.endsWith("_transactional");
          return (
            <ToggleRow
              key={k}
              testid={`pref-${k.replace(/_/g, "-")}`}
              label={CHANNEL_LABELS[k] || k}
              value={v}
              locked={locked}
              onChange={(val) => flipChannel(k, val)}
            />
          );
        })}
      </Section>

      <Section title="Categories">
        {Object.entries(prefs.category_opt_in).map(([k, v]) => (
          <ToggleRow
            key={k}
            testid={`pref-cat-${k.replace(/_/g, "-")}`}
            label={CATEGORY_LABELS[k] || k}
            value={v}
            onChange={(val) => flipCategory(k, val)}
          />
        ))}
      </Section>

      {error ? (
        <div className="text-sm mt-4" style={{ color: colors.error }}>{error}</div>
      ) : null}
      {saved ? (
        <div className="text-sm mt-4 inline-flex items-center gap-1"
             style={{ color: "#16A34A" }}
             data-testid="portal-preferences-saved">
          <ShieldCheck size={13} /> Preferences saved.
        </div>
      ) : null}

      <div className="mt-6 flex justify-end">
        <button onClick={save} disabled={busy}
                className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
                style={{ background: brandGradientCss }}
                data-testid="portal-preferences-save-btn">
          <Save size={14} /> {busy ? "Saving…" : "Save preferences"}
        </button>
      </div>

      {/* Feb-2026 · Slice I — Replay the first-login walkthrough
          without clearing the server-side ``portal_walkthrough_completed_at``
          flag. The tour is force-opened via the ``forceOpen`` prop and
          only closed locally when the customer completes/skips it. */}
      <ReplayTourButton />

      {/* Feb-2026 · P11b — Delete-account danger card (App Store
          consumer-account guideline blocker item 3).  Only rendered
          on the logged-in surface — token-based (magic link) callers
          don't have a session to invalidate. */}
      {!token ? <DeleteAccountDangerCard /> : null}

      {/* Feb-2026 · P11b — Privacy Policy footer link (App Store item 4). */}
      <div className="mt-6 text-center">
        <a
          href="/privacy-policy"
          className="text-sm font-semibold underline"
          style={{ color: colors.muted }}
          data-testid="portal-preferences-privacy-policy-link"
        >
          Privacy Policy
        </a>
      </div>
    </div>
  );
}


function ReplayTourButton() {
  const [replaying, setReplaying] = React.useState(false);
  return (
    <>
      <div className="mt-4">
        <button onClick={() => setReplaying(true)}
                className="text-sm font-semibold underline"
                style={{ color: colors.brand }}
                data-testid="portal-preferences-replay-tour-btn">
          Replay portal tour
        </button>
      </div>
      {replaying && (
        <PortalWalkthrough forceOpen onClose={() => setReplaying(false)} />
      )}
    </>
  );
}


function Section({ title, children }) {
  return (
    <div className="rounded-2xl p-4 mb-4"
         style={{ backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}` }}>
      <h3 className="text-[10px] font-bold uppercase tracking-wider mb-3"
          style={{ color: colors.muted }}>{title}</h3>
      <div className="space-y-2">{children}</div>
    </div>
  );
}


function ToggleRow({ label, value, locked, onChange, testid }) {
  return (
    <label className={`flex items-center justify-between gap-3 py-1 ${locked ? "opacity-60" : "cursor-pointer"}`}>
      <span className="text-sm inline-flex items-center gap-1"
            style={{ color: colors.onSurface }}>
        {locked ? <Lock size={12} style={{ color: colors.muted }} /> : null}
        {label}
      </span>
      <input type="checkbox" checked={!!value} disabled={locked}
             onChange={(e) => onChange(e.target.checked)}
             data-testid={testid} />
    </label>
  );
}
