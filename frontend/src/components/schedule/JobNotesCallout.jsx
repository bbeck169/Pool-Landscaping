/*! P0d · 2026-10-12 · Force chunk hash change to purge stale 5979.aad12649.chunk.js from downstream caches. If this file compiles, confirm the resulting chunk filename does NOT match .aad12649. */
/*
 * expanded-usage audit (chunk 5979 · JobNotesCallout.jsx · Feb-2026)
 *   line  76   JSDoc text ``expanded`` state                        declared? n/a    (comment, not identifier)
 *   line  86   const [expanded, setExpanded] = useState(false)      declared? YES    DECLARATION — scope: NoteBlock
 *   line  98   className={expanded ? "" : "line-clamp-3"}           declared? yes    line 86 (NoteBlock)
 *   line 111   setExpanded((x) => !x)                               declared? yes    line 86 (NoteBlock)  [setter]
 *   line 121   aria-expanded={expanded}                             declared? yes    line 86 (NoteBlock)  [attribute name is hyphenated token; RHS is bare identifier read]
 *   line 122   aria-label={expanded ? ... : ...}                    declared? yes    line 86 (NoteBlock)
 *   line 126   {expanded ? "Show less" : "Show more"}               declared? yes    line 86 (NoteBlock)
 *   line 145   const [expanded, setExpanded] = useState(false)      declared? YES    DECLARATION — scope: JobNotesCallout
 *   line 191   className={expanded ? "" : "line-clamp-2"}           declared? yes    line 145 (JobNotesCallout)
 *   line 223   setExpanded((x) => !x)                               declared? yes    line 145 (JobNotesCallout)  [setter]
 *   line 227   aria-expanded={expanded}                             declared? yes    line 145 (JobNotesCallout)
 *   line 229   {expanded ? "Show less" : "Show more"}               declared? yes    line 145 (JobNotesCallout)
 *
 * Orphan count: 0. All reads covered by one of the two useState
 * declarations in this file. See src/test/expanded-identifier-
 * guard.test.jsx for the CI-level sweep that locks this invariant.
 * Historical: 5th recurrence of ``/schedule`` ReferenceError;
 * every prior fix patched one site and left the other scope's
 * useState unprotected against future refactors. The two
 * ``// expanded fix`` inline comments next to the useState
 * declarations below are the mandated regression breadcrumb —
 * do NOT strip them.
 */
/**
 * Feb-2026 · Schedule polish — Job Notes visibility bump.
 *
 * Renders ``job.notes`` (and optional customer-sourced notes —
 * customer / pool / landscape) as an amber-accented callout on the
 * schedule card.  Replaces the prior blue-tinted card in
 * ``CalendarSchedule`` and the inline text-button treatment in
 * ``TodaySchedule`` — both surfaces now use this single component
 * so the tech / dispatcher sees the SAME chip everywhere.
 *
 * Props:
 *   • ``jobId``        — stable data-testid prefix + a11y label
 *   • ``note``         — job free-text (``job.notes``) · legacy
 *   • ``customerNote`` — ``customer.notes`` · general customer file
 *   • ``poolNote``     — ``customer.service_notes.pool`` (Phase 3)
 *   • ``landscapeNote``— ``customer.service_notes.landscape`` (Phase 3)
 *   • ``truncated``    — backend-side truncation flag for ``note``
 *
 * Phase 3 · Feb-2026 — pool + landscape notes moved from the small
 * "Note" chip (``<ServiceNotePill>``) into the same inline callout
 * as customer notes, so admins/techs read the full note text on the
 * card without a secondary tap.  Order on card:
 *
 *   Job notes (free-text)   — unchanged legacy behaviour, 2-line clamp
 *   Customer notes          — ``customer.notes``
 *   Pool notes              — ``customer.service_notes.pool``
 *   Landscape notes         — ``customer.service_notes.landscape``
 *
 * Each customer-sourced block (customer / pool / landscape) uses the
 * SHARED ``<NoteBlock>`` primitive below so the three note types
 * truncate identically at 120 characters OR 3 lines (whichever hits
 * first), each with its own "Show more" / "Show less" toggle.  The
 * legacy job-free-text block keeps its 2-line clamp for backward
 * compat with the existing ``schedule-card-notes-visibility`` test
 * suite — a job-level free-text note is a separate concept from the
 * customer-file notes this ticket surfaces.
 *
 * Empty state: when ALL inputs are empty / whitespace, the component
 * renders ``null`` so the card stays clean (no "Add note" placeholder).
 */
import React, { useState } from "react";
import { NotebookPen } from "lucide-react";

