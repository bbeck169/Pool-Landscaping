/**
 * Phase K11 · Feb-2026 — Portal payment-method persistent banner.
 *
 * Renders on every /portal/* page when the customer has zero cards
 * OR a card expiring soon.  Banner uses a soft-blue tint (NOT amber
 * / red) so it's visually distinct from the K13 impersonation
 * banner.
 *
 * Contract:
 *   * Renders when ``prompt_kind !== "none"`` for the current
 *     customer — the endpoint returns the ORIGINAL evaluation kind
 *     even during an active snooze (via ``original_prompt_kind``),
 *     so the banner persists until the customer resolves the
 *     underlying missing / expiring card.
 *   * Hides on impersonation (K13 interlock).
 *   * Inline dismiss — clicking ✕ hides for the current page load
 *     only (component-local ``dismissed`` state; a full reload or
 *     route change brings it back).
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

export default function PaymentMethodPromptBanner() {
  const navigate = useNavigate();
  const [state, setState] = React.useState(null);
  const [dismissed, setDismissed] = React.useState(false);

  React.useEffect(() => {
    if (_isImpersonated()) return;
    api.get("/portal/payment-method/prompt-status")
      .then((r) => setState(r))
      .catch(() => { /* silent */ });
  }, []);

  if (!state) return null;
  if (dismissed) return null;
  // The endpoint's ``prompt_kind`` is "none" during an active snooze,
  // but ``original_prompt_kind`` still describes the underlying
  // problem — the banner uses that so it persists past the snooze.
  const effectiveKind = state.original_prompt_kind || state.prompt_kind;
  if (!effectiveKind || effectiveKind === "none") return null;

  const missing = effectiveKind === "missing";
  const firstCard = Array.isArray(state.expiring_cards)
    ? state.expiring_cards[0] : null;
  const label = missing
    ? "⚠ Add a payment method to keep your account active."
    : firstCard
      ? `⚠ Your ${firstCard.brand || "card"} ending ${firstCard.last4 || "••••"} expires soon.`
      : "⚠ A card on file is expiring soon.";
  const cta = missing ? "Add card" : "Update card";

  return (
    <div
      className="w-full px-4 py-2 flex items-center justify-between text-sm flex-shrink-0"
      style={{ backgroundColor: "#DBEAFE",
               color: "#1E3A8A",
               borderBottom: "1px solid #BFDBFE",
               minHeight: 40, maxHeight: 40 }}
      data-testid="k11-prompt-banner"
    >
      <div className="flex-1 min-w-0 truncate font-semibold">{label}</div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={() => navigate("/portal/payment-method")}
          className="text-xs font-bold px-3 py-1 rounded-md"
          style={{ backgroundColor: "#1D4ED8", color: "#fff" }}
          data-testid="k11-prompt-banner-cta"
        >
          {cta}
        </button>
        <button
          onClick={() => setDismissed(true)}
          aria-label="Dismiss"
          className="text-lg font-bold leading-none px-2 opacity-70 hover:opacity-100"
          style={{ color: "#1E3A8A" }}
          data-testid="k11-prompt-banner-dismiss"
        >
          ×
        </button>
      </div>
    </div>
  );
}
