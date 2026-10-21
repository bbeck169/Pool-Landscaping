/**
 * TD-98-be-cleanup · mobile migration · pure super-timeline helpers.
 *
 * Mobile moves off the retired legacy per-customer "communication timeline"
 * endpoint (TD-98-be-cleanup) onto the endpoints web `CustomerFullTimeline.jsx` uses:
 *   admin scope  → GET /customers/{cid}/timeline   (admin/manager/super_admin)
 *   portal scope → GET /customers/me/timeline       (customer; page mode only)
 * Envelope `{items, page, page_size, total, total_pages, next_before}`.
 *
 * Item-shape adapter (legacy → super): `type`→`kind` (6 kinds; `quote` ≡
 * estimate), `actor_label` string → `actor` object, `body_preview` →
 * `body` / `detail.note_body`, `delivery_error` no longer emitted (kept as
 * pass-through in case TD-98-be-sources restores it).
 */

export type TimelineScope = "admin" | "portal";
export type TimelineKind = "email" | "sms" | "invoice" | "estimate" | "call" | "note";

/** Web parity: base chips for everyone; call/note only for admin/super_admin. */
export const TIMELINE_BASE_CHIPS = ["all", "email", "sms", "invoice", "estimate"];
export const TIMELINE_ADMIN_CHIPS = ["call", "note"];
const FULL_TIMELINE_ROLES = new Set(["admin", "super_admin"]);
export const TIMELINE_PAGE_SIZE = 20;

export function timelineChips(role?: string | null): string[] {
  return FULL_TIMELINE_ROLES.has(String(role || "").toLowerCase())
    ? [...TIMELINE_BASE_CHIPS, ...TIMELINE_ADMIN_CHIPS]
    : TIMELINE_BASE_CHIPS;
}

export function timelinePath(scope: TimelineScope, customerId: string, page: number, kind = "all", pageSize = TIMELINE_PAGE_SIZE): string {
  const base = scope === "admin" ? `/customers/${encodeURIComponent(customerId)}/timeline` : "/customers/me/timeline";
  const qs = new URLSearchParams({ page: String(Math.max(1, page)), page_size: String(pageSize) });
  if (kind && kind !== "all") qs.set("kind", kind);
  return `${base}?${qs}`;
}

export type TimelineItem = {
  id: string;
  kind: TimelineKind | string;
  occurredAt: string;
  actor: string | null;
  status: string;
  subject: string;
  summary: string;
  body: string;
  recipient: string;
  url: string;
  deliveryError: string | null;
};

export function normaliseTimelineItem(raw: any): TimelineItem {
  const k = String(raw?.kind || raw?.source_type || raw?.type || "").toLowerCase();
  const actor = raw?.actor && typeof raw.actor === "object"
    ? raw.actor.display_name || null
    : (typeof raw?.actor === "string" ? raw.actor : raw?.actor_label) || null;
  return {
    id: String(raw?.id || raw?.ref_id || ""),
    kind: k === "quote" ? "estimate" : k,
    occurredAt: raw?.occurred_at || raw?.created_at || "",
    actor,
    status: String(raw?.delivery_status || raw?.status || ""),
    subject: raw?.subject || "",
    summary: raw?.summary || "",
    body: raw?.body || raw?.body_preview || raw?.detail?.note_body || "",
    recipient: raw?.recipient || "",
    url: raw?.url || "",
    deliveryError: raw?.delivery_error || null,
  };
}

/**
 * Map the web-path `url` the backend emits to a mobile route. Mobile has
 * one quote/invoice detail screen (`/quote/<id>`, as CustomerInvoiceList)
 * and no portal `[id]` screens → portal rows open the list screens.
 */
export function mobileRouteFor(url: string, scope: TimelineScope): string | null {
  const u = String(url || "").trim();
  if (!u.startsWith("/")) return null;
  const m = u.match(/^\/(portal\/)?(invoices|quotes|estimates|jobs)\/([^/?#]+)/);
  if (!m) return null;
  const [, portal, seg, id] = m;
  if (portal || scope === "portal") {
    if (seg === "invoices") return "/portal/invoices";
    if (seg === "estimates" || seg === "quotes") return "/portal/estimates";
    return null;
  }
  if (seg === "jobs") return `/job/${id}`;
  return `/quote/${id}`;
}

/** Web parity: this 403 renders a silent empty timeline, not an error. */
export function isInsufficientRole(e: any): boolean {
  return e?.status === 403 && e?.detail === "insufficient_role_for_full_timeline";
}

/** Legacy mobile endpoint also 403'd techs (`_TECH_ROLES`) with a plain detail; treat any 403 as "no access". */
export function isTimelineForbidden(e: any): boolean {
  return e?.status === 403;
}
