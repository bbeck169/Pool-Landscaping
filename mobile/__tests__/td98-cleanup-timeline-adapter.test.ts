/**
 * TD-98-be-cleanup b1 · super-timeline adapter (pure).
 */
import {
  timelineChips, timelinePath, normaliseTimelineItem, mobileRouteFor,
  isInsufficientRole, isTimelineForbidden, TIMELINE_PAGE_SIZE,
} from "@/src/lib/customerTimeline";

it("H1 · path per scope: admin → /customers/{cid}/timeline, portal → /customers/me/timeline; page mode; kind only when filtered", () => {
  expect(timelinePath("admin", "c 1", 1)).toBe("/customers/c%201/timeline?page=1&page_size=20");
  expect(timelinePath("admin", "c1", 3, "sms")).toBe("/customers/c1/timeline?page=3&page_size=20&kind=sms");
  expect(timelinePath("portal", "ignored", 2, "all")).toBe("/customers/me/timeline?page=2&page_size=20");
  expect(timelinePath("portal", "", 0)).toContain("page=1");
  expect(TIMELINE_PAGE_SIZE).toBe(20);
  for (const s of ["admin", "portal"] as const) expect(timelinePath(s, "c1", 1)).not.toContain("communication-timeline");
});

it("H2 · chips role-gated like web (call/note admin + super_admin only)", () => {
  expect(timelineChips("admin")).toEqual(["all", "email", "sms", "invoice", "estimate", "call", "note"]);
  expect(timelineChips("SUPER_ADMIN")).toHaveLength(7);
  expect(timelineChips("manager")).toEqual(["all", "email", "sms", "invoice", "estimate"]);
  expect(timelineChips("customer")).toHaveLength(5);
  expect(timelineChips(undefined)).toHaveLength(5);
});

it("H3 · kind: kind → source_type → legacy type; quote ≡ estimate", () => {
  expect(normaliseTimelineItem({ kind: "SMS" }).kind).toBe("sms");
  expect(normaliseTimelineItem({ source_type: "call" }).kind).toBe("call");
  expect(normaliseTimelineItem({ type: "email" }).kind).toBe("email");
  expect(normaliseTimelineItem({ kind: "quote" }).kind).toBe("estimate");
});

it("H4 · actor object → display_name; legacy actor_label string still read; null otherwise", () => {
  expect(normaliseTimelineItem({ actor: { display_name: "Ada Admin", role: "admin" } }).actor).toBe("Ada Admin");
  expect(normaliseTimelineItem({ actor: null, actor_label: "System / Automation" }).actor).toBe("System / Automation");
  expect(normaliseTimelineItem({ actor: { role: "admin" } }).actor).toBeNull();
  expect(normaliseTimelineItem({}).actor).toBeNull();
});

it("H5 · body dispatch: body (lead-era) → body_preview (legacy) → detail.note_body (notes); delivery_error pass-through; status fallback", () => {
  expect(normaliseTimelineItem({ body: "Hi from lead era", detail: { note_body: "x" } }).body).toBe("Hi from lead era");
  expect(normaliseTimelineItem({ body_preview: "legacy" }).body).toBe("legacy");
  expect(normaliseTimelineItem({ kind: "note", detail: { note_body: "Gate code 1234" } }).body).toBe("Gate code 1234");
  expect(normaliseTimelineItem({ kind: "email" }).body).toBe("");
  const inv = normaliseTimelineItem({ kind: "invoice", id: "i1", status: "draft", summary: "Invoice INV-1", occurred_at: "2026-10-01T00:00:00Z", url: "/invoices/i1" });
  expect(inv).toMatchObject({ id: "i1", status: "draft", summary: "Invoice INV-1", occurredAt: "2026-10-01T00:00:00Z", url: "/invoices/i1", deliveryError: null });
  expect(normaliseTimelineItem({ delivery_status: "failed", status: "x", delivery_error: "bounced" })).toMatchObject({ status: "failed", deliveryError: "bounced" });
  expect(normaliseTimelineItem({ ref_id: "r9", created_at: "2026-01-01" })).toMatchObject({ id: "r9", occurredAt: "2026-01-01" });
});

it("H6 · url → mobile route (admin: /quote, /job; portal: list screens; unknown/absolute → null)", () => {
  expect(mobileRouteFor("/invoices/i1", "admin")).toBe("/quote/i1");
  expect(mobileRouteFor("/quotes/q1", "admin")).toBe("/quote/q1");
  expect(mobileRouteFor("/jobs/j1?tab=notes", "admin")).toBe("/job/j1");
  expect(mobileRouteFor("/portal/invoices/i1", "portal")).toBe("/portal/invoices");
  expect(mobileRouteFor("/portal/estimates/q1", "portal")).toBe("/portal/estimates");
  expect(mobileRouteFor("/invoices/i1", "portal")).toBe("/portal/invoices");
  expect(mobileRouteFor("/jobs/j1", "portal")).toBeNull();
  expect(mobileRouteFor("https://evil.example/invoices/1", "admin")).toBeNull();
  expect(mobileRouteFor("", "admin")).toBeNull();
  expect(mobileRouteFor("/settings", "admin")).toBeNull();
});

it("H7 · 403 helpers", () => {
  expect(isInsufficientRole({ status: 403, detail: "insufficient_role_for_full_timeline" })).toBe(true);
  expect(isInsufficientRole({ status: 403, detail: "Forbidden" })).toBe(false);
  expect(isTimelineForbidden({ status: 403, detail: "Forbidden" })).toBe(true);
  expect(isTimelineForbidden({ status: 500 })).toBe(false);
});
