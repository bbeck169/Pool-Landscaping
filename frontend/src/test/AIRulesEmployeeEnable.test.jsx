/**
 * MTH-B · Feb-2026 — Employee Enable/Disable card tests.
 *
 * Locks:
 *   1. Renders one row per injected employee (18-employee registry
 *      passed via the ``employees`` test-hook prop).
 *   2. Toggling a row from enabled → disabled surfaces the
 *      "Disabled" pill + mutes the row background.
 *   3. Save PUTs the draft map with reason.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

const { _apiMock } = vi.hoisted(() => ({
  _apiMock: { put: vi.fn(), post: vi.fn(), get: vi.fn() },
}));
vi.mock("@/api", () => ({ api: _apiMock }));

import EmployeeEnableDisableCard from "@/components/ai-rules/EmployeeEnableDisableCard";

const EMPLOYEES = [
  {
    key: "marco_executive",
    human_name: "MARCO",
    codename: "MARCO",
    role_title: "Chief of Staff",
    org_department: "executive",
    hierarchy_order: 1,
    avatar_url: "http://cdn/marco.jpg",
  },
  {
    key: "nova",
    human_name: "Sarah",
    codename: "NOVA",
    role_title: "CMO",
    org_department: "marketing",
    hierarchy_order: 3,
    avatar_url: "http://cdn/nova.jpg",
  },
  {
    key: "brian",
    human_name: "Ben",
    codename: "BRIAN",
    role_title: "Scheduling Coordinator",
    org_department: "operations",
    hierarchy_order: 16,
    avatar_url: "http://cdn/brian.jpg",
  },
];

describe("MTH-B · EmployeeEnableDisableCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _apiMock.put.mockResolvedValue({ ok: true });
  });

  it("renders one row per employee grouped by department", () => {
    render(
      <EmployeeEnableDisableCard
        value={{ marco_executive: true, nova: true, brian: true }}
        overrideMap={{}}
        employeeKeys={EMPLOYEES.map((e) => e.key)}
        employees={EMPLOYEES}
      />,
    );
    expect(
      screen.getByTestId("ai-rules-employee-row-marco_executive"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("ai-rules-employee-row-nova")).toBeInTheDocument();
    expect(screen.getByTestId("ai-rules-employee-row-brian")).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-employee-dept-executive"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-employee-dept-marketing"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("ai-rules-employee-dept-operations"),
    ).toBeInTheDocument();
  });

  it("toggle flips enabled → disabled and shows Disabled pill", () => {
    render(
      <EmployeeEnableDisableCard
        value={{ marco_executive: true, nova: true, brian: true }}
        overrideMap={{}}
        employeeKeys={EMPLOYEES.map((e) => e.key)}
        employees={EMPLOYEES}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-employee-row-nova-toggle"));
    expect(
      screen.getByTestId("ai-rules-employee-row-nova-disabled-pill"),
    ).toBeInTheDocument();
  });

  it("save PUTs the draft toggles with reason", async () => {
    render(
      <EmployeeEnableDisableCard
        value={{ marco_executive: true, nova: true, brian: true }}
        overrideMap={{}}
        employeeKeys={EMPLOYEES.map((e) => e.key)}
        employees={EMPLOYEES}
      />,
    );
    fireEvent.click(screen.getByTestId("ai-rules-employee-row-nova-toggle"));
    fireEvent.click(screen.getByTestId("ai-rules-employee-enable-save"));
    fireEvent.change(
      screen.getByTestId("ai-rules-employee-enable-save-reason-input"),
      { target: { value: "quiet hours for nova" } },
    );
    fireEvent.click(
      screen.getByTestId("ai-rules-employee-enable-save-reason-confirm"),
    );
    await waitFor(() => {
      expect(_apiMock.put).toHaveBeenCalledWith(
        "/tenant-ai-rules/employee_enable_disable",
        expect.objectContaining({
          value: expect.objectContaining({ nova: false }),
          reason: "quiet hours for nova",
        }),
      );
    });
  });
});
