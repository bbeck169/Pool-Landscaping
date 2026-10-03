/**
 * Quote lifecycle utilities — Phase 3 mobile parity for web cfe1a5d41 + 9ec460aa8.
 *
 * Shared role-gate predicates and visibility helpers for Decline / Reopen
 * buttons on the quotes list screen and quote detail screen.
 */

const LIFECYCLE_ROLES = new Set(["admin", "super_admin", "owner", "manager"]);

/**
 * Returns true for roles permitted to decline or reopen quotes.
 * Same role set as canUserConvertToInvoice (admin/super_admin/owner/manager).
 * Case-insensitive. Returns false for technician/customer/dispatcher/null.
 */
export function canUserDeclineOrReopenQuote(role: string | null | undefined): boolean {
  if (!role) return false;
  return LIFECYCLE_ROLES.has(role.toLowerCase());
}

/**
 * Decline button visibility on a quote row or detail.
 * Visible when: quote (not invoice), status in {draft, sent, accepted},
 * not converted, and role-gated.
 */
export function shouldShowDeclineButton({
  isInvoice,
  docStatus,
  convertedInvoiceId,
  canDecline,
}: {
  isInvoice: boolean;
  docStatus: string;
  convertedInvoiceId?: string | null;
  canDecline: boolean;
}): boolean {
  if (isInvoice) return false;
  if (!canDecline) return false;
  if (convertedInvoiceId) return false;
  const s = (docStatus || "").toLowerCase();
  if (s === "declined") return false;
  return ["draft", "sent", "accepted"].includes(s);
}

/**
 * Reopen button visibility on a quote row or detail.
 * Visible when: quote (not invoice), status === "declined", and role-gated.
 */
export function shouldShowReopenButton({
  isInvoice,
  docStatus,
  canReopen,
}: {
  isInvoice: boolean;
  docStatus: string;
  canReopen: boolean;
}): boolean {
  if (isInvoice) return false;
  if (!canReopen) return false;
  return (docStatus || "").toLowerCase() === "declined";
}

/**
 * Phase 3 regression guard: hide Convert-to-Invoice when status === "declined".
 * Mirrors backend guard that returns 400 {code: "quote_declined"}.
 */
export function shouldHideConvertWhenDeclined(docStatus: string): boolean {
  return (docStatus || "").toLowerCase() === "declined";
}
