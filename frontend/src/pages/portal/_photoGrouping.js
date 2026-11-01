/**
 * Portal media grouping helper · Feb-2026.
 *
 * Canonical home for the Portal Photos + Videos grouping logic
 * — consumed by ``pages/portal/PortalPhotosPage.jsx`` and
 * ``pages/portal/PortalVideosPage.jsx``.  The videos adapter at
 * the bottom of this file field-maps the videos payload onto the
 * photos shape and delegates to the shared helper.
 *
 * Pre-shared history: the function lived inline in the now-
 * deleted ``pages/portal/PortalPhotos.jsx:51-87`` under TD-76c
 * (Feb-2026).  Extraction landed at ``bbecd6da1``
 * (TD-portal-photos-page-wire-grouping); the legacy file was
 * removed in ``TD-portal-photos-videos-legacy-cleanup``.  The
 * shape of the helper is unchanged across that history — this
 * module is the single source of truth going forward.
 */

// TD-76c · Feb-2026 — grouping helper.  Exported so vitest can
// pin the deterministic tiebreak contract without re-rendering.
//
// Return shape:
//   [
//     { day: "2026-10-14", header: "Tuesday, Oct 14, 2026", visits: [
//       { visitKey: "job-id-or-?", jobTitle: "Weekly Pool Cleaning",
//         firstStamp: "<ISO>", photos: [...] },
//       ...
//     ] },
//     ...
//   ]
//
// Sort rules:
//   * Date groups: newest first (``day.localeCompare`` DESC — ISO
//     dates sort lexicographically so this is the correct direction).
//   * Visits within a day: ``firstStamp`` ASC (earliest visit of
//     the day appears first), ``visitKey`` lex ASC as the final
//     deterministic tiebreak.
//   * Photos within a visit: insertion order preserved from BE.
//
// Timezone (TD-portal-photos-page-wire-grouping · Feb-2026):
//   The ``day`` bucket is a plain ISO ``yyyy-mm-dd`` slice of the
//   source stamp.  The header string is rendered via
//   ``toLocaleDateString(undefined, …)`` so the customer's BROWSER
//   timezone is used — matches the shipped portal convention
//   across ``PortalHome.jsx:33,746``, ``PortalServiceReports.jsx:
//   116,297``, ``PortalAgreementRenew.jsx:40``, and
//   ``PortalReferralsPage.jsx:42``.  See TECH_DEBT
//   ``TD-portal-photos-page-wire-grouping`` for the rationale on
//   NOT introducing tenant-tz plumbing in this cycle.
export function groupPhotosByDateAndVisit(photos) {
  const byDay = new Map();
  for (const p of photos || []) {
    const stamp =
      p.submitted_at || p.uploaded_at || p.created_at || "";
    const day = stamp.slice(0, 10) || "Unknown date";
    const visitKey = p.job_id || p.report_id || "no-visit";
    if (!byDay.has(day)) byDay.set(day, new Map());
    const dayMap = byDay.get(day);
    if (!dayMap.has(visitKey)) {
      dayMap.set(visitKey, {
        visitKey,
        jobTitle:
          p.job_title || p.service_type || "Service visit",
        firstStamp: stamp,
        photos: [],
      });
    }
    const v = dayMap.get(visitKey);
    if (!v.firstStamp || (stamp && stamp < v.firstStamp)) {
      v.firstStamp = stamp;
    }
    v.photos.push(p);
  }
  const dayKeys = Array.from(byDay.keys()).sort(
    (a, b) => b.localeCompare(a),
  );
  const fmtHeader = (d) => {
    if (d === "Unknown date") return d;
    try {
      return new Date(d + "T00:00:00").toLocaleDateString(
        undefined,
        {
          weekday: "long",
          month: "short",
          day: "numeric",
          year: "numeric",
        },
      );
    } catch {
      return d;
    }
  };
  return dayKeys.map((day) => {
    const visits = Array.from(byDay.get(day).values()).sort(
      (a, b) => {
        const t =
          (a.firstStamp || "").localeCompare(b.firstStamp || "");
        if (t !== 0) return t;
        return (a.visitKey || "").localeCompare(b.visitKey || "");
      },
    );
    return { day, header: fmtHeader(day), visits };
  });
}


/**
 * Flatten a grouped tree into the ordered list the shared
 * ``<Lightbox>`` consumes.  Iteration order MUST match the
 * group → visit → photo order used by the grid render so that a
 * tile click resolves to the right lightbox index.
 */
export function flattenGrouped(groups) {
  const flat = [];
  for (const g of groups || []) {
    for (const v of g.visits || []) {
      for (const p of v.photos || []) flat.push(p);
    }
  }
  return flat;
}


/**
 * TD-portal-videos-page-wire-grouping · Feb-2026.
 *
 * Thin adapter — maps portal video rows to the Photos helper's
 * expected field names and delegates.  Chosen over duplicating
 * the Photos grouping logic (operator path 1(a)) because the
 * two payloads are structurally identical for grouping
 * purposes; only the field names differ.
 *
 * Field map:
 *   * ``uploaded_at`` →  ``submitted_at``  (service date)
 *   * ``entity_id``   →  ``job_id``        (visit key)
 *   * ``entity_title`` → ``job_title``     (visit title)
 *
 * The Photos helper's exports and internal shape are UNCHANGED
 * — ``bbecd6da1`` is preserved bit-for-bit.  Callers get the
 * same ``[{day, header, visits: [{visitKey, jobTitle,
 * firstStamp, photos: [...]}]}]`` tree the Photos page already
 * consumes; the "photos" array here contains video rows but the
 * caller doesn't need to know (iteration order + visit grouping
 * are what matter for divider rendering + lightbox index-
 * threading).
 */
export function groupVideosByDateAndVisit(videos) {
  const adapted = (videos || []).map((v) => ({
    ...v,
    submitted_at: v.submitted_at || v.uploaded_at,
    job_id: v.job_id || v.entity_id,
    job_title: v.job_title || v.entity_title,
  }));
  return groupPhotosByDateAndVisit(adapted);
}
