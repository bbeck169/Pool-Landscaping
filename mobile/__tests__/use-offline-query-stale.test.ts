/**
 * useOfflineQuery — staleTime + ref-latch tests.
 *
 * Tests:
 *   1. Returns cached value without firing fetch when cache is within staleTime.
 *   2. Re-fetches when cached entry is older than staleTime.
 *   3. refetch() bypasses staleTime (force = true).
 *   4. Unstable fetcher identity does NOT cause repeated fetches.
 *   5. Legacy cache entry without timestamp is treated as stale.
 */
import { renderHook, act, waitFor } from "@testing-library/react-native";
import { useOfflineQuery } from "@/src/hooks/useOfflineQuery";

/* ── Mocks ── */
const mockReadCacheWithAge = jest.fn();
const mockWriteCache = jest.fn().mockResolvedValue(undefined);
jest.mock("@/src/services/readCache", () => ({
  readCacheWithAge: (...a: any[]) => mockReadCacheWithAge(...a),
  writeCache: (...a: any[]) => mockWriteCache(...a),
}));

const mockIsOnlineNow = jest.fn().mockReturnValue(true);
jest.mock("@/src/services/sync/netBus", () => ({
  isOnlineNow: () => mockIsOnlineNow(),
}));

beforeEach(() => {
  jest.clearAllMocks();
  mockIsOnlineNow.mockReturnValue(true);
});

describe("useOfflineQuery staleTime guard", () => {
  it("1. returns cached value without firing fetch when cache is within staleTime", async () => {
    const cachedData = { revenue: 42 };
    const freshTs = Date.now() - 5_000; // 5s ago
    mockReadCacheWithAge.mockResolvedValue({ data: cachedData, cachedAt: freshTs });
    const fetcher = jest.fn().mockResolvedValue({ revenue: 99 });

    const { result } = renderHook(() =>
      useOfflineQuery("dashboard", fetcher, { staleTime: 60_000 }),
    );

    // Wait for the async cache read + state updates to settle.
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Cache was read.
    expect(mockReadCacheWithAge).toHaveBeenCalledWith("dashboard");
    // Fetcher was NOT called — cache is fresh (5s < 60s staleTime).
    expect(fetcher).not.toHaveBeenCalled();
    // Data is the cached value.
    expect(result.current.data).toEqual(cachedData);
    expect(result.current.isStale).toBe(false);
  });

  it("2. re-fetches when cached entry is older than staleTime", async () => {
    const cachedData = { revenue: 42 };
    const oldTs = Date.now() - 120_000; // 2min ago
    mockReadCacheWithAge.mockResolvedValue({ data: cachedData, cachedAt: oldTs });
    const freshData = { revenue: 99 };
    const fetcher = jest.fn().mockResolvedValue(freshData);

    const { result } = renderHook(() =>
      useOfflineQuery("dashboard", fetcher, { staleTime: 60_000 }),
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Fetcher WAS called — cache is stale (120s > 60s staleTime).
    expect(fetcher).toHaveBeenCalled();
    // Data is the fresh value.
    expect(result.current.data).toEqual(freshData);
    expect(result.current.isStale).toBe(false);
  });

  it("3. refetch() bypasses staleTime (force = true)", async () => {
    const cachedData = { revenue: 42 };
    const freshTs = Date.now() - 5_000; // within staleTime
    mockReadCacheWithAge.mockResolvedValue({ data: cachedData, cachedAt: freshTs });
    const freshData = { revenue: 99 };
    const fetcher = jest.fn().mockResolvedValue(freshData);

    const { result } = renderHook(() =>
      useOfflineQuery("dashboard", fetcher, { staleTime: 60_000 }),
    );

    // Initial: cache is fresh, fetcher not called.
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(fetcher).not.toHaveBeenCalled();

    // Force refetch.
    await act(async () => {
      result.current.refetch();
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Fetcher IS called despite fresh cache.
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.data).toEqual(freshData);
  });

  it("4. unstable fetcher identity does NOT cause repeated fetches", async () => {
    mockReadCacheWithAge.mockResolvedValue({ data: null, cachedAt: null });
    let callCount = 0;
    const makeFetcher = () =>
      jest.fn().mockImplementation(() => {
        callCount++;
        return Promise.resolve({ revenue: callCount });
      });

    let currentFetcher = makeFetcher();
    const { result, rerender } = renderHook(
      ({ fetcher }) => useOfflineQuery("dash-unstable", fetcher),
      { initialProps: { fetcher: currentFetcher } },
    );

    // Wait for first fetch to complete.
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(callCount).toBe(1);

    // Rerender with a NEW fetcher identity (simulates inline arrow fn).
    const newFetcher = makeFetcher();
    rerender({ fetcher: newFetcher });

    // Small wait to confirm no extra fetches fire.
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // Should NOT have refired — ref-latch absorbs the identity change.
    expect(callCount).toBe(1);
  });

  it("5. legacy cache entry without timestamp treated as stale", async () => {
    // cachedAt is null (legacy entry without _ts).
    mockReadCacheWithAge.mockResolvedValue({ data: { old: true }, cachedAt: null });
    const freshData = { fresh: true };
    const fetcher = jest.fn().mockResolvedValue(freshData);

    const { result } = renderHook(() =>
      useOfflineQuery("legacy-key", fetcher, { staleTime: 60_000 }),
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // cachedAt is null → treated as stale → fetcher IS called.
    expect(fetcher).toHaveBeenCalled();
    expect(result.current.data).toEqual(freshData);
  });
});
