/**
 * Feb-2026 · Sprint — Team · Remove Unlinked Technician — Vitest.
 *
 * Covers the Atomic B2 Remove button + inline ConfirmRemoveModal
 * flow on `UnlinkedTechniciansWidget`. Backend endpoint is
 * ``POST /api/admin/technicians/{tech_id}/remove`` (Atomic B1,
 * commit 1dc62150d).
 *
 * Mock surface MATCHES ``admin-unlinked-technicians-widget.test.jsx``
 * byte-for-byte (same `vi.hoisted`, same `vi.mock("@/api", ...)`)
 * so vitest's forked-worker module registry sees a single shared
 * mock shape across the two files.
 *
 * CRITICAL regression lock (test 9): asserts `apiGetMock` is called
 * exactly ONCE across mount + confirm + success. The prior B2
 * attempt rolled back when an unintended refetch broke the sibling
 * widget-test's `.toHaveBeenCalledTimes(2)` Refresh invariant;
 * this test file now locks the no-refetch invariant explicitly.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import UnlinkedTechniciansWidget from "@/components/team/UnlinkedTechniciansWidget";


// ─── Shared api mock ─────────────────────────────────────────────
const { apiGetMock, apiPostMock } = vi.hoisted(() => ({
  apiGetMock:  vi.fn(),
  apiPostMock: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: apiGetMock, post: apiPostMock,
           put: vi.fn(), patch: vi.fn(), del: vi.fn() },
  api_base: () => "http://test.example/api",
  TOKEN_KEY: "token",
}));


beforeEach(() => {
  apiGetMock.mockReset();
  apiPostMock.mockReset();
});
afterEach(() => cleanup());


const FIXTURE = [
  { tech_id: "t-x", name: "Sara Nguyen",
     email: "sara@test.co", phone: "+16025550137",
     created_at: "2026-02-05T00:00:00Z", tenant_id: "t1" },
  { tech_id: "t-y", name: "Dan Duplicate",
     email: "dupe@test.co", phone: "",
     created_at: "2026-02-06T00:00:00Z", tenant_id: "t1" },
];


// ══════════════════════════════════════════════════════════════════
// 1. Button render per row
// ══════════════════════════════════════════════════════════════════
describe("Remove button · render", () => {
  it("renders a Remove button per row with testid `team-unlinked-tech-remove-{id}`",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-technicians-widget");
      expect(screen.getByTestId("team-unlinked-tech-remove-t-x")).toBeTruthy();
      expect(screen.getByTestId("team-unlinked-tech-remove-t-y")).toBeTruthy();
    });

  it("hides the whole widget (regression lock) when isAdmin=false",
    async () => {
      const { container } = render(
        <UnlinkedTechniciansWidget isAdmin={false} />,
      );
      expect(container.querySelector(
        "[data-testid='unlinked-technicians-widget']"
      )).toBeNull();
      expect(container.querySelector(
        "[data-testid^='team-unlinked-tech-remove-']"
      )).toBeNull();
      expect(apiGetMock).not.toHaveBeenCalled();
    });
});


// ══════════════════════════════════════════════════════════════════
// 2. Confirm modal — open + cancel path
// ══════════════════════════════════════════════════════════════════
describe("Remove button · confirm modal", () => {
  it("clicking Remove opens the inline ConfirmRemoveModal",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-x");
      fireEvent.click(screen.getByTestId("team-unlinked-tech-remove-t-x"));
      const modal = await screen.findByTestId(
        "team-unlinked-tech-remove-confirm-modal");
      expect(modal).toBeTruthy();
      expect(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-ok")).toBeTruthy();
      expect(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-cancel")).toBeTruthy();
    });

  it("Cancel closes the modal, no api.post call, row stays in the list",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-x");
      fireEvent.click(screen.getByTestId("team-unlinked-tech-remove-t-x"));
      await screen.findByTestId("team-unlinked-tech-remove-confirm-modal");
      fireEvent.click(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-cancel"));
      await waitFor(() => {
        expect(screen.queryByTestId(
          "team-unlinked-tech-remove-confirm-modal")).toBeNull();
      });
      expect(apiPostMock).not.toHaveBeenCalled();
      expect(screen.getByTestId("unlinked-tech-row-t-x")).toBeTruthy();
    });
});


// ══════════════════════════════════════════════════════════════════
// 3. Confirm → POST happy path
// ══════════════════════════════════════════════════════════════════
describe("Remove button · confirm happy path", () => {
  it("Confirm fires POST /admin/technicians/{id}/remove with empty body "
    + "and removes the row from the DOM",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      apiPostMock.mockResolvedValueOnce({
        ok: true, tech_id: "t-x",
        deleted_at: "2026-02-10T00:00:00Z",
        deleted_by_user_id: "u-admin-1",
      });
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-x");
      fireEvent.click(screen.getByTestId("team-unlinked-tech-remove-t-x"));
      await screen.findByTestId("team-unlinked-tech-remove-confirm-modal");
      fireEvent.click(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-ok"));
      await waitFor(() => {
        expect(apiPostMock).toHaveBeenCalledWith(
          "/admin/technicians/t-x/remove", {},
        );
      });
      await waitFor(() => {
        expect(screen.queryByTestId("unlinked-tech-row-t-x")).toBeNull();
      });
      expect(screen.queryByTestId(
        "team-unlinked-tech-remove-confirm-modal")).toBeNull();
      expect(screen.getByTestId("unlinked-tech-row-t-y")).toBeTruthy();
    });
});


// ══════════════════════════════════════════════════════════════════
// 4. Idempotent paths — already_removed + 404
// ══════════════════════════════════════════════════════════════════
describe("Remove button · idempotent paths", () => {
  it("400 `already_removed` → row disappears, modal closes, NO inline error",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      const err = new Error("Bad Request");
      err.status = 400;
      err.data = {
        detail: {
          code: "already_removed",
          deleted_at: "2026-02-10T00:00:00Z",
        },
      };
      apiPostMock.mockRejectedValueOnce(err);
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-x");
      fireEvent.click(screen.getByTestId("team-unlinked-tech-remove-t-x"));
      await screen.findByTestId("team-unlinked-tech-remove-confirm-modal");
      fireEvent.click(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-ok"));
      await waitFor(() => {
        expect(screen.queryByTestId("unlinked-tech-row-t-x")).toBeNull();
      });
      expect(screen.queryByTestId("unlinked-tech-error-t-x")).toBeNull();
      expect(screen.queryByTestId(
        "team-unlinked-tech-remove-confirm-modal")).toBeNull();
    });

  it("404 `Technician not found` → row disappears idempotently",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      const err = new Error("Technician not found");
      err.status = 404;
      err.data = { detail: "Technician not found" };
      apiPostMock.mockRejectedValueOnce(err);
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-y");
      fireEvent.click(screen.getByTestId("team-unlinked-tech-remove-t-y"));
      await screen.findByTestId("team-unlinked-tech-remove-confirm-modal");
      fireEvent.click(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-ok"));
      await waitFor(() => {
        expect(screen.queryByTestId("unlinked-tech-row-t-y")).toBeNull();
      });
      expect(screen.queryByTestId("unlinked-tech-error-t-y")).toBeNull();
    });
});


// ══════════════════════════════════════════════════════════════════
// 5. Non-idempotent error — not_unlinked_technician
// ══════════════════════════════════════════════════════════════════
describe("Remove button · non-idempotent error", () => {
  it("400 `not_unlinked_technician` → row stays, inline error row surfaces, "
    + "modal closes, widget stays mounted",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      const err = new Error("Bad Request");
      err.status = 400;
      err.data = {
        detail: {
          code: "not_unlinked_technician",
          message: "This technician is linked to a user account and cannot be removed.",
        },
      };
      apiPostMock.mockRejectedValueOnce(err);
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-x");
      fireEvent.click(screen.getByTestId("team-unlinked-tech-remove-t-x"));
      await screen.findByTestId("team-unlinked-tech-remove-confirm-modal");
      fireEvent.click(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-ok"));
      const errRow = await screen.findByTestId("unlinked-tech-error-t-x");
      expect(errRow).toHaveTextContent(/not_unlinked_technician/);
      expect(errRow).toHaveTextContent(/This technician is linked/);
      expect(screen.getByTestId("unlinked-tech-row-t-x")).toBeTruthy();
      expect(screen.queryByTestId(
        "team-unlinked-tech-remove-confirm-modal")).toBeNull();
      expect(screen.getByTestId("unlinked-technicians-widget")).toBeTruthy();
    });
});


// ══════════════════════════════════════════════════════════════════
// 6. Busy lock — Confirm button disabled during in-flight POST
// ══════════════════════════════════════════════════════════════════
describe("Remove button · busyTechId lock", () => {
  it("Confirm button is disabled while POST is in flight",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      let resolvePost;
      apiPostMock.mockImplementationOnce(
        () => new Promise((res) => { resolvePost = res; }),
      );
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-x");
      fireEvent.click(screen.getByTestId("team-unlinked-tech-remove-t-x"));
      await screen.findByTestId("team-unlinked-tech-remove-confirm-modal");
      fireEvent.click(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-ok"));
      await waitFor(() => {
        expect(screen.getByTestId(
          "team-unlinked-tech-remove-confirm-ok").disabled).toBe(true);
        expect(screen.getByTestId(
          "team-unlinked-tech-remove-confirm-cancel").disabled).toBe(true);
      });
      // Release the POST so afterEach cleanup is clean.
      resolvePost({ ok: true, tech_id: "t-x",
                    deleted_at: "2026-02-10T00:00:00Z",
                    deleted_by_user_id: "u-admin-1" });
      await waitFor(() => {
        expect(screen.queryByTestId("unlinked-tech-row-t-x")).toBeNull();
      });
    });
});


// ══════════════════════════════════════════════════════════════════
// 7. CRITICAL regression lock — api.get call count
// ══════════════════════════════════════════════════════════════════
describe("Remove button · no-refetch invariant", () => {
  it("api.get is called EXACTLY ONCE across mount + confirm + success "
    + "(locks the invariant that broke the prior B2 attempt)",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      apiPostMock.mockResolvedValueOnce({
        ok: true, tech_id: "t-x",
        deleted_at: "2026-02-10T00:00:00Z",
        deleted_by_user_id: "u-admin-1",
      });
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-x");
      fireEvent.click(screen.getByTestId("team-unlinked-tech-remove-t-x"));
      await screen.findByTestId("team-unlinked-tech-remove-confirm-modal");
      fireEvent.click(screen.getByTestId(
        "team-unlinked-tech-remove-confirm-ok"));
      await waitFor(() => {
        expect(screen.queryByTestId("unlinked-tech-row-t-x")).toBeNull();
      });
      // THE invariant — EXACTLY one GET across the entire flow.
      expect(apiGetMock).toHaveBeenCalledTimes(1);
    });
});
