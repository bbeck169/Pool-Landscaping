/**
 * Task G · Commit 4 · Feb-2026 — K71 Pricebook picker + banner-clear
 * frontend contract tests.
 *
 * Scope: everything the K71LineItemsEditor Pricebook picker
 * introduced in Commit 3 owns. NOT re-covered here:
 *   • The 18 pre-existing K71 suites — `k71-line-items-editor.test.jsx`
 *     (Add/Delete/Undo, banner truthiness, pencil visibility, etc.).
 *     Those stay green as-is after Commit 3.
 *   • Backend tenant-scoping of GET /api/items — pytest coverage in
 *     `backend/tests/test_p59_items_read_scoping.py` (Commit 2).
 *
 * Coverage (12 cases, matching the Commit-4 brief):
 *   1. Empty EditableRow renders search input; no dropdown at rest.
 *   2. Typing "chlor" fires exactly one debounced (250 ms)
 *      `GET /api/items?search=chlor&active=true&limit=50`.
 *   3. Two mocked rows render as bold name + description + money(price)
 *      + service_category_name + income_category_name badges.
 *   4. `k71-pricebook-search-loading` visible in-flight; then
 *      `k71-pricebook-search-empty` when the response is `[]`.
 *   5. Click a result → title / long_desc / unit_price /
 *      service_category_id / income_category_id all update.
 *   6. Decision #5 guard — picking an `item_type="service"` row sets
 *      service_category_id but leaves income_category_id untouched
 *      (fresh row stays empty; the operator picks manually via the
 *      existing CategoryPicker below).
 *   7. Decision #4 banner-clear — inline `attempted && !categoryId`
 *      errors (`k71-error-service-0` L335-341 + `k71-error-income-0`
 *      L356-362 of `K71LineItemsEditor.jsx`) evaporate after a pick
 *      with valid categories, via computed-prop recomputation; no
 *      re-render dance, no manual banner-hide code path.
 *   8. Backward-compat manual entry — free-typing a title without
 *      picking preserves current unit_price / category state.
 *   9. Enter-key does NOT get hijacked — bubbles from the picker
 *      input up to `EditableRow.handleKey`, which fires save.
 *  10. Stale-request cancellation — monotonic reqSeqRef counter
 *      discards a slow "chlor" response arriving after a fast
 *      "chlor2" response has already landed.
 *  11. Adjacent smoke — after a Pricebook pick, the sibling
 *      `<CategoryPicker>` on the same line still renders and its
 *      testid resolves (decision #3 non-regression).
 *  12. `_id:0` projection preserved — a stray `_id` on the mock
 *      response never leaks into the dropdown DOM (Task C safety
 *      net; the picker component never reads `row._id`).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";


// Mock the API client at module boundary. Every test overrides
// `api.get` per-scenario via `mockImplementation` — the default
// impl below keeps CategoryPicker + master-services URLs healthy
// so real CategoryPicker mounts cleanly under every test.
vi.mock("@/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}));

import { api } from "@/api";
import K71LineItemsEditor from "@/components/quotes/K71LineItemsEditor";
import { invalidateCategoryCache }
  from "@/components/income/CategoryPicker";


// Stub category rows used by the real CategoryPicker on every test.
const _INCOME_CATS = [
  { id: "inc-a", name: "Products Revenue", color: "#22C55E" },
  { id: "inc-b", name: "Services Revenue", color: "#3B82F6" },
];
const _SERVICE_CATS = [
  { id: "svc-a", name: "Landscape", color: "#10B981" },
  { id: "svc-b", name: "Pool Cleaning", color: "#0EA5E9" },
];

function _defaultApiGet(url) {
  if (url === "/income-categories") return { items: _INCOME_CATS };
  if (url === "/service-categories") return { items: _SERVICE_CATS };
  // Any /items?... URL returns [] by default — tests that care about
  // pricebook rows override via `mockImplementation` or
  // `mockImplementationOnce`.
  if (url.startsWith("/items?")) return [];
  return [];
}

function _mockItems(rows) {
  // Layered override — categories still resolve, only /items? changes.
  api.get.mockImplementation(async (url) => {
    if (url.startsWith("/items?")) return rows;
    return _defaultApiGet(url);
  });
}


// Sample Pricebook rows shaped like the real /api/items response.
// Fields the picker reads: id, name, description, unit_price,
// service_category_id, service_category_name, income_category_id,
// income_category_name, category, item_type.
const _CHLOR_PRODUCT = {
  id: "item-chlor",
  name: "Chlorine Tablets (25 lb)",
  description: "Weekly shock — 3 tablets per pool.",
  unit_price: 89.0,
  category: "Chemicals",
  item_type: "product",
  service_category_id: "svc-b",
  service_category_name: "Pool Cleaning",
  income_category_id: "inc-a",
  income_category_name: "Products Revenue",
};

const _POOL_LABOR = {
  id: "item-pool-labor",
  name: "Pool Labor (hourly)",
  description: "On-site pool maintenance labor.",
  unit_price: 45.0,
  category: "Labor",
  item_type: "product",
  service_category_id: "svc-b",
  service_category_name: "Pool Cleaning",
  income_category_id: "inc-b",
  income_category_name: "Services Revenue",
};

const _SERVICE_ROW = {
  id: "item-service-row",
  name: "Winterization Service",
  description: "End-of-season shutdown.",
  unit_price: 275.0,
  category: "Service",
  item_type: "service",
  service_category_id: "svc-a",
  service_category_name: "Landscape",
  // Per backend rule (routers/items.py :183-202) services carry no
  // income_category — the mock respects that so the guard's real
  // shape is exercised.
  income_category_id: null,
  income_category_name: null,
};


// Fresh-row line — no pre-filled category ids so the picker's
// auto-fill lands on empty slots.
function _emptyLine() {
  return {
    description: "",
    quantity: 1,
    unit_price: 0,
    long_description: "",
    service_category_id: "",
    income_category_id: "",
  };
}


beforeEach(() => {
  vi.useFakeTimers();
  invalidateCategoryCache();
  api.get.mockReset();
  api.get.mockImplementation(async (url) => _defaultApiGet(url));
});

afterEach(() => {
  vi.useRealTimers();
});


// Helper — enter edit mode on row 0 and let CategoryPicker's initial
// fetch settle so its inner state has hydrated before we assert.
async function _enterEditRow0(doc, extraProps = {}) {
  const utils = render(
    <K71LineItemsEditor doc={doc} canEdit
                         onLinesUpdated={vi.fn()}
                         {...extraProps} />,
  );
  fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
  await act(async () => { await Promise.resolve(); });
  return utils;
}


describe("Task G · K71 Pricebook picker · behaviour", () => {

  it("(1) renders the picker input; no dropdown at rest", async () => {
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);
    expect(screen.getByTestId("k71-input-item-0-input")).toBeTruthy();
    // No keystroke yet → picker's `showDropdown` gate is false.
    expect(screen.queryByTestId("k71-pricebook-search-dropdown"))
      .toBeNull();
  });

  it("(2) fires exactly one debounced /api/items call on keystroke", async () => {
    _mockItems([_CHLOR_PRODUCT]);
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chlor" } });

    // Under 250 ms — no call yet.
    await act(async () => { await vi.advanceTimersByTimeAsync(249); });
    const preCallCount = api.get.mock.calls.filter(
      ([u]) => typeof u === "string" && u.startsWith("/items?"),
    ).length;
    expect(preCallCount).toBe(0);

    // Cross the 250 ms boundary.
    await act(async () => { await vi.advanceTimersByTimeAsync(2); });
    const itemsCalls = api.get.mock.calls
      .map(([u]) => u)
      .filter((u) => typeof u === "string" && u.startsWith("/items?"));
    expect(itemsCalls).toHaveLength(1);
    expect(itemsCalls[0]).toBe("/items?search=chlor&active=true&limit=50");
  });

  it("(3) renders 2 result rows with name / description / price / badges", async () => {
    _mockItems([_CHLOR_PRODUCT, _POOL_LABOR]);
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chl" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });

    const dropdown = screen.getByTestId("k71-pricebook-search-dropdown");
    expect(dropdown).toBeTruthy();

    const rows = screen.getAllByTestId(/^k71-pricebook-search-item-\d+$/);
    expect(rows).toHaveLength(2);

    const row0 = rows[0];
    // Bold name + description + money-formatted price + category badges.
    expect(row0.textContent).toContain("Chlorine Tablets (25 lb)");
    expect(row0.textContent).toContain("Weekly shock");
    expect(row0.textContent).toContain("$89.00");
    expect(row0.textContent).toContain("Pool Cleaning");
    expect(row0.textContent).toContain("Products Revenue");

    const row1 = rows[1];
    expect(row1.textContent).toContain("Pool Labor (hourly)");
    expect(row1.textContent).toContain("$45.00");
    expect(row1.textContent).toContain("Services Revenue");
  });

  it("(4) shows loading testid in-flight then empty testid on []", async () => {
    // Slow-resolving mock so the loading state is observable.
    let resolvePending;
    api.get.mockImplementation(async (url) => {
      if (url.startsWith("/items?")) {
        return new Promise((r) => { resolvePending = () => r([]); });
      }
      return _defaultApiGet(url);
    });
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "zzz" } });

    // Cross the debounce boundary → api.get is now in flight but
    // hasn't resolved.
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    expect(screen.getByTestId("k71-pricebook-search-loading")).toBeTruthy();
    expect(screen.queryByTestId("k71-pricebook-search-empty")).toBeNull();

    // Resolve → empty state renders.
    await act(async () => {
      resolvePending();
      await vi.runAllTimersAsync();
    });
    expect(screen.queryByTestId("k71-pricebook-search-loading")).toBeNull();
    expect(screen.getByTestId("k71-pricebook-search-empty")).toBeTruthy();
  });

  it("(5) picking a product row auto-fills title / desc / price / both cats", async () => {
    _mockItems([_CHLOR_PRODUCT]);
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chl" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });

    fireEvent.click(screen.getByTestId("k71-pricebook-search-item-0"));
    await act(async () => { await Promise.resolve(); });

    expect(screen.getByTestId("k71-input-item-0-input").value)
      .toBe("Chlorine Tablets (25 lb)");
    expect(screen.getByTestId("k71-input-price-0").value).toBe("89");
    expect(screen.getByTestId("k71-input-longdesc-0").value)
      .toBe("Weekly shock — 3 tablets per pool.");

    // Both CategoryPickers now show the resolved names — this is
    // the observable proof that ``setServiceCategoryId`` +
    // ``setIncomeCategoryId`` fired with the item's ids.
    expect(screen.getByTestId("k71-service-picker-0").textContent)
      .toContain("Pool Cleaning");
    expect(screen.getByTestId("k71-income-picker-0").textContent)
      .toContain("Products Revenue");

    // Dropdown closes on pick.
    expect(screen.queryByTestId("k71-pricebook-search-dropdown"))
      .toBeNull();
  });

  it("(6) picking a service-type row skips income_category (decision #5)", async () => {
    _mockItems([_SERVICE_ROW]);
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    // Sanity — income picker starts on its placeholder.
    const incBefore =
      screen.getByTestId("k71-income-picker-0").textContent || "";

    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "wint" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    fireEvent.click(screen.getByTestId("k71-pricebook-search-item-0"));
    await act(async () => { await Promise.resolve(); });

    // Title / price / service-category filled from the pick.
    expect(screen.getByTestId("k71-input-item-0-input").value)
      .toBe("Winterization Service");
    expect(screen.getByTestId("k71-input-price-0").value).toBe("275");
    expect(screen.getByTestId("k71-service-picker-0").textContent)
      .toContain("Landscape");

    // Income picker is UNTOUCHED — guard held. The rendered text is
    // whatever it was pre-pick (placeholder for a fresh line).
    const incAfter =
      screen.getByTestId("k71-income-picker-0").textContent || "";
    expect(incAfter).toBe(incBefore);
    // Belt-and-braces: no income category name appears in the picker.
    expect(incAfter).not.toContain("Products Revenue");
    expect(incAfter).not.toContain("Services Revenue");
  });

  it("(7) inline banner errors clear after a valid pick (decision #4)", async () => {
    _mockItems([_CHLOR_PRODUCT]);
    // Legacy line with a description but no categories — the classic
    // "attempted && !categoryId" trigger surface.
    const doc = {
      line_items: [{
        ...(_emptyLine()),
        description: "Pool cleaning · March",
        unit_price: 150,
      }],
      status: "draft",
    };
    await _enterEditRow0(doc);

    // Trigger the `attempted` state flag by clicking Save without
    // categories — Save short-circuits, banners render.
    fireEvent.click(screen.getByTestId("k71-save-0"));
    // Banners visible per L335-341 (service) + L356-362 (income).
    expect(screen.getByTestId("k71-error-service-0")).toBeTruthy();
    expect(screen.getByTestId("k71-error-income-0")).toBeTruthy();

    // Now pick a Pricebook item that fills BOTH categories.
    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chl" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    fireEvent.click(screen.getByTestId("k71-pricebook-search-item-0"));
    await act(async () => { await Promise.resolve(); });

    // Banners disappear via computed-prop recomputation — no
    // hand-coded banner-hide path. `attempted` stays TRUE but the
    // `!serviceCategoryId` / `!incomeCategoryId` half of the AND is
    // now falsy → conditional collapses.
    expect(screen.queryByTestId("k71-error-service-0")).toBeNull();
    expect(screen.queryByTestId("k71-error-income-0")).toBeNull();
  });

  it("(8) free-typing without picking preserves current price / categories", async () => {
    // /items search returns rows, but the user never clicks one.
    _mockItems([_CHLOR_PRODUCT]);
    const startingLine = {
      description: "Manual entry line",
      quantity: 3,
      unit_price: 42.5,
      long_description: "Untouched notes",
      service_category_id: "svc-a",
      income_category_id: "inc-b",
    };
    const doc = { line_items: [startingLine], status: "draft" };
    await _enterEditRow0(doc);

    // Type "chl" but never click a dropdown row.
    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chl" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    // Dropdown appeared — proves the search fired.
    expect(screen.getByTestId("k71-pricebook-search-dropdown"))
      .toBeTruthy();

    // Description input holds the free-typed value.
    expect(screen.getByTestId("k71-input-item-0-input").value).toBe("chl");
    // Unit price / long-desc / categories unchanged.
    expect(screen.getByTestId("k71-input-price-0").value).toBe("42.5");
    expect(screen.getByTestId("k71-input-longdesc-0").value)
      .toBe("Untouched notes");
    expect(screen.getByTestId("k71-service-picker-0").textContent)
      .toContain("Landscape");
    expect(screen.getByTestId("k71-income-picker-0").textContent)
      .toContain("Services Revenue");
  });

  it("(9) Enter key bubbles from the picker input to EditableRow.handleKey → Save", async () => {
    const onLinesUpdated = vi.fn(async () => true);
    // Line already has both categories — Save WILL commit.
    const line = {
      description: "Ready line",
      quantity: 1,
      unit_price: 100,
      long_description: "",
      service_category_id: "svc-a",
      income_category_id: "inc-a",
    };
    const doc = { line_items: [line], status: "draft" };
    await _enterEditRow0(doc, { onLinesUpdated });

    // Fire Enter on the picker's INPUT. Picker doesn't own an
    // onKeyDown handler — the event bubbles up to
    // <tr data-testid="k71-row-edit-0" onKeyDown={handleKey}>,
    // which calls commit() → onSave() → onLinesUpdated().
    fireEvent.keyDown(screen.getByTestId("k71-input-item-0-input"),
                        { key: "Enter" });
    await act(async () => { await Promise.resolve(); });

    expect(onLinesUpdated).toHaveBeenCalledTimes(1);
    const committed = onLinesUpdated.mock.calls[0][0];
    expect(committed).toHaveLength(1);
    expect(committed[0].description).toBe("Ready line");
  });

  it("(10) monotonic reqSeq discards a stale slow response", async () => {
    // Programmable resolvers: first /items call = SLOW (only resolves
    // when we call slowResolve), second = FAST (resolves immediately
    // via ready value).
    let slowResolve;
    let itemCallCount = 0;
    api.get.mockImplementation(async (url) => {
      if (url.startsWith("/items?")) {
        itemCallCount += 1;
        if (itemCallCount === 1) {
          return new Promise((r) => {
            slowResolve = () => r([{
              id: "stale-1",
              name: "STALE CHLOR RESULT",
              unit_price: 1,
            }]);
          });
        }
        // 2nd call — return the "chlor2" fresh result immediately.
        return [{
          id: "fresh-1",
          name: "FRESH CHLOR2 RESULT",
          unit_price: 2,
        }];
      }
      return _defaultApiGet(url);
    });
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    // Keystroke 1 — "chlor" → SLOW call fires.
    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chlor" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    expect(itemCallCount).toBe(1);
    // Slow response not yet resolved — loading visible.
    expect(screen.getByTestId("k71-pricebook-search-loading")).toBeTruthy();

    // Keystroke 2 — "chlor2" → FAST call fires, resolves.
    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chlor2" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    expect(itemCallCount).toBe(2);
    // Fresh result rendered.
    expect(screen.getByText(/FRESH CHLOR2 RESULT/)).toBeTruthy();

    // NOW resolve the stale slow response. reqSeqRef has advanced —
    // the guard drops the payload on the floor.
    await act(async () => {
      slowResolve();
      await vi.runAllTimersAsync();
    });
    expect(screen.queryByText(/STALE CHLOR RESULT/)).toBeNull();
    expect(screen.getByText(/FRESH CHLOR2 RESULT/)).toBeTruthy();
  });

  it("(11) sibling CategoryPicker remains functional after a pick (decision #3 smoke)", async () => {
    _mockItems([_CHLOR_PRODUCT]);
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chl" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    fireEvent.click(screen.getByTestId("k71-pricebook-search-item-0"));
    await act(async () => { await Promise.resolve(); });

    // Both category pickers still mounted + interactive; testids
    // resolve; both have a rendered selection from the pick that
    // proves the underlying controlled state is live.
    const svcPicker = screen.getByTestId("k71-service-picker-0");
    const incPicker = screen.getByTestId("k71-income-picker-0");
    expect(svcPicker).toBeTruthy();
    expect(incPicker).toBeTruthy();
    expect(svcPicker.textContent).toContain("Pool Cleaning");
    expect(incPicker.textContent).toContain("Products Revenue");
    // Admin-override CategoryPickers on the same line also still
    // resolvable (decision #3 kept them untouched).
    expect(screen.getByTestId("line-item-service-category-select-0"))
      .toBeTruthy();
    expect(screen.getByTestId("line-item-income-category-select-0"))
      .toBeTruthy();
  });

  it("(12) _id:0 projection preserved — no _id leaks into the dropdown", async () => {
    // A row shape that includes a stray Mongo ``_id`` — the picker
    // must NEVER read it, so it must never appear in the DOM.
    _mockItems([{ ..._CHLOR_PRODUCT,
                   _id: "MONGO_OID_SHOULD_NEVER_APPEAR" }]);
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    fireEvent.change(screen.getByTestId("k71-input-item-0-input"),
                       { target: { value: "chl" } });
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });

    const dropdown = screen.getByTestId("k71-pricebook-search-dropdown");
    expect(dropdown.textContent)
      .not.toContain("MONGO_OID_SHOULD_NEVER_APPEAR");
    // The dropdown still shows the legit fields.
    expect(dropdown.textContent).toContain("Chlorine Tablets (25 lb)");
    expect(dropdown.textContent).toContain("$89.00");
  });
});
