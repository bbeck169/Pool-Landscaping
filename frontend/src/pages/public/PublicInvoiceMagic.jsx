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
 */
import React from "react";
import { useParams } from "react-router-dom";
import InvoiceView from "@/components/InvoiceView";


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


export default function PublicInvoiceMagic() {
  const { token } = useParams();
  const payload = decodeJwtPayload(token || "");
  const invoiceId = payload?.invoice_id || "";

  if (!token || !invoiceId) {
    return (
      <div
        style={{ minHeight: "100vh", padding: 24 }}
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

  return (
    <div
      style={{ minHeight: "100vh", padding: 24, background: "#F3F4F6" }}
      data-testid="public-invoice-magic-root"
    >
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        <InvoiceView
          invoiceId={invoiceId}
          magicToken={token}
          magicSrc="link"
        />
      </div>
    </div>
  );
}
