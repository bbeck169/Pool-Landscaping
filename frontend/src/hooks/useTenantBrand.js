/**
 * useTenantBrand — Feb-2026 UI Polish Addendum
 *
 * Tiny module-scope cache around GET /api/tenants/current so the
 * BrandLogo component can render the tenant-specific logo without a
 * fresh HTTP call on every mount.
 *
 * Contract:
 *   • Returns `{ logo_url, branding, name, slug, loaded }`.
 *   • `logo_url` prefers `tenant.branding.logo_url`, falls back to
 *     the top-level `tenant.logo_url` (legacy shape), then null.
 *   • Callers that render a hard fallback (e.g. `/brand/logo.png`)
 *     when `logo_url` is null must NOT block on `loaded === true` —
 *     they must render the fallback immediately and swap in the
 *     tenant asset once the fetch settles. This keeps the header
 *     from flashing empty on first paint.
 *
 * The cache is intentionally simple (no cache invalidation, no
 * refresh). Branding is edited from the tenant-admin surface which
 * hard-reloads on save, so a stale cache in a single tab is not a
 * concern.
 */
import { useEffect, useState } from "react";
import { api } from "@/api";

let cached = null;
let inflight = null;

export function invalidateTenantBrand() {
  cached = null;
  inflight = null;
}

async function loadOnce() {
  if (cached) return cached;
  if (inflight) return inflight;
  // Defensive Promise.resolve() so tests that stub ``api.get`` with a
  // synchronous vi.fn() (undefined return) don't throw a
  // "Cannot read properties of undefined (reading 'then')". Real
  // ``api.get`` always returns a Promise so this is a no-op in
  // production.
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
      // Silent — the caller renders a fallback logo. Never poison the
      // cache with an error object; leave it null so a later mount
      // can retry.
      inflight = null;
      return {};
    });
  return inflight;
}

export function useTenantBrand() {
  const [state, setState] = useState(() => ({
    logo_url: cached?.branding?.logo_url || cached?.logo_url || null,
    branding: cached?.branding || null,
    name: cached?.name || null,
    slug: cached?.slug || null,
    loaded: !!cached,
  }));

  useEffect(() => {
    // If we already have a cached value, skip the effect entirely.
    let alive = true;
    const applyFresh = (t) => {
      if (!alive) return;
      setState({
        logo_url: t?.branding?.logo_url || t?.logo_url || null,
        branding: t?.branding || null,
        name: t?.name || null,
        slug: t?.slug || null,
        loaded: true,
      });
    };
    if (!cached) {
      loadOnce().then(applyFresh);
    }
    // Feb-2026 · TD-08 promoted — refresh the mounted BrandLogo the
    // instant the admin uploads / removes a logo. The BrandLogoSettings
    // page dispatches ``tenant-brand:updated`` after a successful
    // POST / DELETE round-trip. We invalidate the module-scope cache
    // then re-load so every mounted <BrandLogo> across the shell
    // updates without a full page reload.
    const onBrandUpdate = () => {
      cached = null;
      loadOnce().then(applyFresh);
    };
    if (typeof window !== "undefined") {
      window.addEventListener("tenant-brand:updated", onBrandUpdate);
    }
    return () => {
      alive = false;
      if (typeof window !== "undefined") {
        window.removeEventListener("tenant-brand:updated", onBrandUpdate);
      }
    };
  }, []);

  return state;
}

export default useTenantBrand;
