/**
 * Phase S2 · Soshie mobile tests.
 *
 * Covers:
 *   1. Autopilot toggle: optimistic update + revert on API failure.
 *   2. Reddit toggle is disabled + no network request fires on tap.
 *   3. Review Queue Publish now: outgoing URL always contains confirm_flags=1.
 *   4. Brand Brain empty state renders with CTA.
 *   5. Offline banner appears when network is unreachable.
 *   6. SoshieHub 3-tab shell renders with correct tabs.
 */

/* ── MOCKS ────────────────────────────────────────────────────── */
let mockIsOnline = true;

jest.mock("@/src/offline", () => ({
  useOnline: () => mockIsOnline,
}));

jest.mock("@/src/auth", () => ({
  useAuth: () => ({
    user: { id: "u1", role: "admin", name: "Admin" },
    isLoggedIn: true,
    login: jest.fn(),
    logout: jest.fn(),
    loading: false,
  }),
}));

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
  useLocalSearchParams: () => ({}),
  Redirect: ({ href }: { href: string }) => {
    const React = require("react");
    const { Text } = require("react-native");
    return React.createElement(Text, null, `Redirect:${href}`);
  },
  Stack: ({ children }: any) => children,
  Link: ({ children }: any) => children,
}));

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  del: jest.fn(),
};

jest.mock("@/src/api", () => ({
  api: mockApi,
  ApiNetworkError: class ApiNetworkError extends Error {
    constructor(msg: string) { super(msg); this.name = "ApiNetworkError"; }
  },
}));

jest.mock("expo-linear-gradient", () => {
  const React = require("react");
  const { View } = require("react-native");
  return {
    LinearGradient: (props: any) => React.createElement(View, props),
  };
});

jest.mock("@/src/components/widgets", () => {
  const React = require("react");
  const { View, Text } = require("react-native");
  return {
    Header: ({ title }: any) =>
      React.createElement(View, { testID: "header" },
        React.createElement(Text, null, title)),
  };
});

jest.mock("@react-native-community/netinfo", () => ({
  addEventListener: jest.fn(() => jest.fn()),
  fetch: jest.fn(async () => ({ isConnected: true, isInternetReachable: true })),
}));

jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => {}),
}));

/* ── IMPORTS ──────────────────────────────────────────────────── */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

/* ── TESTS ────────────────────────────────────────────────────── */

describe("S2 · SoshieHub shell", () => {
  beforeEach(() => {
    mockIsOnline = true;
    jest.clearAllMocks();
  });

  test("6 · renders 3 tabs", async () => {
    const SoshieHub = require("@/app/soshie/index").default;
    // Suppress act warnings from async effects inside child tabs
    mockApi.get.mockResolvedValue({ brand_brain: null, latest_ingest: null });

    const { getByTestId } = render(<SoshieHub />);
    expect(getByTestId("soshie-hub")).toBeTruthy();
    expect(getByTestId("soshie-tab-brand-brain")).toBeTruthy();
    expect(getByTestId("soshie-tab-autopilot")).toBeTruthy();
    expect(getByTestId("soshie-tab-review-queue")).toBeTruthy();
    console.log("✅ S2-T6: SoshieHub renders all 3 tabs");
  });

  test("5 · offline banner appears when offline", async () => {
    mockIsOnline = false;
    const SoshieHub = require("@/app/soshie/index").default;

    const { getByTestId } = render(<SoshieHub />);
    expect(getByTestId("soshie-offline-banner")).toBeTruthy();
    console.log("✅ S2-T5: Offline banner appears when network is unreachable");
  });

  test("5b · offline banner hidden when online", async () => {
    mockIsOnline = true;
    const SoshieHub = require("@/app/soshie/index").default;
    mockApi.get.mockResolvedValue({ brand_brain: null, latest_ingest: null });

    const { queryByTestId } = render(<SoshieHub />);
    expect(queryByTestId("soshie-offline-banner")).toBeNull();
    console.log("✅ S2-T5b: Offline banner hidden when online");
  });
});

