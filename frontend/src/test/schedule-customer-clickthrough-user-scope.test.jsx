/**
 * SCHEDULE-CUSTOMER-CLICKTHROUGH · hotfix · Feb-2026 — the follow-up
 * commit to ``758208e4a`` (``feat(schedule): clickable customer name
 * on cards for admin + super_admin``) introduced a bare ``user?.role``
 * reference inside ``<GridPanel>`` even though ``GridPanel`` is a
 * plain function component that does NOT call ``useAuth`` — the parent
 * (``CalendarSchedule``) owns the auth read.  Running ``/schedule``
 * at the preview URL threw:
 *
 *   ReferenceError: user is not defined
 *       at GridPanel (CalendarSchedule.jsx:2961)
 *
 * …which crashed every role (admin / tech / manager / etc.) because
 * the throw happened unconditionally while React tried to render the
 * grid card body.
 *
 * This test locks the correct shape (source-guard pattern — mirrors
 * ``schedule-grid-panel-tenant-tz.test.jsx``):
 *
 *   1. ``GridPanel`` destructures a ``canClickCustomerName`` prop
 *      with a safe ``false`` default (so isolated harnesses that mount
 *      GridPanel without the parent don't accidentally light up the
 *      admin-only clickthrough).
 *   2. The body of ``GridPanel`` has NO bare ``user?.role`` /
 *      ``user?.id`` / ``user?.name`` references — any lookup against
 *      the auth user must go through the parent.
 *   3. The parent ``<GridPanel />`` invocation threads
 *      ``canClickCustomerName={canClickCustomerName}``.
 *   4. The parent defines ``canClickCustomerName`` from
 *      ``user?.role`` with the admin + super_admin gate (matches the
 *      backend admin dependency surface — managers, owners, techs and
 *      customers stay on the pre-existing directions shortcut).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = readFileSync(
  resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);

/* GridPanel body = everything from its ``export function`` opener
 * through the end of file (it is the last top-level function
 * exported from the module, same slice convention as the tenantTz
 * regression test next door). */
const GRID_PANEL_START = SRC.indexOf("export function GridPanel(");
const GRID_PANEL_BODY = SRC.slice(GRID_PANEL_START);

/* Parent (CalendarSchedule default export) body = everything BEFORE
 * the GridPanel function.  Enough to anchor the invocation + the
 * precomputed boolean. */
const CAL_SCHED_BODY = SRC.slice(0, GRID_PANEL_START);


describe("SCHEDULE-CUSTOMER-CLICKTHROUGH · GridPanel user-scope hotfix",
  () => {
    it("GridPanel destructures a `canClickCustomerName` prop (safe "
       + "default = false)", () => {
      expect(GRID_PANEL_BODY).toMatch(
        /canClickCustomerName\s*=\s*false\s*,/,
      );
    });

    it("GridPanel body has NO bare `user?.role` references "
       + "(regression lock for the ReferenceError crash)", () => {
      // The destructure line itself is before the body, but even
      // if someone re-adds a bare auth read inside the body this
      // guards against the crash coming back.
      expect(GRID_PANEL_BODY).not.toMatch(/\{\s*user\?\.role\b/);
      expect(GRID_PANEL_BODY).not.toMatch(/\(\s*user\?\.role\b/);
      // Also forbid the exact pattern that was in production.
      expect(GRID_PANEL_BODY).not.toMatch(
        /user\?\.role\s*===\s*["']admin["']\s*\|\|\s*user\?\.role\s*===\s*["']super_admin["']/,
      );
    });

    it("GridPanel body has NO bare `user?.id` / `user?.name` / "
       + "`user?.tenant` references (defence in depth — ANY auth-user "
       + "access from this component is a crash)", () => {
      expect(GRID_PANEL_BODY).not.toMatch(/\buser\?\.(id|name|tenant|technician_id|email)\b/);
    });

    it("the clickable-name branch now reads `canClickCustomerName` "
       + "instead of inlining the role check", () => {
      // Match on the ternary head that opens the CustomerLink vs
      // directions branch.  Allow optional whitespace / newlines
      // between the boolean and the ``&& j.customer_id`` guard.
      expect(GRID_PANEL_BODY).toMatch(
        /\{\s*canClickCustomerName[\s\S]{0,40}&&\s*j\.customer_id\s*\?/,
      );
    });

    it("parent <GridPanel /> invocation threads "
       + "`canClickCustomerName={canClickCustomerName}`", () => {
      expect(CAL_SCHED_BODY).toMatch(
        /<GridPanel[\s\S]{0,4000}canClickCustomerName=\{canClickCustomerName\}[\s\S]{0,2000}\/>/,
      );
    });

    it("parent CalendarSchedule defines `canClickCustomerName` from "
       + "the auth user with the admin + super_admin gate", () => {
      // Flexible match: tolerate whitespace / line-breaks between
      // the array literal, the ``.includes`` call, and the role
      // argument so a cosmetic re-flow doesn't trip the regex.
      expect(CAL_SCHED_BODY).toMatch(
        /const\s+canClickCustomerName\s*=\s*\[\s*["']admin["']\s*,\s*["']super_admin["']\s*\]\s*\.\s*includes\(\s*\(\s*user\?\.role\s*\|\|\s*["']{2}\s*\)\s*\.\s*toLowerCase\(\s*\)\s*,?\s*\)\s*;/,
      );
    });

    it("parent still calls useAuth so `user` is in scope at the "
       + "boolean definition site (sanity — if useAuth is dropped "
       + "the admin gate silently resolves to false)", () => {
      expect(CAL_SCHED_BODY).toMatch(/useAuth\(\)/);
      expect(CAL_SCHED_BODY).toMatch(/const\s*\{\s*user\s*\}\s*=\s*useAuth\(\)/);
    });
  },
);
