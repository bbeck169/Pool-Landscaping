/**
 * Phase 40 · Step 1 · Offline cache for job-bootstrap reads.
 *
 * Very small AsyncStorage wrapper. When a tech opens a checklist and the
 * network round-trip to `GET /api/jobs/{jid}/service-report` fails, the
 * screen can fall back to the last successful payload we saved locally.
 * TTL is 7 days — beyond that we prefer showing an honest "offline and
 * no cached data" state over stale readings.
 *
 * The write queue + replay logic is intentionally NOT in this file
 * (deferred to Phase 40 · Step 2). This module is read-only cache; a
 * queued mutation layer will build on top.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const PREFIX = "cache/job/";
const TTL_MS = 7 * 24 * 60 * 60 * 1000;  // 7 days

type Wrapped<T> = { at: number; value: T };

export async function cacheJobBootstrap(jobId: string, response: any) {
  if (!jobId || !response) return;
  const wrapped: Wrapped<any> = { at: Date.now(), value: response };
  try {
    await AsyncStorage.setItem(PREFIX + jobId, JSON.stringify(wrapped));
  } catch { /* Storage full or platform-specific issue — non-fatal. */ }
}

export async function getCachedBootstrap(jobId: string): Promise<any | null> {
  if (!jobId) return null;
  try {
    const raw = await AsyncStorage.getItem(PREFIX + jobId);
    if (!raw) return null;
    const wrapped: Wrapped<any> = JSON.parse(raw);
    if (!wrapped?.at || (Date.now() - wrapped.at) > TTL_MS) {
      await AsyncStorage.removeItem(PREFIX + jobId);
      return null;
    }
    return wrapped.value;
  } catch { return null; }
}

export async function clearJobCache(jobId: string) {
  if (!jobId) return;
  try { await AsyncStorage.removeItem(PREFIX + jobId); }
  catch { /* non-fatal */ }
}
