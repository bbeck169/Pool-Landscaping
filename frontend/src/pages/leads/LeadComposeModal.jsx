// Phase L3 · Feb-2026 — Compose SMS/email from a lead.
//
// Two flavors — ``channel="sms"`` renders a single textarea with a
// GSM-7 aware char counter (warns > 160 to flag multi-segment cost);
// ``channel="email"`` renders subject + plaintext body inputs.
//
// Consent guardrails — when the lead's ``sms_ok`` / ``email_ok`` flag
// is explicitly ``false`` we render a red warning line + an "Override
// — send anyway" checkbox.  The primary button stays disabled until
// the checkbox flips.  Missing flag on the lead document is treated
// as ``true`` (matches the backend ``.get("sms_ok", True)`` pattern).
//
// Truthful toasts — success shows the provider status; failures show
// the raw error string so ops can debug.
import React, { useState, useMemo } from "react";
import { api } from "@/api";
import { toast } from "sonner";
import { X } from "lucide-react";

const SMS_HARD_CAP = 1600;
const SMS_SINGLE_SEGMENT_WARN = 160;

export default function LeadComposeModal({
  lead, channel, onClose, onSent,
}) {
  const isSms = channel === "sms";
  const [body, setBody] = useState("");
  const [subject, setSubject] = useState("");
  const [override, setOverride] = useState(false);
  const [busy, setBusy] = useState(false);

  // Consent — absent field on the lead means "OK".
  const consentOk = isSms
    ? lead.sms_ok !== false
    : lead.email_ok !== false;
  const needsOverride = !consentOk;

  const canSend = useMemo(() => {
    if (busy) return false;
    if (needsOverride && !override) return false;
    if (isSms) return body.trim().length > 0 && body.length <= SMS_HARD_CAP;
    return subject.trim().length > 0 && body.trim().length > 0;
  }, [busy, needsOverride, override, isSms, body, subject]);

  const submit = async () => {
    setBusy(true);
    try {
      const path = isSms
        ? `/leads/${lead.id}/send-sms`
        : `/leads/${lead.id}/send-email`;
      const payload = isSms
        ? { body, override_consent: override }
        : { subject, body, override_consent: override };
      const row = await api.post(path, payload);
      const status = row?.status || "sent";
      const label = isSms ? "SMS" : "Email";
      if (status === "sent") {
        toast.success(`${label} sent`, { description: row?.provider_status_raw || "" });
      } else {
        toast.error(`${label} ${status}`, { description: row?.error || row?.provider_status_raw || "" });
      }
      onSent?.(row);
      onClose?.();
    } catch (e) {
      const detail = e?.data?.detail || e?.message || "Send failed";
      toast.error(typeof detail === "string" ? detail : (detail?.message || "Send failed"));
    } finally {
      setBusy(false);
    }
  };

  // Char-counter classes.
  const charCount = body.length;
  const charWarn = isSms && charCount > SMS_SINGLE_SEGMENT_WARN;
  const charOver = isSms && charCount > SMS_HARD_CAP;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      data-testid="lead-compose-modal"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-lg max-w-lg w-full p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold">
            {isSms ? "Send SMS" : "Send Email"}
          </h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-700"
            data-testid="lead-compose-close"
            aria-label="Close compose"
          >
            <X size={18} />
          </button>
        </div>

        <div className="text-xs text-slate-500 mb-3">
          To: <span className="font-mono">
            {isSms ? (lead.phone || "—") : (lead.email || "—")}
          </span>
          {lead.name ? <span className="ml-2 text-slate-600">· {lead.name}</span> : null}
        </div>

        {needsOverride && (
          <div
            className="mb-3 rounded border border-rose-200 bg-rose-50 p-2 text-xs text-rose-800"
            data-testid="lead-compose-consent-warning"
          >
            <div className="font-semibold mb-1">
              This lead has opted out of {isSms ? "SMS" : "email"}.
            </div>
            <label className="inline-flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={override}
                onChange={(e) => setOverride(e.target.checked)}
                data-testid="lead-compose-override"
              />
              <span>Override — send anyway</span>
            </label>
          </div>
        )}

        {!isSms && (
          <div className="mb-2">
            <label className="text-xs font-medium text-slate-600">Subject</label>
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              maxLength={200}
              className="mt-1 w-full border border-slate-300 rounded px-2 py-1.5 text-sm"
              placeholder="Following up on your quote request…"
              data-testid="lead-compose-subject"
            />
          </div>
        )}

        <div className="mb-2">
          <label className="text-xs font-medium text-slate-600">
            {isSms ? "Message" : "Body"}
          </label>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            maxLength={isSms ? SMS_HARD_CAP : 50000}
            rows={isSms ? 5 : 8}
            className="mt-1 w-full border border-slate-300 rounded p-2 text-sm"
            placeholder={isSms
              ? "Hi, following up on your quote request…"
              : "Write your message…"}
            data-testid="lead-compose-body"
          />
          {isSms && (
            <div
              className={
                "text-[11px] mt-1 " +
                (charOver
                  ? "text-rose-700 font-semibold"
                  : charWarn
                    ? "text-amber-700"
                    : "text-slate-500")
              }
              data-testid="lead-compose-char-counter"
            >
              {charCount} / {SMS_HARD_CAP}
              {charWarn && !charOver ? " · will send as multi-segment SMS" : ""}
              {charOver ? " · over the 1600-character cap" : ""}
            </div>
          )}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded border border-slate-300 text-sm"
            data-testid="lead-compose-cancel"
          >
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={!canSend}
            className="px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-700 text-white text-sm disabled:opacity-50"
            data-testid="lead-compose-send"
          >
            {busy ? "Sending…" : (isSms ? "Send SMS" : "Send Email")}
          </button>
        </div>
      </div>
    </div>
  );
}
