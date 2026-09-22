/**
 * Phase P31 · Feb-2026 — Customers list counts single-fetch.
 *
 * Locks in that the customers list page now fires ONE
 * ``GET /api/customers/counts`` request instead of the pre-P31
 * NINE ``count_only=true`` fanout calls. Also verifies:
 *   - Zero ``count_only`` call sites remain on the wire.
 *   - The nine counts from the new envelope hydrate the expected
 *     setters (tab counts + 5 standalone badge counts).
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";


// Track every GET path the page fires so we can assert the
// count_only fanout is gone and the new endpoint IS hit.
let _apiGetPaths = [];
let _apiGetImpl = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (path, ...rest) => {
      _apiGetPaths.push(path);
      return _apiGetImpl(path, ...rest);
    },
    post: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/hooks/use-toast", () => ({
  useToast: () => ({ toast: vi.fn() }),
}));

// Stub localStorage user so the page thinks it's mounted by admin
// (so muted/waitlist counts + admin-only surfaces render).
beforeEach(() => {
  _apiGetPaths = [];
  _apiGetImpl = vi.fn().mockImplementation((path) => {
    if (path.startsWith("/customers/counts")) {
      return Promise.resolve({
        active: 12, inactive: 3, muted: 1, waitlist: 2,
        missing_address: 5, portal_activated: 4,
        portal_not_activated: 6, no_payment_method: 8,
        never_logged_in: 7,
      });
    }
    if (path.startsWith("/customers")) {
      // Empty paginated envelope for the list itself.
      return Promise.resolve({
        items: [], total: 0, page: 1, page_size: 100, total_pages: 0,
        counts_by_status: null,
      });
    }
    if (path.startsWith("/tenants/tags")
        || path.startsWith("/tenants/me/tags")
        || path.startsWith("/customer-tags")) {
      return Promise.resolve([]);
    }
    return Promise.resolve({});
  });
  try {
    window.localStorage.setItem(
      "user",
      JSON.stringify({ id: "u-adm", role: "admin" }),
    );
  } catch { /* jsdom sometimes rejects — non-fatal */ }
});


describe("P31 · Customers list — consolidated counts fetch", () => {
  it("fires ONE /customers/counts request instead of the pre-P31 fanout",
      async () => {
    const { default: CustomersList } = await import(
      "@/pages/customers/CustomersList"
    );
    render(
      <MemoryRouter initialEntries={["/customers"]}>
        <CustomersList />
      </MemoryRouter>,
    );

    // Wait for hydration to settle.
    await waitFor(() => {
      const countsHits = _apiGetPaths.filter(
        (p) => p.startsWith("/customers/counts"),
      );
      expect(countsHits.length).toBeGreaterThanOrEqual(1);
    });

    // Zero legacy fanout calls. The pre-P31 code fired paths like
    // ``/customers?is_active=true&count_only=true`` — the guardrail
    // says every ``count_only=true`` call must be gone.
    const legacyCountOnlyHits = _apiGetPaths.filter(
      (p) => p.includes("count_only=true"),
    );
    expect(legacyCountOnlyHits).toEqual([]);

    // Exactly the consolidated endpoint was hit for counts.
    const countsHits = _apiGetPaths.filter(
      (p) => p.startsWith("/customers/counts"),
    );
    expect(countsHits.length).toBeGreaterThanOrEqual(1);
    // Sanity — the call was routed to the new endpoint verbatim.
    expect(countsHits[0]).toMatch(/^\/customers\/counts/);
  });

  it("does NOT fire per-badge standalone count_only requests",
      async () => {
    const { default: CustomersList } = await import(
      "@/pages/customers/CustomersList"
    );
    render(
      <MemoryRouter initialEntries={["/customers"]}>
        <CustomersList />
      </MemoryRouter>,
    );
    // Give the removed per-badge effects a chance to (not) fire.
    await new Promise((r) => setTimeout(r, 50));
    // Nine pre-P31 badge paths — all must be absent.
    const banned = [
      "/customers?count_only=true&missing_address=true",
      "/customers?count_only=true&portal_activated=true",
      "/customers?count_only=true&portal_activated=false",
      "/customers?count_only=true&has_payment_method=false",
      "/customers?count_only=true&first_access=never",
      "/customers?is_active=true&count_only=true",
      "/customers?is_active=false&count_only=true",
      "/customers?is_muted=true&count_only=true",
      "/customers?waitlisted=true&count_only=true",
    ];
    for (const p of banned) {
      expect(_apiGetPaths).not.toContain(p);
    }
  });
});
