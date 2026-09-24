/**
 * Task I · absolutizeUrl — shared image-URL prefix helper.
 *
 * React Native <Image> requires absolute URLs; relative paths like
 * ``/api/objects/...`` render as blank. This helper prepends the
 * backend origin when the URL is relative, passes through absolute
 * URLs and data: URIs unchanged, and returns undefined for
 * null/empty so callers can conditionally render.
 */
import { api_base } from "@/src/api";

export function absolutizeUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (
    url.startsWith("http://") ||
    url.startsWith("https://") ||
    url.startsWith("data:")
  ) {
    return url;
  }
  // api_base() returns "${EXPO_PUBLIC_BACKEND_URL}/api".
  // Strip the "/api" suffix to get the bare origin so we don't
  // double-up when the path already starts with "/api/".
  const base = api_base();
  const origin = base.endsWith("/api") ? base.slice(0, -4) : base;
  return `${origin}${url.startsWith("/") ? "" : "/"}${url}`;
}
