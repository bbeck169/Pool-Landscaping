/**
 * Slice Q · <InvoiceView> — shared invoice viewer.
 *
 * Reads /api/invoices/{id}/full and renders the Vistancia-style
 * layout used by:
 *   • Admin invoice detail
 *   • Customer portal invoice detail
 *   • /invoices/{id}/print printable variant
 *
 * The component is presentational — auth/role gating is enforced by
 * the aggregator endpoint (customer 404 for other tenants, tech 403).
 */
import React, { useEffect, useState } from "react";
import { Printer, Download, Loader2, CreditCard } from "lucide-react";
import { toast } from "sonner";
import { api, TOKEN_KEY } from "@/api";
import { useAuth } from "@/auth";
import PaymentForm from "@/components/PaymentForm";
import InvoiceCreditApplied from "@/components/InvoiceCreditApplied";
// Feb-2026 · Task 5 · Charge on file — admin toolbar button + confirm.
import InvoiceChargeSavedCardDialog from "@/components/invoices/InvoiceChargeSavedCardDialog";
import "./InvoiceView.css";
import "@/components/documents/docMobile.css";
// Feb-2026 · Batch #4 · Logo ship — shared tenant logo helper so
// every doc surface renders the same asset the PDF pipeline uses.
import { getTenantLogoUrl, DEFAULT_LOGO_ALT } from "@/lib/tenantLogo";
// Feb-2026 · Universal mobile-responsive redesign — mobile top
// block + terms slot. Both are gated to mobile viewports via
// docMobile.css, so desktop layout is unchanged.
import DocMobileHeader from "@/components/documents/DocMobileHeader";
// Feb-2026 · Task 6 — Terms & Conditions block is excluded from
// invoices per product lock. Import removed.
// Feb-2026 · Desktop-unification — shared shell so invoice /
// estimate / quote all render the same skeleton at ≥ 768 px.
import DocDesktopShell from "@/components/documents/DocDesktopShell";

const BACKEND = process.env.REACT_APP_BACKEND_URL;

function fmtMoney(n) {
  const v = Number(n || 0);
  return v.toFixed(2);
}

