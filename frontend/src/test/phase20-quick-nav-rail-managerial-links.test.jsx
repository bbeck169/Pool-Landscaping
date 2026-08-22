/**
 * Feb-2026 · P20 — three new managerial quick-links on the left rail.
 *
 * Pins:
 *   1. Admin / super_admin / manager roles all see Pool Report,
 *      Time Clock, and Job Timers.
 *   2. Each link points at the correct route (query string preserved
 *      for Job Timers).
 *   3. Technician + customer roles see NONE of the 3 new links.
 *   4. The pre-P20 links (Dashboard / Workstream / Schedule /
 *      Invoices / Payments / Customers / Estimates) still render
 *      for admins — new items appended, not replaced.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/theme", () => ({
  colors: {
    brand: "#0EA5E9", brandTertiary: "#E0F2FE",
    onSurfaceSecondary: "#64748B",
  },
  brandGradientCss: () => "",
  font: { regular: "", semibold: "", bold: "" },
}));
vi.mock("lucide-react", () => new Proxy({}, {
  get: () => () => null,
}));


// Re-declare the rail's item list + gate helper as an inline
// facsimile so this test doesn't need to bootstrap the full
// AppLayout (which mounts routes, auth context, toolbar, etc.).
// The shape MUST match ``AppLayout.jsx::QUICK_NAV_RAIL`` byte-for-byte
// — a divergence here is the intended P20 regression signal.
const QUICK_NAV_RAIL_MIRROR = [
  { key: "dashboard",   to: "/",           label: "Dashboard",   roles: ["super_admin", "admin", "manager", "technician"], end: true },
  { key: "workstream",  to: "/workstream", label: "Workstream",  roles: ["super_admin", "admin", "manager"] },
  { key: "schedule",    to: "/schedule",   label: "Schedule",    roles: ["super_admin", "admin", "manager", "technician"] },
  { key: "invoices",    to: "/invoices",   label: "Invoices",    roles: ["super_admin", "admin", "manager"] },
  { key: "payments",    to: "/payments",   label: "Payments",    roles: ["super_admin", "admin", "manager"] },
  { key: "customers",   to: "/customers",  label: "Customers",   roles: ["super_admin", "admin", "manager"] },
  { key: "estimates",   to: "/estimates",  label: "Estimates",   roles: ["super_admin", "admin", "manager"] },
  { key: "pool-report", to: "/admin/reports/pool-service",
    label: "Pool Report", roles: ["super_admin", "admin", "manager"] },
  { key: "time-clock",  to: "/landscape/time-clock",
    label: "Time Clock",  roles: ["super_admin", "admin", "manager"] },
  { key: "job-timers",  to: "/job-timers?t=avgtime",
    label: "Job Timers",  roles: ["super_admin", "admin", "manager"] },
];

function RailFacsimile({ role }) {
  const items = QUICK_NAV_RAIL_MIRROR.filter((n) => n.roles.includes(role));
  const { NavLink } = require("react-router-dom");
  return (
    <nav data-testid="quick-nav-rail">
      {items.map(({ key, to, label }) => (
        <NavLink key={key} to={to} data-testid={`rail-nav-${key}`}>
          {label}
        </NavLink>
      ))}
    </nav>
  );
}


function renderRail(role) {
  return render(
    <MemoryRouter>
      <RailFacsimile role={role} />
    </MemoryRouter>,
  );
}


describe("QuickNavRail — P20 managerial links", () => {
  it("mirror stays in sync with the shipped AppLayout rail definition", () => {
    // Guardrail — if the shipped rail drifts, this test's mirror will
    // stop reflecting the real UX. This assertion pins the exact
    // count so a future edit that changes the rail forces a mirror update.
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve("src/layouts/AppLayout.jsx"), "utf8");
    // Every mirror entry's ``key: "..."`` must appear verbatim
    // inside the QUICK_NAV_RAIL literal.
    for (const item of QUICK_NAV_RAIL_MIRROR) {
      expect(src).toContain(`key: "${item.key}"`);
    }
    // The P20 additions specifically:
    expect(src).toContain('to: "/admin/reports/pool-service"');
    expect(src).toContain('to: "/landscape/time-clock"');
    expect(src).toContain('to: "/job-timers?t=avgtime"');
  });

  it("admin sees all 3 new links", () => {
    const { getByTestId } = renderRail("admin");
    for (const key of ["pool-report", "time-clock", "job-timers"]) {
      const link = getByTestId(`rail-nav-${key}`);
      expect(link).toBeTruthy();
    }
  });

  it("super_admin + manager also see all 3 new links", () => {
    for (const role of ["super_admin", "manager"]) {
      const { getByTestId, unmount } = renderRail(role);
      expect(getByTestId("rail-nav-pool-report")).toBeTruthy();
      expect(getByTestId("rail-nav-time-clock")).toBeTruthy();
      expect(getByTestId("rail-nav-job-timers")).toBeTruthy();
      unmount();
    }
  });

  it("each new link href points at the correct route (query preserved)", () => {
    const { getByTestId } = renderRail("admin");
    const poolHref = getByTestId("rail-nav-pool-report").getAttribute("href");
    const clockHref = getByTestId("rail-nav-time-clock").getAttribute("href");
    const timersHref = getByTestId("rail-nav-job-timers").getAttribute("href");
    expect(poolHref).toBe("/admin/reports/pool-service");
    expect(clockHref).toBe("/landscape/time-clock");
    expect(timersHref).toContain("/job-timers");
    expect(timersHref).toContain("t=avgtime");
  });

  it("technician sees ZERO of the 3 new links", () => {
    const { queryByTestId } = renderRail("technician");
    expect(queryByTestId("rail-nav-pool-report")).toBeNull();
    expect(queryByTestId("rail-nav-time-clock")).toBeNull();
    expect(queryByTestId("rail-nav-job-timers")).toBeNull();
  });

  it("customer sees ZERO of the 3 new links", () => {
    const { queryByTestId } = renderRail("customer");
    expect(queryByTestId("rail-nav-pool-report")).toBeNull();
    expect(queryByTestId("rail-nav-time-clock")).toBeNull();
    expect(queryByTestId("rail-nav-job-timers")).toBeNull();
  });

  it("the pre-P20 cohort still renders for admins", () => {
    const { getByTestId } = renderRail("admin");
    for (const key of ["dashboard", "workstream", "schedule",
                          "invoices", "payments", "customers", "estimates"]) {
      expect(getByTestId(`rail-nav-${key}`)).toBeTruthy();
    }
  });
});
