import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async (path) => {
      if (path.startsWith("/users?role=technician"))
        return [{ id: "u-1", name: "Ana Tech" }];
      if (path.startsWith("/gps/stops"))
        return { user_name: "Ana Tech", stops: [] };
      if (path.startsWith("/gps/route"))
        return { user_id: "u-1", user_name: "Ana",
                 from: "", to: "", stops: [], pings: [],
                 pings_total: 0, pings_downsample_step: 1,
                 mapbox_token_configured: false };
      return {};
    }),
    post: vi.fn(),
  },
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));
if (typeof window !== "undefined" && !window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}
vi.mock("@/components/layout/SafeScrollContainer", () => ({
  default: ({ children }) => <div>{children}</div>,
}));

import DriverActivityPage from "@/pages/admin/DriverActivityPage";

describe("DriverActivityPage · CSV export dialog (G4)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("Export button opens dialog with scope + kind radios",
     async () => {
    render(<MemoryRouter><DriverActivityPage /></MemoryRouter>);
    const btn = await screen.findByTestId("route-map-export-btn");
    fireEvent.click(btn);
    expect(await screen.findByTestId("route-map-export-modal"))
      .toBeInTheDocument();
    expect(screen.getByTestId("export-scope-tech")).toBeInTheDocument();
    expect(screen.getByTestId("export-scope-all")).toBeInTheDocument();
    expect(screen.getByTestId("export-kind-stops")).toBeInTheDocument();
    expect(screen.getByTestId("export-kind-pings")).toBeInTheDocument();
    // Download href points at our exports endpoint.
    const dl = screen.getByTestId("export-download-btn");
    expect(dl.getAttribute("href"))
      .toContain("/api/admin/gps/export/activity.csv");
    // Switch to pings — href updates.
    fireEvent.click(screen.getByTestId("export-kind-pings"));
    await waitFor(() =>
      expect(screen.getByTestId("export-download-btn")
        .getAttribute("href"))
        .toContain("/api/admin/gps/export/pings.csv"));
  });
});
