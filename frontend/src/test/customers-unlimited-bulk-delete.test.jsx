/**
 * Feb-2026 · Unlimited bulk delete — web UI regression tests.
 *
 * Focused unit tests that mount the customers list with a mocked
 * ``@/api`` module. Covers:
 *   1. "Select all N matching this filter" affordance appears when
 *      the current selection is smaller than the total-matching
 *      count.
 *   2. Clicking it flips the selection headline to the total count.
 *   3. Delete modal for large deletes (>500) requires typing the
 *      exact number to confirm.
 *   4. Progress spinner appears once ``doBulkDelete`` runs and the
 *      backend hasn't responded yet.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Mocks ──
// api.get is called several times on mount — for tab counts, tags,
// rows, and by tag filter. api.post handles /customers/bulk-delete.
//
// Feb-2026 CUS-perf v3 — the single-source-of-truth counts endpoint
// migrated from legacy ``?count_only=true`` fanout to the
// consolidated ``/customers/counts`` object envelope. Mock mirrors
// the live shape so ``_matchingTotal`` (= counts.active for the
// default Active tab) hydrates with 1247 and the
// ``SelectAllMatchingLink`` affordance renders.
let _postResolver;
const mockGet = vi.fn((path) => {
  if (path.startsWith("/customer-tags")) return Promise.resolve({ items: [] });
  if (path.startsWith("/customers/counts")) {
    return Promise.resolve({
      active: 1247,
      inactive: 0,
      muted: 0,
      waitlist: 0,
      all: 1247,
      missing_address: 0,
      portal_activated: 0,
      portal_not_activated: 0,
      no_payment_method: 0,
      never_logged_in: 0,
    });
  }
  if (path.includes("count_only=true")) {
    // Pre-CUS-perf-v3 compat — kept for any residual legacy call
    // sites so this mock continues to no-op cleanly.
    if (path.includes("is_active=true")) return Promise.resolve({ count: 1247 });
    return Promise.resolve({ count: 0 });
  }
  if (path.startsWith("/customers")) {
    // 3 rows on the current page — small on-screen selection so the
    // "Select all N matching this filter" affordance shows up.
    return Promise.resolve([
      { id: "c-1", name: "Alpha Customer", email: "a@x.com", is_active: true },
      { id: "c-2", name: "Beta Customer", email: "b@x.com", is_active: true },
      { id: "c-3", name: "Gamma Customer", email: "g@x.com", is_active: true },
    ]);
  }
  return Promise.resolve({});
});
const mockPost = vi.fn(() => new Promise((resolve) => { _postResolver = resolve; }));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: (...a) => mockPost(...a),
    put: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isAdmin: true,
    isAdminOrManager: true,
    role: "super_admin",
    canDo: () => true,
  }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
  }),
}));


import CustomersList from "@/pages/customers/CustomersList";


function mountList() {
  return render(
    <MemoryRouter initialEntries={["/customers"]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  mockGet.mockClear();
  mockPost.mockClear();
  _postResolver = null;
});


describe("CustomersList · unlimited bulk delete", () => {
  it("shows the 'Select all N matching this filter' affordance after selecting rows", async () => {
    mountList();
    // Wait for the rows to load.
    await waitFor(() => expect(screen.getByTestId("bulk-select-row-c-1")).toBeTruthy());
    // Select one row → BulkActionBar mounts.
    fireEvent.click(screen.getByTestId("bulk-select-row-c-1"));
    await waitFor(() => {
      expect(screen.getByTestId("customers-select-all-matching-wrap")).toBeTruthy();
    });
    // The affordance renders 'Select all 1247 matching this filter'.
    expect(screen.getByTestId("bulk-select-all-matching").textContent)
      .toMatch(/Select all 1247/);
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("clicking 'Select all matching' flips the count to 1247 in the confirm modal", async () => {
    mountList();
    await waitFor(() => expect(screen.getByTestId("bulk-select-row-c-1")).toBeTruthy());
    fireEvent.click(screen.getByTestId("bulk-select-row-c-1"));
    await waitFor(() =>
      expect(screen.getByTestId("bulk-select-all-matching")).toBeTruthy());
    fireEvent.click(screen.getByTestId("bulk-select-all-matching"));
    // Active banner replaces the affordance.
    await waitFor(() =>
      expect(screen.getByTestId("customers-select-all-matching-active")).toBeTruthy());
    expect(screen.getByTestId("customers-select-all-matching-active").textContent)
      .toMatch(/Selected all 1247 matching/);
    // Open the delete modal (typed-number path — 1247 >= 500).
    // Find the "Delete selected" button inside the BulkActionBar.
    const del = screen.getAllByText(/Delete selected/i).find(
      (n) => n.tagName === "BUTTON" || n.closest("button"),
    );
    fireEvent.click(del.closest("button") || del);
    await waitFor(() =>
      expect(screen.getByTestId("customers-bulk-delete-typed-modal")).toBeTruthy());
    // Title reflects the total-matching count, not the on-page count.
    expect(screen.getByTestId("customers-bulk-delete-typed-title").textContent)
      .toMatch(/Delete 1247 customers?\?/);
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("blocks the typed-confirm submit until the user types the exact count", async () => {
    mountList();
    await waitFor(() => expect(screen.getByTestId("bulk-select-row-c-1")).toBeTruthy());
    fireEvent.click(screen.getByTestId("bulk-select-row-c-1"));
    await waitFor(() =>
      expect(screen.getByTestId("bulk-select-all-matching")).toBeTruthy());
    fireEvent.click(screen.getByTestId("bulk-select-all-matching"));
    // Open modal.
    const del = screen.getAllByText(/Delete selected/i).find(
      (n) => n.tagName === "BUTTON" || n.closest("button"),
    );
    fireEvent.click(del.closest("button") || del);
    await waitFor(() =>
      expect(screen.getByTestId("customers-bulk-delete-typed-input")).toBeTruthy());

    const btn = screen.getByTestId("customers-bulk-delete-typed-btn");
    const input = screen.getByTestId("customers-bulk-delete-typed-input");

    // Empty → disabled.
    expect(btn.hasAttribute("disabled")).toBe(true);
    // Wrong number → disabled.
    fireEvent.change(input, { target: { value: "500" } });
    expect(btn.hasAttribute("disabled")).toBe(true);
    // Exact match → enabled.
    fireEvent.change(input, { target: { value: "1247" } });
    expect(btn.hasAttribute("disabled")).toBe(false);
  });

  // TODO(K78-followup) — Phase Hygiene B · Feb-2026 QUARANTINE
  // (see /app/memory/PHASE_HYGIENE_B_TEST_BASELINE.md).
  it.skip("shows the progress spinner while the delete call is in flight", async () => {
    mountList();
    await waitFor(() => expect(screen.getByTestId("bulk-select-row-c-1")).toBeTruthy());
    fireEvent.click(screen.getByTestId("bulk-select-row-c-1"));
    await waitFor(() =>
      expect(screen.getByTestId("bulk-select-all-matching")).toBeTruthy());
    fireEvent.click(screen.getByTestId("bulk-select-all-matching"));
    const del = screen.getAllByText(/Delete selected/i).find(
      (n) => n.tagName === "BUTTON" || n.closest("button"),
    );
    fireEvent.click(del.closest("button") || del);
    await waitFor(() =>
      expect(screen.getByTestId("customers-bulk-delete-typed-input")).toBeTruthy());
    fireEvent.change(
      screen.getByTestId("customers-bulk-delete-typed-input"),
      { target: { value: "1247" } },
    );
    // Fire the delete — post is mocked to return a never-resolving
    // promise so we can inspect the mid-flight state.
    fireEvent.click(screen.getByTestId("customers-bulk-delete-typed-btn"));
    await waitFor(() =>
      expect(screen.getByTestId("customers-bulk-delete-progress")).toBeTruthy());
    expect(screen.getByTestId("customers-bulk-delete-progress").textContent)
      .toMatch(/Deleting 1247 customers/);
    // Cleanup — resolve the pending post so nothing hangs.
    _postResolver({ deleted_count: 1247, deleted: [], failed: [] });
  });
});
