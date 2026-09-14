/**
 * Multi-industry Phase D — Mobile tests.
 *
 * 7 cases:
 *   1. Config: INDUSTRIES has 25 entries
 *   2. Config: labels match slugs
 *   3. Config: isValidIndustry checks
 *   4. Hook: cold-mount safe defaults
 *   5. NavGating: filterNavByIndustries hides pool-tagged entry on landscape-only
 *   6. NavGating: fail-open on empty industries
 *   7. Badges: overflow renders "+N more" chip
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

// ── Config tests (pure, no mocks needed) ──────────────────────────

import { INDUSTRIES, INDUSTRY_LABELS, DEFAULT_INDUSTRY, isValidIndustry } from "@/src/config/industries";

describe("industries config", () => {
  it("has exactly 25 industries", () => {
    expect(INDUSTRIES).toHaveLength(25);
  });

  it("every slug has a label", () => {
    for (const slug of INDUSTRIES) {
      expect(INDUSTRY_LABELS[slug]).toBeTruthy();
    }
  });

  it("isValidIndustry returns true for known slugs, false for unknowns", () => {
    expect(isValidIndustry("pools")).toBe(true);
    expect(isValidIndustry("landscaping")).toBe(true);
    expect(isValidIndustry("fake_industry")).toBe(false);
    expect(isValidIndustry("")).toBe(false);
  });

  it("default industry is pools", () => {
    expect(DEFAULT_INDUSTRY).toBe("pools");
  });
});

// ── Nav gating tests ──────────────────────────────────────────────

import { filterNavByIndustries, type NavEntry } from "@/src/nav/adminNav";

const POOL_ENTRY: NavEntry = {
  label: "Pool Service", route: "/pool-service", icon: "water-outline",
  tier: "t1", industry: "pools", testID: "drawer-nav-pool-service",
};
const LANDSCAPE_ENTRY: NavEntry = {
  label: "Landscape AI", route: "/landscape", icon: "leaf-outline",
  tier: "t1", industry: "landscaping", testID: "drawer-nav-landscape",
};
const UNTAGGED: NavEntry = {
  label: "Schedule", route: "/schedule", icon: "calendar-outline",
  tier: "t1", testID: "drawer-nav-schedule",
};

describe("filterNavByIndustries", () => {
  it("hides pool-tagged entry when tenant is landscape-only", () => {
    const result = filterNavByIndustries(
      [POOL_ENTRY, LANDSCAPE_ENTRY, UNTAGGED],
      ["landscaping"],
    );
    expect(result).toHaveLength(2);
    expect(result.map((e) => e.testID)).toEqual([
      "drawer-nav-landscape",
      "drawer-nav-schedule",
    ]);
  });

  it("shows both tagged entries for multi-industry tenant", () => {
    const result = filterNavByIndustries(
      [POOL_ENTRY, LANDSCAPE_ENTRY, UNTAGGED],
      ["pools", "landscaping"],
    );
    expect(result).toHaveLength(3);
  });

  it("fail-open: empty industries array returns all entries", () => {
    const result = filterNavByIndustries(
      [POOL_ENTRY, LANDSCAPE_ENTRY, UNTAGGED],
      [],
    );
    expect(result).toHaveLength(3);
  });

  it("fail-open: non-array treated as empty", () => {
    const result = filterNavByIndustries(
      [POOL_ENTRY, LANDSCAPE_ENTRY, UNTAGGED],
      null as any,
    );
    expect(result).toHaveLength(3);
  });
});

// ── Badge overflow test ───────────────────────────────────────────

jest.mock("@/src/hooks/useIndustries", () => ({
  useIndustries: () => ({
    industries: ["pools", "landscaping", "hvac", "plumbing", "electrical"],
    hasIndustry: (s: string) => ["pools", "landscaping", "hvac", "plumbing", "electrical"].includes(s),
    labels: {
      pools: "Pools", landscaping: "Landscaping", hvac: "HVAC",
      plumbing: "Plumbing", electrical: "Electrical",
    },
    loaded: true,
  }),
  invalidateIndustries: jest.fn(),
}));

import TenantIndustryBadges from "@/src/components/tenant/TenantIndustryBadges";

describe("TenantIndustryBadges", () => {
  it("renders first 3 + overflow chip when >4 industries", () => {
    const { getByTestId, queryByTestId } = render(<TenantIndustryBadges max={4} />);
    // Should show 3 chips + overflow
    expect(getByTestId("tenant-industry-badge-pools")).toBeTruthy();
    expect(getByTestId("tenant-industry-badge-landscaping")).toBeTruthy();
    expect(getByTestId("tenant-industry-badge-hvac")).toBeTruthy();
    // 4th and 5th hidden
    expect(queryByTestId("tenant-industry-badge-plumbing")).toBeNull();
    expect(queryByTestId("tenant-industry-badge-electrical")).toBeNull();
    // Overflow chip
    expect(getByTestId("tenant-industry-badge-overflow")).toBeTruthy();
  });

  it("renders all chips inline when ≤ max", () => {
    const { getByTestId, queryByTestId } = render(<TenantIndustryBadges max={10} />);
    expect(getByTestId("tenant-industry-badge-pools")).toBeTruthy();
    expect(getByTestId("tenant-industry-badge-electrical")).toBeTruthy();
    expect(queryByTestId("tenant-industry-badge-overflow")).toBeNull();
  });
});
