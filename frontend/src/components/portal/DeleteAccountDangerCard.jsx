/**
 * Feb-2026 · P11b — Delete Account danger card.
 *
 * App Store consumer-account guideline blocker item 3.  Renders a
 * red-bordered danger card at the bottom of the customer portal's
 * settings surface with a two-step confirmation:
 *
 *   1. Click "Delete My Account" → confirmation modal opens.
 *   2. User must type the phrase ``DELETE`` (case-sensitive) into a
 *      text input to enable the final destructive button.
 *   3. On confirm the component fires
 *      ``DELETE /api/customer-portal/account``, clears the local
 *      session, and redirects to ``/`` with a toast.
 *
 * Copy is deliberately unambiguous about what is preserved (service
 * history + tenant records) and what is scrubbed (name, email,
 * phone, address).  Matches the backend anonymize-not-delete
 * contract pinned by ``test_customer_account_deletion``.
 */
import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";


const REQUIRED_PHRASE = "DELETE";


export default function DeleteAccountDangerCard() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const canConfirm = phrase === REQUIRED_PHRASE && !busy;

  async function onConfirm() {
    if (!canConfirm) return;
    setBusy(true);
    setErr("");
    try {
      await api.delete("/customer-portal/account");
      // Clear local session immediately — the JWT is now dead server-side
      // (utils.get_current_user rejects deleted_at users on next request).
      try { logout && logout(); } catch (_e) { /* best effort */ }
      try { localStorage.clear(); } catch (_e) { /* best effort */ }
      toast.success("Your account has been deleted.");
      navigate("/");
    } catch (e) {
      setErr(e?.message || "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <div
      className="mt-8 rounded-2xl p-5"
      style={{ backgroundColor: colors.surface, border: "1px solid #DC2626" }}
      data-testid="portal-preferences-delete-account-card"
    >
      <div className="flex items-start gap-3">
        <AlertTriangle size={18} style={{ color: "#DC2626", marginTop: 2 }} />
        <div className="flex-1">
          <h3 className="text-sm font-bold" style={{ color: "#DC2626" }}>
            Delete my account
          </h3>
          <p className="text-sm mt-1" style={{ color: colors.onSurface }}>
            Deleting your account will anonymize your profile.  Your
            service history stays on file for the tenant, but your
            name, email, phone, and address will be permanently
            removed.  This cannot be undone.
          </p>
          {!open ? (
            <button
              onClick={() => setOpen(true)}
              // Phase K54 · Feb-2026 — token-compliant destructive.
              // #DC2626 base / #B91C1C hover / #EF4444 focus ring /
              // 0.55 disabled opacity per ``colors.destructive``.
              className="mt-3 inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white bg-[#DC2626] hover:bg-[#B91C1C] active:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4444] focus-visible:ring-offset-1 disabled:opacity-55 shadow-sm"
              data-testid="portal-preferences-delete-account-open-btn"
            >
              Delete My Account
            </button>
          ) : (
            <div
              className="mt-3 rounded-xl p-3"
              style={{ backgroundColor: "#FEF2F2", border: "1px solid #FCA5A5" }}
              data-testid="portal-preferences-delete-account-confirm"
            >
              <p className="text-sm" style={{ color: "#7F1D1D" }}>
                To confirm, type <strong>{REQUIRED_PHRASE}</strong> below.
              </p>
              <input
                type="text"
                value={phrase}
                onChange={(e) => setPhrase(e.target.value)}
                placeholder={REQUIRED_PHRASE}
                autoComplete="off"
                autoCapitalize="none"
                spellCheck={false}
                className="mt-2 w-full rounded-lg px-3 py-2 text-sm"
                style={{
                  border: "1px solid #FCA5A5",
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                }}
                data-testid="portal-preferences-delete-account-phrase-input"
              />
              {err ? (
                <div
                  className="text-sm mt-2"
                  style={{ color: colors.error }}
                  data-testid="portal-preferences-delete-account-error"
                >
                  {err}
                </div>
              ) : null}
              <div className="mt-3 flex items-center gap-2">
                <button
                  disabled={!canConfirm}
                  onClick={onConfirm}
                  // Phase K54 · Feb-2026 — token-compliant destructive.
                  // Disabled opacity moves from ``0.4`` → ``0.55`` per
                  // ``colors.destructive.disabledOpacity`` so the
                  // affordance matches every other destructive
                  // button in the app.
                  className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white bg-[#DC2626] hover:bg-[#B91C1C] active:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4444] focus-visible:ring-offset-1 disabled:opacity-55 shadow-sm"
                  data-testid="portal-preferences-delete-account-confirm-btn"
                >
                  {busy ? (
                    <>
                      <Loader2 size={14} className="animate-spin" />
                      Deleting…
                    </>
                  ) : (
                    "Delete forever"
                  )}
                </button>
                <button
                  onClick={() => {
                    setOpen(false);
                    setPhrase("");
                    setErr("");
                  }}
                  className="text-sm font-semibold"
                  style={{ color: colors.muted }}
                  data-testid="portal-preferences-delete-account-cancel-btn"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
