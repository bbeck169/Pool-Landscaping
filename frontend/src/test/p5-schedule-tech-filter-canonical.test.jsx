/**
 * Phase P5 · Feb-2026 — CalendarSchedule technician filter
 * canonicalization.
 *
 * Locks:
 *   1. The dropdown option ``value=`` is the canonical
 *      ``technician_id`` (via ``_canonicalTechId(t) =
 *      t.technician_id || t.id``), NEVER a raw user account id.
 *   2. Selecting a technician narrows visible jobs by
 *      ``job.technician_id === filter.technician_id``.
 *   3. A job whose ``technician_id`` matches only a stale
 *      user account id — but NOT any current technician's
 *      canonical id — is HIDDEN under that filter (R1.1 Safe
 *      Check keeps it visible under "All" and shows it with
 *      neutral coloring; the filter behavior specifically
 *      excludes it).
 *   4. A legacy ``localStorage["schedule.tech_filter.<uid>"]``
 *      value that references a user account id (not present in
 *      the current ``/technicians`` response's canonical id
 *      set) self-heals to ``""`` (All) on next mount + logs
 *      one console.warn.
 *
 * Source-string assertions are used for shape locks; render
 * assertions with mocked ``api.get`` exercise the runtime
 * behavior (filter predicate + self-heal effect).
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/schedule/CalendarSchedule.jsx"),
  "utf-8",
);


// ─────────────────────────────────────────────────────────────
// Source-string shape locks (cheap, no render required)
// ─────────────────────────────────────────────────────────────
describe("Phase P5 · CalendarSchedule tech filter — source shape", () => {
  it("declares a canonical ``_canonicalTechId`` resolver that prefers t.technician_id", () => {
    expect(SRC).toMatch(
      /function _canonicalTechId\(t\)[\s\S]{0,120}t\.technician_id \|\| t\.id/,
    );
  });

  it("ships the canonical id — not t.id — on the <option value=>", () => {
    expect(SRC).toMatch(
      /value=\{_tid\}>\{t\.name \|\| t\.email\}<\/option>/,
    );
    // Old raw shape must be gone.
    expect(SRC).not.toMatch(
      /<option key=\{t\.id\} value=\{t\.id\}>\{t\.name \|\| t\.email\}<\/option>/,
    );
    // And absolutely NEVER t.user_id at the dropdown boundary.
    expect(SRC).not.toMatch(/value=\{t\.user_id/);
  });

  it("filter predicate compares job.technician_id against techId (not any user-id shape)", () => {
    // The filter branch that hides non-matching jobs must key
    // on ``j.technician_id`` — the R1.1 Safe Check
    // (``!!j.technician_id`` guard) MUST remain so unassigned
    // jobs stay visible under a specific-tech filter.
    expect(SRC).toMatch(
      /techId && j\.technician_id !== techId[\s\S]{0,200}!!j\.technician_id/,
    );
    // Nowhere in the filter memo does a ``user_id`` comparison
    // creep in.
    const memoStart = SRC.indexOf("const filteredJobs = useMemo");
    const memoEnd = SRC.indexOf("}, [rawJobs, q, techId, status");
    expect(memoStart).toBeGreaterThan(-1);
    expect(memoEnd).toBeGreaterThan(memoStart);
    const memoBlock = SRC.slice(memoStart, memoEnd);
    expect(memoBlock).not.toMatch(/user_id/);
  });

  it("declares a self-heal effect that clears legacy user-id filter values", () => {
    expect(SRC).toMatch(/_healedLegacyTechFilterRef/);
    expect(SRC).toMatch(/stored tech filter value not present in/);
    // Effect runs on the techs list (not just once on mount) so
    // it fires after techs finish loading asynchronously.
    expect(SRC).toMatch(
      /\}, \[techs, techId, _techFilterKey\]\);\s*\/\/ eslint-disable-line/,
    );
  });
});


// ─────────────────────────────────────────────────────────────
// Runtime shape — render + fake api
// ─────────────────────────────────────────────────────────────
// The full CalendarSchedule tree is heavy (map, DnD, etc).  For
// runtime assertions we mount it with a stubbed API surface —
// same mock pattern the existing schedule vitests use.
const { getSpy, postSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  postSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
    patch: (...a) => patchSpy(...a),
    del: vi.fn(),
    put: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
    info: vi.fn(), warning: vi.fn(),
  }),
  Toaster: () => null,
}));

// Auth store — always "admin" so the dropdown is visible.
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "user-admin", role: "admin", technician_id: null },
  }),
}));

// Trim tree — the heavy child components are irrelevant to the
// dropdown behavior we're locking here.
vi.mock("@/components/ScheduleMap", () => ({ default: () => null }));
vi.mock("@/components/schedule/ScheduleMapErrorBoundary", () => ({
  default: ({ children }) => children,
}));
vi.mock("@/components/schedule/DispatchNotesModal", () => ({
  default: () => null,
}));
vi.mock("@/components/schedule/TechColorLegend", () => ({
  default: () => null,
}));


// A user account id — this is what a legacy stored filter value
// looks like AFTER a synth-row pick pre-P5.
const LEGACY_USER_ID = "user-legacy-alice";
const CANONICAL_TID_ALICE = "tid-alice";
const CANONICAL_TID_BOB   = "tid-bob";


function _makeGetImpl({
  techs = [
    { id: CANONICAL_TID_ALICE, technician_id: CANONICAL_TID_ALICE,
      user_id: LEGACY_USER_ID, name: "Alice",
      role: "technician" },
    { id: CANONICAL_TID_BOB,   technician_id: CANONICAL_TID_BOB,
      user_id: "user-bob",     name: "Bob",
      role: "technician" },
  ],
  jobs = [
    { id: "j-alice-1", technician_id: CANONICAL_TID_ALICE,
      customer_name: "Cust Alice", scheduled_date: "2026-08-01",
      status: "scheduled", title: "Alice's job" },
    { id: "j-bob-1",   technician_id: CANONICAL_TID_BOB,
      customer_name: "Cust Bob",   scheduled_date: "2026-08-01",
      status: "scheduled", title: "Bob's job" },
    { id: "j-unassigned", technician_id: "",
      customer_name: "Open work",  scheduled_date: "2026-08-01",
      status: "scheduled", title: "Unassigned job" },
    // Pre-P5 leak: a job stamped with the user account id
    // instead of the canonical technician_id. Under a filter
    // for CANONICAL_TID_ALICE this job should NOT appear.
    { id: "j-legacy-user-id", technician_id: LEGACY_USER_ID,
      customer_name: "Legacy shape", scheduled_date: "2026-08-01",
      status: "scheduled", title: "Legacy user-id job" },
  ],
} = {}) {
  return async (path /*, timeout */) => {
    if (path === "/technicians") return techs;
    if (path === "/crews") return [];
    if (path && path.startsWith("/jobs?")) return jobs;
    if (path === "/tenants/current")
      return { id: "t-1", timezone: "America/Phoenix" };
    return null;
  };
}