export default function InvoiceView({ invoiceId, printable = false, magicToken = "", magicSrc = "", hideToolbarPayNow = false }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [payOpen, setPayOpen] = useState(false);
  const [reloadTick, _setReloadTick] = useState(0);
  // Task 5 · Feb-2026 — admin Charge-on-file surface.
  const { user } = useAuth() || {};
  const isAdminSurface = (
    !magicToken && !printable
    && user
    && ["super_admin", "admin", "manager"].includes(user.role)
  );
  const [savedCards, setSavedCards] = useState([]);
  const [chargeOpen, setChargeOpen] = useState(false);
  useEffect(() => {
    if (!invoiceId || !isAdminSurface) return;
    api.get(`/invoices/${invoiceId}/saved-cards`)
      .then((r) => setSavedCards((r && r.methods) || []))
      .catch(() => setSavedCards([]));
  }, [invoiceId, isAdminSurface, reloadTick]);

  useEffect(() => {
    if (!invoiceId) return;
    // Phase K47 · Feb-2026 — forward ``?src=email|sms|link`` to the
    // magic-link viewer so ``invoice_views`` records the send
    // channel that got the customer here. Ignored for the
    // authenticated ``/full`` path (portal source is inferred
    // server-side from the customer role).
    let url;
    if (magicToken) {
      const params = new URLSearchParams({ token: magicToken });
      if (magicSrc) params.set("src", magicSrc);
      url = `/invoices/${invoiceId}/full-magic?${params.toString()}`;
    } else {
      url = `/invoices/${invoiceId}/full`;
    }
    api.get(url)
      .then(setData)
      .catch((e) => setErr(e?.message || "Failed to load invoice."));
  }, [invoiceId, reloadTick, magicToken, magicSrc]);

  const openPdf = () => {
    const token = localStorage.getItem(TOKEN_KEY);
    const url = `${BACKEND}/api/invoices/${invoiceId}/pdf`;
    if (!token) { window.open(url, "_blank"); return; }
    // Send auth via fetch → blob → window for a clean tab-open.
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const objUrl = URL.createObjectURL(blob);
        window.open(objUrl, "_blank");
      })
      .catch(() => window.open(url, "_blank"));
  };

  if (err) {
    return (
      <div className="p-4 text-sm rounded"
        style={{ background: "#FEE2E2", color: "#991B1B" }}
        data-testid="invoice-view-error">
        {err}
      </div>
    );
  }
  if (!data) {
    return (
      <div className="p-8 text-center" data-testid="invoice-view-loading">
        <Loader2 className="animate-spin inline" size={24} />
      </div>
    );
  }

  const { company, bill_to, property_address, header, line_items, totals,
           notes, is_due_on_receipt, payment_status } = data;
  // Task SS Phase 2 · Feb 2026 — pluck the credit-applied summary
  // fields off ``data`` so the shared annotation can render on both
  // portal + admin invoice views. Fields optional; component
  // renders nothing when credits_applied_cents == 0.
  const creditSummary = {
    credits_applied_cents: data.credits_applied_cents
      || (totals && totals.credits_applied_cents) || 0,
    total: totals?.this_invoice ?? data.total,
    amount_paid: totals?.amount_paid ?? data.amount_paid,
    payment_status: payment_status,
    paid_method: data.paid_method || (totals && totals.paid_method),
  };
  const canPay = (payment_status || "").toLowerCase() !== "paid"
                  && (totals?.total_due || 0) > 0;
  const paySource = magicToken ? "portal" : "authenticated";

  return (
    <div className={`iv-shell ${printable ? "iv-printable" : ""}`}
          data-testid="invoice-view">
      {!printable ? (
        <DocMobileHeader
          docType="invoice"
          amount={totals?.total_due || 0}
          company={company || {}}
          docMeta={{
            number: header?.invoice_number,
            date: header?.due_date || header?.invoice_date,
          }}
          onPrimaryAction={canPay ? () => setPayOpen(true) : undefined}
          primaryActionDisabled={!canPay}
          hideActions={!canPay}
        />
      ) : null}
      <DocDesktopShell
        docType="invoice"
        testId="invoice-desktop-shell"
        printable={printable}
        toolbar={!printable ? (
          <>
            {canPay && !hideToolbarPayNow ? (
              /* Feb 2026 · Invoice Pay Now restyle — the top pay CTA
                 renders full-width red so it dominates the invoice
                 header/summary panel. ``flex-basis:100%`` forces the
                 other toolbar buttons (Print, Download PDF, admin
                 Charge-on-file) onto the next row inside the
                 flex-end toolbar. Uses design-system red tokens
                 (bg-red-600 / hover:bg-red-700) — no raw hex.
                 ``hideToolbarPayNow`` lets a parent surface (e.g.
                 PublicInvoiceMagic) render its own top-of-page CTA
                 and suppress the toolbar duplicate. */
              <div
                data-testid="invoice-pay-now-wrapper"
                style={{ flex: "1 1 100%", order: -1 }}
              >
                <button
                  type="button"
                  onClick={() => setPayOpen(true)}
                  className="iv-btn iv-btn-primary iv-pay-now-cta w-full bg-red-600 hover:bg-red-700 text-white justify-center"
                  data-testid="invoice-pay-now-btn"
                  style={{
                    width: "100%",
                    background: undefined,
                    borderColor: "transparent",
                    fontSize: 15, fontWeight: 700, padding: "12px 20px",
                    justifyContent: "center",
                  }}
                >
                  <CreditCard size={16} />
                  &nbsp;Pay ${fmtMoney(totals?.total_due || 0)}
                </button>
              </div>
            ) : null}
            {isAdminSurface && canPay && savedCards.length > 0 ? (
              <button
                type="button"
                onClick={() => setChargeOpen(true)}
                className="iv-btn"
                data-testid="invoice-charge-saved-card-btn"
                style={{ fontSize: 14, fontWeight: 600 }}
              >
                <CreditCard size={14} />
                &nbsp;Charge on file
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => window.print()}
              className="iv-btn"
              data-testid="invoice-print-btn"
            >
              <Printer size={14} /> Print
            </button>
            <button
              type="button"
              onClick={openPdf}
              className="iv-btn iv-btn-primary"
              data-testid="invoice-download-pdf-btn"
            >
              <Download size={14} /> Download PDF
            </button>
          </>
        ) : null}
        headerLeft={(
          <div data-testid="invoice-header-logo">
            <img
              src={getTenantLogoUrl(company)}
              alt={company.name || DEFAULT_LOGO_ALT}
              className="iv-brand-logo"
              data-testid="doc-header-logo"
              data-surface="invoice"
            />
            <div className="iv-company-name">{company.name}</div>
            {company.address ? (
              <div className="iv-company-addr">{company.address}</div>
            ) : null}
            {company.phone ? (
              <div>
                <a href={`tel:${company.phone}`} className="iv-link">
                  {company.phone}
                </a>
              </div>
            ) : null}
            {company.website ? (
              <div>
                <a href={`https://${String(company.website).replace(/^https?:\/\//, "")}`}
                    className="iv-link"
                    target="_blank" rel="noopener noreferrer">
                  {company.website}
                </a>
              </div>
            ) : null}
          </div>
        )}
        title="Invoice"
        headerMeta={(
          <table className="iv-kv" data-testid="invoice-header">
            <tbody>
              <tr>
                <td className="iv-kv-label">Invoice #</td>
                <td className="iv-kv-value" data-testid="invoice-number">
                  {header.invoice_number}
                </td>
              </tr>
              <tr>
                <td className="iv-kv-label">Invoice Date</td>
                <td className="iv-kv-value" data-testid="invoice-date">
                  {header.invoice_date}
                </td>
              </tr>
              <tr>
                <td className="iv-kv-label">Credit Available</td>
                <td className="iv-kv-value" data-testid="invoice-credit-available">
                  {fmtMoney(header.credit_available)}
                </td>
              </tr>
              <tr>
                <td className="iv-kv-label">Outstanding Balance</td>
                <td className="iv-kv-value" data-testid="invoice-outstanding-balance">
                  {fmtMoney(header.outstanding_balance)}
                </td>
              </tr>
            </tbody>
          </table>
        )}
        billTo={(
          <div data-testid="invoice-bill-to">
            <div className="iv-bill-name">{bill_to.name || "—"}</div>
            {bill_to.address ? (
              <div className="iv-bill-addr">{bill_to.address}</div>
            ) : null}
          </div>
        )}
        propertyAddress={property_address ? (
          <span data-testid="invoice-property-address">
            <b>Property Address:</b> {property_address}
          </span>
        ) : null}
        lines={(
          <table className="iv-lines" data-testid="invoice-line-items-table">
            <thead>
              <tr>
                <th>Description</th>
                <th className="iv-num">Cost/Rate</th>
                <th className="iv-num">Qty/Hr</th>
                <th className="iv-num">%</th>
                <th className="iv-num">Total</th>
              </tr>
            </thead>
            <tbody>
              {line_items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="iv-empty">No line items.</td>
                </tr>
              ) : line_items.map((li, i) => (
                <tr key={i} data-testid={`invoice-line-item-row-${i}`}>
                  <td>{li.description}</td>
                  <td className="iv-num">{fmtMoney(li.cost_rate)}</td>
                  <td className="iv-num">{li.qty_hr}</td>
                  <td className="iv-num">{fmtMoney(li.percent)}</td>
                  <td className="iv-num">{fmtMoney(li.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        notes={(
          <div data-testid="invoice-notes">
            <div className="iv-notes-title">Notes:</div>
            <div className="iv-notes-body">
              {notes.split(/(\+?[\d()\-\s]{10,})/g).map((seg, i) => {
                if (i % 2 === 1) {
                  return (
                    <a key={i} href={`tel:${seg.replace(/\s+/g, "")}`} className="iv-link">
                      {seg}
                    </a>
                  );
                }
                return <span key={i}>{seg}</span>;
              })}
            </div>
          </div>
        )}
        totals={(
          <>
            <table className="iv-totals">
              <tbody>
                <tr>
                  <td>Subtotal</td>
                  <td data-testid="invoice-total-subtotal">{fmtMoney(totals.subtotal)}</td>
                </tr>
                <tr>
                  <td>This Invoice</td>
                  <td data-testid="invoice-total-this-invoice">{fmtMoney(totals.this_invoice)}</td>
                </tr>
                <tr>
                  <td>Amount Paid</td>
                  <td data-testid="invoice-total-amount-paid">{fmtMoney(totals.amount_paid)}</td>
                </tr>
                <tr className="iv-total-due">
                  <td>Total Due</td>
                  <td data-testid="invoice-total-due">{fmtMoney(totals.total_due)}</td>
                </tr>
              </tbody>
            </table>
            <InvoiceCreditApplied invoice={creditSummary} />
          </>
        )}
        dueMarker={is_due_on_receipt ? (
          <div className="iv-due-marker" data-testid="invoice-due-on-receipt-marker">
            Due on Receipt
          </div>
        ) : null}
        termsSection={null /* Feb-2026 · Task 6 — Terms & Conditions
          block is excluded from invoices per product lock. Kept the
          slot prop so <DocDesktopShell> layout stays stable. */}
        stub={(
          <div className="iv-stub-cols" data-testid="invoice-payment-stub">
            <div className="iv-stub-left">
              <div className="iv-bill-name">{bill_to.name || "—"}</div>
              {bill_to.address ? <div>{bill_to.address}</div> : null}
              <div style={{ marginTop: 12 }}>
                <div className="iv-company-name">{company.name}</div>
                {company.address ? <div>{company.address}</div> : null}
                {company.phone ? <div>{company.phone}</div> : null}
                {company.website ? <div>{company.website}</div> : null}
              </div>
            </div>
            <table className="iv-stub-right">
              <tbody>
                <tr><td>Customer</td><td>{bill_to.name}</td></tr>
                <tr><td>Invoice #</td><td>{header.invoice_number}</td></tr>
                <tr><td>Invoice Date</td><td>{header.invoice_date}</td></tr>
                <tr><td>Outstanding Balance</td><td>{fmtMoney(header.outstanding_balance)}</td></tr>
                <tr><td>This Invoice</td><td>{fmtMoney(totals.this_invoice)}</td></tr>
                <tr><td>Total Due on Account</td><td>{fmtMoney(totals.total_due)}</td></tr>
                <tr><td>Amount Paid</td><td>{fmtMoney(totals.amount_paid)}</td></tr>
              </tbody>
            </table>
          </div>
        )}
      />
      {payOpen ? (
        <PaymentForm
          invoice={data}
          invoiceId={invoiceId}
          source={paySource}
          magicToken={magicToken}
          amount={totals?.total_due || 0}
          onClose={() => setPayOpen(false)}
        />
      ) : null}
      {chargeOpen ? (
        <InvoiceChargeSavedCardDialog
          invoiceId={invoiceId}
          savedCards={savedCards}
          amount={totals?.total_due || 0}
          onClose={() => setChargeOpen(false)}
          onSuccess={() => {
            setChargeOpen(false);
            toast.success("Payment succeeded — invoice will refresh shortly.");
            _setReloadTick((t) => t + 1);
          }}
        />
      ) : null}
      {/* Feb-2026 · P0 Bug B — sticky mobile pay bar. On phones the
          top toolbar scrolls off the viewport almost immediately;
          this keeps the primary CTA visible for the entire session.
          Only renders when there's an outstanding balance AND we're
          not in printable mode. CSS lives in ``InvoiceView.css``
          under ``.iv-mobile-pay-bar``. */}
      {!printable && canPay ? (
        <div className="iv-mobile-pay-bar" data-testid="invoice-mobile-pay-bar">
          <button
            type="button"
            onClick={() => setPayOpen(true)}
            className="iv-mobile-pay-btn"
            data-testid="invoice-mobile-pay-btn"
          >
            <CreditCard size={18} />
            &nbsp;Pay ${fmtMoney(totals?.total_due || 0)}
          </button>
        </div>
      ) : null}
    </div>
  );
}
