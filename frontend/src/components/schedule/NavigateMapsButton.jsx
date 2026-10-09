/**
 * Phase 3b · Feb-2026 — "Navigate" button on the schedule job card.
 *
 * Pill-shaped orange affordance that sits next to the sibling
 * action buttons (``<OnMyWayButton>`` and the "Could not service"
 * button) on each schedule job card.  Click opens Google Maps in a
 * new tab with the job's destination pre-filled; the user's
 * current location is used as the implicit origin via Google
 * Maps' default behavior.
 *
 * Addressing priority (frontend-only — no backend change):
 *   1. ``job.service_address`` — job-level override.  Non-empty
 *      string wins over the customer's primary address.
 *   2. ``job.address`` — resolved server-side as
 *      ``job.address || job.site_address`` by the schedule / jobs
 *      serializers.  For the Phase 3b data shape this value is
 *      effectively ``customer.address`` when the job carries no
 *      override of its own, since the backend does not surface a
 *      distinct ``customer_address`` field on either endpoint.
 *   3. Neither present → button is DISABLED (opacity-50,
 *      cursor-not-allowed, no click handler, tooltip surfaces
 *      "No address on file").
 *
 * Sibling-button parity:
 *   padding / radius / font / size exactly match the "Could not
 *   service" button in ``CalendarSchedule.jsx`` so the three
 *   buttons wrap as a visually coherent row.
 *
 * Scope note:
 *   This component is intentionally FRONTEND-WEB-ONLY per the
 *   Phase 3b brief.  A mobile mirror (same orange, same icon,
 *   same addressing priority) is batched into the separate Expo
 *   delegation ticket — do NOT touch ``/app/mobile`` from here.
 */
import React from "react";
import { Navigation } from "lucide-react";


export function _resolveAddress(job) {
  if (!job || typeof job !== "object") return "";
  const svc = typeof job.service_address === "string"
                ? job.service_address.trim() : "";
  if (svc) return svc;
  const addr = typeof job.address === "string"
                ? job.address.trim() : "";
  if (addr) return addr;
  return "";
}


export function _buildMapsUrl(address) {
  if (!address) return null;
  const q = new URLSearchParams();
  q.set("api", "1");
  q.set("destination", address);
  return `https://www.google.com/maps/dir/?${q.toString()}`;
}


export default function NavigateMapsButton({ job }) {
  const address  = _resolveAddress(job);
  const disabled = !address;
  const url      = _buildMapsUrl(address);
  const label    = disabled
    ? "No address on file"
    : `Navigate to ${job?.customer_name || "customer"}`;

  const onClick = (e) => {
    // Don't bubble to the card-level onClick (which opens the job
    // detail page) — the Navigate CTA is a sibling action, not a
    // card tap.
    e.stopPropagation();
    if (disabled) return;
    // ``noopener,noreferrer`` prevents ``window.opener`` leaks on
    // the newly opened tab.
    window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      aria-disabled={disabled}
      title={label}
      aria-label={label}
      data-testid={`schedule-card-navigate-${job?.id ?? "unknown"}`}
      data-action-role="navigate"
      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold hover:bg-orange-600"
      style={{
        backgroundColor: "#F97316",             // Tailwind orange-500
        color:           "#FFFFFF",
        border:          "1px solid #EA580C",   // Tailwind orange-600
        opacity:         disabled ? 0.5 : 1,
        cursor:          disabled ? "not-allowed" : "pointer",
      }}
    >
      <Navigation size={11} />
      Navigate
    </button>
  );
}
