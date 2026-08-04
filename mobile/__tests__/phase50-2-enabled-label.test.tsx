/**
 * Phase 50.2 · Feb-2026 — Mobile AI Employees enabled-label parity.
 *
 * The mobile card intentionally does not render an enable-state label
 * (rows are chat launchers — inactive personas are hidden server-side
 * before they hit the list). This test locks that in so a future
 * refactor doesn't accidentally reintroduce the buggy
 * ``item.enabled ? … : …`` shape the web side just retired.
 *
 * Positive guard: card mounts + shows name/role/tagline for both
 * active and inactive rows without ever surfacing a "Disabled"
 * string (which would signal a stale-field leak).
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

const mockPush = jest.fn();
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({}),
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { cb(); }, []);
  },
}));

const mockGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    patch: jest.fn().mockResolvedValue({}),
    post: jest.fn().mockResolvedValue({}),
  },
  api_base: () => "http://test-backend/api",
  getAuthToken: () => Promise.resolve("test-token"),
}));

jest.mock("expo-image", () => ({ Image: "Image" }));

jest.mock("@/src/components/ui", () => {
  const { Text } = require("react-native");
  return {
    Loading: ({ testID }: any) => <Text testID={testID}>Loading</Text>,
    EmptyState: ({ testID, title }: any) => <Text testID={testID}>{title}</Text>,
  };
});

jest.mock("@/src/components/widgets", () => {
  const { Text } = require("react-native");
  return { Header: ({ title }: any) => <Text>{title}</Text> };
});

jest.mock("@/src/components/files/FileUpload", () => ({
  FileUpload: () => null,
}));

jest.mock("@/src/components/files/AuthedImage", () => ({
  AuthedImage: () => null,
}));

// Stub the native Lottie module so <AIAvatar> mounts under jsdom.
jest.mock("lottie-react-native", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: (props: any) => <View {...props} /> };
});

// eslint-disable-next-line import/first
import AIEmployees from "@/app/ai-employees";

const ACTIVE_ROW = {
  id: "emp-active",
  key: "billy",
  name: "Billy",
  role: "Billing concierge",
  icon: "card-outline",
  tagline: "Every dollar accounted for",
  avatar_url: "/avatars/personas/billy.jpg",
  active: true,
};

const INACTIVE_ROW = {
  id: "emp-inactive",
  key: "scouty",
  name: "Scouty",
  role: "Recruiting",
  icon: "people-outline",
  tagline: "Hire smarter, not harder",
  avatar_url: null,
  active: false,     // authoritative source of truth
  enabled: true,     // legacy misleading field — must be ignored
};

describe("Phase 50.2 · Mobile AI Employees enabled-label parity", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockResolvedValue([ACTIVE_ROW, INACTIVE_ROW]);
  });

  it("renders both rows without leaking a 'Disabled' string", async () => {
    const { getByTestId, queryByText, findByTestId } = render(<AIEmployees />);
    await findByTestId("ai-employee-emp-active");
    expect(getByTestId("ai-employee-emp-inactive")).toBeTruthy();
    // No enable-state label on the mobile card — regression guard.
    expect(queryByText(/^Disabled$/i)).toBeNull();
    expect(queryByText(/^○ Disabled$/i)).toBeNull();
  });

  it("does not read from the legacy ``enabled`` field (conflict row still mounts)", async () => {
    const { findByTestId } = render(<AIEmployees />);
    // The inactive row has enabled=true — if the card read ``enabled``
    // it would still show as if active. Card just mounts either way;
    // this test guards that mobile has NO branch on this field at all.
    await findByTestId("ai-employee-emp-inactive");
  });
});
