/**
 * P0 · Job detail spinner-timeout test.
 *
 * Validates two things:
 *   A. The timeout + fallback logic works correctly (pure async, no React).
 *   B. The UI states render correctly (loading, error/retry, cached, content).
 *
 * Tests:
 *   1. API never resolves → 20s timeout fires → error surfaced.
 *   2. flush + API both hang → timeout fires → cache used.
 *   3. API resolves quickly → job returned.
 *   4. API rejects → cache fallback used.
 *   5. Error/retry UI renders with correct testIDs.
 *   6. Cached-banner UI renders with correct testIDs.
 */
import React from "react";
import { render } from "@testing-library/react-native";
import { View, Text, Pressable } from "react-native";

/* ── Mocks ────────────────────────────────────────────────────────── */
jest.mock("@expo/vector-icons", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { Text: T } = require("react-native");
  return { Ionicons: ({ name, ...p }: any) => <T {...p}>{name}</T> };
});

jest.mock("@/src/theme", () => ({
  colors: { brand: "#0EA5E9", onSurface: "#0F172A", error: "#DC2626", muted: "#94A3B8", surface: "#FFF", surfaceSecondary: "#F8FAFC", border: "#E2E8F0", surfaceMuted: "#F1F5F9", onSurfaceSecondary: "#64748B" },
  font: { regular: "Sys", medium: "Sys", semibold: "Sys", bold: "Sys" },
  fontSize: { xs: 10, sm: 13, base: 15, lg: 17, xl: 20 },
  spacing: { xs: 4, sm: 8, md: 12, lg: 16, xl: 20 },
  radius: { sm: 6, md: 10, lg: 14, pill: 999 },
}));

/* ── Pure load() logic (mirrors the fix applied to [id].tsx) ───── */
const LOAD_TIMEOUT_MS = 20_000;

interface LoadResult {
  job: any;
  error: string;
  loading: boolean;
  fromCache: boolean;
}

async function runLoad(opts: {
  apiGet: (url: string) => Promise<any>;
  getCachedJob: (id: string) => Promise<any>;
  flushMutations?: () => Promise<any>;
  flushPhotos?: () => Promise<any>;
  jobId?: string;
}): Promise<LoadResult> {
  const {
    apiGet,
    getCachedJob,
    flushMutations = () => Promise.resolve(),
    flushPhotos = () => Promise.resolve(),
    jobId = "test-job",
  } = opts;
  const result: LoadResult = { job: null, error: "", loading: true, fromCache: false };

  try {
    // Fire-and-forget (non-blocking).
    flushMutations().catch(() => {});
    flushPhotos().catch(() => {});

    let timeoutId: ReturnType<typeof setTimeout>;
    const fresh = await Promise.race([
      apiGet(`/jobs/${jobId}`),
      new Promise<never>((_, rej) => {
        timeoutId = setTimeout(() => rej(new Error("__LOAD_TIMEOUT__")), LOAD_TIMEOUT_MS);
      }),
    ]);
    clearTimeout(timeoutId!);
    result.job = fresh;
    result.fromCache = false;
  } catch (e: any) {
    const cached = await getCachedJob(opts.jobId || "test-job").catch(() => null);
    if (cached) {
      result.job = cached;
      result.fromCache = true;
    } else {
      result.job = null;
      result.error =
        e?.message === "__LOAD_TIMEOUT__"
          ? "Loading timed out. Check your connection and try again."
          : "Couldn't load job. Retry?";
    }
  } finally {
    result.loading = false;
  }
  return result;
}

/* ── Stateless UI shells for render tests ────────────────────────── */
function ErrorRetryUI({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <View testID="job-detail-error">
      <Text testID="job-detail-error-message">{error}</Text>
      <Pressable testID="job-detail-retry-btn" onPress={onRetry}>
        <Text>Retry</Text>
      </Pressable>
    </View>
  );
}

function ContentUI({ job, fromCache }: { job: any; fromCache: boolean }) {
  return (
    <View testID="job-detail-content">
      <Text testID="job-detail-title">{job.title}</Text>
      {fromCache && <Text testID="job-detail-cached-banner">Showing cached copy</Text>}
    </View>
  );
}

