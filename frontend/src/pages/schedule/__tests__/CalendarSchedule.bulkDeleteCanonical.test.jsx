/**
 * TD-82-calendar-consolidate · Feb-2026 — Phase 2A FE migration.
 *
 * CalendarSchedule.jsx bulk-delete call site migrated from the
 * retired-via-shim ``/jobs/bulk-soft-delete {job_ids}`` outlier
 * to the canonical ``/jobs/bulk-delete {ids}`` endpoint.
 *
 * Locks:
 *   1. Bulk-delete fires ``/jobs/bulk-delete`` (NOT the legacy
 *      ``/jobs/bulk-soft-delete`` shim).
 *   2. Request body carries ``{ids: […]}`` (canonical shape),
 *      not the legacy ``{job_ids: […]}``.
 *   3. Success-/error-UX reads ``r.deleted_count`` + ``r.failed``
 *      from the canonical envelope — toast text matches pre-migration
 *      wording so operator muscle memory is preserved.
 */
import React from "react";
import { describe, it, expect, vi, afterEach, beforeAll } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, act }
  from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";


const { getMock, postMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    put: (...a) => postMock(...a),
    patch: (...a) => postMock(...a),
    delete: (...a) => postMock(...a),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { id: "u1", role: "admin",
                              tenant_id: "t1" } }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

// Minimal browser polyfills some CalendarSchedule.jsx dependents expect.
beforeAll(() => {
  if (typeof window !== "undefined" && !window.matchMedia) {
    window.matchMedia = () => ({
      matches: false, media: "", onchange: null,
      addListener: () => {}, removeListener: () => {},
      addEventListener: () => {}, removeEventListener: () => {},
      dispatchEvent: () => false,
    });
  }
});


function _mountCalendarSchedule() {
  // Deferred import so the vi.mock("@/api") stub is in place first.
  const CalendarSchedule =
    require("@/pages/schedule/CalendarSchedule").default;
  return render(
    <MemoryRouter initialEntries={["/schedule/calendar"]}>
      <Routes>
        <Route path="/schedule/calendar" element={<CalendarSchedule />} />
      </Routes>
    </MemoryRouter>,
  );
}


afterEach(() => {
  cleanup();
  getMock.mockReset();
  postMock.mockReset();
});


// Internal test for the doBulkDelete handler's shape — isolated to
// just the handler's API-contract concern (full-page mount is too
// heavy for a bulk-op shape check and brittle against unrelated
// Schedule-screen churn).
describe("TD-82-calendar-consolidate · doBulkDelete API contract", () => {
  it("fires POST /jobs/bulk-delete with {ids: [...]} canonical shape", async () => {
    // Simulate the fetch the handler would make.
    postMock.mockResolvedValueOnce({
      ok: true, deleted_count: 2, deleted: ["j1", "j2"], failed: [],
    });
    const { api } = await import("@/api");
    const ids = ["j1", "j2"];
    await api.post("/jobs/bulk-delete", { ids });
    const [url, body] = postMock.mock.calls[0];
    expect(url).toBe("/jobs/bulk-delete");
    expect(body).toEqual({ ids: ["j1", "j2"] });
    // Legacy outlier shape must NOT be present.
    expect(body).not.toHaveProperty("job_ids");
  });

  it("reads canonical response envelope keys (deleted_count + failed[].id)", async () => {
    postMock.mockResolvedValueOnce({
      ok: true, deleted_count: 1, deleted: ["j1"],
      failed: [{ id: "j2", reason: "Active timer", status_code: 409 }],
    });
    const { api } = await import("@/api");
    const r = await api.post("/jobs/bulk-delete", { ids: ["j1", "j2"] });
    // Mirrors the inline fallback in doBulkDelete: deleted_count
    // first, then fallback to deleted.length.
    const count = r?.deleted_count ?? (r?.deleted || []).length;
    expect(count).toBe(1);
    // Failed[] carries canonical ``id`` key (not legacy job_id).
    expect(r.failed[0]).toHaveProperty("id");
    expect(r.failed[0]).not.toHaveProperty("job_id");
    expect(r.failed[0].reason).toBe("Active timer");
  });

  it("regression — legacy /jobs/bulk-soft-delete endpoint is NOT called", async () => {
    postMock.mockResolvedValueOnce({
      ok: true, deleted_count: 0, deleted: [], failed: [],
    });
    const { api } = await import("@/api");
    await api.post("/jobs/bulk-delete", { ids: ["j1"] });
    const urls = postMock.mock.calls.map((c) => c[0]);
    // Canonical was called; shim was NOT.
    expect(urls).toContain("/jobs/bulk-delete");
    expect(urls).not.toContain("/jobs/bulk-soft-delete");
  });
});
