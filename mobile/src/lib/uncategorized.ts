/**
 * TD-84 b2 · pure helpers for the Uncategorized line-items report (web
 * pages/reports/UncategorizedItemsReport.jsx + Dashboard banner parity).
 */
export type Taxonomy = "income" | "service";
export type CategoryRef = { id: string; name: string; is_archived?: boolean };
export type UncatRow = {
  invoice_id: string; line_item_index: number; invoice_number?: string; customer_name?: string;
  created_at?: string; description?: string; amount?: number;
  income_category_id?: string; income_category_name?: string;
  service_category_id?: string; service_category_name?: string;
  missing_income?: boolean; missing_service?: boolean;
};

// Web RANGE_OPTIONS minus "custom" (needs a date-range picker; deferred).
export const RANGE_OPTIONS = [
  { key: "all", label: "All Time" }, { key: "this_month", label: "This Month" },
  { key: "last_month", label: "Last Month" }, { key: "this_quarter", label: "This Quarter" },
] as const;
export const MISSING_OPTIONS = [
  { key: "income", label: "Income" }, { key: "service", label: "Service" },
  { key: "either", label: "Either" }, { key: "both", label: "Both" },
] as const;
export type RangeKey = (typeof RANGE_OPTIONS)[number]["key"];
export type MissingKey = (typeof MISSING_OPTIONS)[number]["key"];

/** Backend cap: 200 rows per bulk-assign call. */
export const BULK_ASSIGN_CAP = 200;

export const rowKey = (r: Pick<UncatRow, "invoice_id" | "line_item_index">) => `${r.invoice_id}::${r.line_item_index}`;

export function keyToItem(k: string) {
  const i = k.lastIndexOf("::");
  return { invoice_id: k.slice(0, i), line_item_index: Number(k.slice(i + 2)) };
}

/** Web grammar hotfix parity: "1 line item is" / "N line items are". */
export const bannerText = (count: number) =>
  `${count} line item${count === 1 ? "" : "s"} ${count === 1 ? "is" : "are"} uncategorized.`;

export function applyAssign(row: UncatRow, field: Taxonomy, cat: CategoryRef): UncatRow {
  return field === "income"
    ? { ...row, income_category_id: cat.id, income_category_name: cat.name, missing_income: false }
    : { ...row, service_category_id: cat.id, service_category_name: cat.name, missing_service: false };
}

export function assignToast(row: UncatRow, field: Taxonomy, name: string) {
  const stillMissing = field === "income" ? row.missing_service : row.missing_income;
  const other = field === "income" ? "Service" : "Income";
  return `Categorized as ${name}` + (stillMissing ? ` · still missing ${other} category` : " · row fully categorized");
}

export function chunk<T>(arr: T[], size: number = BULK_ASSIGN_CAP): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}

export const bulkToast = (assigned: number, failed: number, field: Taxonomy, name: string) =>
  `Bulk-assigned ${assigned} row${assigned === 1 ? "" : "s"} — ${field} = ${name}` + (failed ? ` · ${failed} failed` : "");

export const assignPath = (r: UncatRow) =>
  `/reports/uncategorized-items/${encodeURIComponent(r.invoice_id)}/${r.line_item_index}/assign`;
export const bodyField = (f: Taxonomy) => (f === "income" ? "income_category_id" : "service_category_id");
