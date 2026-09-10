/**
 * Phase 12 · Feb 2026 — Card-on-file warning banner + "Add card on
 * file" action (magic-link email flow).
 *
 * Feb-2026 · Pivot — the earlier inline SetupIntent modal was
 * reverted per user clarification: the flow stays as an email
 * round-trip, but the CTA in the email is a Stripe-hosted magic
 * link that skips the portal login entirely (see
 * ``routers/customers.py :: send_card_add_link`` +
 * ``services/add_card_links.build_add_card_link``). This banner
 * merely posts to that endpoint and shows a TRUTHFUL toast — the
 * previous "success toast even on silent no-op" bug is closed by
 * gating success on ``sent_email || sent_sms`` and surfacing the
 * exact server reason otherwise.
 *
 * Preserved: test-id ``card-on-file-send-link-btn``, admin
 * visibility gate, banner tone. Label copy renamed from "Send
 * add-card link" → "Add card on file".
 */
import React, { useState } from "react";
import { AlertTriangle, CreditCard } from "lucide-react";
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
      // Feb-2026 · Truthful toast — do NOT claim success unless at
      // least one channel actually left the pod. The server always
      // returns HTTP 200 for silent no-ops (missing email, missing
      // template, opted-out, deferred, gate-suppressed, missing
      // Resend key, upstream exception) — inspect the sent flags
      // instead of trusting the status code alone.
      const sentEmail = !!res?.sent_email;
      const sentSms = !!res?.sent_sms;
      if (sentEmail || sentSms) {
        const to = [
          sentEmail ? res?.email_recipient : null,
          sentSms   ? res?.sms_recipient   : null,
        ].filter(Boolean).join(" and ");
        onSent && onSent(
          to ? `Add-card link sent to ${to}` : "Add-card link sent",
        );
      } else {
        // Nothing was sent — surface the exact reason so ops knows
        // what to fix (missing email, missing template, blocked
        // domain, missing Resend key on this pod, etc.).
        const reason =
          res?.reason ||
          "Nothing was sent — check the customer's email/phone and template setup.";
        onError && onError(reason);
      }
    } catch (e) {
      // Backend returns 429 with a structured detail on rate-limit,
      // 4xx with a structured detail on all other user-actionable
      // errors (missing customer email, template not seeded, etc.).
      let msg;
      if (e?.detail?.code === "RATE_LIMITED") {
        msg = "Please wait a few minutes before sending another link.";
      } else if (typeof e?.detail === "string") {
        msg = e.detail;
      } else if (e?.detail?.message) {
        msg = e.detail.message;
      } else {
        msg = e?.message || "Failed to send add-card link";
      }
      onError && onError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      data-testid="card-on-file-warning-banner"
      className="rounded-2xl p-4 flex flex-wrap items-start gap-3"
      style={{
        backgroundColor: "#FEFCE8",
        border: "1px solid #FDE68A",
      }}
    >
      <div className="mt-0.5 shrink-0">
        <AlertTriangle size={20} color="#B45309" />
      </div>
      <div className="flex-1 min-w-[12rem]">
        <div className="text-sm font-semibold text-amber-900">
          Card on file required — none saved
        </div>
        <div className="text-xs text-amber-800 mt-1">
          Email the customer a secure link to enter their card. The link
          opens Stripe directly — no portal login required.
        </div>
      </div>
      <button
        onClick={send}
        disabled={busy}
        data-testid="card-on-file-send-link-btn"
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white whitespace-nowrap shrink-0 self-center"
        style={{
          backgroundColor: "#B45309",
          opacity: busy ? 0.7 : 1,
        }}
      >
        <CreditCard size={13} className="shrink-0" />
        <span>{busy ? "Sending…" : "Add card on file"}</span>
      </button>
    </div>
  );
}