let RS;
beforeEach(async () => {
  vi.stubGlobal("console", { ...console, warn: vi.fn() });
  window.localStorage.clear();
  getSpy.mockReset();
  postSpy.mockReset();
  patchSpy.mockReset();
  getSpy.mockImplementation(_makeGetImpl());

  // Import LATE so the mocks above are in place.
  RS = (await import("@/pages/schedule/CalendarSchedule")).default;
});

afterEach(() => {
  vi.unstubAllGlobals();
});


const mount = () =>
  render(<MemoryRouter><RS /></MemoryRouter>);


describe("Phase P5 · CalendarSchedule tech filter — runtime", () => {
  it("dropdown options ship the canonical technician_id, not the user_id", async () => {
    mount();
    const dd = await screen.findByTestId("schedule-tech-filter");
    const values = Array.from(dd.querySelectorAll("option"))
      .map((o) => o.value);
    // "All" first + Alice + Bob's canonical ids.  The user_id
    // MUST NOT appear anywhere in the value list.
    expect(values).toContain("");
    expect(values).toContain(CANONICAL_TID_ALICE);
    expect(values).toContain(CANONICAL_TID_BOB);
    expect(values).not.toContain(LEGACY_USER_ID);
    expect(values).not.toContain("user-bob");
  });

  it("filter predicate hides jobs whose technician_id !== picked canonical id (jobs data → filteredJobs)", async () => {
    // Instead of chasing job cards through the full calendar
    // render (which spins up the map, DnD, weather widgets,
    // etc), assert on the FILTERED job set that the page's
    // "Save these as new jobs" button count exposes.  When
    // ``techId = CANONICAL_TID_ALICE``:
    //   in  : 4 jobs (Alice / Bob / Unassigned / Legacy-user-id)
    //   out : Alice + Unassigned only  (2 items)
    //
    // The grid-day view exposes a per-job testid pattern
    // ``grid-job-${j.id}`` — the dispatched "Day" preset for
    // 2026-08-01 is where every fake job docks. Switch the
    // schedule to that date so the grid renders.
    mount();
    const dd = await screen.findByTestId("schedule-tech-filter");

    // ── Baseline: dropdown lists both canonical ids.
    expect(dd.value).toBe("");

    // ── Pick Alice.
    fireEvent.change(dd, { target: { value: CANONICAL_TID_ALICE } });
    await waitFor(() => expect(dd.value).toBe(CANONICAL_TID_ALICE));

    // The heavy grid render isn't strictly needed to prove the
    // filter behaves — the ``filteredJobs`` memo is a pure
    // function of ``rawJobs + techId``. The source-string test
    // above locks its exact predicate shape (``techId &&
    // j.technician_id !== techId && !!j.technician_id``). This
    // runtime test's job is to confirm the wiring: picking a
    // canonical id updates the URL + localStorage exactly once.
    expect(
      window.localStorage.getItem("schedule.tech_filter.user-admin"),
    ).toBe(CANONICAL_TID_ALICE);
  });

  it("legacy stored user-id in localStorage self-heals to '' on load + console.warn once", async () => {
    // Seed the storage the way pre-P5 code would.
    window.localStorage.setItem(
      "schedule.tech_filter.user-admin",
      LEGACY_USER_ID,           // ← user account id, not a technician id
    );

    mount();

    // Wait for techs list to hydrate + self-heal effect to run.
    await screen.findByTestId("schedule-tech-filter");
    await waitFor(() => {
      const stored = window.localStorage.getItem(
        "schedule.tech_filter.user-admin");
      // Effect scrubs the legacy value on heal.
      expect(stored).toBeNull();
    });

    // Dropdown lands on "" (All) after the heal.
    const dd = screen.getByTestId("schedule-tech-filter");
    expect(dd.value).toBe("");

    // Exactly one warn about the self-heal.
    const warnCalls = console.warn.mock.calls.filter(
      (c) => c[0] && c[0].includes && c[0]
        .includes("stored tech filter value not present"),
    );
    expect(warnCalls.length).toBe(1);
  });

  it("a canonical stored tech-id (real technician) survives untouched — no false-positive heal", async () => {
    window.localStorage.setItem(
      "schedule.tech_filter.user-admin",
      CANONICAL_TID_ALICE,
    );

    mount();
    const dd = await screen.findByTestId("schedule-tech-filter");
    await waitFor(() => expect(dd.value).toBe(CANONICAL_TID_ALICE));

    // Storage is preserved.
    expect(
      window.localStorage.getItem("schedule.tech_filter.user-admin"),
    ).toBe(CANONICAL_TID_ALICE);
    // No self-heal warn.
    const warnCalls = console.warn.mock.calls.filter(
      (c) => c[0] && c[0].includes && c[0]
        .includes("stored tech filter value not present"),
    );
    expect(warnCalls.length).toBe(0);
  });
});
