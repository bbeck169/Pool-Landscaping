/**
 * TD-90 · global-search result groups (web `GlobalSearchBar` order) and
 * kind → mobile route map. Invoices AND quotes open `/quote/[id]` (the
 * staff doc viewer that branches on `doc_type`, same target as the
 * staff invoice list + TD-79) — `/invoice/[id]` is the customer-portal
 * viewer and must not be used here.
 */
import type { SearchBuckets } from "@/src/hooks/useGlobalSearch";

export type SearchKind = "customer" | "job" | "invoice" | "quote" | "lead";

export const GLOBAL_SEARCH_GROUPS: { key: keyof SearchBuckets; kind: SearchKind; label: string; icon: string }[] = [
  { key: "customers", kind: "customer", label: "Customers", icon: "people-outline" },
  { key: "jobs", kind: "job", label: "Jobs", icon: "briefcase-outline" },
  { key: "invoices", kind: "invoice", label: "Invoices", icon: "receipt-outline" },
  { key: "quotes", kind: "quote", label: "Quotes", icon: "document-text-outline" },
  { key: "leads", kind: "lead", label: "Leads", icon: "person-add-outline" },
];

export function routeForSearchHit(kind: SearchKind, id?: string | null): string | null {
  if (!id) return null;
  const e = encodeURIComponent(id);
  switch (kind) {
    case "customer": return `/customer/${e}`;
    case "job": return `/job/${e}`;
    case "invoice":
    case "quote": return `/quote/${e}`;
    case "lead": return `/leads/${e}`;
    default: return null;
  }
}
