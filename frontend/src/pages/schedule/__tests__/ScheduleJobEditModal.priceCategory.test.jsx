/**
 * Feb-2026 · Jobs Overhaul Phase 2 — ScheduleJobEditModal Price +
 * Service Category parity contract.
 *
 * Source-inspection contract test — matches the sibling
 * ``schedule-inline-edit`` / ``jobnew-crew-picker`` shape. Locks:
 *   1. Price input renders (``type=number``, ``step=0.01``) via the
 *      shared TextInput primitive.
 *   2. Price hydrates from ``job.price`` on modal open (both the
 *      initial useState AND the ``open+job`` re-seed).
 *   3. Price ``onChange`` writes into ``form.price`` via ``set()``.
 *   4. Save handler patches ``price`` (numeric compare vs stored
 *      value, opportunistic-include).
 *   5. Service Category ``<select>`` renders, fed from
 *      ``GET /api/service-categories``.
 *   6. Save handler patches BOTH ``service_category_id`` +
 *      ``service_category_name`` on change.
 *   7. Service Category hydrates from ``job.service_category_id``
 *      /``job.service_category_name`` on modal open.
 *   8. Existing modal invariants unchanged — PUT endpoint,
 *      testids, embedded ``LineItemsSection`` wiring.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const modalSrc = fs.readFileSync(
  path.resolve(__dirname, "../ScheduleJobEditModal.jsx"),
  "utf8",
);

describe("ScheduleJobEditModal · Phase 2 · Price field", () => {
  it("renders an editable Price TextInput (type=number, step=0.01)", () => {
    // Slice from the Price label so unrelated inputs don't
    // pollute the assertion window.
    const priceIdx = modalSrc.indexOf('label="Price"');
    expect(priceIdx).toBeGreaterThan(-1);
    const priceBlock = modalSrc.slice(priceIdx - 200, priceIdx + 400);
    expect(priceBlock).toMatch(/<TextInput\b/);
    expect(priceBlock).toMatch(/type="number"/);
    expect(priceBlock).toMatch(/step="0\.01"/);
    // No hardcoded read-only / disabled on the Price input.
    expect(priceBlock).not.toMatch(/\breadOnly\b/);
    expect(priceBlock).not.toMatch(/\bdisabled=\{?true\b/);
    // Exposed testid so the sibling schedule E2E suite can drive it.
    expect(priceBlock).toMatch(/testid="schedule-job-edit-price"/);
  });

  it("Price hydrates from job.price in the initial useState", () => {
    // ``String(job.price)`` when non-null so the input renders the
    // stored number as text without a controlled/uncontrolled
    // warning; empty string when the job has no price yet.
    expect(modalSrc).toMatch(
      /useState\(\(\)\s*=>\s*\(\{[\s\S]{0,2500}price:\s*\(job\?\.price\s*!=\s*null\)\s*\?\s*String\(job\.price\)\s*:\s*""/,
    );
  });

  it("Price hydrates from job.price in the open+job re-seed effect", () => {
    // The useEffect re-seeds the form when the caller swaps to a
    // different job — same coerce as initial state so opening the
    // same modal twice on different jobs yields matching state.
    expect(modalSrc).toMatch(
      /setForm\(\{[\s\S]{0,1500}price:\s*\(job\.price\s*!=\s*null\)\s*\?\s*String\(job\.price\)\s*:\s*""/,
    );
  });

  it("Price onChange writes into form.price via set()", () => {
    // Uses the shared ``set(k)`` helper the rest of the modal uses.
    // Guards against a future ``value=... onChange={...}`` inline
    // rewrite that stops updating state.
    const priceIdx = modalSrc.indexOf('testid="schedule-job-edit-price"');
    expect(priceIdx).toBeGreaterThan(-1);
    const priceBlock = modalSrc.slice(priceIdx - 400, priceIdx + 200);
    expect(priceBlock).toMatch(/value=\{form\.price\}/);
    expect(priceBlock).toMatch(/onChange=\{set\("price"\)\}/);
  });

  it("save handler emits patch.price only when the numeric value changed", () => {
    // Numeric before / after so ``open + no-op close`` on a legacy
    // job does not stamp ``price`` onto every row.
    expect(modalSrc).toMatch(
      /const\s+beforePrice\s*=\s*Number\.isFinite\(Number\(job\.price\)\)\s*\?\s*Number\(job\.price\)\s*:\s*null/,
    );
    expect(modalSrc).toMatch(
      /const\s+afterPrice\s*=\s*\(afterPriceRaw\s*===\s*""\s*\|\|\s*afterPriceRaw\s*==\s*null\)\s*\?\s*null\s*:\s*Number\(afterPriceRaw\)/,
    );
    expect(modalSrc).toMatch(
      /if\s*\(afterPrice\s*!==\s*beforePrice[\s\S]{0,120}patch\.price\s*=\s*afterPrice/,
    );
  });
});

describe("ScheduleJobEditModal · Phase 2 · Service Category dropdown", () => {
  it("fetches from GET /api/service-categories on modal open", () => {
    expect(modalSrc).toMatch(/api\.get\(["']\/service-categories["']\)/);
    // Handles both ``{items: []}`` and legacy array response shapes.
    expect(modalSrc).toMatch(/res\?\.items/);
    // Silent failure → [] so non-admin roles never see the modal
    // red-banner.
    expect(modalSrc).toMatch(
      /\.catch\(\(\)\s*=>\s*setServiceCategories\(\[\]\)\)/,
    );
  });

  it("renders a <select> populated from serviceCategories", () => {
    expect(modalSrc).toMatch(
      /data-testid="schedule-job-edit-service-category"/,
    );
    expect(modalSrc).toMatch(
      /serviceCategories\.map\(\(c\)\s*=>\s*\(?\s*<option[\s\S]{0,300}value=\{c\.id\}/,
    );
    expect(modalSrc).toMatch(
      /data-testid=\{`schedule-job-edit-service-category-opt-\$\{c\.id\}`\}/,
    );
  });

  it("Service Category hydrates from job record (initial + re-seed)", () => {
    // Initial useState.
    expect(modalSrc).toMatch(
      /useState\(\(\)\s*=>\s*\(\{[\s\S]{0,2500}service_category_id:\s*job\?\.service_category_id\s*\|\|\s*""/,
    );
    expect(modalSrc).toMatch(
      /useState\(\(\)\s*=>\s*\(\{[\s\S]{0,2500}service_category_name:\s*job\?\.service_category_name\s*\|\|\s*""/,
    );
    // Re-seed on open+job change.
    expect(modalSrc).toMatch(
      /setForm\(\{[\s\S]{0,1800}service_category_id:\s*job\.service_category_id\s*\|\|\s*""/,
    );
    expect(modalSrc).toMatch(
      /setForm\(\{[\s\S]{0,1800}service_category_name:\s*job\.service_category_name\s*\|\|\s*""/,
    );
  });

  it("onChange resolves the name off the fetched list", () => {
    expect(modalSrc).toMatch(
      /const\s+cat\s*=\s*serviceCategories\.find\(\(c\)\s*=>\s*c\.id\s*===\s*id,?\s*\)/,
    );
    expect(modalSrc).toMatch(
      /service_category_id:\s*id,\s*service_category_name:\s*cat\?\.name\s*\|\|\s*""/,
    );
  });

  it("save handler patches BOTH keys when the id changes", () => {
    expect(modalSrc).toMatch(
      /const\s+beforeCatId\s*=\s*job\.service_category_id\s*\|\|\s*""/,
    );
    expect(modalSrc).toMatch(
      /const\s+afterCatId\s*=\s*form\.service_category_id\s*\|\|\s*""/,
    );
    expect(modalSrc).toMatch(
      /if\s*\(afterCatId\s*!==\s*beforeCatId\)\s*\{\s*patch\.service_category_id\s*=\s*afterCatId;\s*patch\.service_category_name\s*=\s*form\.service_category_name\s*\|\|\s*""/,
    );
  });
});

describe("ScheduleJobEditModal · Phase 2 · Regression guard", () => {
  it("Save still hits PUT /jobs/{id} with the partial-patch shape", () => {
    // The endpoint + verb are the load-bearing wire contract —
    // Phase 2 must NOT rewrite the save URL or method.
    expect(modalSrc).toMatch(/api\.put\(`\/jobs\/\$\{job\.id\}`,\s*patch\)/);
  });

  it("Line Items section stays wired to jobId (server-side)", () => {
    // The embedded ``LineItemsSection`` operates on
    // ``/jobs/{jobId}/line-items`` and MUST stay decoupled from
    // ``form.price`` (rationale for skipping the manual-override
    // flag on this surface). Guards a future refactor that might
    // inadvertently bind Line Items into ``form``.
    expect(modalSrc).toMatch(
      /<LineItemsSection[\s\S]{0,240}jobId=\{job\.id\}/,
    );
  });

  it("Existing testids on the modal are preserved (title / service / date / status)", () => {
    // Sample of pre-existing testids — a naive refactor of the
    // grid could easily drop one. Guard the load-bearing ones.
    expect(modalSrc).toMatch(/testid="schedule-job-edit-title"/);
    expect(modalSrc).toMatch(/data-testid="schedule-job-edit-service"/);
    expect(modalSrc).toMatch(/testid="schedule-job-edit-date"/);
    expect(modalSrc).toMatch(/data-testid="schedule-job-edit-status"/);
    // Save button testid.
    expect(modalSrc).toMatch(/testid="schedule-job-edit-save"/);
  });
});
