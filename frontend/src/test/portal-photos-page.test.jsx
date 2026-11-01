/**
 * Portal Photos page · Feb-2026 · Vitest.
 *
 * Covers:
 *   1. ``PortalPhotosPage`` grid renders items (TD-67 canonical
 *      ``photos`` key).
 *   2. Empty state.
 *   3. Lightbox opens on tile click, shows job metadata, closes on
 *      the close button.
 *
 *   TD-portal-photos-page-wire-grouping · Feb-2026 — adds 7 new
 *   cases that lock the grouped-by-service-date layout:
 *   4. Date-divider headers appear between distinct day groups.
 *   5. Groups are sorted newest first (DESC by ISO day slice).
 *   6. Multiple photos on the same calendar day appear under ONE
 *      divider.
 *   7. Photos within a day are rendered in the shipped TD-76c
 *      visit-sort order (``firstStamp`` ASC with ``job_id`` tiebreak).
 *   8. ``Load more`` pagination does NOT duplicate dividers when
 *      the newly-loaded page's leading item is same-day as the
 *      previous page's trailing item.
 *   9. Date headers are rendered as ``<h2>`` with ``aria-labelledby``
 *      wiring so screen readers announce the date on group entry.
 *   10. Lightbox click resolves to the right flat index across
 *       grouped render (click on 2nd tile overall opens lightbox
 *       with 2nd photo's metadata, regardless of which group it
 *       lives in).
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor, within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { getSpy, navigateSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  navigateSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  api: { get: (...a) => getSpy(...a), post: vi.fn(), patch: vi.fn() },
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateSpy };
});

beforeEach(() => {
  getSpy.mockReset();
  navigateSpy.mockReset();
});
afterEach(() => cleanup());


import PortalPhotosPage from "@/pages/portal/PortalPhotosPage";


// Canonical BE shape — ``routers/portal_photos.py:49-67`` emits
// ``{photos: [{url, thumb, caption, job_id, job_title, service_type,
// submitted_at, report_id, source, mime}], total}``.  Tests MUST
// use this shape; the pre-TD-67 ``{items: […]}`` branch is a
// defensive fallback only.
const _photo = (overrides = {}) => ({
  url: "/api/files/x/download",
  thumb_url: "/api/files/x/thumb",
  caption: "",
  job_id: "j1",
  job_title: "Weekly Pool Cleaning",
  service_type: "Weekly Pool Cleaning",
  submitted_at: "2026-02-10T10:00:00Z",
  report_id: "r1",
  source: "service_report",
  mime: "image/jpeg",
  ...overrides,
});


describe("PortalPhotosPage · base", () => {
  it("renders the grouped grid when photos are returned", async () => {
    getSpy.mockResolvedValue({
      photos: [
        _photo({ submitted_at: "2026-02-10T10:00:00Z", caption: "before" }),
        _photo({ submitted_at: "2026-02-10T11:00:00Z", caption: "after" }),
      ],
      total: 2, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-grouped")).toBeTruthy(),
    );
    expect(screen.getByTestId("portal-photo-0")).toBeTruthy();
    expect(screen.getByTestId("portal-photo-1")).toBeTruthy();
  });

  it("renders empty state when no photos", async () => {
    getSpy.mockResolvedValue({
      photos: [], total: 0, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-empty")).toBeTruthy(),
    );
    // No grouped container when empty.
    expect(screen.queryByTestId("portal-photos-grouped")).toBeNull();
  });

  it("opens lightbox on tile click with job metadata, closes on close btn", async () => {
    getSpy.mockResolvedValue({
      photos: [_photo({ job_title: "Pool sparkle service" })],
      total: 1, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() => screen.getByTestId("portal-photo-0"));
    fireEvent.click(screen.getByTestId("portal-photo-0"));
    expect(screen.getByTestId("portal-photo-lightbox")).toBeTruthy();
    expect(screen.getByTestId("portal-photo-lightbox-title").textContent)
      .toContain("Pool sparkle service");
    fireEvent.click(screen.getByTestId("portal-photo-lightbox-close"));
    expect(screen.queryByTestId("portal-photo-lightbox")).toBeNull();
  });
});


// ────────────────────────────────────────────────────────────────
// TD-portal-photos-page-wire-grouping · 7 new cases
// ────────────────────────────────────────────────────────────────

describe("PortalPhotosPage · grouping (TD-portal-photos-page-wire-grouping)", () => {
  it("4 · renders a date-divider header between distinct day groups", async () => {
    getSpy.mockResolvedValue({
      photos: [
        _photo({ submitted_at: "2026-02-11T10:00:00Z", caption: "day2" }),
        _photo({ submitted_at: "2026-02-10T10:00:00Z", caption: "day1" }),
      ],
      total: 2, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-grouped")).toBeTruthy(),
    );
    expect(
      screen.getByTestId("portal-photos-date-header-2026-02-11"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("portal-photos-date-header-2026-02-10"),
    ).toBeTruthy();
    // Dividers under each header.
    expect(
      screen.getByTestId("portal-photos-date-divider-2026-02-11"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("portal-photos-date-divider-2026-02-10"),
    ).toBeTruthy();
  });

  it("5 · groups are rendered newest first", async () => {
    getSpy.mockResolvedValue({
      photos: [
        _photo({ submitted_at: "2026-02-11T10:00:00Z" }),
        _photo({ submitted_at: "2026-02-10T10:00:00Z" }),
        _photo({ submitted_at: "2026-02-12T10:00:00Z" }),
      ],
      total: 3, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-grouped")).toBeTruthy(),
    );
    const groups = screen
      .getAllByTestId(/^portal-photos-date-group-/)
      .map((el) => el.getAttribute("data-testid"));
    expect(groups).toEqual([
      "portal-photos-date-group-2026-02-12",
      "portal-photos-date-group-2026-02-11",
      "portal-photos-date-group-2026-02-10",
    ]);
  });

  it("6 · multiple same-day photos appear under ONE divider", async () => {
    getSpy.mockResolvedValue({
      photos: [
        _photo({ submitted_at: "2026-02-10T09:00:00Z", caption: "early" }),
        _photo({ submitted_at: "2026-02-10T14:00:00Z", caption: "mid" }),
        _photo({ submitted_at: "2026-02-10T17:00:00Z", caption: "late" }),
      ],
      total: 3, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-grouped")).toBeTruthy(),
    );
    // Only one divider for the day.
    expect(
      screen.getAllByTestId(/^portal-photos-date-divider-/),
    ).toHaveLength(1);
    // All three tiles live under the single day's group.
    const dayGroup = screen.getByTestId(
      "portal-photos-date-group-2026-02-10",
    );
    expect(within(dayGroup).getAllByTestId(/^portal-photo-\d+$/))
      .toHaveLength(3);
  });

  it("7 · within-day order follows the shipped TD-76c visit-sort", async () => {
    getSpy.mockResolvedValue({
      photos: [
        _photo({
          submitted_at: "2026-02-10T14:00:00Z",
          job_id: "j-later", caption: "later-visit",
        }),
        _photo({
          submitted_at: "2026-02-10T09:00:00Z",
          job_id: "j-earlier", caption: "earlier-visit",
        }),
      ],
      total: 2, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-grouped")).toBeTruthy(),
    );
    // ``portal-photo-0`` must be the earlier-visit photo
    // (firstStamp 09:00 < 14:00) per TD-76c visit ASC sort.
    const firstImg = within(screen.getByTestId("portal-photo-0"))
      .getByRole("img");
    expect(firstImg.getAttribute("alt") || "").toContain("earlier-visit");
    const secondImg = within(screen.getByTestId("portal-photo-1"))
      .getByRole("img");
    expect(secondImg.getAttribute("alt") || "").toContain("later-visit");
  });

  it("8 · Load more does NOT duplicate the divider when leading-item is same-day as trailing", async () => {
    // Page 1: three photos on 2026-02-10 and 2026-02-11.
    // Page 2: another photo on 2026-02-10 (same-day as the trailing
    // page-1 item).  The grouping helper rebuckets on every items
    // change, so the two 2026-02-10 photos fuse into one group and
    // only ONE 2026-02-10 divider renders.
    getSpy
      .mockResolvedValueOnce({
        photos: [
          _photo({ submitted_at: "2026-02-11T10:00:00Z" }),
          _photo({ submitted_at: "2026-02-10T14:00:00Z" }),
        ],
        total: 3, limit: 24, offset: 0,
      })
      .mockResolvedValueOnce({
        photos: [
          _photo({ submitted_at: "2026-02-10T09:00:00Z" }),
        ],
        total: 3, limit: 24, offset: 24,
      });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-grouped")).toBeTruthy(),
    );
    expect(screen.getByTestId("portal-photos-load-more")).toBeTruthy();
    fireEvent.click(screen.getByTestId("portal-photos-load-more"));
    await waitFor(() => {
      // After page 2 lands, exactly ONE divider per day.
      const dividers = screen
        .getAllByTestId(/^portal-photos-date-divider-/)
        .map((el) => el.getAttribute("data-testid"));
      expect(dividers.sort()).toEqual([
        "portal-photos-date-divider-2026-02-10",
        "portal-photos-date-divider-2026-02-11",
      ]);
    });
    // And the two 2026-02-10 tiles live inside the single
    // 2026-02-10 group.
    const dayGroup = screen.getByTestId(
      "portal-photos-date-group-2026-02-10",
    );
    expect(within(dayGroup).getAllByTestId(/^portal-photo-\d+$/))
      .toHaveLength(2);
  });

  it("9 · date headers are <h2> with aria-labelledby wiring for a11y", async () => {
    getSpy.mockResolvedValue({
      photos: [_photo({ submitted_at: "2026-02-10T10:00:00Z" })],
      total: 1, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-grouped")).toBeTruthy(),
    );
    const header = screen.getByTestId(
      "portal-photos-date-header-2026-02-10",
    );
    expect(header.tagName).toBe("H2");
    // Divider has role=separator for screen readers.
    const divider = screen.getByTestId(
      "portal-photos-date-divider-2026-02-10",
    );
    expect(divider.getAttribute("role")).toBe("separator");
    // The group ``<section>`` points its aria-labelledby at the
    // header's id so SRs announce the date on group entry.
    const groupSection = screen.getByTestId(
      "portal-photos-date-group-2026-02-10",
    );
    expect(groupSection.getAttribute("aria-labelledby")).toBe(
      "portal-photos-date-header-2026-02-10",
    );
    expect(header.getAttribute("id")).toBe(
      "portal-photos-date-header-2026-02-10",
    );
  });

  it("10 · lightbox click resolves to the right flat index across groups", async () => {
    getSpy.mockResolvedValue({
      photos: [
        // Group B · 2026-02-11 — single visit, one photo.
        _photo({
          submitted_at: "2026-02-11T10:00:00Z",
          job_title: "Group-B-job",
          job_id: "jB", caption: "b-only",
        }),
        // Group A · 2026-02-10 — two photos, same visit.
        _photo({
          submitted_at: "2026-02-10T10:00:00Z",
          job_title: "Group-A-job",
          job_id: "jA", caption: "a-first",
        }),
        _photo({
          submitted_at: "2026-02-10T11:00:00Z",
          job_title: "Group-A-job",
          job_id: "jA", caption: "a-second",
        }),
      ],
      total: 3, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalPhotosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-photos-grouped")).toBeTruthy(),
    );
    // Click the third tile — must open lightbox with Group-A-job
    // title (second A photo).
    fireEvent.click(screen.getByTestId("portal-photo-2"));
    expect(screen.getByTestId("portal-photo-lightbox")).toBeTruthy();
    expect(screen.getByTestId("portal-photo-lightbox-title").textContent)
      .toContain("Group-A-job");
    fireEvent.click(screen.getByTestId("portal-photo-lightbox-close"));
    // And click the first tile — Group-B-job (newest day).
    fireEvent.click(screen.getByTestId("portal-photo-0"));
    expect(screen.getByTestId("portal-photo-lightbox-title").textContent)
      .toContain("Group-B-job");
  });
});
