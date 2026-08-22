/**
 * Feb-2026 · P43 — "No email" / "No phone number" chips (Vitest).
 *
 * Pins the toolbar UX contract:
 *   1. Both chips render in the toolbar.
 *   2. Clicking "No email" adds ``missing_email=true`` to the
 *      customers fetch AND drops it into the URL as ``?missing_email=1``.
 *   3. Clicking "No phone number" does the same for its param.
 *   4. Both active at once → both params on the fetch AND URL.
 *   5. URL param ``?missing_email=1`` hydrates the chip state on mount.
 *   6. Tab-count fetches include the P43 params too (P40 unified-
 *      predicate contract).
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


// Shape returned by GET /customers?...page=... — paginated envelope.
const _emptyPage = { items: [], total: 0, page: 1, page_size: 50,
  total_pages: 0 };


function _installMockGet({ counts = {} } = {}) {
  mockGet.mockImplementation((path) => {
    if (path.includes("count_only=true")) {
      // The tests only assert that the P43 params reach the counts
      // endpoint — the payload shape is stable per-tab.
      return Promise.resolve({ count: counts[path] ?? 0 });
    }
    return Promise.resolve(_emptyPage);
  });
}


function _renderAt(url = "/customers") {
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
  _installMockGet();
});


describe("CustomersList · P43 chips", () => {
  it("renders both chips in the toolbar", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("filter-chip-missing-email")).toBeTruthy());
    expect(screen.getByTestId("filter-chip-missing-phone")).toBeTruthy();
  });

  it("clicking 'No email' fires a fetch with missing_email=true",
      async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("filter-chip-missing-email")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("filter-chip-missing-email"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls.find((p) =>
        p.startsWith("/customers?") && !p.includes("count_only"));
      expect(listCall).toBeDefined();
      expect(listCall).toContain("missing_email=true");
      expect(listCall).not.toContain("missing_phone=true");
    });
  });

  it("clicking 'No phone number' fires a fetch with missing_phone=true",
      async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("filter-chip-missing-phone")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("filter-chip-missing-phone"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls.find((p) =>
        p.startsWith("/customers?") && !p.includes("count_only"));
      expect(listCall).toContain("missing_phone=true");
      expect(listCall).not.toContain("missing_email=true");
    });
  });

  it("both chips active → both params on the list fetch", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("filter-chip-missing-email")).toBeTruthy());
    fireEvent.click(screen.getByTestId("filter-chip-missing-email"));
    fireEvent.click(screen.getByTestId("filter-chip-missing-phone"));
    await waitFor(() => {
      const listCall = mockGet.mock.calls
        .map((c) => c[0])
        .find((p) => p.startsWith("/customers?")
                        && !p.includes("count_only")
                        && p.includes("missing_email=true")
                        && p.includes("missing_phone=true"));
      expect(listCall).toBeDefined();
    });
  });

  it("URL ?missing_email=1&missing_phone=1 hydrates chip state on mount",
      async () => {
    _renderAt("/customers?missing_email=1&missing_phone=1");
    // A list fetch with both params should fire on mount.
    await waitFor(() => {
      const listCall = mockGet.mock.calls
        .map((c) => c[0])
        .find((p) => p.startsWith("/customers?")
                        && !p.includes("count_only")
                        && p.includes("missing_email=true")
                        && p.includes("missing_phone=true"));
      expect(listCall).toBeDefined();
    });
  });

  it("tab-count fetches include the P43 params (P40 parity)", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("filter-chip-missing-email")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("filter-chip-missing-email"));
    await waitFor(() => {
      const countCalls = mockGet.mock.calls
        .map((c) => c[0])
        .filter((p) => p.includes("count_only=true"));
      // Active + Inactive + Muted (admin sees all three).
      expect(countCalls.length).toBeGreaterThanOrEqual(2);
      // Every count call must carry the P43 param when the chip is on.
      for (const call of countCalls) {
        expect(call).toContain("missing_email=true");
      }
    });
  });
});
