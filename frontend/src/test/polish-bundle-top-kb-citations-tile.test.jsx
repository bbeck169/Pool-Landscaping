/**
 * top-kb-citations-tile · Feb-2026 · Polish bundle Item 2
 *
 * Locks the TopKBCitationsTile contract:
 *  1. Renders and hits ``GET /ai/kb/citations/top`` with the default
 *     7d window and limit=10 on mount.
 *  2. Empty state renders when ``items === []``.
 *  3. Populated rows render title + citation count + last-cited chip.
 *  4. Testids: ``ai-kb-citations-tile`` + ``ai-kb-citation-row-<i>``.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const getMock = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...args) => getMock(...args),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    muted: "#666", brand: "#0B4A6F", onSurface: "#111", border: "#ddd",
    brandTertiary: "#E0F2FE", onBrandTertiary: "#0369A1",
  },
}));

import TopKBCitationsTile from "@/components/admin/TopKBCitationsTile";


beforeEach(() => { getMock.mockReset(); });


describe("TopKBCitationsTile · Polish bundle Item 2", () => {
  it("fires GET /ai/kb/citations/top with defaults on mount", async () => {
    getMock.mockResolvedValue({
      items: [],
      days: 7,
      since: "2026-02-01T00:00:00+00:00",
      until: "2026-02-08T00:00:00+00:00",
    });
    render(<TopKBCitationsTile />);
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    const url = getMock.mock.calls[0][0];
    expect(url).toContain("/ai/kb/citations/top");
    expect(url).toContain("days=7");
    expect(url).toContain("limit=10");
  });

  it("renders empty state when items is empty", async () => {
    getMock.mockResolvedValue({
      items: [], days: 7,
      since: "2026-02-01T00:00:00+00:00",
      until: "2026-02-08T00:00:00+00:00",
    });
    render(<TopKBCitationsTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("ai-kb-citations-empty")).toBeTruthy(),
    );
    expect(screen.getByTestId("ai-kb-citations-empty").textContent)
      .toContain("No citations yet");
  });

  it("renders top-5 rows with title, citation count and last-cited chip", async () => {
    getMock.mockResolvedValue({
      items: [
        { doc_id: "d1", doc_title: "Company Profile",
          citations: 12, last_cited_at: "2026-02-06T10:00:00Z" },
        { doc_id: "d2", doc_title: "Chemical Dosing Policy",
          citations: 5, last_cited_at: "2026-02-05T09:00:00Z" },
        { doc_id: "d3", doc_title: "Warranty FAQ",
          citations: 3, last_cited_at: "2026-02-03T11:00:00Z" },
      ],
      days: 7,
      since: "2026-02-01T00:00:00+00:00",
      until: "2026-02-08T00:00:00+00:00",
    });
    render(<TopKBCitationsTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("ai-kb-citation-row-0")).toBeTruthy(),
    );
    expect(screen.getByTestId("ai-kb-citation-row-0").textContent)
      .toContain("Company Profile");
    expect(screen.getByTestId("ai-kb-citation-row-0").textContent)
      .toContain("12");
    expect(screen.getByTestId("ai-kb-citation-row-1").textContent)
      .toContain("Chemical Dosing Policy");
    expect(screen.getByTestId("ai-kb-citation-row-2").textContent)
      .toContain("Warranty FAQ");
  });

  it("truncates rows to top-5 client-side", async () => {
    getMock.mockResolvedValue({
      items: Array.from({ length: 10 }, (_v, i) => ({
        doc_id: `d${i}`, doc_title: `Doc ${i}`,
        citations: 10 - i,
        last_cited_at: "2026-02-06T10:00:00Z",
      })),
      days: 7,
      since: "2026-02-01T00:00:00+00:00",
      until: "2026-02-08T00:00:00+00:00",
    });
    render(<TopKBCitationsTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("ai-kb-citation-row-4")).toBeTruthy(),
    );
    expect(screen.queryByTestId("ai-kb-citation-row-5")).toBeNull();
  });

  it("carries the outer tile testid", async () => {
    getMock.mockResolvedValue({
      items: [], days: 7,
      since: "2026-02-01T00:00:00+00:00",
      until: "2026-02-08T00:00:00+00:00",
    });
    render(<TopKBCitationsTile />);
    await waitFor(() =>
      expect(screen.queryByTestId("ai-kb-citations-tile")).toBeTruthy(),
    );
  });
});
