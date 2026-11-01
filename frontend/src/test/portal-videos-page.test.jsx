/**
 * Portal Videos page · Feb-2026 · Vitest.
 *
 * TD-portal-videos-page-wire-grouping — mirror of the Photos
 * fix (`bbecd6da1`).  Covers the same 10 shapes the Photos
 * vitest file does, swapped for the video surface:
 *
 *   1. Grid renders items (TD-67 canonical ``videos`` key).
 *   2. Empty state.
 *   3. Lightbox opens on tile click, closes on close button.
 *   4. Date-divider header renders between distinct day groups.
 *   5. Groups ordered newest first (ISO lex DESC).
 *   6. Same-day videos collapse into ONE divider.
 *   7. Within-day visit-sort via the shared helper
 *      (``firstStamp`` ASC with ``visitKey`` tiebreak).
 *   8. ``Load more`` does NOT duplicate the divider when the
 *      newly-loaded page's leading item is same-day as the
 *      trailing item of the previous page.
 *   9. a11y: ``<h2>`` headers + ``aria-labelledby`` wiring +
 *      ``role="separator"`` divider.
 *  10. Lightbox click resolves to the right flat index across
 *      grouped render.
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


import PortalVideosPage from "@/pages/portal/PortalVideosPage";


// Canonical BE shape — ``routers/portal_videos.py:72`` emits
// ``{videos: [{kind, entity_id, entity_title, video_id,
// storage_path, url, poster_url, mime, size_bytes,
// duration_seconds, caption, uploaded_at, source}], total}``.
const _video = (overrides = {}) => ({
  kind: "job",
  entity_id: "j1",
  entity_title: "Weekly Pool Service · 2026-02-10",
  video_id: `v-${Math.random().toString(36).slice(2, 8)}`,
  storage_path: "x/x.mp4",
  url: "/api/media/videos/x",
  poster_url: "",
  mime: "video/mp4",
  size_bytes: 1,
  duration_seconds: 10,
  caption: "",
  uploaded_at: "2026-02-10T10:00:00Z",
  source: "service_report",
  ...overrides,
});


describe("PortalVideosPage · base", () => {
  it("1 · renders the grouped grid when videos are returned", async () => {
    getSpy.mockResolvedValue({
      videos: [
        _video({ uploaded_at: "2026-02-10T10:00:00Z", caption: "early" }),
        _video({ uploaded_at: "2026-02-10T11:00:00Z", caption: "late" }),
      ],
      total: 2, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-grouped")).toBeTruthy(),
    );
    expect(screen.getByTestId("portal-video-0")).toBeTruthy();
    expect(screen.getByTestId("portal-video-1")).toBeTruthy();
  });

  it("2 · renders empty state when no videos", async () => {
    getSpy.mockResolvedValue({
      videos: [], total: 0, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-empty")).toBeTruthy(),
    );
    expect(screen.queryByTestId("portal-videos-grouped")).toBeNull();
  });

  it("3 · opens the lightbox on tile click, closes on close button", async () => {
    getSpy.mockResolvedValue({
      videos: [_video({ entity_title: "Pool deep-clean recording" })],
      total: 1, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() => screen.getByTestId("portal-video-0"));
    fireEvent.click(screen.getByTestId("portal-video-0"));
    expect(screen.getByTestId("portal-video-modal")).toBeTruthy();
    expect(
      screen.getByTestId("portal-video-modal-title").textContent,
    ).toContain("Pool deep-clean recording");
    fireEvent.click(screen.getByTestId("portal-video-modal-close"));
    expect(screen.queryByTestId("portal-video-modal")).toBeNull();
  });
});


// ────────────────────────────────────────────────────────────
// TD-portal-videos-page-wire-grouping · 7 grouping cases
// ────────────────────────────────────────────────────────────

describe("PortalVideosPage · grouping (TD-portal-videos-page-wire-grouping)", () => {
  it("4 · renders a date-divider header between distinct day groups", async () => {
    getSpy.mockResolvedValue({
      videos: [
        _video({ uploaded_at: "2026-02-11T10:00:00Z" }),
        _video({ uploaded_at: "2026-02-10T10:00:00Z" }),
      ],
      total: 2, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-grouped")).toBeTruthy(),
    );
    expect(
      screen.getByTestId("portal-videos-date-header-2026-02-11"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("portal-videos-date-header-2026-02-10"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("portal-videos-date-divider-2026-02-11"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("portal-videos-date-divider-2026-02-10"),
    ).toBeTruthy();
  });

  it("5 · groups are rendered newest first", async () => {
    getSpy.mockResolvedValue({
      videos: [
        _video({ uploaded_at: "2026-02-11T10:00:00Z" }),
        _video({ uploaded_at: "2026-02-10T10:00:00Z" }),
        _video({ uploaded_at: "2026-02-12T10:00:00Z" }),
      ],
      total: 3, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-grouped")).toBeTruthy(),
    );
    const groups = screen
      .getAllByTestId(/^portal-videos-date-group-/)
      .map((el) => el.getAttribute("data-testid"));
    expect(groups).toEqual([
      "portal-videos-date-group-2026-02-12",
      "portal-videos-date-group-2026-02-11",
      "portal-videos-date-group-2026-02-10",
    ]);
  });

  it("6 · multiple same-day videos appear under ONE divider", async () => {
    getSpy.mockResolvedValue({
      videos: [
        _video({ uploaded_at: "2026-02-10T09:00:00Z", caption: "a" }),
        _video({ uploaded_at: "2026-02-10T14:00:00Z", caption: "b" }),
        _video({ uploaded_at: "2026-02-10T17:00:00Z", caption: "c" }),
      ],
      total: 3, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-grouped")).toBeTruthy(),
    );
    expect(
      screen.getAllByTestId(/^portal-videos-date-divider-/),
    ).toHaveLength(1);
    const dayGroup = screen.getByTestId(
      "portal-videos-date-group-2026-02-10",
    );
    expect(within(dayGroup).getAllByTestId(/^portal-video-\d+$/))
      .toHaveLength(3);
  });

  it("7 · within-day order follows the shared visit-sort via entity_id tiebreak", async () => {
    getSpy.mockResolvedValue({
      videos: [
        _video({
          uploaded_at: "2026-02-10T14:00:00Z",
          entity_id: "j-later",
          entity_title: "later-visit",
        }),
        _video({
          uploaded_at: "2026-02-10T09:00:00Z",
          entity_id: "j-earlier",
          entity_title: "earlier-visit",
        }),
      ],
      total: 2, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-grouped")).toBeTruthy(),
    );
    // ``portal-video-0`` must be the earlier-visit video
    // (firstStamp 09:00 < 14:00) per shared visit ASC sort.
    const first = screen.getByTestId("portal-video-0");
    expect(first.textContent || "").toContain("earlier-visit");
    const second = screen.getByTestId("portal-video-1");
    expect(second.textContent || "").toContain("later-visit");
  });

  it("8 · Load more does NOT duplicate the divider across same-day page boundaries", async () => {
    getSpy
      .mockResolvedValueOnce({
        videos: [
          _video({ uploaded_at: "2026-02-11T10:00:00Z" }),
          _video({ uploaded_at: "2026-02-10T14:00:00Z" }),
        ],
        total: 3, limit: 24, offset: 0,
      })
      .mockResolvedValueOnce({
        videos: [
          _video({ uploaded_at: "2026-02-10T09:00:00Z" }),
        ],
        total: 3, limit: 24, offset: 24,
      });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-grouped")).toBeTruthy(),
    );
    expect(screen.getByTestId("portal-videos-load-more")).toBeTruthy();
    fireEvent.click(screen.getByTestId("portal-videos-load-more"));
    await waitFor(() => {
      const dividers = screen
        .getAllByTestId(/^portal-videos-date-divider-/)
        .map((el) => el.getAttribute("data-testid"));
      expect(dividers.sort()).toEqual([
        "portal-videos-date-divider-2026-02-10",
        "portal-videos-date-divider-2026-02-11",
      ]);
    });
    const dayGroup = screen.getByTestId(
      "portal-videos-date-group-2026-02-10",
    );
    expect(within(dayGroup).getAllByTestId(/^portal-video-\d+$/))
      .toHaveLength(2);
  });

  it("9 · date headers are <h2> with aria-labelledby + role=separator divider", async () => {
    getSpy.mockResolvedValue({
      videos: [_video({ uploaded_at: "2026-02-10T10:00:00Z" })],
      total: 1, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-grouped")).toBeTruthy(),
    );
    const header = screen.getByTestId(
      "portal-videos-date-header-2026-02-10",
    );
    expect(header.tagName).toBe("H2");
    const divider = screen.getByTestId(
      "portal-videos-date-divider-2026-02-10",
    );
    expect(divider.getAttribute("role")).toBe("separator");
    const groupSection = screen.getByTestId(
      "portal-videos-date-group-2026-02-10",
    );
    expect(groupSection.getAttribute("aria-labelledby")).toBe(
      "portal-videos-date-header-2026-02-10",
    );
    expect(header.getAttribute("id")).toBe(
      "portal-videos-date-header-2026-02-10",
    );
  });

  it("10 · lightbox click resolves to the right flat index across groups", async () => {
    getSpy.mockResolvedValue({
      videos: [
        // Group B · 2026-02-11 — one video.
        _video({
          uploaded_at: "2026-02-11T10:00:00Z",
          entity_id: "jB",
          entity_title: "Group-B-recording",
        }),
        // Group A · 2026-02-10 — two videos.
        _video({
          uploaded_at: "2026-02-10T10:00:00Z",
          entity_id: "jA",
          entity_title: "Group-A-recording",
        }),
        _video({
          uploaded_at: "2026-02-10T11:00:00Z",
          entity_id: "jA",
          entity_title: "Group-A-recording",
        }),
      ],
      total: 3, limit: 24, offset: 0,
    });
    render(<MemoryRouter><PortalVideosPage /></MemoryRouter>);
    await waitFor(() =>
      expect(screen.getByTestId("portal-videos-grouped")).toBeTruthy(),
    );
    // Click the third tile — must open modal with Group-A title.
    fireEvent.click(screen.getByTestId("portal-video-2"));
    expect(screen.getByTestId("portal-video-modal")).toBeTruthy();
    expect(
      screen.getByTestId("portal-video-modal-title").textContent,
    ).toContain("Group-A-recording");
    fireEvent.click(screen.getByTestId("portal-video-modal-close"));
    // And click the first tile — Group-B (newest day).
    fireEvent.click(screen.getByTestId("portal-video-0"));
    expect(
      screen.getByTestId("portal-video-modal-title").textContent,
    ).toContain("Group-B-recording");
  });
});