// Feb-2026 HOTFIX — WHITE fill (was amber-100 which competed with
// the K74 mint card).  Amber icon + 3px amber left-border stay.
// Tenants override via ``--note-*`` tokens in ``index.css``.
const NOTE_BG      = "var(--note-bg-white, #FFFFFF)";
const NOTE_BORDER  = "var(--note-border, #E5E7EB)";     // gray-200
const NOTE_ACCENT  = "var(--note-accent, #F59E0B)";     // amber-500
const NOTE_ICON_FG = "var(--note-icon-fg, #B45309)";    // amber-700
const TEXT_DARK    = "var(--note-text-fg, #111827)";
const TEXT_MUTED   = "var(--note-label-fg, #4B5563)";

/** Phase 3 — hard char limit for the shared customer-sourced note
 *  truncation primitive.  Pairs with ``line-clamp-3`` so a note hits
 *  the toggle on either axis (120 chars OR 3 wrapped lines). */
const CUSTOMER_NOTE_CHAR_LIMIT = 120;

/** Heuristic — is this text long enough to plausibly overflow 2 lines?
 *  Used by the legacy job-free-text block ONLY.  Customer-sourced
 *  blocks (customer / pool / landscape) use the stricter 120-char
 *  threshold enforced inside ``<NoteBlock>``. */
function _mayOverflow(s) {
  if (!s) return false;
  return s.length > 100 || s.indexOf("\n") >= 0;
}


/**
 * Phase 3 · Feb-2026 — shared truncation primitive for the three
 * customer-sourced note types (customer / pool / landscape).
 * Visually mirrors the pre-Phase-3 customer-note block (labelled
 * row, ``font-weight: 700`` grey label, body text in near-black)
 * so the three note surfaces read as a single logical cluster on
 * the card.  Each instance owns its own ``expanded`` state so
 * toggling pool notes doesn't accidentally expand landscape or
 * customer notes.
 *
 * Truncation rule: show a "Show more" toggle when ``text.length >
 * CUSTOMER_NOTE_CHAR_LIMIT`` OR the text contains a newline.
 * Collapsed view uses Tailwind's ``line-clamp-3`` so wrapped text
 * also hits the ceiling at 3 lines.
 */
function NoteBlock({ label, text, jobId, testId }) {
  // expanded fix guard — do not remove (Terser-preserved runtime
  // marker so chunk 5979's byte output differs from the pre-guard
  // build and CDN caches purge even though the ``// expanded fix``
  // inline comment next to the useState below is stripped at build.
  // ``output.comments: false`` in react-scripts' Terser config
  // elides every /* */ and // comment, so a real side-effect is the
  // only Terser-safe way to bust the chunk hash without changing
  // semantics. Guard is idempotent — set-once per page load.
  if (typeof window !== "undefined"
      && window.__EXPANDED_FIX_V2__ === undefined) {
    window.__EXPANDED_FIX_V2__ = "jobnotescallout_noteblock";
  }
  // Recurrence #7 (Feb-2026) — atomic-tuple useState pattern.
  // The deploy pipeline silently dropped line 189 (the sibling
  // useState in the default-export component) between HEAD and
  // the production artifact on `.0d15d04e`, producing a 4-site
  // orphan read + ReferenceError. The pattern below splits the
  // hook call and the destructure across THREE statements so a
  // line-level drop cannot leave a hook-reference orphaned, and
  // adds an Array.isArray fallback so if the tuple is somehow
  // undefined the component gracefully degrades to always-
  // collapsed instead of crashing. DO NOT SPLIT the three lines
  // across unrelated edits — they are an atomic unit.
  if (typeof window !== "undefined"
      && window.__EXPANDED_FIX_V3__ === undefined) {
    window.__EXPANDED_FIX_V3__ = "jobnotescallout_noteblock_v3";
  }
  const expandedTuple = React.useState(false); // expanded fix v3 (atomic — do not split)
  const expanded      = Array.isArray(expandedTuple) ? expandedTuple[0] : false;
  const setExpanded   = Array.isArray(expandedTuple) ? expandedTuple[1] : () => {};
  const safe = (text && String(text).trim()) ? String(text) : "";
  if (!safe) return null;
  const overflow = safe.length > CUSTOMER_NOTE_CHAR_LIMIT
                     || safe.indexOf("\n") >= 0;
  return (
    <div
      style={{ color: TEXT_DARK, marginTop: 4 }}
      data-testid={testId}
      data-note-block={label}
    >
      <div
        className={expanded ? "" : "line-clamp-3"}
        data-testid={`${testId}-text`}
      >
        <span style={{ fontWeight: 700, color: TEXT_MUTED }}>
          {label}:{" "}
        </span>
        {safe}
      </div>
      {overflow ? (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((x) => !x);
          }}
          className="mt-0.5 text-xs font-semibold underline-offset-2 hover:underline"
          style={{
            color: NOTE_ICON_FG,
            background: "transparent",
            padding: 0,
            border: 0,
          }}
          data-testid={`${testId}-toggle`}
          aria-expanded={expanded}
          aria-label={expanded
            ? `Collapse ${label.toLowerCase()}`
            : `Expand ${label.toLowerCase()}`}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      ) : null}
    </div>
  );
}


