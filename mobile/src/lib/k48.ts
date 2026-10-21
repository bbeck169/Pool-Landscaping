/**
 * TD-81 · K48 lock flags + Atomic A2 role shim for invoice Business Unit
 * re-classification. Pure helpers, 1:1 with web
 * `DashboardDrillDownModal.jsx` (`_k48StatusFlags`, `resolveInitialBuId`,
 * `commitBusinessUnit` patch body). Shared so the TD-84 "Uncategorized"
 * surface can reuse them later (TD-84-ready, no TD-84 code here).
 */

const K48_TERMINAL_STATUSES = new Set(["void", "cancelled"]);
const K48_CONFIRM_SENT_STATUSES = new Set(["sent"]);
const K48_CONFIRM_PAID_STATUSES = new Set(["paid", "partially_paid", "refunded"]);

/** Web A2: privileged roles auto-carry the sent/paid lock bypass on BU edits. */
export const A2_PRIVILEGED_ROLES = ["admin", "super_admin", "manager", "owner"];

export type K48Flags = { isTerminal: boolean; needsSentConfirm: boolean; needsPaidConfirm: boolean };
export type IncomeCategory = { id: string; name: string };

export function k48StatusFlags(row: any): K48Flags {
  const s = String(row?.invoice_status || "").toLowerCase();
  const p = String(row?.payment_status || "").toLowerCase();
  const any = (set: Set<string>) => set.has(s) || set.has(p);
  return {
    isTerminal: any(K48_TERMINAL_STATUSES),
    needsSentConfirm: any(K48_CONFIRM_SENT_STATUSES),
    needsPaidConfirm: any(K48_CONFIRM_PAID_STATUSES),
  };
}

export function canBypassCategoryConfirm(role?: string | null): boolean {
  return A2_PRIVILEGED_ROLES.includes(String(role || "").toLowerCase());
}

const lc = (v: any) => String(v || "").trim().toLowerCase();

/** Current BU id: invoice `business_unit` name → `income_category_id` → `category` name match. */
export function resolveBusinessUnitId(row: any, cats: IncomeCategory[]): string {
  const bu = lc(row?.business_unit);
  if (bu) {
    const hit = cats.find((c) => lc(c?.name) === bu);
    if (hit) return hit.id;
  }
  const direct = String(row?.income_category_id || "").trim();
  if (direct) return direct;
  const nm = lc(row?.category);
  if (!nm) return "";
  const hit = cats.find((c) => lc(c?.name) === nm);
  return hit ? hit.id : "";
}

/**
 * Minimal BU-only PATCH body for `PATCH /quotes/{invoice_id}` (K48
 * verify-hotfix: never include `line_items`). Privileged roles bypass the
 * lock; others carry only the flags their invoice status requires.
 */
export function buildBusinessUnitPatch(role: string | null | undefined, row: any, cat: IncomeCategory): Record<string, any> {
  const body: Record<string, any> = { business_unit: cat.name, business_unit_id: cat.id };
  if (canBypassCategoryConfirm(role)) {
    body.confirm_edit_sent = true;
    body.acknowledged_lock_bypass = true;
    return body;
  }
  const f = k48StatusFlags(row);
  if (f.needsSentConfirm) body.confirm_edit_sent = true;
  if (f.needsPaidConfirm) body.confirm_edit_paid_invoice_number = row?.invoice_number || "";
  return body;
}
