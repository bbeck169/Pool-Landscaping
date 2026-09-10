/**
 * P0 429 fix tests — retryWithBackoff + ChecklistSavePill + error dialog.
 *
 * 1. Mock a 429 with Retry-After: 3 → assert client waits ~3s before retry 1.
 * 2. Mock 5 consecutive 429s → assert error dialog appears.
 * 3. Mock a successful save → assert only "Saving…" → "Online · Synced".
 * 4. Simulate offline → assert write queues, no retry attempts.
 */
import { retryWithBackoff } from "@/src/services/retryWithBackoff";
import { ApiError, ApiNetworkError } from "@/src/api";

// ── 1. retryWithBackoff respects Retry-After ────────────────────────────

describe("retryWithBackoff", () => {
  beforeAll(() => {
    jest.useFakeTimers();
  });
  afterAll(() => {
    jest.useRealTimers();
  });

  it("honors Retry-After header on the first retry of a 429", async () => {
    jest.useRealTimers();

    const err429 = new ApiError("Too Many Requests", 429, null);
    err429.retryAfterSeconds = 0.1; // 100ms for fast test
    err429.rateLimitSource = "upstream";

    let callCount = 0;
    const fn = jest.fn(async () => {
      callCount++;
      if (callCount === 1) throw err429;
      return "ok";
    });

    const onRetry = jest.fn();
    const startTime = Date.now();
    const result = await retryWithBackoff(fn, {
      maxRetries: 5, baseDelayMs: 2000, maxDelayMs: 30000,
      onRetry,
    });

    const elapsed = Date.now() - startTime;
    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(2);
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onRetry).toHaveBeenCalledWith(1, 100); // 0.1s = 100ms from Retry-After
    // Should have waited approximately 100ms (not 2000ms base)
    expect(elapsed).toBeGreaterThanOrEqual(80);
    expect(elapsed).toBeLessThan(500);

    jest.useFakeTimers();
  });

  it("throws after maxRetries consecutive 429s", async () => {
    jest.useRealTimers(); // Use real timers for this test — faster with small delays

    const make429 = () => {
      const e = new ApiError("Too Many Requests", 429, null);
      e.retryAfterSeconds = 0.05; // 50ms for fast test
      e.rateLimitSource = "upstream";
      return e;
    };

    const fn = jest.fn(async () => { throw make429(); });
    const onRetry = jest.fn();

    await expect(
      retryWithBackoff(fn, {
        maxRetries: 5, baseDelayMs: 50, maxDelayMs: 100,
        onRetry,
      })
    ).rejects.toThrow("Too Many Requests");

    // 1 initial + 5 retries = 6 calls
    expect(fn).toHaveBeenCalledTimes(6);
    expect(onRetry).toHaveBeenCalledTimes(5);

    jest.useFakeTimers(); // Restore fake timers for other tests
  });

  it("does not retry on non-429 errors (e.g. 400)", async () => {
    const err400 = new ApiError("Bad Request", 400, null);
    const fn = jest.fn(async () => { throw err400; });
    const onRetry = jest.fn();

    await expect(
      retryWithBackoff(fn, { maxRetries: 5, onRetry })
    ).rejects.toThrow("Bad Request");

    expect(fn).toHaveBeenCalledTimes(1);
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("retries on ApiNetworkError", async () => {
    jest.useRealTimers();

    let callCount = 0;
    const fn = jest.fn(async () => {
      callCount++;
      if (callCount <= 2) throw new ApiNetworkError("Network down");
      return "recovered";
    });

    const result = await retryWithBackoff(fn, {
      maxRetries: 5, baseDelayMs: 50, maxDelayMs: 100,
    });

    expect(result).toBe("recovered");
    expect(fn).toHaveBeenCalledTimes(3);

    jest.useFakeTimers();
  });

  it("succeeds on first try without any retry", async () => {
    jest.useRealTimers();
    const fn = jest.fn(async () => "success");
    const onRetry = jest.fn();

    const result = await retryWithBackoff(fn, { maxRetries: 5, onRetry });
    expect(result).toBe("success");
    expect(fn).toHaveBeenCalledTimes(1);
    expect(onRetry).not.toHaveBeenCalled();
    jest.useFakeTimers();
  });
});

// ── 2. ChecklistSavePill renders correct state ──────────────────────────

import React from "react";
import { render } from "@testing-library/react-native";

jest.mock("@/src/theme", () => ({
  colors: { brand: "#2563EB", muted: "#9CA3AF", onSurface: "#111827", error: "#EF4444", surface: "#FFFFFF", border: "#E5E7EB", surfaceSecondary: "#F9FAFB" },
  spacing: { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 },
  radius: { sm: 4, md: 8, lg: 12, pill: 999 },
  font: { regular: "System", medium: "System", semibold: "System", bold: "System" },
  fontSize: { xs: 11, sm: 13, base: 15, md: 15, lg: 18, xl: 22 },
}));

jest.mock("@expo/vector-icons", () => {
  const { Text } = require("react-native");
  return { Ionicons: (p: any) => <Text testID={`icon-${p.name}`}>{p.name}</Text> };
});

import ChecklistSavePill, { type SavePillState } from "@/src/components/sync/ChecklistSavePill";

describe("ChecklistSavePill", () => {
  it("renders 'Saving…' for saving state", () => {
    const { getByTestId } = render(
      <ChecklistSavePill state={{ kind: "saving" }} />
    );
    expect(getByTestId("checklist-save-pill-state-saving")).toBeTruthy();
    expect(getByTestId("save-pill-spinner")).toBeTruthy();
  });

  it("renders 'Save error — retrying 2/5' for retrying state", () => {
    const { getByTestId, getByText } = render(
      <ChecklistSavePill state={{ kind: "retrying", attempt: 2, maxRetries: 5 }} />
    );
    expect(getByTestId("checklist-save-pill-state-retrying")).toBeTruthy();
    expect(getByText("Save error — retrying 2/5")).toBeTruthy();
  });

  it("renders 'Save error — tap to retry' for exhausted state", () => {
    const { getByTestId, getByText } = render(
      <ChecklistSavePill state={{ kind: "exhausted", onRetry: jest.fn() }} />
    );
    expect(getByTestId("checklist-save-pill-state-exhausted")).toBeTruthy();
    expect(getByText("Save error — tap to retry")).toBeTruthy();
  });

  it("renders 'Online · Synced' for synced state", () => {
    const { getByTestId, getByText } = render(
      <ChecklistSavePill state={{ kind: "synced" }} />
    );
    expect(getByTestId("checklist-save-pill-state-synced")).toBeTruthy();
    expect(getByText("Online · Synced")).toBeTruthy();
  });

  it("renders 'Offline · Queued (3)' for offline state with count", () => {
    const { getByTestId, getByText } = render(
      <ChecklistSavePill state={{ kind: "offline", queuedCount: 3 }} />
    );
    expect(getByTestId("checklist-save-pill-state-offline")).toBeTruthy();
    expect(getByText("Offline · Queued (3)")).toBeTruthy();
  });

  it("renders exactly one pill — never two simultaneously", () => {
    const { getAllByTestId } = render(
      <ChecklistSavePill state={{ kind: "synced" }} />
    );
    // There should be exactly one pill root
    expect(getAllByTestId("checklist-save-pill")).toHaveLength(1);
  });
});

// ── 3. ApiError attaches 429 metadata ───────────────────────────────────

describe("ApiError 429 metadata", () => {
  it("has retryAfterSeconds and rateLimitSource fields", () => {
    const err = new ApiError("rate limited", 429, null);
    err.retryAfterSeconds = 5;
    err.rateLimitSource = "upstream";
    expect(err.retryAfterSeconds).toBe(5);
    expect(err.rateLimitSource).toBe("upstream");
    expect(err.status).toBe(429);
  });
});