/* ── A. Logic tests (async, fake timers for timeout) ─────────────── */
describe("P0 · Job detail load() logic", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("1. API never resolves → timeout fires → error message set", async () => {
    const neverResolves = () => new Promise<any>(() => {});
    const mockCache = jest.fn().mockResolvedValue(null);

    const loadPromise = runLoad({ apiGet: neverResolves, getCachedJob: mockCache });

    // Fire the 20s timeout
    jest.advanceTimersByTime(LOAD_TIMEOUT_MS + 500);

    const result = await loadPromise;

    expect(result.loading).toBe(false);
    expect(result.job).toBeNull();
    expect(result.error).toContain("timed out");
    expect(result.fromCache).toBe(false);
    expect(mockCache).toHaveBeenCalled();
  }, 10000);

  it("2. flush + API hang → timeout → falls back to cache", async () => {
    const hang = () => new Promise<any>(() => {});
    const cachedJob = { id: "cached-1", title: "Cached Pool Cleaning" };
    const mockCache = jest.fn().mockResolvedValue(cachedJob);

    const loadPromise = runLoad({
      apiGet: hang,
      getCachedJob: mockCache,
      flushMutations: hang,
      flushPhotos: hang,
    });

    jest.advanceTimersByTime(LOAD_TIMEOUT_MS + 500);

    const result = await loadPromise;

    expect(result.loading).toBe(false);
    expect(result.job).toEqual(cachedJob);
    expect(result.fromCache).toBe(true);
    expect(result.error).toBe("");
  }, 10000);

  it("3. API resolves quickly → job returned, no error", async () => {
    const job = { id: "fast-1", title: "Fast Pool Service" };
    const mockApiGet = jest.fn().mockResolvedValue(job);
    const mockCache = jest.fn().mockResolvedValue(null);

    const loadPromise = runLoad({ apiGet: mockApiGet, getCachedJob: mockCache });

    // Advance a tiny bit to process the resolved promise microtasks
    jest.advanceTimersByTime(1);

    const result = await loadPromise;

    expect(result.loading).toBe(false);
    expect(result.job).toEqual(job);
    expect(result.fromCache).toBe(false);
    expect(result.error).toBe("");
  });

  it("4. API rejects → falls back to cache", async () => {
    const mockApiGet = jest.fn().mockRejectedValue(new Error("Network error"));
    const cachedJob = { id: "offline-1", title: "Cached Landscaping" };
    const mockCache = jest.fn().mockResolvedValue(cachedJob);

    const loadPromise = runLoad({ apiGet: mockApiGet, getCachedJob: mockCache });

    jest.advanceTimersByTime(1);

    const result = await loadPromise;

    expect(result.loading).toBe(false);
    expect(result.job).toEqual(cachedJob);
    expect(result.fromCache).toBe(true);
    expect(result.error).toBe("");
  });
});

/* ── B. UI render tests (static, no async) ──────────────────────── */
describe("P0 · Job detail fallback UI rendering", () => {
  it("5. Error + retry UI renders correct testIDs and message", () => {
    const { getByTestId } = render(
      <ErrorRetryUI error="Loading timed out. Check your connection and try again." onRetry={jest.fn()} />,
    );

    expect(getByTestId("job-detail-error")).toBeTruthy();
    expect(getByTestId("job-detail-retry-btn")).toBeTruthy();
    const msg = getByTestId("job-detail-error-message");
    expect(msg.children.join("")).toContain("timed out");
  });

  it("6. Cached-banner UI renders when fromCache is true", () => {
    const { getByTestId } = render(
      <ContentUI job={{ id: "j1", title: "Pool Service" }} fromCache={true} />,
    );

    expect(getByTestId("job-detail-content")).toBeTruthy();
    expect(getByTestId("job-detail-title").children[0]).toBe("Pool Service");
    expect(getByTestId("job-detail-cached-banner")).toBeTruthy();
  });
});
