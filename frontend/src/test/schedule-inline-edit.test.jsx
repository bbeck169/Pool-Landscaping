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
    // Feb 2026 · Loop compares ``form[k]`` against a normalized
    // ``before`` value derived from the incoming ``job`` prop so the
    // ``work_class`` field can normalize a missing value → "service"
    // without emitting a spurious patch on every save. Assert the
    // comparison shape without over-constraining the exact variable
    // names.
    expect(modalSrc).toMatch(/if\s*\(\s*after\s*!==\s*before\s*\)\s*patch\[k\]\s*=\s*form\[k\]/);
  });

  it("includes work_class in the tracked-fields loop (Feb 2026)", () => {
    // The loop's key list must carry ``work_class`` so a Repair
    // ↔ Service retag is emitted on save. Regression guard against
    // dropping the key while renaming siblings.
    expect(modalSrc).toMatch(/for \(const k of \[[\s\S]{0,300}"work_class"[\s\S]{0,50}\]\)/);
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

  it("exposes a work_class segmented picker with per-value testids (Feb 2026)", () => {
    // Group container.
    expect(modalSrc).toMatch(/data-testid=["']schedule-job-edit-work-class["']/);
    // Two radio buttons keyed on the literal values.
    expect(modalSrc).toMatch(/data-testid=\{`schedule-job-edit-work-class-\$\{opt\.value\}`\}/);
    // Both literal values referenced in the options array.
    expect(modalSrc).toMatch(/\{\s*value:\s*["']service["']\s*,\s*label:\s*["']Service["']\s*\}/);
    expect(modalSrc).toMatch(/\{\s*value:\s*["']repair["']\s*,\s*label:\s*["']Repair["']\s*\}/);
    // Initial state seeds work_class from the incoming job doc,
    // normalizing missing/legacy → "service".
    expect(modalSrc).toMatch(/\(job\?\.work_class === ["']repair["']\)\s*\?\s*["']repair["']\s*:\s*["']service["']/);
  });

  it("renders the address picker only when the customer has ≥2 properties (Feb 2026)", () => {
    // Fetches customer's properties on open (guarded on customer_id).
    expect(modalSrc).toMatch(/\/customers\/\$\{job\.customer_id\}\/properties/);
    // Picker rendered behind ``properties.length >= 2`` guard so
    // single-property customers see no clutter.
    expect(modalSrc).toMatch(/properties\.length\s*>=\s*2\s*\?/);
    // Picker testids present.
    expect(modalSrc).toMatch(/data-testid=["']schedule-job-edit-property["']/);
    expect(modalSrc).toMatch(/data-testid=\{`schedule-job-edit-property-\$\{p\.id\}`\}/);
    // property_id is in the change-detection loop so save emits it
    // to the backend when changed.
    expect(modalSrc).toMatch(/for \(const k of \[[\s\S]{0,300}"property_id"[\s\S]{0,50}\]\)/);
  });

  it("renders the crew overlay picker with role-hidden fallback (Feb 2026 · Crew Phase A)", () => {
    // Hydrate: GET /crews on modal open. Silent failure → empty rows,
    // which the render guard collapses to null (tech-role safe).
    expect(modalSrc).toMatch(/api\.get\(["']\/crews["']\)/);
    // Render guard hides the picker when the endpoint returned [].
    expect(modalSrc).toMatch(/crews\.length\s*>\s*0\s*\?/);
    // Testids present — group + per-crew option.
    expect(modalSrc).toMatch(/data-testid=["']schedule-job-edit-crew["']/);
    expect(modalSrc).toMatch(/data-testid=\{`schedule-job-edit-crew-item-\$\{c\.id\}`\}/);
    // crew_id is in the change-detection loop so save PATCHes it.
    expect(modalSrc).toMatch(/for \(const k of \[[\s\S]{0,300}"crew_id"[\s\S]{0,50}\]\)/);
    // Initial state seeds crew_id from the incoming job doc.
    expect(modalSrc).toMatch(/crew_id:\s*job\?\.crew_id \|\| ""/);
  });
});

describe("CalendarSchedule · Calendar-view double-click → edit modal (Feb 2026)", () => {
  it("wires onDoubleClickEvent to open the edit modal only for admin roles", () => {
    // Handler is defined + admin-gated.
    expect(scheduleSrc).toMatch(
      /onDoubleClickEvent\s*=\s*React\.useCallback\(\(ev\)\s*=>\s*\{[\s\S]{0,200}if\s*\(!isAdminRole\)\s*return;[\s\S]{0,200}setEditingJob\(rawJob\)/,
    );
    // Handler wired into the DnDCalendar prop.
    expect(scheduleSrc).toMatch(/onDoubleClickEvent=\{onDoubleClickEvent\}/);
  });
});
