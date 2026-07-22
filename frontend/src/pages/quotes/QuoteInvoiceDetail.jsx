import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Send,
  Link2,
  Check,
  X,
  DollarSign,
  Repeat2,
  CreditCard,
  MessageSquare,
  Trash2,
  PenTool,
  CheckCircle2,
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
import { PayNowButton, StripeCheckoutReturn } from '@/components/stripe/StripePayments';
// Phase 5A hot-fix · Feb 2026 — Pay Now on the invoice detail page now
// uses the Phase 4B <PaymentForm> (Card + ACH + wallets via Stripe
// PaymentElement). The legacy hosted-checkout <PayNowButton> above is
// kept only for the Portal / Magic-Link viewer where it still ships,
// but the authenticated invoice screen no longer calls it. The
// legacy path returned ``stripe_error`` whenever the Phase-53 checkout
// route hit a Stripe SDK exception, which surfaced to the user as
// "Stripe not configured".
import PaymentForm from "@/components/PaymentForm";
import {
  PageHeader,
  Button,
  Skeleton,
  StatusPill,
  Modal,
  TextInput,
  Toast,
  Chip,
  EmptyState,
} from "@/components/ui-kit";

/** Reused for both /quotes/:id and /invoices/:id — same collection. */
export default function QuoteInvoiceDetail({ docType = "quote" }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [customer, setCustomer] = useState(null);
  const [pmethod, setPmethod] = useState(null);
  const [handles, setHandles] = useState(null);
  const [toast, setToast] = useState(null);
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [smsOpen, setSmsOpen] = useState(false);
  const [payOpen, setPayOpen] = useState(false);
  const [convertOpen, setConvertOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Phase 5A hot-fix · Feb 2026 — Phase 4B PaymentForm mount toggle.
  const [payNowOpen, setPayNowOpen] = useState(false);
  const [termsEditOpen, setTermsEditOpen] = useState(false);
  const [termsDraft, setTermsDraft] = useState("");
  const [termsDefaultForDoc, setTermsDefaultForDoc] = useState("");
  const [signInfo, setSignInfo] = useState(null);
  const [signOpen, setSignOpen] = useState(false);
  const [signEmail, setSignEmail] = useState("");
  const [signMsg, setSignMsg] = useState("");

  const load = async () => {
    try {
      const q = await api.get(`/quotes/${id}`);
      setDoc(q);
      if (q.customer_id) {
        api.get(`/customers/${q.customer_id}`).then((c) => { setCustomer(c); setSignEmail(c?.email || ""); }).catch(() => {});
        api.get(`/payments/method?customer_id=${q.customer_id}`).then(setPmethod).catch(() => setPmethod(null));
      }
      api.get("/settings/payment-handles").then(setHandles).catch(() => {});
      api.get("/settings/terms").then((r) => {
        const def = q.doc_type === "invoice" ? r.default_invoice_terms : r.default_quote_terms;
        setTermsDefaultForDoc(def || "");
      }).catch(() => {});
      // Signature status (silently ignore errors — endpoint returns {signed:false} normally)
      api.get(`/quotes/${id}/signature`).then(setSignInfo).catch(() => setSignInfo(null));
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line
  }, [id]);

  if (!doc) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Skeleton style={{ height: 200 }} />
      </div>
    );
  }

  const isInvoice = doc.doc_type === "invoice";
  const balance = Math.max(0, Number(doc.total || 0) - Number(doc.amount_paid || 0));
  const canConvertToJob = doc.decision === "approved" || doc.status === "approved";

  const setStatus = async (status) => {
    try {
      await api.put(`/quotes/${id}/status`, { status });
      setToast({ tone: "success", message: `Marked ${status}` });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const decision = async (d) => {
    try {
      await api.post(`/quotes/${id}/decision?decision=${d}`);
      setToast({ tone: "success", message: `Recorded ${d}` });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const generateLink = async () => {
    try {
      const r = await api.post(`/payments/admin/generate-link/${id}`);
      setLinkUrl(r.payment_url);
      setLinkOpen(true);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const sendReminder = async () => {
    try {
      await api.post(`/quotes/${id}/send-reminder`);
      setToast({ tone: "success", message: "Reminder sent (or logged if email not configured)" });
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const chargeOnFile = async () => {
    try {
      const r = await api.post(`/payments/charge-on-file/${id}`);
      setToast({ tone: "success", message: `Charged ${money(r.amount ?? doc.total)}` });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const del = async () => {
    // Backend has no /quotes/{id} DELETE — soft-cancel via status.
    await setStatus("cancelled");
    setConfirmDelete(false);
    setTimeout(() => navigate(isInvoice ? "/invoices" : "/quotes"), 300);
  };

  const requestSignature = async () => {
    try {
      const r = await api.post(`/quotes/${id}/request-signature`, {
        signer_email: signEmail || undefined,
        message: signMsg || undefined,
      });
      setSignOpen(false);
      setToast({
        tone: "success",
        message: r.emailed ? "Signature request emailed" : `Sign link: ${r.url}`,
      });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid={`${isInvoice ? "invoice" : "quote"}-detail`}>
      <button
        onClick={() => navigate(isInvoice ? "/invoices" : "/quotes")}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> All {isInvoice ? "invoices" : "quotes"}
      </button>

      <StripeCheckoutReturn onPaid={() => load()} />

      <div
        className="rounded-2xl p-6 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <StatusPill status={doc.decision || doc.status} />
              {isInvoice ? (
                <Chip
                  label={doc.payment_status || "unpaid"}
                  tone={doc.payment_status === "paid" ? "success" : doc.payment_status === "partial" ? "warning" : "danger"}
                />
              ) : null}
              {signInfo?.signed ? (
                <Chip
                  label={`Signed by ${signInfo.signer_name}`}
                  tone="success"
                  testid="signed-chip"
                />
              ) : null}
            </div>
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
              {doc.title}
            </h1>
            <p className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
              <span
                className="font-semibold cursor-pointer hover:underline"
                onClick={() => customer && navigate(`/customers/${customer.id}`)}
              >
                {doc.customer_name}
              </span>
              {doc.due_date ? <> · Due {doc.due_date}</> : null}
            </p>
          </div>
          <div className="text-right">
            <div className="text-3xl font-bold" style={{ color: colors.brand }}>{money(doc.total)}</div>
            {isInvoice ? (
              <div className="text-xs mt-1" style={{ color: colors.muted }}>
                Paid {money(doc.amount_paid || 0)} · Balance {money(balance)}
              </div>
            ) : null}
          </div>
        </div>

        {/* Action bar */}
        <div className="flex flex-wrap gap-2 mt-5">
          {!isInvoice ? (
            <>
              {doc.status === "draft" ? (
                <>
                  <Button onClick={() => setStatus("sent")} testid="qd-send"><Send size={14} /> Send</Button>
                  <Button variant="ghost" onClick={() => decision("approved")}><Check size={14} /> Mark approved</Button>
                  <Button variant="ghost" onClick={() => decision("declined")}><X size={14} /> Mark declined</Button>
                </>
              ) : (
                <>
                  <Button variant="ghost" onClick={sendReminder}><Send size={14} /> Send reminder</Button>
                  <Button variant="ghost" onClick={generateLink} testid="qd-gen-link"><Link2 size={14} /> Payment link</Button>
                </>
              )}
              {canConvertToJob ? (
                <Button onClick={() => setConvertOpen(true)} testid="qd-convert-job">
                  <Repeat2 size={14} /> Convert to job
                </Button>
              ) : null}
              {!signInfo?.signed ? (
                <Button variant="ghost" onClick={() => setSignOpen(true)} testid="qd-request-sig">
                  <PenTool size={14} /> Send for signature
                </Button>
              ) : (
                <Button variant="ghost"
                        onClick={() => window.open(`${process.env.REACT_APP_BACKEND_URL}/api/quotes/${id}/signed-pdf`, "_blank")}
                        testid="qd-view-signed">
                  <CheckCircle2 size={14} /> View signed PDF
                </Button>
              )}
            </>
          ) : (
            <>
              <Button variant="ghost" onClick={sendReminder} testid="id-send-email"><Send size={14} /> Email invoice</Button>
              <Button variant="ghost" onClick={() => setSmsOpen(true)} testid="id-send-sms"><MessageSquare size={14} /> Text invoice</Button>
              <Button variant="ghost" onClick={generateLink} testid="id-gen-link"><Link2 size={14} /> Payment link</Button>
              {pmethod?.brand ? (
                <Button onClick={chargeOnFile} testid="id-charge-on-file">
                  <CreditCard size={14} /> Charge {pmethod.brand} · {pmethod.last4}
                </Button>
              ) : null}
              <Button variant="ghost" onClick={() => setPayOpen(true)} testid="id-record-payment">
                <DollarSign size={14} /> Record payment
              </Button>
              {balance > 0 ? (
                <Button onClick={() => setPayNowOpen(true)} testid="id-pay-now-phase4b">
                  <CreditCard size={14} /> Pay {`$${balance.toFixed(2)}`}
                </Button>
              ) : null}
            </>
          )}
          <Button variant="danger" onClick={() => setConfirmDelete(true)} testid="qd-cancel">
            <Trash2 size={14} /> Cancel
          </Button>
        </div>
      </div>

      {/* Line items */}
      <div
        className="rounded-2xl p-6 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <h2 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>Line items</h2>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
              <th className="text-left px-2 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Description</th>
              <th className="text-right px-2 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Qty</th>
              <th className="text-right px-2 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Unit</th>
              <th className="text-right px-2 py-2 font-semibold" style={{ color: colors.onSurfaceSecondary }}>Total</th>
            </tr>
          </thead>
          <tbody>
            {(doc.line_items || []).map((li, i) => (
              <tr key={i} style={{
                borderBottom: `1px solid ${colors.divider}`,
                backgroundColor: li.is_late_fee ? "#FFF7ED" : undefined,
              }}
                  data-testid={li.is_late_fee ? "line-item-late-fee" : undefined}>
                <td className="px-2 py-2" style={{ color: colors.onSurface }}>
                  <div className="flex items-center gap-2">
                    <span>{li.description}</span>
                    {li.is_late_fee ? (
                      <span
                        className="px-1.5 py-0.5 rounded-md text-[10px] font-bold uppercase tracking-wide"
                        style={{ backgroundColor: "#FEE2E2", color: "#B91C1C" }}
                        data-testid="late-fee-chip"
                      >
                        Late fee
                      </span>
                    ) : null}
                  </div>
                </td>
                <td className="px-2 py-2 text-right" style={{ color: colors.onSurfaceSecondary }}>{li.quantity}</td>
                <td className="px-2 py-2 text-right" style={{ color: colors.onSurfaceSecondary }}>{money(li.unit_price)}</td>
                <td className="px-2 py-2 text-right font-semibold" style={{ color: colors.onSurface }}>
                  {money((li.quantity || 0) * (li.unit_price || 0))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-4 flex justify-end">
          <div className="w-64 space-y-1 text-sm">
            <div className="flex justify-between"><span style={{ color: colors.muted }}>Subtotal</span><span>{money(doc.subtotal)}</span></div>
            <div className="flex justify-between"><span style={{ color: colors.muted }}>Tax ({doc.tax_rate}%)</span><span>{money(doc.tax)}</span></div>
            <div className="flex justify-between font-bold" style={{ color: colors.brand }}>
              <span>Total</span><span>{money(doc.total)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* Terms & Conditions */}
      <div
        className="rounded-2xl p-5 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="doc-terms-card"
      >
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs uppercase font-semibold tracking-wide"
               style={{ color: colors.muted }}>
            Terms &amp; Conditions
          </div>
          <button
            onClick={() => { setTermsDraft(doc.terms || ""); setTermsEditOpen(true); }}
            className="text-xs font-semibold hover:underline"
            style={{ color: colors.brand }}
            data-testid="doc-terms-edit"
          >
            Edit
          </button>
        </div>
        {(doc.terms || "").trim() ? (
          <p className="text-sm whitespace-pre-wrap" style={{ color: colors.onSurface }}
             data-testid="doc-terms-text">
            {doc.terms}
          </p>
        ) : (
          <p className="text-sm italic" style={{ color: colors.muted }}
             data-testid="doc-terms-empty">
            No terms provided.
          </p>
        )}
      </div>

      {/* Payment handles chips */}
      {isInvoice && handles && (handles.venmo || handles.zelle || handles.cashapp || handles.paypal) ? (
        <div
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>
            Alternate pay methods
          </div>
          <div className="flex flex-wrap gap-2">
            {handles.venmo ? <Chip label={`Venmo · ${handles.venmo}`} tone="purple" /> : null}
            {handles.zelle ? <Chip label={`Zelle · ${handles.zelle}`} tone="brand" /> : null}
            {handles.cashapp ? <Chip label={`Cash App · ${handles.cashapp}`} tone="success" /> : null}
            {handles.paypal ? <Chip label={`PayPal · ${handles.paypal}`} tone="brand" /> : null}
          </div>
        </div>
      ) : null}

      {/* Payment link modal */}
      <Modal
        open={termsEditOpen}
        onClose={() => setTermsEditOpen(false)}
        title="Edit Terms & Conditions"
        footer={
          <div className="flex justify-between items-center w-full flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setTermsDraft(termsDefaultForDoc)}
              className="text-xs font-semibold hover:underline"
              style={{ color: colors.brand }}
              data-testid="doc-terms-reset"
            >
              Reset to default
            </button>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => setTermsEditOpen(false)}>Cancel</Button>
              <Button
                onClick={async () => {
                  try {
                    await api.put(`/quotes/${id}`, { terms: termsDraft });
                    setTermsEditOpen(false);
                    setToast({ tone: "success", message: "Terms saved" });
                    await load();
                  } catch (e) {
                    setToast({ tone: "error", message: e.message });
                  }
                }}
                testid="doc-terms-save"
              >
                Save
              </Button>
            </div>
          </div>
        }
      >
        <textarea
          rows={8}
          value={termsDraft}
          onChange={(e) => setTermsDraft(e.target.value)}
          placeholder="Legal terms rendered on the document + PDF."
          className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
          data-testid="doc-terms-textarea"
        />
      </Modal>
      <Modal open={linkOpen} onClose={() => setLinkOpen(false)} title="Stripe Payment Link"
        footer={<Button onClick={() => setLinkOpen(false)}>Close</Button>}>
        <p className="text-sm mb-3" style={{ color: colors.onSurfaceSecondary }}>Copy and share this link to collect payment.</p>
        <div className="p-3 rounded-lg text-xs break-all font-mono"
          style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}>
          {linkUrl}
        </div>
        <div className="mt-3 flex gap-2">
          <Button variant="ghost" onClick={() => { navigator.clipboard.writeText(linkUrl); setToast({ tone: "success", message: "Copied" }); }} testid="qd-copy-link">Copy</Button>
          <a href={linkUrl} target="_blank" rel="noreferrer">
            <Button variant="ghost">Open in Stripe</Button>
          </a>
        </div>
      </Modal>

      <SmsModal open={smsOpen} onClose={() => setSmsOpen(false)} invoice={doc} customer={customer}
        onDone={(m, t) => { setSmsOpen(false); setToast({ tone: t || "success", message: m }); }} />

      <RecordPaymentModal open={payOpen} onClose={() => setPayOpen(false)} invoice={doc}
        onDone={async (m) => { setPayOpen(false); setToast({ tone: "success", message: m }); await load(); }}
        onError={(e) => setToast({ tone: "error", message: e })} />

      <ConvertToJobModal
        open={convertOpen}
        onClose={() => setConvertOpen(false)}
        quote={doc}
        onDone={(jid) => { setConvertOpen(false); navigate(`/jobs/${jid}`); }}
        onError={(e) => setToast({ tone: "error", message: e })}
      />

      <Modal open={confirmDelete} onClose={() => setConfirmDelete(false)}
        title="Cancel this document?"
        footer={<>
          <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Keep it</Button>
          <Button variant="danger" onClick={del}>Cancel it</Button>
        </>}>
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Marks the document as cancelled. It stays in the ledger.</p>
      </Modal>

      <Modal open={signOpen} onClose={() => setSignOpen(false)} title="Send for signature"
        footer={<>
          <Button variant="ghost" onClick={() => setSignOpen(false)}>Cancel</Button>
          <Button onClick={requestSignature} testid="sig-modal-submit">Send</Button>
        </>}>
        <div className="space-y-3" data-testid="sig-request-modal">
          <TextInput label="RECIPIENT EMAIL" value={signEmail} onChange={(e) => setSignEmail(e.target.value)} />
          <div>
            <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>PERSONAL MESSAGE (optional)</label>
            <textarea value={signMsg} onChange={(e) => setSignMsg(e.target.value)} rows={3}
              className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
              style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
              placeholder="Please review and sign your estimate." />
          </div>
          <p className="text-xs" style={{ color: colors.muted }}>
            Sends a magic-link the customer can open without logging in.
          </p>
        </div>
      </Modal>

      <Toast toast={toast} onClose={() => setToast(null)} />
      {payNowOpen ? (
        <PaymentForm
          invoiceId={doc?.id}
          source="authenticated"
          onClose={() => setPayNowOpen(false)}
          onSuccess={() => {
            setPayNowOpen(false);
            setToast({ tone: "success", message: "Payment received. Thank you!" });
            // Refresh invoice so paid/partial reflects immediately.
            api.get(`/quotes/${id}`).then(setDoc).catch(() => {});
          }}
        />
      ) : null}
    </div>
  );
}

function SmsModal({ open, onClose, invoice, customer, onDone }) {
  const [to, setTo] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setTo(customer?.phone || "");
      setMsg(`Invoice ${invoice.id.slice(0, 8).toUpperCase()}: $${(invoice.total || 0).toFixed(2)} due. Pay: ${invoice.payment_link || "(generate link first)"}`);
    }
  }, [open, customer, invoice]);
  const send = async () => {
    setBusy(true);
    try {
      const r = await api.post(`/invoices/${invoice.id}/send-sms`, { to, message: msg });
      if (r.sent) onDone(`Text sent to ${r.to}`);
      else if (r.reason === "twilio-not-configured") onDone("Twilio not configured — SMS skipped (dev mode)", "info");
      else onDone(r.reason || "Failed", "error");
    } catch (e) {
      onDone(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Text Invoice via SMS"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={send} disabled={busy}>{busy ? "Sending…" : "Send SMS"}</Button></>}>
      <div className="space-y-3">
        <TextInput label="TO" value={to} onChange={(e) => setTo(e.target.value)} />
        <div>
          <label className="text-xs font-semibold tracking-wide mb-1 block" style={{ color: colors.onSurfaceSecondary }}>MESSAGE</label>
          <textarea value={msg} onChange={(e) => setMsg(e.target.value)} rows={4}
            className="w-full px-3 py-2 text-sm rounded-lg outline-none focus:ring-2"
            style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }} />
        </div>
      </div>
    </Modal>
  );
}

function RecordPaymentModal({ open, onClose, invoice, onDone, onError }) {
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setAmount(String(Math.max(0, Number(invoice.total || 0) - Number(invoice.amount_paid || 0)).toFixed(2)));
  }, [open, invoice]);
  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/quotes/${invoice.id}/record-payment`, { amount: Number(amount) });
      onDone(`Recorded ${money(Number(amount))}`);
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Record Payment"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy}>{busy ? "Saving…" : "Record"}</Button></>}>
      <TextInput label="AMOUNT" type="number" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
      <p className="text-xs mt-2" style={{ color: colors.muted }}>Cash / check / other — recorded manually. Stripe checkout marks paid automatically.</p>
    </Modal>
  );
}

function ConvertToJobModal({ open, onClose, quote, onDone, onError }) {
  const [scheduledDate, setScheduledDate] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const j = await api.post(`/quotes/${quote.id}/convert-to-job`, { scheduled_date: scheduledDate || null });
      onDone(j.id);
    } catch (e) {
      onError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open={open} onClose={onClose} title="Convert quote to job"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button onClick={submit} disabled={busy} testid="qd-convert-submit">{busy ? "Creating…" : "Create job"}</Button></>}>
      <TextInput label="SCHEDULE DATE (optional)" type="date" value={scheduledDate} onChange={(e) => setScheduledDate(e.target.value)} />
      <p className="text-xs mt-2" style={{ color: colors.muted }}>Creates a scheduled job for {quote.customer_name} totaling {money(quote.total)}.</p>
    </Modal>
  );
}
