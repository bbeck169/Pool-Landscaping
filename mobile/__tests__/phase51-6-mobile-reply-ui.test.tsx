/**
 * Phase 51.6 · Feb-2026 — Mobile walkie visible reply UI wiring.
 *
 * Locks the actual channel-screen render: bottom-sheet contains a
 * "Reply" option for permitted callers (alongside Pin/Unpin from
 * 51.5), the "Replying to X" banner renders after selecting Reply,
 * banner cancel clears state, and inline ``walkie-reply-preview``
 * block renders on reply rows (with deleted-parent placeholder
 * when applicable).
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

const mockApiGet = jest.fn();
const mockApiPost = jest.fn(async () => ({ ok: true }));
const mockApiDel = jest.fn(async () => ({ ok: true }));

let mockUserRole: any = { id: "u_admin", role: "admin", name: "Alice", department: "" };

jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: mockUserRole }) }));

jest.mock("@/src/api", () => ({
  api: {
    get: (...a: any[]) => mockApiGet(...a),
    post: (...a: any[]) => mockApiPost(...a),
    del: (...a: any[]) => mockApiDel(...a),
  },
  api_base: () => "https://example.test/api",
  getAuthToken: async () => "tok",
}));

jest.mock("expo-router", () => {
  const React = require("react");
  return {
    useLocalSearchParams: () => ({ channelId: "ch_ah" }),
    useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
    useFocusEffect: (fn: any) => React.useEffect(() => {
      const cleanup = fn();
      return typeof cleanup === "function" ? cleanup : undefined;
    }, []),
  };
});

jest.mock("expo-audio", () => ({
  useAudioPlayer: () => ({ play: jest.fn(), pause: jest.fn(), addListener: () => ({ remove: () => undefined }) }),
  useAudioRecorder: () => ({ prepareToRecordAsync: async () => undefined, record: jest.fn(), stop: async () => undefined, uri: "file:///tmp/c.m4a" }),
  useAudioRecorderState: () => ({ isRecording: false }),
  RecordingPresets: { HIGH_QUALITY: {} },
  requestRecordingPermissionsAsync: async () => ({ granted: true }),
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: () => <Text testID="stub-loading">Loading</Text>,
    EmptyState: ({ title, testID }: any) => (<View testID={testID || "stub-empty"}><Text>{title}</Text></View>),
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View, Text } = require("react-native");
  return { Header: ({ title }: any) => (<View testID="stub-header"><Text>{title}</Text></View>) };
});

jest.mock("@expo/vector-icons", () => {
  const { View } = require("react-native");
  return { Ionicons: (props: any) => <View {...props} testID={`icon-${props.name}`} /> };
});

const _store: Record<string, string> = {};
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn((k: string) => Promise.resolve(_store[k] ?? null)),
  setItem: jest.fn((k: string, v: string) => { _store[k] = v; return Promise.resolve(); }),
  removeItem: jest.fn((k: string) => { delete _store[k]; return Promise.resolve(); }),
  clear: jest.fn(() => { Object.keys(_store).forEach((k) => delete _store[k]); return Promise.resolve(); }),
}));

// eslint-disable-next-line import/first
import WalkieChannel from "@/app/walkie/[channelId]";

const CH = { id: "ch_ah", kind: "all_hands" };
const PARENT = {
  id: "m_parent", channel_id: "ch_ah", sender_user_id: "u_other", sender_name: "Bob",
  audio_url: "/files/a/download", duration_ms: 3400,
  created_at: "2026-02-07T10:00:00Z", is_pinned: false,
};
const REPLY_LIVE = {
  ...PARENT,
  id: "m_reply1", sender_user_id: "u_admin", sender_name: "Alice",
  audio_url: "/files/b/download", duration_ms: 2000,
  created_at: "2026-02-07T10:05:00Z",
  reply_to_message_id: "m_parent",
  reply_preview: { id: "m_parent", sender_display_name: "Bob", duration_ms: 3400, deleted: false },
};
const REPLY_DEAD = {
  ...PARENT,
  id: "m_reply2", sender_user_id: "u_admin", sender_name: "Alice",
  audio_url: "/files/c/download", duration_ms: 1500,
  created_at: "2026-02-07T10:10:00Z",
  reply_to_message_id: "m_ghost",
  reply_preview: { id: null, sender_display_name: null, duration_ms: null, deleted: true },
};

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPost.mockReset();
  mockApiDel.mockReset();
  mockApiGet.mockImplementation(async (path: string) => {
    if (path === "/walkie/channels") return { channels: [CH] };
    if (path.startsWith("/walkie/messages")) return { messages: [REPLY_DEAD, REPLY_LIVE, PARENT] };
    return { messages: [] };
  });
});

describe("Phase 51.6 · mobile visible reply UI", () => {
  it("long-press on a message opens the bottom sheet with a Reply option (admin)", async () => {
    mockUserRole = { id: "u_admin", role: "admin", name: "Alice" };
    const { getByTestId, getAllByTestId } = render(<WalkieChannel />);
    await waitFor(() => expect(getAllByTestId("walkie-message-row").length).toBeGreaterThan(0));
    const rows = getAllByTestId("walkie-message-row");
    // Long-press the first row.
    await act(async () => {
      fireEvent(rows[0], "longPress");
    });
    // Sheet visible with Reply option.
    await waitFor(() => expect(getByTestId("walkie-sheet-reply")).toBeTruthy());
  });

  it("selecting Reply from the sheet shows the 'Replying to X' banner", async () => {
    mockUserRole = { id: "u_admin", role: "admin", name: "Alice" };
    const { getByTestId, getAllByTestId, queryByTestId } = render(<WalkieChannel />);
    await waitFor(() => expect(getAllByTestId("walkie-message-row").length).toBeGreaterThan(0));
    // Pick the PARENT row (Bob) — after the client-side reverse the
    // messages are in ascending order so PARENT is at index 0.
    const rows = getAllByTestId("walkie-message-row");
    const parentRow = rows[0];
    await act(async () => { fireEvent(parentRow, "longPress"); });
    await waitFor(() => expect(queryByTestId("walkie-sheet-reply")).toBeTruthy());
    await act(async () => { fireEvent.press(getByTestId("walkie-sheet-reply")); });
    await waitFor(() => expect(getByTestId("walkie-reply-banner")).toBeTruthy());
    const label = getByTestId("walkie-reply-banner-label").props.children;
    const labelText = Array.isArray(label) ? label.flat().join("") : String(label);
    expect(labelText).toContain("Bob");
    expect(labelText).toContain("3s");
    // Cancel clears the banner.
    await act(async () => { fireEvent.press(getByTestId("walkie-reply-banner-cancel")); });
    await waitFor(() => expect(queryByTestId("walkie-reply-banner")).toBeNull());
  });

  it("reply rows render inline reply-preview blocks (live + deleted)", async () => {
    mockUserRole = { id: "u_admin", role: "admin", name: "Alice" };
    const { getAllByTestId } = render(<WalkieChannel />);
    await waitFor(() => expect(getAllByTestId("walkie-message-row").length).toBeGreaterThan(0));
    const previews = getAllByTestId("walkie-reply-preview");
    expect(previews.length).toBe(2);
    const texts = previews.map((p) => {
      const kids = p.findAllByType("Text" as any);
      return kids.map((k) => k.props.children).join("");
    });
    // One live ("Bob · 3s") + one deleted placeholder.
    expect(texts.some((t) => t.includes("Bob") && t.includes("3s"))).toBe(true);
    expect(texts.some((t) => t.includes("(original message deleted)"))).toBe(true);
  });

  it("tech-pool does NOT see a Reply option on all-hands (broadcast gate)", async () => {
    mockUserRole = { id: "u_tech", role: "technician", department: "pool", name: "Mike" };
    const { getAllByTestId, queryByTestId } = render(<WalkieChannel />);
    await waitFor(() => expect(getAllByTestId("walkie-message-row").length).toBeGreaterThan(0));
    // Long-press a row — non-admins on all-hands don't get the sheet
    // for Reply OR Pin, so the sheet never opens.
    await act(async () => { fireEvent(getAllByTestId("walkie-message-row")[0], "longPress"); });
    expect(queryByTestId("walkie-sheet-reply")).toBeNull();
  });
});
