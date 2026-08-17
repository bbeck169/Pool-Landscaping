// Feb-2026 P1 · Customers Tag filter dropdown — source-inspection
// vitest. Replaces the previous 147-chip bar with a searchable
// multi-select popover. Locks in:
//   • Trigger button + collapsed / populated states
//   • Popover contains auto-focused search + system section +
//     divider + rest + no-match empty state + footer actions.
//   • System tags rendered with the Lock icon + SYSTEM badge.
//   • Selected pills with individual removes + "+N more" collapse.
//   • Multi-select AND semantics preserved via the toggle helper.
//   • URL sync unchanged (setSelectedTags still owned by parent).
//   • Reuses shadcn Popover — no new library added.
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const DROPDOWN = resolve(
  __dirname, "../components/customers/CustomersTagFilterDropdown.jsx",
);
const LIST = resolve(__dirname, "../pages/customers/CustomersList.jsx");

const read = (p) => readFileSync(p, "utf8");

describe("Feb-2026 P1 · Customers Tag filter dropdown", () => {
  it("dropdown component file exists", () => {
    expect(existsSync(DROPDOWN)).toBe(true);
  });

  const src = read(DROPDOWN);

  describe("component structure", () => {
    it("re-uses the existing shadcn Popover primitive (no new library)", () => {
      expect(src).toContain('from "@/components/ui/popover"');
      expect(src).toContain("<Popover ");
      expect(src).toContain("<PopoverTrigger");
      expect(src).toContain("<PopoverContent");
    });

    it("exposes the locked-in testIDs", () => {
      expect(src).toContain('data-testid="customers-tag-filter-dropdown"');
      expect(src).toContain('data-testid="customers-tag-filter-button"');
      expect(src).toContain('data-testid="customers-tag-filter-popover"');
      expect(src).toContain('data-testid="customers-tag-filter-search"');
      expect(src).toContain('data-testid="customers-tag-filter-clear-all"');
      expect(src).toContain('data-testid="customers-tag-filter-footer-clear-all"');
      expect(src).toContain('data-testid="customers-tag-filter-footer-done"');
      // Templated per-option + per-pill testIDs.
      expect(src).toContain("`customers-tag-filter-option-${tag.name}`");
      expect(src).toContain("`customers-tag-selected-pill-${name}`");
      expect(src).toContain("`customers-tag-selected-pill-remove-${name}`");
      expect(src).toContain('data-testid="customers-tag-selected-more"');
    });

    it("button label switches on selection state", () => {
      expect(src).toContain('"Filter by tag"');
      expect(src).toMatch(/\$\{selectedTags\.size\} tag/);
    });

    it("auto-focuses the search input on open", () => {
      expect(src).toContain("autoFocus");
      // Resets query when the popover closes so the next open starts fresh.
      expect(src).toContain('if (!next) setQuery("")');
    });
  });

  describe("system-first ordering + lock icon + SYSTEM badge", () => {
    it("splits list into system + rest and pins system first", () => {
      expect(src).toContain("(allTags || []).filter((t) => t.is_system)");
      expect(src).toContain("(a.name || \"\").localeCompare(b.name || \"\")");
    });

    it("renders the Lock icon + SYSTEM badge on system rows", () => {
      // Lock icon rendered inside OptionRow when is_system is true.
      expect(src).toMatch(/tag\.is_system \? <Lock/);
      expect(src).toMatch(/>\s*System\s*</);
    });

    it("renders a divider between system + rest sections", () => {
      // Uses colors.divider on a 1px inline height:1 spacer.
      expect(src).toMatch(/height:\s*1[^\}]+colors\.divider/);
    });
  });

  describe("multi-select AND semantics + URL sync preserved", () => {
    it("does NOT own selectedTags — parent CustomersList still drives URL sync", () => {
      // Component takes selectedTags + setSelectedTags as props; no
      // useSearchParams / useEffect that reaches out to the URL.
      expect(src).not.toContain("useSearchParams");
      expect(src).not.toContain("window.location");
    });

    it("toggle helper adds/removes single tag names from a Set", () => {
      expect(src).toMatch(/const next = new Set\(selectedTags\)/);
      expect(src).toMatch(/next\.has\(name\)/);
    });

    it("clearAll resets to an empty Set", () => {
      expect(src).toContain("const clearAll = () => setSelectedTags(new Set())");
    });
  });

  describe("selected-state pill row + '+N more' collapse", () => {
    it("caps visible pills at MAX_SELECTED_PILL", () => {
      expect(src).toContain("MAX_SELECTED_PILL = 3");
      expect(src).toContain("selectedList.slice(0, MAX_SELECTED_PILL)");
      expect(src).toMatch(/overflowCount = Math\.max\(0/);
    });

    it("each pill has an individual remove affordance", () => {
      expect(src).toContain("Remove ${name} filter");
      // Remove wires back into the same toggle helper.
      expect(src).toMatch(/onClick=\{\(\) => toggle\(name\)\}/);
    });
  });

  describe("no-match empty state", () => {
    it("renders a friendly no-match block when the search comes up empty", () => {
      expect(src).toContain('data-testid="customers-tag-filter-no-match"');
      expect(src).toMatch(/No tags match/);
    });
  });
});

describe("CustomersList wiring", () => {
  const list = read(LIST);

  it("imports and mounts the new dropdown", () => {
    expect(list).toContain(
      'import CustomersTagFilterDropdown from "@/components/customers/CustomersTagFilterDropdown"',
    );
    expect(list).toContain("<CustomersTagFilterDropdown");
  });

  it("no longer renders the old 147-chip bar", () => {
    expect(list).not.toContain('data-testid="customers-tag-chipbar"');
    expect(list).not.toContain("customers-tag-chip-");
  });

  it("URL sync effect still lives in the page (unchanged surface)", () => {
    // The Feb-2026 URL sync effect + AND filter live here, not in
    // the dropdown component.
    expect(list).toContain('p.set("tags", arr.join(","));');
    expect(list).toMatch(/const rowTags = new Set\(r\.tags \|\| \[\]\)/);
  });
});
