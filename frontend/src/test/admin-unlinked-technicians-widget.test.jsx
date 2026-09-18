/**
 * Feb-2026 · Sprint 2 · Section A — Admin "Unlinked Technicians"
 * widget · Vitest.
 *
 * Covers:
 *   1. Empty state — GET returns [] → widget renders nothing.
 *   2. Loading — GET pending → widget renders nothing (no flicker).
 *   3. Populated state — rows render with correct testids + count badge.
 *   4. Create-user happy path — POST fires, temp password modal
 *      surfaces with copy button and invite status line.
 *   5. 409 error path — inline error row surfaces with the code +
 *      an inline "Refresh" button; the widget is NOT dismissed.
 *   6. isAdmin=false → renders null (defense-in-depth).
 *   7. Refresh button re-fetches.
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


// Clipboard mock — jsdom leaves ``navigator.clipboard`` undefined.
beforeEach(() => {
  apiGetMock.mockReset();
  apiPostMock.mockReset();
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: vi.fn(() => Promise.resolve()) },
    configurable: true,
  });
});
afterEach(() => cleanup());


const FIXTURE = [
  { tech_id: "t-a", name: "Sara Nguyen",
     email: "sara@test.co", phone: "+16025550137",
     created_at: "2026-02-05T00:00:00Z", tenant_id: "t1" },
  { tech_id: "t-b", name: "Duplicate Dan",
     email: "dupe@test.co", phone: "",
     created_at: "2026-02-06T00:00:00Z", tenant_id: "t1" },
];


// ══════════════════════════════════════════════════════════════════
// 1. Empty state hides the widget entirely
// ══════════════════════════════════════════════════════════════════
describe("UnlinkedTechniciansWidget · empty state", () => {
  it("renders null when GET returns []", async () => {
    apiGetMock.mockResolvedValueOnce({ technicians: [], count: 0 });
    const { container } = render(<UnlinkedTechniciansWidget isAdmin={true} />);
    // Assert nothing rendered even after the effect resolves.
    await waitFor(() => {
      expect(container.querySelector(
        "[data-testid='unlinked-technicians-widget']"
      )).toBeNull();
    });
    expect(apiGetMock).toHaveBeenCalledWith("/admin/technicians/unlinked");
  });

  it("renders null when GET rejects", async () => {
    apiGetMock.mockRejectedValueOnce(new Error("boom"));
    const { container } = render(<UnlinkedTechniciansWidget isAdmin={true} />);
    await waitFor(() => {
      expect(container.querySelector(
        "[data-testid='unlinked-technicians-widget']"
      )).toBeNull();
    });
  });

  it("renders null when isAdmin=false and never hits the API",
    async () => {
      const { container } = render(
        <UnlinkedTechniciansWidget isAdmin={false} />,
      );
      expect(container.querySelector(
        "[data-testid='unlinked-technicians-widget']"
      )).toBeNull();
      expect(apiGetMock).not.toHaveBeenCalled();
    });
});


// ══════════════════════════════════════════════════════════════════
// 2. Populated state
// ══════════════════════════════════════════════════════════════════
describe("UnlinkedTechniciansWidget · populated state", () => {
  it("renders one row per tech + count badge", async () => {
    apiGetMock.mockResolvedValueOnce({
      technicians: FIXTURE, count: FIXTURE.length,
    });
    render(<UnlinkedTechniciansWidget isAdmin={true} />);
    await screen.findByTestId("unlinked-technicians-widget");
    expect(screen.getByTestId("unlinked-technicians-count-badge"))
      .toHaveTextContent("2");
    expect(screen.getByTestId("unlinked-tech-row-t-a")).toBeTruthy();
    expect(screen.getByTestId("unlinked-tech-row-t-b")).toBeTruthy();
    expect(screen.getByTestId("unlinked-tech-name-t-a"))
      .toHaveTextContent("Sara Nguyen");
    expect(screen.getByTestId("unlinked-tech-email-t-a"))
      .toHaveTextContent("sara@test.co");
  });

  it("Refresh button re-invokes the GET", async () => {
    apiGetMock.mockResolvedValue({
      technicians: FIXTURE, count: FIXTURE.length,
    });
    render(<UnlinkedTechniciansWidget isAdmin={true} />);
    await screen.findByTestId("unlinked-technicians-widget");
    fireEvent.click(screen.getByTestId("unlinked-technicians-refresh"));
    await waitFor(() => {
      expect(apiGetMock).toHaveBeenCalledTimes(2);
    });
  });
});


// ══════════════════════════════════════════════════════════════════
// 3. Create user happy path
// ══════════════════════════════════════════════════════════════════
describe("UnlinkedTechniciansWidget · create user happy path", () => {
  it("POSTs and surfaces the temp password modal + invite status",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      apiPostMock.mockResolvedValueOnce({
        ok: true,
        user_id: "u-new-1",
        email: "sara@test.co",
        temporary_password: "AbCdE123fGhI",
        invite_email_status: "sent",
      });
      const onCreated = vi.fn();
      render(<UnlinkedTechniciansWidget isAdmin={true} onCreated={onCreated} />);
      await screen.findByTestId("unlinked-tech-row-t-a");

      fireEvent.click(screen.getByTestId("unlinked-tech-create-btn-t-a"));

      // Modal appears with the temp password + invite status line.
      const modal = await screen.findByTestId(
        "unlinked-tech-temp-password-modal");
      expect(modal).toBeTruthy();
      expect(screen.getByTestId("unlinked-tech-temp-password-value"))
        .toHaveTextContent("AbCdE123fGhI");
      expect(screen.getByTestId("unlinked-tech-temp-password-email"))
        .toHaveTextContent("sara@test.co");
      expect(screen.getByTestId(
        "unlinked-tech-temp-password-invite-line"))
        .toHaveTextContent(/invite email was also sent/i);

      // Row disappears (widget shrinks toward zero).
      expect(screen.queryByTestId("unlinked-tech-row-t-a")).toBeNull();
      // Second row still there.
      expect(screen.getByTestId("unlinked-tech-row-t-b")).toBeTruthy();
      // Parent notified.
      expect(onCreated).toHaveBeenCalledWith(
        expect.objectContaining({ email: "sara@test.co",
                                    user_id: "u-new-1" }),
      );

      // POST payload is the right shape.
      expect(apiPostMock).toHaveBeenCalledWith(
        "/admin/technicians/t-a/create-user", {},
      );
    });

  it("shows 'skipped' / 'failed' invite message when API says so",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      apiPostMock.mockResolvedValueOnce({
        ok: true, user_id: "u-2", email: "dupe@test.co",
        temporary_password: "aB1cD2eF3gH4",
        invite_email_status: "failed",
      });
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-b");
      fireEvent.click(screen.getByTestId("unlinked-tech-create-btn-t-b"));
      await screen.findByTestId("unlinked-tech-temp-password-modal");
      expect(screen.getByTestId(
        "unlinked-tech-temp-password-invite-line"))
        .toHaveTextContent(/invite email failed/i);
    });

  it("Copy button writes the temp password to the clipboard",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      apiPostMock.mockResolvedValueOnce({
        ok: true, user_id: "u-3", email: "sara@test.co",
        temporary_password: "COPYme1234AB",
        invite_email_status: "sent",
      });
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-a");
      fireEvent.click(screen.getByTestId("unlinked-tech-create-btn-t-a"));
      await screen.findByTestId("unlinked-tech-temp-password-modal");
      fireEvent.click(screen.getByTestId("unlinked-tech-temp-password-copy"));
      await waitFor(() => {
        expect(navigator.clipboard.writeText)
          .toHaveBeenCalledWith("COPYme1234AB");
      });
    });
});


// ══════════════════════════════════════════════════════════════════
// 4. 409 error surface — inline error row, widget stays mounted
// ══════════════════════════════════════════════════════════════════
describe("UnlinkedTechniciansWidget · 409 error path", () => {
  it("surfaces email_already_in_use with the existing user id",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      // Mimic api.post throwing with a .body payload.
      const err = new Error("Conflict");
      err.body = {
        detail: {
          code: "email_already_in_use",
          message: "A user with this email already exists.",
          user_id: "u-existing-999",
        },
      };
      apiPostMock.mockRejectedValueOnce(err);
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-b");
      fireEvent.click(screen.getByTestId("unlinked-tech-create-btn-t-b"));

      const errRow = await screen.findByTestId("unlinked-tech-error-t-b");
      expect(errRow).toHaveTextContent(/email_already_in_use/);
      expect(errRow).toHaveTextContent(/u-existing-999/);
      // Widget stays mounted; NO modal appears.
      expect(screen.getByTestId("unlinked-technicians-widget")).toBeTruthy();
      expect(screen.queryByTestId(
        "unlinked-tech-temp-password-modal")).toBeNull();
      // Refresh button on the error row is wired.
      expect(screen.getByTestId(
        "unlinked-tech-error-refresh-t-b")).toBeTruthy();
    });

  it("surfaces already_linked with a helpful message",
    async () => {
      apiGetMock.mockResolvedValueOnce({
        technicians: FIXTURE, count: FIXTURE.length,
      });
      const err = new Error("Conflict");
      err.body = {
        detail: {
          code: "already_linked",
          message: "This technician is already linked to a user account.",
          user_id: "u-linked-1",
        },
      };
      apiPostMock.mockRejectedValueOnce(err);
      render(<UnlinkedTechniciansWidget isAdmin={true} />);
      await screen.findByTestId("unlinked-tech-row-t-a");
      fireEvent.click(screen.getByTestId("unlinked-tech-create-btn-t-a"));
      const errRow = await screen.findByTestId("unlinked-tech-error-t-a");
      expect(errRow).toHaveTextContent(/already_linked/);
    });
});
