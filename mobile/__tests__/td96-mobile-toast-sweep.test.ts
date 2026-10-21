/**
 * TD-96-mobile-toast-sweep · regression guard.
 * The 4a8d04429 Alert→Toast rollout replaced `Alert.alert` with
 * `showToast(...)` in 20 files without wiring `useToast()`, so success paths
 * threw ReferenceErrors / showed false "Error" alerts (tsc TS2304, hidden in
 * the 650-error baseline). Every file that CALLS `showToast(` must also
 * DECLARE it: `const { showToast } = useToast()`, a prop / param / type
 * member named `showToast`, a local function, or an import.
 */
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(__dirname, "..");
const DECL = new RegExp([
  String.raw`(const|let|var)\s*\{[^}]*\bshowToast\b[^}]*\}\s*=`,
  String.raw`\bshowToast\s*\??\s*:`,
  String.raw`[(,{]\s*showToast\s*[,)}=:]`,
  String.raw`function\s+showToast\b`,
  String.raw`(const|let|var)\s+showToast\s*=`,
  String.raw`import\s*\{[^}]*\bshowToast\b`,
].join("|"));

function walk(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) { if (e.name !== "node_modules") walk(p, out); }
    else if (/\.tsx?$/.test(e.name)) out.push(p);
  }
  return out;
}

it("every file that calls showToast( declares it (no undefined showToast)", () => {
  const callers = [...walk(path.join(ROOT, "app")), ...walk(path.join(ROOT, "src"))]
    .filter((f) => !f.endsWith("ToastProvider.tsx"))
    .filter((f) => fs.readFileSync(f, "utf-8").includes("showToast("));
  expect(callers.length).toBeGreaterThan(50);
  const undeclared = callers.filter((f) => !DECL.test(fs.readFileSync(f, "utf-8"))).map((f) => path.relative(ROOT, f));
  expect(undeclared).toEqual([]);
});

it("the 20 swept files wire useToast()", () => {
  const swept = [
    "app/(app)/more.tsx", "app/(app)/reviews/recent.tsx", "app/(app)/reviews/requests/[id].tsx",
    "app/(app)/settings/offline-diagnostics.tsx", "app/admin/chemicals.tsx", "app/admin/diagnostics/errors.tsx",
    "app/admin/seo/otto/[id].tsx", "app/customer/new.tsx", "app/estimator/settings.tsx", "app/profit-report.tsx",
    "app/reports/aeo-digest.tsx", "app/reports/weekly-digest.tsx", "app/settings/business-card.tsx",
    "app/settings/ringcentral.tsx", "app/soshie/BrandBrainTab.tsx",
    "src/components/customers/CustomerMultiContactEditor.tsx",
    "src/components/customers/SendServiceRecordsLinkModal.tsx", "src/components/sync/ManualSyncButton.tsx",
    "app/leads/index.tsx",
  ];
  for (const f of swept) {
    const s = fs.readFileSync(path.join(ROOT, f), "utf-8");
    expect([f, /import \{ useToast \} from "@\/src\/components\/ToastProvider";/.test(s)]).toEqual([f, true]);
    expect([f, /const \{ showToast \} = useToast\(\);/.test(s)]).toEqual([f, true]);
  }
});
