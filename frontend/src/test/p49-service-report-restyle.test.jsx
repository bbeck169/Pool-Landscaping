/**
 * Phase P49 · Feb-2026 — Portal Service Report visual restyle.
 *
 * File-inspection tests locking the visual contract landed in
 * ``frontend/src/pages/portal/PortalServiceReports.jsx`` (the
 * detail view for a single service report):
 *
 *   1.  Page root wraps in ``bg-slate-50 min-h-screen``.
 *   2.  Brand logo (``useTenantBrand().logo_url``) renders at the
 *       top-left of the header card.
 *   3.  "Pool service" / "Landscape service" / "Service" chip
 *       (``data-testid="report-kind"``) uses ``colors.brand`` +
 *       white text.
 *   4.  "Completed" status pill (``data-testid="status-pill-completed"``)
 *       uses the same primary-brand fill.
 *   5.  Pool sections use ``Droplet`` (via ``icon={Droplet}``).
 *   6.  Checklist section uses ``ClipboardCheck``.
 *   7.  Photos sections use ``Image`` (aliased ``ImageIcon`` to avoid
 *       shadowing the DOM ``Image`` constructor).
 *   8.  Chem-band chips use ``bg-amber-500`` / ``bg-emerald-500`` /
 *       ``bg-sky-500`` with ``text-white`` on each.
 *   9.  Every ``rounded-2xl`` card has ``shadow-sm`` — verified
 *       structurally on the ``Section`` shell + the header card.
 *  10.  Every ``data-testid`` present in the source before P49 is
 *       still present after (set equality).
 *  11.  Section icons paint ``w-5 h-5`` fixed (no ``sm:``-scale
 *       shrinkage on mobile) with ``text-slate-700``.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, p), "utf-8");
const SRC = R("../pages/portal/PortalServiceReports.jsx");

// The pre-P49 testid baseline was captured via
// ``grep -oE 'data-testid="[^"]+"' PortalServiceReports.jsx``
// against the file at scope-lock time (27 unique double-quoted
// testids — template-literal testids such as ``data-testid=
// {`chem-label-${…}`}`` do NOT appear here because they use
// backticks, not double-quotes; those are handled implicitly by
// leaving them untouched).  Encoded inline for hermetic testing.
const P49_TESTIDS_BEFORE = [
  "portal-service-report-address",
  "portal-service-report-algae",
  "portal-service-report-back",
  "portal-service-report-chemicals-block",
  "portal-service-report-detail",
  "portal-service-report-error",
  "portal-service-report-primary-empty",
  "portal-service-report-readings-list",
  "portal-service-report-repair-chip",
  "portal-service-report-tech",
  "portal-service-report-title",
  "portal-service-report-visit-date",
  "portal-service-report-water-bodies-list",
  "portal-service-reports",
  "portal-service-reports-error",
  "portal-service-reports-grouped",
  "portal-service-reports-list",
  "service-reports-click-hint",
  "sr-list-filter-from",
  "sr-list-filter-service-type",
  "sr-list-filter-to",
  "sr-list-filters",
  "sr-list-page-indicator",
  "sr-list-pagination",
  "sr-list-pagination-next",
  "sr-list-pagination-prev",
  // TD-75 · Feb-2026 — ``sr-list-search`` removed per operator
  // directive (free-text search input deleted from the filters
  // bar; status/date/service-type filters retained).
];

const P49_TESTIDS_ADDED = [
  "portal-service-report-brand-logo",    // new element — logo <img>
  "portal-service-report-detail-root",   // new element — bg-slate-50 wrapper
  "report-kind",                         // previously injected by <Chip>; now inline
  "status-pill-completed",               // previously injected by <StatusPill>; now inline
  // Phase C.web residual · Feb-2026 — superseded-report banner shipped
  // post-P49 (service-report cross-submission supersedes a prior
  // tech's record and the detail view surfaces the audit anchor).
  // Both testids are additive — zero collisions with the P49 baseline.
  "portal-service-report-superseded-banner",
  "portal-service-report-superseded-original-at",
  // TD-68 · Feb-2026 — Portal theme bundle wraps the LIST / DETAIL
  // returns in the shared ``PortalPageShell`` white-card chrome
  // (parity with /portal/home). The loading-skeleton branch is
  // now its own addressable testid so the three return branches
  // (loading / error / loaded) each surface a stable DOM anchor
  // without colliding on ``portal-service-report-detail`` which
  // the ``portal-service-report-detail.test.jsx`` suite expects
  // to see ONLY on the loaded branch (``renders the error card
  // without a hooks-order crash`` + ``renders the loaded detail
  // card without a hooks-order crash`` tests pin this contract).
  "portal-service-report-loading",
];

describe("Phase P49 · Portal service-report visual restyle", () => {
  it("page root has bg-slate-50 min-h-screen", () => {
    // The new outer wrapper mounts as the first ``<div>`` inside
    // the detail-view ``return`` — pattern is a bare ``<div>`` with
    // ``className="bg-slate-50 min-h-screen"`` + a fresh testid.
    expect(SRC).toMatch(
      /<div\s+className="bg-slate-50 min-h-screen"\s+data-testid="portal-service-report-detail-root"/,
    );
  });

  it("brand logo renders from useTenantBrand().logo_url when present", () => {
    // Hook imported.
    expect(SRC).toMatch(
      /import\s*\{\s*useTenantBrand\s*\}\s*from\s*["']@\/hooks\/useTenantBrand["']/,
    );
    // Destructured at call site with the P49-specific rename.
    expect(SRC).toMatch(
      /const\s*\{\s*logo_url:\s*brandLogoUrl\s*,\s*name:\s*brandName\s*\}\s*=\s*useTenantBrand\(\)/,
    );
    // Conditional img — only renders when the URL is truthy.
    expect(SRC).toMatch(
      /brandLogoUrl\s*\?[\s\S]{0,300}<img\s+[\s\S]{0,300}src=\{brandLogoUrl\}[\s\S]{0,300}data-testid="portal-service-report-brand-logo"/,
    );
    // Responsive sizing per spec — h-8 mobile → h-10 sm+.
    const imgBlock = SRC.match(
      /<img\s+[\s\S]{0,400}data-testid="portal-service-report-brand-logo"[\s\S]{0,120}\/>/,
    );
    expect(imgBlock).not.toBeNull();
    expect(imgBlock[0]).toMatch(/h-8\s+sm:h-10\s+w-auto/);
  });

  it("pool-service chip uses the primary brand color (colors.brand) with white text", () => {
    // The inline branded chip carries ``data-testid="report-kind"``
    // (preserving the pre-P49 wire shape emitted by <Chip>) and
    // paints ``backgroundColor: colors.brand`` + ``text-white``.
    const chip = SRC.match(
      /<span\s+className="text-xs font-semibold px-2 py-0.5 rounded-full text-white"\s+style=\{\{[^}]*backgroundColor:\s*colors\.brand[^}]*\}\}\s+data-testid="report-kind"[\s\S]{0,600}<\/span>/,
    );
    expect(chip).not.toBeNull();
    // Fallback labels intact — pool / landscape / service.
    expect(chip[0]).toMatch(/"Pool service"/);
    expect(chip[0]).toMatch(/"Landscape service"/);
    expect(chip[0]).toMatch(/"Service"/);
  });

  it("completed status pill uses the primary brand color with white text", () => {
    const pill = SRC.match(
      /<span\s+className="text-xs font-semibold px-2\.5 py-1 rounded-full whitespace-nowrap text-white"\s+style=\{\{[^}]*backgroundColor:\s*colors\.brand[^}]*\}\}\s+data-testid="status-pill-completed"[\s\S]{0,200}Completed[\s\S]{0,50}<\/span>/,
    );
    expect(pill).not.toBeNull();
  });

  it("pool primary-chemistry section uses Droplet icon", () => {
    // Match the JSX ``<Section icon={Droplet} title={primaryLabel}
    // testid="portal-service-report-primary-pool">``.
    expect(SRC).toMatch(
      /<Section\s+icon=\{Droplet\}\s+title=\{primaryLabel\}\s+testid="portal-service-report-primary-pool"/,
    );
  });

  it("checklist section uses ClipboardCheck icon", () => {
    expect(SRC).toMatch(
      /<Section\s+icon=\{ClipboardCheck\}[\s\S]{0,200}testid="portal-service-report-checklist"/,
    );
  });

  it("photos sections use Image (aliased ImageIcon) instead of Waves", () => {
    // ``Image`` collides with the DOM ``Image`` constructor so
    // we aliased at import: ``import { Image as ImageIcon }
    // from "lucide-react"``.
    expect(SRC).toMatch(
      /Image as ImageIcon,/,
    );
    // Both photo sections now use it.
    expect(SRC).toMatch(
      /<Section\s+icon=\{ImageIcon\}\s+title="Job Photos"/,
    );
    expect(SRC).toMatch(
      /<Section\s+icon=\{ImageIcon\}\s+title="Visit photos"/,
    );
    // And ``Waves`` is no longer wired into either photo section
    // (may still appear elsewhere — e.g., ``KindIcon`` for pool
    // header — but never on Job Photos / Visit photos).
    expect(SRC).not.toMatch(
      /<Section\s+icon=\{Waves\}\s+title="Job Photos"/,
    );
    expect(SRC).not.toMatch(
      /<Section\s+icon=\{Waves\}\s+title="Visit photos"/,
    );
  });

  it("chem-band chips use bg-amber-500 / bg-emerald-500 / bg-sky-500 with text-white", () => {
    // The three restyled bands.  Elevated stays red — it's a
    // distinct WARN bucket not part of the three-band trio.
    const chemBlock = SRC.match(
      /const CHEM_BAND_STYLES = \{([\s\S]*?)\};/,
    );
    expect(chemBlock).not.toBeNull();
    const cfg = chemBlock[1];
    expect(cfg).toMatch(
      /below:\s*\{\s*className:\s*"bg-sky-500 text-white"/,
    );
    expect(cfg).toMatch(
      /average:\s*\{\s*className:\s*"bg-emerald-500 text-white"/,
    );
    expect(cfg).toMatch(
      /above:\s*\{\s*className:\s*"bg-amber-500 text-white"/,
    );
    // ChemChip flows ``style.className`` through to the ``<span>``.
    expect(SRC).toMatch(
      /className=\{`inline-flex items-center px-2\.5 py-1 rounded-full text-xs font-medium shrink-0 \$\{style\.className\}`\}/,
    );
    // Accessibility — aria-label preserved.
    expect(SRC).toMatch(/aria-label=\{`Chemistry level:/);
  });

  it("Section card + header card carry shadow-sm border", () => {
    // Section shell.
    // Phase C.web residual · Feb-2026 — ``Section`` gained a fifth
    // ``templateFieldId`` prop post-P49 (the checklist-template
    // reclassifier threads the field id through the shell so the
    // "edit field" affordance can target the right template row).
    // Widen the signature regex to accept any destructured arg
    // list — the semantic intent (Section renders a rounded-2xl
    // shadow-sm shell) is preserved.
    const section = SRC.match(
      /function Section\(\{[\s\S]*?\}\)\s*\{[\s\S]*?<div\s+className="([^"]+)"/,
    );
    expect(section).not.toBeNull();
    expect(section[1]).toMatch(/rounded-2xl/);
    expect(section[1]).toMatch(/shadow-sm/);
    // Header card (mounts BEFORE the brand-logo conditional).
    // The card's opening <div className has ``rounded-2xl p-6 mb-4
    // shadow-sm``; grep against the full source works because it's
    // unique on that combo.
    expect(SRC).toMatch(
      /className="rounded-2xl p-6 mb-4 shadow-sm"[\s\S]{0,200}brandLogoUrl \?/,
    );
  });

  it("preserves every pre-P49 data-testid (source-level grep)", () => {
    // Compute the current set of testids in the source and assert
    // (a) every baseline id is still present and (b) every added
    // id is registered in the P49_TESTIDS_ADDED allowlist.
    const found = new Set(
      (SRC.match(/data-testid="[^"]+"/g) || []).map(
        (s) => s.slice("data-testid=\"".length, -1),
      ),
    );
    // Every baseline id present.
    for (const id of P49_TESTIDS_BEFORE) {
      expect(found.has(id)).toBe(true);
    }
    // Every added id registered.
    for (const id of P49_TESTIDS_ADDED) {
      expect(found.has(id)).toBe(true);
    }
    // No unregistered new ids — union == before + added.
    const expected = new Set(
      [...P49_TESTIDS_BEFORE, ...P49_TESTIDS_ADDED],
    );
    for (const id of found) {
      expect(expected.has(id)).toBe(true);
    }
  });

  it("section icons paint w-5 h-5 with text-slate-700 and no responsive shrinkage", () => {
    // The Section body renders ``<Icon className="w-5 h-5
    // text-slate-700 shrink-0" />`` — fixed size on every
    // breakpoint per user's hard rule (no ``sm:w-4`` shrink).
    expect(SRC).toMatch(
      /<Icon className="w-5 h-5 text-slate-700 shrink-0"\s*\/>/,
    );
    // Regression guard — no ``sm:w-`` on the icon tag.
    expect(SRC).not.toMatch(
      /<Icon className="[^"]*sm:w-\d/,
    );
  });
});
