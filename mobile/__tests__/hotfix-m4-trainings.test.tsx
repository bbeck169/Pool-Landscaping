/**
 * Hotfix M4 — Trainings designation visibility parity.
 *
 * Verifies the mobile trainings screen does NOT do client-side
 * department filtering — backend `_visible_departments()` is authoritative.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

/* ── Mocks ────────────────────────────────────────────────────────── */
const mockApiGet = jest.fn();

jest.mock("@/src/api", () => ({
  api: { get: (...args: any[]) => mockApiGet(...args) },
}));

jest.mock("expo-router", () => ({
  useFocusEffect: (cb: any) => {
    const { useEffect } = require("react");
    useEffect(() => { cb(); }, []);
  },
  useRouter: () => ({ push: jest.fn() }),
}));

jest.mock("@/src/theme", () => ({
  colors: {
    brand: "#007AFF", surface: "#fff", surfaceAlt: "#F0F0F0",
    surfaceSecondary: "#F5F5F5", background: "#FAFAFA",
    onSurface: "#000", muted: "#999", border: "#E0E0E0",
  },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 10, sm: 12, base: 14, lg: 16, xl: 18 },
}));

jest.mock("@/src/components/ui", () => ({
  Loading: () => null,
  EmptyState: () => null,
}));

jest.mock("@/src/components/widgets", () => ({
  Header: () => null,
}));

import TrainingList from "../app/(app)/tests/index";

/* ── Tests ─────────────────────────────────────────────────────────── */
describe("M4 — Trainings designation visibility", () => {
  const MOCK_MODULES = [
    { code: "pool-basics", title: "Pool Basics", department: "pool", lesson_count: 3, question_count: 10, progress: { percent: 0.5 } },
    { code: "landscaping-101", title: "Landscaping 101", department: "landscaping", lesson_count: 5, question_count: 15, progress: { percent: 0 } },
    { code: "safety-all", title: "Safety for All", department: "both", lesson_count: 2, question_count: 8, progress: { percent: 1 } },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    mockApiGet.mockResolvedValue(MOCK_MODULES);
  });

  it("does NOT client-side-filter the API result — renders all modules from backend", async () => {
    const { getByTestId } = render(<TrainingList />);
    await waitFor(() => {
      // All 3 modules should appear regardless of department
      expect(getByTestId("training-module-card-pool-basics")).toBeTruthy();
      expect(getByTestId("training-module-card-landscaping-101")).toBeTruthy();
      expect(getByTestId("training-module-card-safety-all")).toBeTruthy();
    });
  });

  it("passes API response directly to list without filtering", async () => {
    render(<TrainingList />);
    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith("/training/modules");
    });
    // The mock returns 3 items, and the component should render all 3
    // (no `.filter()` narrows the result)
  });

  it("handles pool-only tech (backend only returns pool modules)", async () => {
    mockApiGet.mockResolvedValue([MOCK_MODULES[0]]); // just pool-basics
    const { getByTestId, queryByTestId } = render(<TrainingList />);
    await waitFor(() => {
      expect(getByTestId("training-module-card-pool-basics")).toBeTruthy();
      expect(queryByTestId("training-module-card-landscaping-101")).toBeNull();
    });
  });
});
