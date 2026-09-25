/**
 * Phase P52 · Feb-2026 — Customer profile Chemistry actions
 * consolidation into the ``+ Create`` menu.
 *
 * History:
 *
 *   Round 0 (pre-P52) — Chemistry + Chem History rendered as two
 *   standalone brand-coloured <Button> elements directly on
 *   ``cd-action-row``.
 *
 *   Round 1 (cc5477dc4) — the pair collapsed into a single
 *   brand-coloured <DropdownMenu> whose trigger lived on
 *   ``cd-action-row`` (testid ``cd-chemistry-actions-trigger``)
 *   and whose two items were the Chemistry / Chem History
 *   destinations.
 *
 *   Round 2 (cc5477dc4, same commit) — the brand-coloured
 *   dropdown was in turn folded into the ``+ Create`` menu on
 *   ``CustomerActionDropdowns.jsx`` as a nested ``DropdownMenuSub``
 *   labelled ``Chemistry…``.  The ``cd-action-row`` inline
 *   trigger and the DropdownMenu primitive imports were removed
 *   from ``CustomerDetail.jsx`` entirely.
 *
 *   Round 3 (15b87aaaf, this refactor) — the ``DropdownMenuSub``
 *   was FLATTENED per user ruling.  Chemistry + Chemistry History
 *   now render as top-level ``DropdownMenuItem`` siblings inside
 *   the ``+ Create`` menu on ``CustomerActionDropdowns.jsx``,
 *   sitting directly after the ``Meeting`` item.  Both items
 *   preserve their P52 testids AND their pre-P52 legacy testids
 *   via ``data-legacy-testid``.
 *
 * Contract locked by this file (post-round-3):
 *   1. The pre-P52 standalone <Button testid="cd-chemistry"> and
 *      <Button testid="cd-chemistry-history"> shapes are GONE
 *      from ``CustomerDetail.jsx`` (round-0 → round-1 regression
 *      guard — file-inspects ``CustomerDetail.jsx``).
 *   2. ``CustomerActionDropdowns.jsx`` imports only the four base
 *      DropdownMenu primitives (Menu, Trigger, Content, Item).
 *      Sub / SubTrigger / SubContent / Portal were removed by the
 *      round-3 flatten and any re-import here would be dead code.
 *   3. ``CustomerDetail.jsx`` no longer carries the round-1
 *      ``cd-chemistry-actions-trigger`` inline dropdown trigger,
 *      AND ``CustomerActionDropdowns.jsx`` carries the ``+ Create``
 *      menu trigger (``customer-create-menu-trigger``) that
 *      subsumed it.
 *   4. ``CustomerActionDropdowns.jsx`` renders both Chemistry
 *      items as flat siblings — both P52 testids
 *      (``cd-action-chemistry`` / ``cd-action-chem-history``) and
 *      both pre-P52 legacy testids (``cd-chemistry`` /
 *      ``cd-chemistry-history``) are present, and both items
 *      navigate to the expected ``/customers/${cid}/chemistry``
 *      and ``/customers/${cid}/chemistry-history`` routes.
 *
 * File-inspect (not mount) — CustomerDetail pulls in ~40 heavy
 * children so we lock markup contracts via regex, matching P49 /
 * P47 conventions.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const CD_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/customers/CustomerDetail.jsx"),
  "utf-8",
);
const ACTIONS_SRC = fs.readFileSync(
  path.resolve(__dirname,
      "../components/customers/CustomerActionDropdowns.jsx"),
  "utf-8",
);


describe("P52 · Customer Detail Chemistry-actions (post-round-3 flatten)", () => {
  it("removes the pre-P52 standalone Chemistry + Chem History " +
     "<Button> shapes from CustomerDetail.jsx (round-0 → round-1 " +
     "regression guard)", () => {
    // The pre-P52 exact snippet
    //   `testid="cd-chemistry"\n            >\n              <Beaker`
    // must not appear anywhere in CustomerDetail.jsx (it existed
    // only on the standalone button that was pulled in round 1).
    expect(
      /testid="cd-chemistry"\s*\n\s*>\s*\n\s*<Beaker\s+size=\{14\}\s*\/>\s*Chemistry\s*\n\s*<\/Button>/
        .test(CD_SRC),
      "Pre-P52 <Button testid='cd-chemistry'>...</Button> shape " +
      "must be gone — the button collapsed into a DropdownMenuItem " +
      "on CustomerActionDropdowns.jsx",
    ).toBe(false);
    expect(
      /testid="cd-chemistry-history"\s*\n\s*>\s*\n\s*<Beaker\s+size=\{14\}\s*\/>\s*Chem History\s*\n\s*<\/Button>/
        .test(CD_SRC),
      "Pre-P52 <Button testid='cd-chemistry-history'> shape must " +
      "be gone",
    ).toBe(false);
  });

  it("CustomerActionDropdowns.jsx imports ONLY the four base " +
     "DropdownMenu primitives — Sub / Portal primitives removed " +
     "by the round-3 flatten", () => {
    // Isolate the dropdown-menu import block so a comment prose
    // mention of the identifiers doesn't false-positive.
    const importBlockMatch = ACTIONS_SRC.match(
      /import\s+\{([\s\S]*?)\}\s+from\s+"@\/components\/ui\/dropdown-menu"/,
    );
    expect(importBlockMatch).not.toBeNull();
    const importBlock = importBlockMatch[1];
    // Base primitives — must all be present.
    expect(importBlock).toMatch(/\bDropdownMenu\b/);
    expect(importBlock).toMatch(/\bDropdownMenuTrigger\b/);
    expect(importBlock).toMatch(/\bDropdownMenuContent\b/);
    expect(importBlock).toMatch(/\bDropdownMenuItem\b/);
    // Sub + Portal primitives — must all be absent.
    expect(importBlock).not.toMatch(/\bDropdownMenuSub\b/);
    expect(importBlock).not.toMatch(/\bDropdownMenuSubTrigger\b/);
    expect(importBlock).not.toMatch(/\bDropdownMenuSubContent\b/);
    expect(importBlock).not.toMatch(/\bDropdownMenuPortal\b/);
    // And no JSX open-tag for any of them either.
    expect(ACTIONS_SRC).not.toMatch(
      /<DropdownMenuSub(?:Trigger|Content|Portal)?\b/,
    );
  });

  it("round-1 inline ``cd-chemistry-actions-trigger`` is gone " +
     "from CustomerDetail.jsx, and CustomerActionDropdowns.jsx " +
     "carries the ``customer-create-menu-trigger`` that replaced it", () => {
    // Round 2 pulled the trigger out of CustomerDetail.jsx.
    expect(CD_SRC).not.toContain("cd-chemistry-actions-trigger");
    // Round 3 kept the replacement trigger on the + Create menu.
    expect(ACTIONS_SRC).toMatch(/testid="customer-create-menu-trigger"/);
    // The round-1 nested submenu trigger is also gone (round-3).
    expect(ACTIONS_SRC).not.toContain("customer-create-chemistry-submenu");
  });

  it("renders two DropdownMenuItems — Chemistry + Chemistry " +
     "History — with the new P52 testids AND preserves the " +
     "pre-P52 testids via data-legacy-testid so existing suites " +
     "keep resolving", () => {
    // New P52 testids on CustomerActionDropdowns.jsx (post-round-3
    // flat siblings, not CD_SRC any more).
    expect(ACTIONS_SRC).toMatch(/data-testid="cd-action-chemistry"/);
    expect(ACTIONS_SRC).toMatch(/data-testid="cd-action-chem-history"/);
    // Legacy testids preserved on the same items.
    expect(ACTIONS_SRC).toMatch(/data-legacy-testid="cd-chemistry"/);
    expect(ACTIONS_SRC).toMatch(/data-legacy-testid="cd-chemistry-history"/);
    // Route navigation preserved on select — post-round-2 the
    // variable is ``cid`` (was ``id`` in the round-0 CustomerDetail
    // scope).  Both destinations render as ``onSelect={() =>
    // navigate(`/customers/${cid}/chemistry(-history)?`)}``.
    expect(ACTIONS_SRC).toMatch(
      /onSelect=\{\(\)\s*=>\s*navigate\(`\/customers\/\$\{cid\}\/chemistry`\)\}/,
    );
    expect(ACTIONS_SRC).toMatch(
      /navigate\(`\/customers\/\$\{cid\}\/chemistry-history`\)/,
    );
  });
});
