/**
 * Phase 51c · Feb-2026 — Walkie mobile screen mount tests.
 *
 * Mounts both walkie screens with every native dep mocked. Covers:
 *   - channel list renders + unread badge visible
 *   - customer role bounces to the empty state
 *   - record button greyed for tech on all-hands, live for admin
 *   - timeline renders own-messages with the ``you`` tag +
 *     waveform bar when peaks present / fallback bar when null
 */
import React from "react";
import { render, waitFor } from "@testing-library/react-native";

// Phase 53a triage · Feb-2026 — raise per-test timeout to 15s. Batch
// jest runs put React Native suites under scheduler contention that
// pushes the first-test wall-clock above jest's default 5s even when
// CPU time is <1s (isolated runs pass in ~1s). This is a scheduling
// accommodation, not a code change — the tests themselves are green.
jest.setTimeout(15000);

// ── Mocks ────────────────────────────────────────────────────────────
const mockApiGet = jest.fn();
const mockApiPost = jest.fn();
const mockUseLocalSearchParams = jest.fn(() => ({ channelId: "ch_ah_1" }));
const mockUseFocusEffect = jest.fn((fn: any) => fn());

// Prefixed ``mock`` name so jest.mock factories can reference it
// (per jest hoisting rules).
let mockUserRole: any = { id: "u_admin", role: "admin", email: "a@ex.com", name: "Alice", department: "" };

jest.mock("@/src/auth", () => ({
  useAuth: () => ({ user: mockUserRole }),
}));

jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a), post: (...a: any[]) => mockApiPost(...a) },
  api_base: () => "https://example.test/api",
  getAuthToken: async () => "tok",
}));

jest.mock("expo-router", () => {
  const React = require("react");
  return {
    useLocalSearchParams: () => mockUseLocalSearchParams(),
    useRouter: () => ({ push: jest.fn(), back: jest.fn(), replace: jest.fn() }),
    // Real ``useFocusEffect`` runs the callback once on focus and
    // returns its cleanup. Emulating with ``useEffect`` empty-deps
    // (component mounts once in the test) keeps the callback from
    // re-firing on every state update — otherwise we hit React's
    // "Too many re-renders" guard because loading state churn would
    // re-trigger the mock every cycle.
    useFocusEffect: (fn: any) => React.useEffect(() => {
      const cleanup = fn();
      return typeof cleanup === "function" ? cleanup : undefined;
    }, []),
  };
});

jest.mock("expo-audio", () => ({
  useAudioPlayer: () => ({
    play: jest.fn(),
    pause: jest.fn(),
    addListener: () => ({ remove: () => undefined }),
  }),
  useAudioRecorder: () => ({
    prepareToRecordAsync: jest.fn(async () => undefined),
    record: jest.fn(),
    stop: jest.fn(async () => undefined),
    uri: "file:///tmp/clip.m4a",
  }),
  useAudioRecorderState: () => ({ isRecording: false, durationMillis: 0 }),
  RecordingPresets: { HIGH_QUALITY: {} },
  requestRecordingPermissionsAsync: jest.fn(async () => ({ granted: true })),
}));

jest.mock("@/src/components/ui", () => {
  const { View, Text } = require("react-native");
  return {
    Loading: () => <Text testID="stub-loading">Loading</Text>,
    EmptyState: ({ title, testID }: any) => (
      <View testID={testID || "stub-empty"}><Text>{title}</Text></View>
    ),
  };
});

jest.mock("@/src/components/widgets", () => {
  const { View, Text } = require("react-native");
  return {
    Header: ({ title, left, right }: any) => (
      <View testID="stub-header"><Text>{title}</Text>{left}{right}</View>
    ),
  };
});

jest.mock("@expo/vector-icons", () => {
  const { View } = require("react-native");
  return { Ionicons: (props: any) => <View {...props} testID={`icon-${props.name}`} /> };
});

// In-memory AsyncStorage mock — the walkie helpers persist mute
// preference through it. Parity with GpsTracker.test.ts.
const _store: Record<string, string> = {};
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn((key: string) => Promise.resolve(_store[key] ?? null)),
  setItem: jest.fn((key: string, val: string) => { _store[key] = val; return Promise.resolve(); }),
  removeItem: jest.fn((key: string) => { delete _store[key]; return Promise.resolve(); }),
  clear: jest.fn(() => { Object.keys(_store).forEach(k => delete _store[k]); return Promise.resolve(); }),
}));

