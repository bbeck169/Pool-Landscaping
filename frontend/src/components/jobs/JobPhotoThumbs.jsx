/**
 * JobPhotoThumbs — shared thumbnail strip for list-view rows.
 *
 * Task L+P · Commit 6 · Feb-2026.  Renders up to ``max``
 * thumbnails from a row's precomputed ``photoThumbUrls`` array
 * (populated by Commit 3's widened ``slim_photos_on_rows``
 * which unions service_reports.photos IDs into
 * ``photo_thumb_urls`` on every list row).  After Commit 3's
 * endpoint extension, thumbnails for SR-source photo IDs also
 * resolve — no per-source render logic needed here.
 *
 * Props
 *   jobId         — the parent job id, used only for testid
 *                    scoping.
 *   photoIds      — full list of photo IDs on the row.  Length
 *                    drives the ``+N`` overflow badge; individual
 *                    ids are used for the per-thumb testid key.
 *   photoThumbUrls — parallel array of precomputed ``/thumb``
 *                    URLs from the backend.  Expected shape:
 *                    ``/api/public/job-photo/{jid}/{pid}/thumb``.
 *   max           — cap on rendered thumbnails (default 3).
 *   testidBase    — prefix for the four testid slots (default
 *                    ``"job-photos"``).
 *
 * Empty state renders an em-dash (``—``) with a scoped testid so
 * screen readers + testers can distinguish "no photos" from
 * "photos not yet loaded".  Matches the Pricebook column
 * empty-state convention from Task E.
 *
 * Failure handling
 *   onError swap → an ``<ImageOff>`` glyph replaces the broken
 *   thumb tile.  Keeps the row layout stable when a single URL
 *   fails to resolve (e.g. a stale ``jobs.photos`` row whose
 *   ``s3_key`` no longer exists and whose base64 fallback is
 *   empty — see Commit 3's structured 404 branch).
 *
 * Loading skeleton
 *   Native ``loading="lazy"`` on <img> handles browser-native
 *   deferred loads.  For the pre-load flash we render the image
 *   inside a subtle bg-zinc-100 wrapper so the tile size stays
 *   stable even before the network resolves.
 */
import React, { useState } from "react";
import { ImageOff } from "lucide-react";

const BACKEND = process.env.REACT_APP_BACKEND_URL;

function ThumbTile({ url, testid, alt }) {
  const [broken, setBroken] = useState(false);
  return (
    <div
      className="relative rounded overflow-hidden flex items-center justify-center bg-zinc-100"
      style={{ width: 28, height: 28, border: "1px solid #E4E4E7" }}
      data-testid={testid}
    >
      {broken ? (
        <ImageOff size={12} className="text-zinc-400" />
      ) : (
        <img
          src={`${BACKEND}${url}`}
          alt={alt || ""}
          loading="lazy"
          onError={() => setBroken(true)}
          className="w-full h-full object-cover"
        />
      )}
    </div>
  );
}

export function JobPhotoThumbs({
  jobId,
  photoIds,
  photoThumbUrls,
  max = 3,
  testidBase = "job-photos",
}) {
  const ids = Array.isArray(photoIds) ? photoIds : [];
  const urls = Array.isArray(photoThumbUrls) ? photoThumbUrls : [];
  const count = ids.length || urls.length;

  if (count === 0) {
    return (
      <span
        className="text-sm text-zinc-400"
        data-testid={`${testidBase}-empty-${jobId}`}
        aria-label="No photos"
      >
        —
      </span>
    );
  }

  const shown = urls.slice(0, max);
  const overflow = Math.max(0, count - max);

  return (
    <div
      className="inline-flex items-center gap-1"
      data-testid={`${testidBase}-container-${jobId}`}
    >
      {shown.map((u, i) => (
        <ThumbTile
          key={`${ids[i] || i}`}
          url={u}
          testid={`${testidBase}-thumb-${jobId}-${i}`}
          alt={`Job photo ${i + 1}`}
        />
      ))}
      {overflow > 0 ? (
        <span
          className="text-[10px] font-semibold text-zinc-500 rounded px-1"
          style={{ minWidth: 20, textAlign: "center",
                    border: "1px dashed #D4D4D8", height: 28,
                    display: "inline-flex", alignItems: "center",
                    justifyContent: "center" }}
          data-testid={`${testidBase}-more-${jobId}`}
        >
          +{overflow}
        </span>
      ) : null}
    </div>
  );
}

export default JobPhotoThumbs;
