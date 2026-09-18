/**
 * Feb-2026 · Sprint 1 · Section C — CalendarSchedule GridPanel
 * tenant-tz-aware focused day + "Today" pill.
 *
 * Bug context: prior to Section C, GridPanel derived its focused
 * day + isToday flag from ``format(date, "yyyy-MM-dd")`` and
 * ``new Date()`` — both browser-local. A Phoenix tenant viewed at
 * 8 PM local from a US-Eastern browser (UTC-5) would see the
 * header advance to tomorrow while the parent CalendarSchedule
 * (already tenant-tz-aware since Section C in this sprint) still
 * showed today's jobs — a jarring split.
 *
 * Guardrails locked here:
 *   1. The GridPanel destructuring accepts a ``tenantTz`` prop
 *      (defaulted to TENANT_TZ_FALLBACK for isolated harness use).
 *   2. GridPanel uses ``getTenantISODate(date, tenantTz)`` for
 *      the focused ISO — no bare ``format(date, "yyyy-MM-dd")``.
 *   3. GridPanel uses ``getTenantTodayISO(tenantTz)`` for the
 *      "Today" pill comparison — no bare ``new Date()``.
 *   4. The parent CalendarSchedule invocation passes
 *      ``tenantTz={tenantTz}`` down.
 *   5. Both source-guard checks match verbatim so a copy-paste
 *      regression to the pre-C form fails immediately.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = readFileSync(
  resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);


describe("CalendarSchedule · Section C · GridPanel tenantTz threading",
  () => {
    it("GridPanel destructures a `tenantTz` prop with a fallback", () => {
      // Accept either ``tenantTz = TENANT_TZ_FALLBACK`` OR
      // ``tenantTz = "America/Phoenix"`` — both are canonical.
      expect(SRC).toMatch(
        /tenantTz\s*=\s*(TENANT_TZ_FALLBACK|["']America\/Phoenix["'])/,
      );
    });

    it("GridPanel uses getTenantISODate(date, tenantTz) for focusISO", () => {
      // Focused-day derivation must go through the shared helper.
      expect(SRC).toMatch(
        /const\s+focusISO\s*=\s*getTenantISODate\(\s*date\s*,\s*tenantTz\s*\)/,
      );
    });

    it("GridPanel uses getTenantTodayISO(tenantTz) for the Today pill", () => {
      expect(SRC).toMatch(
        /const\s+isToday\s*=\s*focusISO\s*===\s*getTenantTodayISO\(\s*tenantTz\s*\)/,
      );
    });

    it("no bare `format(new Date(), \"yyyy-MM-dd\")` remains inside GridPanel",
      () => {
        // Find the GridPanel function body and assert the browser-local
        // shortcut is gone. Everything from ``export function GridPanel(``
        // up to the next ``function `` / end-of-file is the body.
        const start = SRC.indexOf("export function GridPanel(");
        expect(start).toBeGreaterThan(-1);
        // GridPanel is the last top-level function in the file — take the
        // remainder as its body.
        const body = SRC.slice(start);
        expect(body).not.toMatch(/format\(\s*new\s+Date\(\)\s*,\s*["']yyyy-MM-dd["']\)/);
        // Also assert we didn't leave the OLD ``focusISO`` form behind.
        expect(body).not.toMatch(/const\s+focusISO\s*=\s*format\(\s*date\s*,\s*["']yyyy-MM-dd["']\)/);
      });

    it("parent <GridPanel /> receives the tenantTz prop", () => {
      // Search inside the parent's JSX invocation.  The invocation
      // spans multiple lines — check that ``tenantTz={tenantTz}``
      // sits inside the opening tag block.
      expect(SRC).toMatch(/<GridPanel[\s\S]{0,4000}tenantTz=\{tenantTz\}[\s\S]{0,80}\/>/);
    });

    it("imports the tenant-tz helpers from @/lib/tenantTz", () => {
      expect(SRC).toMatch(/from\s+["']@\/lib\/tenantTz["']/);
      expect(SRC).toMatch(/getTenantTodayISO[\s\S]{0,200}getTenantISODate[\s\S]{0,200}TENANT_TZ_FALLBACK/);
    });
  });
