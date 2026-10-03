/**
 * Convert-to-Invoice utilities — mobile parity for web f5dd1eb0a.
 *
 * Shared role-gate predicate and conversion handler for both
 * quote and estimate detail screens.
 */

const CONVERT_ROLES = new Set(["admin", "super_admin", "owner", "manager"]);

/**
 * Returns true for roles permitted to convert quotes/estimates to invoices.
 * Case-insensitive. Returns false for technician/customer/dispatcher/null.
 */
export function canUserConvertToInvoice(role: string | null | undefined): boolean {
  if (!role) return false;
  return CONVERT_ROLES.has(role.toLowerCase());
}
