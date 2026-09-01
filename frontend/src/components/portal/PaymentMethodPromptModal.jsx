/**
 * Phase K11 · Feb-2026 — Portal payment-method prompt modal.
 *
 * Renders once per browser session on portal home when the customer
 * has zero cards on file OR at least one card expiring within 30
 * days.  Session marker: ``sessionStorage["k11_prompt_shown"]``.
 *
 * Impersonation interlock (K13): decodes the tab's impersonation
 * token from ``sessionStorage["portal_token"]`` and, when the ``act``
 * claim is present, renders nothing — admins auditing a portal
 * shouldn't be interrupted by customer-facing prompts.
 *
 * Snooze: primary "Add card / Update card" button navigates to
 * ``/portal/payment-method``.  Secondary "Remind me tomorrow" POSTs
 * a 24-hour snooze via the new endpoint and closes the modal.
 */
import React from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";

function _isImpersonated() {
  try {
    const t = window.sessionStorage.getItem("portal_token");
    if (!t) return false;
    const parts = t.split(".");
    if (parts.length < 2) return false;
    const b64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = b64 + "=".repeat((4 - b64.length % 4) % 4);
    const payload = JSON.parse(atob(padded));
    return Boolean(payload && payload.act);
  } catch { return false; }
}

export default function PaymentMethodPromptModal() {
  const navigate = useNavigate();
  const [state, setState] = React.useState(null);   // {prompt_kind, expiring_cards}
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    // Session marker — shown once per portal tab lifetime.
    if (window.sessionStorage.getItem("k11_prompt_shown") === "1") return;
    if (_isImpersonated()) return;                 // K13 interlock
    api.get("/portal/payment-method/prompt-status")
      .then((r) => {
        if (!r || r.prompt_kind === "none") return;
        setState(r);
        setOpen(true);
        window.sessionStorage.setItem("k11_prompt_shown", "1");
      })
      .catch(() => { /* silent — a stale prompt is a bad reason to
                          block the portal from loading */ });
  }, []);

  const snooze = async () => {
    if (!state) return;
    setBusy(true);
    try {
      await api.post("/portal/payment-method/prompt-snooze",
                      { kind: state.prompt_kind });
    } catch { /* silent */ }
    setBusy(false);
    setOpen(false);
  };

  const goToPaymentMethod = () => {
    setOpen(false);
    navigate("/portal/payment-method");
  };

  if (!open || !state) return null;
  const missing = state.prompt_kind === "missing";
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center"
      style={{ background: "rgba(15,23,42,0.55)" }}
      data-testid="k11-prompt-modal"
    >
      <div
        className="rounded-2xl shadow-2xl bg-white max-w-md w-[92%] p-6"
        role="dialog"
        aria-modal="true"
      >
        <div className="text-lg font-bold text-slate-900 mb-1"
             data-testid="k11-prompt-title">
          {missing ? "Add a payment method" : "Update your card"}
        </div>
        <div className="text-sm text-slate-600 mb-4">
          {missing
            ? "Add a card to your account so we can charge you for services."
            : "One or more cards on file are expiring soon:"}
        </div>
        {!missing && Array.isArray(state.expiring_cards) && (
          <ul className="text-sm text-slate-700 mb-4 space-y-1"
              data-testid="k11-prompt-expiring-list">
            {state.expiring_cards.map((c) => {
              const mm = String(c.exp_month || "").padStart(2, "0");
              const yy = String(c.exp_year || "");
              return (
                <li key={c.payment_method_id} className="flex justify-between">
                  <span>{c.brand} ending {c.last4}</span>
                  <span className="text-slate-500">
                    expires {mm}/{yy} ({c.days_until_expiry} day
                    {c.days_until_expiry === 1 ? "" : "s"})
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2 mt-4">
          <button
            onClick={snooze}
            disabled={busy}
            className="px-3 py-2 rounded-lg text-sm font-semibold text-slate-700 border border-slate-300 hover:bg-slate-50"
            data-testid="k11-prompt-snooze"
          >
            Remind me tomorrow
          </button>
          <button
            onClick={goToPaymentMethod}
            className="px-3 py-2 rounded-lg text-sm font-semibold text-white"
            style={{ backgroundColor: "#2563EB" }}
            data-testid="k11-prompt-cta"
          >
            {missing ? "Add card" : "Update card"}
          </button>
        </div>
      </div>
    </div>
  );
}
