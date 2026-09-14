/**
 * useIndustries — Phase D · Multi-industry mobile hook.
 *
 * Returns the tenant's ``industries[]`` array + a ``hasIndustry(slug)``
 * predicate. Module-scope cache mirrors the web hook pattern — the
 * tenant document is only fetched once per session across every consumer.
 *
 * Data source: GET ``/api/tenants/current`` (canonical route per Phase A).
 */
import { useEffect, useState } from "react";
import { api } from "@/src/api";
import { INDUSTRY_LABELS } from "@/src/config/industries";

// Module-scope cache — single fetch per session.
let cached: Record<string, any> | null = null;
let inflight: Promise<Record<string, any>> | null = null;

async function loadOnce(): Promise<Record<string, any>> {
  if (cached) return cached;
  if (inflight) return inflight;
  inflight = api.get("/tenants/current")
    .then((t: any) => {
      cached = t || {};
      inflight = null;
      return cached!;
    })
    .catch(() => {
      inflight = null;
      return {};
    });
  return inflight;
}

/** Clear the module cache so the next mount re-fetches. */
export function invalidateIndustries(): void {
  cached = null;
  inflight = null;
}

export type UseIndustriesResult = {
  industries: string[];
  hasIndustry: (slug: string) => boolean;
  labels: Readonly<Record<string, string>>;
  loaded: boolean;
};

export function useIndustries(): UseIndustriesResult {
  const [tenant, setTenant] = useState<Record<string, any> | null>(cached);

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
    hasIndustry: (slug: string) => industries.includes(slug),
    labels: INDUSTRY_LABELS,
    loaded: Boolean(tenant),
  };
}
