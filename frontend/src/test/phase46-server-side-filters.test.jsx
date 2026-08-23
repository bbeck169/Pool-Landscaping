/**
 * Feb-2026 · P46 — server-side ``tags`` (multi) + ``city`` filters.
 *
 * Pins the contract shift from client-side ``filtered`` memo to
 * backend query params:
 *   1. Selecting a tag chip fires a list fetch with ``tags=<name>``
 *      AND a matching set of ``count_only=true`` refetches so tab
 *      badges stay honest (P40 parity).
 *   2. Typing a city fires a list fetch with ``city=<value>``.
 *   3. Both filters compose on the fetch URL.
 *   4. URL sync — mounting the page with ``?tags=Pool&city=Phoenix``
 *      immediately fires a fetch that carries both params.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const mockGet = vi.fn();
const mockPost = vi.fn();
const mockPatch = vi.fn();
const mockDelete = vi.fn();


vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: (...a) => mockPatch(...a),
    delete: (...a) => mockDelete(...a),
  },
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ role: "admin", effectiveRole: "admin" }),
}));


import CustomersList from "@/pages/customers/CustomersList";


function _installMockGet() {
  mockGet.mockImplementation((path) => {
    if (typeof path === "string" && path.startsWith("/customer-tags")) {
      return Promise.resolve({
        items: [
          { id: "t-pool", name: "Pool", usage_count: 3, is_active: true },
          { id: "t-land", name: "Landscaping", usage_count: 2, is_active: true },
        ],
        total: 2,
      });
    }
    if (typeof path === "string" && path.startsWith("/customers")) {
      if (path.includes("count_only=true")) {
        return Promise.resolve({ count: 0 });
      }
      return Promise.resolve({ items: [], total: 0, page: 1,
        page_size: 100, total_pages: 0 });
    }
    return Promise.resolve({});
  });
}


function _renderAt(url = "/customers") {
  // Both ``selectedTags`` and ``city`` state initializers read from
  // ``window.location.search`` directly (parity with the P34 pattern),
  // so ``MemoryRouter``'s ``initialEntries`` alone doesn't hydrate
  // them. Seed the JSDOM URL via ``history.pushState`` first.
  try {
    window.history.pushState(null, "", url);
  } catch { /* noop */ }
  return render(
    <MemoryRouter initialEntries={[url]}>
      <CustomersList />
    </MemoryRouter>);
}


beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockDelete.mockReset();
  mockPost.mockResolvedValue({ ok: true });
  mockPatch.mockResolvedValue({ ok: true });
  mockDelete.mockResolvedValue({ ok: true });
  _installMockGet();
  try { sessionStorage.clear(); } catch { /* noop */ }
  // Wipe any URL state left over from the previous test's ``history
  // .replaceState`` calls.
  try {
    window.history.replaceState(null, "", "/customers");
  } catch { /* noop */ }
});


function _listCalls() {
  return mockGet.mock.calls
    .map((c) => c[0])
    .filter((p) => typeof p === "string"
                       && p.startsWith("/customers?")
                       && !p.includes("count_only"));
}


function _countCalls() {
  return mockGet.mock.calls
    .map((c) => c[0])
    .filter((p) => typeof p === "string"
                       && p.startsWith("/customers?")
                       && p.includes("count_only=true"));
}


describe("CustomersList · P46 server-side filters", () => {
  it("URL mount with ?tags=Pool fires a list fetch with tags=Pool",
      async () => {
    _renderAt("/customers?tags=Pool");
    await waitFor(() => {
      const listCall = _listCalls().find((p) => p.includes("tags=Pool"));
      expect(listCall).toBeDefined();
      expect(listCall).toContain("page=1");
      expect(listCall).toContain("page_size=100");
    });
  });

  it("URL mount with ?city=Phoenix fires a list fetch with city=Phoenix",
      async () => {
    _renderAt("/customers?city=Phoenix");
    await waitFor(() => {
      const listCall = _listCalls().find((p) =>
        p.includes("city=Phoenix"));
      expect(listCall).toBeDefined();
    });
  });

  it("URL mount with both params fires a single list fetch carrying both",
      async () => {
    _renderAt("/customers?tags=Pool&city=Phoenix");
    await waitFor(() => {
      const listCall = _listCalls().find((p) =>
        p.includes("tags=Pool") && p.includes("city=Phoenix"));
      expect(listCall).toBeDefined();
    });
  });

  it("Multiple selectedTags URL param (comma-joined) serializes as "
        + "repeated tags= on the fetch", async () => {
    _renderAt("/customers?tags=Pool,Landscaping");
    await waitFor(() => {
      const listCall = _listCalls().find((p) => {
        const matches = p.match(/tags=/g) || [];
        return matches.length >= 2
                  && p.includes("tags=Pool")
                  && p.includes("tags=Landscaping");
      });
      expect(listCall).toBeDefined();
    });
  });

  it("tab-count fetches include the same tags + city params (P40 parity)",
      async () => {
    _renderAt("/customers?tags=Pool&city=Phoenix");
    await waitFor(() => {
      const cnt = _countCalls().filter((p) =>
        p.includes("tags=Pool") && p.includes("city=Phoenix"));
      // Active + Inactive + Muted (admin sees all three). All must
      // carry both filter params.
      expect(cnt.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("filtered memo no longer applies city/tag client-side "
        + "(URL param drives everything)", async () => {
    // Stub a list response with rows that would DEFINITELY be
    // filtered out by the old client-side ``filtered`` memo
    // (address doesn't contain "Phoenix", tags don't contain "Pool").
    // Under P46 the backend controls the set, so the rows we return
    // here are what the user sees — no client-side stripping.
    mockGet.mockImplementation((path) => {
      if (typeof path === "string" && path.startsWith("/customer-tags")) {
        return Promise.resolve({ items: [
          { id: "t-pool", name: "Pool", usage_count: 3, is_active: true },
        ], total: 1 });
      }
      if (typeof path === "string" && path.startsWith("/customers")) {
        if (path.includes("count_only=true")) return Promise.resolve({ count: 1 });
        return Promise.resolve({
          items: [{
            id: "cust-1",
            name: "Trusted Backend Row",
            address: "Tempe, AZ",   // doesn't contain "Phoenix"
            tags: ["Landscaping"],   // doesn't contain "Pool"
            is_active: true,
          }],
          total: 1, page: 1, page_size: 100, total_pages: 1,
        });
      }
      return Promise.resolve({});
    });
    _renderAt("/customers?tags=Pool&city=Phoenix");
    // Wait for the list fetch + render. The row must appear even
    // though its local ``address``/``tags`` wouldn't survive the
    // legacy client-side predicates — proof the client no longer
    // filters that surface.
    await waitFor(() => {
      const rendered = screen.queryByText("Trusted Backend Row");
      expect(rendered).toBeTruthy();
    });
  });
});
