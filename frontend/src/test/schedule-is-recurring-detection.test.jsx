/**
 * Feb-2026 · Recurring-star detection — Task C.
 *
 * Locks the ``isRecurring(job)`` helper on ``CalendarSchedule.jsx``
 * (call site: L2830 · ``{isRecurring(j) ? "🔁 " : ""}{service_type}``)
 * so occurrences spawned from a recurring template — which do NOT
 * carry the legacy ``is_recurring`` / ``recurring`` / ``recurrence``
 * flags but DO reference their parent via ``recurring_template_id``
 * — still render the 🔁 marker.  The helper is exported directly
 * so these specs can exercise the truthy contract without mounting
 * the 3.4kLoc calendar page.
 */
import { describe, it, expect } from "vitest";

import { isRecurring } from "@/pages/schedule/CalendarSchedule";


describe("isRecurring — schedule-calendar recurring-job detection", () => {
  it("job with ONLY ``recurring_template_id`` set → renders star marker", () => {
    // The primary Task-C use case — an occurrence spawned from a
    // recurring template carries only the parent-FK, not the
    // legacy per-job recurrence flags.  Pre-fix this returned
    // false; post-fix it returns true so the 🔁 marker renders.
    const job = {
      id: "j-1",
      recurring_template_id: "tpl-8b3c-4d21-9e5a-uuid-shape",
    };
    expect(isRecurring(job)).toBe(true);
  });

  it("job with ONLY ``is_recurring: true`` → renders star (regression)", () => {
    // Legacy per-job flag — must keep firing after the fix so a
    // regression here would silently hide the marker on any
    // single-instance recurring job that pre-dated the template
    // system.
    expect(isRecurring({ id: "j-2", is_recurring: true })).toBe(true);
  });

  it("job with ONLY ``recurring: true`` → renders star (regression)", () => {
    // Second legacy shape — some jobs use ``recurring`` without
    // the ``is_`` prefix.
    expect(isRecurring({ id: "j-3", recurring: true })).toBe(true);
  });

  it("job with ONLY ``recurrence`` object populated → renders star (regression)", () => {
    // Third legacy shape — a populated ``recurrence`` rule object.
    // The ``!== "none"`` clause remains to avoid a false positive
    // on the sentinel string ``"none"`` that some legacy tenants
    // wrote to disable recurrence without dropping the key.
    expect(isRecurring({
      id: "j-4",
      recurrence: { rrule: "FREQ=WEEKLY", interval: 1 },
    })).toBe(true);
  });

  it("job with NONE of the four recurrence fields → no star", () => {
    // Baseline non-recurring job — the 🔁 marker MUST stay off.
    expect(isRecurring({
      id: "j-5",
      title: "One-off cleanup",
      status: "scheduled",
    })).toBe(false);
  });

  it("job with ``recurring_template_id: null`` and no other flags → no star (defensive)", () => {
    // Defensive shape — a Mongo doc where the FK was explicitly
    // written as ``null`` (e.g. by a legacy migration) MUST NOT
    // trigger the marker.  Loose truthy check on the FK handles
    // this without a special guard.
    expect(isRecurring({ id: "j-6", recurring_template_id: null })).toBe(false);
  });

  it("job with ``recurring_template_id: \"\"`` and no other flags → no star (defensive)", () => {
    // Empty-string FK — same defensive rule.  Some form flows
    // clear a text-input to ``""`` before persistence.
    expect(isRecurring({ id: "j-7", recurring_template_id: "" })).toBe(false);
  });

  // ─── Bonus regression guards — cheap to add, catch drift on
  //     the underlying truthy semantics if someone tightens the
  //     check later (e.g. explicit ``=== true``). ──────────────
  it("``recurrence: \"none\"`` sentinel does NOT trigger star", () => {
    // Guards the ``!== "none"`` clause.  A legacy tenant wrote
    // ``recurrence: "none"`` to disable recurrence without
    // dropping the key; the marker MUST stay off.
    expect(isRecurring({ id: "j-8", recurrence: "none" })).toBe(false);
  });

  it("multiple recurrence signals set together → still renders once", () => {
    // Boolean-OR contract — a job with BOTH ``is_recurring`` AND
    // ``recurring_template_id`` returns a single ``true``, not a
    // truthy-coalesced string.  Guards against a future refactor
    // that returns the raw expression instead of ``Boolean(...)``.
    const j = {
      id: "j-9",
      is_recurring: true,
      recurring_template_id: "tpl-abc",
    };
    expect(isRecurring(j)).toBe(true);
    // Explicit strict-equality so a stringified truthy value
    // ("tpl-abc") would fail this line, catching a `Boolean` drop.
    expect(isRecurring(j) === true).toBe(true);
  });
});
