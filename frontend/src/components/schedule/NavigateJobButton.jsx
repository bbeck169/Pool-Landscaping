/**
 * Feb-2026 · Schedule polish — per-job "Navigate" button.
 *
 * One-tap deep-link that opens Google Maps with the customer's
 * destination pre-filled. Origin is intentionally omitted so
 * Google Maps defaults to the user's current location — which is
 * what techs want.
 *
 * Destination preference:
 *   1. ``latitude,longitude`` when both are finite AND not (0,0).
 *      Coord routing is more accurate than string parsing.
 *   2. Fall back to the job's ``address`` string.
 *   3. Neither available → button is DISABLED with an explanatory
 *      tooltip. We do not silently no-op.
 *
 * Deliberately does NOT read the tech's current location — the
 * <OnMyWayButton> component next door already requests
 * geolocation, and stacking a second permission prompt would be
 * hostile. Google Maps' "current location" auto-fill handles this.
 */
import React from "react";
import { Navigation } from "lucide-react";

export function _resolveDestination(job) {
  if (!job || typeof job !== "object") return null;
  const lat = Number(job.latitude);
  const lng = Number(job.longitude);
  if (
    Number.isFinite(lat) && Number.isFinite(lng)
    && !(lat === 0 && lng === 0)
  ) {
    return { kind: "coords", value: `${lat},${lng}` };
  }
  const addr = (job.address || "").trim();
  if (addr) return { kind: "address", value: addr };
  return null;
}

export function _buildMapsUrl(dest) {
  if (!dest) return null;
  const q = new URLSearchParams();
  q.set("api", "1");
  q.set("destination", dest.value);
  return `https://www.google.com/maps/dir/?${q.toString()}`;
}

export default function NavigateJobButton({ job, size = 16 }) {
  const dest = _resolveDestination(job);
  const url = _buildMapsUrl(dest);
  const disabled = !url;
  const customerName = job?.customer_name || "customer";
  const label = disabled
    ? "No address on file"
    : `Navigate to ${customerName}`;

  const onClick = (e) => {
    // Don't bubble to the card-level onClick (which opens the job).
    e.stopPropagation();
    if (disabled) return;
    // ``noopener,noreferrer`` prevents ``window.opener`` leaks.
    window.open(url, "_blank", "noopener,noreferrer");
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      data-testid={`schedule-job-nav-${job?.id ?? "unknown"}`}
      style={{
        background: "transparent",
        border: 0,
        cursor: disabled ? "not-allowed" : "pointer",
        color: disabled ? "#9CA3AF" : "#2563EB",
        opacity: disabled ? 0.5 : 1,
        padding: "2px 4px",
        display: "inline-flex",
        alignItems: "center",
      }}
    >
      <Navigation size={size} />
    </button>
  );
}
