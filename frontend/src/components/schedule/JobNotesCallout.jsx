/**
 * Feb-2026 · Schedule polish — Job Notes visibility bump.
 *
 * Renders ``job.notes`` (and optional ``customer_notes`` / ``account_notes``
 * with a "Customer note:" prefix) as an amber-accented callout on the
 * schedule card. Replaces the prior blue-tinted card in ``CalendarSchedule``
 * and the inline text-button treatment in ``TodaySchedule`` — both surfaces
 * now use this single component so the tech / dispatcher sees the SAME
 * chip everywhere the note appears.
 *
 * Props:
 *   • ``jobId``        — used for stable data-testid rendering + a11y label
 *   • ``note``         — primary free-text (``job.notes``)
 *   • ``customerNote`` — optional ``customer_notes`` / ``account_notes``
 *   • ``truncated``    — backend-side truncation flag; if true, append ``…``
 *
 * Empty state: if both ``note`` and ``customerNote`` are empty/whitespace,
 * the component renders ``null`` (no "Add note" placeholder — cards stay
 * clean per the spec).
 *
 * Truncation: 2-line clamp with a "Show more" affordance rendered only
 * when the combined text is long enough to plausibly overflow (heuristic:
 * >100 chars or contains a newline). Expanded state persists per instance
 * until the schedule refreshes. No modal — expansion is inline.
 */
import React, { useState } from "react";
import { NotebookPen } from "lucide-react";

const AMBER_BG = "#FEF3C7";     // amber-100
const AMBER_ACCENT = "#F59E0B"; // amber-500 · 3px left-border bar
const AMBER_BORDER = "#FDE68A"; // amber-200
const AMBER_ICON = "#B45309";   // amber-700 · readable on amber-100
const TEXT_DARK = "#111827";    // near-black
const TEXT_MUTED = "#4B5563";   // gray-600 · for the "Customer note:" prefix

/** Heuristic — is this text long enough to plausibly overflow 2 lines? */
function _mayOverflow(s) {
  if (!s) return false;
  return s.length > 100 || s.indexOf("\n") >= 0;
}

export default function JobNotesCallout({
  jobId,
  note,
  customerNote,
  truncated = false,
}) {
  // Rules of Hooks — ``useState`` must be called on every render.
  // Compute the derived values first and hoist the hook above the
  // empty-state early return so the hook order stays stable.
  const [expanded, setExpanded] = useState(false);
  const jobNote = (note && String(note).trim()) ? String(note) : "";
  const custNote = (customerNote && String(customerNote).trim()) ? String(customerNote).trim() : "";
  const showMoreEligible = _mayOverflow(jobNote) || _mayOverflow(custNote);
  if (!jobNote && !custNote) return null;

  return (
    <div
      className="text-sm rounded-md flex items-start gap-2"
      style={{
        marginTop: 6,
        padding: "8px 10px",
        backgroundColor: AMBER_BG,
        border: `1px solid ${AMBER_BORDER}`,
        borderLeftWidth: 3,
        borderLeftStyle: "solid",
        borderLeftColor: AMBER_ACCENT,
        color: TEXT_DARK,
      }}
      title={[jobNote + (truncated ? "…" : ""),
                custNote ? `Customer note: ${custNote}` : ""].filter(Boolean).join("\n\n")}
      data-testid={`job-notes-callout-${jobId}`}
    >
      <NotebookPen
        size={14}
        color={AMBER_ICON}
        style={{ flexShrink: 0, marginTop: 2 }}
        aria-label="Job note"
        data-testid={`job-notes-icon-${jobId}`}
      />
      <div style={{ minWidth: 0, flex: 1, fontSize: 14, lineHeight: "20px" }}>
        {jobNote ? (
          <div
            className={expanded ? "" : "line-clamp-2"}
            style={{ color: TEXT_DARK }}
            data-testid={`job-${jobId}-notes`}
          >
            {jobNote}{truncated ? "…" : ""}
          </div>
        ) : null}
        {custNote ? (
          <div
            className={expanded ? "" : "line-clamp-2"}
            style={{ color: TEXT_DARK, marginTop: jobNote ? 4 : 0 }}
            data-testid={`job-notes-preview-${jobId}`}
          >
            <span style={{ fontWeight: 700, color: TEXT_MUTED }}>Customer note: </span>
            {custNote}
          </div>
        ) : null}
        {showMoreEligible ? (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setExpanded((x) => !x); }}
            className="mt-1 text-xs font-semibold underline-offset-2 hover:underline"
            style={{ color: AMBER_ICON, background: "transparent", padding: 0 }}
            data-testid={`job-notes-toggle-${jobId}`}
            aria-expanded={expanded}
          >
            {expanded ? "Show less" : "Show more"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
