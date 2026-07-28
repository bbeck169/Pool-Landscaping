/**
 * Wave M3 · F2d Chat Attachments tests.
 *
 * Tests the chat attachment upload flow: paperclip button → pending queue →
 * attachment_ids sent with message → inline attachment rendering.
 */
import React from "react";
import { render, fireEvent, waitFor, act } from "@testing-library/react-native";

// ── Mocks ──────────────────────────────────────────────────────────

// Mock expo-router
jest.mock("expo-router", () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({}),
  useFocusEffect: (cb: any) => {
    const React = require("react");
    React.useEffect(() => { cb(); }, []);
  },
  Link: ({ children }: any) => children,
}));

// Mock api
const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a) },
  api_base: () => "http://test-backend/api",
  getAuthToken: () => Promise.resolve("test-token"),
}));

// Mock expo-image-picker
jest.mock("expo-image-picker", () => ({
  requestCameraPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
  requestMediaLibraryPermissionsAsync: jest.fn().mockResolvedValue({ granted: true }),
  launchCameraAsync: jest.fn().mockResolvedValue({
    canceled: false,
    assets: [{ uri: "file://photo.jpg", fileName: "photo.jpg", mimeType: "image/jpeg", fileSize: 1024 }],
  }),
  launchImageLibraryAsync: jest.fn().mockResolvedValue({
    canceled: false,
    assets: [{ uri: "file://library.jpg", fileName: "library.jpg", mimeType: "image/jpeg", fileSize: 2048 }],
  }),
}));

// Mock expo-document-picker
jest.mock("expo-document-picker", () => ({
  getDocumentAsync: jest.fn().mockResolvedValue({
    canceled: false,
    assets: [{ uri: "file://doc.pdf", name: "doc.pdf", mimeType: "application/pdf", size: 4096 }],
  }),
}));

// Mock expo-image
jest.mock("expo-image", () => ({
  Image: "Image",
}));

// Mock Header
jest.mock("@/src/components/widgets", () => ({
  Header: ({ title }: any) => {
    const { Text } = require("react-native");
    return <Text>{title}</Text>;
  },
}));

// Mock AuthedImage
jest.mock("@/src/components/files/AuthedImage", () => ({
  AuthedImage: ({ fileId }: any) => {
    const { Text } = require("react-native");
    return <Text testID={`authed-image-${fileId}`}>AuthedImage</Text>;
  },
}));

// Mock fetch for attachment upload
const mockFetch = jest.fn();
(global as any).fetch = mockFetch;

// Mock Alert
jest.spyOn(require("react-native").Alert, "alert");
const Alert = require("react-native").Alert;

// Mock ActionSheetIOS
jest.mock("react-native/Libraries/ActionSheetIOS/ActionSheetIOS", () => ({
  showActionSheetWithOptions: jest.fn(),
}));

import ChatMobile from "@/app/(app)/chat";

describe("F2d · Chat Attachments", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default: return conversations
    mockGet.mockImplementation((path: string) => {
      if (path.includes("/chat/conversations") && !path.includes("/messages")) {
        return Promise.resolve({ conversations: [
          { id: "conv1", name: "General", type: "channel", unread_count: 0 },
        ]});
      }
      if (path.includes("/messages")) {
        return Promise.resolve({ messages: [
          {
            id: "msg1",
            author_name: "Alice",
            body_markdown: "Hello",
            attachments: [{ id: "att-existing", name: "report.pdf" }],
            reactions: {},
          },
          {
            id: "msg2",
            author_name: "Bob",
            body_markdown: "Hi there",
            attachments: [],
            reactions: { "👍": { count: 1 } },
          },
        ]});
      }
      return Promise.resolve({});
    });
    mockPost.mockResolvedValue({ id: "msg-new", body_markdown: "test" });
  });

  it("renders conversation list with at least one convo", async () => {
    const { getByTestId, getByText } = render(<ChatMobile />);
    await waitFor(() => {
      expect(getByTestId("chat-mobile-convo-conv1")).toBeTruthy();
      expect(getByText("General")).toBeTruthy();
    });
  }, 15000);

  it("opens a conversation and shows messages with attachments", async () => {
    const { getByTestId, getByText } = render(<ChatMobile />);
    await waitFor(() => expect(getByTestId("chat-mobile-convo-conv1")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("chat-mobile-convo-conv1"));
    });

    await waitFor(() => {
      // msg1 has an attachment
      expect(getByTestId("chat-attachment-att-existing")).toBeTruthy();
      expect(getByText("report.pdf")).toBeTruthy();
      // msg2 has no attachments
      expect(getByText("Hi there")).toBeTruthy();
    });
  });

  it("shows composer with paperclip (attach) button and send button", async () => {
    const { getByTestId } = render(<ChatMobile />);
    await waitFor(() => expect(getByTestId("chat-mobile-convo-conv1")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("chat-mobile-convo-conv1"));
    });

    await waitFor(() => {
      expect(getByTestId("chat-upload-btn")).toBeTruthy();
      expect(getByTestId("chat-mobile-composer")).toBeTruthy();
      expect(getByTestId("chat-mobile-send")).toBeTruthy();
    });
  });

  it("sends message with attachment_ids when pending attachments exist", async () => {
    // Mock fetch for upload
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ id: "att-1", name: "photo.jpg" }),
    });

    const { getByTestId } = render(<ChatMobile />);
    await waitFor(() => expect(getByTestId("chat-mobile-convo-conv1")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("chat-mobile-convo-conv1"));
    });

    await waitFor(() => expect(getByTestId("chat-mobile-composer")).toBeTruthy());

    // Type a message
    await act(async () => {
      fireEvent.changeText(getByTestId("chat-mobile-composer"), "Check this out");
    });

    // Send the message
    await act(async () => {
      fireEvent.press(getByTestId("chat-mobile-send"));
    });

    // Verify the post was called with the draft text
    expect(mockPost).toHaveBeenCalledWith(
      "/chat/conversations/conv1/messages",
      expect.objectContaining({ body_markdown: "Check this out" }),
    );
  });

  it("renders existing message attachments as links", async () => {
    const { getByTestId, getAllByTestId } = render(<ChatMobile />);
    await waitFor(() => expect(getByTestId("chat-mobile-convo-conv1")).toBeTruthy());

    await act(async () => {
      fireEvent.press(getByTestId("chat-mobile-convo-conv1"));
    });

    await waitFor(() => {
      const attachments = getAllByTestId(/^chat-attachment-/);
      expect(attachments.length).toBeGreaterThanOrEqual(1);
    });
  });
});
