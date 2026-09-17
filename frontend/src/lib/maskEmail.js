/**
 * Sep-2026 · Per-tenant DFS creds · client-side email masking helper.
 *
 * Mirrors the backend's ``_mask_login`` (routers/tenant_dataforseo_
 * integration.py) so the UI has consistent masking. The backend
 * response already includes ``login_masked`` — this helper exists
 * for cases where the UI has just captured plaintext locally
 * (e.g. immediately after a Save) and wants to render the masked
 * view without another network round-trip.
 *
 *   "brian@plofv.com"       → "bri***@plofv.com"
 *   "bob@example.com"       → "***@example.com"   (short local part)
 *   "not-an-email"          → "***"
 *   ""                      → "***"
 */
export function maskEmail(email) {
  const s = String(email || "").trim();
  if (!s || !s.includes("@")) return "***";
  const [local, ...rest] = s.split("@");
  const domain = rest.join("@");
  if (!domain) return "***";
  if (local.length <= 3) return `***@${domain}`;
  return `${local.slice(0, 3)}***@${domain}`;
}
