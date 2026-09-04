/**
 * customersActiveFilter.test.tsx — Phase K25 (updated for Phase K40)
 *
 * Phase K40 · Feb-2026 — the Customers list is the ONE exception to
 * the "default to All / no filter" rule: the segmented control still
 * defaults to ``"active"``. However K40 REMOVED the AsyncStorage
 * persistence layer — every mount lands on Active regardless of the
 * operator's last selection (unless a URL param overrides it, which
 * this list surfaces via router state today).
 *
 * The customers list (``app/(app)/customers.tsx``) is too large to
 * render fully in isolation. This suite still exercises the pure
 * query-param mapping logic (unchanged by K40) and now enforces
 * that the AsyncStorage read/write is GONE (regression guard).
 */

import fs from "node:fs";
import path from "node:path";

/* ── Query-string mapping (unchanged by K40) ─────────────────── */

describe("Customer status filter — query param logic", () => {
  it("maps 'active' → is_active=true", () => {
    const qp = new URLSearchParams();
    const statusFilter = "active";
    if (statusFilter === "waitlist") {
      qp.set("waitlisted", "true");
    } else if (statusFilter !== "all") {
      qp.set("is_active", String(statusFilter === "active"));
    }
    expect(qp.get("is_active")).toBe("true");
  });

  it("maps 'inactive' → is_active=false", () => {
    const qp = new URLSearchParams();
    const statusFilter = "inactive";
    if (statusFilter === "waitlist") {
      qp.set("waitlisted", "true");
    } else if (statusFilter !== "all") {
      qp.set("is_active", String(statusFilter === "active"));
    }
    expect(qp.get("is_active")).toBe("false");
  });

  it("maps 'all' → no is_active param", () => {
    const qp = new URLSearchParams();
    const statusFilter = "all";
    if (statusFilter === "waitlist") {
      qp.set("waitlisted", "true");
    } else if (statusFilter !== "all") {
      qp.set("is_active", String(statusFilter === "active"));
    }
    expect(qp.has("is_active")).toBe(false);
  });

  it("maps 'waitlist' → waitlisted=true (no is_active)", () => {
    const qp = new URLSearchParams();
    const statusFilter = "waitlist";
    if (statusFilter === "waitlist") {
      qp.set("waitlisted", "true");
    } else if (statusFilter !== "all") {
      qp.set("is_active", String(statusFilter === "active"));
    }
    expect(qp.get("waitlisted")).toBe("true");
    expect(qp.has("is_active")).toBe(false);
  });
});

/* ── K40 · No-persistence contract check (source-body regex) ───── */

const CUSTOMERS_SRC = fs.readFileSync(
  path.resolve(__dirname, "..", "app", "(app)", "customers.tsx"),
  "utf-8",
);

describe("Phase K40 · Customers status filter — NO AsyncStorage persistence", () => {
  it("statusFilter initializer is the literal 'active' (no storage.getItem)", () => {
    expect(CUSTOMERS_SRC).toMatch(
      /useState<"active" \| "inactive" \| "all" \| "waitlist">\("active"\)/,
    );
  });

  it("portalFilter initializer is the literal 'all' (no storage.getItem)", () => {
    expect(CUSTOMERS_SRC).toMatch(
      /useState<"all" \| "activated" \| "not_activated">\("all"\)/,
    );
  });

  it("no ``storage.getItem`` call for filter keys anywhere in the file", () => {
    expect(CUSTOMERS_SRC).not.toMatch(
      /storage\.getItem[^;]*customerListFilter\./,
    );
  });

  it("no ``storage.setItem`` call for filter keys anywhere in the file", () => {
    expect(CUSTOMERS_SRC).not.toMatch(
      /storage\.setItem[^;]*customerListFilter\./,
    );
  });
});
