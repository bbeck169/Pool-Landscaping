import React from "react";
import { useNavigate } from "react-router-dom";
import { UserCog, Check, AlertTriangle, Clock } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors, brandGradientCss } from "@/theme";

/**
 * Feb-2026 · Customer self-serve profile-completion gate.
 *
 * Renders NOTHING unless the server-authoritative
 * ``user.customer_record_missing`` flag is true. When it renders, the
 * gate blocks the entire viewport (fixed inset-0 · z-[70] — just under
 * the ToS gate at z-[80] so ToS wins if both fire) until either:
 *
 *   1. The customer submits the form → POST ``/portal/complete-profile``.
 *      On 2xx we PATCH the auth-context user in place (flip
 *      ``customer_record_missing`` to false + stamp ``customer_id``),
 *      persist to localStorage, then route to /portal/home.
 *   2. The customer clicks "Skip for now" → POST a reminder audit note
 *      via ``/portal/complete-profile?skip=1`` (the server still checks
 *      idempotency) and lets them into the portal for this session. The
 *      flag flips back on the next /auth/me refresh so we do NOT flip it
 *      client-side.
 *
 * The gate is mounted at the AppLayout shell alongside ``<TosGate />``.
 */
export default function ProfileCompletionGate() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = React.useState({
    first_name: "",
    last_name: "",
    phone: "",
    service_address: "",
    preferred_contact: "email",
  });
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [skipped, setSkipped] = React.useState(false);

  // Skip decision is remembered for the SESSION only. Refresh or
  // navigation-only remount clears the reminder; the server-side flag
  // will still be true on the next /auth/me so this gate returns.
  React.useEffect(() => {
    try {
      const flag = sessionStorage.getItem("profile_completion_skipped");
      if (flag === "1") setSkipped(true);
    } catch { /* ignore */ }
  }, []);

  // Prefill first/last from `user.name` on mount if we have it.
  React.useEffect(() => {
    if (!user || !user.name) return;
    const [f, ...rest] = (user.name || "").trim().split(" ");
    setForm((s) => ({
      ...s,
      first_name: s.first_name || f || "",
      last_name: s.last_name || rest.join(" ") || "",
      phone: s.phone || user.phone || "",
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  const gated =
    !!user &&
    user.role === "customer" &&
    user.customer_record_missing === true &&
    !skipped;

  if (!gated) return null;

  const setField = (k) => (e) => {
    setError("");
    setForm((f) => ({ ...f, [k]: e?.target?.value ?? "" }));
  };

  const submit = async (e) => {
    e?.preventDefault?.();
    setError("");
    const first = (form.first_name || "").trim();
    const last = (form.last_name || "").trim();
    const phone = (form.phone || "").trim();
    const addr = (form.service_address || "").trim();
    if (!first || !last) {
      setError("First and last name are required.");
      return;
    }
    if (!phone) {
      setError("A phone number is required so we can reach you.");
      return;
    }
    if (!addr) {
      setError("Please add the service address for your property.");
      return;
    }
    setSaving(true);
    try {
      const res = await api.post("/portal/complete-profile", {
        first_name: first,
        last_name: last,
        phone,
        service_address: addr,
        preferred_contact: form.preferred_contact || "email",
      });
      const nextUser = {
        ...user,
        customer_id: res?.customer_id || user.customer_id,
        customer_record_missing: false,
        phone: phone || user.phone,
        name: `${first} ${last}`.trim() || user.name,
      };
      setUser(nextUser);
      try {
        localStorage.setItem("user", JSON.stringify(nextUser));
      } catch { /* ignore quota errors */ }
      navigate("/portal/home", { replace: true });
    } catch (e) {
      setError(e?.message || "Could not save your profile. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const onSkip = () => {
    try { sessionStorage.setItem("profile_completion_skipped", "1"); } catch { /* ignore */ }
    setSkipped(true);
    // Fire-and-forget audit note. Never block on this — the customer
    // has clicked "Later" and we should not throw a modal error at them.
    api.post("/portal/complete-profile?skip=1", {}).catch(() => { /* audit only */ });
  };

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center p-0 sm:p-4"
      style={{ background: "rgba(15,23,42,0.72)" }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="profile-gate-title"
      data-testid="profile-completion-gate"
    >
      <div
        className="w-full sm:max-w-lg h-full sm:h-auto sm:max-h-[92vh] rounded-none sm:rounded-2xl shadow-2xl flex flex-col overflow-hidden"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="px-5 py-4 flex items-center gap-3"
          style={{
            borderBottom: `1px solid ${colors.border}`,
            background: brandGradientCss,
            color: "#fff",
          }}
        >
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{ backgroundColor: "rgba(255,255,255,0.18)" }}
            aria-hidden="true"
          >
            <UserCog size={20} />
          </div>
          <div className="min-w-0">
            <h2
              id="profile-gate-title"
              className="text-lg font-bold leading-tight"
              data-testid="profile-completion-title"
            >
              Let's complete your profile
            </h2>
            <p className="text-xs opacity-90 mt-0.5">
              We need a few details so we can service your property.
            </p>
          </div>
        </div>

        {/* Body */}
        <form onSubmit={submit} className="flex-1 overflow-y-auto">
          <div className="px-5 py-4 space-y-3">
            {error ? (
              <div
                className="text-sm flex items-start gap-2 rounded-lg px-3 py-2"
                style={{
                  backgroundColor: "#FEF3C7",
                  color: "#92400E",
                  border: "1px solid #FDE68A",
                }}
                data-testid="profile-completion-error"
              >
                <AlertTriangle size={16} className="shrink-0 mt-0.5" />
                <div className="font-semibold">{error}</div>
              </div>
            ) : null}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <FieldInput
                label="First name"
                testid="profile-completion-first-name"
                value={form.first_name}
                onChange={setField("first_name")}
                autoComplete="given-name"
                required
              />
              <FieldInput
                label="Last name"
                testid="profile-completion-last-name"
                value={form.last_name}
                onChange={setField("last_name")}
                autoComplete="family-name"
                required
              />
            </div>

            <FieldInput
              label="Phone"
              testid="profile-completion-phone"
              value={form.phone}
              onChange={setField("phone")}
              type="tel"
              autoComplete="tel"
              placeholder="(555) 555-5555"
              required
            />

            <FieldInput
              label="Service address"
              testid="profile-completion-service-address"
              value={form.service_address}
              onChange={setField("service_address")}
              autoComplete="street-address"
              placeholder="123 Vistancia Blvd, Peoria, AZ"
              required
            />

            <div>
              <label
                htmlFor="profile-completion-preferred-contact"
                className="text-xs font-semibold block mb-1"
                style={{ color: colors.onSurface }}
              >
                Preferred contact
              </label>
              <select
                id="profile-completion-preferred-contact"
                value={form.preferred_contact}
                onChange={setField("preferred_contact")}
                className="w-full px-3 py-2 rounded-lg border text-sm"
                style={{
                  borderColor: colors.border,
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                }}
                data-testid="profile-completion-preferred-contact"
              >
                <option value="email">Email</option>
                <option value="sms">Text message</option>
                <option value="phone">Phone call</option>
              </select>
            </div>
          </div>

          {/* Footer */}
          <div
            className="px-5 py-4 flex items-center justify-between gap-3"
            style={{
              borderTop: `1px solid ${colors.border}`,
              backgroundColor: colors.surfaceSecondary,
            }}
          >
            <button
              type="button"
              onClick={onSkip}
              disabled={saving}
              className="inline-flex items-center gap-1.5 text-sm font-semibold"
              style={{ color: colors.muted }}
              data-testid="profile-completion-skip"
            >
              <Clock size={14} /> Skip for now
            </button>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-sm font-bold text-white disabled:opacity-50 disabled:cursor-not-allowed"
              style={{ background: brandGradientCss }}
              data-testid="profile-completion-submit"
            >
              <Check size={15} />
              {saving ? "Saving…" : "Save & continue"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


function FieldInput({ label, testid, required, ...inputProps }) {
  const id = `${testid}-input`;
  return (
    <div>
      <label
        htmlFor={id}
        className="text-xs font-semibold block mb-1"
        style={{ color: colors.onSurface }}
      >
        {label}
        {required ? (
          <span style={{ color: "#DC2626" }} aria-hidden="true"> *</span>
        ) : null}
      </label>
      <input
        id={id}
        className="w-full px-3 py-2 rounded-lg border text-sm"
        style={{
          borderColor: colors.border,
          backgroundColor: colors.surface,
          color: colors.onSurface,
        }}
        data-testid={testid}
        {...inputProps}
      />
    </div>
  );
}
