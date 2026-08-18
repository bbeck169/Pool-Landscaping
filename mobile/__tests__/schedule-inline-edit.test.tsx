/**
 * Feb-2026 · Mobile Schedule inline edit affordance.
 *
 * Source-inspection contract test. Asserts:
 *   1. The mobile Schedule renders a ``grid-edit-{id}`` Pencil next
 *      to ``grid-open-{id}`` guarded by ``isAdminForCard``.
 *   2. The GridView invocation passes ``onOpenEdit`` only when the
 *      caller is an admin role (super_admin | admin | manager).
 *   3. The parent screen owns ``editingJob`` state + mounts the
 *      ``ScheduleJobEditSheet`` wired to in-place mutate helpers.
 *   4. The Edit sheet hits the same PUT / DELETE contract as the
 *      web modal.
 */
import fs from "fs";
import path from "path";

const scheduleSrc = fs.readFileSync(
  path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"),
  "utf8",
);
const sheetSrc = fs.readFileSync(
  path.resolve(__dirname, "../src/components/schedule/ScheduleJobEditSheet.tsx"),
  "utf8",
);

describe("Mobile schedule · Edit button visibility (role gate)", () => {
  it("renders a Pencil button next to grid-open with testID=grid-edit-{id}", () => {
    expect(scheduleSrc).toMatch(/testID=\{`grid-edit-\$\{job\.id\}`\}/);
    expect(scheduleSrc).toMatch(/name="pencil-outline"/);
  });

  it("guards the Pencil on isAdminForCard && onEdit", () => {
    expect(scheduleSrc).toMatch(
      /isAdminForCard\s*&&\s*onEdit\s*\?[\s\S]{0,600}testID=\{`grid-edit-\$\{job\.id\}`\}/,
    );
  });

  it("passes onEdit into JobRow only when the caller is admin+ (manager included)", () => {
    // Admin gate now includes manager for parity with web.
    expect(scheduleSrc).toMatch(
      /isAdmin\s*=\s*role\s*===\s*["']admin["']\s*\|\|\s*role\s*===\s*["']super_admin["']\s*\|\|\s*role\s*===\s*["']manager["']/,
    );
    // The parent site: onEdit={isAdmin ? onOpenEdit : undefined}
    expect(scheduleSrc).toMatch(/onEdit=\{isAdmin\s*\?\s*onOpenEdit\s*:\s*undefined\}/);
    expect(scheduleSrc).toMatch(/isAdminForCard=\{isAdmin\}/);
  });
});

describe("Mobile schedule · in-place mutate on save / delete", () => {
  it("mounts <ScheduleJobEditSheet> wired to patchJobInPlace + removeJobInPlace", () => {
    expect(scheduleSrc).toMatch(
      /import ScheduleJobEditSheet from ["']@\/src\/components\/schedule\/ScheduleJobEditSheet["']/,
    );
    expect(scheduleSrc).toMatch(/<ScheduleJobEditSheet[\s\S]{0,600}open=\{!!editingJob\}/);
    expect(scheduleSrc).toMatch(
      /onSaved=\{[\s\S]{0,300}patchJobInPlace\(patched\)[\s\S]{0,150}setEditingJob\(null\)/,
    );
    expect(scheduleSrc).toMatch(
      /onDeleted=\{[\s\S]{0,300}removeJobInPlace\(jid\)[\s\S]{0,150}setEditingJob\(null\)/,
    );
  });
});

describe("ScheduleJobEditSheet · PUT + DELETE contract", () => {
  it("PUTs only changed fields to /jobs/{id}", () => {
    expect(sheetSrc).toMatch(/\.put\(`\/jobs\/\$\{job\.id\}`,\s*patch\)/);
    expect(sheetSrc).toMatch(/if \(\(form\[k\] \|\| ""\) !== \(job\[k\] \|\| ""\)\) patch\[k\] = form\[k\]/);
  });

  it("DELETEs via api.del (matches the shared client method)", () => {
    expect(sheetSrc).toMatch(/\.del\(`\/jobs\/\$\{job\.id\}`\)/);
  });

  it("exposes stable testids for header + save + delete affordances", () => {
    expect(sheetSrc).toMatch(/testID=["']schedule-job-edit-sheet["']/);
    expect(sheetSrc).toMatch(/testID=["']schedule-job-edit-save["']/);
    expect(sheetSrc).toMatch(/testID=["']schedule-job-edit-delete["']/);
    expect(sheetSrc).toMatch(/testID=["']schedule-job-edit-confirm-delete-btn["']/);
  });
});
