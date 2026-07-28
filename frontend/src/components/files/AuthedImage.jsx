/**
 * Phase F1 · Feb 2026 — AuthedImage components (web).
 *
 * Two variants:
 *   • <AuthedImage>          — fetches the bytes via bearer header,
 *                              renders from a blob URL. No token
 *                              leakage into the URL / referrer.
 *   • <AuthedImageQueryParam> — passes ``?auth=<token>`` in the src
 *                              directly. Cheaper (no blob, no
 *                              revoke), but the token WILL appear in
 *                              server access logs and referrer
 *                              headers. Prefer AuthedImage unless
 *                              you're rendering into email HTML or
 *                              a share-link surface.
 */
import React, { useEffect, useRef, useState } from "react";
import { ImageOff, Loader2 } from "lucide-react";
import { fetchAsBlob, revokeBlobUrl, buildAuthedDownloadUrl } from "@/api/files";

export function AuthedImage({
  fileId, alt = "", className = "", size = 96, fallback, testid,
}) {
  const [state, setState] = useState({ url: null, loading: true, error: false });
  // Track the blob url so unmount + fileId change can revoke exactly one.
  const activeUrlRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setState({ url: null, loading: true, error: false });
    fetchAsBlob(fileId)
      .then(({ url }) => {
        if (cancelled) {
          revokeBlobUrl(url);
          return;
        }
        // Revoke the prior url if present.
        if (activeUrlRef.current && activeUrlRef.current !== url) {
          revokeBlobUrl(activeUrlRef.current);
        }
        activeUrlRef.current = url;
        setState({ url, loading: false, error: false });
      })
      .catch(() => {
        if (cancelled) return;
        setState({ url: null, loading: false, error: true });
      });
    return () => {
      cancelled = true;
      // Revoke whatever this effect owned.
      if (activeUrlRef.current) {
        revokeBlobUrl(activeUrlRef.current);
        activeUrlRef.current = null;
      }
    };
  }, [fileId]);

  const boxStyle = { width: size, height: size };
  const resolvedTestid = testid || `authed-image-${fileId}`;

  if (state.loading) {
    return (
      <div style={boxStyle}
            className={`rounded-lg bg-zinc-100 flex items-center justify-center ${className}`}
            data-testid={`${resolvedTestid}-loading`}
            aria-label={`${alt} loading`}>
        <Loader2 className="animate-spin text-zinc-400" size={Math.max(14, size / 4)} />
      </div>
    );
  }
  if (state.error) {
    if (fallback !== undefined) return fallback;
    return (
      <div style={boxStyle}
            className={`rounded-lg bg-zinc-100 flex items-center justify-center ${className}`}
            data-testid={`${resolvedTestid}-error`}
            aria-label={`${alt} unavailable`}>
        <ImageOff className="text-zinc-400" size={Math.max(14, size / 3)} />
      </div>
    );
  }
  return (
    <img
      src={state.url}
      alt={alt}
      className={`rounded-lg object-cover ${className}`}
      style={boxStyle}
      data-testid={resolvedTestid}
    />
  );
}

// Lighter variant — token in URL. Trade-off documented in the file header.
export function AuthedImageQueryParam({
  fileId, alt = "", className = "", size = 96, testid,
}) {
  const src = buildAuthedDownloadUrl(fileId);
  const resolvedTestid = testid || `authed-image-qp-${fileId}`;
  return (
    <img
      src={src}
      alt={alt}
      className={`rounded-lg object-cover ${className}`}
      style={{ width: size, height: size }}
      data-testid={resolvedTestid}
    />
  );
}

export default AuthedImage;
