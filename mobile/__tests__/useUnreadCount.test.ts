/**
 * G2 · Tests for useUnreadCount hook + Messages tab badge config.
 */
import { renderHook, act, waitFor } from "@testing-library/react-native";
import { AppState } from "react-native";

// ── Mock api ──
const mockGet = jest.fn();
jest.mock("@/src/api", () => ({ api: { get: (...args: any[]) => mockGet(...args) } }));

// ── Mock AppState ──
let appStateCallback: ((state: string) => void) | null = null;
const removeSpy = jest.fn();
jest.spyOn(AppState, "addEventListener").mockImplementation((_type: string, cb: any) => {
  appStateCallback = cb;
  return { remove: removeSpy } as any;
});

import { useUnreadCount } from "@/src/hooks/useUnreadCount";

beforeEach(() => {
  jest.useFakeTimers();
  mockGet.mockReset();
  removeSpy.mockReset();
  appStateCallback = null;
});
afterEach(() => {
  jest.useRealTimers();
});

describe("useUnreadCount", () => {
  it("returns numeric badge when unread_count > 0 and <= 99", async () => {
    mockGet.mockResolvedValue({ unread_count: 5, by_channel: { sms: 3, chat: 2 } });
    const { result } = renderHook(() => useUnreadCount(true));
    await waitFor(() => expect(result.current).toBe(5));
  });

  it('returns "99+" when unread_count > 99', async () => {
    mockGet.mockResolvedValue({ unread_count: 150, by_channel: {} });
    const { result } = renderHook(() => useUnreadCount(true));
    await waitFor(() => expect(result.current).toBe("99+"));
  });

  it("returns undefined (no badge) when unread_count is 0", async () => {
    mockGet.mockResolvedValue({ unread_count: 0, by_channel: {} });
    const { result } = renderHook(() => useUnreadCount(true));
    // Initial value is undefined; after fetch resolves it stays undefined for 0
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(result.current).toBeUndefined();
  });

  it("returns undefined and does not crash on fetch failure", async () => {
    const consoleSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    mockGet.mockRejectedValue(new Error("401 Not authenticated"));
    const { result } = renderHook(() => useUnreadCount(true));
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(result.current).toBeUndefined();
    consoleSpy.mockRestore();
  });

  it("polls every 60s", async () => {
    mockGet.mockResolvedValue({ unread_count: 1 });
    renderHook(() => useUnreadCount(true));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));

    // Advance 60s
    act(() => { jest.advanceTimersByTime(60_000); });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));

    // Advance another 60s
    act(() => { jest.advanceTimersByTime(60_000); });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(3));
  });

  it("refetches on app foreground", async () => {
    mockGet.mockResolvedValue({ unread_count: 2 });
    renderHook(() => useUnreadCount(true));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));

    // Simulate app going to background then foreground
    act(() => { appStateCallback?.("background"); });
    act(() => { appStateCallback?.("active"); });
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });

  it("cleans up interval and AppState listener on unmount", async () => {
    mockGet.mockResolvedValue({ unread_count: 0 });
    const { unmount } = renderHook(() => useUnreadCount(true));
    await waitFor(() => expect(mockGet).toHaveBeenCalled());

    unmount();
    expect(removeSpy).toHaveBeenCalled();

    // Advancing time should NOT trigger another fetch
    const callsBefore = mockGet.mock.calls.length;
    act(() => { jest.advanceTimersByTime(120_000); });
    expect(mockGet).toHaveBeenCalledTimes(callsBefore);
  });

  it("returns undefined when disabled", async () => {
    mockGet.mockResolvedValue({ unread_count: 10 });
    const { result } = renderHook(() => useUnreadCount(false));
    // Should never call API
    expect(mockGet).not.toHaveBeenCalled();
    expect(result.current).toBeUndefined();
  });
});
