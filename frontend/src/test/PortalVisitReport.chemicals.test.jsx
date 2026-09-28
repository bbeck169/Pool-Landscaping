/**
 * CHEM-LOCK · Feb-2026 — Portal visit-report chemical rendering.
 *
 * Contract locked by source inspection (matches the pattern used by
 * ``jobdetail-k6-completed-unlock.test.jsx``):
 *   1. Both the flat pool block AND the additional-body block
 *      prefer ``c.quantity`` over ``c.amount``.
 *   2. Genuinely blank rows (no name, no raw_label, no non-zero
 *      quantity/amount) are skipped in-render.
 *   3. The ``superseded_at`` stale-report banner renders when the
 *      SR carries a superseded_at value.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/portal/PortalServiceReports.jsx"),
  "utf8",
);


describe("PortalServiceReports · CHEM-LOCK chemical rendering", () => {
  it("prefers ``c.quantity`` over ``c.amount`` on the flat pool block", () => {
    // The flat block is the ``portal-service-report-chemicals-block``
    // ul. Locate that block and assert quantity comes first in the
    // nullish-coalescing chain.
    expect(SRC).toMatch(
      /portal-service-report-chemicals-block/,
    );
    // The quantity-first read is:
    //   const rawQty = c.quantity ?? c.amount ?? c.qty ?? "";
    expect(SRC).toMatch(
      /c\.quantity\s*\?\?\s*c\.amount\s*\?\?\s*c\.qty\s*\?\?\s*""/,
    );
  });

  it("prefers ``c_.quantity`` over ``c_.amount`` on the additional-body block", () => {
    // The additional-body iteration uses the ``c_`` alias.
    expect(SRC).toMatch(
      /c_\.quantity\s*\?\?\s*c_\.amount\s*\?\?\s*c_\.qty\s*\?\?\s*""/,
    );
  });

  it("skips genuinely blank rows via a ``hasContent`` guard", () => {
    // Both the flat and body blocks include a hasContent check that
    // returns null for rows with no name, no raw_label, and no
    // non-zero quantity/amount.
    expect(SRC).toMatch(/const\s+hasContent\s*=/);
    // The chain checks name/chemical/raw_label OR a non-blank qty.
    expect(SRC).toMatch(
      /c\.name\s*\|\|\s*c\.chemical\s*\|\|\s*c\.raw_label/,
    );
    expect(SRC).toMatch(/if\s*\(\s*!hasContent\s*\)\s*return\s+null/);
  });

  it("renders the superseded_at stale-report banner when set", () => {
    // Banner data-testid + copy locked so a future edit can't
    // silently rename them.
    expect(SRC).toMatch(
      /data-testid="portal-service-report-superseded-banner"/,
    );
    expect(SRC).toMatch(
      /Report updated after original send/,
    );
    // The banner is gated ``sr.superseded_at ? … : null`` so a
    // vanilla submit (no unlock cycle) renders nothing.
    expect(SRC).toMatch(/sr\.superseded_at\s*\?/);
    expect(SRC).toMatch(
      /data-testid="portal-service-report-superseded-original-at"/,
    );
  });

  it("preserves the empty-state fallback when no chemicals recorded", () => {
    // The empty-state ``No chemistry recorded`` line MUST still
    // render when both readings and chemicals are empty — CHEM-LOCK
    // is a preference/skip fix, not an empty-state removal.
    expect(SRC).toMatch(/No chemistry recorded/);
    expect(SRC).toMatch(
      /data-testid="portal-service-report-primary-empty"/,
    );
  });
});
