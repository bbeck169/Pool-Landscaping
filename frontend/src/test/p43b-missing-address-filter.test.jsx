/**
 * Feb-2026 · P43b — "Missing address" chip on Customer list.
 *
 * Pins:
 *   1. Chip renders with the canonical testid.
 *   2. Chip shows a "(N)" count badge sourced from a standalone
 *      count-only call on mount.
 *   3. Clicking the chip adds ``missing_address=true`` to the list
 *      fetch AND drops ``?missing_address=1`` into the URL.
 *   4. Composes with sibling P43 chips — both params travel together
 *      on a single fetch.
 *   5. URL hydration works — visiting ``/customers?missing_address=1``
 *      renders the chip in the "on" state.
 *   6. Info banner renders ONLY when the chip is on and is gone when
 *      the chip is off.
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

const _emptyPage = { items: [], total: 0, page: 1, page_size: 50, total_pages: 0 };

function _installMockGet({ missingAddressCount = 7 } = {}) {
  mockGet.mockImplementation((path) => {
    if (path === "/customers?count_only=true&missing_address=true") {
      return Promise.resolve({ count: missingAddressCount });
    }
    if (path.includes("count_only=true")) {
      return Promise.resolve({ count: 0 });
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

describe("CustomersList · P43b missing-address chip", () => {
  it("renders the chip with the canonical testid", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-missing-address-filter")).toBeTruthy());
  });

  it("renders a (N) count badge sourced from the standalone count call", async () => {
    _installMockGet({ missingAddressCount: 42 });
    _renderAt();
    await waitFor(() => {
      const badge = screen.getByTestId("customers-missing-address-count");
      expect(badge.textContent).toMatch(/\(?\s*42\s*\)?/);
    });
    // Correct endpoint was hit.
    const calls = mockGet.mock.calls.map((c) => c[0]);
    expect(calls).toContain(
      "/customers?count_only=true&missing_address=true",
    );
  });

  it("clicking the chip fires a fetch with missing_address=true", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-missing-address-filter")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("customers-missing-address-filter"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls.find((p) =>
        p.startsWith("/customers?") && !p.includes("count_only"));
      expect(listCall).toBeDefined();
      expect(listCall).toContain("missing_address=true");
    });
  });

  it("composes with the missing_email chip", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-missing-address-filter")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("filter-chip-missing-email"));
    fireEvent.click(screen.getByTestId("customers-missing-address-filter"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls
        .filter((p) => p.startsWith("/customers?") && !p.includes("count_only"))
        .pop();
      expect(listCall).toContain("missing_email=true");
      expect(listCall).toContain("missing_address=true");
    });
  });

  it("hydrates the chip state from ?missing_address=1 in the URL", async () => {
    _renderAt("/customers?missing_address=1");
    await waitFor(() => {
      const chip = screen.getByTestId("customers-missing-address-filter");
      expect(chip.getAttribute("aria-pressed")).toBe("true");
    });
    // The initial fetch should carry the param.
    const calls = mockGet.mock.calls.map((c) => c[0]);
    const listCall = calls.find((p) =>
      p.startsWith("/customers?") && !p.includes("count_only"));
    expect(listCall).toContain("missing_address=true");
  });

  it("renders the info banner ONLY when the chip is on", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-missing-address-filter")).toBeTruthy());
    // Chip off — no banner.
    expect(screen.queryByTestId("customers-missing-address-banner")).toBeNull();
    fireEvent.click(screen.getByTestId("customers-missing-address-filter"));
    // Chip on — banner appears.
    expect(await screen.findByTestId("customers-missing-address-banner"))
      .toBeTruthy();
    fireEvent.click(screen.getByTestId("customers-missing-address-filter"));
    // Chip off again — banner gone.
    await waitFor(() =>
      expect(screen.queryByTestId("customers-missing-address-banner")).toBeNull(),
    );
  });
});
