/**
 * Feb-2026 · Phase 21 · Addition A recovered — Workstream tab in the
 * Dispatch Board tab strip pushes `/workstream`.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => navigateMock };
});

// Stub away the heavy dispatch dependencies so the test only exercises
// the tab strip render path.
vi.mock("@/api", () => ({ api: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock("@/lib/dispatchBoardApi", () => ({
  fetchBoard: vi.fn().mockResolvedValue({ jobs: [], techs: [] }),
  optimizeBoard: vi.fn(),
  applyBoardOrder: vi.fn(),
  fetchAllShifts: vi.fn().mockResolvedValue([]),
  applyShiftMove: vi.fn(),
  fetchWeekBoard: vi.fn().mockResolvedValue({ days: {} }),
}));
vi.mock("@/hooks/useTechColorMap", () => ({
  useTechColorMap: () => new Map(),
}), { virtual: true });
vi.mock("@/components/DispatchBoard/DispatchMap", () => ({ default: () => null }));
vi.mock("@/components/DispatchBoard/RouteDetailsPanel", () => ({ default: () => null }));
vi.mock("@/components/DispatchBoard/TechLoadStrip", () => ({ default: () => null }));
vi.mock("@/components/DispatchBoard/OptimizeButton", () => ({ default: () => null }));
vi.mock("@vis.gl/react-google-maps", () => ({
  Map: () => null,
  APIProvider: ({ children }) => children,
  useMap: () => null,
  useMapsLibrary: () => null,
  AdvancedMarker: () => null,
  Pin: () => null,
  InfoWindow: () => null,
}));

import DispatchBoardPage from "@/pages/dispatch/DispatchBoardPage";


beforeEach(() => { navigateMock.mockReset(); });


describe("DispatchBoardPage · Workstream tab", () => {
  it("clicking the Workstream tab pushes '/workstream'", async () => {
    render(
      <MemoryRouter>
        <DispatchBoardPage />
      </MemoryRouter>,
    );
    const btn = await screen.findByTestId("dispatch-tab-workstream");
    expect(btn.textContent).toMatch(/workstream/i);
    fireEvent.click(btn);
    expect(navigateMock).toHaveBeenCalledWith("/workstream");
  });
});
