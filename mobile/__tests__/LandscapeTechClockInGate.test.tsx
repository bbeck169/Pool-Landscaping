/**
 * Tests for LandscapeTechClockInGate — mobile parity for web f5dd1eb0a.
 *
 * 1. Landscape tech + not clocked in → Clock In button renders, children do NOT.
 * 2. Landscape tech + clocked in → children render.
 * 3. Pool tech → children render (gate bypassed).
 * 4. Admin → children render (gate bypassed).
 * 5. Clock In button press → POST with GPS; on 200 → refetch & children render.
 * 6. GPS denied → POST fires with geo_denied: true.
 */
import React from "react";
import { Text } from "react-native";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";
import LandscapeTechClockInGate from "@/src/components/LandscapeTechClockInGate";
import { isLandscapeTech, isPoolTech } from "@/src/utils/clockInGate";

/* ── Mocks ─────────────────────────────────────────────────────── */

// Auth mock — set per test
let mockUser: any = null;
jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUser, loading: false }),
}));

// API mock
const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...args: any[]) => mockApiGet(...args),
    post: (...args: any[]) => mockApiPost(...args),
  },
}));

// expo-location mock
const mockRequestPerms = jest.fn();
const mockGetCurrentPosition = jest.fn();
jest.mock("expo-location", () => ({
  requestForegroundPermissionsAsync: (...args: any[]) => mockRequestPerms(...args),
  getCurrentPositionAsync: (...args: any[]) => mockGetCurrentPosition(...args),
  Accuracy: { Balanced: 3 },
}));

// Theme mock (minimal)
jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#1B1F5C",
    brandTertiary: "#E8E8FF",
    surface: "#FFFFFF",
    surfaceSecondary: "#F5F5F5",
    onSurface: "#111111",
    muted: "#888888",
    border: "#E0E0E0",
  },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 18, xl: 22 },
}));

/* ── Helpers ───────────────────────────────────────────────────── */

const ChildContent = () => <Text testID="child-content">Dashboard</Text>;

function renderGate() {
  return render(
    <LandscapeTechClockInGate>
      <ChildContent />
    </LandscapeTechClockInGate>,
  );
}

/* ── Setup ─────────────────────────────────────────────────────── */
beforeEach(() => {
  jest.clearAllMocks();
  mockUser = null;
  mockApiGet.mockResolvedValue({ clocked_in: false });
  mockApiPost.mockResolvedValue({ ok: true });
  mockRequestPerms.mockResolvedValue({ status: "granted" });
  mockGetCurrentPosition.mockResolvedValue({
    coords: { latitude: 33.65, longitude: -112.01, accuracy: 12 },
  });
});

/* ── Tests ──────────────────────────────────────────────────────── */

