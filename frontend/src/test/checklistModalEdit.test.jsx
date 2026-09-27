/**
 * Feb-2026 · Pool Service PS-A — ChecklistModal post-submit tech-edit UI.
 *
 * Pins the three PS-A frontend invariants:
 *   1. Tech role viewing a SUBMITTED report sees the "changes are
 *      audited" banner + the child form receives ``locked={false}``
 *      so inputs remain editable.
 *   2. Admin role viewing a SUBMITTED report sees the read-only
 *      footer caption + the child form receives ``locked={true}``
 *      (regression check for the "retain existing edit path"
 *      ruling).
 *   3. Tech role viewing a NON-submitted report does NOT show the
 *      banner (banner is post-submit-specific).
 *
 * Mocks
 * ─────
 * ``@/api`` for job + report GETs, ``@/auth`` for role, and stubs
 * the heavy child components (Pool / Landscaping / IndustryChecklistForm,
 * PoolChecklistWizard) so the shell paints quickly and we can
 * capture the ``locked`` prop that ChecklistModal passes down.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen } from "@testing-library/react";

const _mockGet = vi.fn();
const _mockPatch = vi.fn();
const _mockPost = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get:   (...a) => _mockGet(...a),
    patch: (...a) => _mockPatch(...a),
    post:  (...a) => _mockPost(...a),
    put:   vi.fn(),
    del:   vi.fn(),
    delete: vi.fn(),
    request: vi.fn(),
  },
}));

// ── Role is the only piece the modal reads off useAuth for the
// PS-A branches — swap the return on demand per describe block.
let _currentRole = "technician";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: {
      role: _currentRole,
      name: "PS-A test user",
      email: "psa@test",
      technician_id: "tech-1",
      id: "user-1",
    },
  }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
    warning: vi.fn(), info: vi.fn(),
  }),
}));

// ── Capture the props ChecklistModal passes to each child form.
// We only need ``locked`` for PS-A assertions; keep the rest so
// nothing crashes if the modal grabs a callback.
const _landscapingProps = { last: null };
vi.mock("@/components/checklist/LandscapingChecklistForm", () => ({
  default: (props) => {
    _landscapingProps.last = props;
    return (
      <div data-testid="landscape-form-stub"
            data-locked={String(!!props.locked)}
      />
    );
  },
}));
vi.mock("@/components/checklist/PoolChecklistForm", () => ({
  default: (props) => (
    <div data-testid="pool-form-stub"
          data-locked={String(!!props.locked)}
    />
  ),
}));
vi.mock("@/components/checklist/WaterBodyManager", () => ({
  default: () => <div data-testid="pool-wizard-stub" />,
}));
vi.mock("@/components/checklist/GenericChecklistForm", () => ({
  default: () => <div data-testid="generic-form-stub" />,
}));
vi.mock("@/components/checklist/IndustryChecklistForm", () => ({
  default: () => <div data-testid="industry-form-stub" />,
}));
vi.mock("@/components/checklist/PhotoUploader", () => ({
  default: () => <div data-testid="photo-uploader-stub" />,
}));
vi.mock("@/components/customers/CustomerRecapDialog", () => ({
  default: () => null,
}));

// eslint-disable-next-line import/first
import ChecklistModal from "@/components/checklist/ChecklistModal";


function _wireGet({ submitted = false } = {}) {
  _mockGet.mockImplementation((path) => {
    if (path.startsWith("/jobs/") && !path.endsWith("/service-report")) {
      // Landscape service type so ChecklistModal renders the
      // classic landscaping branch (avoids the pool wizard).
      return Promise.resolve({
        id: "job-psa", customer_id: "cust-psa",
        customer_name: "PS-A Cust",
        service_type: "Landscape maintenance",
        title: "PS-A landscape",
        status: submitted ? "completed" : "in-progress",
      });
    }
    if (path.endsWith("/service-report")) {
      return Promise.resolve({
        id: "sr-psa",
        job_id: "job-psa",
        template: "landscape",
        chemical_readings: [],
        chemicals_added: [],
        photos: [],
        notes: "",
        internal_notes: "",
        customer_notes: "",
        checklist_items: [],
        water_bodies: [],
        submitted_at: submitted ? "2026-02-10T00:00:00Z" : null,
      });
    }
    return Promise.resolve({});
  });
}


async function _drain(ms = 40) {
  await act(async () => {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await new Promise((r) => setTimeout(r, ms));
  });
}


beforeEach(() => {
  _mockGet.mockReset();
  _mockPatch.mockReset();
  _mockPost.mockReset();
  _landscapingProps.last = null;
  _currentRole = "technician";
});


describe("PS-A · ChecklistModal · technician on submitted report", () => {
  it("renders the audit banner + passes locked=false to the child form", async () => {
    _wireGet({ submitted: true });
    _currentRole = "technician";
    render(<ChecklistModal jobId="job-psa" open onClose={() => {}} />);
    await _drain();

    // (1) Banner is present with the PS-A copy + testid.
    const banner = screen.getByTestId(
      "checklist-post-submit-edit-banner",
    );
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toMatch(
      /Editing submitted report — changes are audited/,
    );

    // (2) LandscapingChecklistForm was mounted with locked=false so
    //     inputs stay editable.
    expect(_landscapingProps.last).not.toBeNull();
    expect(_landscapingProps.last.locked).toBe(false);
    // Confirm the stub attribute matches for a visible probe.
    expect(screen.getByTestId("landscape-form-stub"))
      .toHaveAttribute("data-locked", "false");

    // (3) Read-only "submitted — read-only" footer caption is
    //     SUPPRESSED for the tech (autosave carries the writes).
    expect(screen.queryByText(/read-only/i)).toBeNull();
  });
});


describe("PS-A · ChecklistModal · admin on submitted report (regression)", () => {
  it("does NOT render the audit banner + passes locked=true to the child form", async () => {
    _wireGet({ submitted: true });
    _currentRole = "admin";
    render(<ChecklistModal jobId="job-psa" open onClose={() => {}} />);
    await _drain();

    // No PS-A banner for admins.
    expect(
      screen.queryByTestId("checklist-post-submit-edit-banner"),
    ).toBeNull();

    // Child form receives locked=true so the read-only view is
    // preserved.
    expect(_landscapingProps.last).not.toBeNull();
    expect(_landscapingProps.last.locked).toBe(true);
    expect(screen.getByTestId("landscape-form-stub"))
      .toHaveAttribute("data-locked", "true");

    // Read-only footer caption is present for admins on submitted
    // reports (retain existing edit path — no regression).
    expect(screen.queryByText(/read-only/i)).toBeInTheDocument();
  });
});


describe("PS-A · ChecklistModal · technician on NOT-yet-submitted report", () => {
  it("does NOT render the audit banner (pre-submit edits aren't audited)", async () => {
    _wireGet({ submitted: false });
    _currentRole = "technician";
    render(<ChecklistModal jobId="job-psa" open onClose={() => {}} />);
    await _drain();

    expect(
      screen.queryByTestId("checklist-post-submit-edit-banner"),
    ).toBeNull();
    // Child form still editable.
    expect(_landscapingProps.last.locked).toBe(false);
  });
});
