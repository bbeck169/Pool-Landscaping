/**
 * Feb-2026 · P43c — "Portal status" tri-state segmented control.
 *
 * Pins:
 *   1. The tri-state control renders with the canonical container
 *      testid and per-option testids.
 *   2. Default state is "Any" (no filter).
 *   3. Both count badges hydrate from parallel ``count_only`` calls.
 *   4. Clicking "Activated" fires a fetch carrying
 *      ``portal_activated=true`` and writes ``portal_activated=1`` to
 *      the URL.
 *   5. Clicking "Not activated" swaps to ``portal_activated=false``
 *      + ``portal_activated=0`` in the URL.
 *   6. Clicking "Any" clears the filter + drops the URL param.
 *   7. Composes AND with the P43b missing-address chip on a single
 *      fetch.
 *   8. URL hydration works for both truth values.
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

function _installMockGet(overrides = {}) {
  const counts = {
    "/customers?count_only=true&missing_address=true": { count: 0 },
    "/customers?count_only=true&portal_activated=true": { count: 10 },
    "/customers?count_only=true&portal_activated=false": { count: 18 },
    ...overrides,
  };
  mockGet.mockImplementation((path) => {
    if (path in counts) return Promise.resolve(counts[path]);
    if (path.includes("count_only=true")) return Promise.resolve({ count: 0 });
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

describe("CustomersList · P43c portal-status filter", () => {
  it("renders the segmented control + all three options", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-portal-status-filter")).toBeTruthy());
    expect(screen.getByTestId("customers-portal-status-any")).toBeTruthy();
    expect(screen.getByTestId("customers-portal-status-activated")).toBeTruthy();
    expect(screen.getByTestId("customers-portal-status-not-activated")).toBeTruthy();
  });

  it("defaults to Any (no filter)", async () => {
    _renderAt();
    await waitFor(() => {
      const control = screen.getByTestId("customers-portal-status-filter");
      expect(control.getAttribute("data-value")).toBe("any");
      expect(screen.getByTestId("customers-portal-status-any")
        .getAttribute("aria-pressed")).toBe("true");
    });
  });

  it("hydrates count badges from the parallel count calls", async () => {
    _renderAt();
    await waitFor(() => {
      const aCount = screen.getByTestId("customers-portal-status-activated-count");
      const naCount = screen.getByTestId("customers-portal-status-not-activated-count");
      expect(aCount.textContent).toMatch(/10/);
      expect(naCount.textContent).toMatch(/18/);
    });
    const calls = mockGet.mock.calls.map((c) => c[0]);
    expect(calls).toContain(
      "/customers?count_only=true&portal_activated=true",
    );
    expect(calls).toContain(
      "/customers?count_only=true&portal_activated=false",
    );
  });

  it("clicking Activated fires a fetch with portal_activated=true", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-portal-status-activated")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("customers-portal-status-activated"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls.find((p) =>
        p.startsWith("/customers?") && !p.includes("count_only"));
      expect(listCall).toContain("portal_activated=true");
    });
  });

  it("clicking Not activated fires a fetch with portal_activated=false", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-portal-status-not-activated")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("customers-portal-status-not-activated"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls.find((p) =>
        p.startsWith("/customers?") && !p.includes("count_only"));
      expect(listCall).toContain("portal_activated=false");
    });
  });

  it("clicking Any clears the filter", async () => {
    _renderAt("/customers?portal_activated=1");
    // Wait for hydration.
    await waitFor(() => {
      expect(screen.getByTestId("customers-portal-status-activated")
        .getAttribute("aria-pressed")).toBe("true");
    });
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("customers-portal-status-any"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls.find((p) =>
        p.startsWith("/customers?") && !p.includes("count_only"));
      expect(listCall).toBeDefined();
      expect(listCall).not.toContain("portal_activated=");
    });
  });

  it("composes AND with the missing-address chip", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-missing-address-filter")).toBeTruthy());
    mockGet.mockClear();
    fireEvent.click(screen.getByTestId("customers-missing-address-filter"));
    fireEvent.click(screen.getByTestId("customers-portal-status-not-activated"));
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      const listCall = calls
        .filter((p) => p.startsWith("/customers?") && !p.includes("count_only"))
        .pop();
      expect(listCall).toContain("missing_address=true");
      expect(listCall).toContain("portal_activated=false");
    });
  });

  it("URL hydration: ?portal_activated=1 shows Activated selected", async () => {
    _renderAt("/customers?portal_activated=1");
    await waitFor(() => {
      const control = screen.getByTestId("customers-portal-status-filter");
      expect(control.getAttribute("data-value")).toBe("activated");
      expect(screen.getByTestId("customers-portal-status-activated")
        .getAttribute("aria-pressed")).toBe("true");
    });
    const listCalls = mockGet.mock.calls.map((c) => c[0])
      .filter((p) => p.startsWith("/customers?") && !p.includes("count_only"));
    expect(listCalls[0]).toContain("portal_activated=true");
  });

  it("URL hydration: ?portal_activated=0 shows Not activated selected", async () => {
    _renderAt("/customers?portal_activated=0");
    await waitFor(() => {
      const control = screen.getByTestId("customers-portal-status-filter");
      expect(control.getAttribute("data-value")).toBe("not_activated");
      expect(screen.getByTestId("customers-portal-status-not-activated")
        .getAttribute("aria-pressed")).toBe("true");
    });
  });
});
