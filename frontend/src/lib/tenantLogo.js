/**
 * Feb-2026 · Batch #4 · Logo ship — tenant-scoped brand-logo helper.
 *
 * ``getTenantLogoUrl(company, tenant?)`` returns the src to plug
 * into an ``<img>`` on any doc surface (invoice / quote /
 * estimate / magic-link view / portal doc list).
 *
 * Resolution order (first non-empty wins):
 *   1. ``company.logo_url`` — explicit override coming back from
 *      the ``_load_company`` payload the API emits.
 *   2. ``tenant.logo_url`` — future field a P2 admin-upload flow
 *      will populate.
 *   3. ``DEFAULT_LOGO_URL`` — the Pool & Landscaping of Vistancia
 *      mark shipped under ``/public/logos/``. Kept as a single
 *      exported constant so the P2 upload flow only needs to
 *      remove the fallback branch once tenants are seeded.
 *
 * The default resolves to the ``@1x`` optimized asset (16 KB) for
 * on-screen preview; the full-res 1024×1024 lives at
 * ``/logos/pool-landscaping-of-vistancia.png`` and is consumed by
 * the backend PDF renderer.
 */
export const DEFAULT_LOGO_URL =
  "/logos/pool-landscaping-of-vistancia@1x.png";


export function getTenantLogoUrl(company, tenant) {
  const co = (company && company.logo_url) || "";
  const te = (tenant && tenant.logo_url) || "";
  return co || te || DEFAULT_LOGO_URL;
}


export const DEFAULT_LOGO_ALT = "Pool & Landscaping of Vistancia";
