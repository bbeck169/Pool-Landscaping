import React, { useEffect, useMemo, useState } from "react";
import { Modal, Button } from "@/components/ui-kit";
import { colors } from "@/theme";
import { Mail, MessageSquare, Copy, Check, Link2, AlertTriangle } from "lucide-react";
import { api } from "@/api";

/**
 * Task 6 · Feb 2026 — "Send service records link" modal.
 *
 * Renders from the Customer detail page. Admin picks Email or SMS,
 * confirms the recipient (defaulting to the customer's primary
 * email/mobile) and taps Send. The backend mints a portal auto-login
 * magic URL that drops the customer directly on
 * ``/portal/service-reports`` (the existing portal list surface —
 * NO new portal view is invented). The URL is returned so the admin
 * can copy-paste it as a fallback.
 *
 * Compliance rules (see backend/routers/customers.py):
 *   - Consent hard-blocks: ``channel_opt_in.email_marketing=false``
 *     or ``sms_marketing=false`` (or ``is_muted=true``) disables the
 *     matching tab and renders a tooltip explaining the block.
 *     Admin CANNOT bypass.
 *   - Rate limit: 5 sends per hour per customer, across both
 *     channels. When throttled we render a warning banner with a
 *     retry-after countdown.
 */
export default function SendServiceRecordsLinkModal({
  open,
  customer,
  onClose,
  onSent,
  onError,
}) {
  const [channel, setChannel] = useState("email");
  const [recipient, setRecipient] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null); // { url, expires_at, ... }
  const [copied, setCopied] = useState(false);
  const [status, setStatus] = useState(null); // { rate_limited, sends_last_hour, ... }
  const [statusLoading, setStatusLoading] = useState(false);

  // ── Consent derivation. Absent field OR True = allow. Explicit
  //    False = block. Muted trumps everything.
  const muted = !!customer?.is_muted;
  const channelOptIn = customer?.channel_opt_in || {};
  const emailConsent = !muted && channelOptIn.email_marketing !== false;
  const smsConsent = !muted && channelOptIn.sms_marketing !== false;

  const defaultEmail = useMemo(() => {
    const primary = (customer?.emails || []).find((e) => e.is_primary)?.address;
    return (primary || customer?.email || "").trim();
  }, [customer]);
  const defaultMobile = useMemo(() => {
    const primary = (customer?.mobiles || []).find((m) => m.is_primary)?.number_e164;
    return (primary || customer?.phone || "").trim();
  }, [customer]);

  // Prefill recipient on open + when the channel switches.
  useEffect(() => {
    if (!open) return;
    setRecipient(channel === "email" ? defaultEmail : defaultMobile);
    setResult(null);
    setCopied(false);
  }, [open, channel, defaultEmail, defaultMobile]);

  // If the picked channel is consent-blocked but the other channel
  // isn't, auto-switch on open so the modal never lands on a
  // disabled tab.
  useEffect(() => {
    if (!open) return;
    if (channel === "email" && !emailConsent && smsConsent) {
      setChannel("sms");
    } else if (channel === "sms" && !smsConsent && emailConsent) {
      setChannel("email");
    }
  }, [open, channel, emailConsent, smsConsent]);

  // Fetch rate-limit status once when the modal opens so the send
  // button can preemptively show a throttle warning.
  useEffect(() => {
    if (!open || !customer?.id) return;
    setStatusLoading(true);
    api
      .get(`/customers/${customer.id}/service-records-link-status`)
      .then((r) => setStatus(r))
      .catch(() => setStatus(null))
      .finally(() => setStatusLoading(false));
  }, [open, customer?.id]);

  const consentOk = channel === "email" ? emailConsent : smsConsent;
  const noContactOnFile =
    channel === "email" ? !defaultEmail : !defaultMobile;

  const send = async () => {
    if (!recipient?.trim()) {
      onError?.("Recipient required");
      return;
    }
    setBusy(true);
    setResult(null);
    try {
      const r = await api.post(
        `/customers/${customer.id}/send-service-records-link`,
        { channel, recipient: recipient.trim() },
      );
      setResult(r);
      onSent?.(r);
      // Refresh throttle status so the count ticks up.
      api
        .get(`/customers/${customer.id}/service-records-link-status`)
        .then((s) => setStatus(s))
        .catch(() => {});
    } catch (e) {
      // 429 rate-limited comes back with a structured body; surface
      // it as a scoped banner rather than a toast.
      // FastAPI wraps ``HTTPException(detail={...})`` as
      // ``response.data = {"detail": {...}}`` — the dict body lives
      // at ``e.data.detail``.
      const detail = e?.data?.detail;
      if (e?.status === 429 || (typeof detail === "object" && detail?.detail === "rate_limited")) {
        setStatus((s) => ({ ...(s || {}),
                            rate_limited: true,
                            retry_after_seconds: detail?.retry_after_seconds,
                            sends_last_hour: detail?.limit_per_hour || 5,
                            rate_limit: detail?.limit_per_hour || 5 }));
      } else if (typeof detail === "object" && detail?.detail === "consent_blocked") {
        onError?.(detail.message || "Consent blocked");
      } else {
        onError?.(e?.message || "Send failed");
      }
    } finally {
      setBusy(false);
    }
  };

  const copyUrl = async () => {
    if (!result?.url) return;
    try {
      await navigator.clipboard.writeText(result.url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback — select + copy via a hidden textarea.
      const ta = document.createElement("textarea");
      ta.value = result.url;
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); setCopied(true); } catch {}
      document.body.removeChild(ta);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const rateLimited = !!status?.rate_limited;
  const disabledSend =
    busy ||
    !consentOk ||
    !recipient?.trim() ||
    rateLimited;

  return (
    <Modal
      open={!!open}
      onClose={onClose}
      title="Send service records link"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} testid="sr-link-cancel">
            Close
          </Button>
          <Button
            onClick={send}
            disabled={disabledSend}
            testid="sr-link-send"
          >
            {busy ? "Sending…" : `Send via ${channel === "email" ? "Email" : "SMS"}`}
          </Button>
        </>
      }
    >
      <div className="space-y-4" data-testid="sr-link-modal">
        <p className="text-sm" style={{ color: colors.muted }}>
          Send <strong>{customer?.name || "this customer"}</strong> a secure
          link that opens their service records — no password required.
          Link expires in 7 days.
        </p>

        {/* Channel tabs */}
        <div
          className="inline-flex rounded-md border overflow-hidden"
          style={{ borderColor: colors.border }}
          data-testid="sr-link-channel-tabs"
        >
          <TabButton
            active={channel === "email"}
            disabled={!emailConsent}
            disabledTitle={
              muted
                ? "Customer is muted — outbound comms disabled"
                : "Email opt-in is off for this customer"
            }
            onClick={() => emailConsent && setChannel("email")}
            testid="sr-link-tab-email"
          >
            <Mail size={14} /> Email
          </TabButton>
          <TabButton
            active={channel === "sms"}
            disabled={!smsConsent}
            disabledTitle={
              muted
                ? "Customer is muted — outbound comms disabled"
                : "SMS opt-in is off for this customer"
            }
            onClick={() => smsConsent && setChannel("sms")}
            testid="sr-link-tab-sms"
          >
            <MessageSquare size={14} /> SMS
          </TabButton>
        </div>

        {!consentOk ? (
          <ConsentBanner
            channel={channel}
            muted={muted}
            testid="sr-link-consent-banner"
          />
        ) : null}

        {rateLimited ? (
          <RateLimitBanner
            status={status}
            testid="sr-link-rate-banner"
          />
        ) : null}

        {/* Recipient */}
        <div>
          <label
            htmlFor="sr-link-recipient-input"
            className="block text-xs uppercase font-semibold mb-1"
            style={{ color: colors.muted }}
          >
            {channel === "email" ? "Recipient email" : "Recipient phone"}
          </label>
          <input
            id="sr-link-recipient-input"
            type="text"
            className="w-full rounded-md px-3 py-2 text-sm border"
            style={{ borderColor: colors.border, background: colors.surface }}
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
            disabled={!consentOk}
            placeholder={
              noContactOnFile
                ? `No ${channel} on file for this customer`
                : ""
            }
            data-testid="sr-link-recipient"
          />
          <div
            className="text-xs mt-1"
            style={{ color: colors.muted }}
            data-testid="sr-link-recipient-hint"
          >
            Must match one of the customer's contacts on file.
          </div>
        </div>

        {/* Successful send — surface the URL for copy fallback. */}
        {result?.url ? (
          <div
            className="rounded-md border p-3"
            style={{ borderColor: colors.border, background: colors.surfaceSecondary }}
            data-testid="sr-link-result"
          >
            <div
              className="flex items-center gap-2 text-xs font-semibold mb-2"
              style={{ color: colors.onSurface }}
            >
              <Link2 size={14} /> Link ready — sent to{" "}
              <span data-testid="sr-link-result-recipient">
                {result.recipient}
              </span>
            </div>
            <div className="flex items-stretch gap-2">
              <input
                readOnly
                value={result.url}
                className="flex-1 rounded-md px-2 py-1 text-xs border font-mono"
                style={{ borderColor: colors.border, background: colors.surface }}
                data-testid="sr-link-result-url"
                onFocus={(e) => e.target.select()}
              />
              <Button
                variant="ghost"
                onClick={copyUrl}
                testid="sr-link-copy"
              >
                {copied ? (
                  <>
                    <Check size={14} /> Copied
                  </>
                ) : (
                  <>
                    <Copy size={14} /> Copy
                  </>
                )}
              </Button>
            </div>
            <div
              className="text-xs mt-2"
              style={{ color: colors.muted }}
              data-testid="sr-link-result-expiry"
            >
              Expires {formatExpiry(result.expires_at)}
            </div>
          </div>
        ) : null}

        {/* Throttle counter (non-blocking hint below the 5-of-5 limit) */}
        {status && !rateLimited && !statusLoading ? (
          <div
            className="text-xs"
            style={{ color: colors.muted }}
            data-testid="sr-link-throttle-count"
          >
            {status.sends_last_hour || 0} / {status.rate_limit || 5} sends used
            in the past hour.
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

function TabButton({ active, disabled, disabledTitle, onClick, testid, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={disabled ? disabledTitle : undefined}
      aria-label={disabled ? disabledTitle : undefined}
      data-testid={testid}
      data-active={active ? "true" : "false"}
      data-disabled={disabled ? "true" : "false"}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm border-r last:border-r-0"
      style={{
        borderColor: colors.border,
        background: active
          ? colors.surface
          : disabled
          ? colors.surfaceSecondary
          : "transparent",
        color: disabled ? colors.muted : colors.onSurface,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.6 : 1,
        fontWeight: active ? 600 : 400,
      }}
    >
      {children}
    </button>
  );
}

function ConsentBanner({ channel, muted, testid }) {
  const isEmail = channel === "email";
  const msg = muted
    ? "This customer is muted — outbound comms are disabled. Ask an admin to unmute before sending."
    : isEmail
    ? "Email opt-in is off for this customer. Ask them to opt back in via their portal preferences before sending."
    : "SMS opt-in is off for this customer. Ask them to reply START to a prior text (or re-opt-in from the portal) before sending.";
  return (
    <div
      className="flex items-start gap-2 rounded-md p-3 text-sm"
      style={{
        background: "#fef3c7",
        color: "#92400e",
        border: "1px solid #fbbf24",
      }}
      data-testid={testid}
    >
      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
      <div>{msg}</div>
    </div>
  );
}

function RateLimitBanner({ status, testid }) {
  const retry = Number(status?.retry_after_seconds || 0);
  const mins = Math.max(1, Math.round(retry / 60));
  return (
    <div
      className="flex items-start gap-2 rounded-md p-3 text-sm"
      style={{
        background: "#fee2e2",
        color: "#991b1b",
        border: "1px solid #fca5a5",
      }}
      data-testid={testid}
    >
      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 2 }} />
      <div>
        Rate limit hit — max {status?.rate_limit || 5} sends per hour per
        customer. Try again in ~{mins} minute{mins === 1 ? "" : "s"}.
      </div>
    </div>
  );
}

function formatExpiry(iso) {
  if (!iso) return "in 7 days";
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return "in 7 days";
  }
}
