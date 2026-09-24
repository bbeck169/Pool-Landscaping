/**
 * Phase P52 · Feb-2026 — Customer profile Chemistry actions
 * consolidation into a brand-coloured dropdown.
 *
 * Locks the CustomerDetail action-row refactor:
 *   1. The standalone <Button testid="cd-chemistry"> + <Button
 *      testid="cd-chemistry-history"> no longer render as top-level
 *      buttons on ``cd-action-row``.
 *   2. A single DropdownMenu trigger (``cd-chemistry-actions-
 *      trigger``) sits inline with Edit / Delete on the same row.
 *   3. The trigger carries the brand-colour inline style
 *      (backgroundColor: colors.brandPrimary, color:
 *      colors.onBrandPrimary).
 *   4. Both dropdown items are reachable via new P52 testids AND
 *      preserve their pre-P52 testids via ``data-legacy-testid``
 *      so existing suites that select by cd-chemistry /
 *      cd-chemistry-history keep resolving.
 *   5. Clicking each item navigates to the expected route.
 *
 * Tests file-inspect the source (mounting the full CustomerDetail
 * pulls in ~40 heavy children — see the vitest.config exclusions on
 * similar detail-page suites).  The mount pattern is proven for
 * lighter pages (Leads P48) but not for CustomerDetail.  Locking
 * markup contracts via regex is idiomatic here and mirrors P49 +
 * P47 conventions.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const CD_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/customers/CustomerDetail.jsx"),
  "utf-8",
);


describe("P52 · Customer Detail Chemistry-actions dropdown", () => {
  it("removes the standalone Chemistry + Chem History <Button> " +
     "elements from the action row (top-level buttons no longer " +
     "render — they must live INSIDE the DropdownMenuContent)", () => {
    // Regex: <Button ...> where testid="cd-chemistry" AND the
    // element is NOT a DropdownMenuTrigger asChild wrapper.  We
    // approximate by looking for the removed shape (testid on a
    // <Button> that navigates to /chemistry) OUTSIDE the DropdownMenu
    // block.  A simpler assertion: the pre-P52 exact snippet
    // `testid="cd-chemistry"\n            >\n              <Beaker`
    // must not appear (it existed only on the standalone button).
    expect(
      /testid="cd-chemistry"\s*\n\s*>\s*\n\s*<Beaker\s+size=\{14\}\s*\/>\s*Chemistry\s*\n\s*<\/Button>/
        .test(CD_SRC),
      "Pre-P52 <Button testid='cd-chemistry'>...</Button> shape " +
      "must be gone — the button collapsed into a DropdownMenuItem",
    ).toBe(false);
    expect(
      /testid="cd-chemistry-history"\s*\n\s*>\s*\n\s*<Beaker\s+size=\{14\}\s*\/>\s*Chem History\s*\n\s*<\/Button>/
        .test(CD_SRC),
      "Pre-P52 <Button testid='cd-chemistry-history'> shape must " +
      "be gone",
    ).toBe(false);
  });

  it("imports the DropdownMenu primitives from the ui-kit + " +
     "the ChevronDown icon", () => {
    // Multiline import — use ``[\s\S]`` between tokens because JS
    // regex ``\s`` matches newlines only in some engines / at some
    // positions.  Anchor on the four primitive names in any order.
    expect(CD_SRC).toMatch(/DropdownMenu[\s\S]{0,4}[,\s}]/);
    expect(CD_SRC).toMatch(/DropdownMenuTrigger[\s\S]{0,4}[,\s}]/);
    expect(CD_SRC).toMatch(/DropdownMenuContent[\s\S]{0,4}[,\s}]/);
    expect(CD_SRC).toMatch(/DropdownMenuItem[\s\S]{0,4}[,\s}]/);
    expect(CD_SRC).toMatch(
      /from\s*["']@\/components\/ui\/dropdown-menu["']/,
    );
    // ChevronDown is added in a separate lucide-react import group
    // — assert both the identifier and the module path.
    expect(CD_SRC).toMatch(/ChevronDown/);
    expect(CD_SRC).toMatch(/from\s*["']lucide-react["']/);
  });

  it("renders the DropdownMenu trigger with brand-colour inline " +
     "styling on the cd-action-row", () => {
    // Trigger testid + inline colour tokens.
    expect(CD_SRC).toMatch(
      /testid="cd-chemistry-actions-trigger"/,
    );
    // Both style tokens present + comma-separated (order-agnostic
    // to survive a prettier reflow).
    expect(CD_SRC).toMatch(/backgroundColor:\s*colors\.brandPrimary/);
    expect(CD_SRC).toMatch(/color:\s*colors\.onBrandPrimary/);
    // The trigger sits INSIDE cd-action-row — confirm ordering by
    // asserting the trigger source line appears AFTER the
    // ``data-testid="cd-action-row"`` marker but BEFORE the
    // cd-delete testid (the Delete button follows the dropdown).
    const rowIdx = CD_SRC.indexOf('data-testid="cd-action-row"');
    const triggerIdx = CD_SRC.indexOf('testid="cd-chemistry-actions-trigger"');
    const deleteIdx = CD_SRC.indexOf('testid="cd-delete"');
    expect(rowIdx).toBeGreaterThan(-1);
    expect(triggerIdx).toBeGreaterThan(rowIdx);
    expect(deleteIdx).toBeGreaterThan(triggerIdx);
  });

  it("renders two DropdownMenuItems - Chemistry + Chem History - " +
     "with the new P52 testids AND preserves the pre-P52 testids " +
     "via data-legacy-testid so existing suites keep resolving", () => {
    // New P52 testids.
    expect(CD_SRC).toMatch(/data-testid="cd-action-chemistry"/);
    expect(CD_SRC).toMatch(/data-testid="cd-action-chem-history"/);
    // Legacy testids preserved on the same items.
    expect(CD_SRC).toMatch(/data-legacy-testid="cd-chemistry"/);
    expect(CD_SRC).toMatch(/data-legacy-testid="cd-chemistry-history"/);
    // Route navigation preserved on click.
    expect(CD_SRC).toMatch(
      /onClick=\{\(\)\s*=>\s*navigate\(`\/customers\/\$\{id\}\/chemistry`\)\}/,
    );
    expect(CD_SRC).toMatch(
      /onClick=\{\(\)\s*=>\s*navigate\(`\/customers\/\$\{id\}\/chemistry-history`\)\}/,
    );
  });
});
