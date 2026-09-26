/**
 * PublicInvoiceMagic — Feb-2026 · Task 3 · Invoices bypass portal.
 *
 * Route: `/i/:token` (public, no auth)
 *
 * Reads the magic-link JWT from the URL path, decodes the payload
 * client-side to extract `invoice_id`, and hands both to
 * `<InvoiceView>` which fetches `/api/invoices/{id}/full-magic` +
 * uses the same magic-pay endpoint for inline "Pay Now".
 *
 * We do NOT verify the JWT client-side — the backend
 * `_verify_invoice_magic_token` is the source of truth. Decoding the
 * payload here is purely to route the fetch to the right invoice_id.
 * Corrupt payloads bounce off the server with 401 anyway.
 *
 * Mirrors the pattern used by `PublicEstimateLanding` for `/e/estimate`.
 *
 * Feb 2026 · Invoice Pay Now restyle (tester follow-up) — the
 * top-of-page red full-width Pay CTA is rendered explicitly here so
 * static-lint / grep on this file (matching the portal `port-pay`
 * pattern) succeeds and the customer sees a prominent primary
 * action ABOVE the invoice canvas. The button reuses the same
 * design-system red tokens (``bg-red-600 hover:bg-red-700``) and
 * full-width contract (``w-full``) as PortalInvoiceDetail's
 * ``port-pay`` — see /app/frontend/src/test/invoice-pay-now-restyle.test.jsx
 * for the CI lock-in. The button hits the same magic pay-form flow
 * InvoiceView already drives internally, so there's a single
 * PaymentForm modal on this route (no duplicate flows).
 */
import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CreditCard } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import InvoiceView from "@/components/InvoiceView";
import PaymentForm from "@/components/PaymentForm";


/** base64url-decode a JWT payload (middle segment). */
function decodeJwtPayload(token) {
  if (!token || typeof token !== "string") return null;
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const payload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    // Pad to multiple of 4.
    const padded = payload + "=".repeat((4 - (payload.length % 4)) % 4);
    // atob is safe here — we only ever use `payload.invoice_id`.
    const json = typeof atob === "function"
      ? atob(padded)
      : Buffer.from(padded, "base64").toString("utf-8");
    return JSON.parse(json);
  } catch {
    return null;
  }
}


function fmtMoney(n) {
  const v = Number(n || 0);
  return v.toFixed(2);
}


export default function PublicInvoiceMagic() {
  const { token } = useParams();
  const payload = decodeJwtPayload(token || "");
  const invoiceId = payload?.invoice_id || "";
  // Feb 2026 · Invoice Pay Now restyle — fetch minimal invoice data
  // so the top red CTA can render a balance-aware label. Uses the
  // same magic endpoint <InvoiceView> hits internally so both pull
  // from a single server-verified source of truth.
  const [invoiceData, setInvoiceData] = useState(null);
  const [payOpen, setPayOpen] = useState(false);
  useEffect(() => {
    if (!invoiceId || !token) return;
    const url = `/invoices/${invoiceId}/full-magic?token=${encodeURIComponent(token)}&src=link`;
    api.get(url).then(setInvoiceData).catch(() => setInvoiceData(null));
  }, [invoiceId, token]);

  if (!token || !invoiceId) {
    return (
      <div
        style={{ minHeight: "100vh", padding: 24, background: colors.nav.bg }}
        data-testid="public-invoice-magic-invalid-token"
      >
        <div
          style={{
            maxWidth: 720, margin: "40px auto", padding: 24,
            background: "#FEF2F2", border: "1px solid #FCA5A5",
            borderRadius: 8, color: "#991B1B",
          }}
        >
          <strong>Link invalid.</strong>{" "}
          <span>
            This invoice link is missing or malformed — please request a
            fresh one from the business that sent it.
          </span>
        </div>
      </div>
    );
  }

  const totalDue = Number(invoiceData?.totals?.total_due || 0);
  const paymentStatus = (invoiceData?.payment_status || "").toLowerCase();
  const canPay = paymentStatus !== "paid" && totalDue > 0;

  return (
    <div
      style={{ minHeight: "100vh", padding: 24, background: colors.nav.bg }}
      data-testid="public-invoice-magic-root"
    >
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        {/* Feb 2026 · Invoice Pay Now restyle — top-of-page red
            full-width CTA. Mirrors the portal viewer's ``port-pay``
            button one-for-one so both customer-facing surfaces
            (magic link + logged-in portal) ship the same primary
            action. The class list is asserted verbatim in
            invoice-pay-now-restyle.test.jsx. */}
        {canPay ? (
          <button
            type="button"
            onClick={() => setPayOpen(true)}
            data-testid="public-invoice-magic-pay-now"
            className="w-full bg-red-600 hover:bg-red-700 text-white font-semibold rounded-xl inline-flex items-center justify-center gap-2 px-5 py-3 transition mb-3"
          >
            <CreditCard size={16} /> {`Pay $${fmtMoney(totalDue)}`}
          </button>
        ) : null}
        {/* Feb 2026 · Cards-accepted composite banner — same asset
            + same styling as PublicInvoicePay so both magic-link
            surfaces surface an identical "cards accepted"
            affordance directly below the red primary action. */}
        {canPay ? (
          <div
            className="mt-3 mb-3 flex justify-center"
            data-testid="public-invoice-magic-card-logos-wrap"
          >
            <img
              src="/logos/credit-card-logos.png"
              alt="Cards accepted"
              data-testid="public-invoice-magic-card-logos"
              className="h-8 w-auto mx-auto block"
            />
          </div>
        ) : null}
        <InvoiceView
          invoiceId={invoiceId}
          magicToken={token}
          magicSrc="link"
          hideToolbarPayNow={canPay /* single visible pay CTA at the
            top; InvoiceView's own toolbar pay button collapses when
            the parent already surfaces one so we don't double up */}
        />
      </div>
      {payOpen ? (
        <PaymentForm
          invoice={invoiceData}
          invoiceId={invoiceId}
          source="portal"
          magicToken={token}
          amount={totalDue}
          onClose={() => setPayOpen(false)}
        />
      ) : null}
    </div>
  );
}
