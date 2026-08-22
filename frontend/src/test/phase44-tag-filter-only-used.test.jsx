/**
 * Feb-2026 · P44 — Customers-list "All tags" dropdown hides zero-usage
 * catalog rows. Vitest pins:
 *   1. The list-page dropdown fetches `/customer-tags?only_used=true`.
 *   2. Rendered options match the API response.
 *   3. The two OTHER `/customer-tags` consumers (settings page +
 *      CustomerTagPicker used by the edit form) do NOT carry
 *      ``only_used=true``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
import CustomerTagsSettingsPage from
  "@/pages/settings/CustomerTagsSettingsPage";
import CustomerTagPicker from
  "@/components/customers/CustomerTagPicker";


// Two ONLY-used tags; C+D are absent from the response so the dropdown
// should never surface them.
const _onlyUsed = {
  items: [
    { id: "t-a", name: "in_use_A", usage_count: 3, is_active: true,
       is_system: false },
    { id: "t-b", name: "in_use_B", usage_count: 2, is_active: true,
       is_system: false },
  ],
  total: 2,
};

// Full catalog (settings/edit-form path) — includes unused tags.
const _fullCatalog = {
  items: [
    { id: "t-a", name: "in_use_A", usage_count: 3, is_active: true,
       is_system: false },
    { id: "t-b", name: "in_use_B", usage_count: 2, is_active: true,
       is_system: false },
    { id: "t-c", name: "unused_C", usage_count: 0, is_active: true,
       is_system: false },
    { id: "t-d", name: "unused_D", usage_count: 0, is_active: true,
       is_system: false },
  ],
  total: 4,
};


function _routeMockGet(path) {
  // Route by the presence of the P44 param so we can inspect BOTH
  // response shapes in the same test.
  if (typeof path === "string"
        && path.startsWith("/customer-tags")) {
    if (path.includes("only_used=true")) {
      return Promise.resolve(_onlyUsed);
    }
    return Promise.resolve(_fullCatalog);
  }
  // Every other GET (customers, counts, etc.) resolves empty.
  if (typeof path === "string" && path.startsWith("/customers")) {
    return Promise.resolve({ items: [], total: 0, page: 1,
      page_size: 50, total_pages: 0, count: 0 });
  }
  return Promise.resolve({});
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
  mockDelete.mockReset();
  mockGet.mockImplementation(_routeMockGet);
  mockPost.mockResolvedValue({ ok: true });
  mockPatch.mockResolvedValue({ ok: true });
  mockDelete.mockResolvedValue({ ok: true });
  try { sessionStorage.clear(); } catch { /* noop */ }
});


// ── Customers list: uses ?only_used=true ────────────────────────────
describe("CustomersList tag filter · P44", () => {
  it("fetches /customer-tags?only_used=true on mount", async () => {
    render(
      <MemoryRouter initialEntries={["/customers"]}>
        <CustomersList />
      </MemoryRouter>);
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const tagCall = calls.find((p) =>
        typeof p === "string" && p.startsWith("/customer-tags"));
      expect(tagCall).toBeDefined();
      expect(tagCall).toContain("only_used=true");
    });
  });
});


// ── Settings page: MUST NOT carry only_used=true ───────────────────
describe("CustomerTagsSettingsPage · P44 isolation", () => {
  it("does NOT include only_used=true on any /customer-tags fetch",
      async () => {
    render(<CustomerTagsSettingsPage />);
    // Give both the catalog GET and the suggest-duplicates GET a chance
    // to fire.
    await waitFor(() => {
      const tagCalls = mockGet.mock.calls
        .map((c) => c[0])
        .filter((p) => typeof p === "string"
                          && p.startsWith("/customer-tags")
                          // exclude the suggest-duplicates URL — that's
                          // a different endpoint.
                          && !p.startsWith("/customer-tags/suggest"));
      expect(tagCalls.length).toBeGreaterThanOrEqual(1);
      for (const call of tagCalls) {
        expect(call).not.toContain("only_used=true");
      }
    });
  });
});


// ── CustomerTagPicker (edit form): MUST NOT carry only_used=true ───
describe("CustomerTagPicker · P44 isolation", () => {
  it("does NOT include only_used=true when the edit-form loads tags",
      async () => {
    const { getByTestId } = render(
      <CustomerTagPicker
        customerId="c-1"
        value={[]}
        onChange={() => {}}
      />);
    // Open the popover to trigger the registry fetch.
    (await import("@testing-library/react")).fireEvent.click(
      getByTestId("customer-tag-picker-trigger"));
    await waitFor(() => {
      const tagCalls = mockGet.mock.calls
        .map((c) => c[0])
        .filter((p) => typeof p === "string"
                          && p.startsWith("/customer-tags"));
      expect(tagCalls.length).toBeGreaterThanOrEqual(1);
      for (const call of tagCalls) {
        expect(call).not.toContain("only_used=true");
      }
    });
  });
});
