/**
 * TD-66 · Feb-2026 — token-aware URL concatenation helper.
 *
 * Problem: multiple ``<img>`` / ``<video>`` sites across the Work
 * Stream + Service Log pages built authenticated media URLs with a
 * naïve concatenation:
 *
 *   src={url + (token ? "?token=" + token : "")}
 *
 * This works for RELATIVE paths that carry no query string, but
 * breaks the moment the backend 302-redirects the request to an S3
 * presigned URL that already carries ``?X-Amz-Algorithm=…&X-Amz-
 * Signature=…`` — appending another ``?token=…`` produces a URL
 * with TWO question marks (``…?X-Amz-Signature=…?token=…``), which
 * S3 interprets as the signature value including the second ``?``
 * character.  Signature verification fails and S3 returns 403, so
 * every thumbnail renders as a broken-image placeholder.
 *
 * Fix: a single helper that:
 *   1. Prefers ``URL`` + ``URLSearchParams`` (idempotent — a second
 *      call replaces the previous ``token`` value, never appends).
 *   2. Falls back to a separator-aware string splice for pre-``?``
 *      paths (``URL`` constructor rejects pure relative-no-base
 *      inputs in test envs that lack ``window.location``).
 *   3. Preserves ``#fragment`` positioning so deep-link anchors
 *      survive the token stamp.
 *   4. No-ops cleanly when ``token`` is falsy — identical to the
 *      pre-TD-66 "no auth" branch.
 */

export function withAuthToken(url, token) {
  if (!url) return url;
  if (!token) return url;

  // Fast path: ``URL`` constructor + ``URLSearchParams``.  Works for
  // absolute URLs AND for relative paths when ``window.location.
  // origin`` is defined (every browser; jsdom under vitest).
  try {
    const base =
      typeof window !== "undefined" && window.location
        ? window.location.origin
        : "http://localhost";
    const u = new URL(url, base);
    u.searchParams.set("token", token);
    // Re-stringify.  If the input was relative, strip the synthetic
    // base so we return the same shape we received.
    const absolute = u.toString();
    if (/^(https?:)?\/\//i.test(url)) return absolute;
    // Relative input → return pathname + search + hash only.
    return `${u.pathname}${u.search}${u.hash}`;
  } catch {
    // Fallback: separator-aware string splice.  Covers two edge
    // cases the URL constructor rejects:
    //   * Pure fragment inputs like ``#foo``.
    //   * Malformed inputs we'd rather pass through unchanged than
    //     corrupt further.
    const hashIdx = url.indexOf("#");
    const fragment = hashIdx >= 0 ? url.slice(hashIdx) : "";
    const base = hashIdx >= 0 ? url.slice(0, hashIdx) : url;
    const sep = base.includes("?") ? "&" : "?";
    // Idempotent guard — if ``token=`` already exists, replace it.
    if (/[?&]token=/.test(base)) {
      const replaced = base.replace(
        /([?&])token=[^&]*/,
        `$1token=${encodeURIComponent(token)}`,
      );
      return `${replaced}${fragment}`;
    }
    return `${base}${sep}token=${encodeURIComponent(token)}${fragment}`;
  }
}

export default withAuthToken;
