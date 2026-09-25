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
 *     "+ Create" submenu on CustomerActionDropdowns.
 *
 * Chemistry submenu contract (CustomerActionDropdowns.jsx):
 *   • Uses shadcn ``DropdownMenuSub`` / ``DropdownMenuSubTrigger``
 *     / ``DropdownMenuSubContent`` primitives.
 *   • Submenu trigger carries ``data-testid=
 *     "customer-create-chemistry-submenu"``.
 *   • Both options preserved with their legacy testids:
 *     ``cd-action-chemistry`` (→ ``/customers/:id/chemistry``)
 *     and ``cd-action-chem-history`` (→
 *     ``/customers/:id/chemistry-history``).
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

  it("+ Create dropdown carries a Chemistry submenu using shadcn Sub primitives", () => {
    // Import surface — the three sub-primitives must be present.
    expect(actionsSrc).toMatch(
      /import\s+\{[\s\S]*DropdownMenuSub\b[\s\S]*\}\s+from\s+"@\/components\/ui\/dropdown-menu"/);
    expect(actionsSrc).toContain("DropdownMenuSubTrigger");
    expect(actionsSrc).toContain("DropdownMenuSubContent");
    // Submenu is mounted inside the + Create menu.
    const createIdx = actionsSrc.indexOf(
      'testid="customer-create-menu-trigger"');
    expect(createIdx).toBeGreaterThan(-1);
    const submenuIdx = actionsSrc.indexOf(
      'data-testid="customer-create-chemistry-submenu"');
    expect(submenuIdx).toBeGreaterThan(createIdx);
  });

  it("both Chemistry options preserved with legacy testids + handlers", () => {
    // Chemistry
    expect(actionsSrc).toMatch(
      /navigate\(`\/customers\/\$\{cid\}\/chemistry`\)/);
    expect(actionsSrc).toContain('data-testid="cd-action-chemistry"');
    expect(actionsSrc).toContain('data-legacy-testid="cd-chemistry"');
    // Chemistry History
    expect(actionsSrc).toMatch(
      /navigate\(`\/customers\/\$\{cid\}\/chemistry-history`\)/);
    expect(actionsSrc).toContain(
      'data-testid="cd-action-chem-history"');
    expect(actionsSrc).toContain(
      'data-legacy-testid="cd-chemistry-history"');
    // Both options carry the visible label copy.
    const submenuIdx = actionsSrc.indexOf(
      'data-testid="customer-create-chemistry-submenu"');
    const contentBlock = actionsSrc.slice(submenuIdx,
                                           submenuIdx + 1500);
    expect(contentBlock).toMatch(/Chemistry\b/);
    expect(contentBlock).toMatch(/Chemistry History/);
  });
});
