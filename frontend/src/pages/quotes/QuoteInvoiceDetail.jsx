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
} from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";
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

  const load = async () => {
    try {
      const q = await api.get(`/quotes/${id}`);
      setDoc(q);
      if (q.customer_id) {
        api.get(`/customers/${q.customer_id}`).then(setCustomer).catch(() => {});
        api.get(`/payments/method?customer_id=${q.customer_id}`).then(setPmethod).catch(() => setPmethod(null));
      }
      api.get("/settings/payment-handles").then(setHandles).catch(() => {});
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

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid={`${isInvoice ? "invoice" : "quote"}-detail`}>
      <button
        onClick={() => navigate(isInvoice ? "/invoices" : "/quotes")}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> All {isInvoice ? "invoices" : "quotes"}
      </button>

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

      <Toast toast={toast} onClose={() => setToast(null)} />
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
