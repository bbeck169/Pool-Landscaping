/**
 * Phase Feb-2026 — Customer Warranties admin section smoke.
 *
 *   1. Empty state when API returns no items.
 *   2. Admin sees "Add Warranty" button + can POST via modal.
 *   3. Cards render plan / coverage window / linked_summary.
 *   4. Customer role sees no "Add" button (portal read-only path
 *      uses a different component anyway).
 *   5. Selecting linked_type='install' fetches link-options and
 *      populates the dependent dropdown.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, postSpy, patchSpy, delSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
  delSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    delete: (...a) => delSpy(...a),
    del: (...a) => delSpy(...a),
  },
}));

import CustomerWarrantiesLibrary from "@/components/customers/CustomerWarrantiesLibrary";

const ADMIN_USER = { id: "u-1", email: "a@t.com", role: "admin" };
const CUSTOMER_USER = { id: "u-2", email: "c@t.com", role: "customer" };

function mockApis({ items = [], plans = null, install = [], equipment = [] }) {
  const defaultPlans = plans ?? [
    { id: "plan-1", name: "Basic Pool Warranty", duration_months: 12 },
    { id: "plan-2", name: "Extended", duration_months: 24 },
  ];
  getSpy.mockImplementation((path) => {
    if (path.startsWith("/customers/") && path.includes("/warranties/link-options")) {
      const isInstall = path.includes("type=install");
      return Promise.resolve({
        type: isInstall ? "install" : "equipment",
        options: isInstall ? install : equipment,
      });
    }
    if (path.startsWith("/customers/") && path.includes("/warranties")) {
      return Promise.resolve({
        items, page: 1, page_size: 50,
        total: items.length, total_pages: 1,
      });
    }
    if (path === "/warranties/plans") {
      return Promise.resolve({ items: defaultPlans, total: defaultPlans.length });
    }
    return Promise.resolve({});
  });
}

describe("CustomerWarrantiesLibrary — admin", () => {
  beforeEach(() => {
    getSpy.mockReset(); postSpy.mockReset();
    patchSpy.mockReset(); delSpy.mockReset();
    window.confirm = vi.fn(() => true);
  });

  it("renders the empty state when no warranties", async () => {
    mockApis({ items: [] });
    render(<CustomerWarrantiesLibrary customerId="c-1" currentUser={ADMIN_USER} />);
    await waitFor(() =>
      expect(screen.getByTestId("warranty-empty")).toBeInTheDocument()
    );
    expect(screen.getByTestId("warranty-add-btn")).toBeInTheDocument();
  });

  it("customer role does NOT see the Add button", async () => {
    mockApis({ items: [] });
    render(<CustomerWarrantiesLibrary customerId="c-1" currentUser={CUSTOMER_USER} />);
    await waitFor(() =>
      expect(screen.getByTestId("customer-warranties-section")).toBeInTheDocument()
    );
    expect(screen.queryByTestId("warranty-add-btn")).toBeNull();
  });

  it("renders card fields including linked_summary", async () => {
    mockApis({
      items: [{
        id: "w-1", plan_name_snapshot: "Extended Pool Warranty",
        start_date: "2026-02-01", end_date: "2028-02-01",
        status: "active", notes: "Attached to install.",
        linked_type: "install", linked_id: "j-1",
        linked_summary: {
          type: "install", label: "Pool Install · 2026-01-10",
          details: {},
        },
      }],
    });
    render(<CustomerWarrantiesLibrary customerId="c-1" currentUser={ADMIN_USER} />);
    await waitFor(() =>
      expect(screen.getByTestId("warranty-card-0")).toBeInTheDocument()
    );
    expect(screen.getByTestId("warranty-card-name-0").textContent)
      .toBe("Extended Pool Warranty");
    expect(screen.getByTestId("warranty-card-window-0").textContent)
      .toContain("2026-02-01");
    expect(screen.getByTestId("warranty-card-link-0").textContent)
      .toContain("Pool Install");
  });

  it("Add flow: selects install linked_type → fetches link-options → POSTs", async () => {
    mockApis({
      items: [],
      install: [{ id: "job-1", title: "Pool Install", service_date: "2026-01-10",
                  service_type: "Pool Install" }],
    });
    postSpy.mockResolvedValue({ id: "w-new" });
    render(<CustomerWarrantiesLibrary customerId="c-1" currentUser={ADMIN_USER} />);
    await waitFor(() =>
      expect(screen.getByTestId("warranty-add-btn")).toBeInTheDocument()
    );
    fireEvent.click(screen.getByTestId("warranty-add-btn"));
    expect(screen.getByTestId("warranty-form-modal")).toBeInTheDocument();

    // Fill in plan + start_date.
    fireEvent.change(screen.getByTestId("warranty-contract-name-input"), {
      target: { value: "plan-1" },
    });
    fireEvent.change(screen.getByTestId("warranty-coverage-start-input"), {
      target: { value: "2026-02-01" },
    });

    // Switch linked_type → install → should hit link-options.
    fireEvent.change(screen.getByTestId("warranty-linked-type-select"), {
      target: { value: "install" },
    });
    await waitFor(() =>
      expect(getSpy.mock.calls.some(
        (call) => String(call[0]).includes("link-options?type=install"),
      )).toBe(true)
    );

    // Choose install option.
    await waitFor(() => {
      const sel = screen.getByTestId("warranty-linked-id-select");
      expect(sel).not.toBeDisabled();
      fireEvent.change(sel, { target: { value: "job-1" } });
    });

    fireEvent.click(screen.getByTestId("warranty-form-submit"));

    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    const [path, body] = postSpy.mock.calls[0];
    expect(path).toBe("/warranties/contracts");
    expect(body).toMatchObject({
      plan_id: "plan-1", customer_id: "c-1",
      start_date: "2026-02-01",
      linked_type: "install", linked_id: "job-1",
    });
  });

  it("linked_type='none' disables linked_id dropdown and sends null", async () => {
    mockApis({ items: [] });
    postSpy.mockResolvedValue({ id: "w-new" });
    render(<CustomerWarrantiesLibrary customerId="c-1" currentUser={ADMIN_USER} />);
    await waitFor(() => screen.getByTestId("warranty-add-btn"));
    fireEvent.click(screen.getByTestId("warranty-add-btn"));

    fireEvent.change(screen.getByTestId("warranty-contract-name-input"), {
      target: { value: "plan-1" },
    });
    fireEvent.change(screen.getByTestId("warranty-coverage-start-input"), {
      target: { value: "2026-02-01" },
    });
    // linked_type defaults to "none" → the dropdown is disabled.
    expect(screen.getByTestId("warranty-linked-id-select")).toBeDisabled();

    fireEvent.click(screen.getByTestId("warranty-form-submit"));
    await waitFor(() => expect(postSpy).toHaveBeenCalledTimes(1));
    expect(postSpy.mock.calls[0][1]).toMatchObject({
      linked_type: "none",
      linked_id: null,
    });
  });
});
