/**
 * Feb-2026 · Customer Header Navy Strip
 * ────────────────────────────────────────────────────────────────
 * Regression coverage for the unified navy command strip on
 * ``CustomerDetail.jsx``.
 *
 * Layout contract:
 *   • A single container tagged ``data-testid="cd-command-strip"``
 *     sits below the Portal Access panel and above the Header
 *     card. It carries ``colors.nav.bg`` as its background.
 *   • The Overview dropdown (ResponsiveTabs) lives INSIDE the
 *     strip; its shell testid ``cd-tabs-dropdown-shell`` is
 *     retained.
 *   • The action-row testid ``cd-action-row`` also lives INSIDE
 *     the strip.
 *   • The standalone inline Chemistry brand dropdown (previously
 *     rendered right after the Edit button) is GONE from
 *     CustomerDetail.jsx; its two options now live inside the
 *     ``+ Create`` menu on CustomerActionDropdowns.
 *
 * Chemistry flat-items contract (CustomerActionDropdowns.jsx):
 *   Round 2 (2026-02) — the intermediate ``DropdownMenuSub``
 *   labelled ``Chemistry…`` was FLATTENED per user ruling.  The
 *   two items now render as top-level ``+ Create`` siblings,
 *   sitting directly after ``Meeting`` in source order.  Both
 *   items preserve their P52 testids AND their pre-P52 legacy
 *   testids:
 *
 *     • ``cd-action-chemistry`` / ``cd-chemistry`` →
 *       ``/customers/:id/chemistry``
 *     • ``cd-action-chem-history`` / ``cd-chemistry-history`` →
 *       ``/customers/:id/chemistry-history``
 *
 *   Neither ``DropdownMenuSub`` / ``DropdownMenuSubTrigger`` /
 *   ``DropdownMenuSubContent`` / ``DropdownMenuPortal`` remains
 *   imported or mounted in the file after the flatten.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(__dirname,
  "../pages/customers/CustomerDetail.jsx");
const ACTIONS_PATH = resolve(__dirname,
  "../components/customers/CustomerActionDropdowns.jsx");
const pageSrc = readFileSync(PAGE_PATH, "utf8");
const actionsSrc = readFileSync(ACTIONS_PATH, "utf8");


describe("CustomerDetail · unified navy command strip", () => {
  it("renders a single navy strip container with colors.nav.bg", () => {
    const idx = pageSrc.indexOf('data-testid="cd-command-strip"');
    expect(idx).toBeGreaterThan(-1);
    // Slice back to the opening <div so we can read the style tag.
    const openIdx = pageSrc.lastIndexOf("<div", idx);
    const slice = pageSrc.slice(openIdx, idx + 60);
    expect(slice).toMatch(/backgroundColor:\s*colors\.nav\.bg/);
    expect(slice).toMatch(/gap-4/);
  });

  it("navy strip sits below Portal Access and above the header card", () => {
    const portalIdx = pageSrc.indexOf("<PortalInviteQuickAction");
    const stripIdx = pageSrc.indexOf('data-testid="cd-command-strip"');
    const headerCardIdx = pageSrc.indexOf("{/* Header card */}");
    expect(portalIdx).toBeGreaterThan(-1);
    expect(stripIdx).toBeGreaterThan(portalIdx);
    expect(headerCardIdx).toBeGreaterThan(stripIdx);
  });

  it("Overview dropdown + action row both live inside the strip", () => {
    const stripIdx = pageSrc.indexOf(
      'data-testid="cd-command-strip"');
    // Take a generous forward slice — both testids MUST appear
    // before the strip's closing tag (i.e. before the "Header
    // card" comment which starts the next sibling block).
    const nextBlockIdx = pageSrc.indexOf("{/* Header card */}",
                                            stripIdx);
    const stripBlock = pageSrc.slice(stripIdx, nextBlockIdx);
    expect(stripBlock).toContain('data-testid="cd-tabs-dropdown-shell"');
    expect(stripBlock).toContain('data-testid="cd-action-row"');
  });

  it("standalone Chemistry dropdown is removed from CustomerDetail", () => {
    // The previous cd-chemistry-actions-trigger testid on the
    // inline brand dropdown must NOT appear anywhere in the
    // page source (it lived at ~ line 787 pre-fix).
    expect(pageSrc).not.toContain("cd-chemistry-actions-trigger");
    // And the file no longer imports the DropdownMenu* primitives
    // that only powered that removed block.
    expect(pageSrc).not.toMatch(
      /^import\s+\{\s*ChevronDown\s*\}\s+from\s+"lucide-react"/m);
    expect(pageSrc).not.toMatch(
      /import\s+\{[\s\S]*DropdownMenuTrigger[\s\S]*\}\s+from\s+"@\/components\/ui\/dropdown-menu"/);
  });

  it("+ Create dropdown carries Chemistry items as FLAT siblings — no Sub primitives", () => {
    // Round-2 flatten — the intermediate ``DropdownMenuSub`` /
    // ``DropdownMenuSubTrigger`` / ``DropdownMenuSubContent`` /
    // ``DropdownMenuPortal`` primitives are no longer imported or
    // mounted anywhere in CustomerActionDropdowns.jsx.  Guarding
    // against a regressed re-nest — check JSX open-tags AND the
    // dropdown-menu import list, but tolerate identifiers that
    // appear only inside inline comment prose.
    const jsxOpens =
      /<DropdownMenuSub(?:Trigger|Content|Portal)?\b/;
    expect(actionsSrc).not.toMatch(jsxOpens);
    // Import surface — the file must import ONLY the base four
    // primitives (Menu, Trigger, Content, Item).  Any Sub / Portal
    // import here would be dead code.
    const dropdownImportBlock = actionsSrc.match(
      /import\s+\{([\s\S]*?)\}\s+from\s+"@\/components\/ui\/dropdown-menu"/,
    )?.[1] || "";
    expect(dropdownImportBlock).not.toMatch(/\bDropdownMenuSub\b/);
    expect(dropdownImportBlock).not.toMatch(/\bDropdownMenuPortal\b/);
    // And the submenu-trigger testid is gone.
    expect(actionsSrc).not.toContain("customer-create-chemistry-submenu");
  });

  it("Chemistry + Chemistry History render as flat siblings AFTER Meeting", () => {
    // Source-order lock — Meeting → Chemistry → Chemistry History,
    // all three as top-level ``+ Create`` items.  A future refactor
    // that reorders (or re-nests) any of them trips this.
    const meetingIdx = actionsSrc.indexOf(
      'data-testid="customer-create-meeting"');
    const chemistryIdx = actionsSrc.indexOf(
      'data-testid="cd-action-chemistry"');
    const chemHistoryIdx = actionsSrc.indexOf(
      'data-testid="cd-action-chem-history"');
    expect(meetingIdx).toBeGreaterThan(-1);
    expect(chemistryIdx).toBeGreaterThan(meetingIdx);
    expect(chemHistoryIdx).toBeGreaterThan(chemistryIdx);
  });

  it("both Chemistry options preserved with legacy testids + handlers + labels", () => {
    // Chemistry — nav destination, both testids, visible label.
    expect(actionsSrc).toMatch(
      /navigate\(`\/customers\/\$\{cid\}\/chemistry`\)/);
    expect(actionsSrc).toContain('data-testid="cd-action-chemistry"');
    expect(actionsSrc).toContain('data-legacy-testid="cd-chemistry"');
    // Chemistry History — nav destination, both testids, visible label.
    expect(actionsSrc).toMatch(
      /navigate\(`\/customers\/\$\{cid\}\/chemistry-history`\)/);
    expect(actionsSrc).toContain(
      'data-testid="cd-action-chem-history"');
    expect(actionsSrc).toContain(
      'data-legacy-testid="cd-chemistry-history"');
    // Both options render inside the SAME + Create menu content
    // as the Meeting item.  Slice from ``Meeting`` through to the
    // closing DropdownMenuContent and confirm both label copies +
    // both Beaker icons appear.
    const meetingIdx = actionsSrc.indexOf(
      'data-testid="customer-create-meeting"');
    const contentEndIdx = actionsSrc.indexOf(
      "</DropdownMenuContent>", meetingIdx);
    const flatBlock = actionsSrc.slice(meetingIdx, contentEndIdx);
    expect(flatBlock).toMatch(/Chemistry\b/);
    expect(flatBlock).toMatch(/Chemistry History/);
    // Beaker icons on both — 2 hits expected.
    const beakerHits = flatBlock.match(
      /<Beaker\s+size=\{14\}\s+className="mr-2"\s*\/>/g) || [];
    expect(beakerHits.length).toBeGreaterThanOrEqual(2);
  });
});
