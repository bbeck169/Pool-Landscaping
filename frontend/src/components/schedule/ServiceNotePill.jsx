/*! P0d · 2026-10-12 · Force chunk hash change to purge stale 5979.aad12649.chunk.js from downstream caches. If this file compiles, confirm the resulting chunk filename does NOT match .aad12649. */
import React, { useState, useCallback } from "react";
import { Droplets, Trees, Info } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { classifyServiceType } from "../../lib/serviceTypeGroups";

/**
 * Small "Note" chip surfaced on Schedule / Route / Calendar job rows.
 * Feb-2026 Note-pill polish ship · widened vocab Feb-2026 F8 ·
 * inline-preview Feb-2026 F8.1.
 *
 * Behavior:
 *   • Default state: pill only. Zero visual regression at rest.
 *   • Click / Enter / Space → expands to a truncated preview
 *     underneath the pill (~80 chars + "…more" if the note is
 *     longer). aria-expanded reflects the toggle. Preview text
 *     lives inside an ``aria-live="polite"`` region so screen
 *     readers announce it on expand.
 *   • Click "…more" (or click the pill again after the truncated
 *     preview) → toggles between truncated and full-text.
 *   • Middle-click / Ctrl-click on the pill still navigates to
 *     ``/jobs/{id}?focus=notes`` for the "read on the job page"
 *     path (preserved from the pre-F8.1 behavior).
 *
 * Icon + color routing is delegated to
 * ``@/lib/serviceTypeGroups::classifyServiceType`` so backend and
 * frontend share ONE substring vocab.
 *
 * Props:
 *   note         — string (renders nothing when null/empty)
 *   serviceType  — service_type string; routed via classifier
 *   jobId        — used for stable data-testids + deep-link target
 *   testid       — optional data-testid override
 */

const PREVIEW_MAX_CHARS = 80;

export function ServiceNotePill({ note, serviceType, jobId, testid, compact = false }) {
  const navigate = useNavigate();
  // Hooks must run unconditionally before the early return.
  const [expanded, setExpanded] = useState(false); // preview visible?
  const [full, setFull] = useState(false);         // preview full-text vs truncated?

  const onDeepLink = useCallback(() => {
    if (jobId) navigate(`/jobs/${jobId}?focus=notes`);
  }, [jobId, navigate]);

  const togglePill = useCallback(
    (e) => {
      // Middle-click / Ctrl-click / Cmd-click → old deep-link behavior.
      if (
        e?.metaKey || e?.ctrlKey || e?.button === 1
      ) {
        e.preventDefault();
        e.stopPropagation();
        onDeepLink();
        return;
      }
      if (e) e.stopPropagation();
      setExpanded((was) => {
        if (was) {
          // second click collapses the preview back to just the pill.
          setFull(false);
          return false;
        }
        return true;
      });
    },
    [onDeepLink],
  );

  const onKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        togglePill(e);
      }
    },
    [togglePill],
  );

  if (!note) return null;

  const group = classifyServiceType(serviceType);
  // Feb-2026 · Schedule Notes-pill visibility bump (user request) —
  // pill bg/text are uniformly yellow-200 + red-700 bold regardless
  // of service type so the "Note" chip stops competing with the pool
  // (blue) / landscape (green) group tints and reads as a warning.
  // The service-type icon (Droplets / Trees / Info) is retained so
  // tech / dispatcher still gets the group tell at a glance.
  // Tailwind token equivalents: bg-yellow-200 / text-red-700 /
  // border-yellow-400. Chosen for WCAG AA on the pill's small
  // bold text (≈4.6:1 contrast).
  let Icon;
  if (group === "landscape") Icon = Trees;
  else if (group === "pool") Icon = Droplets;
  else Icon = Info;
  const bg = "#FEF08A";     // yellow-200
  const fg = "#B91C1C";     // red-700
  const border = "#FACC15"; // yellow-400

  const safe = String(note);
  const overflow = safe.length > PREVIEW_MAX_CHARS;
  const truncated = overflow ? safe.slice(0, PREVIEW_MAX_CHARS) + "…" : safe;
  const shownText = full || !overflow ? safe : truncated;
  const pillTid = testid || `service-note-pill${jobId ? `-${jobId}` : ""}`;

  return (
    <div
      className="inline-flex flex-col items-start"
      style={{ maxWidth: "100%", minWidth: 0 }}
    >
      <button
        type="button"
        onClick={togglePill}
        onKeyDown={onKeyDown}
        onAuxClick={togglePill}
        title={safe.length > 120 ? safe.slice(0, 120) + "…" : safe}
        aria-expanded={expanded}
        aria-controls={`${pillTid}-preview`}
        data-testid={pillTid}
        className="inline-flex items-center gap-1 rounded-md font-bold cursor-pointer transition hover:opacity-90"
        style={{
          backgroundColor: bg,
          color: fg,
          border: `1px solid ${border}`,
          padding: compact ? "1px 6px" : "2px 8px",
          fontSize: compact ? 10 : 11,
        }}
      >
        <Icon size={compact ? 9 : 11} /> Note
      </button>
      {expanded ? (
        <div
          id={`${pillTid}-preview`}
          role="region"
          aria-live="polite"
          data-testid={`${pillTid}-preview`}
          className="mt-1 rounded-md"
          style={{
            backgroundColor: bg,
            border: `1px solid ${border}`,
            color: fg,
            padding: "6px 8px",
            fontSize: 12,
            lineHeight: "16px",
            maxWidth: "100%",
            wordBreak: "break-word",
            fontWeight: 700,
          }}
        >
          <span data-testid={`${pillTid}-preview-text`}>{shownText}</span>
          {overflow ? (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setFull((x) => !x);
              }}
              data-testid={`${pillTid}-more-toggle`}
              className="ml-1 underline-offset-2 hover:underline"
              style={{
                background: "transparent",
                border: 0,
                cursor: "pointer",
                color: fg,
                fontWeight: 700,
                padding: 0,
                fontSize: 11,
              }}
              aria-label={full ? "Collapse note" : "Expand full note"}
            >
              {full ? "less" : "…more"}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export default ServiceNotePill;
