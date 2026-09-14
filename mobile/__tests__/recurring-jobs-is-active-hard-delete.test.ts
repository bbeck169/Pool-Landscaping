/**
 * Recurring Jobs · is_active + hard-delete mobile parity.
 *
 * Source-inspection tests verifying:
 *   1. Active toggle + start-date validation + testIDs
 *   2. Hard-delete confirmation modal with correct testIDs + API call
 *   3. Soft-delete button with correct testID
 *   4. Inactive badge renders per row
 */

import fs from "fs";
import path from "path";

function readSrc(): string {
  return fs.readFileSync(
    path.resolve(__dirname, "../app/finance/recurring-jobs.tsx"),
    "utf8",
  );
}

describe("Recurring Jobs · is_active toggle + validation", () => {
  const src = readSrc();

  it("renders the Active toggle with correct testID", () => {
    expect(src).toContain('testID="recurring-job-active-toggle"');
  });

  it("renders the start-date input with correct testID", () => {
    expect(src).toContain('testID="recurring-job-start-date-input"');
  });

  it("Active toggle is disabled when start_date is empty", () => {
    // The Switch must be disabled={!(editing.start_date || "").trim()}
    expect(src).toMatch(
      /disabled=\{!\(editing\.start_date\s*\|\|\s*""\)\.trim\(\)\}/,
    );
  });

  it("openCreate defaults is_active to false", () => {
    const create = src.match(
      /const\s+openCreate\s*=[\s\S]*?setEditing\(\{([\s\S]*?)\}\)/,
    );
    expect(create).not.toBeNull();
    expect(create![1]).toMatch(/is_active:\s*false/);
  });

  it("save() blocks submission when is_active is true but start_date is empty", () => {
    // Client-side gate: editing.is_active && !start_date => early return
    expect(src).toMatch(
      /if\s*\(editing\.is_active\s*&&\s*!\(editing\.start_date\s*\|\|\s*""\)\.trim\(\)\)/,
    );
    // Must set an error and return before the API call
    expect(src).toMatch(
      /setSaveErr\([^)]*start date[^)]*\);\s*return;/i,
    );
  });

  it("surfaces backend 422 start_date_required_for_active error", () => {
    expect(src).toContain("start_date_required_for_active");
  });
});

describe("Recurring Jobs · Inactive badge", () => {
  const src = readSrc();

  it("renders Inactive badge with correct per-row testID", () => {
    expect(src).toMatch(
      /testID=\{`recurring-job-inactive-badge-\$\{r\.id\}`\}/,
    );
  });

  it("only shows badge when is_active === false", () => {
    expect(src).toMatch(
      /r\.is_active\s*===\s*false\s*\?[\s\S]{0,300}recurring-job-inactive-badge/,
    );
  });
});

describe("Recurring Jobs · soft-delete + hard-delete buttons", () => {
  const src = readSrc();

  it("renders soft-delete button with correct per-row testID", () => {
    expect(src).toMatch(
      /testID=\{`recurring-job-soft-delete-btn-\$\{r\.id\}`\}/,
    );
  });

  it("soft-delete calls DELETE /recurring-jobs/{id} (no ?hard)", () => {
    expect(src).toMatch(
      /api\.del\(`\/recurring-jobs\/\$\{row\.id\}`\)/,
    );
  });

  it("renders hard-delete button with correct per-row testID", () => {
    expect(src).toMatch(
      /testID=\{`recurring-job-hard-delete-btn-\$\{r\.id\}`\}/,
    );
  });

  it("hard-delete button opens the confirmation modal (does NOT call API directly)", () => {
    // The row button sets state; it does NOT fire api.del directly
    expect(src).toMatch(
      /testID=\{`recurring-job-hard-delete-btn-\$\{r\.id\}`\}/,
    );
    // onPress sets hardDeleteTarget, not api.del
    expect(src).toMatch(
      /onPress=\{\(\)\s*=>\s*setHardDeleteTarget\(r\)\}[\s\S]{0,300}recurring-job-hard-delete-btn/,
    );
  });
});

describe("Recurring Jobs · hard-delete confirmation modal", () => {
  const src = readSrc();

  it("renders the modal with correct testID", () => {
    expect(src).toContain('testID="recurring-job-hard-delete-confirm-modal"');
  });

  it("modal title matches spec", () => {
    expect(src).toContain("Permanently delete this recurring job?");
  });

  it("modal body matches spec verbatim", () => {
    expect(src).toMatch(
      /This removes the recurring template AND cancels any future[\s\n]*scheduled jobs derived from[\s\n]*it\. Completed jobs[\s\n]*will not be affected\. This cannot be undone\./,
    );
  });

  it("cancel button has correct testID and dismisses modal", () => {
    expect(src).toContain('testID="recurring-job-hard-delete-cancel-btn"');
    // The cancel button must render text "Cancel" nearby
    expect(src).toMatch(
      /testID="recurring-job-hard-delete-cancel-btn"[\s\S]{0,100}Cancel/,
    );
  });

  it("confirm button has correct testID and fires DELETE ?hard=true", () => {
    expect(src).toContain('testID="recurring-job-hard-delete-confirm-btn"');
    // The hardDelete function calls api.del with ?hard=true
    expect(src).toMatch(
      /api\.del\(`\/recurring-jobs\/\$\{row\.id\}\?hard=true`\)/,
    );
  });

  it("confirm toast includes future_jobs_cancelled count", () => {
    expect(src).toMatch(/future_jobs_cancelled/);
    expect(src).toMatch(/future jobs cancelled/);
  });
});

describe("Recurring Jobs · RecurringJob type includes is_active", () => {
  const src = readSrc();

  it("type definition includes is_active field", () => {
    expect(src).toMatch(/is_active\??\s*:\s*boolean/);
  });
});
