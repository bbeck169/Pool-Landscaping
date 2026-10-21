/**
 * TD-81 · shared K48 lock flags + Atomic A2 role shim (TD-84-ready).
 * Web parity: DashboardDrillDownModal.jsx `_k48StatusFlags`,
 * `resolveInitialBuId`, `commitBusinessUnit` patch body.
 */
import { buildBusinessUnitPatch, resolveBusinessUnitId, k48StatusFlags, canBypassCategoryConfirm } from "@/src/lib/k48";

const CATS = [{ id: "c-pool", name: "Pool" }, { id: "c-land", name: "Landscaping" }];

it("privileged roles → minimal body + A2 bypass; never line_items", () => {
  for (const role of ["admin", "super_admin", "manager", "owner", "ADMIN"]) {
    expect(buildBusinessUnitPatch(role, { invoice_status: "paid" }, CATS[0])).toEqual({ business_unit: "Pool", business_unit_id: "c-pool", confirm_edit_sent: true, acknowledged_lock_bypass: true });
  }
  expect(canBypassCategoryConfirm("technician")).toBe(false);
  expect(canBypassCategoryConfirm(undefined)).toBe(false);
});

it("non-privileged → only the flags the status needs (sent / paid / draft); terminal flags", () => {
  expect(buildBusinessUnitPatch("technician", { invoice_status: "sent" }, CATS[0])).toEqual({ business_unit: "Pool", business_unit_id: "c-pool", confirm_edit_sent: true });
  expect(buildBusinessUnitPatch("technician", { payment_status: "partially_paid", invoice_number: "INV-9" }, CATS[0])).toEqual({ business_unit: "Pool", business_unit_id: "c-pool", confirm_edit_paid_invoice_number: "INV-9" });
  expect(buildBusinessUnitPatch(null, { invoice_status: "draft" }, CATS[0])).toEqual({ business_unit: "Pool", business_unit_id: "c-pool" });
  expect(k48StatusFlags({ invoice_status: "void" }).isTerminal).toBe(true);
  expect(k48StatusFlags({ payment_status: "cancelled" }).isTerminal).toBe(true);
  expect(k48StatusFlags({ invoice_status: "paid" })).toEqual({ isTerminal: false, needsSentConfirm: false, needsPaidConfirm: true });
});

it("resolveBusinessUnitId: business_unit name → income_category_id → category name", () => {
  expect(resolveBusinessUnitId({ business_unit: "landscaping", income_category_id: "c-pool" }, CATS)).toBe("c-land");
  expect(resolveBusinessUnitId({ income_category_id: "c-x", category: "Pool" }, CATS)).toBe("c-x");
  expect(resolveBusinessUnitId({ category: " POOL " }, CATS)).toBe("c-pool");
  expect(resolveBusinessUnitId({ category: "Uncategorized" }, CATS)).toBe("");
});
