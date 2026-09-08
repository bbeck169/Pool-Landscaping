/**
 * Feb-2026 · Notifications filter dropdown — grouping catalog.
 *
 * The bell-notification catalog carries ~48 distinct ``kind`` values.
 * Rendered as a chip wall the page was a visual bomb (~10 rows).
 * This module carves the catalog into 7 semantic sections so the new
 * dropdown popover can render clean group headers.
 *
 * Contract:
 *   * Input: the raw ``[{key, label}]`` list returned by
 *     ``GET /api/notifications/kinds``.
 *   * Output: ordered ``[{section, items}]`` where ``items`` preserves
 *     server order within each section.
 *   * Any ``kind`` key not mapped to a section lands in a final
 *     ``"Other"`` bucket — new kinds ship immediately without a code
 *     change here, and can be re-homed later once we settle on a
 *     canonical section.
 */

// Ordered — section-header order in the dropdown UI. Keep semantic
// clusters that a support/ops user would scan for in a hurry.
export const SECTION_ORDER = [
  "RingCentral",
  "Jobs",
  "Invoices & Payments",
  "Team & Chat",
  "Customers & Portal",
  "Sales & Marketing",
  "System & Inventory",
  "Other",
];

// Mapping from a notification ``kind`` (backend key) → section header.
// Keep this list flat + explicit so grep-by-kind stays trivial.
export const KIND_TO_SECTION = {
  // RingCentral (8)
  rc_sms_inbound: "RingCentral",
  rc_call_inbound: "RingCentral",
  rc_voicemail: "RingCentral",
  rc_fax: "RingCentral",
  rc_sms_inbound_unmatched: "RingCentral",
  rc_call_inbound_unmatched: "RingCentral",
  rc_voicemail_unmatched: "RingCentral",
  rc_fax_unmatched: "RingCentral",
  // Jobs (8)
  job_assigned: "Jobs",
  job_completed: "Jobs",
  job_cancelled: "Jobs",
  job_status_change: "Jobs",
  dispatch_alert: "Jobs",
  autosave_conflict: "Jobs",
  route_optimization_request: "Jobs",
  task_assigned: "Jobs",
  // Invoices & Payments (5)
  invoice_paid: "Invoices & Payments",
  invoice_overdue: "Invoices & Payments",
  payment_received: "Invoices & Payments",
  payment_failed: "Invoices & Payments",
  payment_refunded: "Invoices & Payments",
  // Team & Chat (6)
  tech_message: "Team & Chat",
  tech_note: "Team & Chat",
  chat_dm: "Team & Chat",
  chat_dm_to_admin: "Team & Chat",
  chat_mention_in_channel: "Team & Chat",
  chat_message_in_channel: "Team & Chat",
  // Customers & Portal (5)
  customer_message: "Customers & Portal",
  inbound_customer_message: "Customers & Portal",
  inbound_customer_message_assigned: "Customers & Portal",
  customer_created: "Customers & Portal",
  "customer.vip_flagged": "Customers & Portal",
  // Sales & Marketing (10)
  lead_new: "Sales & Marketing",
  new_lead: "Sales & Marketing",
  subscriber_confirmed: "Sales & Marketing",
  marketing_import_complete: "Sales & Marketing",
  marketing_campaign_sent: "Sales & Marketing",
  review_received: "Sales & Marketing",
  review_low_star: "Sales & Marketing",
  deal_created: "Sales & Marketing",
  deal_won: "Sales & Marketing",
  deal_lost: "Sales & Marketing",
  directory_status_change: "Sales & Marketing",
  // System & Inventory (5)
  automation_error: "System & Inventory",
  system_alert: "System & Inventory",
  "property.created": "System & Inventory",
  "property.deleted": "System & Inventory",
  inventory_low_stock: "System & Inventory",
};

/**
 * Group a raw kinds catalog into ordered sections.
 *
 * @param {Array<{key: string, label: string}>} kinds
 * @returns {Array<{section: string, items: Array<{key:string,label:string}>}>}
 */
export function groupKinds(kinds) {
  if (!Array.isArray(kinds) || kinds.length === 0) return [];
  const bySection = {};
  for (const k of kinds) {
    const section = KIND_TO_SECTION[k.key] || "Other";
    if (!bySection[section]) bySection[section] = [];
    bySection[section].push(k);
  }
  return SECTION_ORDER
    .filter((s) => bySection[s] && bySection[s].length > 0)
    .map((s) => ({ section: s, items: bySection[s] }));
}
