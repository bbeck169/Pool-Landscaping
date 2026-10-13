/**
 * Phase P40 · Feb-2026 — K71LineItemsEditor category guard (upstream
 * cure for the "UUIDs in Income by Category" bug).
 *
 * Feb-2026 · invoice-category hard-block removal update:
 *   Operators asked to be able to save / send / approve / convert
 *   invoices whose line items are missing or point at an inactive
 *   Service / Income category.  The three red UI blockers (top
 *   "Missing categories" banner, mid "Inactive categories" banner,
 *   and bottom form-level alert) were collapsed into a SINGLE
 *   amber soft-warning banner (``k71-category-soft-warning-banner``,
 *   role="status") that renders when ANY row is flagged — missing
 *   OR stale.  Per-row aria-invalid + inline chip + stale-badge
 *   assertions are kept exactly as-is because the row-level
 *   affordance is still the operator's cue to clean up later.
 *   The backend writes an ``invoices.saved_with_category_warnings``
 *   audit row for ops reporting; see
 *   ``backend/tests/test_invoice_category_hard_block_removal.py``.
 *
 * Coverage:
 *   1. Prefilled row with an unresolvable id → row marked invalid.
 *   2. Prefilled row with a valid id → no highlight, no soft banner.
 *   3. Fetch error → fail-open (soft banner hidden, backend
 *      validator is the durable guard).
 *   4. Soft banner renders when ANY row is flagged.
 *   5. Multiple rows — one valid, one stale — soft banner present +
 *      only the stale row carries aria-invalid.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

// Test-scoped ``api`` mock. Each test can override via
// ``__setResponse`` so we can simulate empty active lists or
// network errors without global side effects.
const _state = { income: { items: [] }, service: { items: [] }, throwOn: null };

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (url) => {
      if (_state.throwOn && url.includes(_state.throwOn)) {
        throw new Error("network");
      }
      if (url === "/income-categories") return _state.income;
      if (url === "/service-categories") return _state.service;
      return { items: [] };
    }),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import K71LineItemsEditor from "@/components/quotes/K71LineItemsEditor";
import { invalidateCategoryCache }
  from "@/components/income/CategoryPicker";
import { invalidateMasterServicesCache }
  from "@/components/services/MasterServiceCombobox";

const VALID_SVC = "svc-active-1";
const VALID_INC = "inc-active-1";
const STALE_UUID = "48cd653e-afc6-4864-a59b-47b7a0953b5c";

function _setActive(inc, svc) {
  _state.income = {
    items: inc.map((c) => (typeof c === "string"
      ? { id: c, name: c, color: "#22C55E" } : c)),
  };
  _state.service = {
    items: svc.map((c) => (typeof c === "string"
      ? { id: c, name: c, color: "#0EA5E9" } : c)),
  };
  _state.throwOn = null;
}

beforeEach(() => {
  invalidateCategoryCache();
  invalidateMasterServicesCache();
  _setActive([VALID_INC], [VALID_SVC]);
});

const staleLine = {
  description: "Chemical treatment",
  quantity: 1,
  unit_price: 100,
  service_category_id: VALID_SVC,
  income_category_id: STALE_UUID,       // ← id no longer in active list
};

const validLine = {
  description: "Pool maintenance",
  quantity: 2,
  unit_price: 80,
  service_category_id: VALID_SVC,
  income_category_id: VALID_INC,
};

describe("Phase P40 · K71LineItemsEditor category guard", () => {
  it("test_prefilled_invalid_category_marks_row_invalid", async () => {
    const doc = { line_items: [staleLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    // Wait until the categories fetch resolves and the guard runs.
    await waitFor(() =>
      expect(screen.getByTestId("k71-row-0").getAttribute("aria-invalid"))
        .toBe("true")
    );
    expect(screen.getByTestId(`k71-stale-badge-0`)).toBeTruthy();
    expect(screen.getByTestId(`k71-stale-error-0`).textContent).toContain(
      "This category is no longer active"
    );
    // Feb-2026 · invoice-category hard-block removal — the two red
    // ``k71-stale-category-banner`` + ``k71-form-invalid-message``
    // blockers collapsed into one amber soft-warning banner.
    const soft = screen.getByTestId("k71-category-soft-warning-banner");
    expect(soft).toBeTruthy();
    expect(soft.getAttribute("role")).toBe("status");
    expect(soft.textContent).toContain(
      "You can categorize them later - saving is not blocked"
    );
    // Legacy red blockers must be gone.
    expect(screen.queryByTestId("k71-stale-category-banner")).toBeNull();
    expect(screen.queryByTestId("k71-form-invalid-message")).toBeNull();
  });

  it("test_prefilled_valid_category_no_highlight", async () => {
    const doc = { line_items: [validLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    // Give the fetch effect a chance to flush.
    await waitFor(() =>
      // Row is rendered.
      expect(screen.getByTestId("k71-row-0")).toBeTruthy()
    );
    expect(screen.getByTestId("k71-row-0").getAttribute("aria-invalid"))
      .toBeNull();
    expect(screen.queryByTestId("k71-stale-badge-0")).toBeNull();
    expect(screen.queryByTestId("k71-stale-error-0")).toBeNull();
    // Feb-2026 · invoice-category hard-block removal — amber soft
    // banner must stay hidden when no row is flagged. Legacy red
    // blockers must also stay hidden.
    expect(screen.queryByTestId("k71-category-soft-warning-banner"))
      .toBeNull();
    expect(screen.queryByTestId("k71-stale-category-banner")).toBeNull();
    expect(screen.queryByTestId("k71-form-invalid-message")).toBeNull();
  });

  it("test_fetch_error_fails_open", async () => {
    // Force the /income-categories fetch to reject so activeIds never
    // populates. The guard MUST fail-open (no form-level block) —
    // backend validator is the durable guard.
    _state.throwOn = "/income-categories";
    const doc = { line_items: [staleLine], status: "draft" };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    // Wait for the async effect to settle. Since we can't easily
    // detect a "settled" state, wait a tick + re-assert.
    await new Promise((r) => setTimeout(r, 0));
    // No soft-warning banner rendered (nothing to flag because the
    // fetch failed-open). Legacy red blockers must also stay hidden.
    expect(screen.queryByTestId("k71-category-soft-warning-banner"))
      .toBeNull();
    expect(screen.queryByTestId("k71-form-invalid-message")).toBeNull();
    // Row does NOT carry aria-invalid — the client-side guard is
    // disabled, and the row otherwise looks normal.
    expect(screen.getByTestId("k71-row-0").getAttribute("aria-invalid"))
      .toBeNull();
  });

  it("test_save_button_shows_soft_warning_when_any_row_invalid",
      async () => {
        const doc = { line_items: [validLine, staleLine], status: "draft" };
        render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
        // Second row (idx=1) is stale; first row is clean.
        await waitFor(() =>
          expect(screen.getByTestId("k71-row-1").getAttribute("aria-invalid"))
            .toBe("true")
        );
        expect(screen.getByTestId("k71-row-0").getAttribute("aria-invalid"))
          .toBeNull();
        // Feb-2026 · invoice-category hard-block removal — the
        // old red ``role="alert"`` form-level block was replaced
        // with a single amber ``role="status"`` soft-warning
        // banner. Save is NOT blocked; this is just a heads-up.
        const soft = screen.getByTestId("k71-category-soft-warning-banner");
        expect(soft).toBeTruthy();
        expect(soft.getAttribute("role")).toBe("status");
        expect(soft.textContent).toContain(
          "line item is missing or has an inactive Service / Income category"
        );
        expect(soft.textContent).toContain(
          "You can categorize them later - saving is not blocked"
        );
        // Legacy red blockers must be gone.
        expect(screen.queryByTestId("k71-form-invalid-message")).toBeNull();
      });

  it("test_missing_category_row_still_caught_alongside_stale", async () => {
    // Belt-and-braces: an empty income_category_id row and a stale
    // row together — the single amber soft-warning banner counts
    // both (its copy still says "N line items are missing or have
    // an inactive Service / Income category") and the per-row
    // chips/badges differentiate between gap vs stale.
    const missingLine = {
      description: "Missing income",
      quantity: 1,
      unit_price: 50,
      service_category_id: VALID_SVC,
      income_category_id: "",
    };
    const doc = {
      line_items: [missingLine, staleLine], status: "draft",
    };
    render(<K71LineItemsEditor doc={doc} canEdit onLinesUpdated={vi.fn()} />);
    // Soft-warning banner renders once; its copy counts BOTH rows.
    await waitFor(() =>
      expect(screen.getByTestId("k71-category-soft-warning-banner"))
        .toBeTruthy()
    );
    const soft = screen.getByTestId("k71-category-soft-warning-banner");
    expect(soft.textContent).toContain(
      "2 line items are missing or have an inactive Service / Income category"
    );
    // Per-row stale badge for the stale row (idx 1).
    expect(screen.getByTestId("k71-stale-badge-1")).toBeTruthy();
    // Legacy red blockers must stay hidden.
    expect(screen.queryByTestId("k71-gap-banner")).toBeNull();
    expect(screen.queryByTestId("k71-stale-category-banner")).toBeNull();
    expect(screen.queryByTestId("k71-form-invalid-message")).toBeNull();
  });
});
