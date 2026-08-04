// Phase 41.2 · Feb-2026 — source-inspection vitest.
//
// Locks in the 5 pages migrated onto the shared `<AdminListPage>`
// primitive and the primitive itself. Uses fs.readFileSync to keep the
// suite lightweight — no RN renderer, no MetroProvider, no expo-router
// setup. Mirrors the Phase 35 / 36 / 37 style.
//
// Regression guards:
//   • each migrated file must `import { AdminListPage } from
//     "@/src/components/layout/AdminListPage"`
//   • each must NOT hand-wire `RoleGate` + `ScrollView` +
//     `RefreshControl` at the same time any more — that's the whole
//     point of the extraction.
//   • Preserved testIDs: `{page}-page`, `{page}-empty`, `{page}-create`
//     (where applicable), `{page}-sheet` (where applicable). These get
//     asserted verbatim so downstream tests / e2e drivers stay green.
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const MOBILE = resolve(__dirname, "../../../mobile");
const PRIMITIVE_PATH = resolve(MOBILE, "src/components/layout/AdminListPage.tsx");

const MIGRATED = [
  {
    file: "app/finance/recurring-jobs.tsx",
    pageTestID: "recurring-jobs-page",
    emptyTestID: "recurring-empty",
    createTestID: null, // no create button — desktop-only creation
    sheetTestID: null,
  },
  {
    file: "app/finance/vendor-bills.tsx",
    pageTestID: "vendor-bills-page",
    emptyTestID: "vendor-bills-empty",
    createTestID: "vendor-bills-create",
    sheetTestID: "vendor-bills-sheet",
  },
  {
    file: "app/os/scorecards.tsx",
    pageTestID: "os-scorecards-page",
    emptyTestID: "os-scorecards-empty",
    createTestID: "os-scorecards-create",
    sheetTestID: "os-scorecards-sheet",
  },
  {
    file: "app/os/roles.tsx",
    pageTestID: "os-roles-page",
    emptyTestID: "os-roles-empty",
    createTestID: "os-roles-create",
    sheetTestID: "os-roles-sheet",
  },
  {
    file: "app/os/sops.tsx",
    pageTestID: "os-sops-page",
    emptyTestID: "os-sops-empty",
    createTestID: "os-sops-create",
    sheetTestID: "os-sops-sheet",
  },
];

const _read = (rel: string) => readFileSync(resolve(MOBILE, rel), "utf8");

describe("Phase 41.2 · AdminListPage primitive", () => {
  it("primitive file exists at the expected path", () => {
    expect(existsSync(PRIMITIVE_PATH)).toBe(true);
  });

  it("primitive exports AdminListPage and its prop type", () => {
    const src = readFileSync(PRIMITIVE_PATH, "utf8");
    expect(src).toContain("export function AdminListPage");
    expect(src).toContain("export type AdminListPageProps");
    // Wraps in RoleGate, ScrollView + RefreshControl, EmptyState/Loading.
    expect(src).toContain("<RoleGate ");
    expect(src).toContain("<ScrollView");
    expect(src).toContain("RefreshControl ");
    expect(src).toContain("<EmptyState");
    expect(src).toContain("<Loading />");
    expect(src).toContain('roleLevel = "strict_admin"');
  });
});

describe("Phase 41.2 · migrated pages import and use AdminListPage", () => {
  MIGRATED.forEach(({ file, pageTestID, emptyTestID, createTestID, sheetTestID }) => {
    describe(file, () => {
      const src = _read(file);

      it("imports AdminListPage from the shared layout path", () => {
        expect(src).toMatch(/from ["']@\/src\/components\/layout\/AdminListPage["']/);
        expect(src).toContain("AdminListPage");
      });

      it("mounts <AdminListPage> in its JSX", () => {
        expect(src).toContain("<AdminListPage");
        expect(src).toContain("</AdminListPage>");
      });

      it("no longer hand-wires RoleGate + ScrollView + RefreshControl inline", () => {
        // The primitive owns all three. A page that still imports and
        // renders `<RoleGate>` next to its own `<ScrollView>` + hand-rolled
        // `<RefreshControl>` has NOT actually been migrated.
        const hasRoleGateTag = /<RoleGate\b/.test(src);
        const hasScrollViewTag = /<ScrollView\b/.test(src);
        const hasRefreshControlTag = /<RefreshControl\b/.test(src);
        // At most ONE of the three should still be present (e.g. a nested
        // ScrollView inside a bespoke row is fine); all three at once is
        // the tell-tale unmigrated shape.
        const flags = [hasRoleGateTag, hasScrollViewTag, hasRefreshControlTag].filter(Boolean).length;
        expect(flags).toBeLessThanOrEqual(1);
      });

      it("preserves the page testID", () => {
        expect(src).toContain(`testID="${pageTestID}"`);
      });

      it("preserves the empty-state testID", () => {
        expect(src).toContain(`emptyTestID="${emptyTestID}"`);
      });

      if (createTestID) {
        it("preserves the create-button testID via createTestID prop", () => {
          expect(src).toContain(`createTestID="${createTestID}"`);
        });
      }

      if (sheetTestID) {
        it("mounts a <Sheet> with the expected testID via the sheet prop", () => {
          expect(src).toContain(`testID="${sheetTestID}"`);
          expect(src).toContain("<Sheet");
        });
      }
    });
  });
});

describe("Phase 41.2 · LOC reduction gate", () => {
  // Guard against future untangling of the primitive — if someone adds
  // dozens of lines back into a migrated page, this budget catches it.
  const BUDGETS: Record<string, number> = {
    "app/finance/recurring-jobs.tsx": 170,
    "app/finance/vendor-bills.tsx": 220,
    "app/os/scorecards.tsx": 110,
    "app/os/roles.tsx": 110,
    "app/os/sops.tsx": 120,
  };

  Object.entries(BUDGETS).forEach(([file, cap]) => {
    it(`${file} stays under ${cap} lines`, () => {
      const src = _read(file);
      const lines = src.split("\n").length;
      expect(lines).toBeLessThanOrEqual(cap);
    });
  });
});
