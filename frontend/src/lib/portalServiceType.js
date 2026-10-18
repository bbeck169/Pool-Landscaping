/**
 * TD-69 · Feb-2026 — Portal / Workstream shared service-type
 * resolver.
 *
 * Pre-TD-69 the portal service-reports surface had its own inline
 * ``reportKind()`` in ``pages/portal/PortalServiceReports.jsx``
 * that read ``template || service_type || job.service_type`` as
 * an OR-chain and categorised via ``.includes()`` substring
 * matching. Operator reported two landscape customers (Frances
 * LaPrairie + Amy Hinojosa) seeing a "Pool service" badge on
 * their landscape SRs — the first-truthy-wins OR-chain made the
 * resolver fragile against data drift: if ``template`` was set
 * to a pool-ish value on the SR while ``job.service_type`` was
 * the authoritative "Landscaping", the pool branch fired first
 * because it never consulted the job-level service type at all.
 *
 * This helper fixes the ordering bug and is the single resolver
 * Portal + (future) Workstream consume so a landscape-tagged job
 * NEVER renders a pool badge regardless of which field happens
 * to be populated.
 *
 * Contract — ``resolveServiceType(record) → "pool" | "landscape" | "generic"``:
 *   * SCANS every candidate field (``template``, ``service_type``,
 *     ``job.service_type``, ``service_line``) rather than
 *     stopping at the first truthy one.
 *   * LANDSCAPE PRIORITY — if ANY field matches a landscape
 *     signal (``landscap`` / ``mow`` / ``lawn`` / ``yard`` /
 *     ``garden``), the record is landscape. This guards against
 *     data-drift where a landscape job has a stray pool-ish
 *     string in one of its service-type fields.
 *   * POOL FALLBACK — if no landscape signal AND any field
 *     matches ``pool`` / ``chem`` / ``spa`` / ``water``, the
 *     record is pool. ``water`` is included because the
 *     Workstream service-line field uses "pool" literal while
 *     the SR template field occasionally carries "water_care".
 *   * GENERIC — neither signal matched. Portal renders a neutral
 *     "Service" label; chemistry section stays HIDDEN (same as
 *     landscape — only explicit pool kind reveals chemistry).
 *
 * Case-insensitive, null-safe, type-tolerant (coerces non-string
 * inputs to string before scanning).
 */

// Signals ordered so landscape ALWAYS wins over pool when both
// substrings exist in the same field (rare data-drift case but
// the operator-reported symptom).
const LANDSCAPE_SIGNALS = ["landscap", "mow", "lawn", "yard", "garden"];
const POOL_SIGNALS      = ["pool", "chem", "spa", "water"];

function _hasAny(haystack, signals) {
  for (const s of signals) {
    if (haystack.includes(s)) return true;
  }
  return false;
}

/**
 * Resolve a record (service report or job) to a canonical
 * service-kind.
 *
 * @param {object} record — may expose any subset of
 *   ``template`` / ``service_type`` / ``service_line`` /
 *   ``service_category`` / ``job.service_type``. Missing or
 *   null fields are skipped.
 * @returns {"pool" | "landscape" | "generic"}
 */
export function resolveServiceType(record) {
  if (!record || typeof record !== "object") return "generic";
  const parts = [];
  const push = (v) => {
    if (v == null) return;
    const s = String(v).toLowerCase().trim();
    if (s) parts.push(s);
  };
  push(record.template);
  push(record.service_type);
  push(record.service_line);
  push(record.service_category);
  if (record.job && typeof record.job === "object") {
    push(record.job.service_type);
    push(record.job.service_line);
    push(record.job.service_category);
  }
  const scanned = parts.join(" ");
  if (!scanned) return "generic";
  if (_hasAny(scanned, LANDSCAPE_SIGNALS)) return "landscape";
  if (_hasAny(scanned, POOL_SIGNALS))      return "pool";
  return "generic";
}

export default resolveServiceType;
