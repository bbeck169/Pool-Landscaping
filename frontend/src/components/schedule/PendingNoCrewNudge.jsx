/**
 * Feb-2026 Enhancement — pending-no-crew admin nudge banner.
 *
 * Rendered near the top of ``/schedule`` for admin / manager /
 * super_admin roles. Fetches
 * ``GET /api/schedule/unassigned-pending-stale?days=7`` and shows
 * a small yellow banner when the count > 0. Session-only dismiss:
 * the banner reappears on the next full-page load if the condition
 * still holds — surfacing chronic dispatch neglect without being
 * naggy inside a single work session.
 */
import React from "react";
import { AlertTriangle, X } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useNavigate } from "react-router-dom";

const _DISMISS_SESSION_KEY = "schedule.pendingNoCrewNudge.dismissed";
const _DAYS = 7;

const _ADMIN_ROLES = new Set(["admin", "manager", "super_admin"]);


export default function PendingNoCrewNudge({ user }) {
  const [count, setCount] = React.useState(null);
  const [dismissed, setDismissed] = React.useState(false);
  const navigate = useNavigate();

  React.useEffect(() => {
    // Session-scoped: reappears on the next full page load.
    try {
      if (sessionStorage.getItem(_DISMISS_SESSION_KEY) === "1") {
        setDismissed(true);
      }
    } catch { /* private-mode / sandboxed */ }
  }, []);

  React.useEffect(() => {
    if (!user || !_ADMIN_ROLES.has(user.role)) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get(
          `/schedule/unassigned-pending-stale?days=${_DAYS}`,
        );
        if (!cancelled) setCount(Number(r?.count || 0));
      } catch {
        if (!cancelled) setCount(0);
      }
    })();
    return () => { cancelled = true; };
  }, [user?.role]);   // eslint-disable-line react-hooks/exhaustive-deps

  const dismiss = () => {
    try {
      sessionStorage.setItem(_DISMISS_SESSION_KEY, "1");
    } catch { /* ignore */ }
    setDismissed(true);
  };

  if (!user || !_ADMIN_ROLES.has(user.role)) return null;
  if (dismissed) return null;
  if (count == null || count <= 0) return null;

  const label = count === 1
    ? "1 job has been pending assignment for over a week."
    : `${count} jobs have been pending assignment for over a week.`;

  return (
    <div
      className="rounded-md p-3 mb-3 flex items-start gap-3"
      style={{
        backgroundColor: "#FEF3C7",
        border: "1px solid #FCD34D",
        color: "#78350F",
      }}
      role="region"
      aria-label="Pending unassigned jobs nudge"
      data-testid="schedule-pending-no-crew-nudge"
    >
      <AlertTriangle size={18} className="shrink-0 mt-0.5" />
      <div className="flex-1 text-sm">
        <span data-testid="schedule-pending-no-crew-nudge-label">
          {label}
        </span>
      </div>
      <button
        type="button"
        onClick={() => navigate(
          "/schedule?filter=pending-unassigned-7d",
        )}
        className="text-xs font-semibold px-3 py-1.5 rounded-md shrink-0"
        style={{
          backgroundColor: "#B45309",
          color: "#FFFFFF",
          border: 0,
        }}
        data-testid="schedule-pending-no-crew-nudge-review"
        aria-label="Review pending unassigned jobs"
      >
        Review
      </button>
      <button
        type="button"
        onClick={dismiss}
        className="shrink-0 rounded-md p-1"
        style={{
          background: "transparent",
          border: 0,
          color: colors.muted,
        }}
        data-testid="schedule-pending-no-crew-nudge-dismiss"
        aria-label="Dismiss until next session"
        title="Dismiss until next session"
      >
        <X size={14} />
      </button>
    </div>
  );
}
