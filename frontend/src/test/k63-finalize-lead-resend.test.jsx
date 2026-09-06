/**
 * Phase K63.finalize · Feb-2026 — Lead detail "Resend alerts" button.
 *
 * Locks:
 *   1. The button is admin-only (admin, super_admin, owner). Non-
 *      admins never see it.
 *   2. The dialog fetches confirmation before firing.
 *   3. The confirm handler POSTs to
 *      ``/admin/leads/{id}/resend-notifications`` (K63.finalize
 *      endpoint) and surfaces the resulting per-recipient rows.
 *   4. Idempotency-bypass copy is present so the admin understands
 *      recipients WILL receive a duplicate.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/leads/LeadDetail.jsx"),
  "utf-8",
);


describe("K63.finalize · Lead detail Resend alerts", () => {
  it("gates the Resend button on admin/super_admin/owner", () => {
    expect(SRC).toMatch(
      /const isAdmin = \[\s*"admin",\s*"super_admin",\s*"owner"\s*\]\.includes\(user\?\.role\)/,
    );
    // JSX render is gated on ``isAdmin && …``.
    expect(SRC).toMatch(
      /\{isAdmin && \(\s*<button[\s\S]{0,240}data-testid="lead-resend-notifications-btn"/,
    );
  });

  it("opens the confirmation dialog before firing", () => {
    expect(SRC).toMatch(
      /onClick=\{\(\) => \{ setResendResult\(null\); setResendOpen\(true\); \}\}/,
    );
    expect(SRC).toMatch(/data-testid="resend-notifications-dialog"/);
    expect(SRC).toMatch(/data-testid="resend-notifications-cancel"/);
    expect(SRC).toMatch(/data-testid="resend-notifications-confirm"/);
  });

  it("fires POST /admin/leads/{id}/resend-notifications on confirm", () => {
    expect(SRC).toMatch(
      /api\.post\(`\/admin\/leads\/\$\{id\}\/resend-notifications`\)/,
    );
  });

  it("surfaces per-recipient dispatched rows in the result panel", () => {
    expect(SRC).toMatch(/data-testid="resend-notifications-result"/);
    expect(SRC).toMatch(/`resend-notifications-row-\$\{i\}`/);
    // Shows sms/email queued counts prominently.
    expect(SRC).toMatch(/Queued · SMS: \{result\.sms_queued/);
  });

  it("mentions the idempotency bypass in the confirmation copy", () => {
    expect(SRC).toMatch(/bypasses idempotency/i);
  });
});
