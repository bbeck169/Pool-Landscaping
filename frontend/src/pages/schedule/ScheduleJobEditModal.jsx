/**
 * Feb-2026 · Schedule-screen inline job edit modal.
 *
 * Small dedicated modal that lets ``super_admin | admin | manager``
 * edit a job without leaving the Schedule screen. Reuses the shared
 * ``Modal`` / ``Button`` / ``TextInput`` primitives — NO fork of the
 * new-job form (there's no consolidated edit form on JobDetail today,
 * so we build one here rather than repurposing ``JobNew``, which is
 * create-only and carries create-only concepts like ``cadence``).
 *
 * Editable fields mirror the ``JobUpdate`` shape that
 * ``PUT /api/jobs/{jid}`` accepts:
 *   title, service_type, scheduled_date, technician_id, notes, status.
 *
 * Also exposes an admin-only "Delete job" affordance that hits
 * ``DELETE /api/jobs/{id}`` — matches the delete pattern on
 * JobDetail (same 403 gating server-side).
 */
import React, { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Modal, Button, TextInput } from "@/components/ui-kit";

const SERVICE_TYPES = [
  "Pool Cleaning", "Repair", "Landscaping", "Inspection",
  "Installation", "Weekly Pool", "Chemical Balance", "Filter Clean",
];
const STATUSES = [
  { value: "scheduled",   label: "Scheduled" },
  { value: "in_progress", label: "In progress" },
  { value: "completed",   label: "Completed" },
  { value: "cancelled",   label: "Cancelled" },
];

export default function ScheduleJobEditModal({
  open,
  job,
  onClose,
  onSaved,
  onDeleted,
}) {
  const [form, setForm] = useState(() => ({
    title:          job?.title || "",
    service_type:   job?.service_type || "",
    scheduled_date: job?.scheduled_date || "",
    technician_id:  job?.technician_id || "",
    notes:          job?.notes || "",
    status:         job?.status || "scheduled",
  }));
  const [techs, setTechs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open || !job) return;
    // Re-seed when the caller swaps to a different job — keeps the
    // modal state fresh across multiple opens.
    setForm({
      title:          job.title || "",
      service_type:   job.service_type || "",
      scheduled_date: job.scheduled_date || "",
      technician_id:  job.technician_id || "",
      notes:          job.notes || "",
      status:         job.status || "scheduled",
    });
    setErr("");
    setConfirmDelete(false);
    api.get("/technicians")
      .then((rows) => setTechs(Array.isArray(rows) ? rows : []))
      .catch(() => setTechs([]));
  }, [open, job?.id]);

  if (!open || !job) return null;

  const set = (k) => (e) => {
    const v = e && e.target ? e.target.value : e;
    setForm((prev) => ({ ...prev, [k]: v }));
  };

  const onSave = async () => {
    setBusy(true);
    setErr("");
    try {
      // Only send changed fields so backend PUT respects
      // partial-update semantics and stays deterministic.
      const patch = {};
      for (const k of ["title", "service_type", "scheduled_date",
                       "technician_id", "notes", "status"]) {
        if ((form[k] || "") !== (job[k] || "")) patch[k] = form[k];
      }
      if (Object.keys(patch).length === 0) {
        onClose();
        setBusy(false);
        return;
      }
      const updated = await api.put(`/jobs/${job.id}`, patch);
      // Backend returns 200 with the job on success; a 403 raises.
      onSaved && onSaved({ ...job, ...patch, ...(updated || {}) });
    } catch (e) {
      setErr(String(e?.message || e || "Save failed"));
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async () => {
    setBusy(true);
    setErr("");
    try {
      await api.del(`/jobs/${job.id}`);
      onDeleted && onDeleted(job.id);
    } catch (e) {
      setErr(String(e?.message || e || "Delete failed"));
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Edit job"
      testid="schedule-job-edit-modal"
      wide
      footer={
        <div className="flex items-center justify-between w-full gap-2">
          <Button
            variant="danger"
            onClick={() => setConfirmDelete(true)}
            disabled={busy}
            testid="schedule-job-edit-delete"
          >
            <Trash2 size={14} /> Delete job
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={onSave} disabled={busy} testid="schedule-job-edit-save">
              {busy ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </div>
      }
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TextInput
          label="Title"
          value={form.title}
          onChange={set("title")}
          testid="schedule-job-edit-title"
        />
        <div>
          <label className="text-xs font-semibold uppercase tracking-wide"
                 style={{ color: colors.muted }}>Service Type</label>
          <select
            value={form.service_type}
            onChange={set("service_type")}
            className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm mt-1"
            style={{
              backgroundColor: colors.surface, color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="schedule-job-edit-service"
          >
            {!form.service_type ? <option value="">Choose a service…</option> : null}
            {SERVICE_TYPES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <TextInput
          type="date"
          label="Scheduled date"
          value={form.scheduled_date}
          onChange={set("scheduled_date")}
          testid="schedule-job-edit-date"
        />
        <div>
          <label className="text-xs font-semibold uppercase tracking-wide"
                 style={{ color: colors.muted }}>Technician</label>
          <select
            value={form.technician_id || ""}
            onChange={set("technician_id")}
            className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm mt-1"
            style={{
              backgroundColor: colors.surface, color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="schedule-job-edit-tech"
          >
            <option value="">Unassigned</option>
            {techs.map((t) => {
              // Feb-2026 · Assignable-user widen — admin / super_admin
              // / manager rows now appear in the picker alongside
              // techs (they're working owners, not just office
              // roles). Suffix a role hint so admins stand out.
              const r = String(t.role || "").toLowerCase();
              const suffix =
                r === "super_admin" ? " (Super Admin)"
                  : r === "admin"    ? " (Admin)"
                  : r === "manager"  ? " (Manager)"
                  : "";
              return (
                <option key={t.id} value={t.id}
                        data-testid={`schedule-job-edit-tech-opt-${t.id}`}>
                  {t.name}{suffix}
                </option>
              );
            })}
          </select>
        </div>
        <div>
          <label className="text-xs font-semibold uppercase tracking-wide"
                 style={{ color: colors.muted }}>Status</label>
          <select
            value={form.status}
            onChange={set("status")}
            className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm mt-1"
            style={{
              backgroundColor: colors.surface, color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="schedule-job-edit-status"
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-3">
        <label className="text-xs font-semibold uppercase tracking-wide"
               style={{ color: colors.muted }}>Notes</label>
        <textarea
          value={form.notes}
          onChange={set("notes")}
          rows={4}
          className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm mt-1"
          style={{
            backgroundColor: colors.surface, color: colors.onSurface,
            border: `1px solid ${colors.border}`, resize: "vertical",
          }}
          data-testid="schedule-job-edit-notes"
        />
      </div>

      {err ? (
        <div className="mt-3 text-sm font-semibold"
             style={{ color: colors.error }}
             data-testid="schedule-job-edit-error">
          {err}
        </div>
      ) : null}

      {confirmDelete ? (
        <div className="mt-3 p-3 rounded-lg"
             style={{ backgroundColor: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}` }}
             data-testid="schedule-job-edit-confirm-delete">
          <p className="text-sm font-semibold" style={{ color: colors.onSurface }}>
            Delete this job? This cannot be undone.
          </p>
          <div className="flex gap-2 mt-2">
            <Button variant="ghost" onClick={() => setConfirmDelete(false)} disabled={busy}>
              Keep job
            </Button>
            <Button
              variant="danger"
              onClick={onDelete}
              disabled={busy}
              testid="schedule-job-edit-confirm-delete-btn"
            >
              Yes, delete
            </Button>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
