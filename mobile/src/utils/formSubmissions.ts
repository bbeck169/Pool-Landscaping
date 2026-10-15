/**
 * Pure helpers for the read-only Form submissions inbox / detail
 * (Form Builder mobile parity C2).
 */
import type { FormSubmission } from "@/src/api/marketingForms";

export const ALL_FORMS_FANOUT_CAP = 25;
export type Range = "all" | "7d" | "30d";
const RANGE_DAYS: Record<Range, number | null> = { all: null, "7d": 7, "30d": 30 };

export function inRange(createdAt: string | undefined, range: Range, now: number = Date.now()): boolean {
  const days = RANGE_DAYS[range];
  if (days == null) return true;
  const t = createdAt ? Date.parse(createdAt) : NaN;
  return Number.isFinite(t) && now - t <= days * 86400000;
}

export function answersOf(s: FormSubmission): Record<string, any> {
  return (s.answers && Object.keys(s.answers).length ? s.answers : s.data) || {};
}

export function summaryLine(s: FormSubmission): string {
  const a = answersOf(s);
  const pick = a.name || a.full_name || [a.first_name, a.last_name].filter(Boolean).join(" ") || "";
  const contact = a.email || a.phone || "";
  return [pick, contact].filter(Boolean).join(" · ") || `${Object.keys(a).length} answers`;
}

export function destinationLabel(s: FormSubmission): string | null {
  if (s.customer_id) return "Customer";
  if (s.lead_id) return "Lead";
  return null;
}

export function formatAnswer(v: any): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.map(formatAnswer).join(", ");
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
export const isSensitive = (f: any) => !!(f && (f.pii_tag || f.is_customer_facing === false));

