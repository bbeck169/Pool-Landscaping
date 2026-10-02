/**
 * Jobs Overhaul · Phase 3b · JobCostingPanel inline editability.
 *
 * Mounts the real ``<JobCostingPanel>`` with the ``@/api`` + ``@/auth``
 * module boundaries mocked so each test gets fine-grained control
 * over the GET + PUT roundtrip. Keeps the Phase 47.3 testid
 * contract intact (progress rows + estimated/actual profit tiles)
 * and asserts the new Phase 3b inline-edit behaviour contract:
 *
 *   1. Admin sees click-to-edit Budgeted + Actual cells on each
 *      row with ``money`` formatting on the display side.
 *   2. Enter commits with the full merged ``costing_overrides``
 *      dict in the PUT payload.
 *   3. Escape reverts the draft without firing a PUT.
 *   4. Non-admin (customer / technician / viewer) sees display-
 *      only — the inline-edit button is disabled, no inputs.
 *   5. A failed PUT reverts the optimistic mutation + surfaces
 *      a ``job-costing-save-error`` row.
 *   6. Editing a cell on row A preserves any pre-existing
 *      overrides on rows B and C (dict integrity under the
 *      locked full-merge write contract).
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, fireEvent, waitFor, cleanup, act,
} from "@testing-library/react";
import fs from "fs";
import path from "path";


// ─────────────────────── module mocks ────────────────────────────
const apiMock = { get: vi.fn(), put: vi.fn() };
vi.mock("@/api", () => ({ api: apiMock }));

const authMock = { user: { role: "admin" } };
vi.mock("@/auth", () => ({ useAuth: () => authMock }));

// Theme + lucide — just stubs so the tree mounts.
vi.mock("@/theme", () => ({
  colors: {
    muted: "#999", onSurface: "#000", surface: "#fff",
    surfaceSecondary: "#eee", border: "#ccc", brand: "#1E40AF",
  },
}));


// Pulled dynamically so the mocks above apply.
let JobCostingPanel;
beforeEach(async () => {
  cleanup();
  apiMock.get.mockReset();
  apiMock.put.mockReset();
  authMock.user = { role: "admin" };
  JobCostingPanel = (await import("../JobCostingPanel.jsx")).default;
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });


// Canonical response shape — mirrors
// ``backend/routers/budgets.py::job_costing``.
function makePayload(overrides = {}) {
  const base = {
    job_id: "job-ph3b-1",
    baseline: {
      labor_cents: 10000, materials_cents: 5000,
      equipment_cents: 2000, revenue_cents: 50000,
    },
    actual: {
      labor_cents: 15000, materials_cents: 3000, equipment_cents: 1000,
    },
    progress: { labor_pct: 150.0, materials_pct: 60.0, equipment_pct: 50.0 },
    estimated_net_profit_cents: 33000,
    actual_net_profit_cents: 31000,
    estimated_margin_pct: 66.0,
    actual_margin_pct: 62.0,
    time_entries_count: 2,
    total_labor_minutes: 90,
    costing_overrides: overrides,
  };
  return base;
}


describe("JobCostingPanel · Phase 3b · admin inline-edit", () => {
  it("renders admin inline cells with the Phase 47.3 + Phase 3b testids", async () => {
    apiMock.get.mockResolvedValueOnce(makePayload());
    render(<JobCostingPanel jobId="job-ph3b-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("job-costing-panel")).toBeInTheDocument(),
    );
    // Row testids locked by Phase 47.3.
    for (const k of ["labor", "materials", "equipment"]) {
      expect(screen.getByTestId(`job-costing-row-${k}`)).toBeInTheDocument();
      expect(
        screen.getByTestId(`job-costing-${k}-budgeted-display`),
      ).toBeInTheDocument();
      expect(
        screen.getByTestId(`job-costing-${k}-actual-display`),
      ).toBeInTheDocument();
    }
    expect(screen.getByTestId("job-costing-estimated-profit"))
      .toBeInTheDocument();
    expect(screen.getByTestId("job-costing-actual-profit"))
      .toBeInTheDocument();
  });

  it("click Budgeted → input → Enter → PUT with full merged dict → re-render", async () => {
    apiMock.get
      .mockResolvedValueOnce(makePayload())
      .mockResolvedValueOnce(makePayload({
        labor: { budgeted_cents: 20000 },
      }));
    apiMock.put.mockResolvedValueOnce({ id: "job-ph3b-1" });

    render(<JobCostingPanel jobId="job-ph3b-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("job-costing-panel")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("job-costing-labor-budgeted-display"));
    const input = await screen.findByTestId("job-costing-labor-budgeted-input");
    fireEvent.change(input, { target: { value: "200" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
    const [putUrl, putBody] = apiMock.put.mock.calls[0];
    expect(putUrl).toBe("/jobs/job-ph3b-1");
    // Full merged dict (seed had no overrides ⇒ dict is just the
    // one cell we edited).
    expect(putBody).toEqual({
      costing_overrides: { labor: { budgeted_cents: 20000 } },
    });
    // Second GET refetch hydrates the new merged payload.
    await waitFor(() =>
      expect(apiMock.get).toHaveBeenCalledTimes(2),
    );
  });

  it("Escape reverts without firing a PUT", async () => {
    apiMock.get.mockResolvedValueOnce(makePayload());
    render(<JobCostingPanel jobId="job-ph3b-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("job-costing-panel")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("job-costing-materials-actual-display"));
    const input = await screen.findByTestId(
      "job-costing-materials-actual-input",
    );
    fireEvent.change(input, { target: { value: "999" } });
    fireEvent.keyDown(input, { key: "Escape" });
    // Editor collapses.
    expect(
      screen.queryByTestId("job-costing-materials-actual-input"),
    ).toBeNull();
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it("failed PUT reverts optimistic mutation + surfaces save-error row", async () => {
    apiMock.get.mockResolvedValueOnce(makePayload());
    apiMock.put.mockRejectedValueOnce(new Error("boom"));
    render(<JobCostingPanel jobId="job-ph3b-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("job-costing-panel")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("job-costing-equipment-budgeted-display"));
    const input = await screen.findByTestId(
      "job-costing-equipment-budgeted-input",
    );
    fireEvent.change(input, { target: { value: "500" } });
    fireEvent.keyDown(input, { key: "Enter" });
    // Save-error row appears carrying the server message.
    await waitFor(() =>
      expect(screen.getByTestId("job-costing-save-error")).toHaveTextContent(/boom/),
    );
    // Editor stays open on failure (locked by the ``onCommit → false``
    // keep-open contract — mirrors Phase 3a). Press Escape to
    // close it; then confirm the display shows the ORIGINAL
    // baseline (equipment_cents=2000 ⇒ "$20"), proving the
    // optimistic mutation was reverted.
    fireEvent.keyDown(input, { key: "Escape" });
    const disp = await screen.findByTestId(
      "job-costing-equipment-budgeted-display",
    );
    expect(disp).toHaveTextContent("$20");
  });

  it("preserves pre-existing overrides on OTHER rows on commit", async () => {
    const seeded = {
      materials: { budgeted_cents: 7777 },
      equipment: { actual_cents: 1234 },
    };
    apiMock.get
      .mockResolvedValueOnce(makePayload(seeded))
      .mockResolvedValueOnce(makePayload({
        ...seeded,
        labor: { actual_cents: 42000 },
      }));
    apiMock.put.mockResolvedValueOnce({ id: "job-ph3b-1" });
    render(<JobCostingPanel jobId="job-ph3b-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("job-costing-panel")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("job-costing-labor-actual-display"));
    const input = await screen.findByTestId("job-costing-labor-actual-input");
    fireEvent.change(input, { target: { value: "420" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(apiMock.put).toHaveBeenCalledTimes(1));
    const [, putBody] = apiMock.put.mock.calls[0];
    expect(putBody.costing_overrides).toEqual({
      materials: { budgeted_cents: 7777 },
      equipment: { actual_cents: 1234 },
      labor: { actual_cents: 42000 },
    });
  });
});


describe("JobCostingPanel · Phase 3b · non-admin role gate", () => {
  it("technician sees display-only (edit buttons disabled, no inputs on click)", async () => {
    authMock.user = { role: "technician" };
    apiMock.get.mockResolvedValueOnce(makePayload());
    render(<JobCostingPanel jobId="job-ph3b-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("job-costing-panel")).toBeInTheDocument(),
    );
    const disp = screen.getByTestId("job-costing-labor-budgeted-display");
    expect(disp).toBeDisabled();
    // Click is a no-op — no input appears.
    fireEvent.click(disp);
    expect(
      screen.queryByTestId("job-costing-labor-budgeted-input"),
    ).toBeNull();
    expect(apiMock.put).not.toHaveBeenCalled();
  });

  it("customer sees display-only too", async () => {
    authMock.user = { role: "customer" };
    apiMock.get.mockResolvedValueOnce(makePayload());
    render(<JobCostingPanel jobId="job-ph3b-1" />);
    await waitFor(() =>
      expect(screen.getByTestId("job-costing-panel")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("job-costing-materials-actual-display"),
    ).toBeDisabled();
  });
});


// ─────── Source-inspection contract on JobCostingPanel.jsx ───────
describe("JobCostingPanel · Phase 3b · source contract", () => {
  const SRC = fs.readFileSync(
    path.resolve(__dirname, "../JobCostingPanel.jsx"), "utf8",
  );

  it("imports useAuth + gates on ADMIN_ROLES", () => {
    expect(SRC).toMatch(/import\s*\{\s*useAuth\s*\}\s*from\s*["']@\/auth["']/);
    expect(SRC).toMatch(/ADMIN_ROLES\s*=\s*new\s+Set\(/);
    expect(SRC).toMatch(/"admin"[\s\S]{0,80}"super_admin"[\s\S]{0,80}"owner"[\s\S]{0,80}"manager"/);
  });

  it("PUT target is /jobs/{jobId} with costing_overrides key", () => {
    expect(SRC).toMatch(/api\.put\(`\/jobs\/\$\{jobId\}`,\s*\{\s*costing_overrides/);
  });

  it("builds the full merged dict from current overrides state", () => {
    expect(SRC).toMatch(/buildMergedOverrides/);
    expect(SRC).toMatch(/\.\.\.current/);
    expect(SRC).toMatch(/\.\.\.\(current\[bucket\]\s*\|\|\s*\{\}\)/);
  });

  it("rollback restores snapshot on PUT failure", () => {
    expect(SRC).toMatch(/setData\(snapshot\)/);
    expect(SRC).toMatch(/setOverrides\(snapshotOverrides\)/);
    expect(SRC).toMatch(/setSaveErr/);
  });
});
