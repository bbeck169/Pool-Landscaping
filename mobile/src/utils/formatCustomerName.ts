/**
 * Orphan-safe customer name renderer.
 *
 * Every surface that renders a child row's `customer_name` (snapshotted
 * at creation time) MUST funnel through this helper so a hard-deleted
 * customer never leaks as a blank / "—" cell.
 *
 * Contract:
 *   • Non-blank string               → return as-is.
 *   • Object shape ({ customer_name }) → read the field.
 *   • Falsy / blank / whitespace-only → "Unknown Customer".
 *
 * Port of /frontend/src/utils/formatCustomerName.js
 */

export const UNKNOWN_CUSTOMER_LABEL = "Unknown Customer";

/**
 * @param rowOrName  Either a snapshotted name string OR the row object
 *                   (job, invoice, quote, service report, etc.).
 * @returns A non-empty display string.
 */
export function formatCustomerName(
  rowOrName: string | { customer_name?: string } | null | undefined,
): string {
  const raw =
    typeof rowOrName === "string"
      ? rowOrName
      : (rowOrName && rowOrName.customer_name) || "";
  const trimmed = String(raw || "").trim();
  if (!trimmed) return UNKNOWN_CUSTOMER_LABEL;
  return trimmed;
}

export default formatCustomerName;
