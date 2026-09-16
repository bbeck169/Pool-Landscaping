/**
 * Phase MI1.1 · Feb 2026 — client-side industry deriver.
 *
 * Mirror of the backend helper ``derive_industry_for_job`` in
 * ``routers/industry_checklists.py``. Returns one of the seven
 * canonical checklist slugs so the tech-side dispatcher can pick
 * the right form component per job.
 *
 * Keep both helpers in lockstep — the keyword order matters
 * (``solar`` wins before the broader ``clean`` match so
 * "Solar Panel Cleaning" resolves to ``solar``, not ``cleaning``).
 */

const INDUSTRY_SLUGS = [
  "pool", "landscaping", "hvac", "pest_control",
  "cleaning", "solar", "handyman",
];

// Ordered — narrower wins first.
const KEYWORD_MAP = [
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

const TENANT_INDUSTRY_ALIAS = { pools: "pool" };


export function deriveIndustryForJob(job, tenant) {
  if (job && typeof job === "object") {
    const explicit = String(job.industry || "").trim().toLowerCase();
    if (INDUSTRY_SLUGS.includes(explicit)) return explicit;
    const hay = [job.service_type, job.job_type, job.title]
      .filter(Boolean).join(" ").toLowerCase();
    for (const [needle, slug] of KEYWORD_MAP) {
      if (hay.includes(needle)) return slug;
    }
  }
  if (tenant && typeof tenant === "object") {
    let primary = null;
    if (Array.isArray(tenant.industries) && tenant.industries.length) {
      primary = String(tenant.industries[0]).trim().toLowerCase();
    } else if (tenant.industry) {
      primary = String(tenant.industry).trim().toLowerCase();
    }
    primary = TENANT_INDUSTRY_ALIAS[primary] || primary;
    if (primary && INDUSTRY_SLUGS.includes(primary)) return primary;
  }
  return "pool";
}


export default deriveIndustryForJob;
export { INDUSTRY_SLUGS };
