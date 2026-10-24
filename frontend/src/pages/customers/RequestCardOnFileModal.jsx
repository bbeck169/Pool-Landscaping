/**
 * TD-customer-list-bulk-request-card-on-file · Feb-2026.
 *
 * Modal for the Customers list "Request card on file" bulk action.
 *
 * Flow
 * ----
 * 1. Operator selects ≥1 customers on the Customers list and clicks
 *    "Request card on file" in the floating ``<BulkActionBar>``.
 * 2. This modal opens with:
 *      * Email template picker (``channel=email`` list, auto-pre-
 *        selects a row with ``code === "add_card_request_email"``
 *        when it exists).
 *      * SMS template picker (``channel=sms``, same auto-select
 *        contract against ``add_card_request_sms``).
 *      * Live preview panel per channel — fetched via
 *        ``POST /marketing/templates/{tid}/preview`` so merge-tag
 *        rendering is byte-identical to what the server will send.
 * 3. On confirm, POST /customers/bulk-request-card with the full
 *    selection + both chosen template ids.
 *      * 200 → render the per-row ``results`` + ``counts`` summary.
 *      * 403 ``tenant_isolation_breach`` → render the categorised
 *        ``errors`` list inline so operator sees exactly which
 *        customer_id / template_id was foreign / orphan.
 *      * Other errors → generic toast.
 *
 * Isolation guarantees: every request this modal fires goes through
 * ``api.*`` which attaches the operator's bearer token.  The BE
 * scopes all three endpoints by ``tenant_id`` + role so there's no
 * cross-tenant readability from the picker or the send step.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { X, Send, AlertTriangle, CheckCircle2, CircleSlash } from "lucide-react";
import { api } from "@/api";
import { Button, Modal } from "@/components/ui-kit";

const _CODE_EMAIL = "add_card_request_email";
const _CODE_SMS = "add_card_request_sms";


export default function RequestCardOnFileModal({
  open,
  onClose,
  customerIds,       // Array<string>  selected customer ids
  onSent,            // callback(summary) fired after a 200 send
}) {
  const [emailTemplates, setEmailTemplates] = useState([]);
  const [smsTemplates, setSmsTemplates] = useState([]);
  const [emailTemplateId, setEmailTemplateId] = useState("");
  const [smsTemplateId, setSmsTemplateId] = useState("");
  const [emailPreview, setEmailPreview] = useState(null);
  const [smsPreview, setSmsPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [results, setResults] = useState(null);
  const [beErrors, setBeErrors] = useState([]);

  // ─── Load tenant-scoped templates when the modal opens ──────────
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setBeErrors([]);
    setResults(null);
    (async () => {
      try {
        const [eRes, sRes] = await Promise.all([
          api.get("/marketing/templates?channel=email&active=true"),
          api.get("/marketing/templates?channel=sms&active=true"),
        ]);
        if (cancelled) return;
        const _emails = eRes?.templates || eRes?.items || [];
        const _smses = sRes?.templates || sRes?.items || [];
        setEmailTemplates(_emails);
        setSmsTemplates(_smses);
        // Auto-pre-select by code when present.
        const _preE = _emails.find((t) => t?.code === _CODE_EMAIL);
        const _preS = _smses.find((t) => t?.code === _CODE_SMS);
        setEmailTemplateId(_preE?.id || "");
        setSmsTemplateId(_preS?.id || "");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  // ─── Live preview per channel ──────────────────────────────────
  const _preview = useCallback(async (tid, setter) => {
    if (!tid) { setter(null); return; }
    try {
      const r = await api.post(`/marketing/templates/${tid}/preview`, {});
      setter({
        subject: r?.subject ?? r?.rendered_subject ?? "",
        body: r?.body ?? r?.rendered_body ?? "",
      });
    } catch { setter(null); }
  }, []);
  useEffect(() => { _preview(emailTemplateId, setEmailPreview); },
            [emailTemplateId, _preview]);
  useEffect(() => { _preview(smsTemplateId,   setSmsPreview); },
            [smsTemplateId, _preview]);

  const canSend = (emailTemplateId || smsTemplateId)
                   && customerIds.length > 0 && !sending;

  const confirm = async () => {
    setSending(true);
    setBeErrors([]);
    try {
      const r = await api.post("/customers/bulk-request-card", {
        customer_ids: customerIds,
        email_template_id: emailTemplateId || null,
        sms_template_id: smsTemplateId || null,
      });
      setResults(r);
      onSent?.(r);
    } catch (e) {
      const _detail = e?.data?.detail || null;
      if (_detail?.error === "tenant_isolation_breach"
          && Array.isArray(_detail.errors)) {
        setBeErrors(_detail.errors);
      } else {
        setBeErrors([{ reason: "unknown",
                       message: e?.message || "Send failed" }]);
      }
    } finally {
      setSending(false);
    }
  };

  if (!open) return null;

  return (
    <Modal open={open} onClose={onClose} title="Request card on file"
            data-testid="request-card-modal">
      <div className="space-y-4 p-4">
        {results ? (
          <SummaryPanel results={results} onClose={onClose} />
        ) : (
          <>
            <div className="text-sm font-semibold"
                  data-testid="request-card-recipient-count">
              Sending to {customerIds.length} customer{customerIds.length === 1 ? "" : "s"}
            </div>

            {beErrors.length > 0 ? (
              <ErrorPanel errors={beErrors} />
            ) : null}

            {loading ? (
              <div className="text-xs text-gray-500">
                Loading templates…
              </div>
            ) : (
              <>
                <TemplateChannelBlock
                  label="Email template"
                  testid="email"
                  templates={emailTemplates}
                  value={emailTemplateId}
                  onChange={setEmailTemplateId}
                  preview={emailPreview}
                />
                <TemplateChannelBlock
                  label="SMS template"
                  testid="sms"
                  templates={smsTemplates}
                  value={smsTemplateId}
                  onChange={setSmsTemplateId}
                  preview={smsPreview}
                />
              </>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button type="button" onClick={onClose}
                       className="text-sm px-3 py-1.5 rounded-md border"
                       data-testid="request-card-cancel">
                Cancel
              </button>
              <Button
                onClick={confirm}
                disabled={!canSend}
                data-testid="request-card-confirm">
                <Send size={14} />{" "}
                {sending ? "Sending…"
                  : `Send to ${customerIds.length} customer${customerIds.length === 1 ? "" : "s"}`}
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}


function TemplateChannelBlock({ label, testid, templates, value, onChange, preview }) {
  return (
    <section className="rounded-md border p-3 space-y-2"
              data-testid={`request-card-${testid}-block`}>
      <div className="text-xs font-bold uppercase tracking-wider text-gray-500">
        {label}
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full text-sm border rounded-md px-2 py-1.5"
        data-testid={`request-card-${testid}-select`}
      >
        <option value="">— skip this channel —</option>
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}{t.code ? ` [${t.code}]` : ""}
          </option>
        ))}
      </select>
      {value && preview ? (
        <div className="rounded bg-gray-50 p-2 text-xs space-y-1"
              data-testid={`request-card-${testid}-preview`}>
          {preview.subject ? (
            <div><b>Subject:</b> {preview.subject}</div>
          ) : null}
          <pre className="whitespace-pre-wrap font-sans">{preview.body}</pre>
        </div>
      ) : null}
    </section>
  );
}


function ErrorPanel({ errors }) {
  return (
    <div className="rounded-md border border-red-300 bg-red-50 p-3 text-xs text-red-900 space-y-1"
          data-testid="request-card-error-panel">
      <div className="flex items-center gap-1 font-semibold">
        <AlertTriangle size={14} /> Send blocked — tenant isolation breach
      </div>
      <ul className="list-disc pl-5">
        {errors.map((e, i) => (
          <li key={i} data-testid={`request-card-error-${e.reason}`}>
            {e.customer_id ? `Customer ${String(e.customer_id).slice(0, 8)}…` : null}
            {e.template_id ? `Template ${String(e.template_id).slice(0, 8)}…` : null}
            {" — "}
            {e.reason === "foreign_tenant" ? "belongs to another tenant" :
              e.reason === "orphan" ? "no record found" :
              (e.message || e.reason)}
          </li>
        ))}
      </ul>
    </div>
  );
}


function SummaryPanel({ results, onClose }) {
  const counts = results?.counts || {};
  const rows = results?.results || [];
  return (
    <div className="space-y-3" data-testid="request-card-summary">
      <div className="text-sm font-semibold flex items-center gap-2">
        <CheckCircle2 size={16} className="text-green-600" />
        Send complete
      </div>
      <div className="grid grid-cols-4 gap-2 text-xs">
        <Tally label="Emails sent"  value={counts.email_sent || 0}
                testid="summary-email-sent" />
        <Tally label="SMS sent"    value={counts.sms_sent || 0}
                testid="summary-sms-sent" />
        <Tally label="Skipped"     value={counts.skipped || 0}
                testid="summary-skipped" tone="warn" />
        <Tally label="Errors"      value={counts.error || 0}
                testid="summary-error" tone="danger" />
      </div>
      <div className="rounded border max-h-64 overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              <th className="text-left p-2">Customer</th>
              <th className="text-left p-2">Email</th>
              <th className="text-left p-2">SMS</th>
              <th className="text-left p-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.customer_id} className="border-t"
                   data-testid={`summary-row-${r.customer_id}`}>
                <td className="p-2 font-mono">{String(r.customer_id).slice(0, 8)}…</td>
                <td className="p-2">{r.email_status}</td>
                <td className="p-2">{r.sms_status}</td>
                <td className="p-2">
                  <StatusChip status={r.status} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end">
        <Button onClick={onClose} data-testid="request-card-close">Close</Button>
      </div>
    </div>
  );
}


function Tally({ label, value, testid, tone = "info" }) {
  const bg = tone === "danger" ? "bg-red-50 text-red-900 border-red-200" :
             tone === "warn"   ? "bg-yellow-50 text-yellow-900 border-yellow-200" :
             "bg-green-50 text-green-900 border-green-200";
  return (
    <div className={`rounded border p-2 ${bg}`} data-testid={testid}>
      <div className="text-[10px] uppercase tracking-wider">{label}</div>
      <div className="text-lg font-bold">{value}</div>
    </div>
  );
}


function StatusChip({ status }) {
  const tone = status === "sent_both"       ? "bg-green-100 text-green-800" :
                status === "sent_email_only" ? "bg-blue-100 text-blue-800" :
                status === "sent_sms_only"   ? "bg-blue-100 text-blue-800" :
                status === "skipped_no_contact" ? "bg-yellow-100 text-yellow-800" :
                "bg-red-100 text-red-800";
  return (
    <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[11px] font-semibold ${tone}`}>
      {status === "skipped_no_contact" ? <CircleSlash size={10} /> : null}
      {status}
    </span>
  );
}
