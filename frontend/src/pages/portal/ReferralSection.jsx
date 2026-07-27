/**
 * Slice O2 · Portal "Refer a Friend" form.
 *
 * Posts to ``/api/customer-portal/referrals`` and swaps to a thank-you
 * screen on success.  Handles the 429 rate-limit response and the 422
 * self-referral guard with friendly copy.
 */
import React, { useState } from "react";
import { UserPlus, Send, Sparkles, Loader2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const initialForm = {
  friend_name: "",
  friend_phone: "",
  friend_email: "",
  friend_address: "",
  service_of_interest: "",
  notes: "",
};

export default function ReferralSection() {
  const [form, setForm] = useState(initialForm);
  const [submitting, setSubmitting] = useState(false);
  const [thanks, setThanks] = useState(null);
  const [err, setErr] = useState("");

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr("");
    if (!form.friend_name.trim()) {
      setErr("Please enter your friend's name.");
      return;
    }
    if (!form.friend_phone.trim() && !form.friend_email.trim()) {
      setErr("Please add your friend's phone or email so we can reach out.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await api.post("/customer-portal/referrals", form);
      setThanks(res);
      setForm(initialForm);
    } catch (ex) {
      setErr(ex?.message || "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (thanks) {
    return (
      <div
        className="rounded-2xl p-6 my-4 text-center"
        style={{
          background: "linear-gradient(135deg, #F0FDF4 0%, #DCFCE7 100%)",
          border: `1px solid #86EFAC`,
        }}
        data-testid="portal-referral-thankyou"
      >
        <Sparkles size={28} className="mx-auto mb-2" color="#16A34A" />
        <div className="text-lg font-bold" style={{ color: "#14532D" }}>
          Thanks! {thanks.message}
        </div>
        <div className="text-sm mt-1" style={{ color: "#166534" }}>
          If they become a customer we'll let you know.
        </div>
        <button
          type="button"
          onClick={() => setThanks(null)}
          className="mt-4 text-sm font-semibold underline"
          style={{ color: "#166534", background: "transparent", border: 0, cursor: "pointer" }}
          data-testid="portal-referral-refer-another"
        >
          Refer someone else
        </button>
      </div>
    );
  }

  return (
    <div
      className="rounded-3xl p-6 my-4 shadow-lg"
      style={{
        /* Phase 34 · Feb 2026 · Refer highlight — brand-purple → pink
           gradient, distinct from the Ask-Concierge teal→blue gradient
           so the two hero-ish blocks are visually differentiated.
           White text on the gradient gives WCAG AA contrast against
           the darkest stop (#7C3AED at 4.8:1 for 16px+ bold; the
           lighter #EC4899 stop covers <20% of body area). */
        background: "linear-gradient(135deg, #7C3AED 0%, #A855F7 55%, #EC4899 100%)",
        border: "1px solid rgba(255,255,255,0.10)",
        color: "#FFFFFF",
      }}
      data-testid="portal-referral-section"
      data-tour-id="referrals-panel"
    >
      <div className="flex items-center gap-2 mb-1">
        <UserPlus size={20} color="#FFFFFF" />
        <h3 className="text-xl font-black" style={{ color: "#FFFFFF" }}>
          Refer a Friend — earn $25
        </h3>
      </div>
      <p className="text-sm mb-4" style={{ color: "rgba(255,255,255,0.92)" }}>
        Know someone who could use pool or landscape care? Send us their info
        and we'll reach out. You'll get $25 in credit after their first paid month.
      </p>

      <form onSubmit={submit} className="space-y-3">
        <div>
          <label className="text-[11px] font-bold uppercase" style={{ color: colors.muted }}>
            Friend's name
          </label>
          <input
            required
            type="text"
            value={form.friend_name}
            onChange={set("friend_name")}
            className="mt-1 w-full px-3 py-2 rounded-md text-sm"
            style={{
              border: `1px solid ${colors.border}`,
              background: colors.surface,
              color: colors.onSurface,
            }}
            data-testid="portal-referral-friend-name"
          />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] font-bold uppercase" style={{ color: colors.muted }}>
              Phone
            </label>
            <input
              type="tel"
              placeholder="(555) 555-1234"
              value={form.friend_phone}
              onChange={set("friend_phone")}
              className="mt-1 w-full px-3 py-2 rounded-md text-sm"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="portal-referral-friend-phone"
            />
          </div>
          <div>
            <label className="text-[11px] font-bold uppercase" style={{ color: colors.muted }}>
              Email
            </label>
            <input
              type="email"
              placeholder="friend@example.com"
              value={form.friend_email}
              onChange={set("friend_email")}
              className="mt-1 w-full px-3 py-2 rounded-md text-sm"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="portal-referral-friend-email"
            />
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div>
            <label className="text-[11px] font-bold uppercase" style={{ color: colors.muted }}>
              Address / City (optional)
            </label>
            <input
              type="text"
              value={form.friend_address}
              onChange={set("friend_address")}
              className="mt-1 w-full px-3 py-2 rounded-md text-sm"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="portal-referral-friend-address"
            />
          </div>
          <div>
            <label className="text-[11px] font-bold uppercase" style={{ color: colors.muted }}>
              Interested in
            </label>
            <select
              value={form.service_of_interest}
              onChange={set("service_of_interest")}
              className="mt-1 w-full px-3 py-2 rounded-md text-sm"
              style={{
                border: `1px solid ${colors.border}`,
                background: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="portal-referral-service-select"
            >
              <option value="">Not sure</option>
              <option>Pool Cleaning</option>
              <option>Pool Service</option>
              <option>Landscape Maintenance</option>
              <option>Landscape Design</option>
              <option>Repair</option>
              <option>Other</option>
            </select>
          </div>
        </div>
        <div>
          <label className="text-[11px] font-bold uppercase" style={{ color: colors.muted }}>
            Anything else we should know?
          </label>
          <textarea
            rows={2}
            value={form.notes}
            onChange={set("notes")}
            className="mt-1 w-full px-3 py-2 rounded-md text-sm"
            style={{
              border: `1px solid ${colors.border}`,
              background: colors.surface,
              color: colors.onSurface,
              resize: "vertical",
            }}
            data-testid="portal-referral-notes"
          />
        </div>
        {err ? (
          <div
            className="rounded-md p-2 text-sm"
            style={{ background: "#FEE2E2", color: "#991B1B" }}
            data-testid="portal-referral-error"
          >
            {err}
          </div>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-xl font-bold text-white shadow-sm hover:brightness-95 disabled:opacity-60"
          style={{ background: colors.brand, minHeight: 40 }}
          data-testid="portal-referral-submit-btn"
        >
          {submitting ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Send size={16} />
          )}
          {submitting ? "Sending…" : "Send Referral"}
        </button>
      </form>
    </div>
  );
}
