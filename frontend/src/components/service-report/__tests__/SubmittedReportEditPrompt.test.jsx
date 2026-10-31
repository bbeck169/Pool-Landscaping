/**
 * Feb-2026 · TD-g2 β · SubmittedReportEditPrompt vitest.
 *
 * Pins the WEB-side β behavior: silent-drop → visible dismissible
 * banner with a CTA that deep-links to the shipped CHEM-LOCK
 * ``JobUnlockButton`` on JobDetail.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import {
  render, screen, fireEvent, act,
} from "@testing-library/react";

import SubmittedReportEditPrompt
  from "@/components/service-report/SubmittedReportEditPrompt";


function _LocationStub() {
  const loc = useLocation();
  return (
    <div data-testid="location-stub">
      {`${loc.pathname}${loc.hash}`}
    </div>
  );
}


function _mount(ui, initial = "/jobs/j1/service-report") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="/jobs/:id/service-report" element={ui} />
        <Route path="/jobs/:id" element={<_LocationStub />} />
      </Routes>
    </MemoryRouter>,
  );
}


describe("SubmittedReportEditPrompt · β", () => {
  it("renders nothing when show=false", () => {
    _mount(<SubmittedReportEditPrompt show={false} jobId="j1" />);
    expect(screen.queryByTestId("submitted-report-edit-prompt"))
      .toBeNull();
  });

  it("renders dismissible banner when show=true with status role",
      () => {
    _mount(<SubmittedReportEditPrompt
      show onDismiss={() => {}} jobId="j1" />);
    const el = screen.getByTestId("submitted-report-edit-prompt");
    expect(el).toBeInTheDocument();
    expect(el).toHaveAttribute("role", "status");
    expect(el).toHaveAttribute("aria-live", "polite");
    expect(el.textContent).toMatch(/This report is submitted/i);
    expect(screen.getByTestId(
      "submitted-report-edit-prompt-unlock-cta",
    )).toBeInTheDocument();
    expect(screen.getByTestId(
      "submitted-report-edit-prompt-close",
    )).toBeInTheDocument();
  });

  it("close button fires onDismiss", () => {
    const onDismiss = vi.fn();
    _mount(<SubmittedReportEditPrompt
      show onDismiss={onDismiss} jobId="j1" />);
    fireEvent.click(screen.getByTestId(
      "submitted-report-edit-prompt-close",
    ));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("Esc fires onDismiss", () => {
    const onDismiss = vi.fn();
    _mount(<SubmittedReportEditPrompt
      show onDismiss={onDismiss} jobId="j1" />);
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(onDismiss).toHaveBeenCalled();
  });

  it("outside-click dismisses the banner", () => {
    const onDismiss = vi.fn();
    _mount(
      <div>
        <div data-testid="outside">outside</div>
        <SubmittedReportEditPrompt
          show onDismiss={onDismiss} jobId="j1" />
      </div>,
    );
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(onDismiss).toHaveBeenCalled();
  });

  it("CTA navigates to /jobs/{jid}#unlock and dismisses", () => {
    const onDismiss = vi.fn();
    _mount(<SubmittedReportEditPrompt
      show onDismiss={onDismiss} jobId="j1" />);
    fireEvent.click(screen.getByTestId(
      "submitted-report-edit-prompt-unlock-cta",
    ));
    expect(onDismiss).toHaveBeenCalled();
    expect(screen.getByTestId("location-stub").textContent)
      .toBe("/jobs/j1#unlock");
  });

  it("CTA is a no-op when jobId is missing (defensive guard)", () => {
    const onDismiss = vi.fn();
    _mount(<SubmittedReportEditPrompt show onDismiss={onDismiss} />);
    fireEvent.click(screen.getByTestId(
      "submitted-report-edit-prompt-unlock-cta",
    ));
    // Dismiss still fires but no navigation occurs.
    expect(onDismiss).toHaveBeenCalled();
    expect(screen.queryByTestId("location-stub")).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// Call-site regression lock — ``ServiceReport.jsx`` + ``Checklist
// Modal.jsx`` short-circuits now split by role.  Pin the shape via
// static source grep so a future refactor can't silently restore the
// pre-β silent-drop behavior.
// ═══════════════════════════════════════════════════════════════════
import fs from "fs";
import path from "path";

const SR = fs.readFileSync(
  path.resolve(__dirname, "../../../pages/tech/ServiceReport.jsx"),
  "utf8",
);
const CM = fs.readFileSync(
  path.resolve(__dirname, "../../../components/checklist/ChecklistModal.jsx"),
  "utf8",
);


describe("TD-g2 β · call-site regressions", () => {
  it("ServiceReport.jsx mounts the banner + splits role on autosave",
      () => {
    expect(SR).toMatch(
      /import SubmittedReportEditPrompt[\s\S]{0,120}service-report\/SubmittedReportEditPrompt/,
    );
    // Admin role branch sets showUnlockPrompt; technician path still
    // short-circuits silently (no setShowUnlockPrompt call).  Role
    // set mirrors BE truth at ``jobs.py:4332`` — dispatcher is NOT
    // included (BE /jobs/{jid}/unlock would 403 them).
    expect(SR).toMatch(
      /_ADMIN_UNLOCK\s*=\s*new Set\(\s*\[\s*"admin",\s*"super_admin",\s*"manager",\s*"owner"\s*,?\s*\]\s*,?\s*\)/,
    );
    // Dispatcher must NOT appear inside the _ADMIN_UNLOCK Set
    // literal — the BE endpoint 403s them, so letting them click
    // the CTA would bounce.
    expect(SR).not.toMatch(
      /_ADMIN_UNLOCK\s*=\s*new Set\([\s\S]{0,160}"dispatcher"/,
    );
    expect(SR).toMatch(
      /if \(_ADMIN_UNLOCK\.has\(_lcRole\)\)[\s\S]{0,80}setShowUnlockPrompt\(true\)/,
    );
    // The pre-β silent-drop short-circuit is GONE as a bare `return;`
    // paired directly with `report.submitted_at`.  Ensures the role
    // split is not accidentally reverted.
    expect(SR).not.toMatch(
      /if \(report\.submitted_at\) return;\s*\n\s*savingRef\.current = true;/,
    );
  });

  it("ChecklistModal.jsx mounts the banner + splits role on autosave",
      () => {
    expect(CM).toMatch(
      /import SubmittedReportEditPrompt[\s\S]{0,120}service-report\/SubmittedReportEditPrompt/,
    );
    expect(CM).toMatch(
      /_ADMIN_UNLOCK_ROLES\s*=\s*new Set\(\s*\[\s*"admin",\s*"super_admin",\s*"manager",\s*"owner"\s*,?\s*\]\s*,?\s*\)/,
    );
    // Dispatcher must NOT appear inside the _ADMIN_UNLOCK_ROLES Set
    // literal — the BE endpoint 403s them, so letting them click the
    // CTA would bounce.
    expect(CM).not.toMatch(
      /_ADMIN_UNLOCK_ROLES\s*=\s*new Set\([\s\S]{0,160}"dispatcher"/,
    );
    expect(CM).toMatch(
      /if \(_ADMIN_UNLOCK_ROLES\.has\(_lcRole\)\)[\s\S]{0,120}setShowUnlockPrompt/,
    );
    // Technician short-circuit path preserved — the submitted-check
    // still runs; the `role !== "technician"` guard is intact.
    expect(CM).toMatch(
      /if \(cur\.submitted_at && role !== "technician"\)/,
    );
  });
});
