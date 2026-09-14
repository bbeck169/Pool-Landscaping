/**
 * Phase Feb-2026 · Multi-industry Phase B — settings UI + badges.
 *
 * Covers:
 *   • Settings grid renders all 25 checkboxes with proper testids.
 *   • Toggling a checkbox PATCHes /tenants/mine/settings with the
 *     updated array (canonical enum order preserved).
 *   • Success shows the saved toast; 422 shows the error toast + rolls back.
 *   • Badges render N chips (one per selected industry).
 *   • Overflow: >4 → 3 chips + "+N more"; click expands to reveal the rest.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const { getSpy, patchSpy } = vi.hoisted(() => ({
  getSpy: vi.fn(),
  patchSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => getSpy(...a),
    patch: (...a) => patchSpy(...a),
  },
}));

// Reset the useIndustries module cache between tests.
import { invalidateIndustries } from "@/hooks/useIndustries";
import IndustriesSettings from "@/pages/settings/IndustriesSettings";
import TenantIndustryBadges from "@/components/tenant/TenantIndustryBadges";
import { INDUSTRIES } from "@/config/industries";


describe("Multi-industry Phase B · IndustriesSettings", () => {
  beforeEach(() => {
    getSpy.mockReset(); patchSpy.mockReset();
    invalidateIndustries();
  });

  it("renders all 25 checkboxes with per-slug testids", async () => {
    getSpy.mockResolvedValue({ industries: ["pools"] });
    render(<IndustriesSettings />);
    await waitFor(() =>
      expect(screen.getByTestId("settings-industry-checkbox-pools"))
        .toBeInTheDocument()
    );
    for (const slug of INDUSTRIES) {
      expect(screen.getByTestId(`settings-industry-checkbox-${slug}`))
        .toBeInTheDocument();
    }
    expect(screen.getByTestId("settings-industry-checkbox-pools").checked)
      .toBe(true);
    expect(screen.getByTestId("settings-industry-checkbox-hvac").checked)
      .toBe(false);
  });

  it("toggling a checkbox PATCHes with the updated array in canonical enum order", async () => {
    getSpy.mockResolvedValue({ industries: ["pools"] });
    patchSpy.mockResolvedValue({});
    render(<IndustriesSettings />);
    await waitFor(() =>
      screen.getByTestId("settings-industry-checkbox-hvac")
    );
    fireEvent.click(screen.getByTestId("settings-industry-checkbox-hvac"));

    await waitFor(() => expect(patchSpy).toHaveBeenCalledTimes(1));
    const [path, body] = patchSpy.mock.calls[0];
    expect(path).toBe("/tenants/mine/settings");
    // Canonical order: "pools" is index 0, "hvac" is index 2.
    expect(body).toEqual({ industries: ["pools", "hvac"] });
  });

  it("shows the success toast after a save", async () => {
    getSpy.mockResolvedValue({ industries: [] });
    patchSpy.mockResolvedValue({});
    render(<IndustriesSettings />);
    await waitFor(() =>
      screen.getByTestId("settings-industry-checkbox-plumbing")
    );
    fireEvent.click(screen.getByTestId("settings-industry-checkbox-plumbing"));
    await waitFor(() =>
      expect(screen.getByTestId("settings-industry-save-toast").textContent)
        .toContain("Saved")
    );
  });

  it("rolls back and shows an error toast on 422", async () => {
    getSpy.mockResolvedValue({ industries: ["pools"] });
    patchSpy.mockRejectedValue(new Error("422"));
    render(<IndustriesSettings />);
    await waitFor(() =>
      screen.getByTestId("settings-industry-checkbox-hvac")
    );
    fireEvent.click(screen.getByTestId("settings-industry-checkbox-hvac"));
    await waitFor(() =>
      expect(screen.getByTestId("settings-industry-save-toast").textContent)
        .toContain("Failed to save")
    );
    // Roll back: hvac unchecked, pools still checked.
    expect(screen.getByTestId("settings-industry-checkbox-hvac").checked)
      .toBe(false);
    expect(screen.getByTestId("settings-industry-checkbox-pools").checked)
      .toBe(true);
  });
});


describe("Multi-industry Phase B · TenantIndustryBadges", () => {
  beforeEach(() => {
    getSpy.mockReset();
    invalidateIndustries();
  });

  it("renders one chip per selected industry", async () => {
    getSpy.mockResolvedValue({ industries: ["pools", "hvac"] });
    render(<TenantIndustryBadges />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-industry-badge-pools")).toBeInTheDocument()
    );
    expect(screen.getByTestId("tenant-industry-badge-hvac")).toBeInTheDocument();
  });

  it("renders nothing when the tenant has no industries", async () => {
    getSpy.mockResolvedValue({ industries: [] });
    render(<TenantIndustryBadges />);
    // Wait a tick for the fetch to settle; nothing renders.
    await waitFor(() =>
      expect(screen.queryByTestId("tenant-industry-badges")).toBeNull()
    );
  });

  it("shows first 3 + overflow chip when >4 industries selected", async () => {
    getSpy.mockResolvedValue({
      industries: ["pools", "hvac", "plumbing", "electrical", "roofing"],
    });
    render(<TenantIndustryBadges />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-industry-badge-pools")).toBeInTheDocument()
    );
    expect(screen.getByTestId("tenant-industry-badge-hvac")).toBeInTheDocument();
    expect(screen.getByTestId("tenant-industry-badge-plumbing")).toBeInTheDocument();
    // 4th + 5th collapsed behind the overflow chip.
    expect(screen.queryByTestId("tenant-industry-badge-electrical")).toBeNull();
    expect(screen.queryByTestId("tenant-industry-badge-roofing")).toBeNull();
    const overflow = screen.getByTestId("tenant-industry-badge-overflow");
    expect(overflow.textContent).toContain("+2");

    // Clicking the overflow chip reveals the rest.
    fireEvent.click(overflow);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-industry-badge-electrical"))
        .toBeInTheDocument()
    );
    expect(screen.getByTestId("tenant-industry-badge-roofing"))
      .toBeInTheDocument();
    expect(screen.queryByTestId("tenant-industry-badge-overflow")).toBeNull();
  });

  it("shows all chips inline when total ≤ 4", async () => {
    getSpy.mockResolvedValue({
      industries: ["pools", "hvac", "plumbing", "electrical"],
    });
    render(<TenantIndustryBadges />);
    await waitFor(() =>
      expect(screen.getByTestId("tenant-industry-badge-pools")).toBeInTheDocument()
    );
    expect(screen.getByTestId("tenant-industry-badge-hvac")).toBeInTheDocument();
    expect(screen.getByTestId("tenant-industry-badge-plumbing")).toBeInTheDocument();
    expect(screen.getByTestId("tenant-industry-badge-electrical")).toBeInTheDocument();
    expect(screen.queryByTestId("tenant-industry-badge-overflow")).toBeNull();
  });
});
