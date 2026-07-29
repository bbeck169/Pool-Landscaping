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
import { api, TOKEN_KEY } from "@/api";
import PaymentForm from "@/components/PaymentForm";
import InvoiceCreditApplied from "@/components/InvoiceCreditApplied";
import "./InvoiceView.css";

const BACKEND = process.env.REACT_APP_BACKEND_URL;

function fmtMoney(n) {
  const v = Number(n || 0);
  return v.toFixed(2);
}

export default function InvoiceView({ invoiceId, printable = false, magicToken = "" }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [payOpen, setPayOpen] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    if (!invoiceId) return;
    const url = magicToken
      ? `/invoices/${invoiceId}/full-magic?token=${encodeURIComponent(magicToken)}`
      : `/invoices/${invoiceId}/full`;
    api.get(url)
      .then(setData)
      .catch((e) => setErr(e?.message || "Failed to load invoice."));
  }, [invoiceId, reloadTick, magicToken]);

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
        <div className="iv-toolbar" data-testid="invoice-toolbar">
          {canPay ? (
            <button
              type="button"
              onClick={() => setPayOpen(true)}
              className="iv-btn iv-btn-primary"
              data-testid="invoice-pay-now-btn"
              style={{ background: "#0F766E", borderColor: "#0F766E" }}
            >
              <CreditCard size={14} /> Pay Now
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
        </div>
      ) : null}

      <div className="iv-doc">
        {/* ── Header ─────────────────────────────────────── */}
        <div className="iv-header" data-testid="invoice-header">
          <div className="iv-header-left" data-testid="invoice-header-logo">
            {/* Phase 34 · Feb 2026 — brand logo header. Falls back to
                the shared /logo-full.png bundled with the frontend so
                every invoice preview matches PDFs, estimates + emails. */}
            <img
              src={company.logo_url || "/logo-full.png"}
              alt={company.name || "Pool & Landscaping of Vistancia"}
              className="iv-brand-logo"
              data-testid="invoice-brand-logo"
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
          <div className="iv-header-right">
            <div className="iv-title">Invoice</div>
            <table className="iv-kv">
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
          </div>
        </div>

        <div className="iv-divider" />

        {/* ── Bill To ────────────────────────────────────── */}
        <div className="iv-bill-to" data-testid="invoice-bill-to">
          <div className="iv-bill-name">{bill_to.name || "—"}</div>
          {bill_to.address ? (
            <div className="iv-bill-addr">{bill_to.address}</div>
          ) : null}
        </div>

        {property_address ? (
          <div className="iv-prop-addr" data-testid="invoice-property-address">
            <b>Property Address:</b> {property_address}
          </div>
        ) : null}

        {/* ── Line items ─────────────────────────────────── */}
        <div className="iv-lines-wrap">
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
        </div>

        {/* ── Totals ─────────────────────────────────────── */}
        <div className="iv-totals-row">
          <div className="iv-notes" data-testid="invoice-notes">
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
        </div>

        {is_due_on_receipt ? (
          <div className="iv-due-marker" data-testid="invoice-due-on-receipt-marker">
            Due on Receipt
          </div>
        ) : null}

        {/* ── Payment stub ───────────────────────────────── */}
        <div className="iv-stub-divider" />
        <div className="iv-stub" data-testid="invoice-payment-stub">
          <div className="iv-stub-title">PAYMENT STUB</div>
          <div className="iv-stub-cols">
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
        </div>
      </div>
      {payOpen ? (
        <PaymentForm
          invoice={data}
          invoiceId={invoiceId}
          source={paySource}
          magicToken={magicToken}
          onClose={() => setPayOpen(false)}
        />
      ) : null}
    </div>
  );
}