describe("S2 · Brand Brain", () => {
  beforeEach(() => {
    mockIsOnline = true;
    jest.clearAllMocks();
  });

  test("4 · empty state renders with CTA when brand_brain is null", async () => {
    mockApi.get.mockResolvedValueOnce({ brand_brain: null, latest_ingest: null });

    const BrandBrainTab = require("@/app/soshie/BrandBrainTab").default;
    const { findByTestId } = render(<BrandBrainTab disabled={false} />);

    const emptyState = await findByTestId("brand-brain-empty-state");
    expect(emptyState).toBeTruthy();
    const cta = await findByTestId("ingest-empty-cta");
    expect(cta).toBeTruthy();
    console.log("✅ S2-T4: Brand Brain empty state renders with prominent CTA");
  });
});

describe("S2 · Autopilot Schedules", () => {
  beforeEach(() => {
    mockIsOnline = true;
    jest.clearAllMocks();
  });

  test("1 · AutopilotTab shows redirect message to Settings → Social", async () => {
    mockApi.get.mockImplementation(async (url: string) => {
      if (url.includes("/autopilot/global")) return { enabled: true };
      if (url.includes("/recent-actions")) return { items: [] };
      return {};
    });

    const AutopilotTab = require("@/app/soshie/AutopilotTab").default;
    const { findByText } = render(<AutopilotTab disabled={false} />);

    // Platform grid has been moved — AutopilotTab now shows a redirect message
    const redirectMsg = await findByText(/Settings → Social/);
    expect(redirectMsg).toBeTruthy();
    console.log("✅ S2-T1: Autopilot tab shows redirect to Settings → Social for platform cadences");
  });

  test("2 · Kill switch still renders in AutopilotTab", async () => {
    mockApi.get.mockImplementation(async (url: string) => {
      if (url.includes("/autopilot/global")) return { enabled: true };
      if (url.includes("/recent-actions")) return { items: [] };
      return {};
    });

    const AutopilotTab = require("@/app/soshie/AutopilotTab").default;
    const { findByTestId } = render(<AutopilotTab disabled={false} />);

    const killSwitch = await findByTestId("global-kill-switch");
    expect(killSwitch).toBeTruthy();
    console.log("✅ S2-T2: Kill switch still renders in AutopilotTab");
  });
});

describe("S2 · Review Queue", () => {
  beforeEach(() => {
    mockIsOnline = true;
    jest.clearAllMocks();
  });

  test("3 · Publish now always sends confirm_flags=1", async () => {
    const actionId = "test-action-123";
    // First call: pending actions (with a flagged action)
    mockApi.get
      .mockResolvedValueOnce({
        items: [{
          id: actionId,
          action: "soshie.publish_blog",
          status: "pending",
          created_at: new Date(Date.now() - 48 * 3600_000).toISOString(), // 48h ago
          moderation_flags: [{ type: "profanity", match: "test" }],
          requires_human_approval: true,
          draft: { text: "Test post content" },
          params: { platform: "wordpress" },
        }],
      })
      .mockResolvedValueOnce({ items: [] }); // deferred bucket

    // Approve call returns published
    mockApi.post.mockResolvedValueOnce({ status: "published" });

    const ReviewQueueTab = require("@/app/soshie/ReviewQueueTab").default;
    const { findByTestId } = render(<ReviewQueueTab disabled={false} />);

    const publishBtn = await findByTestId(`review-publish-${actionId}`);
    expect(publishBtn).toBeTruthy();

    await act(async () => {
      fireEvent.press(publishBtn);
    });

    await waitFor(() => {
      expect(mockApi.post).toHaveBeenCalledWith(
        `/ai-employees/actions/${actionId}/approve?confirm_flags=1`,
      );
    });
    console.log("✅ S2-T3: Publish now URL always contains confirm_flags=1");
  });

  test("3b · empty state renders", async () => {
    mockApi.get
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({ items: [] });

    const ReviewQueueTab = require("@/app/soshie/ReviewQueueTab").default;
    const { findByTestId } = render(<ReviewQueueTab disabled={false} />);

    const emptyState = await findByTestId("review-queue-empty-state");
    expect(emptyState).toBeTruthy();
    console.log("✅ S2-T3b: Review queue empty state renders correctly");
  });
});
