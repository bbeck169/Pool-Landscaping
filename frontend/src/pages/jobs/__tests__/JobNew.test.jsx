/**
 * Feb-2026 · Jobs Overhaul Phase 1 — /jobs/new parity contract.
 *
 * Source-inspection contract test — matches the sibling
 * ``jobnew-crew-picker`` / ``job-new-customer-picker`` shape.
 *
 * Locks the Phase-1 wire so Phase 2 (Edit Job modal parity) and
 * Phase 3 (JobDetail overhaul + shared LineItemsEditor extraction)
 * can't silently regress:
 *   1. Price input is fully editable (no ``readOnly`` / ``disabled``,
 *      type=number, step=0.01, ``onPriceChange`` bound) and accepts
 *      decimals.
 *   2. Service Category dropdown is rendered, fetched from
 *      ``GET /api/service-categories``, and stores the paired
 *      ``{id, name}`` on the form.
 *   3. On save, the payload emits both ``service_category_id`` +
 *      ``service_category_name`` when a category is picked.
 *   4. "Add from pricebook" affordance mounts ``PricebookItemPicker``
 *      and, on select, appends a line with ``description`` +
 *      ``unit_price`` + ``quantity: 1``.
 *   5. "Add line" (``jf-li-add-blank``) appends a blank row for
 *      manual entry.
 *   6. Per-row Total = ``quantity × unit_price`` formatted as
 *      dollars (fixed-2).
 *   7. Subtotal is Σ (qty × unit_price) via ``.reduce(…, 0)`` over
 *      ``form.line_items`` and rendered with ``jf-li-subtotal``.
 *   8. Subtotal auto-writes ``form.price`` via a ``useEffect`` on
 *      ``lineItemsSubtotal`` — unless ``price_manually_overridden``.
 *   9. Remove button (``jf-li-del-{i}``) calls ``removeLine(i)``.
 *  10. Save payload conditionally includes ``line_items`` array
 *      when non-empty.
 *  11. Manual-override affordance: hint (``jf-price-manual-hint``)
 *      + Recalculate button (``jf-price-recalc``) reset the flag.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const jobNewSrc = fs.readFileSync(
  path.resolve(__dirname, "../JobNew.jsx"),
  "utf8",
);

describe("JobNew · Phase 1 · Price is fully editable", () => {
  it("Price TextInput uses type=number + step=0.01 and no readOnly/disabled", () => {
    // Slice the JSX block starting from the PRICE label so we
    // don't accidentally match unrelated ``readOnly`` on other
    // inputs (there are none today, but keeps the assertion
    // scoped).
    const priceIdx = jobNewSrc.indexOf('label="PRICE"');
    expect(priceIdx).toBeGreaterThan(-1);
    const priceBlock = jobNewSrc.slice(priceIdx, priceIdx + 600);
    expect(priceBlock).toMatch(/type="number"/);
    expect(priceBlock).toMatch(/step="0\.01"/);
    // No hardcoded read-only / disabled on the Price input.
    expect(priceBlock).not.toMatch(/\breadOnly\b/);
    expect(priceBlock).not.toMatch(/\bdisabled=\{?true\b/);
  });

  it("Price onChange is bound to onPriceChange (flips manual-override)", () => {
    expect(jobNewSrc).toMatch(
      /<TextInput[\s\S]{0,200}label="PRICE"[\s\S]{0,200}onChange=\{onPriceChange\}/,
    );
    // Handler flips the override flag.
    expect(jobNewSrc).toMatch(
      /const\s+onPriceChange\s*=\s*\(e\)\s*=>[\s\S]{0,200}price_manually_overridden:\s*true/,
    );
  });
});

describe("JobNew · Phase 1 · Service Category dropdown", () => {
  it("fetches from GET /api/service-categories on mount", () => {
    expect(jobNewSrc).toMatch(
      /api\.get\(["']\/service-categories["']\)/,
    );
    // Handles both ``{items: []}`` and legacy array shape.
    expect(jobNewSrc).toMatch(/res\?\.items/);
    // Silent failure keeps the form usable when 403.
    expect(jobNewSrc).toMatch(
      /\.catch\(\(\)\s*=>\s*setServiceCategories\(\[\]\)\)/,
    );
  });

  it("renders a <select> populated from serviceCategories", () => {
    expect(jobNewSrc).toMatch(/data-testid="jf-service-category"/);
    expect(jobNewSrc).toMatch(
      /serviceCategories\.map\(\(c\)\s*=>\s*\(?\s*<option[\s\S]{0,200}value=\{c\.id\}/,
    );
    expect(jobNewSrc).toMatch(
      /data-testid=\{`jf-service-category-opt-\$\{c\.id\}`\}/,
    );
  });

  it("stores the paired {id, name} on the form state", () => {
    // Initial state.
    expect(jobNewSrc).toMatch(/service_category_id:\s*["']["']/);
    expect(jobNewSrc).toMatch(/service_category_name:\s*["']["']/);
    // onChange resolves the name off the fetched list.
    expect(jobNewSrc).toMatch(
      /const\s+cat\s*=\s*serviceCategories\.find\(\s*\(c\)\s*=>\s*c\.id\s*===\s*id,?\s*\)/,
    );
    expect(jobNewSrc).toMatch(
      /service_category_id:\s*id,\s*service_category_name:\s*cat\?\.name\s*\|\|\s*""/,
    );
  });
});

describe("JobNew · Phase 1 · Line Items section", () => {
  it("mounts the Line Items card with headline + subtotal footer testids", () => {
    expect(jobNewSrc).toMatch(/data-testid="jf-line-items-section"/);
    expect(jobNewSrc).toMatch(/data-testid="jf-li-table"/);
    expect(jobNewSrc).toMatch(/data-testid="jf-li-empty"/);
    expect(jobNewSrc).toMatch(/data-testid="jf-li-subtotal"/);
  });

  it("mounts the shared PricebookItemPicker for the 'Add from pricebook' affordance", () => {
    expect(jobNewSrc).toMatch(
      /import\s+PricebookItemPicker\s+from\s+["']@\/components\/pricebook\/PricebookItemPicker["']/,
    );
    expect(jobNewSrc).toMatch(/<PricebookItemPicker\b[\s\S]{0,600}wrapperTestid="jf-li-add-pricebook"/);
    // On select → append line + clear the search input.
    expect(jobNewSrc).toMatch(
      /onSelect=\{\(row\)\s*=>\s*\{\s*addPricebookLine\(row\);\s*setPbSearch\(""\);/,
    );
  });

  it("addPricebookLine appends {description, unit_price, quantity: 1} from a picked item", () => {
    expect(jobNewSrc).toMatch(
      /const\s+addPricebookLine\s*=\s*\(row\)\s*=>[\s\S]{0,400}description:\s*row\?\.name[\s\S]{0,60}quantity:\s*1,[\s\S]{0,60}unit_price:\s*Number\(row\?\.unit_price\s*\|\|\s*0\)/,
    );
  });

  it("'Add line' button (jf-li-add-blank) appends a blank row via addBlankLine", () => {
    expect(jobNewSrc).toMatch(
      /testid="jf-li-add-blank"\s+onClick=\{addBlankLine\}/,
    );
    expect(jobNewSrc).toMatch(
      /const\s+addBlankLine\s*=\s*\(\)\s*=>[\s\S]{0,300}\{\s*description:\s*"",\s*quantity:\s*1,\s*unit_price:\s*0\s*\}/,
    );
  });

  it("per-row Total is quantity × unit_price formatted as dollars", () => {
    // Row totalization inside the .map block.
    expect(jobNewSrc).toMatch(
      /const\s+rowTotal\s*=\s*\(Number\(li\.quantity\)\s*\|\|\s*0\)\s*\*\s*\(Number\(li\.unit_price\)\s*\|\|\s*0\)/,
    );
    // Rendered with a dollar prefix + fixed-2 in the total cell.
    expect(jobNewSrc).toMatch(
      /data-testid=\{`jf-li-total-\$\{i\}`\}[\s\S]{0,120}\$\$\{rowTotal\.toFixed\(2\)\}/,
    );
  });

  it("subtotal is Σ (qty × unit_price) via reduce over form.line_items", () => {
    expect(jobNewSrc).toMatch(
      /const\s+lineItemsSubtotal\s*=\s*useMemo\([\s\S]{0,400}\(form\.line_items\s*\|\|\s*\[\]\)\.reduce\(/,
    );
    expect(jobNewSrc).toMatch(
      /sum\s*\+\s*\(Number\(li\.quantity\)\s*\|\|\s*0\)\s*\*\s*\(Number\(li\.unit_price\)\s*\|\|\s*0\)/,
    );
    // Rendered under jf-li-subtotal with the ``$X.XX`` shape.
    expect(jobNewSrc).toMatch(
      /data-testid="jf-li-subtotal"[\s\S]{0,120}\$\$\{lineItemsSubtotal\.toFixed\(2\)\}/,
    );
  });

  it("subtotal auto-writes form.price via a useEffect on lineItemsSubtotal", () => {
    expect(jobNewSrc).toMatch(
      /useEffect\(\(\)\s*=>\s*\{[\s\S]{0,300}if\s*\(form\.price_manually_overridden\)\s*return;[\s\S]{0,200}setForm[\s\S]{0,120}price:\s*next[\s\S]{0,300}\},\s*\[lineItemsSubtotal,\s*form\.line_items,\s*form\.price_manually_overridden\]/,
    );
  });

  it("removeLine drops the row at index i", () => {
    expect(jobNewSrc).toMatch(
      /const\s+removeLine\s*=\s*\(idx\)\s*=>[\s\S]{0,240}\.filter\(\(_,\s*i\)\s*=>\s*i\s*!==\s*idx\)/,
    );
    expect(jobNewSrc).toMatch(
      /data-testid=\{`jf-li-del-\$\{i\}`\}/,
    );
  });
});

describe("JobNew · Phase 1 · Manual-override hint + Recalculate", () => {
  it("shows the hint only when line_items non-empty AND override flag is set", () => {
    expect(jobNewSrc).toMatch(
      /\(form\.line_items\s*\|\|\s*\[\]\)\.length\s*>\s*0[\s\S]{0,80}&&\s*form\.price_manually_overridden\s*\?/,
    );
    expect(jobNewSrc).toMatch(/data-testid="jf-price-manual-hint"/);
  });

  it("Recalculate button clears the override flag and resets Price to subtotal", () => {
    expect(jobNewSrc).toMatch(
      /const\s+recalcPriceFromLineItems\s*=\s*\(\)\s*=>[\s\S]{0,300}price:\s*Number\(lineItemsSubtotal\.toFixed\(2\)\),\s*price_manually_overridden:\s*false/,
    );
    expect(jobNewSrc).toMatch(
      /data-testid="jf-price-recalc"[\s\S]{0,120}onClick=\{recalcPriceFromLineItems\}|onClick=\{recalcPriceFromLineItems\}[\s\S]{0,200}data-testid="jf-price-recalc"/,
    );
  });
});

describe("JobNew · Phase 1 · Submit payload additions", () => {
  it("conditionally emits service_category_id + service_category_name when a category is picked", () => {
    // Guard so the field is only added when a value is present —
    // preserves back-compat with legacy POST /jobs consumers.
    expect(jobNewSrc).toMatch(
      /if\s*\(form\.service_category_id\)\s*\{\s*payload\.service_category_id\s*=\s*form\.service_category_id;\s*payload\.service_category_name\s*=\s*form\.service_category_name\s*\|\|\s*""/,
    );
  });

  it("conditionally emits line_items array when non-empty, mapped to a clean wire shape", () => {
    expect(jobNewSrc).toMatch(
      /if\s*\(\(form\.line_items\s*\|\|\s*\[\]\)\.length\s*>\s*0\)\s*\{\s*payload\.line_items\s*=\s*form\.line_items\.map/,
    );
    // Wire shape: description + quantity + unit_price, plus an
    // optional pricebook_item_id back-reference for future BE
    // contract widening.
    expect(jobNewSrc).toMatch(/description:\s*li\.description\s*\|\|\s*""/);
    expect(jobNewSrc).toMatch(/quantity:\s*Number\(li\.quantity\)\s*\|\|\s*0/);
    expect(jobNewSrc).toMatch(/unit_price:\s*Number\(li\.unit_price\)\s*\|\|\s*0/);
  });

  it("preserves the existing price + status + work_class payload contract", () => {
    // Guard against a Phase-1 regression on the existing wire.
    expect(jobNewSrc).toMatch(/price:\s*Number\(form\.price\)\s*\|\|\s*0/);
    expect(jobNewSrc).toMatch(/status:\s*"scheduled"/);
    expect(jobNewSrc).toMatch(/work_class:\s*form\.work_class\s*\|\|\s*"service"/);
  });

  it("MasterService pick does NOT overwrite Price when line_items already exist", () => {
    // Line Items own Price in the auto-driven case — MasterService
    // pick only sets ``service_type`` when a line-items list is
    // present. See the ``!hasLineItems`` guard.
    expect(jobNewSrc).toMatch(
      /const\s+hasLineItems\s*=\s*\(f\.line_items\s*\|\|\s*\[\]\)\.length\s*>\s*0/,
    );
    expect(jobNewSrc).toMatch(
      /Number\.isFinite\(default_price\)[\s\S]{0,60}&&\s*default_price\s*!=\s*null[\s\S]{0,80}&&\s*!hasLineItems/,
    );
  });
});
