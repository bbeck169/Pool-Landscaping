// Phase 17 · Feb-2026 — Shift Route dialog (temporary + permanent).
//
// Segmented control at top toggles between:
//   • This week only — override auto-reverts Saturday 23:59 tenant-tz.
//   • Permanent — mutates master + cascades this-week's jobs + audit.
//
// Fields:
//   • Target tech dropdown (color-swatched).
//   • Notes (optional).
//   • Same-day warning (surfaced when API returns same_day_warning).
//   • Existing-override conflict warning (surfaced on first
//     submit when API returns warning="existing_override_conflict").
//   • "I understand this is permanent" checkbox — required for
//     permanent mode; Confirm stays disabled otherwise.
import React from "react";
import { X, Sparkles, AlertTriangle, RotateCcw, Check } from "lucide-react";
import { toast } from "sonner";
import { colors } from "@/theme";
import { api } from "@/api";

function formatSaturday(tenantTz) {
  // We compute a display-only end-date label. The authoritative
  // ``end_at`` value is what the backend returns. Use browser's
  // ``Intl.DateTimeFormat`` with the tenant tz.
  const now = new Date();
  const dow = now.getDay(); // 0=Sun … 6=Sat
  const daysAhead = (6 - dow + 7) % 7;
  const sat = new Date(now);
  sat.setDate(now.getDate() + daysAhead);
  sat.setHours(23, 59, 0, 0);
  try {
    return new Intl.DateTimeFormat("en-US", {
      timeZone: tenantTz || "America/Phoenix",
      weekday: "long", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit", timeZoneName: "short",
    }).format(sat);
  } catch {
    return sat.toLocaleString();
  }
}

