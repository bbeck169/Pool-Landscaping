/**
 * CHEM-LOCK · Feb-2026 — Admin unlock button contract tests.
 *
 * Full-component render (JobUnlockButton is a self-contained modal
 * with a small footprint). Covers:
 *   1. Admin sees "Unlock for Edit" when the job is locked.
 *   2. Tech does NOT see the button (role gate).
 *   3. Non-admin never sees it even when the SR is submitted.
 *   4. Admin sees NOTHING when the job is already unlocked
 *      (idempotency: no re-unlock button).
 *   5. Clicking opens a modal with a required reason textarea.
 *   6. Submit button disabled until reason >= 8 chars.
 *   7. Paid-invoice warning renders when backend returns the flag.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/api", () => ({ api: { post: vi.fn() } }));

import { api } from "@/api";
import JobUnlockButton from "../pages/jobs/JobUnlockButton";


function _lockedJob(overrides = {}) {
  return {
    id: "job-abc",
    status: "completed",
    service_report_submitted_at: "2026-02-16T10:00:00Z",
    unlocked_at: null,
    ...overrides,
  };
}

const _admin  = { role: "admin",       id: "u-admin",  email: "a@x.com" };
const _super  = { role: "super_admin", id: "u-super",  email: "s@x.com" };
const _tech   = { role: "technician",  id: "u-tech",   email: "t@x.com" };
const _cust   = { role: "customer",    id: "u-cust",   email: "c@x.com" };


beforeEach(() => {
  vi.clearAllMocks();
});


describe("JobUnlockButton · CHEM-LOCK", () => {
  it("renders the ``Unlock for Edit`` button for admin on a locked job", () => {
    render(<JobUnlockButton job={_lockedJob()} user={_admin} />);
    expect(screen.getByTestId("jd-unlock-button")).toBeTruthy();
    expect(screen.getByTestId("jd-unlock-button").textContent)
      .toMatch(/Unlock for Edit/);
  });

  it("renders for super_admin on a locked job", () => {
    render(<JobUnlockButton job={_lockedJob()} user={_super} />);
    expect(screen.getByTestId("jd-unlock-button")).toBeTruthy();
  });

  it("does NOT render for technician role", () => {
    render(<JobUnlockButton job={_lockedJob()} user={_tech} />);
    expect(screen.queryByTestId("jd-unlock-button")).toBeNull();
  });

  it("does NOT render for customer role", () => {
    render(<JobUnlockButton job={_lockedJob()} user={_cust} />);
    expect(screen.queryByTestId("jd-unlock-button")).toBeNull();
  });

  it("does NOT render when job.unlocked_at is already stamped (idempotent)", () => {
    render(
      <JobUnlockButton
        job={_lockedJob({ unlocked_at: "2026-02-16T11:00:00Z" })}
        user={_admin}
      />,
    );
    expect(screen.queryByTestId("jd-unlock-button")).toBeNull();
  });

  it("does NOT render when job.service_report_submitted_at is null (nothing to unlock)", () => {
    render(
      <JobUnlockButton
        job={_lockedJob({ service_report_submitted_at: null })}
        user={_admin}
      />,
    );
    expect(screen.queryByTestId("jd-unlock-button")).toBeNull();
  });

  it("opens a modal with a required reason field on click", () => {
    render(<JobUnlockButton job={_lockedJob()} user={_admin} />);
    fireEvent.click(screen.getByTestId("jd-unlock-button"));
    expect(screen.getByTestId("jd-unlock-modal")).toBeTruthy();
    expect(screen.getByTestId("jd-unlock-reason-input")).toBeTruthy();
  });

  it("keeps the confirm button disabled until reason >= 8 chars", () => {
    render(<JobUnlockButton job={_lockedJob()} user={_admin} />);
    fireEvent.click(screen.getByTestId("jd-unlock-button"));
    const confirm = screen.getByTestId("jd-unlock-confirm");
    const input = screen.getByTestId("jd-unlock-reason-input");

    // Empty → disabled.
    expect(confirm.disabled).toBe(true);

    // Short (< 8 chars) → still disabled.
    fireEvent.change(input, { target: { value: "short" } });
    expect(confirm.disabled).toBe(true);

    // Exactly 8 chars → enabled.
    fireEvent.change(input, { target: { value: "12345678" } });
    expect(confirm.disabled).toBe(false);
  });

  it("renders the reason length hint (progress toward 8)", () => {
    render(<JobUnlockButton job={_lockedJob()} user={_admin} />);
    fireEvent.click(screen.getByTestId("jd-unlock-button"));
    const input = screen.getByTestId("jd-unlock-reason-input");
    fireEvent.change(input, { target: { value: "abc" } });
    expect(screen.getByTestId("jd-unlock-reason-length").textContent)
      .toMatch(/3\/8/);
  });

  it("submits the reason to POST /jobs/{id}/unlock and calls onUnlocked on success", async () => {
    api.post.mockResolvedValueOnce({
      ok: true, warnings: [], audit_id: "aud-1",
      unlocked_at: "2026-02-16T12:00:00Z",
      job: { id: "job-abc", unlocked_at: "2026-02-16T12:00:00Z" },
    });
    const onUnlocked = vi.fn();
    render(
      <JobUnlockButton
        job={_lockedJob()}
        user={_admin}
        onUnlocked={onUnlocked}
      />,
    );
    fireEvent.click(screen.getByTestId("jd-unlock-button"));
    fireEvent.change(screen.getByTestId("jd-unlock-reason-input"),
                     { target: { value: "Correcting chlorine typo" } });
    fireEvent.click(screen.getByTestId("jd-unlock-confirm"));

    await waitFor(() => expect(onUnlocked).toHaveBeenCalledTimes(1));
    expect(api.post).toHaveBeenCalledWith(
      "/jobs/job-abc/unlock",
      { reason: "Correcting chlorine typo" },
    );
  });

  it("reveals the paid-invoice ack checkbox after a warnings payload comes back", async () => {
    // First POST → returns invoice_paid warning; second POST after
    // ack → success. The component surfaces the ack checkbox after
    // the first response so the admin has to consciously agree.
    api.post.mockResolvedValueOnce({
      ok: true, warnings: ["invoice_paid"], audit_id: null,
    });
    render(<JobUnlockButton job={_lockedJob()} user={_admin} />);
    fireEvent.click(screen.getByTestId("jd-unlock-button"));
    fireEvent.change(screen.getByTestId("jd-unlock-reason-input"),
                     { target: { value: "This has been paid already" } });
    fireEvent.click(screen.getByTestId("jd-unlock-confirm"));

    await waitFor(() =>
      expect(screen.queryByTestId("jd-unlock-invoice-paid-warning"))
        .toBeTruthy(),
    );
    // Confirm re-disables until ack.
    const confirm = screen.getByTestId("jd-unlock-confirm");
    expect(confirm.disabled).toBe(true);
    fireEvent.click(screen.getByTestId("jd-unlock-ack-invoice-checkbox"));
    expect(confirm.disabled).toBe(false);
  });

  it("cancel button closes the modal without an api call", () => {
    render(<JobUnlockButton job={_lockedJob()} user={_admin} />);
    fireEvent.click(screen.getByTestId("jd-unlock-button"));
    fireEvent.click(screen.getByTestId("jd-unlock-cancel"));
    expect(screen.queryByTestId("jd-unlock-modal")).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });
});
