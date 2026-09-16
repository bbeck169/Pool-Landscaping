/**
 * Phase MI1.1-mobile — client-side industry deriver.
 *
 * Mirror of the backend helper `derive_industry_for_job` in
 * `routers/industry_checklists.py` AND the web helper at
 * `frontend/src/lib/deriveIndustry.js`.
 *
 * Returns one of the seven canonical checklist slugs so the
 * mobile dispatcher can pick the right form component per job.
 *
 * Keep all three helpers (backend, web, mobile) in lockstep —
 * the keyword order matters (`solar` wins before the broader
 * `clean` match so "Solar Panel Cleaning" resolves to `solar`,
 * not `cleaning`).
 */

export const INDUSTRY_SLUGS = [
  "pool", "landscaping", "hvac", "pest_control",
  "cleaning", "solar", "handyman",
] as const;

export type IndustrySlug = (typeof INDUSTRY_SLUGS)[number];

// Ordered — narrower keywords win first.
const KEYWORD_MAP: [string, IndustrySlug][] = [
  ["solar", "solar"], ["pv panel", "solar"], ["photovoltaic", "solar"],
  ["hvac", "hvac"], ["heating", "hvac"], ["cooling", "hvac"],
  ["air conditioning", "hvac"],
  ["pest", "pest_control"], ["exterminator", "pest_control"],
  ["handyman", "handyman"],
  ["landscape", "landscaping"], ["landscap", "landscaping"],
  ["mowing", "landscaping"], ["lawn", "landscaping"],
  ["pool", "pool"], ["chem", "pool"],
  ["clean", "cleaning"], ["janitorial", "cleaning"],
  ["housekeep", "cleaning"],
  ["repair", "handyman"],
];

const TENANT_INDUSTRY_ALIAS: Record<string, IndustrySlug> = { pools: "pool" };

export function deriveIndustryForJob(job?: any, tenant?: any): IndustrySlug {
  if (job && typeof job === "object") {
    const explicit = String(job.industry || "").trim().toLowerCase();
    if ((INDUSTRY_SLUGS as readonly string[]).includes(explicit)) return explicit as IndustrySlug;
    const hay = [job.service_type, job.job_type, job.title]
      .filter(Boolean).join(" ").toLowerCase();
    for (const [needle, slug] of KEYWORD_MAP) {
      if (hay.includes(needle)) return slug;
    }
  }
  if (tenant && typeof tenant === "object") {
    let primary: string | null = null;
    if (Array.isArray(tenant.industries) && tenant.industries.length) {
      primary = String(tenant.industries[0]).trim().toLowerCase();
    } else if (tenant.industry) {
      primary = String(tenant.industry).trim().toLowerCase();
    }
    primary = TENANT_INDUSTRY_ALIAS[primary as string] || primary;
    if (primary && (INDUSTRY_SLUGS as readonly string[]).includes(primary)) return primary as IndustrySlug;
  }
  return "pool";
}

export default deriveIndustryForJob;