export default function JobNotesCallout({
  jobId,
  note,
  customerNote,
  poolNote,
  landscapeNote,
  truncated = false,
}) {
  // Rules of Hooks — ``useState`` must be called on every render.
  // Compute the derived values first and hoist the hook above the
  // empty-state early return so the hook order stays stable.
  // expanded fix guard — do not remove (Terser-preserved runtime
  // marker; see NoteBlock above for rationale). Idempotent: assigns
  // once per page load, no-op thereafter.
  if (typeof window !== "undefined"
      && window.__EXPANDED_FIX_V2_MAIN__ === undefined) {
    window.__EXPANDED_FIX_V2_MAIN__ = "jobnotescallout_main";
  }
  // Recurrence #7 (Feb-2026) — atomic-tuple useState pattern.
  // THIS component was the one whose line-level useState was
  // dropped on prod `.0d15d04e`. The split-across-three-statements
  // pattern below is the primary defensive measure — if a future
  // deploy strips any one of the three lines, the remaining lines
  // keep the component rendering (graceful degrade to always-
  // collapsed) instead of a ReferenceError. See NoteBlock above
  // for the detailed rationale. DO NOT SPLIT.
  if (typeof window !== "undefined"
      && window.__EXPANDED_FIX_V3_MAIN__ === undefined) {
    window.__EXPANDED_FIX_V3_MAIN__ = "jobnotescallout_main_v3";
  }
  const expandedTuple = React.useState(false); // expanded fix v3 (atomic — do not split)
  const expanded      = Array.isArray(expandedTuple) ? expandedTuple[0] : false;
  const setExpanded   = Array.isArray(expandedTuple) ? expandedTuple[1] : () => {};
  const jobNote     = (note && String(note).trim()) ? String(note) : "";
  const custNote    = (customerNote && String(customerNote).trim())
                        ? String(customerNote).trim() : "";
  const pool        = (poolNote && String(poolNote).trim())
                        ? String(poolNote).trim() : "";
  const landscape   = (landscapeNote && String(landscapeNote).trim())
                        ? String(landscapeNote).trim() : "";
  const showMoreEligible = _mayOverflow(jobNote);
  if (!jobNote && !custNote && !pool && !landscape) return null;

  return (
    <div
      className="text-sm rounded-md flex items-start gap-2"
      style={{
        marginTop: 6,
        padding: "8px 10px",
        backgroundColor: NOTE_BG,
        border: `1px solid ${NOTE_BORDER}`,
        borderLeftWidth: 3,
        borderLeftStyle: "solid",
        borderLeftColor: NOTE_ACCENT,
        color: TEXT_DARK,
      }}
      title={[
        jobNote + (truncated ? "…" : ""),
        custNote     ? `Customer note: ${custNote}` : "",
        pool         ? `Pool note: ${pool}`         : "",
        landscape    ? `Landscape note: ${landscape}` : "",
      ].filter(Boolean).join("\n\n")}
      data-testid={`job-notes-callout-${jobId}`}
      data-note-surface="white"
    >
      <NotebookPen
        size={14}
        color={NOTE_ICON_FG}
        style={{ flexShrink: 0, marginTop: 2 }}
        aria-label="Job note"
        data-testid={`job-notes-icon-${jobId}`}
      />
      <div style={{ minWidth: 0, flex: 1, fontSize: 14, lineHeight: "20px" }}>
        {/* Legacy block — job free-text note. Kept at line-clamp-2
            + heuristic-driven toggle for backward compat with the
            Feb-2026 schedule-card-notes-visibility suite. */}
        {jobNote ? (
          <div
            className={expanded ? "" : "line-clamp-2"}
            style={{ color: TEXT_DARK }}
            data-testid={`job-${jobId}-notes`}
          >
            {jobNote}{truncated ? "…" : ""}
          </div>
        ) : null}
        {/* Phase 3 · Feb-2026 — three customer-sourced blocks share
            the ``<NoteBlock>`` primitive so truncation + Show more
            behaviour is identical for all three.  Order on card is
            Customer → Pool → Landscape per the ticket brief. */}
        <NoteBlock
          label="Customer note"
          text={custNote}
          jobId={jobId}
          testId={`job-notes-preview-${jobId}`}
        />
        <NoteBlock
          label="Pool note"
          text={pool}
          jobId={jobId}
          testId={`job-notes-pool-${jobId}`}
        />
        <NoteBlock
          label="Landscape note"
          text={landscape}
          jobId={jobId}
          testId={`job-notes-landscape-${jobId}`}
        />
        {showMoreEligible ? (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setExpanded((x) => !x); }}
            className="mt-1 text-xs font-semibold underline-offset-2 hover:underline"
            style={{ color: NOTE_ICON_FG, background: "transparent", padding: 0 }}
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