export default function ShiftRouteDialog({
  open,
  onClose,
  sourceTech,        // {id, name, color_hex}
  techs,             // full tech directory
  customerIds,       // stops being shifted (partial) or [] (whole_route)
  scope,             // "whole_route" | "partial"
  day,               // current day filter for whole-route (mon/…, or "all")
  tenantTz = "America/Phoenix",
  onSuccess = () => {},
}) {
  const [duration, setDuration] = React.useState("week");
  const [targetTechId, setTargetTechId] = React.useState("");
  const [notes, setNotes] = React.useState("");
  const [permanentAck, setPermanentAck] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [conflict, setConflict] = React.useState(null); // conflict payload

  React.useEffect(() => {
    if (open) {
      setDuration("week");
      setTargetTechId("");
      setNotes("");
      setPermanentAck(false);
      setConflict(null);
    }
  }, [open]);

  const otherTechs = React.useMemo(
    () => (techs || []).filter((t) => t.id !== sourceTech?.id),
    [techs, sourceTech],
  );

  const endLabel = formatSaturday(tenantTz);
  const isSaturdayToday = new Date().getDay() === 6;

  const confirmDisabled = !targetTechId || submitting
    || (duration === "permanent" && !permanentAck);

  const submit = async ({ force }) => {
    if (!targetTechId) return;
    setSubmitting(true);
    try {
      const body = {
        source_tech_user_id: sourceTech.id,
        target_tech_user_id: targetTechId,
        scope,
        customer_ids: scope === "partial" ? customerIds : undefined,
        duration,
        day: day && day !== "all" ? day : undefined,
        notes: notes || undefined,
        force: force === true,
      };
      const res = await api.post("/dispatch/reassign", body);
      if (res?.warning === "existing_override_conflict") {
        setConflict(res);
        return; // wait for the user to hit "Continue anyway"
      }
      const target = otherTechs.find((t) => t.id === targetTechId);
      if (duration === "permanent") {
        toast.success(
          `Permanently reassigned ${res.updated_customer_ids?.length || 0} ` +
          `customer(s) to ${target?.name || "tech"}.`,
        );
      } else if (res?.same_day_warning) {
        toast.success(
          `Shift saved — ends today at 11:59 PM. No effect after that.`,
        );
      } else {
        toast.success(
          `Shifted ${res.customer_ids?.length || 0} stop(s) to ${target?.name || "tech"} until Sat 11:59 PM.`,
        );
      }
      onSuccess(res);
      onClose();
    } catch (e) {
      toast.error(`Failed to shift route: ${e.message || e}`);
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;
  const targetTech = otherTechs.find((t) => t.id === targetTechId);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: "rgba(15, 23, 42, 0.55)" }}
      role="dialog"
      aria-modal="true"
      data-testid="shift-route-dialog"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="w-full max-w-lg rounded-2xl shadow-2xl"
        style={{ backgroundColor: colors.surface }}
      >
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="flex items-center gap-2">
            <RotateCcw size={16} style={{ color: colors.brand }} />
            <div className="text-base font-bold" style={{ color: colors.onSurface }}
                 data-testid="shift-route-dialog-title">
              Shift {scope === "whole_route" ? "entire route" : `${customerIds?.length || 0} stop(s)`}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-md hover:brightness-95"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
            data-testid="shift-route-dialog-close"
            aria-label="Close"
          >
            <X size={14} />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {/* Duration segmented control */}
          <div>
            <div
              className="text-xs uppercase tracking-wide font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              Duration
            </div>
            <div
              className="grid grid-cols-2 rounded-lg p-1"
              style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
              role="tablist"
              data-testid="shift-duration-segmented"
            >
              {[
                { key: "week", label: "This week only" },
                { key: "permanent", label: "Permanent" },
              ].map((d) => {
                const active = duration === d.key;
                return (
                  <button
                    key={d.key}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => setDuration(d.key)}
                    className="py-1.5 rounded-md text-sm font-semibold transition"
                    style={{
                      backgroundColor: active ? colors.brand : "transparent",
                      color: active ? "#fff" : colors.onSurface,
                    }}
                    data-testid={`shift-duration-${d.key}`}
                  >
                    {d.label}
                  </button>
                );
              })}
            </div>
            {duration === "week" ? (
              <div
                className="text-xs mt-2"
                style={{ color: colors.muted }}
                data-testid="shift-duration-week-help"
              >
                Ends {endLabel}. Automatically reverts on Sunday.
                {isSaturdayToday ? (
                  <span
                    className="inline-flex items-center gap-1 ml-1"
                    style={{ color: "#B45309" }}
                    data-testid="shift-same-day-warning"
                  >
                    <AlertTriangle size={11} /> Shift ends today — no effect after 11:59 PM.
                  </span>
                ) : null}
              </div>
            ) : (
              <div
                className="text-xs mt-2 rounded-md p-2"
                style={{
                  backgroundColor: "#FEF2F2",
                  color: "#991B1B",
                  border: "1px solid #FECACA",
                }}
                data-testid="shift-duration-permanent-help"
              >
                <AlertTriangle size={12} className="inline mr-1" />
                This will change the default tech going forward, not just this week.
              </div>
            )}
          </div>

          {/* Target tech */}
          <div>
            <div
              className="text-xs uppercase tracking-wide font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              Move to
            </div>
            <select
              value={targetTechId}
              onChange={(e) => setTargetTechId(e.target.value)}
              className="w-full rounded-lg px-3 py-2 text-sm font-semibold focus:outline-none"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="shift-target-tech-select"
            >
              <option value="">Pick a tech…</option>
              {otherTechs.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            {sourceTech ? (
              <div
                className="text-xs mt-1"
                style={{ color: colors.muted }}
                data-testid="shift-source-tech-label"
              >
                From: <strong>{sourceTech.name}</strong>
              </div>
            ) : null}
          </div>

          {/* Notes */}
          <div>
            <div
              className="text-xs uppercase tracking-wide font-semibold mb-1"
              style={{ color: colors.muted }}
            >
              Notes (optional)
            </div>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Reason for shift…"
              className="w-full rounded-lg px-3 py-2 text-sm focus:outline-none"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="shift-notes-input"
            />
          </div>

          {/* Permanent acknowledgement */}
          {duration === "permanent" && (
            <label
              className="flex items-start gap-2 cursor-pointer rounded-md p-2"
              style={{ backgroundColor: "#FFF7ED", border: "1px solid #FED7AA" }}
              data-testid="shift-permanent-ack-label"
            >
              <input
                type="checkbox"
                checked={permanentAck}
                onChange={(e) => setPermanentAck(e.target.checked)}
                className="mt-0.5"
                data-testid="shift-permanent-ack-checkbox"
              />
              <span className="text-xs" style={{ color: "#9A3412" }}>
                I understand this is permanent — the default tech will
                change going forward and this week's already-scheduled
                jobs will move to {targetTech?.name || "the new tech"}.
              </span>
            </label>
          )}

          {/* Conflict warning */}
          {conflict ? (
            <div
              className="rounded-md p-3 text-sm"
              style={{
                backgroundColor: "#FEF3C7",
                color: "#92400E",
                border: "1px solid #FDE68A",
              }}
              data-testid="shift-conflict-warning"
            >
              <AlertTriangle size={13} className="inline mr-1" />
              This will override an existing shift affecting{" "}
              <strong>{conflict.conflicts?.[0]?.customer_ids?.length || 0}</strong>{" "}
              customer(s). Continue anyway?
            </div>
          ) : null}
        </div>

        <div
          className="flex items-center justify-end gap-2 px-5 py-3"
          style={{ borderTop: `1px solid ${colors.border}` }}
        >
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold hover:brightness-95"
            style={{
              backgroundColor: colors.surfaceSecondary,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="shift-route-cancel-btn"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => submit({ force: !!conflict })}
            disabled={confirmDisabled}
            className="px-3 py-1.5 rounded-lg text-sm font-semibold text-white hover:brightness-95 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ backgroundColor: duration === "permanent" ? "#B91C1C" : colors.brand }}
            data-testid="shift-route-confirm-btn"
          >
            {conflict ? (
              <><Check size={12} className="inline mr-1" /> Continue anyway</>
            ) : duration === "permanent" ? (
              <>Permanently reassign</>
            ) : (
              <><Sparkles size={12} className="inline mr-1" /> Shift for this week</>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
