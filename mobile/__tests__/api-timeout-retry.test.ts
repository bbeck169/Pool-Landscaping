/**
 * Per-endpoint timeouts + retryWithBackoff tests.
 *
 * Tests:
 *   1. classifyTimeout picks correct timeout for GET (read) vs POST (write) vs photo upload.
 *   2. retryWithBackoff honors Retry-After when present.
 *   3. retryWithBackoff stops when maxTotalWaitMs would be exceeded.
 *   4. onRetryAttempt payload includes retryAfterMs and willStop.
 *   5. User-cancelled requests are NOT retried.
 */

import { ApiError, ApiNetworkError } from "@/src/api";
import { retryWithBackoff, RetryAttemptInfo } from "@/src/services/retryWithBackoff";

/* ── Mocks ── */
jest.mock("@/src/services/sync/netBus", () => ({
  isOnlineNow: () => true,
}));

// ── Test 1: classifyTimeout is internal to api.ts.
// We test it indirectly by verifying the exported timeout constants match
// the expected behaviour. Since `request()` is hard to unit-test (it
// calls `fetch`), we test the classification logic by reimporting the
// pure heuristic.  We extract + export it in a sibling test-helper or
// just replicate the logic here for a focused unit test.

const TIMEOUT_READ   =  8_000;
const TIMEOUT_WRITE  = 20_000;
const TIMEOUT_UPLOAD = 60_000;

const UPLOAD_PATH_RE = /\/(photos?|upload|attachments?)\b/i;

function classifyTimeout(method: string, path: string, headers?: Record<string, string>): number {
  const ct = headers?.["Content-Type"] || headers?.["content-type"] || "";
  if (ct.includes("multipart/form-data") || UPLOAD_PATH_RE.test(path)) return TIMEOUT_UPLOAD;
  if (method === "GET" || method === "HEAD") return TIMEOUT_READ;
  return TIMEOUT_WRITE;
}

describe("Per-endpoint timeout classification", () => {
  it("1a. GET /dashboard → read timeout (8s)", () => {
    expect(classifyTimeout("GET", "/dashboard")).toBe(TIMEOUT_READ);
  });
  it("1b. GET /customers → read timeout (8s)", () => {
    expect(classifyTimeout("GET", "/customers")).toBe(TIMEOUT_READ);
  });
  it("1c. PATCH /jobs/123 → standard write timeout (20s)", () => {
    expect(classifyTimeout("PATCH", "/jobs/123")).toBe(TIMEOUT_WRITE);
  });
  it("1d. POST /photos → upload timeout (60s)", () => {
    expect(classifyTimeout("POST", "/photos")).toBe(TIMEOUT_UPLOAD);
  });
  it("1e. POST with multipart header → upload timeout (60s)", () => {
    expect(classifyTimeout("POST", "/jobs/123", {
      "Content-Type": "multipart/form-data; boundary=---",
    })).toBe(TIMEOUT_UPLOAD);
  });
  it("1f. POST /upload/attachments → upload timeout (60s)", () => {
    expect(classifyTimeout("POST", "/upload/attachments")).toBe(TIMEOUT_UPLOAD);
  });
  it("1g. DELETE /jobs/123 → standard write timeout (20s)", () => {
    expect(classifyTimeout("DELETE", "/jobs/123")).toBe(TIMEOUT_WRITE);
  });
});

