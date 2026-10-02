/**
 * Feb-2026 · Jobs Overhaul Phase 1 — /jobs/new parity contract.
 *
 * Source-inspection contract test — matches the sibling
 * ``jobnew-crew-picker`` / ``job-new-customer-picker`` shape.
 *
 * Locks the Phase-1 wire so Phase 2 (Edit Job modal parity) and
 * Phase 3 (JobDetail overhaul + shared LineItemsEditor extraction)
 * can't silently regress. Post Phase-3c the Line Items JSX chunks
 * were extracted to ``@/components/jobs/LineItemsEditor`` — the
 * JSX-matcher assertions in this file now split: those pattern-
 * matches read from ``lineItemsEditorSrc``; state-helper matches
 * (addBlankLine / addPricebookLine / removeLine / lineItemsSubtotal
 * useMemo / price-sync useEffect / submit-payload shape) stay on
 * ``jobNewSrc`` because that state ownership did NOT move.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const jobNewSrc = fs.readFileSync(
  path.resolve(__dirname, "../JobNew.jsx"),
  "utf8",
);

// Phase 3c · post-extraction second source file. Any JSX-matcher
// assertion that targets the Line Items table / picker / footer
// now reads from here; the inner JSX was moved out of JobNew.jsx
// but the state ownership + composition root stayed.
const lineItemsEditorSrc = fs.readFileSync(
  path.resolve(__dirname, "../../../components/jobs/LineItemsEditor.jsx"),
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

describe("JobNew · Phase 3c · Line Items composition root (stayed in JobNew)", () => {
  it("JobNew mounts <LineItemsEditor> with testidPrefix='jf-li' and wires the controlled callbacks", () => {
    // Phase 3c extraction — the inner JSX moved to the shared
    // ``@/components/jobs/LineItemsEditor`` component. JobNew now
    // owns the OUTER card wrapper + the composition call + the
    // state (lines array, pricebook search string, handlers), and
    // delegates the inner table/picker/footer to the extracted
    // component via the controlled prop surface.
    expect(jobNewSrc).toMatch(/data-testid="jf-line-items-section"/);
    expect(jobNewSrc).toMatch(
      /import\s+LineItemsEditor\s+from\s+["']@\/components\/jobs\/LineItemsEditor["']/,
    );
    expect(jobNewSrc).toMatch(
      /<LineItemsEditor\b[\s\S]{0,800}testidPrefix="jf-li"/,
    );
    expect(jobNewSrc).toMatch(/lines=\{form\.line_items\s*\|\|\s*\[\]\}/);
    expect(jobNewSrc).toMatch(/onAddBlank=\{addBlankLine\}/);
    expect(jobNewSrc).toMatch(/onAddFromPricebook=\{addPricebookLine\}/);
    expect(jobNewSrc).toMatch(/onUpdateLine=\{updateLine\}/);
    expect(jobNewSrc).toMatch(/onRemoveLine=\{removeLine\}/);
    expect(jobNewSrc).toMatch(/pricebookSearch=\{pbSearch\}/);
    expect(jobNewSrc).toMatch(/onPricebookSearchChange=\{setPbSearch\}/);
  });
});

describe("JobNew · Phase 1 · Line Items state helpers (stayed in JobNew)", () => {
  it("addPricebookLine appends {description, unit_price, quantity: 1} from a picked item", () => {
    expect(jobNewSrc).toMatch(
      /const\s+addPricebookLine\s*=\s*\(row\)\s*=>[\s\S]{0,400}description:\s*row\?\.name[\s\S]{0,60}quantity:\s*1,[\s\S]{0,60}unit_price:\s*Number\(row\?\.unit_price\s*\|\|\s*0\)/,
    );
  });

  it("addBlankLine appends a blank {description:'', quantity:1, unit_price:0} row", () => {
    expect(jobNewSrc).toMatch(
      /const\s+addBlankLine\s*=\s*\(\)\s*=>[\s\S]{0,300}\{\s*description:\s*"",\s*quantity:\s*1,\s*unit_price:\s*0\s*\}/,
    );
  });

  it("lineItemsSubtotal useMemo computes Σ (qty × unit_price) over form.line_items", () => {
    expect(jobNewSrc).toMatch(
      /const\s+lineItemsSubtotal\s*=\s*useMemo\([\s\S]{0,400}\(form\.line_items\s*\|\|\s*\[\]\)\.reduce\(/,
    );
    expect(jobNewSrc).toMatch(
      /sum\s*\+\s*\(Number\(li\.quantity\)\s*\|\|\s*0\)\s*\*\s*\(Number\(li\.unit_price\)\s*\|\|\s*0\)/,
    );
  });

  it("subtotal auto-writes form.price via a useEffect on lineItemsSubtotal (price-sync side effect)", () => {
    expect(jobNewSrc).toMatch(
      /useEffect\(\(\)\s*=>\s*\{[\s\S]{0,300}if\s*\(form\.price_manually_overridden\)\s*return;[\s\S]{0,200}setForm[\s\S]{0,120}price:\s*next[\s\S]{0,300}\},\s*\[lineItemsSubtotal,\s*form\.line_items,\s*form\.price_manually_overridden\]/,
    );
  });

  it("removeLine drops the row at index i", () => {
    expect(jobNewSrc).toMatch(
      /const\s+removeLine\s*=\s*\(idx\)\s*=>[\s\S]{0,240}\.filter\(\(_,\s*i\)\s*=>\s*i\s*!==\s*idx\)/,
    );
  });
});

describe("LineItemsEditor · Phase 3c · extracted JSX chunks (post-extraction source contract)", () => {
  it("imports PricebookItemPicker and wires the pricebook wrapperTestid via testidPrefix", () => {
    expect(lineItemsEditorSrc).toMatch(
      /import\s+PricebookItemPicker\s+from\s+["']@\/components\/pricebook\/PricebookItemPicker["']/,
    );
    expect(lineItemsEditorSrc).toMatch(
      /<PricebookItemPicker\b[\s\S]{0,800}wrapperTestid=\{`\$\{testidPrefix\}-add-pricebook`\}/,
    );
    // onSelect delegates to the controlled callbacks + clears the
    // search string.
    expect(lineItemsEditorSrc).toMatch(
      /onSelect=\{\(row\)\s*=>\s*\{\s*onAddFromPricebook\(row\);\s*onPricebookSearchChange\(""\);/,
    );
  });

  it("renders the Add-line Button with testid=`${testidPrefix}-add-blank` + onClick={onAddBlank}", () => {
    expect(lineItemsEditorSrc).toMatch(
      /testid=\{`\$\{testidPrefix\}-add-blank`\}[\s\S]{0,80}onClick=\{onAddBlank\}/,
    );
  });

  it("renders the empty-state + table + subtotal footer testids via testidPrefix", () => {
    expect(lineItemsEditorSrc).toMatch(/data-testid=\{`\$\{testidPrefix\}-table`\}/);
    expect(lineItemsEditorSrc).toMatch(/data-testid=\{`\$\{testidPrefix\}-empty`\}/);
    expect(lineItemsEditorSrc).toMatch(/data-testid=\{`\$\{testidPrefix\}-subtotal`\}/);
  });

  it("per-row Total = quantity × unit_price formatted as $ fixed-2", () => {
    expect(lineItemsEditorSrc).toMatch(
      /const\s+rowTotal\s*=\s*\(Number\(li\.quantity\)\s*\|\|\s*0\)\s*\*\s*\(Number\(li\.unit_price\)\s*\|\|\s*0\)/,
    );
    expect(lineItemsEditorSrc).toMatch(
      /data-testid=\{`\$\{testidPrefix\}-total-\$\{i\}`\}[\s\S]{0,200}\$\$\{rowTotal\.toFixed\(2\)\}/,
    );
  });

  it("subtotal footer renders Σ via useMemo+reduce + Subtotal $N.NN label", () => {
    expect(lineItemsEditorSrc).toMatch(
      /const\s+subtotal\s*=\s*useMemo\([\s\S]{0,400}\(lines\s*\|\|\s*\[\]\)\.reduce\(/,
    );
    expect(lineItemsEditorSrc).toMatch(
      /sum\s*\+\s*\(Number\(li\.quantity\)\s*\|\|\s*0\)\s*\*\s*\(Number\(li\.unit_price\)\s*\|\|\s*0\)/,
    );
    expect(lineItemsEditorSrc).toMatch(
      /data-testid=\{`\$\{testidPrefix\}-subtotal`\}[\s\S]{0,200}Subtotal\s*\$\$\{subtotal\.toFixed\(2\)\}/,
    );
  });

  it("per-row trash button carries the ${testidPrefix}-del-{i} testid", () => {
    expect(lineItemsEditorSrc).toMatch(
      /data-testid=\{`\$\{testidPrefix\}-del-\$\{i\}`\}/,
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
