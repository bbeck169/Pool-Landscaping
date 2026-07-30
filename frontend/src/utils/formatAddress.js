// Feb-2026 · P0 fix — address value formatter for React render sites.
//
// Backend endpoints occasionally return an OBJECT for a customer /
// job address (fields `{street, city, state, postal_code}`) — most
// notably for CSV-imported customers whose `service_address` was
// persisted as a nested block by `services/customer_import.py`.
// Rendering that object directly in JSX crashes with React error #31:
// "Objects are not valid as a React child".
//
// This helper is the single place we defensively coerce those values
// to a display string. Keep it dependency-free and side-effect-free so
// it can be pulled into any component (including Google Maps
// InfoWindows) without breaking Vitest / SSR / jsdom.
//
// Contract:
//   • string in  →  string out (trimmed)
//   • null / undefined  →  "" (falsy — callers can then decide
//     whether to render a "No address" fallback)
//   • plain object in →  best-effort formatted string using the
//     documented shape (`formatted` wins if present, otherwise
//     line1/street + city + state + postal_code + country)
//   • anything else (numbers, arrays) →  String(value) fallback
//
// Do NOT change API response shapes on the backend from here — this
// is strictly a frontend render-site safety net.

const ADDRESS_KEYS = [
  "line1", "address_line1", "street", "street_address",
  "city",
  "state", "region",
  "postal_code", "postcode", "zip",
  "country",
];

export function formatAddress(value) {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(formatAddress).filter(Boolean).join(", ");
  }
  if (typeof value !== "object") return String(value);

  // Preferred: pre-formatted string from the reverse-geocoder cache.
  if (typeof value.formatted === "string" && value.formatted.trim()) {
    return value.formatted.trim();
  }
  if (typeof value.display === "string" && value.display.trim()) {
    return value.display.trim();
  }

  // Otherwise, assemble from the documented field set. We de-dupe
  // adjacent equal parts so "PHOENIX, PHOENIX, AZ" collapses cleanly.
  const parts = [];
  const seen = new Set();
  for (const key of ADDRESS_KEYS) {
    const raw = value[key];
    if (raw == null) continue;
    const str = String(raw).trim();
    if (!str) continue;
    const norm = str.toLowerCase();
    if (seen.has(norm)) continue;
    seen.add(norm);
    parts.push(str);
  }
  return parts.join(", ");
}

export default formatAddress;
