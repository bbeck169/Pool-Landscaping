/**
 * Phase MI1.1 · Feb 2026 — client-side industry deriver.
 * Phase D2   · Feb 2026 — extended to all 23 canonical industries.
 *
 * Mirror of the backend helper ``derive_industry_for_job`` in
 * ``backend/routers/industry_checklists.py``. Returns one of the
 * canonical checklist slugs so the tech-side dispatcher can pick
 * the right form component per job.
 *
 * Keep both helpers in lockstep — the keyword order matters.
 * Compound keywords MUST match before their component words
 * (e.g. ``window clean`` before ``clean`` so "Window Cleaning"
 * resolves to ``window_cleaning``, not ``cleaning``).
 */

// Canonical slug order used by settings pickers + locale switcher.
// ``Object.freeze`` locks the array so downstream consumers can't
// mutate the shared list.
export const CANONICAL_INDUSTRIES = Object.freeze([
  // Original Phase MI1 industries — order preserved.
  "pool", "landscaping", "hvac", "pest_control",
  "cleaning", "solar", "handyman",
  // Phase D1/D2 · +16 = 23 total.
  "plumbing", "electrical", "roofing", "painting",
  "garage_door", "appliance_repair", "locksmith",
  "chimney_sweep", "gutter", "window_cleaning",
  "carpet_cleaning", "pressure_washing", "tree_service",
  "snow_removal", "fencing", "irrigation",
]);

// Retained for MI1 back-compat — some callers imported it before
// D2. Same set, different name.
const INDUSTRY_SLUGS = CANONICAL_INDUSTRIES;


// Ordered — compound / narrower matches win first.
// Mirrors ``routers/industry_checklists.py::keyword_map`` verbatim.
const KEYWORD_MAP = [
  // Compound / multi-word matches — narrowest first.
  ["garage door", "garage_door"], ["garage-door", "garage_door"],
  ["chimney", "chimney_sweep"],
  ["window clean", "window_cleaning"], ["window wash", "window_cleaning"],
  ["carpet", "carpet_cleaning"],
  ["pressure wash", "pressure_washing"], ["power wash", "pressure_washing"],
  ["tree", "tree_service"],
  ["snow", "snow_removal"],
  // Original Phase-MI1 industries — order preserved.
  ["solar", "solar"], ["pv panel", "solar"], ["photovoltaic", "solar"],
  ["hvac", "hvac"], ["heating", "hvac"], ["cooling", "hvac"],
  ["air conditioning", "hvac"],
  ["pest", "pest_control"], ["exterminator", "pest_control"],
  ["handyman", "handyman"],
  ["landscape", "landscaping"], ["landscap", "landscaping"],
  ["mowing", "landscaping"], ["lawn", "landscaping"],
  ["pool", "pool"], ["chem", "pool"],
  // Phase D1 · single-keyword new industries.
  ["appliance", "appliance_repair"],
  ["locksmith", "locksmith"], ["rekey", "locksmith"],
  ["plumb", "plumbing"],
  ["electric", "electrical"],
  ["roof", "roofing"],
  ["paint", "painting"],
  ["gutter", "gutter"],
  ["fenc", "fencing"],
  ["irrigat", "irrigation"], ["sprinkler", "irrigation"],
  // Broader matches last so they don't preempt an industry
  // keyword earlier in the string.
  ["clean", "cleaning"], ["janitorial", "cleaning"],
  ["housekeep", "cleaning"],
  ["repair", "handyman"],
];

const TENANT_INDUSTRY_ALIAS = { pools: "pool" };


export function deriveIndustryForJob(job, tenant) {
  if (job && typeof job === "object") {
    // Explicit override wins first — either ``job.industry`` (D2
    // canonical) or ``job.checklist_industry`` (legacy override
    // key some clients still emit).
    const explicit = String(
      job.industry || job.checklist_industry || "",
    ).trim().toLowerCase();
    if (CANONICAL_INDUSTRIES.includes(explicit)) return explicit;
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
    if (primary && CANONICAL_INDUSTRIES.includes(primary)) return primary;
  }
  return "pool";
}


export default deriveIndustryForJob;
export { INDUSTRY_SLUGS };
