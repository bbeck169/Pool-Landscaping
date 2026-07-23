/**
 * Phase 12 · Feb 2026 — Card-on-file warning banner + "Send add-card
 * link" action. Rendered only when the customer effectively requires
 * a card AND has none saved.
 *
 * Posts to ``POST /api/customers/{cid}/send-card-add-link`` — the
 * backend rate-limits (1 per 5 min per customer) and returns the
 * recipient email + phone that were used.
 */
import React, { useState } from "react";
import { AlertTriangle, Send } from "lucide-react";
import { api } from "@/api";


export default function CardOnFileWarningBanner({ customer, onSent, onError }) {
  const [busy, setBusy] = useState(false);
  const effective = !!customer.effective_require_card_on_file;
  const hasCard = !!customer.has_card_on_file;
  if (!effective || hasCard) return null;

  const send = async () => {
    setBusy(true);
    try {
      const res = await api.post(
        `/customers/${customer.id}/send-card-add-link`,
        {},
      );
      const to = [res.email_recipient, res.sms_recipient]
        .filter(Boolean).join(" and ");
      onSent && onSent(
        to ? `Card add link sent to ${to}` : "Card add link sent",
      );
    } catch (e) {
      // Backend returns 429 with a structured detail on rate-limit.
      const msg = e?.detail?.code === "RATE_LIMITED"
        ? "Please wait a few minutes before sending another link."
        : (e?.message || "Failed to send link");
      onError && onError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="card-on-file-warning-banner"
      className="rounded-2xl p-4 mb-4 flex items-start gap-3"
      style={{
        backgroundColor: "#FEFCE8",
        border: "1px solid #FDE68A",
      }}
    >
      <div className="mt-0.5">
        <AlertTriangle size={20} color="#B45309" />
      </div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold text-amber-900">
          Card on file required — none saved
        </div>
        <div className="text-xs text-amber-800 mt-1">
          This customer requires a card on file but hasn't added one yet.
        </div>
      </div>
      <button
        onClick={send}
        disabled={busy}
        data-testid="card-on-file-send-link-btn"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
        style={{
          backgroundColor: "#B45309",
          opacity: busy ? 0.7 : 1,
        }}
      >
        <Send size={13} />
        {busy ? "Sending…" : "Send add-card link"}
      </button>
    </div>
  );
}
