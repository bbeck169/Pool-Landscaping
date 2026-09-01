/**
 * Phase K2 · Feb-2026 — Dynamic breadcrumb label registry.
 *
 * Pages that own a dynamic entity (customer detail, invoice detail,
 * portal service) publish their resolved label via
 * ``useSetDynamicCrumb`` and the provider passes the map down into
 * ``AppBreadcrumbs`` so the current-page crumb reads
 * ``"Jennifer Carson"`` instead of the generic
 * ``"Customer"`` placeholder.
 *
 * Provider is mounted ONCE in ``AppLayout`` so every route inside
 * ``<Outlet>`` shares the same map.  Unmounting a page clears its
 * own contribution so navigating from ``/customers/A`` →
 * ``/customers/B`` doesn't leak "A"'s label into the interim
 * render.
 *
 * Keys can be either the route-meta ``dynamic`` handle
 * (``"customer"``) — preferred — or the raw route key
 * (``"/customers/:id"``) for older callers.
 */
import React, { createContext, useCallback, useContext, useEffect,
                 useMemo, useState } from "react";

const DynamicCrumbContext = createContext({
  labels: {},
  setLabel: () => {},
});


export function DynamicCrumbProvider({ children }) {
  const [labels, setLabels] = useState({});

  const setLabel = useCallback((key, value) => {
    if (!key) return;
    setLabels((prev) => {
      // If the value is nullish we treat this as an unregister —
      // returning a new object without the key so we can also drop
      // stale entries.
      if (value === undefined || value === null || value === "") {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      }
      // No-op re-render guard: the map is checked shallow so
      // React StrictMode's double-invoke doesn't churn.
      if (prev[key] === value) return prev;
      return { ...prev, [key]: value };
    });
  }, []);

  const value = useMemo(() => ({ labels, setLabel }),
                                    [labels, setLabel]);
  return (
    <DynamicCrumbContext.Provider value={value}>
      {children}
    </DynamicCrumbContext.Provider>
  );
}


/** Read-only accessor used by ``AppBreadcrumbs``. */
export function useDynamicCrumbLabels() {
  return useContext(DynamicCrumbContext).labels;
}


/**
 * Register/deregister a dynamic label under ``key``.  Call this
 * from a page component with the currently-loaded entity name.
 * Passing an empty/nullish value clears the entry so the
 * "..." skeleton reappears while the next page loads.
 *
 * Effect cleanup deregisters on unmount so the label doesn't
 * bleed into the sibling route.
 */
export function useSetDynamicCrumb(key, value) {
  const { setLabel } = useContext(DynamicCrumbContext);
  useEffect(() => {
    setLabel(key, value);
    return () => setLabel(key, null);
  }, [key, value, setLabel]);
}
