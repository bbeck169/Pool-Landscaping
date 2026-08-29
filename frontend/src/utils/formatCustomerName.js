/**
 * Feb-2026 · Customer Delete UX overhaul — orphan-safe customer
 * name renderer.
 *
 * Every list/detail surface that renders a child row's
 * ``customer_name`` (snapshotted at creation) MUST funnel through
 * this helper so a hard-deleted customer never leaks as a blank /
 * "—" cell. Reads that survive a hard-delete keep the snapshot
 * intact; this helper only kicks in on the (rare) rows where the
 * snapshot was never populated or was cleared post-hoc (e.g. via
 * a manual DB migration or a legacy pre-Feb-2026 row).
 *
 * Contract:
 *   * Non-blank snapshot                        → return as-is.
 *   * Object shape ({customer_name})            → read the field.
 *   * Falsy / blank / whitespace-only           → "Unknown Customer".
 *
 * Deliberately does NOT try to hit ``/customers/{id}`` to look up a
 * live name — the row is already orphaned; a network round-trip
 * for every render would be wasteful and often 404 anyway.
 *
 * Test IDs: consumers should keep their existing testid on the
 * cell/element; this helper only touches the visible text.
 */

// Exported for direct unit-testing without importing the whole
// UI-kit chain of dependencies.
export const UNKNOWN_CUSTOMER_LABEL = "Unknown Customer";

/**
 * @param {string | { customer_name?: string } | null | undefined} rowOrName
 *        Either a snapshotted name string OR the row itself (job,
 *        invoice, quote, service report, CSAT survey, etc.). Object
 *        input is the primary use — one call site per list cell.
 * @returns {string} A non-empty display string.
 */
export function formatCustomerName(rowOrName) {
  const raw =
    typeof rowOrName === "string"
      ? rowOrName
      : (rowOrName && rowOrName.customer_name) || "";
  const trimmed = String(raw || "").trim();
  if (!trimmed) return UNKNOWN_CUSTOMER_LABEL;
  return trimmed;
}

export default formatCustomerName;
