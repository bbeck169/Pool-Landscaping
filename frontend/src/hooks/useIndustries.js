/**
 * useIndustries — Feb-2026 · Multi-industry Phase A
 *
 * Hook that returns the current tenant's ``industries[]`` array +
 * a ``hasIndustry(slug)`` predicate used by future Phase C
 * gating.  Safe defaults on cold mount so callers can call
 * ``hasIndustry(...)`` before the tenant fetch settles without a
 * ``TypeError``.
 *
 * Data source: GET ``/api/tenants/current`` via the existing
 * ``useTenantBrand`` cache — the tenant document now carries
 * ``industries: string[]`` on that surface (see
 * ``memory/FEATURE_MULTI_INDUSTRY_PHASE_A.md``).  Re-using the
 * cache means every mount is free after the first paint.
 */
import { useEffect, useState } from "react";
import { api } from "@/api";
import { INDUSTRY_LABELS } from "@/config/industries";

// Module-scope cache — mirrors the useTenantBrand pattern so the
// tenant document is only fetched once per session across every
// consumer of this hook.
let cached = null;
let inflight = null;

async function loadOnce() {
  if (cached) return cached;
  if (inflight) return inflight;
  inflight = Promise.resolve()
    .then(() => {
      try { return api.get("/tenants/current"); } catch { return null; }
    })
    .then((t) => {
      cached = t || {};
      inflight = null;
      return cached;
    })
    .catch(() => {
      inflight = null;
      return {};
    });
  return inflight;
}

export function invalidateIndustries() {
  cached = null;
  inflight = null;
}

export function useIndustries() {
  const [tenant, setTenant] = useState(cached);

  useEffect(() => {
    let alive = true;
    if (cached) {
      setTenant(cached);
    } else {
      loadOnce().then((t) => { if (alive) setTenant(t); });
    }
    return () => { alive = false; };
  }, []);

  const industries = Array.isArray(tenant?.industries) ? tenant.industries : [];
  return {
    industries,
    // Predicate is safe on cold mount — before the fetch settles
    // ``industries`` is ``[]`` so every gate resolves false, which
    // matches the "hide feature until confirmed on" default.
    hasIndustry: (slug) => industries.includes(slug),
    labels: INDUSTRY_LABELS,
    loaded: Boolean(tenant),
  };
}
