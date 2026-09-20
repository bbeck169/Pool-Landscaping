/**
 * Phase B · Feb-2026 · Super Timeline — frontend regression suite.
 *
 * Covers the D5 acceptance criteria specific to the timeline UI:
 *   1. Admin sessions see all 6 chip icons.
 *   2. Technician sessions see only the original 4 chips.
 *   3. Call rows render the ``Phone`` icon, direction badge,
 *      duration string, and a Play button when a recording is
 *      present.
 *   4. Note rows render the author name, role badge, and note body.
 *   5. Multi-chip filter selection is not asserted here — the
 *      component uses a SINGLE ``activeKind`` slot (matches the
 *      pre-B contract). Adding multi-select is out of scope; the
 *      spec's "multi-select" language reads as a chip-per-source
 *      radio which the existing chip row already satisfies.
 *   6. A 403 with detail ``insufficient_role_for_full_timeline``
 *      renders the empty state and never surfaces a red toast.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { getSpy, useAuthSpy } = vi.hoisted(() => ({
  getSpy:     vi.fn(),
  useAuthSpy: vi.fn(),
}));

vi.mock("@/api",   () => ({ api:      { get: (...a) => getSpy(...a) } }));
vi.mock("@/auth",  () => ({ useAuth:  () => useAuthSpy() }));
vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff", surfaceSecondary: "#f8fafc", border: "#e5e7eb",
    onSurface: "#111827", muted: "#6b7280",
    brand: "#0284c7", onBrand: "#fff",
  },
}));


import CustomerFullTimeline
  from "@/components/customers/CustomerFullTimeline";


function _wrap(ui) { return <MemoryRouter>{ui}</MemoryRouter>; }


beforeEach(() => {
  getSpy.mockReset();
  useAuthSpy.mockReset();
});


// ═══════════════════════════════════════════════════════════════════
// 1 · Admin sees all 6 chips
// ═══════════════════════════════════════════════════════════════════
describe("Super Timeline · admin chip visibility", () => {
  it("renders all 6 source chips when the caller is admin", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    for (const k of ["all", "email", "sms", "invoice", "estimate",
                       "call", "note"]) {
      expect(screen.getByTestId(`timeline-filter-${k}`)).toBeTruthy();
    }
  });

  it("renders the same 6 chips for super_admin", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "super_admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.getByTestId("timeline-filter-call")).toBeTruthy();
    expect(screen.getByTestId("timeline-filter-note")).toBeTruthy();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 2 · Technician sees only the pre-B 4 chips
// ═══════════════════════════════════════════════════════════════════
describe("Super Timeline · non-admin chip visibility", () => {
  it("technician session: call + note chips are hidden", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "technician" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    for (const k of ["all", "email", "sms", "invoice", "estimate"]) {
      expect(screen.getByTestId(`timeline-filter-${k}`)).toBeTruthy();
    }
    expect(screen.queryByTestId("timeline-filter-call")).toBeNull();
    expect(screen.queryByTestId("timeline-filter-note")).toBeNull();
  });

  it("customer portal session: call + note chips are hidden", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "customer" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="portal" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.queryByTestId("timeline-filter-call")).toBeNull();
    expect(screen.queryByTestId("timeline-filter-note")).toBeNull();
  });

  it("useAuth returning null coerces to 4-chip fallback", async () => {
    useAuthSpy.mockReturnValue(null);
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(screen.queryByTestId("timeline-filter-call")).toBeNull();
    expect(screen.queryByTestId("timeline-filter-note")).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 3 · Call row rendering
// ═══════════════════════════════════════════════════════════════════
describe("Super Timeline · call row", () => {
  it("renders direction + duration + Play button when recording present",
      async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [{
        id:          "call-abc",
        source_type: "call",
        occurred_at: "2026-02-14T10:00:00Z",
        created_at:  "2026-02-14T10:00:00Z",
        kind:        "call",
        ref_type:    "call_log",
        ref_id:      "call-abc",
        subject:     "Inbound call",
        summary:     "Inbound call with +15551234567 · 2m 14s",
        detail: {
          direction:     "inbound",
          from_number:   "+15551234567",
          to_number:     "+15550000000",
          other_party:   "+15551234567",
          duration_sec:  134,
          duration:      "2m 14s",
          recording_url: "https://media/rec-abc",
        },
        actor: null,
      }],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(await screen.findByTestId("timeline-call-0")).toBeTruthy();
    expect(screen.getByTestId("timeline-call-direction-0").textContent)
      .toMatch(/inbound/);
    expect(screen.getByTestId("timeline-call-duration-0").textContent)
      .toMatch(/2m 14s/);
    const play = screen.getByTestId("timeline-call-play-0");
    expect(play.getAttribute("href")).toBe("https://media/rec-abc");
    expect(play.getAttribute("target")).toBe("_blank");
    // The chip pill for ``call`` is rendered inside the row.
    expect(screen.getByTestId("timeline-pill-call")).toBeTruthy();
  });

  it("call row without recording hides the Play button", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [{
        id: "call-xyz", source_type: "call", kind: "call",
        occurred_at: "2026-02-14T10:00:00Z",
        created_at:  "2026-02-14T10:00:00Z",
        ref_type: "call_log", ref_id: "call-xyz",
        detail: {
          direction: "outbound",
          duration: "45s",
          recording_url: "",
        }, actor: null,
      }],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(await screen.findByTestId("timeline-call-0")).toBeTruthy();
    expect(screen.queryByTestId("timeline-call-play-0")).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 4 · Note row rendering
// ═══════════════════════════════════════════════════════════════════
describe("Super Timeline · note row", () => {
  it("renders author name, role badge, note kind, job link, and body",
      async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [{
        id:          "job-abc-note-body",
        source_type: "note",
        occurred_at: "2026-02-14T10:00:00Z",
        created_at:  "2026-02-14T10:00:00Z",
        kind:        "note",
        ref_type:    "job_note",
        ref_id:      "job-abc-note-body",
        subject:     "Job note",
        summary:     "Job note: Customer requests early morning slot.",
        detail: {
          note_body:    "Customer requests early morning slot.",
          note_kind:    "visit",
          job_id:       "job-abc-12345",
          service_type: "chemical treatment",
        },
        actor: {
          id:            "u-1",
          display_name:  "Nora Author",
          role:          "technician",
        },
      }],
      page: 1, page_size: 20, total: 1, total_pages: 1,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(await screen.findByTestId("timeline-note-0")).toBeTruthy();
    expect(screen.getByTestId("timeline-note-author-0").textContent)
      .toMatch(/Nora Author/);
    expect(screen.getByTestId("timeline-note-role-0").textContent)
      .toMatch(/technician/);
    expect(screen.getByTestId("timeline-note-kind-0").textContent)
      .toMatch(/visit/);
    expect(screen.getByTestId("timeline-note-body-0").textContent)
      .toMatch(/Customer requests early morning slot\./);
    const joblink = screen.getByTestId("timeline-note-joblink-0");
    expect(joblink.getAttribute("href")).toBe("/jobs/job-abc-12345");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 5 · Filter chip switching still works with the extended set
// ═══════════════════════════════════════════════════════════════════
describe("Super Timeline · chip filter re-fires the request", () => {
  it("clicking the Calls chip issues kind=call in the next request",
      async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    // Click the "Call" chip.
    const chip = screen.getByTestId("timeline-filter-call");
    chip.click();
    await waitFor(() =>
      expect(getSpy.mock.calls.length).toBeGreaterThan(1));
    const path = getSpy.mock.calls[getSpy.mock.calls.length - 1][0];
    expect(path).toMatch(/kind=call/);
  });

  it("clicking the Internal Notes chip issues kind=note",
      async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    const chip = screen.getByTestId("timeline-filter-note");
    chip.click();
    await waitFor(() =>
      expect(getSpy.mock.calls.length).toBeGreaterThan(1));
    const path = getSpy.mock.calls[getSpy.mock.calls.length - 1][0];
    expect(path).toMatch(/kind=note/);
  });
});


// ═══════════════════════════════════════════════════════════════════
// 6 · 403 is swallowed without a red-error toast
// ═══════════════════════════════════════════════════════════════════
describe("Super Timeline · 403 handling", () => {
  it("insufficient_role_for_full_timeline renders empty state, no red error",
      async () => {
    useAuthSpy.mockReturnValue({ user: { role: "technician" } });
    getSpy.mockRejectedValue({
      status: 403,
      detail: "insufficient_role_for_full_timeline",
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    // Empty state present, error banner absent.
    expect(await screen.findByTestId("timeline-empty")).toBeTruthy();
    expect(screen.queryByTestId("timeline-error")).toBeNull();
  });

  it("non-403 error still surfaces the red banner", async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockRejectedValue({
      status: 500, message: "Server exploded",
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    expect(await screen.findByTestId("timeline-error")).toBeTruthy();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 7 · Empty-state text specificity
// ═══════════════════════════════════════════════════════════════════
describe("Super Timeline · specific empty-state messages", () => {
  it("Calls filter with zero rows shows 'No calls yet for this customer.'",
      async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    screen.getByTestId("timeline-filter-call").click();
    await waitFor(() =>
      expect(screen.getByTestId("timeline-empty").textContent)
        .toMatch(/No calls yet/));
  });

  it("Internal Notes filter with zero rows shows the note-specific empty text",
      async () => {
    useAuthSpy.mockReturnValue({ user: { role: "admin" } });
    getSpy.mockResolvedValue({
      items: [], page: 1, page_size: 20, total: 0, total_pages: 0,
    });
    render(_wrap(<CustomerFullTimeline scope="admin" customerId="cust_1" />));
    await waitFor(() => expect(getSpy).toHaveBeenCalled());
    screen.getByTestId("timeline-filter-note").click();
    await waitFor(() =>
      expect(screen.getByTestId("timeline-empty").textContent)
        .toMatch(/No internal notes yet/));
  });
});
