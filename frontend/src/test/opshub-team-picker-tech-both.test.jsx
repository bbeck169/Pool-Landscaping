/**
 * Feb-2026 · /team picker "Tech (Both)" — vitest.
 *
 * Covers the additions to ``frontend/src/pages/ops/OpsHub.jsx``:
 *
 *   1. ``ROLE_OPTIONS`` now exposes a 5th combo — ``tech_both`` —
 *      labelled "Tech (Both)" for a cross-trained technician
 *      (``role=technician, department=both``).
 *   2. ``_roleKey()`` maps ``{role:"technician", department:"both"}``
 *      to ``"tech_both"``, and the row-level badge renders the new
 *      teal palette instead of falling through to "Unassigned".
 *   3. The row ``<select>`` fires
 *      ``PATCH /users/{id}`` with ``{role:"technician", department:"both"}``
 *      when the admin picks "Tech (Both)".
 *   4. Relabel: the ``admin+both`` option now reads
 *      "All (Admin + Pool + Landscape)" — matching the backend
 *      canonical label — instead of the stale terse "All".
 *   5. The new "Tech (Both)" filter chip narrows the roster to
 *      cross-trained techs only.
 *
 * Ships alongside ``backend/tests/test_team_picker_tech_both.py``
 * and the ``_VALID_DEPTS_BY_ROLE`` loosening in ``routers/team.py``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ─── shared mocks (mirror ``team-admin-actions.test.jsx``) ───────────
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@/components/ui/confirm-dialog", () => ({
  mustConfirm: vi.fn(async () => true),
}));

const { apiGetMock, apiPostMock, apiPatchMock, apiDelMock, apiPutMock } =
  vi.hoisted(() => ({
    apiGetMock: vi.fn(),
    apiPostMock: vi.fn(),
    apiPatchMock: vi.fn(),
    apiDelMock: vi.fn(),
    apiPutMock: vi.fn(),
  }));

vi.mock("@/api", () => ({
  api: {
    get: apiGetMock, post: apiPostMock,
    patch: apiPatchMock, del: apiDelMock, put: apiPutMock,
  },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));

const { useAuthMock } = vi.hoisted(() => ({ useAuthMock: vi.fn() }));
vi.mock("@/auth", () => ({
  useAuth: () => useAuthMock(),
  AuthProvider: ({ children }) => <>{children}</>,
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ can: () => true, isAdmin: true }),
}));

vi.mock("@/pages/ops/WorkstreamJobDrawer", () => ({
  __esModule: true, default: () => null,
}));

vi.mock("@/hooks/useAttendance", () => ({
  useAttendance: () => ({ punched_in: false, shifts: [], loading: false }),
}));


// Render helper — same pattern as ``team-admin-actions.test.jsx``.
async function renderTeamRoster() {
  const { default: OpsHub } = await import("@/pages/ops/OpsHub");
  return render(
    <MemoryRouter initialEntries={["/ops?t=team"]}>
      <OpsHub />
    </MemoryRouter>,
  );
}


// A roster covering every combo the picker must handle. The "cross"
// user is the target of most assertions — they start unassigned and
// get promoted to "Tech (Both)" via the row dropdown.
const ROSTER = [
  { id: "u-pool",  name: "Mike Pool",     email: "mp@a.com",
    role: "technician", department: "pool" },
  { id: "u-land",  name: "Carlos Land",   email: "cl@a.com",
    role: "technician", department: "landscaping" },
  { id: "u-cross", name: "Alex Cross",    email: "ax@a.com",
    role: "technician", department: null },   // will become tech_both
  { id: "u-both",  name: "Riley Both",    email: "rb@a.com",
    role: "technician", department: "both" }, // already tech_both
  { id: "u-admin", name: "Manager",       email: "mg@a.com",
    role: "admin",      department: null },
  { id: "u-all",   name: "Super Ops",     email: "so@a.com",
    role: "admin",      department: "both" },  // admin+both = "all"
];


beforeEach(() => {
  vi.clearAllMocks();
  apiGetMock.mockResolvedValue(ROSTER);
  useAuthMock.mockReturnValue({
    user: {
      id: "u-admin",             // caller is the admin row above
      role: "admin",
      email: "mg@a.com",
      name: "Manager",
    },
  });
});


// ══════════════════════════════════════════════════════════════════
// 1 · Picker exposes all 5 options with the correct labels.
// ══════════════════════════════════════════════════════════════════
describe("TeamRoster · role picker options", () => {
  it("renders 5 combos including the new Tech (Both) and the relabelled All", async () => {
    await renderTeamRoster();

    // Any tech-row dropdown works — pick the "u-cross" row that starts
    // unassigned so the current-value option ("") doesn't shadow one
    // of the 5 combos we're asserting on.
    const sel = await screen.findByTestId("team-role-select-u-cross");
    const optionLabels = within(sel)
      .getAllByRole("option")
      .map((o) => o.textContent);

    // First option is the leading "— Choose role —" placeholder.
    expect(optionLabels[0]).toMatch(/Choose role/);

    // All 5 canonical combos present, in the ROLE_OPTIONS order.
    expect(optionLabels).toEqual(
      expect.arrayContaining([
        "Pool Tech",
        "Landscape Tech",
        "Tech (Both)",                          // NEW
        "Admin",
        "All (Admin + Pool + Landscape)",       // relabelled from "All"
      ]),
    );
    // Explicit assertion that the terse "All" label is gone.
    expect(optionLabels).not.toContain("All");
  });
});


// ══════════════════════════════════════════════════════════════════
// 2 · Selecting Tech (Both) fires the correct PATCH payload.
// ══════════════════════════════════════════════════════════════════
describe("TeamRoster · Tech (Both) selection", () => {
  it("PATCHes /users/{id} with role=technician, department=both", async () => {
    apiPatchMock.mockResolvedValueOnce({ ok: true });
    await renderTeamRoster();

    const sel = await screen.findByTestId("team-role-select-u-cross");
    fireEvent.change(sel, { target: { value: "tech_both" } });

    await waitFor(() =>
      expect(apiPatchMock).toHaveBeenCalledWith(
        "/users/u-cross",
        { role: "technician", department: "both" },
      ),
    );
  });

  it("row that already stores tech+both renders the Tech (Both) badge, not Unassigned", async () => {
    await renderTeamRoster();
    const badge = await screen.findByTestId("team-role-badge-u-both");
    // Badge text is the RoleOption label.
    expect(badge.textContent).toMatch(/Tech \(Both\)/i);
    // And explicitly NOT "Unassigned" (the legacy fallthrough bug).
    expect(badge.textContent).not.toMatch(/Unassigned/i);
  });

  it("row that stores admin+both still renders the relabelled All (Admin + Pool + Landscape)", async () => {
    await renderTeamRoster();
    const badge = await screen.findByTestId("team-role-badge-u-all");
    expect(badge.textContent).toMatch(/All \(Admin \+ Pool \+ Landscape\)/i);
  });
});


// ══════════════════════════════════════════════════════════════════
// 3 · New "Tech (Both)" filter chip narrows to cross-trained techs.
// ══════════════════════════════════════════════════════════════════
describe("TeamRoster · Tech (Both) filter chip", () => {
  it("clicking the chip leaves only rows where roleKey === tech_both", async () => {
    await renderTeamRoster();

    // Baseline — all 6 seeded rows are visible.
    await waitFor(() =>
      expect(screen.getByTestId("team-row-u-cross")).toBeTruthy(),
    );
    expect(screen.getByTestId("team-row-u-pool")).toBeTruthy();
    expect(screen.getByTestId("team-row-u-both")).toBeTruthy();
    expect(screen.getByTestId("team-row-u-admin")).toBeTruthy();
    expect(screen.getByTestId("team-row-u-all")).toBeTruthy();

    // Click the new chip.
    const chip = screen.getByTestId("team-filter-tech_both");
    expect(chip.textContent).toMatch(/Tech \(Both\)/);
    fireEvent.click(chip);

    // After the chip fires, only "u-both" (the seeded tech+both row)
    // remains. "u-cross" was seeded with department=null and does NOT
    // match tech_both.
    await waitFor(() =>
      expect(screen.getByTestId("team-row-u-both")).toBeTruthy(),
    );
    expect(screen.queryByTestId("team-row-u-cross")).toBeNull();
    expect(screen.queryByTestId("team-row-u-pool")).toBeNull();
    expect(screen.queryByTestId("team-row-u-land")).toBeNull();
    expect(screen.queryByTestId("team-row-u-admin")).toBeNull();
    expect(screen.queryByTestId("team-row-u-all")).toBeNull();
  });
});
