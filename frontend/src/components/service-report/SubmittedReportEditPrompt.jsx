/**
 * Feb-2026 · TD-g2-admin-409-vs-mobile-unlock · WEB β fix.
 *
 * Dismissible banner that converts the shipped silent-short-
 * circuit for admin/super_admin/manager/owner on a
 * submitted service report into visible feedback. CTA points at
 * the shipped CHEM-LOCK ``JobUnlockButton`` (mounted at
 * ``JobDetail.jsx:791``) via the ``/jobs/{jid}#unlock`` deep-link.
 * Role set mirrors BE truth at ``jobs.py:4332`` + shipped FE at
 * ``JobUnlockButton.jsx:21`` — dispatcher is NOT included (BE
 * /jobs/{jid}/unlock would 403 them).
 *
 * Guardrails:
 *   - Non-destructive by default: appears ONLY when the admin
 *     actually ATTEMPTS to edit (``show`` prop toggled by parent
 *     on first field focus / change / toggle). Submitted reports
 *     still read-only without the banner on page view.
 *   - Role-aware: parents MUST only render this with ``role`` in
 *     the admin set. ``technician`` on own submitted report path
 *     keeps the shipped silent-short-circuit at
 *     ``ServiceReport.jsx:196`` + the ``service_reports.py:604-610``
 *     BE bypass — this component NEVER renders for techs.
 *   - Dismissible: close button, outside-click, Esc.
 *   - a11y: role="status" (non-blocking), aria-live="polite",
 *     explicit focusable CTA.
 *   - Does NOT fork a new unlock endpoint or primitive.
 */
import React from "react";
import { Unlock, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { colors } from "@/theme";


export default function SubmittedReportEditPrompt({
  show, onDismiss, jobId,
}) {
  const navigate = useNavigate();
  const ref = React.useRef(null);

  React.useEffect(() => {
    if (!show) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") onDismiss?.();
    };
    const onClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) {
        onDismiss?.();
      }
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [show, onDismiss]);

  if (!show) return null;

  const openUnlock = () => {
    onDismiss?.();
    if (jobId) {
      navigate(`/jobs/${jobId}#unlock`);
    }
  };

  return (
    <div
      ref={ref}
      role="status"
      aria-live="polite"
      className="rounded-lg border px-3 py-2 flex items-center gap-3 shadow-sm"
      style={{
        backgroundColor: colors.surface || "#fff",
        borderColor: colors.border || "#fde68a",
      }}
      data-testid="submitted-report-edit-prompt"
    >
      <Unlock size={16} aria-hidden style={{ color: colors.accent || "#b45309" }} />
      <span
        className="text-sm flex-1"
        style={{ color: colors.onSurface || "#1f2937" }}
      >
        This report is submitted. Unlock to edit.
      </span>
      <button
        type="button"
        onClick={openUnlock}
        className="rounded-md px-2 py-1 text-xs font-semibold border"
        style={{
          backgroundColor: colors.accent || "#f59e0b",
          color: colors.onAccent || "#1f2937",
          borderColor: colors.border || "#d97706",
        }}
        data-testid="submitted-report-edit-prompt-unlock-cta"
      >
        Unlock…
      </button>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="rounded-md p-1 opacity-70 hover:opacity-100"
        style={{ color: colors.onSurface || "#1f2937" }}
        data-testid="submitted-report-edit-prompt-close"
      >
        <X size={14} aria-hidden />
      </button>
    </div>
  );
}
