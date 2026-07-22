/**
 * Phase 4B · Public magic-link invoice payer.
 *
 * Route: /pay/invoice/:id?token=<magic>
 *
 * Renders <InvoiceView> pointed at the ``/full-magic`` endpoint and
 * exposes the same "Pay Now" flow used by the authenticated portal.
 * No login required — the magic token is the sole credential.
 */
import React from "react";
import { useParams, useSearchParams } from "react-router-dom";
import InvoiceView from "@/components/InvoiceView";

export default function PublicInvoicePay() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const token = sp.get("token") || "";
  if (!id || !token) {
    return (
      <div style={{ maxWidth: 480, margin: "10vh auto", padding: 24,
                    borderRadius: 12, background: "#FEE2E2",
                    color: "#991B1B", fontSize: 14 }}
            data-testid="public-invoice-pay-invalid">
        This invoice link is invalid or has expired. Please contact us for
        a new payment link.
      </div>
    );
  }
  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "24px 16px" }}
          data-testid="public-invoice-pay-shell">
      <InvoiceView invoiceId={id} magicToken={token} />
    </div>
  );
}
