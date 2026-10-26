/**
 * Lead Profile parity (web Z1 · LeadProfile.jsx `_pickRequestedService`).
 * Picks the "requested service" free text from GET /leads/{id}/raw-submission
 * (`values` is BE-normalised from answers / values / data). Same key ladder as web.
 */
export const REQUESTED_SERVICE_KEYS = [
  "services_requested", "service_requested", "requested_service",
  "service", "services", "service_type", "message", "inquiry",
  "description", "notes", "comments",
];

export function pickRequestedService(rawSubmission: any): string {
  const values = rawSubmission?.values || {};
  for (const k of REQUESTED_SERVICE_KEYS) {
    const v = values[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  // Rare path (web parity): surface every string value so the operator can read it.
  return Object.entries(values)
    .filter(([, v]) => typeof v === "string" && (v as string).trim())
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");
}
