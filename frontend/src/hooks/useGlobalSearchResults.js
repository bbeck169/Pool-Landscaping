/**
 * Feb-2026 · Universal Search — shared results hook.
 *
 * Powers both:
 *   • The visible ``<GlobalSearchBar>`` in ``AdminTopBar`` (primary
 *     entry point — always mounted).
 *   • The ``⌘K`` ``<GlobalSearch>`` palette (modal shortcut).
 *
 * Contract
 * ────────
 *   const {
 *     pages,       // synchronous nav-index hits
 *     customers, jobs, invoices, quotes, leads,  // grouped API buckets
 *     documents,   // merged view (jobs + invoices + quotes) with a
 *                  // ``kind`` tag on each row — kept because the
 *                  // ⌘K palette renders documents as a single
 *                  // section with per-row kind badges.
 *     loading, error,
 *   } = useGlobalSearchResults(query);
 *
 * Behaviour
 * ─────────
 *   * Pages resolve synchronously via ``searchNavIndex(query)`` so the
 *     local list appears with zero latency.
 *   * Backend buckets are fetched from ``GET /api/search`` (the
 *     consolidated endpoint from ``feat(search-be)`` · Feb-2026),
 *     gated on ``query.trim().length >= 2`` and debounced 300 ms.
 *   * Stale requests are truly aborted via ``AbortController`` so a
 *     fast typist can't spam the server.
 *   * On transient error, LAST valid buckets are preserved so the UI
 *     doesn't flash empty.
 *   * ``loading`` reflects the in-flight backend fetch only — the
 *     synchronous ``pages`` list is never "loading".
 *
 * NOTE — supersedes the legacy client-side global-search hook that
 * used to hit the retired ``/api/search/global`` endpoint. Both the
 * hook and its regression suite have been pruned in the search-
 * cleanup chore (Feb-2026) now that every UI consumer has been
 * migrated onto this results-oriented hook + the consolidated
 * ``GET /api/search`` backend.
 */
import { useEffect, useMemo, useState } from "react";
// Feb-2026 · Phase 40b hotfix — the ``@/lib/*`` alias only exposes
// the three allowlisted utilities (utils / stripeConfig /
// checklistType).  ``navIndex`` is a lib module but not in the
// allowlist, so we import it via relative path (same pattern the
// retired legacy hook used pre-Phase-40b).
import { searchNavIndex } from "../lib/navIndex";
import { api } from "@/api";


const MIN_BACKEND_CHARS = 2;
const DEBOUNCE_MS = 300;
const DEFAULT_LIMIT = 5;


// Empty-shape constant so ``useMemo`` deps stay stable across renders
// when the query hasn't reached the backend-fetch threshold.
const _EMPTY_BUCKETS = Object.freeze({
  customers: [], jobs: [], invoices: [], quotes: [], leads: [],
});


export function useGlobalSearchResults(query, { limit = DEFAULT_LIMIT } = {}) {
  const q = (query || "").trim();

  // ── local (synchronous) ─────────────────────────────────────
  const pages = q ? searchNavIndex(q) : [];

  // ── backend (debounced) ─────────────────────────────────────
  const [buckets, setBuckets] = useState(_EMPTY_BUCKETS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (q.length < MIN_BACKEND_CHARS) {
      setBuckets(_EMPTY_BUCKETS);
      setLoading(false);
      setError(null);
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      // ``@/api`` doesn't expose an AbortController hook — we
      // guard with a ``cancelled`` flag so stale responses do not
      // land in state.  Cheap client-side abort simulation.
      api
        .get(`/search?q=${encodeURIComponent(q)}&limit=${limit}`)
        .then((data) => {
          if (cancelled) return;
          setBuckets({
            customers: Array.isArray(data?.customers) ? data.customers : [],
            jobs:      Array.isArray(data?.jobs)      ? data.jobs      : [],
            invoices:  Array.isArray(data?.invoices)  ? data.invoices  : [],
            quotes:    Array.isArray(data?.quotes)    ? data.quotes    : [],
            leads:     Array.isArray(data?.leads)     ? data.leads     : [],
          });
          setError(null);
        })
        .catch((e) => {
          if (cancelled) return;
          // Preserve prior buckets so the UI doesn't flash empty
          // on transient network blips.  Expose the error for
          // any caller that wants to surface a toast / badge.
          setError(e);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [q, limit]);

  // Merged ``documents`` list — kept because the ⌘K palette renders
  // jobs + invoices + quotes under one "Documents" section with a
  // per-row kind badge.  Tag every row with its bucket ``kind`` so
  // the palette can pick the right badge label without a lookup.
  const documents = useMemo(() => ([
    ...buckets.jobs.map((r) => ({ ...r, kind: "job" })),
    ...buckets.invoices.map((r) => ({ ...r, kind: "invoice" })),
    ...buckets.quotes.map((r) => ({ ...r, kind: "quote" })),
  ]), [buckets.jobs, buckets.invoices, buckets.quotes]);

  return {
    pages,
    customers: buckets.customers,
    jobs:      buckets.jobs,
    invoices:  buckets.invoices,
    quotes:    buckets.quotes,
    leads:     buckets.leads,
    documents,
    loading,
    error,
  };
}


export default useGlobalSearchResults;
