/**
 * retryWithBackoff — generic async retry with exponential backoff + jitter.
 *
 * Designed for the P0 tech-close-job 429 fix, enhanced with:
 *   - Wall-clock budget (`maxTotalWaitMs`) — stops retrying when total
 *     elapsed time would exceed the budget, regardless of attempt count.
 *   - Retry-After honored on ALL retries (not just the first).
 *   - Enhanced `onRetryAttempt` callback exposes `retryAfterMs`,
 *     `totalElapsedMs`, and `willStop` so the UI can show
 *     "retrying in Xs" or "save failed after Xs".
 */
import { ApiError, ApiNetworkError } from "@/src/api";
import { isOnlineNow } from "@/src/services/sync/netBus";

export type RetryAttemptInfo = {
  attempt: number;
  nextDelayMs: number;
  retryAfterMs: number | null;
  totalElapsedMs: number;
  willStop: boolean;
};

export type RetryOpts = {
  /** Max number of retries (default 5). */
  maxRetries?: number;
  /** Base delay in ms (default 2000). */
  baseDelayMs?: number;
  /** Max delay cap in ms (default 30000). */
  maxDelayMs?: number;
  /** Wall-clock budget in ms across ALL retries (default 30000). 0 = no limit. */
  maxTotalWaitMs?: number;
  /** Legacy callback on each retry. */
  onRetry?: (attempt: number, delayMs: number) => void;
  /** Enhanced callback with full retry context. */
  onRetryAttempt?: (info: RetryAttemptInfo) => void;
  /** If true, skip retries and throw immediately when offline. */
  skipWhenOffline?: boolean;
};

const DEFAULT_MAX_RETRIES = 5;
const DEFAULT_BASE_DELAY = 2000;
const DEFAULT_MAX_DELAY = 30000;
const DEFAULT_MAX_TOTAL_WAIT = 30000;

function jitter(ms: number): number {
  // ±25% jitter
  return ms * (0.75 + Math.random() * 0.5);
}

function backoffDelay(attempt: number, base: number, cap: number): number {
  return jitter(Math.min(base * Math.pow(2, attempt), cap));
}

/**
 * Returns true if the error is retryable (429 or network/timeout error).
 * Non-retryable errors (400, 401, 403, 404, 422, 500) are thrown immediately.
 * Cancelled requests (user abort) are NOT retried.
 */
function isRetryable(e: any): boolean {
  if (e instanceof ApiNetworkError) {
    // User-initiated cancel → don't retry.
    if (e.reason === "cancelled") return false;
    return true; // timeout or network
  }
  if (e instanceof ApiError && e.status === 429) return true;
  return false;
}

function getRetryAfterFromError(e: any): number | null {
  if (!(e instanceof ApiError)) return null;
  if (e.retryAfterSeconds && e.retryAfterSeconds > 0) {
    return e.retryAfterSeconds * 1000; // convert to ms
  }
  return null;
}

export async function retryWithBackoff<T>(
  fn: () => Promise<T>,
  opts?: RetryOpts,
): Promise<T> {
  const maxRetries = opts?.maxRetries ?? DEFAULT_MAX_RETRIES;
  const baseDelay = opts?.baseDelayMs ?? DEFAULT_BASE_DELAY;
  const maxDelay = opts?.maxDelayMs ?? DEFAULT_MAX_DELAY;
  const maxTotalWait = opts?.maxTotalWaitMs ?? DEFAULT_MAX_TOTAL_WAIT;

  const startTime = Date.now();
  let lastError: any;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (e: any) {
      lastError = e;

      // If not retryable, throw immediately
      if (!isRetryable(e)) throw e;

      // If offline and skipWhenOffline, throw immediately
      if (opts?.skipWhenOffline && !isOnlineNow()) throw e;

      // If we've exhausted all retries, throw
      if (attempt >= maxRetries) throw e;

      const totalElapsedMs = Date.now() - startTime;

      // Calculate delay — honor Retry-After on ALL retries.
      let delayMs: number;
      const retryAfterMs = getRetryAfterFromError(e);
      if (retryAfterMs !== null) {
        // Clamp to [0, maxDelay]
        delayMs = Math.min(retryAfterMs, maxDelay);
      } else {
        delayMs = backoffDelay(attempt, baseDelay, maxDelay);
      }

      // Wall-clock budget check: if the next delay would push us
      // past the total budget, either clamp or stop.
      let willStop = false;
      if (maxTotalWait > 0) {
        const remaining = maxTotalWait - totalElapsedMs;
        if (remaining <= 0) {
          // Budget already exhausted — stop immediately.
          willStop = true;
          opts?.onRetry?.(attempt + 1, 0);
          opts?.onRetryAttempt?.({
            attempt: attempt + 1, nextDelayMs: 0,
            retryAfterMs, totalElapsedMs, willStop: true,
          });
          throw e;
        }
        if (delayMs > remaining) {
          // Clamp delay to remaining budget, then this will be the last attempt.
          delayMs = remaining;
          willStop = true;
        }
      }

      // Notify callers.
      opts?.onRetry?.(attempt + 1, delayMs);
      opts?.onRetryAttempt?.({
        attempt: attempt + 1, nextDelayMs: delayMs,
        retryAfterMs, totalElapsedMs, willStop,
      });

      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }

  throw lastError;
}
