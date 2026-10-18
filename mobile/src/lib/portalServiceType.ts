/**
 * TD-69 (web b86ecb289) — portal service-type resolver, mobile-owned
 * port of web `lib/portalServiceType.js`.
 *
 * Replaces the first-truthy-wins inline `reportKind()` that let a stray
 * pool-ish `template` beat an authoritative landscape `job.service_type`.
 *   - SCANS every candidate field: template, service_type, service_line,
 *     service_category + job.service_type / job.service_line /
 *     job.service_category.
 *   - LANDSCAPE PRIORITY: any landscape signal → "landscape".
 *   - POOL FALLBACK: else any pool signal → "pool".
 *   - else "generic". Chemistry renders ONLY for "pool".
 */
export type PortalServiceKind = "pool" | "landscape" | "generic";

const LANDSCAPE_SIGNALS = ["landscap", "mow", "lawn", "yard", "garden"];
const POOL_SIGNALS = ["pool", "chem", "spa", "water"];

const hasAny = (haystack: string, signals: string[]) => signals.some((s) => haystack.includes(s));

export function resolveServiceType(record: any): PortalServiceKind {
  if (!record || typeof record !== "object") return "generic";
  const parts: string[] = [];
  const push = (v: unknown) => {
    if (v == null) return;
    const s = String(v).toLowerCase().trim();
    if (s) parts.push(s);
  };
  push(record.template);
  push(record.service_type);
  push(record.service_line);
  push(record.service_category);
  if (record.job && typeof record.job === "object") {
    push(record.job.service_type);
    push(record.job.service_line);
    push(record.job.service_category);
  }
  const scanned = parts.join(" ");
  if (!scanned) return "generic";
  if (hasAny(scanned, LANDSCAPE_SIGNALS)) return "landscape";
  if (hasAny(scanned, POOL_SIGNALS)) return "pool";
  return "generic";
}

export default resolveServiceType;
