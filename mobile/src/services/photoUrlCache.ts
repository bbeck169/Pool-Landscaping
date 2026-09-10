/**
 * Fix 2 — Photo URL cache utility.
 *
 * - Builds public URLs for job photos via `/api/public/job-photo/{jid}/{pid}`.
 * - Prefetches images into expo-image's built-in disk cache.
 * - Strips base64 blobs from cached service reports (backward compat migration).
 *
 * expo-image handles all disk caching internally — we do NOT store base64 in SQLite.
 */
import { Image } from "expo-image";

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL || "";

/**
 * Build the public (unauthenticated) URL for a job photo.
 * The endpoint `GET /api/public/job-photo/{jid}/{pid}` is UUID-gated.
 */
export function jobPhotoUrl(jobId: string, photoId: string): string {
  return `${BASE_URL}/api/public/job-photo/${encodeURIComponent(jobId)}/${encodeURIComponent(photoId)}`;
}

/**
 * Prefetch a single photo into expo-image's disk cache.
 * Best-effort — failures are silently swallowed.
 */
export async function prefetchJobPhoto(jobId: string, photoId: string): Promise<boolean> {
  const url = jobPhotoUrl(jobId, photoId);
  try {
    const ok = await Image.prefetch(url);
    return !!ok;
  } catch {
    return false;
  }
}

/**
 * Prefetch all photos from a service report's `photos` array.
 * Returns count of successfully prefetched photos.
 */
export async function prefetchReportPhotos(jobId: string, photos: { id: string }[]): Promise<number> {
  if (!photos?.length || !jobId) return 0;
  let ok = 0;
  // Batch in groups of 3 to avoid flooding.
  const BATCH = 3;
  for (let i = 0; i < photos.length; i += BATCH) {
    const batch = photos.slice(i, i + BATCH);
    const results = await Promise.allSettled(
      batch.map((p) => prefetchJobPhoto(jobId, p.id)),
    );
    ok += results.filter((r) => r.status === "fulfilled" && r.value).length;
  }
  return ok;
}

/**
 * Strip base64 blobs from a cached service report (backward compat).
 *
 * Legacy SQLite rows may contain reports with inline base64 photo data.
 * This strips it so:
 *   1. SQLite row size stays small.
 *   2. Components use URL-based lazy loading instead.
 *   3. No crashes on legacy rows.
 *
 * Returns a new (shallow-cloned) object — does NOT mutate the input.
 */
export function stripBase64FromReport(report: any): any {
  if (!report) return report;
  const clone = { ...report };
  if (Array.isArray(clone.photos)) {
    clone.photos = clone.photos.map((p: any) => {
      if (!p) return p;
      if (p.base64 || p.data || p.dataUrl || p.data_url) {
        const { base64, data, dataUrl, data_url, ...rest } = p;
        return rest;
      }
      return p;
    });
  }
  return clone;
}

/**
 * Given a photo object from a service report, resolve its display source.
 * Returns a URL string suitable for expo-image's `source` prop.
 *
 * Priority:
 *   1. If photo has a `url` field → use it.
 *   2. If we have (jobId, photo.id) → build public URL.
 *   3. If photo has base64/data → use as fallback (legacy).
 *   4. null → nothing to display.
 */
export function resolvePhotoSource(jobId: string, photo: any): string | null {
  if (!photo) return null;
  // Prefer explicit URL
  if (photo.url) return photo.url;
  // Build public URL from IDs
  if (jobId && photo.id) return jobPhotoUrl(jobId, photo.id);
  // Legacy base64 fallback (will be stripped on next sync)
  if (photo.base64) return `data:image/jpeg;base64,${photo.base64}`;
  if (photo.data) return photo.data;
  if (photo.dataUrl || photo.data_url) return photo.dataUrl || photo.data_url;
  return null;
}
