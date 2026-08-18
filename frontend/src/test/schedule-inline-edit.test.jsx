/**
 * Feb-2026 · Schedule-screen inline edit affordance + modal.
 *
 * Source-inspection contract test — matches the sibling
 * ``schedule-job-notes`` / ``jobdetail-new-scheduled-job`` shape.
 * Asserts the CalendarSchedule renders the Edit Pencil next to
 * ``grid-open-{id}`` only when ``isAdminRole`` is true, the modal
 * mount is wired for in-place mutate, and the shared modal
 * component uses the right primitives + PUT / DELETE endpoints.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const scheduleSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);
const modalSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/ScheduleJobEditModal.jsx"),
  "utf8",
);

describe("Schedule · Edit button visibility (role gate)", () => {
  it("renders a ``grid-edit-{id}`` button that is admin-gated", () => {
    // Testid contract.
    expect(scheduleSrc).toMatch(/data-testid=\{`grid-edit-\$\{j\.id\}`\}/);
    // Guarded by ``isAdminForCard`` — the prop the row receives from
    // the parent, which is only truthy when ``isAdminRole`` evaluates
    // to super_admin / admin / manager.
    expect(scheduleSrc).toMatch(
      /onOpenEdit\s*&&\s*isAdminForCard\s*\?[\s\S]{0,600}data-testid=\{`grid-edit-\$\{j\.id\}`\}/,
    );
  });

  it("passes ``onOpenEdit`` only when the caller is an admin role", () => {
    // Parent site: onOpenEdit={isAdminRole ? ... : undefined}
    expect(scheduleSrc).toMatch(
      /onOpenEdit=\{isAdminRole\s*\?\s*\(\(jobRow\)\s*=>\s*setEditingJob\(jobRow\)\)\s*:\s*undefined\}/,
    );
    // isAdminForCard mirrors the same value so the child renders zero
    // spurious buttons when it isn't set.
    expect(scheduleSrc).toMatch(/isAdminForCard=\{isAdminRole\}/);
  });

  it("isAdminRole includes super_admin, admin, manager", () => {
    expect(scheduleSrc).toMatch(
      /isAdminRole\s*=\s*\(user\?\.role\s*===\s*["']admin["']\s*\|\|\s*user\?\.role\s*===\s*["']super_admin["']\s*\|\|\s*user\?\.role\s*===\s*["']manager["']\)/,
    );
  });
});

describe("Schedule · in-place mutate on save / delete", () => {
  it("mounts <ScheduleJobEditModal> wired to patchJobInPlace + removeJobInPlace", () => {
    expect(scheduleSrc).toMatch(/import ScheduleJobEditModal from ["']@\/pages\/schedule\/ScheduleJobEditModal["']/);
    expect(scheduleSrc).toMatch(/<ScheduleJobEditModal[\s\S]{0,700}open=\{!!editingJob\}/);
    // onSaved must mutate ``rawJobs`` in place, close modal, toast.
    expect(scheduleSrc).toMatch(
      /onSaved=\{[\s\S]{0,600}patchJobInPlace\(updated\)[\s\S]{0,300}setEditingJob\(null\)[\s\S]{0,300}Job saved for /,
    );
    // onDeleted must drop the row and close.
    expect(scheduleSrc).toMatch(
      /onDeleted=\{[\s\S]{0,300}removeJobInPlace\(jid\)[\s\S]{0,150}setEditingJob\(null\)/,
    );
  });
});

describe("ScheduleJobEditModal · PUT /jobs/{id} + DELETE contract", () => {
  it("PUTs only the changed fields to /jobs/{job.id}", () => {
    expect(modalSrc).toMatch(/api\.put\(`\/jobs\/\$\{job\.id\}`,\s*patch\)/);
    // Change detection compares against the incoming ``job`` prop.
    expect(modalSrc).toMatch(/for \(const k of \[/);
    expect(modalSrc).toMatch(/if \(\(form\[k\] \|\| ""\) !== \(job\[k\] \|\| ""\)\) patch\[k\] = form\[k\]/);
  });

  it("DELETEs via api.del (matches the shared client method name)", () => {
    // The api client exposes ``del`` not ``delete`` (see /app/frontend/src/api.js).
    expect(modalSrc).toMatch(/api\.del\(`\/jobs\/\$\{job\.id\}`\)/);
    expect(modalSrc).not.toMatch(/api\.delete\(/);
  });

  it("exposes stable testids for the header + save + delete affordances", () => {
    expect(modalSrc).toMatch(/testid=["']schedule-job-edit-modal["']|testid="schedule-job-edit-modal"/);
    expect(modalSrc).toMatch(/testid=["']schedule-job-edit-save["']/);
    expect(modalSrc).toMatch(/testid=["']schedule-job-edit-delete["']/);
    expect(modalSrc).toMatch(/testid=["']schedule-job-edit-confirm-delete-btn["']/);
  });
});
