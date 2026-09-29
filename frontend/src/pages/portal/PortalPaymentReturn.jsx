/**
 * Task QQ Phase 2 · Feb 2026 — post-checkout return page.
 *
 * Customer returns here from Lumino hosted checkout. Parses
 * `?session_id=...`, POSTs to `/api/payments/lumino/return`, renders
 * the appropriate outcome screen.
 */
import React, { useEffect, useState } from "react";
import { CheckCircle2, XCircle, AlertCircle, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "@/api";
import { portalColors as colors } from "@/theme";

export default function PortalPaymentReturn() {
  const [state, setState] = useState({ status: "loading" });

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const session_id = params.get("session_id") || "";
    if (!session_id) { setState({ status: "failed", reason: "missing session id" }); return; }
    api.post("/payments/lumino/return", { session_id })
      .then((r) => setState({ ...r, status: r.status || "unknown" }))
      .catch((e) => setState({ status: "failed", reason: e?.message || "network error" }));
  }, []);

  const wrapper = { maxWidth: 520, margin: "0 auto", padding: "3rem 1.5rem",
                       textAlign: "center", color: colors.onSurface };

  if (state.status === "loading") {
    return (
      <div style={wrapper} data-testid="payment-return-loading">
        <Loader2 size={40} className="animate-spin mx-auto" />
        <p className="mt-3 text-sm" style={{ color: colors.muted }}>Confirming payment…</p>
      </div>
    );
  }
  if (state.status === "paid") {
    return (
      <div style={wrapper} data-testid="payment-return-success">
        <CheckCircle2 size={48} color="#16A34A" className="mx-auto" />
        <h1 className="text-2xl font-bold mt-3">Payment received</h1>
        <p className="text-sm mt-2" style={{ color: colors.muted }}>
          Thanks — your invoice is now paid.
        </p>
        <Link to="/portal/invoices"
                className="inline-block mt-6 px-5 py-2 rounded-xl text-sm font-semibold text-white"
                style={{ backgroundColor: "#1D4ED8" }}
                data-testid="payment-return-back-to-invoices">
          Back to invoices
        </Link>
      </div>
    );
  }
  if (state.status === "cancelled") {
    return (
      <div style={wrapper} data-testid="payment-return-cancelled">
        <AlertCircle size={48} color="#F59E0B" className="mx-auto" />
        <h1 className="text-2xl font-bold mt-3">Payment cancelled</h1>
        <p className="text-sm mt-2" style={{ color: colors.muted }}>
          No charge was made. You can retry from the invoice at any time.
        </p>
        <Link to="/portal/invoices"
                className="inline-block mt-6 px-5 py-2 rounded-xl text-sm font-semibold"
                style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
                data-testid="payment-return-cancelled-back">
          Back to invoice
        </Link>
      </div>
    );
  }
  return (
    <div style={wrapper} data-testid="payment-return-failed">
      <XCircle size={48} color="#DC2626" className="mx-auto" />
      <h1 className="text-2xl font-bold mt-3">Payment didn’t go through</h1>
      <p className="text-sm mt-2" style={{ color: colors.muted }}>
        {state.reason || "The processor couldn’t complete this payment. Please try again or use a different card."}
      </p>
      <Link to="/portal/invoices"
              className="inline-block mt-6 px-5 py-2 rounded-xl text-sm font-semibold text-white"
              style={{ backgroundColor: "#1D4ED8" }}
              data-testid="payment-return-retry">
        Retry payment
      </Link>
    </div>
  );
}
