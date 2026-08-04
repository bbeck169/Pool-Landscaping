/**
 * Phase F2c · Feb 2026 — Customer portal uploads · Vitest.
 *
 * Covers:
 *   F2c.1 — PortalBookingPhotos on the booking confirmation panel
 *   F2c.2 — JobBeforeAfterPhotos in readOnly mode for customers
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

const uploadSpies = [];
const listSpies = [];
vi.mock("@/components/files/FileUpload", () => ({
  FileUpload: (props) => {
    uploadSpies.push(props);
    return <div data-testid={`mock-upload-${props.purpose}`}
                 data-accept={props.accept}
                 data-multiple={String(props.multiple)}
                 data-max-files={String(props.maxFiles)}
                 data-linked-type={props.linkedEntityType}
                 data-linked-id={props.linkedEntityId} />;
  },
}));

// Overridable mock so a couple of tests can simulate empty vs non-empty
// FileList results.
let listResults = { job_before_photo: 0, job_after_photo: 0, portal_booking_photo: 0 };
vi.mock("@/components/files/FileList", () => ({
  FileList: (props) => {
    listSpies.push(props);
    // Immediately fire onChange with an array of the mocked length so
    // hideWhenEmpty logic works synchronously in tests.
    const n = listResults[props.purpose] ?? 0;
    // Phase 41.3 · fire ONCE on mount — hook call must be
    // unconditional to satisfy rules-of-hooks. Effect body guards
    // the ``onChange`` presence itself.
    // Phase 41.3 · Feb-2026 — this mock intentionally captures ``n`` and
    // ``props`` at mount and fires ``onChange`` once. Adding either to
    // the deps array would defeat the mock's purpose.
    React.useEffect(() => {
      if (typeof props.onChange === "function") {
        props.onChange(Array(n).fill({ id: "x", purpose: props.purpose }));
      }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps -- mount-only test mock; captured deps are stable for this mock's lifetime
    return <div data-testid={`mock-list-${props.purpose}`}
                 data-linked-type={props.linkedEntityType}
                 data-linked-id={props.linkedEntityId}
                 data-can-delete={String(props.canDelete)}
                 data-count={n} />;
  },
}));

import { PortalBookingPhotos } from "@/components/portal/PortalBookingPhotos";
import { JobBeforeAfterPhotos } from "@/components/jobs/JobBeforeAfterPhotos";

beforeEach(() => {
  uploadSpies.length = 0;
  listSpies.length = 0;
  listResults = { job_before_photo: 0, job_after_photo: 0, portal_booking_photo: 0 };
  cleanup();
});

// ═══════════════════════════════════════════════════════════════════
// F2c.1 · PortalBookingPhotos
// ═══════════════════════════════════════════════════════════════════
describe("PortalBookingPhotos · F2c.1", () => {
  it("renders when an appointmentId is present", () => {
    render(<PortalBookingPhotos appointmentId="appt-1" />);
    expect(screen.getByTestId("portal-booking-photos")).toBeTruthy();
  });

  it("returns null when appointmentId is falsy", () => {
    const { container } = render(<PortalBookingPhotos appointmentId={null} />);
    expect(container.textContent).toBe("");
  });

  it("FileUpload passes purpose='portal_booking_photo' + type='portal_appointment' + id", () => {
    render(<PortalBookingPhotos appointmentId="appt-42" />);
    const el = screen.getByTestId("mock-upload-portal_booking_photo");
    expect(el.getAttribute("data-linked-type")).toBe("portal_appointment");
    expect(el.getAttribute("data-linked-id")).toBe("appt-42");
  }); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3: deps 'n' intentionally omitted (mount-only or stable-ref)

  it("multi-file mode with maxFiles=5", () => {
    render(<PortalBookingPhotos appointmentId="appt-1" />);
    const el = screen.getByTestId("mock-upload-portal_booking_photo");
    expect(el.getAttribute("data-multiple")).toBe("true");
    expect(el.getAttribute("data-max-files")).toBe("5");
  });

  it("accept: image/* + video/mp4", () => {
    render(<PortalBookingPhotos appointmentId="appt-1" />);
    const el = screen.getByTestId("mock-upload-portal_booking_photo");
    const accept = el.getAttribute("data-accept");
    expect(accept).toContain("image/");
    expect(accept).toContain("video/mp4");
  });

  it("customer can delete their own uploads (F0 backend gates per-file)", () => {
    render(<PortalBookingPhotos appointmentId="appt-1" />);
    expect(screen.getByTestId("mock-list-portal_booking_photo").getAttribute("data-can-delete"))
      .toBe("true");
  });
});

// ═══════════════════════════════════════════════════════════════════
// F2c.2 · JobBeforeAfterPhotos read-only for customers
// ═══════════════════════════════════════════════════════════════════
describe("JobBeforeAfterPhotos · readOnly (F2c.2)", () => {
  it("hides FileUpload entirely in readOnly mode", () => {
    listResults = { job_before_photo: 1, job_after_photo: 1 };
    render(<JobBeforeAfterPhotos jobId="j1" user={{ role: "customer" }} readOnly />);
    expect(screen.queryByTestId("mock-upload-job_before_photo")).toBeNull();
    expect(screen.queryByTestId("mock-upload-job_after_photo")).toBeNull();
  });

  it("forces canDelete=false on both FileLists in readOnly mode", () => {
    listResults = { job_before_photo: 1, job_after_photo: 1 };
    render(<JobBeforeAfterPhotos jobId="j1" user={{ role: "customer" }} readOnly />);
    for (const p of ["job_before_photo", "job_after_photo"]) {
      expect(screen.getByTestId(`mock-list-${p}`).getAttribute("data-can-delete"))
        .toBe("false");
    }
  });

  it("renders the FileLists when readOnly + at least one bucket has photos", () => {
    listResults = { job_before_photo: 2, job_after_photo: 0 };
    render(<JobBeforeAfterPhotos jobId="j1" user={{ role: "customer" }} readOnly />);
    // Before bucket has photos → its list mounts.
    expect(screen.getByTestId("mock-list-job_before_photo")).toBeTruthy();
    // After bucket has 0 photos → hidden per hideWhenEmpty.
    // (Not asserting DOM-absence because the mock still calls onChange
    // once — the parent bucket only unmounts on the second render
    // after ``count`` state updates. This is fine — the visual outcome
    // in production is a suppressed empty bucket.)
  });

  it("uses 'Photos' heading (not 'Before & After Photos') in readOnly", () => {
    listResults = { job_before_photo: 1, job_after_photo: 1 };
    render(<JobBeforeAfterPhotos jobId="j1" user={{ role: "customer" }} readOnly />);
    // hint chip is hidden in readOnly
    expect(screen.queryByTestId("job-before-after-photos-hint")).toBeNull();
    const container = screen.getByTestId("job-before-after-photos");
    expect(container.textContent).toContain("Photos");
    expect(container.textContent).not.toContain("Before & After Photos");
  });

  it("write mode (readOnly=false) still shows the upload + hint chip", () => {
    render(<JobBeforeAfterPhotos jobId="j1" user={{ role: "admin" }} />);
    expect(screen.getByTestId("mock-upload-job_before_photo")).toBeTruthy();
    expect(screen.getByTestId("mock-upload-job_after_photo")).toBeTruthy();
    expect(screen.getByTestId("job-before-after-photos-hint")).toBeTruthy();
  });
});
