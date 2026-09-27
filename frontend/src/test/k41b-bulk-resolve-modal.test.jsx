/**
 * Phase K41b · Feb-2026 — Bulk Resolve picker Vitest.
 *
 * Source-body contract checks matching the K41 pattern already in
 * use across the repo — validates the modal wires the checkbox
 * column, sticky bar, mismatched-picker disable, destructive
 * double-confirm, batch cap alignment, and idempotent batch id
 * without spinning up the shadcn/recharts/api dependency graph.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const MODAL = read("src/components/dashboard/DashboardDrillDownModal.jsx");


describe("K41b · Bulk selection column — checkbox on every DI row", () => {
  it("imports the shadcn Checkbox once", () => {
    expect(MODAL).toMatch(/import\s*\{\s*Checkbox\s*\}\s*from "@\/components\/ui\/checkbox"/);
  });

  it("renders a header select-all checkbox with indeterminate state", () => {
    expect(MODAL).toMatch(/data-testid="di-select-all"/);
    expect(MODAL).toMatch(/indeterminate/);
    expect(MODAL).toMatch(/toggleSelectAllVisible/);
  });

  it("renders a per-row select checkbox wired to the job id", () => {
    expect(MODAL).toMatch(/data-testid=\{`di-row-\$\{row\.job_id\}-select`\}/);
    expect(MODAL).toMatch(/onCheckedChange=\{\(v\) => onToggleSelect\?\.\(row\.job_id, !!v\)\}/);
  });

  it("scopes 'select all' to visible rows only (no cross-pagination)", () => {
    // Explicit user-facing helper text.
    expect(MODAL).toMatch(/Selects visible rows only\./);
    // Implementation uses the visibleJobIds memo derived from rows.
    expect(MODAL).toMatch(/visibleJobIds = useMemo\(\s*\(\) => rows\.map\(\(r\) => r\.job_id\)/);
  });
});


describe("K41b · Sticky Bulk Resolve action bar", () => {
  it("renders a sticky action bar container when at least one row is selected", () => {
    expect(MODAL).toMatch(/data-testid="bulk-resolve-bar"/);
    // K41b hotfix — the sticky wrapper lives on the outer zone
    // (drilldown-di-sticky-zone), not the bar itself.  Bar is inside
    // the zone.
    expect(MODAL).toMatch(/data-testid="drilldown-di-sticky-zone"/);
    expect(MODAL).toMatch(/position: "sticky"[\s\S]{0,200}top: 0[\s\S]{0,200}zIndex: 20/);
  });

  it("exposes the three K41b action buttons", () => {
    expect(MODAL).toMatch(/data-testid="bulk-resolve-mode-customer"/);
    expect(MODAL).toMatch(/data-testid="bulk-resolve-mode-tech"/);
    expect(MODAL).toMatch(/data-testid="bulk-resolve-mode-delete"/);
  });

  it("prints the live selection count", () => {
    expect(MODAL).toMatch(/data-testid="bulk-resolve-selection-count"/);
    expect(MODAL).toMatch(/\{n\} selected/);
  });

  it("Clear button resets both the selection and the picker state", () => {
    expect(MODAL).toMatch(/data-testid="bulk-resolve-clear"/);
    expect(MODAL).toMatch(/onClearSelection[\s\S]{0,80}reset\(\)/);
  });

  it("disables the action buttons that don't apply to the current class", () => {
    expect(MODAL).toMatch(/function classSupports\(refClass\)/);
    // Customer-orphan class → assign-customer + soft-delete only.
    expect(MODAL).toMatch(/orphaned_customer_refs[\s\S]{0,200}customer: true[\s\S]{0,80}tech: false[\s\S]{0,80}delete: true/);
    // Technician-orphan class → assign-tech only.
    expect(MODAL).toMatch(/orphaned_technician_refs[\s\S]{0,200}customer: false[\s\S]{0,80}tech: true[\s\S]{0,80}delete: false/);
    // Buttons pass a tooltip-worthy `title` explaining the disable.
    expect(MODAL).toMatch(/Not applicable for this issue class/);
    expect(MODAL).toMatch(/Only enabled when every selected row is a job-type orphan/);
  });
});


describe("K41b · Confirm strip — per-action summary", () => {
  it("renders the inline confirm strip with a per-action summary line", () => {
    expect(MODAL).toMatch(/data-testid="bulk-resolve-confirm-strip"/);
    expect(MODAL).toMatch(/data-testid="bulk-resolve-confirm-summary"/);
    // Summary refers to the target picker selection.
    expect(MODAL).toMatch(/Reassign \$\{n\} orphan job\$\{n === 1 \? "" : "s"\} to Customer "\$\{[^"]+/);
    // Destructive summary is specific and calls out irreversibility.
    // Feb-2026 · Data-Integrity hard-delete upgrade — buildSummary
    // text updated from "Soft-delete ... cannot be undone by user"
    // to "Hard-delete ... cannot be undone".  Dead code from the UI
    // path (top-level Hard-delete button bypasses this strip per
    // R4=B) but retained defensively; test tracks the current copy.
    expect(MODAL).toMatch(/Hard-delete \$\{n\} orphan job\$\{n === 1 \? "" : "s"\} — cannot be undone\./);
  });

  it("destructive soft-delete requires a second click (two-step confirm)", () => {
    // The 'confirming' guard flips on first click before firing.
    expect(MODAL).toMatch(/if \(mode === "delete"\)[\s\S]{0,200}if \(!confirming\)[\s\S]{0,200}setConfirming\(true\)/);
    // Second click actually fires the bulk delete.
    expect(MODAL).toMatch(/runBulk\("delete", null\)/);
    // Button label transitions from 'Confirm' -> 'Confirm delete N job(s)'.
    expect(MODAL).toMatch(/confirming \? `Confirm delete \$\{n\}/);
  });

  it("non-destructive assign fires on first confirm click", () => {
    expect(MODAL).toMatch(/if \(mode === "customer" \|\| mode === "tech"\)[\s\S]{0,120}runBulk\("assign", target\?\.id\)/);
  });

  it("Cancel button dismisses the strip without mutating", () => {
    expect(MODAL).toMatch(/data-testid="bulk-resolve-confirm-cancel"/);
  });
});


describe("K41b · POST payload — bulk_batch_id + batch cap", () => {
  it("posts /dashboard/data-integrity/resolve-bulk with client-minted batch id", () => {
    expect(MODAL).toMatch(/api\.post\(\s*"\/dashboard\/data-integrity\/resolve-bulk"/);
    expect(MODAL).toMatch(/bulk_batch_id: bulkBatchId/);
    expect(MODAL).toMatch(/function makeBulkBatchId\(\)/);
    // Prefers crypto.randomUUID when available.
    expect(MODAL).toMatch(/crypto\.randomUUID/);
  });

  it("client-side batch cap aligns with the backend _BULK_CAP", () => {
    expect(MODAL).toMatch(/const BULK_CAP = 100/);
    // Client short-circuits before the API call if selection exceeds cap.
    expect(MODAL).toMatch(/if \(n > BULK_CAP\)/);
  });

  it("sends the exact ref_class + action + target_id triplet per row", () => {
    expect(MODAL).toMatch(/items = selectedRows\.map\(\(jobId\) => \(\{/);
    expect(MODAL).toMatch(/ref_class: refClass/);
    expect(MODAL).toMatch(/action: act/);
    expect(MODAL).toMatch(/target_id: tgtId \|\| null/);
  });
});


describe("K41b · Partial failure UX", () => {
  it("renders a failed-list block with per-row errors", () => {
    expect(MODAL).toMatch(/data-testid="bulk-resolve-failed-list"/);
    expect(MODAL).toMatch(/data-testid=\{`bulk-resolve-failed-\$\{f\.job_id\}`\}/);
  });

  it("removes succeeded rows from the table and keeps failed ones", () => {
    // handleBulkComplete fades then filters ok ids out of rows,
    // never touching the failed ones.
    expect(MODAL).toMatch(/handleBulkComplete = useCallback\(\(okIds, meta\)/);
    expect(MODAL).toMatch(/setRows\(\(prev\) => prev\.filter\(\(r\) => !okIds\.includes\(r\.job_id\)\)\)/);
  });

  it("toast fires with both success and failure counts", () => {
    expect(MODAL).toMatch(/toast\.success\(\s*`Resolved \$\{okIds\.length\}\/\$\{n\}/);
    expect(MODAL).toMatch(/toast\.error\(`All \$\{n\} rows failed/);
  });
});


describe("K41b · Boundary + scope guarantees", () => {
  it("does NOT add a second PortalErrorBoundary (K37 rule)", () => {
    // Count the JSX boundary tags — must still be exactly one wrap.
    // (The `<PortalErrorBoundary>` in the docblock is not a JSX tag.)
    const opens = (MODAL.match(/<PortalErrorBoundary[\s\n]/g) || []).length;
    expect(opens).toBe(1);
  });

  it("does NOT expose bulk actions on the income variants", () => {
    // Sanity: the BulkResolveBar is rendered ONLY inside the
    // data-integrity branch of ModalBody.
    const barMatches = MODAL.match(/<BulkResolveBar/g) || [];
    expect(barMatches.length).toBe(1);
    // And the income variants render neither the checkbox column
    // nor the sticky bar.
    const incomeBody = MODAL.substring(
      MODAL.indexOf('data-testid={`drilldown-body-${variant}`}'),
    );
    expect(incomeBody).not.toMatch(/data-testid="di-select-all"/);
    expect(incomeBody).not.toMatch(/<BulkResolveBar/);
  });
});
