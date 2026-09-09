/**
 * Feb-2026 · P45 — Customer list "More filters" dropdown.
 *
 * Consolidates the pre-P45 chip strip (No email / No phone / Missing
 * address / No payment / Portal status / Show deleted / Show merged /
 * Merge candidates) into a single grouped dropdown. Missing card
 * stays on the primary chip row and is NOT inside the dropdown.
 *
 * Pins:
 *   1. Trigger renders with the canonical testid + accessible ARIA.
 *   2. Panel is always-mounted (``hidden`` toggle) so existing
 *      filter testids resolve without opening the dropdown first.
 *   3. Trigger summary reads "All" with active=0, updates as chips
 *      toggle, and shows a numeric badge when active > 0.
 *   4. Clear button resets every consolidated filter to its zero
 *      state.
 *   5. Missing card chip is OUTSIDE the dropdown (primary row).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockGet = vi.fn();
const mockPost = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ role: "admin", effectiveRole: "admin" }),
}));

import CustomersList from "@/pages/customers/CustomersList";

function _installMockGet({ items = [] } = {}) {
  mockGet.mockImplementation((path) => {
    if (path.includes("count_only=true")) return Promise.resolve({ count: 42 });
    return Promise.resolve({
      items, total: items.length, page: 1, page_size: 50,
      total_pages: items.length ? 1 : 0,
    });
  });
}

function _renderAt(url = "/customers", opts = {}) {
  _installMockGet(opts);
  return render(
    <MemoryRouter initialEntries={[url]}>
      <CustomersList />
    </MemoryRouter>);
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe("CustomersList · P45 More filters dropdown", () => {
  it("trigger renders with canonical testid + ARIA", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    const trg = screen.getByTestId("customers-more-filters-dropdown");
    expect(trg.getAttribute("aria-haspopup")).toBe("dialog");
    expect(trg.getAttribute("aria-expanded")).toBe("false");
    expect(trg.getAttribute("aria-controls")).toBe("customers-more-filters-panel");
  });

  it("summary reads 'All' by default and updates when a chip toggles", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-more-filters-summary")).toBeTruthy());
    expect(screen.getByTestId("customers-more-filters-summary").textContent)
      .toBe("All");
    fireEvent.click(screen.getByTestId("customers-missing-address-filter"));
    await waitFor(() => {
      expect(screen.getByTestId("customers-more-filters-summary").textContent)
        .toMatch(/Missing address/);
      expect(screen.getByTestId("customers-more-filters-active-count").textContent)
        .toBe("1");
    });
    fireEvent.click(screen.getByTestId("customers-no-payment-filter"));
    await waitFor(() => {
      // With 2 active, summary is "First +1".
      expect(screen.getByTestId("customers-more-filters-summary").textContent)
        .toMatch(/\+1$/);
      expect(screen.getByTestId("customers-more-filters-active-count").textContent)
        .toBe("2");
    });
  });

  it("clicking the trigger flips aria-expanded", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    const trg = screen.getByTestId("customers-more-filters-dropdown");
    expect(trg.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trg);
    await waitFor(() =>
      expect(trg.getAttribute("aria-expanded")).toBe("true"));
    fireEvent.click(trg);
    await waitFor(() =>
      expect(trg.getAttribute("aria-expanded")).toBe("false"));
  });

  it("Clear resets every consolidated filter to its zero state", async () => {
    _renderAt("/customers?missing_address=1&has_payment_method=0&portal_activated=1");
    await waitFor(() => expect(
      screen.getByTestId("customers-more-filters-clear")).toBeTruthy());
    // Three filters should be active on hydration.
    await waitFor(() => {
      expect(screen.getByTestId("customers-more-filters-active-count").textContent)
        .toBe("3");
    });
    fireEvent.click(screen.getByTestId("customers-more-filters-clear"));
    await waitFor(() => {
      expect(screen.getByTestId("customers-more-filters-summary").textContent)
        .toBe("All");
      expect(
        screen.queryByTestId("customers-more-filters-active-count"),
      ).toBeNull();
      expect(
        screen.getByTestId("customers-missing-address-filter")
          .getAttribute("aria-pressed"),
      ).toBe("false");
      expect(
        screen.getByTestId("customers-no-payment-filter")
          .getAttribute("aria-pressed"),
      ).toBe("false");
      expect(
        screen.getByTestId("customers-portal-status-any")
          .getAttribute("aria-pressed"),
      ).toBe("true");
    });
  });

  it("Missing card chip stays OUTSIDE the dropdown panel", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    const panel = document.getElementById("customers-more-filters-panel");
    expect(panel).toBeTruthy();
    // Missing card testid must NOT be nested inside the panel.
    const missingCardBtn = screen.queryByTestId("customers-filter-missing-card");
    if (missingCardBtn) {
      expect(panel.contains(missingCardBtn)).toBe(false);
    }
  });

  it("Portal status inside dropdown is a radio group (role=radio)", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-portal-status-filter")).toBeTruthy());
    const group = screen.getByTestId("customers-portal-status-filter");
    expect(group.getAttribute("role")).toBe("radiogroup");
    const any = screen.getByTestId("customers-portal-status-any");
    expect(any.getAttribute("role")).toBe("radio");
    // Tri-state semantics preserved: default Any is selected.
    expect(any.getAttribute("aria-pressed")).toBe("true");
  });

  it("Escape key closes the panel", async () => {
    _renderAt();
    await waitFor(() => expect(
      screen.getByTestId("customers-more-filters-dropdown")).toBeTruthy());
    const trg = screen.getByTestId("customers-more-filters-dropdown");
    fireEvent.click(trg);
    await waitFor(() =>
      expect(trg.getAttribute("aria-expanded")).toBe("true"));
    const panel = document.getElementById("customers-more-filters-panel");
    fireEvent.keyDown(panel, { key: "Escape" });
    await waitFor(() =>
      expect(trg.getAttribute("aria-expanded")).toBe("false"));
  });
});
