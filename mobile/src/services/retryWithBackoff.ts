/**
 * retryWithBackoff — generic async retry with exponential backoff + jitter.
 *
 * Designed for the P0 tech-close-job 429 fix:
 *   - Base delay 2 s, cap 30 s, max 5 retries.
 *   - On 429 with Retry-After header or body `retry_after_seconds`,
 *     honor that value for the FIRST retry instead of the base delay.
 *   - After max retries, throw the last error — caller surfaces UI.
 *   - `onRetry(attempt, delayMs)` callback lets the caller update pill state.
 */
import { ApiError, ApiNetworkError } from "@/src/api";
import { isOnlineNow } from "@/src/services/sync/netBus";

export type RetryOpts = {
  /** Max number of retries (default 5). */
  maxRetries?: number;
  /** Base delay in ms (default 2000). */
  baseDelayMs?: number;
  /** Max delay cap in ms (default 30000). */
  maxDelayMs?: number;
  /** Callback on each retry. */
  onRetry?: (attempt: number, delayMs: number) => void;
  /** If true, skip retries and throw immediately when offline. */
  skipWhenOffline?: boolean;
};

const DEFAULT_MAX_RETRIES = 5;
const DEFAULT_BASE_DELAY = 2000;
const DEFAULT_MAX_DELAY = 30000;

function jitter(ms: number): number {
  // ±25% jitter
  return ms * (0.75 + Math.random() * 0.5);
}

function backoffDelay(attempt: number, base: number, cap: number): number {
  return jitter(Math.min(base * Math.pow(2, attempt), cap));
}

/**
 * Returns true if the error is retryable (429 or network error).
 * Non-retryable errors (400, 401, 403, 404, 422, 500) are thrown immediately.
 */
function isRetryable(e: any): boolean {
  if (e instanceof ApiNetworkError) return true;
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

      // Calculate delay
      let delayMs: number;
      const retryAfterMs = getRetryAfterFromError(e);
      if (attempt === 0 && retryAfterMs !== null) {
        // Honor Retry-After for the first retry
        delayMs = retryAfterMs;
      } else {
        delayMs = backoffDelay(attempt, baseDelay, maxDelay);
      }

      opts?.onRetry?.(attempt + 1, delayMs);

      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
  }

  throw lastError;
}
