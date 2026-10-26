/**
 * M3a · Schedule Service Category filter (web Ticket Y parity).
 * Buckets All / Pool / Landscaping / Both. "All" = no query param. Non-All ships
 * the lowercase enum the BE expects (`/jobs?service_category=pool|landscaping|both`,
 * strict customer.service_category match, AND with other filters).
 */
export const SERVICE_CATEGORY_BUCKETS = ["All", "Pool", "Landscaping", "Both"] as const;
export type ServiceCategoryBucket = (typeof SERVICE_CATEGORY_BUCKETS)[number];
export const SERVICE_CATEGORY_KEY = "schedule.service_category";

export function normalizeServiceCategory(v: unknown): ServiceCategoryBucket {
  const s = String(v ?? "").trim().toLowerCase();
  if (s === "pool") return "Pool";
  if (s === "landscaping") return "Landscaping";
  if (s === "both") return "Both";
  return "All";
}

/** `&service_category=<lowercase>` for non-All buckets, "" for All. */
export function serviceCategoryParam(bucket: unknown): string {
  const b = normalizeServiceCategory(bucket);
  return b === "All" ? "" : `&service_category=${encodeURIComponent(b.toLowerCase())}`;
}

/**
 * Offline cache write-through is a per-user bulk REPLACE (`cacheWeekJobs`), so a
 * filtered /jobs subset must never be written — it would wipe the unfiltered jobs
 * techs need offline. Skip when a crew filter OR a non-All category is active.
 */
export function canWriteThroughJobs(opts: { crewFiltered: boolean; serviceCategory: unknown }): boolean {
  return !opts.crewFiltered && normalizeServiceCategory(opts.serviceCategory) === "All";
}
