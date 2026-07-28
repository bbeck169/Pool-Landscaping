/**
 * Phase F2a · Feb 2026 — Job Before/After Photos section (web).
 *
 * Renders two side-by-side upload+display sections on the Job Detail
 * page. Files are persisted in the F0 ``files`` collection with:
 *   purpose             ∈ { "job_before_photo", "job_after_photo" }
 *   linked_entity_type  = "job"
 *   linked_entity_id    = <jid>
 *
 * Legacy ``jobs.photos[]`` (base64 in the job doc) is intentionally
 * left untouched — it still powers the service-log email embeds.
 * F2a is additive.
 *
 * Access control mirrors the F0 backend gate:
 *   Upload  — any authenticated user with job access (admins, techs)
 *   Delete  — uploader OR admin/super_admin  (backend enforces;
 *              client always shows the button and surfaces the 403
 *              toast if the caller isn't allowed).
 *
 * Customer role is filtered OUT one level up in ``JobDetail.jsx`` so
 * they never see this section at all.
 */
import React, { useCallback, useState } from "react";
import { FileUpload } from "@/components/files/FileUpload";
import { FileList } from "@/components/files/FileList";

const ACCEPT = "image/*,video/mp4";

// Extracted for the vitest suite — mirrors the F0 backend gate so
// tests can verify per-role visibility without mounting the section.
export function canDeletePhoto({ user, file }) {
  if (!user) return false;
  const role = String(user.role || "").toLowerCase();
  if (role === "admin" || role === "super_admin") return true;
  if (!file) return false;
  return Boolean(file.uploaded_by_user_id) && file.uploaded_by_user_id === user.id;
}

/** Small self-contained "one purpose" bucket — upload area on top,
 *  scoped list below. ``nonce`` is incremented on successful upload
 *  which remounts FileList so it re-fetches. */
function PhotoBucket({ label, purpose, jobId, canDelete }) {
  const [nonce, setNonce] = useState(0);
  const onUploaded = useCallback(() => setNonce((n) => n + 1), []);

  return (
    <section
      data-testid={`job-photos-${purpose === "job_before_photo" ? "before" : "after"}`}
      className="flex flex-col gap-3"
    >
      <h3 className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
        {label}
      </h3>
      <FileUpload
        purpose={purpose}
        linkedEntityType="job"
        linkedEntityId={jobId}
        accept={ACCEPT}
        multiple
        maxFiles={12}
        onUploaded={onUploaded}
        buttonLabel="Add photos or MP4"
      />
      <FileList
        key={nonce}
        linkedEntityType="job"
        linkedEntityId={jobId}
        purpose={purpose}
        canDelete={canDelete}
        emptyLabel="No photos yet."
      />
    </section>
  );
}

export function JobBeforeAfterPhotos({ jobId, user }) {
  if (!jobId) return null;
  // Backend enforces the fine-grained (uploader-owned) gate; here we
  // just show the delete button whenever the caller COULD delete
  // (admin/super_admin) — non-admin uploaders will see the button
  // per file, and the backend rejects unauthorized attempts.
  const role = String(user?.role || "").toLowerCase();
  const canDelete = role === "admin" || role === "super_admin"
                     || role === "manager" || role === "pool_tech";

  return (
    <div
      className="rounded-2xl p-6 mb-4"
      style={{
        backgroundColor: "var(--surface, #FFFFFF)",
        border: "1px solid var(--border, #E4E4E7)",
      }}
      data-testid="job-before-after-photos"
    >
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-bold" style={{ color: "var(--onSurface, #18181B)" }}>
          Before &amp; After Photos
        </h2>
        <span
          className="text-xs uppercase tracking-wide text-zinc-500"
          data-testid="job-before-after-photos-hint"
        >
          Images + MP4 · 25 MB max per file
        </span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
        <PhotoBucket
          label="Before"
          purpose="job_before_photo"
          jobId={jobId}
          canDelete={canDelete}
        />
        <PhotoBucket
          label="After"
          purpose="job_after_photo"
          jobId={jobId}
          canDelete={canDelete}
        />
      </div>
    </div>
  );
}

export default JobBeforeAfterPhotos;
