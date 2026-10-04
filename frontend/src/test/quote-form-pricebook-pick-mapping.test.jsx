/**
 * QF-1 · Feb-2026 — Quote form pricebook pick mapping fix.
 *
 * Option B + legacy-string.  Picking a pricebook row on the K71 line-
 * items editor must land each pricebook field on the correct line-
 * item state:
 *
 *   item.name              → item_name  (NEW bold SKU label slot)
 *   item.description       → description (free-text, picker input)
 *   item.unit_price        → unit_price  (decimal dollars)
 *   item.service_category_id / item.income_category_id → FK pickers
 *   item.category          → legacy string category (NEW wire,
 *                            hidden pass-through; carried through
 *                            commit() so downstream K71-parity
 *                            reports keep ``line_items[].category``
 *                            in sync with the pricebook row)
 *
 * ``long_description`` is NO LONGER auto-filled on pick (operator
 * types freely).  Mirrors the ``task-g-k71-pricebook-picker.test.jsx``
 * mock pattern — same ``vi.mock("@/api")`` boundary, same category
 * stubs, same ``_enterEditRow0`` helper shape.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";


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


const _INCOME_CATS = [
  { id: "inc-1", name: "Services Revenue", color: "#3B82F6" },
];
const _SERVICE_CATS = [
  { id: "sc-1", name: "Pool Service", color: "#0EA5E9" },
];

function _defaultApiGet(url) {
  if (url === "/income-categories") return { items: _INCOME_CATS };
  if (url === "/service-categories") return { items: _SERVICE_CATS };
  if (url.startsWith("/items?")) return [];
  return [];
}

function _mockItems(rows) {
  api.get.mockImplementation(async (url) => {
    if (url.startsWith("/items?")) return rows;
    return _defaultApiGet(url);
  });
}

const _WEEKLY_SERVICE = {
  id: "pb-weekly-1",
  name: "Weekly Service",
  description: "Full chlorination + skim",
  unit_price: 125,
  category: "maintenance",
  item_type: "product",
  service_category_id: "sc-1",
  service_category_name: "Pool Service",
  income_category_id: "inc-1",
  income_category_name: "Services Revenue",
};

const _NO_DESCRIPTION = {
  id: "pb-no-desc",
  name: "SKU Only",
  description: null,
  unit_price: 50,
  category: "chemicals",
  item_type: "product",
  service_category_id: "sc-1",
  income_category_id: "inc-1",
};

const _NO_NAME = {
  id: "pb-no-name",
  name: null,
  description: "Mystery item",
  unit_price: 10,
  category: "misc",
  item_type: "product",
  service_category_id: "sc-1",
  income_category_id: "inc-1",
};

function _emptyLine() {
  return {
    description: "",
    quantity: 1,
    unit_price: 0,
    long_description: "",
    service_category_id: "",
    income_category_id: "",
    item_name: "",
    category: "",
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


async function _pickWeeklyService() {
  _mockItems([_WEEKLY_SERVICE]);
  const doc = { line_items: [_emptyLine()], status: "draft" };
  await _enterEditRow0(doc);

  fireEvent.change(
    screen.getByTestId("k71-input-item-0-input"),
    { target: { value: "weekly" } },
  );
  await act(async () => { await vi.advanceTimersByTimeAsync(260); });
  fireEvent.click(screen.getByTestId("k71-pricebook-search-item-0"));
  await act(async () => { await Promise.resolve(); });
}


describe("QF-1 · pricebook pick mapping · behavioural (K71 editor)", () => {

  it("a. picking an item sets item_name input to item.name", async () => {
    await _pickWeeklyService();
    expect(screen.getByTestId("k71-input-itemname-0").value)
      .toBe("Weekly Service");
  });

  it("b. picking an item sets description to item.description — NOT item.name", async () => {
    await _pickWeeklyService();
    const descVal = screen.getByTestId("k71-input-item-0-input").value;
    expect(descVal).toBe("Full chlorination + skim");
    expect(descVal).not.toBe("Weekly Service");
  });

  it("c. picking an item sets unit_price to item.unit_price (decimal dollars string)", async () => {
    await _pickWeeklyService();
    expect(screen.getByTestId("k71-input-price-0").value).toBe("125");
  });

  it("d. picking an item sets service_category_id to item.service_category_id", async () => {
    await _pickWeeklyService();
    // The CategoryPicker surfaces the resolved category NAME when the
    // id lands on the state — same observable proof pattern as
    // task-g case (5).
    expect(screen.getByTestId("k71-service-picker-0").textContent)
      .toContain("Pool Service");
  });

  it("e. picking an item routes item.category onto the committed line's legacy category field", async () => {
    // Capture the commit() payload via onLinesUpdated and assert the
    // ``category`` key — this is the ONLY wire that the brief's
    // "category: maintenance" criterion can observe (K71 UI has no
    // legacy-category input).
    _mockItems([_WEEKLY_SERVICE]);
    const onLinesUpdated = vi.fn();
    const doc = { line_items: [_emptyLine()], status: "draft" };
    render(
      <K71LineItemsEditor doc={doc} canEdit
                           onLinesUpdated={onLinesUpdated} />,
    );
    fireEvent.click(screen.getByTestId("k71-edit-btn-0"));
    await act(async () => { await Promise.resolve(); });

    fireEvent.change(
      screen.getByTestId("k71-input-item-0-input"),
      { target: { value: "weekly" } },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    fireEvent.click(screen.getByTestId("k71-pricebook-search-item-0"));
    await act(async () => { await Promise.resolve(); });

    // Fire the row's Save button so onLinesUpdated gets the committed
    // payload.
    fireEvent.click(screen.getByTestId("k71-save-0"));
    await act(async () => { await Promise.resolve(); });

    expect(onLinesUpdated).toHaveBeenCalled();
    const lastCall =
      onLinesUpdated.mock.calls[onLinesUpdated.mock.calls.length - 1];
    const committedLines = lastCall[0];
    expect(committedLines[0].category).toBe("maintenance");
    // Belt-and-braces: item_name also lands on the committed line.
    expect(committedLines[0].item_name).toBe("Weekly Service");
    expect(committedLines[0].description).toBe("Full chlorination + skim");
  });

  it("f. picking an item with description=null → description falls back to '' (NOT item.name)", async () => {
    _mockItems([_NO_DESCRIPTION]);
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    fireEvent.change(
      screen.getByTestId("k71-input-item-0-input"),
      { target: { value: "sku" } },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    fireEvent.click(screen.getByTestId("k71-pricebook-search-item-0"));
    await act(async () => { await Promise.resolve(); });

    // Regression lock — description must NOT fall back to item.name.
    const descVal = screen.getByTestId("k71-input-item-0-input").value;
    expect(descVal).toBe("");
    expect(descVal).not.toBe("SKU Only");
    // item_name slot still gets the name.
    expect(screen.getByTestId("k71-input-itemname-0").value)
      .toBe("SKU Only");
  });

  it("g. picking an item with name=null → item_name falls back to '' (no crash)", async () => {
    _mockItems([_NO_NAME]);
    const doc = { line_items: [_emptyLine()], status: "draft" };
    await _enterEditRow0(doc);

    fireEvent.change(
      screen.getByTestId("k71-input-item-0-input"),
      { target: { value: "myst" } },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(260); });
    fireEvent.click(screen.getByTestId("k71-pricebook-search-item-0"));
    await act(async () => { await Promise.resolve(); });

    // item_name slot stays empty (no crash on null coalesce).
    expect(screen.getByTestId("k71-input-itemname-0").value).toBe("");
    // description still receives item.description.
    expect(screen.getByTestId("k71-input-item-0-input").value)
      .toBe("Mystery item");
  });
});
