/**
 * Portal media grouping helper · Feb-2026.
 *
 * Shared between ``pages/portal/PortalPhotos.jsx`` (legacy page,
 * currently shadowed by `App.js:1629` behind `App.js:1621`'s
 * `PortalPhotosPage` route — tracked by
 * ``TD-portal-photos-videos-legacy-cleanup``) and
 * ``pages/portal/PortalPhotosPage.jsx`` (active page) so both
 * surfaces call a single owner.
 *
 * Pre-shared history: the function lived inline in
 * ``PortalPhotos.jsx:51-87`` under TD-76c (Feb-2026).  The shape
 * is unchanged; this file is a straight extraction so the
 * canonical vitest at ``test/portal-photos-td76-canonical.test.jsx``
 * continues to import ``groupPhotosByDateAndVisit`` from the
 * same two-file surface (re-export from the legacy page).
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
