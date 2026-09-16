/**
 * Phase U1 · Feb-2026 · Frontend — "+ Add Job" quick-action button in the
 * admin top bar.  Sits DIRECTLY to the LEFT of the existing "+ Add
 * Customer" button and reuses the shipped ``/jobs/new`` (``JobNew.jsx``)
 * route.
 *
 * Covers:
 *  * Renders for admin + super_admin (matches ``AddCustomerButton``).
 *  * Hidden for technician + customer.
 *  * Click routes to ``/jobs/new``.
 *  * DOM order: ``admin-topbar-add-job`` renders BEFORE
 *    ``topbar-add-customer-btn`` (i.e. is a *previous sibling* / earlier
 *    in document order) — the visual "+ Add Job → + Add Customer" flow
 *    the spec calls for.
 *  * Visual parity — the two buttons share an identical class list so a
 *    future rebrand touches only one place.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ─── Mocks — cloned from phase21-add-customer-btn.test.jsx so both
// suites stay in step. ---------------------------------------------
let currentRole = "admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u", role: currentRole, email: "x@y.z" } }),
}));

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
    useLocation: () => ({ pathname: "/" }),
  };
});

vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [{
    key: "ops", label: "Ops", icon: () => null,
    entries: [{ to: "/dashboard", feature: "dashboard", label: "Dashboard" }],
  }],
  filterNavByIndustries: (entries) => entries,
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    can: () => true,
    cannot: () => false,
    effectiveRole: currentRole,
    role: currentRole,
    isAdmin: currentRole === "admin" || currentRole === "super_admin",
    isAdminOrManager: true,
    canDo: () => true,
  }),
}));
vi.mock("@/components/NotificationBell", () => ({ default: () => null }));
vi.mock("@/components/AIDock/CreditsBudgetChip", () => ({ default: () => null }));

// Import AFTER mocks so the module picks them up.
import AdminTopBar from "@/layouts/AdminTopBar";


function renderBar() {
  return render(
    <MemoryRouter initialEntries={["/dashboard"]}>
      <AdminTopBar />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
});


describe("Phase U1 · AdminTopBar · AddJobButton", () => {
  // K76.1 dual-render — jsdom paints both narrow + wide branches so
  // testids resolve to two nodes when role-visible.  Use
  // ``getAllByTestId(...)[0]`` to stay behavior-focused.
  it("renders for admin and routes to /jobs/new on click", () => {
    currentRole = "admin";
    renderBar();
    const btns = screen.getAllByTestId("admin-topbar-add-job");
    expect(btns.length).toBeGreaterThanOrEqual(1);
    const btn = btns[0];
    expect(btn).toBeInTheDocument();
    expect(btn.textContent).toMatch(/add job/i);
    fireEvent.click(btn);
    expect(navigateMock).toHaveBeenCalledWith("/jobs/new");
    expect(navigateMock).toHaveBeenCalledTimes(1);
  });

  it("renders for super_admin", () => {
    currentRole = "super_admin";
    renderBar();
    const btns = screen.getAllByTestId("admin-topbar-add-job");
    expect(btns.length).toBeGreaterThanOrEqual(1);
    expect(btns[0]).toBeInTheDocument();
  });

  it("is hidden for technician", () => {
    currentRole = "technician";
    renderBar();
    expect(screen.queryByTestId("admin-topbar-add-job")).toBeNull();
  });

  it("is hidden for customer", () => {
    currentRole = "customer";
    renderBar();
    expect(screen.queryByTestId("admin-topbar-add-job")).toBeNull();
  });

  it("sits immediately before topbar-add-customer-btn in DOM order", () => {
    currentRole = "admin";
    renderBar();
    // Pair the two testids branch-by-branch so we compare buttons
    // that live inside the SAME wrapper (narrow xor wide).  We
    // check the wide branch (last one in DOM order) as the primary
    // assertion because that's what the spec screenshot shows, and
    // also assert the narrow branch has the same neighbour to
    // guard the mobile mount.
    const jobs = screen.getAllByTestId("admin-topbar-add-job");
    const custs = screen.getAllByTestId("topbar-add-customer-btn");
    expect(jobs.length).toBe(custs.length);
    for (let i = 0; i < jobs.length; i += 1) {
      const j = jobs[i];
      const c = custs[i];
      // Both must be inside the SAME parent flex row.
      expect(j.parentElement).toBe(c.parentElement);
      // Add Job must be a strictly earlier sibling than Add Customer.
      const cmp = j.compareDocumentPosition(c);
      // Node.DOCUMENT_POSITION_FOLLOWING === 4 → c follows j.
      expect(cmp & 4).toBeTruthy();
      // Also assert they are IMMEDIATE siblings (Add Job → Add Customer,
      // nothing between).
      expect(j.nextElementSibling).toBe(c);
    }
  });

  it("shares visual style with Add Customer (identical class list)", () => {
    currentRole = "admin";
    renderBar();
    const j = screen.getAllByTestId("admin-topbar-add-job")[0];
    const c = screen.getAllByTestId("topbar-add-customer-btn")[0];
    // The two buttons must be visually indistinguishable other than
    // the label — the spec forbids a divergent class list.
    expect(j.className).toBe(c.className);
    // ARIA labels differ (label ≠ button semantics), styling doesn't.
    expect(j.getAttribute("aria-label")).toBe("Add job");
    expect(c.getAttribute("aria-label")).toBe("Add customer");
  });

  it("carries the Plus icon just like Add Customer", () => {
    currentRole = "admin";
    renderBar();
    const j = screen.getAllByTestId("admin-topbar-add-job")[0];
    // lucide-react's ``Plus`` renders as ``<svg class="lucide lucide-plus">``.
    const svg = j.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg.getAttribute("class") || "").toMatch(/lucide/i);
  });
});
