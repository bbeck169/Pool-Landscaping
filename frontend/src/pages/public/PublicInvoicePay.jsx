/**
 * PublicInvoicePay — Feb 2026 · Public magic-link viewer landing page.
 *
 * Route: /pay/invoice/:id?token=<jwt>[&src=email|sms|link]
 *
 * Reads the JWT from the query string and hands it to <InvoiceView>
 * which fetches ``/api/invoices/{id}/full-magic``. Phase K47 forwards
 * the optional ``?src=`` query param so the resulting ``invoice_views``
 * record is stamped with the send channel that got the customer here.
 *
 * Feb-2026 · Pay Now CTA restyle — this page now renders a top-of-page
 * red full-width "Pay Now - $X" CTA plus a Visa / Mastercard / Amex /
 * Discover icon row directly below, mirroring the sibling
 * ``PublicInvoiceMagic`` surface. The toolbar duplicate inside
 * ``<InvoiceView>`` is suppressed via ``hideToolbarPayNow`` so
 * customers see a single, prominent primary action. No payment handler
 * or Stripe integration was touched — the button hits the same magic
 * pay-form flow ``InvoiceView`` already drives internally, and
 * ``PaymentForm`` is the same modal both surfaces use.
 */
import React, { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { CreditCard } from "lucide-react";
import { api } from "@/api";
import InvoiceView from "@/components/InvoiceView";
import PaymentForm from "@/components/PaymentForm";

/** Match the ``fmtMoney`` helper used by ``InvoiceView`` and
 * ``PublicInvoiceMagic`` — plain 2-decimal string, no locale coercion. */
function fmtMoney(n) {
  const v = Number(n || 0);
  return v.toFixed(2);
}

/** Inline monochrome text-mark for a card network. Uses ``currentColor``
 * so parent styling drives fill. NOT a trademarked brand logo — this is
 * a bordered wordmark chip in the "cards accepted" affordance style. */
function CardNetworkMark({ label, letters, testId, width = 40 }) {
  return (
    <span
      role="img"
      aria-label={label}
      data-testid={testId}
      className="inline-flex items-center justify-center h-8 text-slate-600"
      style={{ minWidth: width }}
    >
      <svg
        width={width}
        height="24"
        viewBox={`0 0 ${width} 24`}
        xmlns="http://www.w3.org/2000/svg"
        aria-hidden="true"
        focusable="false"
      >
        <rect
          x="0.75"
          y="0.75"
          width={width - 1.5}
          height="22.5"
          rx="4"
          ry="4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1"
        />
        <text
          x={width / 2}
          y="16"
          textAnchor="middle"
          fontFamily="ui-sans-serif, system-ui, sans-serif"
          fontSize="10"
          fontWeight="700"
          letterSpacing="0.5"
          fill="currentColor"
        >
          {letters}
        </text>
      </svg>
    </span>
  );
}

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

  // Fetch minimal invoice data so the top red CTA can render a
  // balance-aware label. Uses the same magic endpoint <InvoiceView>
  // hits internally so both pull from a single server-verified
  // source of truth — no duplicate flows.
  const [invoiceData, setInvoiceData] = useState(null);
  const [payOpen, setPayOpen] = useState(false);
  useEffect(() => {
    if (!id || !token) return;
    const qs = src
      ? `token=${encodeURIComponent(token)}&src=${encodeURIComponent(src)}`
      : `token=${encodeURIComponent(token)}`;
    api.get(`/invoices/${id}/full-magic?${qs}`)
      .then(setInvoiceData)
      .catch(() => setInvoiceData(null));
  }, [id, token, src]);

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

  const totalDue = Number(invoiceData?.totals?.total_due || 0);
  const paymentStatus = (invoiceData?.payment_status || "").toLowerCase();
  const canPay = paymentStatus !== "paid" && totalDue > 0;
  const amountStr = fmtMoney(totalDue);

  return (
    <div style={{ minHeight: "100vh", padding: 24, background: "#F3F4F6" }} data-testid="public-invoice-pay-root">
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        {/* Feb 2026 · Pay Now CTA restyle — top-of-page red
            full-width CTA + card-network icon row. Class list is
            asserted in ``public-invoice-pay-button.test.jsx``.
            ``hideToolbarPayNow`` prevents InvoiceView's own toolbar
            pay button from duplicating this one. */}
        {canPay ? (
          <div data-testid="public-invoice-pay-cta-block">
            <button
              type="button"
              onClick={() => setPayOpen(true)}
              data-testid="public-invoice-pay-now"
              className="w-full bg-red-600 hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 text-white font-semibold rounded-xl inline-flex items-center justify-center gap-2 px-5 py-3 transition"
            >
              <CreditCard size={16} aria-hidden="true" />
              {/* Responsive label: full label on ≥sm, compact on
                  narrow screens so the pill doesn't overflow. */}
              <span className="sm:hidden" data-testid="public-invoice-pay-now-label-short">
                Pay Now
              </span>
              <span className="hidden sm:inline" data-testid="public-invoice-pay-now-label-full">
                {`Pay Now - $${amountStr}`}
              </span>
            </button>
            <div
              className="mt-3 flex flex-row items-center justify-center gap-4"
              data-testid="public-invoice-pay-card-icons"
              aria-label="Cards accepted"
            >
              <CardNetworkMark label="Visa"             letters="VISA"  testId="pay-icon-visa" />
              <CardNetworkMark label="Mastercard"       letters="MC"    testId="pay-icon-mastercard" />
              <CardNetworkMark label="American Express" letters="AMEX"  testId="pay-icon-amex" />
              <CardNetworkMark label="Discover"         letters="DISC"  testId="pay-icon-discover" />
            </div>
          </div>
        ) : null}
        <div style={{ marginTop: canPay ? 20 : 0 }}>
          <InvoiceView
            invoiceId={id}
            magicToken={token}
            magicSrc={src}
            hideToolbarPayNow={canPay /* single visible pay CTA at
              the top; InvoiceView's toolbar pay button collapses
              when the parent already surfaces one. */}
          />
        </div>
      </div>
      {payOpen ? (
        <PaymentForm
          invoice={invoiceData}
          invoiceId={id}
          source="portal"
          magicToken={token}
          amount={totalDue}
          onClose={() => setPayOpen(false)}
        />
      ) : null}
    </div>
  );
}
