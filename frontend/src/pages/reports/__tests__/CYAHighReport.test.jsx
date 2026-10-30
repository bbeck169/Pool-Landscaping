/**
 * Feb-2026 · CYA Over-Threshold Report FE — operator v2 fix.
 *
 * Pins the 6 vitest cases locked in the operator dispatch for
 * Commit B (per-reading row shape + threshold clamp).
 */
import fs from "node:fs";
import path from "node:path";

import React from "react";
import {
  describe, it, expect, vi, beforeEach,
} from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, fireEvent, waitFor, within,
} from "@testing-library/react";

const { getSpy } = vi.hoisted(() => ({ getSpy: vi.fn() }));
vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    post: vi.fn(),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));

vi.mock("@/hooks/use-toast", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/layout/PageHeader", () => ({
  default: ({ title, subtitle }) => (
    <header>
      <h1>{title}</h1>
      {subtitle ? <div>{subtitle}</div> : null}
    </header>
  ),
}));

import CYAHighReport from "../CYAHighReport";


function _mkRow(over = {}) {
  return {
    customer_id: "cust-1",
    customer_name: "Customer 1",
    job_id: "job-1",
    job_date: "2026-07-04",
    value: 150,
    ...over,
  };
}


function _mkResponse(threshold = 100, items = [_mkRow()]) {
  return { threshold, count: items.length, items };
}


describe("CYAHighReport (operator v2 — per-reading rows)", () => {
  beforeEach(() => {
    getSpy.mockReset();
  });

  // 1. Table renders with the three operator-spec columns.
  it("1. renders a 3-column table (customer, job date, value)", async () => {
    getSpy.mockResolvedValueOnce(_mkResponse(100, [_mkRow()]));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-high-table")).toBeTruthy();
    });
    const table = screen.getByTestId("cya-high-table");
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.length).toBe(3);
    expect(headers[0].textContent).toMatch(/Customer/i);
    expect(headers[1].textContent).toMatch(/Job date/i);
    expect(headers[2].textContent).toMatch(/CYA reading/i);
  });

  // 2. Multiple readings for the same customer render as distinct rows.
  it("2. multiple readings same customer → multiple rows", async () => {
    getSpy.mockResolvedValueOnce(_mkResponse(100, [
      _mkRow({ job_id: "job-A", value: 115, job_date: "2026-08-10" }),
      _mkRow({ job_id: "job-B", value: 125, job_date: "2026-08-11" }),
      _mkRow({ job_id: "job-C", value: 135, job_date: "2026-08-12" }),
    ]));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-high-table")).toBeTruthy();
    });
    const rows = screen.getAllByTestId(/^cya-row-/);
    expect(rows.length).toBe(3);
    // Each row carries one of the three distinct values.
    const vals = rows.map((r) => r.textContent).join(" | ");
    expect(vals).toContain("115");
    expect(vals).toContain("125");
    expect(vals).toContain("135");
  });

  // 3. Customer name link routes to /customers/{id}.
  it("3. customer-name cell links to /customers/{id}", async () => {
    getSpy.mockResolvedValueOnce(_mkResponse(100, [_mkRow()]));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getAllByTestId(/^cya-row-/)[0]).toBeTruthy();
    });
    const row = screen.getAllByTestId(/^cya-row-/)[0];
    const anchor = within(row).getByRole("link");
    expect(anchor.getAttribute("href")).toBe("/customers/cust-1");
  });

  // 4. CSV button triggers a Blob download.
  it("4. CSV button triggers a download via Blob + anchor click", async () => {
    const createObjSpy = vi.fn(() => "blob:fake");
    const revokeSpy = vi.fn();
    const origCreate = URL.createObjectURL;
    const origRevoke = URL.revokeObjectURL;
    URL.createObjectURL = createObjSpy;
    URL.revokeObjectURL = revokeSpy;

    getSpy.mockResolvedValueOnce(_mkResponse(100, [_mkRow()]));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-export-csv-btn")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("cya-export-csv-btn"));
    expect(createObjSpy).toHaveBeenCalledTimes(1);
    expect(revokeSpy).toHaveBeenCalledTimes(1);

    URL.createObjectURL = origCreate;
    URL.revokeObjectURL = origRevoke;
  });

  // 5. Threshold change refetches; clearing input clamps to 1.
  it("5. threshold refetches; clear-input clamps to 1 not 0", async () => {
    getSpy
      .mockResolvedValueOnce(_mkResponse(100, [_mkRow()]))
      .mockResolvedValueOnce(_mkResponse(50, [_mkRow()]))
      .mockResolvedValueOnce(_mkResponse(1, [_mkRow()]));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(1));
    expect(getSpy.mock.calls[0][0]).toContain("threshold=100");

    // Set to 50 → explicit refetch.
    fireEvent.change(screen.getByTestId("cya-threshold-input"), {
      target: { value: "50" },
    });
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(2));
    expect(getSpy.mock.calls[1][0]).toContain("threshold=50");

    // Clear the input → ``Number("") || 1`` clamps to 1,
    // the request MUST carry threshold=1 and NEVER threshold=0.
    fireEvent.change(screen.getByTestId("cya-threshold-input"), {
      target: { value: "" },
    });
    await waitFor(() => expect(getSpy).toHaveBeenCalledTimes(3));
    expect(getSpy.mock.calls[2][0]).toContain("threshold=1");
    expect(getSpy.mock.calls[2][0]).not.toContain("threshold=0");
  });

  // 6. Empty response renders empty state.
  it("6. empty response renders empty state", async () => {
    getSpy.mockResolvedValueOnce(_mkResponse(100, []));
    render(
      <MemoryRouter>
        <CYAHighReport />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("cya-high-empty")).toBeTruthy();
    });
    expect(screen.queryByTestId("cya-high-table")).toBeNull();
  });

  // Smoke: ReportsHub tile stays registered (shipped lock preserved
  // from Commit `b33965479`).
  it("smoke: ReportsHub tile registration preserved", () => {
    const hubPath = path.resolve(
      __dirname, "..", "ReportsHub.jsx",
    );
    const src = fs.readFileSync(hubPath, "utf8");
    expect(src).toContain('key: "cya-high"');
    expect(src).toContain("/reports/cya-high");
  });
});