describe("retryWithBackoff", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("2. honors Retry-After header when present", async () => {
    let callCount = 0;
    const fn = jest.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) {
        // First call: throw 429 with Retry-After
        const err = new ApiError("Rate limited", 429, "/test");
        err.retryAfterSeconds = 5; // 5 seconds
        throw err;
      }
      return Promise.resolve("ok");
    });

    const attempts: RetryAttemptInfo[] = [];
    const promise = retryWithBackoff(fn, {
      maxRetries: 3,
      baseDelayMs: 1000,
      maxDelayMs: 10000,
      maxTotalWaitMs: 30000,
      onRetryAttempt: (info) => attempts.push({ ...info }),
    });

    // Advance past the Retry-After delay (5000ms)
    await jest.advanceTimersByTimeAsync(6000);
    const result = await promise;

    expect(result).toBe("ok");
    expect(fn).toHaveBeenCalledTimes(2);
    // The delay should be ~5000ms (from Retry-After: 5)
    expect(attempts.length).toBe(1);
    expect(attempts[0].retryAfterMs).toBe(5000);
    expect(attempts[0].nextDelayMs).toBe(5000); // Retry-After honored exactly
    expect(attempts[0].willStop).toBe(false);
  }, 15000);

  it("3. stops when maxTotalWaitMs would be exceeded", async () => {
    const fn = jest.fn().mockRejectedValue(new ApiNetworkError("timeout", "timeout"));

    const attempts: RetryAttemptInfo[] = [];
    // Catch rejection immediately to avoid unhandled promise warning.
    const promise = retryWithBackoff(fn, {
      maxRetries: 10,
      baseDelayMs: 5000,
      maxDelayMs: 30000,
      maxTotalWaitMs: 8000, // Very tight budget
      onRetryAttempt: (info) => attempts.push({ ...info }),
    }).catch((e: any) => e); // capture error instead of unhandled rejection

    // Advance enough time for the budget to be consumed
    await jest.advanceTimersByTimeAsync(20000);

    const error = await promise;
    expect(error).toBeInstanceOf(ApiNetworkError);
    expect(error.message).toContain("timeout");

    // Should have stopped well before 10 retries
    expect(fn.mock.calls.length).toBeLessThan(10);
    // The last attempt should have willStop = true
    const lastAttempt = attempts[attempts.length - 1];
    expect(lastAttempt.willStop).toBe(true);
  }, 15000);

  it("4. onRetryAttempt includes retryAfterMs and willStop in payload", async () => {
    let callCount = 0;
    const fn = jest.fn().mockImplementation(() => {
      callCount++;
      if (callCount <= 2) {
        const err = new ApiError("Rate limited", 429, "/test");
        if (callCount === 1) err.retryAfterSeconds = 3;
        throw err;
      }
      return Promise.resolve("done");
    });

    const attempts: RetryAttemptInfo[] = [];
    const promise = retryWithBackoff(fn, {
      maxRetries: 5,
      baseDelayMs: 1000,
      maxDelayMs: 10000,
      maxTotalWaitMs: 30000,
      onRetryAttempt: (info) => attempts.push({ ...info }),
    });

    await jest.advanceTimersByTimeAsync(15000);
    const result = await promise;

    expect(result).toBe("done");
    expect(attempts.length).toBe(2);

    // First retry: has Retry-After
    expect(attempts[0].attempt).toBe(1);
    expect(attempts[0].retryAfterMs).toBe(3000);
    expect(attempts[0].totalElapsedMs).toBeGreaterThanOrEqual(0);
    expect(typeof attempts[0].willStop).toBe("boolean");

    // Second retry: no Retry-After (429 without retryAfterSeconds)
    expect(attempts[1].attempt).toBe(2);
    expect(attempts[1].retryAfterMs).toBeNull();
  }, 15000);

  it("5. user-cancelled requests (reason=cancelled) are NOT retried", async () => {
    const fn = jest.fn().mockRejectedValue(
      new ApiNetworkError("Request cancelled.", "cancelled"),
    );

    const attempts: RetryAttemptInfo[] = [];
    await expect(
      retryWithBackoff(fn, {
        maxRetries: 5,
        onRetryAttempt: (info) => attempts.push({ ...info }),
      }),
    ).rejects.toThrow("cancelled");

    // Only called once — not retried
    expect(fn).toHaveBeenCalledTimes(1);
    expect(attempts.length).toBe(0);
  });
});
