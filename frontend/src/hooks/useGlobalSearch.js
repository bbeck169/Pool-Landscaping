/**
 * N4' · Feb-2026 — Grouped global-search hook for <PageHeader>.
 *
 * Combines the *local* nav-index search (synchronous, cheap — pages
 * from ``ADMIN_NAV_V2``) with a *debounced backend* search
 * (customers + merged documents from ``/api/search/global``).
 *
 * Contract
 * ────────
 *   const { pages, customers, documents, loading, error }
 *       = useGlobalSearch(query);
 *
 * Behaviour
 * ─────────
 *   * ``pages`` — from ``searchNavIndex(query)``, always populated
 *     synchronously so the local list appears with zero latency.
 *   * ``customers`` + ``documents`` — from
 *     ``searchGlobal(query, {signal})``, gated on
 *     ``query.trim().length >= 2`` and debounced 300 ms.
 *   * Stale requests are truly aborted via ``AbortController`` —
 *     not just discarded — so slow-backend + fast-typing users
 *     don't spam the server.
 *   * On transient error, the LAST valid ``customers`` /
 *     ``documents`` are preserved so the UI doesn't flash empty.
 *   * ``loading`` — reflects the in-flight backend fetch only. The
 *     local ``pages`` list is never "loading".
 */
import { useEffect, useState } from "react";
import { searchNavIndex } from "@/lib/navIndex";
import { searchGlobal } from "@/lib/globalSearchClient";


const MIN_BACKEND_CHARS = 2;
const DEBOUNCE_MS = 300;


export function useGlobalSearch(query) {
  const q = (query || "").trim();

  // ── local (synchronous) ─────────────────────────────────────
  const pages = q ? searchNavIndex(q) : [];

  // ── backend (debounced) ─────────────────────────────────────
  const [customers, setCustomers] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (q.length < MIN_BACKEND_CHARS) {
      setCustomers([]);
      setDocuments([]);
      setLoading(false);
      setError(null);
      return undefined;
    }
    const controller = new AbortController();
    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      searchGlobal(q, { signal: controller.signal })
        .then((res) => {
          if (cancelled) return;
          setCustomers(Array.isArray(res?.customers) ? res.customers : []);
          setDocuments(Array.isArray(res?.documents) ? res.documents : []);
          setError(null);
        })
        .catch((e) => {
          // Aborts are expected on stale requests — swallow silently.
          if (e && (e.name === "AbortError"
                       || (typeof e.message === "string"
                            && e.message.includes("aborted")))) {
            return;
          }
          if (cancelled) return;
          // On transient error, PRESERVE prior results and expose
          // the error to the UI so the toast/badge can surface.
          setError(e);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [q]);

  return { pages, customers, documents, loading, error };
}


export default useGlobalSearch;
