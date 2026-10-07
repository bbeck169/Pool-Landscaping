/**
 * CUSTOMER-RETENTION-ACCOUNT-CORRECTION · Feb-2026 — FE source lock.
 *
 * Locks the UI contract on three surfaces:
 *   1. CustomerRetentionReport.jsx — Gained + Lost tiles clickable,
 *      two new MRR tiles present (gained + lost), drill-down modal
 *      scaffolding (component + state), click handler wires to
 *      ``setDrilldownKind``.
 *   2. CustomersList.jsx — grey "Account Correction" pill rendered
 *      only when ``c.account_correction`` is truthy, right after
 *      the Inactive pill in the same tag row.
 *   3. CustomerDetail.jsx — role-gated "Mark/Un-flag Correction"
 *      button on the action strip + confirm modal with optional
 *      note textarea + POST wiring.
 *
 * Pure source inspection (jsdom-free) — matches the harness used by
 * ``crew-schedule-fanout-badge.test.jsx`` + ``schedule-card-directions``.
 * The backend behavioral contract is locked in
 * ``test_customer_retention_account_correction.py``.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const RETENTION = readFileSync(
  resolve(__dirname, "../pages/reports/CustomerRetentionReport.jsx"), "utf8",
);
const LIST = readFileSync(
  resolve(__dirname, "../pages/customers/CustomersList.jsx"), "utf8",
);
const DETAIL = readFileSync(
  resolve(__dirname, "../pages/customers/CustomerDetail.jsx"), "utf8",
);

const stripComments = (s) => s
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/\/\/[^\n]*/g, "");

const R = stripComments(RETENTION);
const L = stripComments(LIST);
const D = stripComments(DETAIL);


