/**
 * Feb-2026 · Phase 1 — Tech "On my way" SMS button.
 *
 * Reusable one-tap CTA that posts to
 * ``POST /api/jobs/{jobId}/on-my-way``. Two placements share this
 * component in <TodaySchedule>:
 *   • The prominent top-level "On my way — next job" button.
 *   • A compact inline button on each job card.
 *
 * Behaviour spec:
 *   1. Request browser geolocation with a 4s timeout. Whether it
 *      resolves or times out, POST proceeds (with coords when
 *      available, without when not).
 *   2. Success → green sonner toast with the ETA when returned.
 *   3. Guard-hit response (``{sent:false, reason}``) → yellow toast
 *      with humanized reason.
 *   4. Error → red toast.
 *   5. 10-second local disable after any completed request to
 *      backstop the server-side once-per-job-per-day guard against
 *      double-tap spam.
 */
import React, { useState, useCallback, useRef } from "react";
import { Send } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/api";
import { useAuth } from "@/auth";


const _ALLOWED_ROLES = new Set([
  "technician", "manager", "admin", "super_admin",
]);


function _humanizeReason(reason) {
  switch (reason) {
    case "already_sent_today":
      return "Already notified this customer today.";
    case "sms_opt_in_false":
      return "Customer has opted out of SMS.";
    case "customer_blocked":
      return "Customer is blocked / demo — SMS suppressed.";
    case "no_phone":
      return "No phone number on file for this customer.";
    case "outbound_disabled":
      return "Outbound SMS is currently disabled by system config.";
    case "send_failed":
      return "SMS provider rejected the send. Try again in a moment.";
    default:
      return "Could not send 'on my way' message.";
  }
}


function _geolocatePromise() {
  return new Promise((resolve) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      resolve(null);
      return;
    }
    let done = false;
    const timer = setTimeout(() => {
      if (!done) { done = true; resolve(null); }
    }, 4000);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve({
          origin_lat: pos.coords.latitude,
          origin_lng: pos.coords.longitude,
        });
      },
      () => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        resolve(null);
      },
      { enableHighAccuracy: false, timeout: 4000, maximumAge: 60_000 },
    );
  });
}


export default function OnMyWayButton({
  jobId,
  customerFirstName = "",
  variant = "compact",
  className = "",
  disabled: disabledProp = false,
  testId,
}) {
  const { user } = useAuth();
  const role = (user?.role || "").toLowerCase();
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(false);
  const cooldownTimer = useRef(null);

  const send = useCallback(async () => {
    if (busy || cooldown || disabledProp || !jobId) return;
    setBusy(true);
    try {
      const coords = await _geolocatePromise();
      const body = coords || {};
      let resp;
      try {
        resp = await api.post(`/jobs/${jobId}/on-my-way`, body);
      } catch (e) {
        toast.error(e?.message || "Could not reach the server.");
        return;
      }
      if (resp?.sent) {
        const name = customerFirstName ? ` to ${customerFirstName}` : "";
        const eta = resp.eta_minutes
          ? ` — ETA ${resp.eta_minutes} min`
          : "";
        toast.success(`Sent 'on my way'${name}${eta}`);
      } else {
        toast.warning(_humanizeReason(resp?.reason));
      }
    } finally {
      setBusy(false);
      setCooldown(true);
      if (cooldownTimer.current) clearTimeout(cooldownTimer.current);
      cooldownTimer.current = setTimeout(() => setCooldown(false), 10_000);
    }
  }, [busy, cooldown, disabledProp, jobId, customerFirstName]);

  if (!_ALLOWED_ROLES.has(role)) return null;

  const label = busy ? "Sending…" : (cooldown ? "Sent · wait 10s" : "On my way");
  const _tid = testId || `on-my-way-btn-${jobId}`;

  if (variant === "primary") {
    return (
      <button
        type="button"
        onClick={send}
        disabled={busy || cooldown || disabledProp}
        className={`inline-flex items-center justify-center gap-2 h-11 px-4 rounded-xl font-semibold text-white shadow-sm transition disabled:opacity-60 disabled:cursor-not-allowed ${className}`}
        style={{ background: "linear-gradient(135deg,#059669 0%,#047857 100%)" }}
        data-testid={_tid}
        aria-label="Notify next customer that you're on the way"
      >
        <Send size={16} />
        <span>{busy ? "Sending…" : (cooldown ? "Sent — wait 10s" : "On my way — next job")}</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={(e) => { e.stopPropagation(); send(); }}
      disabled={busy || cooldown || disabledProp}
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold transition disabled:opacity-60 disabled:cursor-not-allowed ${className}`}
      // Feb-2026 HOTFIX (live user report) — was light-mint (#ECFDF5)
      // which looked wishy-washy on the schedule card. Now navy-family
      // (tenant --action-onmyway-* tokens) so techs see a strong,
      // dispatch-brand CTA. Contrast: white on #1B1F5C · WCAG AA ok.
      style={{
        backgroundColor: "var(--action-onmyway-bg, #1B1F5C)",
        color:           "var(--action-onmyway-fg, #FFFFFF)",
        border:          "1px solid var(--action-onmyway-border, #1B1F5C)",
      }}
      data-testid={_tid}
      data-action-role="onmyway"
      aria-label={`Send 'on my way' SMS for job ${jobId}`}
      title="Send 'on my way' SMS"
    >
      <Send size={12} />
      <span>{label}</span>
    </button>
  );
}
