/**
 * TD-90 · mobile global search — mirror of web
 * `frontend/src/hooks/useGlobalSearchResults.js`.
 *
 *   GET /api/search?q=<q>&limit=5 → { customers, jobs, invoices, quotes, leads }
 *   each row `{ id, primary, secondary }` (BE `routers/global_search.py`).
 *
 * Same rules as web: fetch only when `q.trim().length >= 2`, debounced
 * 300 ms, stale responses dropped, and on error the LAST buckets are kept
 * (no empty flash) while `error` is raised for the muted inline line.
 * Role gate (G1): the BE allows admin / super_admin / owner / manager
 * only (`_require_dashboard_role`); every other role never fetches and
 * keeps the tools-only search. Tenant scoping is server-side (JWT tenant)
 * — mobile sends no tenant hint.
 */
import { useEffect, useState } from "react";
import { api } from "@/src/api";

export const GLOBAL_SEARCH_MIN_CHARS = 2;
export const GLOBAL_SEARCH_DEBOUNCE_MS = 300;
export const GLOBAL_SEARCH_LIMIT = 5;
export const GLOBAL_SEARCH_ROLES = ["admin", "super_admin", "owner", "manager"];

export type SearchHit = { id: string; primary: string; secondary?: string };
export type SearchBuckets = {
  customers: SearchHit[]; jobs: SearchHit[]; invoices: SearchHit[]; quotes: SearchHit[]; leads: SearchHit[];
};
export const EMPTY_SEARCH_BUCKETS: SearchBuckets = Object.freeze({
  customers: [], jobs: [], invoices: [], quotes: [], leads: [],
}) as SearchBuckets;

export function canGlobalSearch(role?: string | null): boolean {
  return GLOBAL_SEARCH_ROLES.includes(String(role || ""));
}

const arr = (v: any): SearchHit[] => (Array.isArray(v) ? v.filter((r) => r && r.id) : []);

export function useGlobalSearch(query: string, role?: string | null) {
  const q = (query || "").trim();
  const active = canGlobalSearch(role) && q.length >= GLOBAL_SEARCH_MIN_CHARS;
  const [buckets, setBuckets] = useState<SearchBuckets>(EMPTY_SEARCH_BUCKETS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!active) {
      setBuckets(EMPTY_SEARCH_BUCKETS);
      setLoading(false);
      setError(false);
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      api.get(`/search?q=${encodeURIComponent(q)}&limit=${GLOBAL_SEARCH_LIMIT}`)
        .then((d: any) => {
          if (cancelled) return;
          setBuckets({
            customers: arr(d?.customers), jobs: arr(d?.jobs), invoices: arr(d?.invoices),
            quotes: arr(d?.quotes), leads: arr(d?.leads),
          });
          setError(false);
        })
        .catch(() => { if (!cancelled) setError(true); })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, GLOBAL_SEARCH_DEBOUNCE_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [q, active]);

  const total = buckets.customers.length + buckets.jobs.length + buckets.invoices.length
    + buckets.quotes.length + buckets.leads.length;
  return { active, buckets, loading, error, total };
}