describe("CUSTOMER-RETENTION-ACCOUNT-CORRECTION · retention report", () => {
  it("imports DollarSign + ChevronUp/Down from lucide-react", () => {
    expect(RETENTION).toMatch(
      /import\s*\{[^}]*\bDollarSign\b[^}]*\}\s*from\s*["']lucide-react["']/,
    );
    expect(RETENTION).toMatch(/\bChevronUp\b/);
    expect(RETENTION).toMatch(/\bChevronDown\b/);
  });

  it("defines a 'drilldownKind' state slot wired to setDrilldownKind", () => {
    expect(R).toMatch(/const \[drilldownKind, setDrilldownKind\] = useState\(null\)/);
  });

  it("makes Gained tile clickable → setDrilldownKind('gained')", () => {
    expect(R).toMatch(/testId=["']retention-kpi-gained["'][\s\S]{0,250}clickable[\s\S]{0,250}setDrilldownKind\(["']gained["']\)/);
  });

  it("makes Lost tile clickable → setDrilldownKind('lost')", () => {
    expect(R).toMatch(/testId=["']retention-kpi-lost["'][\s\S]{0,250}clickable[\s\S]{0,250}setDrilldownKind\(["']lost["']\)/);
  });

  it("renders the 2 new MRR tiles with stable test-ids", () => {
    expect(R).toMatch(/testId=["']retention-kpi-mrr-gained["']/);
    expect(R).toMatch(/testId=["']retention-kpi-mrr-lost["']/);
  });

  it("MRR tiles consume totals.recurring_revenue_gained / _lost", () => {
    expect(R).toMatch(/totals\.recurring_revenue_gained/);
    expect(R).toMatch(/totals\.recurring_revenue_lost/);
  });

  it("mounts <AccountCorrectionDrilldownModal> when drilldownKind is set", () => {
    expect(R).toMatch(/{drilldownKind \?[\s\S]{0,500}<AccountCorrectionDrilldownModal[\s\S]{0,500}kind=\{drilldownKind\}/);
  });

  it("drill-down modal fetches the correct endpoint shape", () => {
    expect(R).toMatch(/\/reports\/customer-retention\/\$\{kind\}-list\?/);
  });

  it("drill-down modal consumes the {items,total,has_more,page,limit} envelope", () => {
    expect(R).toMatch(/setTotal\(r\.total/);
    expect(R).toMatch(/setHasMore\(!!r\.has_more/);
    expect(R).toMatch(/setPage\(r\.page/);
  });

  it("drill-down table renders row-level toggle button with role-gated endpoint call", () => {
    expect(R).toMatch(/retention-drilldown-row-\$\{row\.customer_id\}-toggle-btn/);
    expect(R).toMatch(/api\.post\(`\/customers\/\$\{row\.customer_id\}\/account-correction`/);
  });

  it("drill-down modal exposes pagination controls when total > limit", () => {
    expect(R).toMatch(/retention-drilldown-page-prev/);
    expect(R).toMatch(/retention-drilldown-page-next/);
    expect(R).toMatch(/retention-drilldown-page-info/);
  });

  it("sortable headers: name, date, mrr", () => {
    expect(R).toMatch(/retention-drilldown-sort-name/);
    expect(R).toMatch(/retention-drilldown-sort-date/);
    expect(R).toMatch(/retention-drilldown-sort-mrr/);
  });
});


describe("CUSTOMER-RETENTION-ACCOUNT-CORRECTION · customers list grey pill", () => {
  it("renders a grey 'Account Correction' pill when c.account_correction is truthy", () => {
    // Use index-based slicing to avoid false negatives from comment
    // chatter between the gate and the testid.
    const gate = L.indexOf("{c.account_correction ?");
    const pill = L.indexOf("row-${c.id}-account-correction-pill");
    expect(gate).toBeGreaterThan(0);
    expect(pill).toBeGreaterThan(gate);
    expect(pill - gate).toBeLessThan(600);
    expect(L).toMatch(/Account Correction/);
  });

  it("pill carries the muted tooltip 'Excluded from retention reports'", () => {
    expect(L).toMatch(/title="Excluded from retention reports"/);
  });

  it("pill palette matches the muted grey target (bg #F3F4F6, text #6B7280)", () => {
    // Isolate the pill render block (opening span → closing span) and
    // assert both hex colors live inside that slice. Avoids false
    // negatives from unrelated greys elsewhere in the file.
    const pillStart = L.indexOf("row-${c.id}-account-correction-pill");
    expect(pillStart).toBeGreaterThan(0);
    const pillSlice = L.slice(Math.max(0, pillStart - 400), pillStart + 300);
    expect(pillSlice).toMatch(/#F3F4F6/);
    expect(pillSlice).toMatch(/#6B7280/);
  });
});


describe("CUSTOMER-RETENTION-ACCOUNT-CORRECTION · customer detail toggle", () => {
  it("declares a canToggleAccountCorrection role gate", () => {
    expect(D).toMatch(/canToggleAccountCorrection\s*=\s*canIssueCredit/);
  });

  it("renders the 'Mark Correction' / 'Un-flag Correction' button with the correct testid", () => {
    expect(D).toMatch(/testid=["']cd-account-correction-btn["']/);
    expect(D).toMatch(/customer\.account_correction[\s\S]{0,400}Un-flag Correction[\s\S]{0,400}Mark Correction/);
  });

  it("button is wrapped in {canToggleAccountCorrection ? … : null}", () => {
    expect(D).toMatch(/{canToggleAccountCorrection \?[\s\S]{0,600}cd-account-correction-btn/);
  });

  it("renders the confirmation modal with optional note textarea", () => {
    expect(D).toMatch(/testid=["']account-correction-modal["']/);
    expect(D).toMatch(/data-testid=["']account-correction-note-input["']/);
    expect(D).toMatch(/data-testid=["']account-correction-form["']/);
  });

  it("modal confirm button POSTs to /customers/{id}/account-correction", () => {
    expect(D).toMatch(/api\.post\(\s*`\/customers\/\$\{id\}\/account-correction`/);
  });

  it("modal explicit cancel + confirm testids wired", () => {
    expect(D).toMatch(/testid=["']account-correction-cancel-btn["']/);
    expect(D).toMatch(/testid=["']account-correction-confirm-btn["']/);
  });
});