describe("LandscapeTechClockInGate", () => {
  it("1. landscape tech + not clocked in → shows gate, hides children", async () => {
    mockUser = { id: "u1", role: "technician", department: "landscaping", name: "Luis" };
    mockApiGet.mockResolvedValue({ clocked_in: false });

    const { getByTestId, queryByTestId } = renderGate();

    await waitFor(() => {
      expect(getByTestId("landscape-clock-gate-in-btn")).toBeTruthy();
    });
    expect(queryByTestId("child-content")).toBeNull();
  });

  it("2. landscape tech + clocked in → children render", async () => {
    mockUser = { id: "u2", role: "technician", department: "landscaping", name: "Luis" };
    mockApiGet.mockResolvedValue({ clocked_in: true });

    const { getByTestId, queryByTestId } = renderGate();

    await waitFor(() => {
      expect(getByTestId("child-content")).toBeTruthy();
    });
    // Verify gate button is not shown
    expect(queryByTestId("landscape-clock-gate-in-btn")).toBeNull();
  });

  it("3. pool tech → children render (gate bypassed)", async () => {
    mockUser = { id: "u3", role: "technician", department: "pool", name: "Mike" };

    const { getByTestId, queryByTestId } = renderGate();
    expect(getByTestId("child-content")).toBeTruthy();
    expect(queryByTestId("landscape-clock-gate-in-btn")).toBeNull();
  });

  it("4. admin → children render (gate bypassed)", async () => {
    mockUser = { id: "u4", role: "admin", department: "landscaping", name: "Admin" };

    const { getByTestId, queryByTestId } = renderGate();
    expect(getByTestId("child-content")).toBeTruthy();
    expect(queryByTestId("landscape-clock-gate-in-btn")).toBeNull();
  });

  it("5. clock-in press → POST with GPS; on success → children render", async () => {
    mockUser = { id: "u5", role: "technician", department: "both", name: "Carlos" };
    // First call: not clocked in. After punch: clocked in.
    mockApiGet
      .mockResolvedValueOnce({ clocked_in: false })
      .mockResolvedValueOnce({ clocked_in: true });

    const { getByTestId } = renderGate();

    await waitFor(() => {
      expect(getByTestId("landscape-clock-gate-in-btn")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(getByTestId("landscape-clock-gate-in-btn"));
    });

    // Verify POST was called with correct body
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/timeclock/punch", {
        punch_type: "in",
        lat: 33.65,
        lng: -112.01,
        accuracy_m: 12,
        source: "mobile",
        geo_denied: false,
      });
    });

    // After refetch, children should render
    await waitFor(() => {
      expect(getByTestId("child-content")).toBeTruthy();
    });
  });

  it("6. GPS denied → POST fires with geo_denied: true", async () => {
    mockUser = { id: "u6", role: "technician", department: "landscaper", name: "Jose" };
    mockApiGet
      .mockResolvedValueOnce({ clocked_in: false })
      .mockResolvedValueOnce({ clocked_in: true });
    // GPS permission denied
    mockRequestPerms.mockResolvedValue({ status: "denied" });

    const { getByTestId } = renderGate();

    await waitFor(() => {
      expect(getByTestId("landscape-clock-gate-in-btn")).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(getByTestId("landscape-clock-gate-in-btn"));
    });

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/timeclock/punch", {
        punch_type: "in",
        lat: null,
        lng: null,
        accuracy_m: null,
        source: "mobile",
        geo_denied: true,
      });
    });
  });

  /* ── Hotfix · pool techs bypass the gate ─────────────────────── */
  it.each(["pool_tech", "pool", "Pool Tech", "pool-tech", " POOL_TECH "])(
    "7. pool tech (department=%j) → children render, no mine-status probe",
    async (department) => {
      mockUser = { id: "u7", role: "technician", department, name: "Mike" };
      mockApiGet.mockResolvedValue({ clocked_in: false });

      const { getByTestId, queryByTestId } = renderGate();
      expect(getByTestId("child-content")).toBeTruthy();
      expect(queryByTestId("landscape-clock-gate")).toBeNull();
      await act(async () => {});
      expect(mockApiGet).not.toHaveBeenCalled();
      expect(queryByTestId("landscape-clock-gate-in-btn")).toBeNull();
    },
  );

  it("8. cross-trained (department=both) + not clocked in → still gated", async () => {
    mockUser = { id: "u8", role: "technician", department: "both", name: "Carlos" };
    mockApiGet.mockResolvedValue({ clocked_in: false });

    const { getByTestId, queryByTestId } = renderGate();
    await waitFor(() => {
      expect(getByTestId("landscape-clock-gate-in-btn")).toBeTruthy();
    });
    expect(queryByTestId("child-content")).toBeNull();
    expect(mockApiGet).toHaveBeenCalledWith("/timeclock/mine-status");
  });

  it("9. landscape dept normalisation (\"Landscaping \") → gated", async () => {
    mockUser = { id: "u9", role: "technician", department: "Landscaping ", name: "Luis" };
    mockApiGet.mockResolvedValue({ clocked_in: false });

    const { getByTestId } = renderGate();
    await waitFor(() => {
      expect(getByTestId("landscape-clock-gate-in-btn")).toBeTruthy();
    });
  });
});

describe("clockInGate discriminator (users.role + users.department)", () => {
  it("isPoolTech: pool-family depts for technicians only", () => {
    expect(isPoolTech({ role: "technician", department: "pool_tech" })).toBe(true);
    expect(isPoolTech({ role: "technician", department: "Pool Technician" })).toBe(true);
    expect(isPoolTech({ role: "admin", department: "pool_tech" })).toBe(false);
    expect(isPoolTech({ role: "technician", department: "landscaping" })).toBe(false);
    expect(isPoolTech({ role: "technician", department: "both" })).toBe(false);
    expect(isPoolTech(null)).toBe(false);
  });

  it("isLandscapeTech: pool never gated; landscape family + both gated; others untouched", () => {
    expect(isLandscapeTech({ role: "technician", department: "pool_tech" })).toBe(false);
    expect(isLandscapeTech({ role: "technician", department: "pool" })).toBe(false);
    expect(isLandscapeTech({ role: "technician", department: "landscaping" })).toBe(true);
    expect(isLandscapeTech({ role: "technician", department: "landscape_tech" })).toBe(true);
    expect(isLandscapeTech({ role: "technician", department: "landscaper" })).toBe(true);
    expect(isLandscapeTech({ role: "technician", department: "both" })).toBe(true);
    expect(isLandscapeTech({ role: "admin", department: "landscaping" })).toBe(false);
    expect(isLandscapeTech({ role: "technician", department: undefined })).toBe(false);
    expect(isLandscapeTech({ role: "technician", department: "north" })).toBe(false);
  });
});
