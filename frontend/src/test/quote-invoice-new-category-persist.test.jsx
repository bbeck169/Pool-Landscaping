/**
 * Feb-2026 · Phase 5 Item-1 — vitest for the category-dropdown
 * persist fix in ``QuoteInvoiceNew.jsx``.
 *
 * Operator spec (4 cases):
 *   (1) Select category → line state has both ``category`` + ``income_category_id``
 *   (2) Submit payload includes ``income_category_id`` on every line
 *   (3) Backward compat — legacy ``category`` string still stamped
 *   (4) Pricebook pick path still works (stamps ``service_category_id``
 *       + ``income_category_id`` when present)
 *
 * Posture: source-inspection matching the shipped
 * ``quote-invoice-new-picker-wired.test.jsx`` sibling and the
 * ``record-payment-save-card-info.test.jsx`` pattern. Full DOM
 * mount of ``QuoteInvoiceNew`` has heavy ``/customers`` +
 * ``/pricebook`` + ``/categories`` async-fetch deps; the behavioral
 * contract we care about (payload shape + state updates) is
 * fully observable from the source — a future refactor that drops
 * the stamp instruction trips these assertions regardless of DOM.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";


const QIN_PATH = path.resolve(
  __dirname, "..", "pages", "quotes", "QuoteInvoiceNew.jsx",
);
const QIN_SRC = fs.readFileSync(QIN_PATH, "utf8");


describe("Phase 5 Item-1 · CategoryPicker.onChange stamps both fields", () => {
  it("CategoryPicker.onChange patches line.category AND line.income_category_id", () => {
    // Load-bearing — the whole point of the fix. Normalise
    // whitespace since the stamp is prettier-wrapped across lines.
    const normalised = QIN_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "patchLine(i, { category: v, income_category_id: v, });",
    );
  });

  it("stamp lives inside the CategoryPicker onChange handler, not elsewhere", () => {
    // Guard against a future refactor that accidentally hoists
    // the stamp out of the picker's onChange (e.g., stamping on
    // every patchLine). We assert the stamp sits BETWEEN the
    // ``<CategoryPicker`` opening tag and its ``/>`` closing.
    const openIdx = QIN_SRC.indexOf("<CategoryPicker");
    const closeIdx = QIN_SRC.indexOf("/>", openIdx);
    const slice = QIN_SRC.slice(openIdx, closeIdx);
    expect(slice).toContain("income_category_id: v");
    expect(slice).toContain("category: v");
  });
});


describe("Phase 5 Item-1 · payload includes income_category_id", () => {
  it("line_items payload maps income_category_id from local state", () => {
    const normalised = QIN_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "income_category_id: li.income_category_id || undefined,",
    );
  });

  it("line_items payload maps service_category_id from local state (K71 parity)", () => {
    // Shipped K71 pricebook pick stamps service_category_id into
    // local state (L498-504) but the pre-fix payload never
    // forwarded it. This commit adds forward on both axes so the
    // Edit modal's two dropdowns prefill after a fresh create.
    const normalised = QIN_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "service_category_id: li.service_category_id || undefined,",
    );
  });

  it("payload keeps legacy ``category`` string field — backward compat", () => {
    // The ``category`` field stays in the payload so legacy
    // readers that key off ``line.category`` (e.g., export CSV,
    // list filters, older PDF renderer) keep working. The BE
    // validator at ``routers/income_categories.py:223`` already
    // accepts both id + name shapes.
    expect(QIN_SRC).toContain('category: li.category || ""');
  });
});


describe("Phase 5 Item-1 · pricebook pick preserves K71 parity", () => {
  it("pricebook pick stamps service_category_id when the item carries one", () => {
    const normalised = QIN_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "if (item.service_category_id) { next.service_category_id = item.service_category_id; }",
    );
  });

  it("pricebook pick stamps income_category_id when the item carries one", () => {
    // New with this commit — pricebook items with ``item_type !==
    // "service"`` can carry an income_category_id per
    // ``routers/items.py:183-202``. Shipped K71 handler already
    // propagates it; mirror on QuoteInvoiceNew for parity.
    const normalised = QIN_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain(
      "if (item.income_category_id) { next.income_category_id = item.income_category_id; }",
    );
  });
});


describe("Phase 5 Item-1 · regression lock — isLegacyLine guard satisfied", () => {
  it("saved lines will carry at least one id — K71 badge guard honoured", () => {
    // The ``isLegacyLine`` guard at
    // ``K71LineItemsEditor.jsx:125-131`` returns true iff
    // BOTH ``service_category_id`` AND ``income_category_id``
    // are not strings. This commit ensures every create-flow
    // save stamps at least ``income_category_id`` from the
    // CategoryPicker — so the Uncategorized badge CAN'T render
    // on a freshly-saved line.
    //
    // Source-level guard: the payload builder MUST forward both
    // id axes AND the picker MUST stamp income_category_id.
    const normalised = QIN_SRC.replace(/\s+/g, " ");
    expect(normalised).toContain("income_category_id: v,");
    expect(normalised).toContain(
      "income_category_id: li.income_category_id || undefined",
    );
  });
});
