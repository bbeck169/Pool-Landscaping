/**
 * PublicInvoicePay — Feb 2026 · Public magic-link viewer landing page.
 *
 * Route: /pay/invoice/:id?token=<jwt>[&src=email|sms|link]
 *
 * Reads the JWT from the query string and hands it to <InvoiceView>
 * which fetches ``/api/invoices/{id}/full-magic``. Phase K47 forwards
 * the optional ``?src=`` query param so the resulting ``invoice_views``
 * record is stamped with the send channel that got the customer here.
 */
import React from "react";
import { useParams, useSearchParams } from "react-router-dom";
import InvoiceView from "@/components/InvoiceView";

export default function PublicInvoicePay() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const token = sp.get("token") || "";
  const rawSrc = (sp.get("src") || "").toLowerCase();
  // Feb-2026 · P0 Pay-link routing fix — the auto-login endpoint
  // now redirects legacy portal-invoice-pay tokens whose TTL
  // lapsed to ``/pay/invoice/{id}?msg=link_expired`` (instead of
  // ``/portal/login?reason=link_expired``, which was blocking the
  // customer with a login wall).  This branch renders the
  // friendly-invalid copy WITHOUT the Stripe form because a fresh
  // ``token=`` was not carried across the redirect.
  const linkExpiredMsg = sp.get("msg") === "link_expired";
  // Whitelist match — anything unknown collapses to "link" so we
  // don't accidentally forward attacker-controlled free text.
  const src = ["email", "sms", "portal", "link"].includes(rawSrc)
    ? rawSrc
    : "";

  if (linkExpiredMsg && !token) {
    return (
      <div
        style={{ minHeight: "100vh", padding: 24 }}
        data-testid="public-invoice-pay-link-expired"
      >
        <div
          style={{
            maxWidth: 720, margin: "40px auto", padding: 24,
            background: "#FEF3C7", border: "1px solid #FCD34D",
            borderRadius: 8, color: "#92400E",
          }}
        >
          <strong>This payment link is no longer valid.</strong>{" "}
          <span>
            To pay this invoice, please contact the business that sent it
            and ask them to resend the payment link.
          </span>
        </div>
      </div>
    );
  }

  if (!token) {
    return (
      <div
        style={{ minHeight: "100vh", padding: 24 }}
        data-testid="public-invoice-pay-missing-token"
      >
        <div
          style={{
            maxWidth: 720, margin: "40px auto", padding: 24,
            background: "#FEF2F2", border: "1px solid #FCA5A5",
            borderRadius: 8, color: "#991B1B",
          }}
        >
          <strong>Link invalid.</strong>{" "}
          <span>This payment link is missing its access token — please request a new one.</span>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", padding: 24, background: "#F3F4F6" }} data-testid="public-invoice-pay-root">
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        <InvoiceView invoiceId={id} magicToken={token} magicSrc={src} />
      </div>
    </div>
  );
}
