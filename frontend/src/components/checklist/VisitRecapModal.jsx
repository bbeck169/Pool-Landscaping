/**
 * Phase 39 · Step 2 · Visit Recap modal (web).
 *
 * Shown right after `Close Job` completes on the ChecklistModal. Lets
 * the tech decide whether to text the customer, email them, both — or
 * skip the whole thing. Uses honest mocking: when RingCentral/Resend
 * aren't configured the backend returns `{sent:false, mocked:true, reason}`
 * per channel and this modal surfaces the reason verbatim.
 */
import React, { useMemo, useState } from "react";
import { X as CloseX, Send, MessageCircle, Mail, Camera, AlertTriangle, CheckCircle2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export default function VisitRecapModal({
  serviceReportId,
  customer,
  onClose,
}) {
  // Default channel: whichever contacts we have, biased to "both" when
  // both phone and email exist.
  // APR-III · Feb-2026 — the legacy after-hours fallback was dropped
  // (field removed from CustomerIn in APR-II); SMS routes to primary
  // phone only.
  const hasPhone = !!customer?.phone;
  const hasEmail = !!customer?.email;
  const defaultChannel = hasPhone && hasEmail ? "both" : hasEmail ? "email" : hasPhone ? "sms" : "";

  const [channel, setChannel] = useState(defaultChannel);
  const [includePhotos, setIncludePhotos] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const disabledMsg = useMemo(() => {
    if (!hasPhone && !hasEmail) return "Customer has no phone or email on file.";
    return "";
  }, [hasPhone, hasEmail]);

  const send = async () => {
    if (!channel || busy) return;
    setBusy(true); setErr(""); setResult(null);
    try {
      const r = await api.post(
        `/service-reports/${serviceReportId}/send-recap`,
        { channel, include_photos: includePhotos },
      );
      setResult(r);
      if (r?.sent) {
        // Auto-close on any real send.
        setTimeout(() => onClose?.(), 2000);
      }
    } catch (e) {
      setErr(e?.message || "Send failed.");
    } finally {
      setBusy(false);
    }
  };

  const skip = () => onClose?.();

  return (
    <div
      onClick={skip}
      style={{
        position: "fixed", inset: 0, background: "rgba(15,23,42,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        zIndex: 60, padding: "16px",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        data-testid="visit-recap-modal"
        style={{
          background: colors.surface, borderRadius: 16, maxWidth: 480,
          width: "100%", border: `1px solid ${colors.border}`,
          boxShadow: "0 20px 60px rgba(15,23,42,0.25)",
        }}
      >
        <div className="flex items-center justify-between px-5 py-3"
             style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="flex items-center gap-2">
            <Send size={16} color={colors.brand} />
            <div className="text-lg font-bold" style={{ color: colors.onSurface }}>
              Send visit recap?
            </div>
          </div>
          <button onClick={skip} style={{ background: "transparent", border: 0, cursor: "pointer" }}>
            <CloseX size={18} color={colors.muted} />
          </button>
        </div>

        <div className="px-5 py-4">
          <div className="text-sm mb-3" style={{ color: colors.onSurface }}>
            Text or email <b>{customer?.name || "the customer"}</b> a summary of
            today's visit — chemicals added, water readings{" "}
            {includePhotos ? "and up to 3 photos" : ""}.
          </div>

          {disabledMsg ? (
            <div
              className="p-3 rounded-md text-xs font-semibold flex items-center gap-2 mb-3"
              style={{ background: "#FEE2E2", color: "#B91C1C" }}
            >
              <AlertTriangle size={12} /> {disabledMsg}
            </div>
          ) : null}

          {/* Channel radios */}
          <div className="flex flex-wrap gap-2 mb-3">
            <ChannelPill
              label="SMS" icon={MessageCircle} disabled={!hasPhone}
              selected={channel === "sms"} onClick={() => setChannel("sms")}
              testId="visit-recap-channel-sms"
            />
            <ChannelPill
              label="Email" icon={Mail} disabled={!hasEmail}
              selected={channel === "email"} onClick={() => setChannel("email")}
              testId="visit-recap-channel-email"
            />
            <ChannelPill
              label="Both" icon={Send} disabled={!(hasPhone && hasEmail)}
              selected={channel === "both"} onClick={() => setChannel("both")}
              testId="visit-recap-channel-both"
            />
          </div>

          {/* Include-photos toggle */}
          <label
            className="flex items-center gap-2 text-sm cursor-pointer mb-3"
            style={{ color: colors.onSurface }}
            data-testid="visit-recap-include-photos"
          >
            <input
              type="checkbox"
              checked={includePhotos}
              onChange={(e) => setIncludePhotos(e.target.checked)}
              style={{ accentColor: colors.brand }}
            />
            <Camera size={13} color={colors.muted} />
            Include photos (up to 3)
          </label>

          {result ? (
            <ResultBanner result={result} />
          ) : null}
          {err ? (
            <div
              className="p-2 rounded-md text-xs font-semibold flex items-center gap-1.5 mb-2"
              style={{ background: "#FEE2E2", color: "#B91C1C" }}
            >
              <AlertTriangle size={12} /> {err}
            </div>
          ) : null}
        </div>

        <div className="px-5 py-3 flex items-center justify-end gap-2"
             style={{ borderTop: `1px solid ${colors.border}` }}>
          <button
            onClick={skip}
            data-testid="visit-recap-skip-btn"
            className="px-3 py-1.5 rounded-md text-sm font-semibold"
            style={{
              background: "transparent", color: colors.onSurface,
              border: `1px solid ${colors.border}`, cursor: "pointer",
            }}
          >
            Skip
          </button>
          <button
            onClick={send}
            disabled={busy || !channel || !!disabledMsg}
            data-testid="visit-recap-send-btn"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-bold"
            style={{
              background: colors.brand, color: "#fff", border: 0,
              cursor: busy ? "wait" : "pointer",
              opacity: (busy || !channel || !!disabledMsg) ? 0.5 : 1,
            }}
          >
            <Send size={13} /> {busy ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ChannelPill({ label, icon: Icon, selected, disabled, onClick, testId }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold"
      style={{
        background: selected ? colors.brand : colors.surfaceSecondary || "#F1F5F9",
        color: selected ? "#fff" : (disabled ? colors.muted : colors.onSurface),
        border: `1px solid ${selected ? colors.brand : colors.border}`,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      <Icon size={13} /> {label}
    </button>
  );
}

function ResultBanner({ result }) {
  const mockedChannels = result?.mocked_channels || [];
  const okChannels = Object.entries(result?.results || {})
    .filter(([, v]) => v?.sent).map(([k]) => k);
  const anySent = result?.sent;
  return (
    <div className="space-y-1.5">
      {anySent ? (
        <div
          className="p-2 rounded-md text-xs font-semibold flex items-center gap-1.5"
          style={{ background: "#D1FAE5", color: "#065F46" }}
          data-testid="visit-recap-success"
        >
          <CheckCircle2 size={13} />
          Sent via {okChannels.join(" + ")}.
        </div>
      ) : null}
      {mockedChannels.map((ch) => {
        const reason = (result?.results || {})[ch]?.reason || "no reason";
        return (
          <div
            key={ch}
            className="p-2 rounded-md text-xs flex items-center gap-1.5"
            style={{ background: "#FEF3C7", color: "#B45309" }}
            data-testid="visit-recap-mocked-reason"
          >
            <AlertTriangle size={12} />
            <span>
              <b>{ch.toUpperCase()}</b> not sent — {reason}
            </span>
          </div>
        );
      })}
    </div>
  );
}
