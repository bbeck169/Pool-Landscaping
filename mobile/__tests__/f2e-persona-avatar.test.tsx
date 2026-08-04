/**
 * Wave M3 · F2e Persona Avatar Upload tests.
 *
 * Tests the avatar upload modal on the AI Employees list:
 * camera overlay button → modal with FileUpload → PATCH avatar_url.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

// ── Mocks ──────────────────────────────────────────────────────────

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
const mockPatch = jest.fn();
jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockGet(...a),
    patch: (...a: any[]) => mockPatch(...a),
    post: jest.fn().mockResolvedValue({}),
  },
  api_base: () => "http://test-backend/api",
  getAuthToken: () => Promise.resolve("test-token"),
}));

jest.mock("expo-image", () => ({
  Image: "Image",
}));

jest.mock("@/src/components/ui", () => ({
  Loading: ({ testID }: any) => {
    const { Text } = require("react-native");
    return <Text testID={testID}>Loading</Text>;
  },
  EmptyState: ({ testID, title }: any) => {
    const { Text } = require("react-native");
    return <Text testID={testID}>{title}</Text>;
  },
}));

jest.mock("@/src/components/widgets", () => ({
  Header: ({ title }: any) => {
    const { Text } = require("react-native");
    return <Text>{title}</Text>;
  },
}));

jest.mock("@/src/components/files/FileUpload", () => ({
  FileUpload: ({ onUploaded, purpose, disabled }: any) => {
    const { Pressable, Text } = require("react-native");
    return (
      <Pressable
        testID="mock-file-upload"
        onPress={() => onUploaded?.({ id: "file-abc", url: "/api/files/file-abc/download" })}
        disabled={disabled}
      >
        <Text>FileUpload ({purpose})</Text>
      </Pressable>
    );
  },
}));

jest.mock("@/src/components/files/AuthedImage", () => ({
  AuthedImage: ({ fileId }: any) => {
    const { Text } = require("react-native");
    return <Text testID={`authed-image-${fileId}`}>AuthedImage</Text>;
  },
}));

// Phase 50 / 50.1 · Feb-2026 — ``lottie-react-native`` is a native
// module and can't load under jest without a dev-client bridge.
// Stub it here so the AI-employees list can mount inside jsdom.
jest.mock("lottie-react-native", () => {
  const { View } = require("react-native");
  return { __esModule: true, default: (props: any) => <View {...props} /> };
});

jest.spyOn(require("react-native").Alert, "alert");
const Alert = require("react-native").Alert;

import AIEmployees from "@/app/ai-employees";

const MOCK_EMPLOYEES = [
  { id: "emp1", key: "casey", name: "Casey", role: "Directories", icon: "compass-outline", tagline: "Find businesses", avatar_url: null },
  { id: "emp2", key: "emmie", name: "Emmie", role: "Email marketing", icon: "mail-outline", tagline: "Email campaigns", avatar_url: "/api/files/existing-file/download" },
];

describe("F2e · Persona Avatar Upload", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockGet.mockResolvedValue(MOCK_EMPLOYEES);
    mockPatch.mockResolvedValue({});
  });

  it("renders AI employees list with camera overlay buttons", async () => {
    const { getByTestId } = render(<AIEmployees />);
    await waitFor(() => {
      expect(getByTestId("ai-employee-emp1")).toBeTruthy();
      expect(getByTestId("persona-avatar-upload-casey")).toBeTruthy();
      expect(getByTestId("persona-avatar-upload-emmie")).toBeTruthy();
    });
  }, 15000);

  it("opens avatar upload modal on camera press", async () => {
    const { getByTestId, getByText, getAllByText } = render(<AIEmployees />);
    await waitFor(() => expect(getByTestId("persona-avatar-upload-casey")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("persona-avatar-upload-casey"));
    });

    await waitFor(() => {
      // "Casey" appears in both the list and the modal, so use getAllByText
      const caseyElements = getAllByText("Casey");
      expect(caseyElements.length).toBeGreaterThanOrEqual(2);
      expect(getByText("Upload a new avatar image")).toBeTruthy();
      expect(getByTestId("mock-file-upload")).toBeTruthy();
    });
  });

  it("PATCHes avatar_url on upload success", async () => {
    const { getByTestId } = render(<AIEmployees />);
    await waitFor(() => expect(getByTestId("persona-avatar-upload-casey")).toBeTruthy());

    // Open modal
    await act(async () => {
      fireEvent.press(getByTestId("persona-avatar-upload-casey"));
    });

    await waitFor(() => expect(getByTestId("mock-file-upload")).toBeTruthy());

    // Trigger upload callback
    await act(async () => {
      fireEvent.press(getByTestId("mock-file-upload"));
    });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        "/ai-employees/emp1",
        { avatar_url: "/api/files/file-abc/download" },
      );
    });
  });

  it("resets avatar to default on reset press", async () => {
    const { getByTestId } = render(<AIEmployees />);
    await waitFor(() => expect(getByTestId("persona-avatar-upload-casey")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("persona-avatar-upload-casey"));
    });

    await waitFor(() => expect(getByTestId("persona-avatar-reset")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("persona-avatar-reset"));
    });

    await waitFor(() => {
      expect(mockPatch).toHaveBeenCalledWith(
        "/ai-employees/emp1",
        { avatar_url: "/avatars/personas/casey.jpg" },
      );
    });
  });

  it("renders an <AIAvatar> for personas with existing avatar_url", async () => {
    // Phase 50 / 50.1 · Feb-2026 — the row-level ``<AuthedImage>`` was
    // replaced by ``<AIAvatar>`` (Lottie backdrop + optional image
    // overlay). ``<AuthedImage>`` still appears inside the upload
    // modal, but the list row now renders the animated avatar. This
    // test guards that every persona (with or without an
    // ``avatar_url``) gets its own AIAvatar testID.
    const { getByTestId } = render(<AIEmployees />);
    await waitFor(() => {
      expect(getByTestId("ai-lottie-avatar-casey")).toBeTruthy();
      expect(getByTestId("ai-lottie-avatar-emmie")).toBeTruthy();
    });
  });

  it("closes modal on close button press", async () => {
    const { getByTestId, queryByText } = render(<AIEmployees />);
    await waitFor(() => expect(getByTestId("persona-avatar-upload-casey")).toBeTruthy());

    // Open modal
    await act(async () => {
      fireEvent.press(getByTestId("persona-avatar-upload-casey"));
    });

    await waitFor(() => expect(getByTestId("persona-avatar-close")).toBeTruthy());

    // Close modal
    await act(async () => {
      fireEvent.press(getByTestId("persona-avatar-close"));
    });

    await waitFor(() => {
      expect(queryByText("Upload a new avatar image")).toBeNull();
    });
  });
});