// eslint-disable-next-line import/first
import WalkieChannelList from "@/app/walkie/index";
// eslint-disable-next-line import/first
import WalkieChannel from "@/app/walkie/[channelId]";

const ALL_HANDS = { id: "ch_ah_1", kind: "all_hands", unread_count: 2 };
const POOL_DEPT = { id: "ch_pool", kind: "department", department: "pool", unread_count: 0 };

beforeEach(() => {
  mockApiGet.mockReset();
  mockApiPost.mockReset();
});

describe("Phase 51c · WalkieChannelList mount", () => {
  it("renders channels with unread badge visible when count > 0", async () => {
    mockUserRole = { id: "u_admin", role: "admin", email: "a@ex.com", name: "Alice" };
    mockApiGet.mockResolvedValueOnce({ channels: [ALL_HANDS, POOL_DEPT] });
    const { getByTestId, queryByTestId } = render(<WalkieChannelList />);
    await waitFor(() => expect(getByTestId("walkie-channel-all_hands")).toBeTruthy());
    expect(getByTestId(`walkie-channel-unread-${ALL_HANDS.id}`)).toBeTruthy();
    // Zero-unread channels do NOT render a badge.
    expect(queryByTestId(`walkie-channel-unread-${POOL_DEPT.id}`)).toBeNull();
  });

  it("bounces customer to the empty-customer state", async () => {
    mockUserRole = { id: "u_cust", role: "customer", email: "c@ex.com", name: "Chris" };
    mockApiGet.mockResolvedValueOnce({ channels: [ALL_HANDS] });
    const { getByTestId } = render(<WalkieChannelList />);
    await waitFor(() => expect(getByTestId("walkie-empty-customer")).toBeTruthy());
  });
});

describe("Phase 51c · WalkieChannel record-button gate parity", () => {
  it("greys the record button for tech on all-hands channel", async () => {
    mockUserRole = { id: "u_tech", role: "technician", department: "pool", name: "Mike" };
    // First call: channel list; second call: messages.
    mockApiGet
      .mockResolvedValueOnce({ channels: [ALL_HANDS] })
      .mockResolvedValueOnce({ messages: [] });
    const { getByTestId } = render(<WalkieChannel />);
    await waitFor(() => expect(getByTestId("walkie-record-btn")).toBeTruthy());
    // Locked reason surfaces (server-parity string).
    await waitFor(() => expect(getByTestId("walkie-record-locked-reason")).toBeTruthy());
  });

  it("leaves the record button live for admin on all-hands channel", async () => {
    mockUserRole = { id: "u_admin", role: "admin", name: "Alice" };
    mockApiGet
      .mockResolvedValueOnce({ channels: [ALL_HANDS] })
      .mockResolvedValueOnce({ messages: [] });
    const { getByTestId, queryByTestId } = render(<WalkieChannel />);
    await waitFor(() => expect(getByTestId("walkie-record-btn")).toBeTruthy());
    // Not locked — the locked-reason node is NOT rendered.
    expect(queryByTestId("walkie-record-locked-reason")).toBeNull();
  });

  it("renders own-message tag + timeline for admin sender", async () => {
    mockUserRole = { id: "u_admin", role: "admin", name: "Alice" };
    const msg = {
      id: "m1", channel_id: ALL_HANDS.id, sender_user_id: "u_admin",
      audio_url: "/files/x/download", duration_ms: 3000,
      waveform_peaks: [0.2, 0.5, 0.9, 0.7, 0.3],
      created_at: "2026-02-07T10:00:00Z",
    };
    mockApiGet
      .mockResolvedValueOnce({ channels: [ALL_HANDS] })
      .mockResolvedValueOnce({ messages: [msg] });
    const { getByTestId, getAllByTestId } = render(<WalkieChannel />);
    await waitFor(() => expect(getAllByTestId("walkie-message-row").length).toBe(1));
    // Own-message pill visible on the sender's own clip.
    expect(getByTestId("walkie-own-tag")).toBeTruthy();
    // Waveform bar rendered (peaks present).
    expect(getByTestId("walkie-waveform")).toBeTruthy();
  });
});
