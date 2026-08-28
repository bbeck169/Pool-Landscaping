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
import JobTitleCombobox from "@/components/JobTitleCombobox";
// Feb 2026 · Same color-coded toggle as ``JobNew`` — one component
// keeps both surfaces consistent.
import WorkClassToggle from "@/components/jobs/WorkClassToggle";

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
    // Feb 2026 · Work-class dimension (service | repair). Backend
    // ``JobUpdate.work_class`` validates + persists on PUT; missing
    // legacy jobs read as "service" via ``services.work_class.
    // infer_work_class`` so the initial value here is safe to
    // default. Send-time normalization in the save handler.
    work_class:     (job?.work_class === "repair") ? "repair" : "service",
    // Feb 2026 · Address picker — a multi-property customer's job
    // can be re-pointed at another of their properties. The picker
    // is only rendered when the customer has ≥2 active properties
    // (see ``properties`` state below). Backend PUT
    // ``/api/jobs/{id}`` snapshots the target property's address +
    // coords onto the job on save.
    property_id:    job?.property_id || "",
    // Feb-2026 · Crew Phase A · Schedule Edit modal crew overlay.
    // Optional. When set alongside ``technician_id`` the tech remains
    // the lead (overlay-only decision). Validated in
    // ``routers/jobs.py::update_job`` against the caller's tenant.
    crew_id:        job?.crew_id || "",
  }));
  const [techs, setTechs] = useState([]);
  const [crews, setCrews] = useState([]);
  const [properties, setProperties] = useState([]);
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
      work_class:     (job.work_class === "repair") ? "repair" : "service",
      property_id:    job.property_id || "",
      crew_id:        job.crew_id || "",
    });
    setErr("");
    setConfirmDelete(false);
    api.get("/technicians")
      .then((rows) => setTechs(Array.isArray(rows) ? rows : []))
      .catch(() => setTechs([]));
    // Feb-2026 · Crew Phase A — hydrate the crew overlay picker.
    // Silent failure keeps the modal usable when the /crews endpoint
    // is 403 for the current role.
    api.get("/crews")
      .then((rows) => setCrews(Array.isArray(rows) ? rows : []))
      .catch(() => setCrews([]));
    // Feb 2026 · Fetch the customer's properties so we can render
    // the picker for multi-property customers. Failure is silent —
    // the picker just doesn't render, preserving the previous UX.
    if (job.customer_id) {
      api.get(`/customers/${job.customer_id}/properties`)
        .then((rows) => setProperties(Array.isArray(rows) ? rows : []))
        .catch(() => setProperties([]));
    } else {
      setProperties([]);
    }
  }, [open, job?.id, job?.customer_id]);   // eslint-disable-line react-hooks/exhaustive-deps

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
                       "technician_id", "notes", "status",
                       "work_class", "property_id", "crew_id"]) {
        // Feb 2026 · Compare against the same normalized ``work_class``
        // shape the initial state uses ("service" for missing/legacy),
        // so a modal open + immediate save does NOT emit a spurious
        // patch that stamps ``work_class`` onto every legacy job.
        const before = k === "work_class"
          ? ((job[k] === "repair") ? "repair" : "service")
          : (job[k] || "");
        const after = form[k] || "";
        if (after !== before) patch[k] = form[k];
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
        <JobTitleCombobox
          label="Title"
          value={form.title}
          onChange={(v) =>
            setForm((prev) => ({ ...prev, title: v }))
          }
          testid="schedule-job-edit-title"
        />
        {/* Feb 2026 · Work-class picker. Mirrors the segmented
            control on ``JobNew.jsx`` so the create + edit surfaces
            stay symmetric. testids match the ``jf-work-class-*``
            naming on the create form for consistency, prefixed with
            ``schedule-job-edit-`` so E2E can target the edit-modal
            instance specifically. */}
        <div>
          <label
            className="text-xs font-semibold uppercase tracking-wide"
            style={{ color: colors.muted }}
          >
            Type
          </label>
          <div className="mt-1">
            <WorkClassToggle
              value={form.work_class}
              onChange={(v) => setForm((f) => ({ ...f, work_class: v }))}
              disabled={busy}
              testIdPrefix="schedule-job-edit-work-class"
            />
          </div>
        </div>
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
        {/* Feb 2026 · Property (address) picker. Only rendered when
            the customer has ≥2 active properties — single-property
            customers see no clutter. Backend re-snapshots the
            selected property's address + coords onto the job on
            save; historical jobs stay accurate even if the property
            record is later edited. */}
        {properties.length >= 2 ? (
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide"
                   style={{ color: colors.muted }}>Address</label>
            <select
              value={form.property_id || ""}
              onChange={set("property_id")}
              className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm mt-1"
              style={{
                backgroundColor: colors.surface, color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="schedule-job-edit-property"
            >
              {properties.map((p) => {
                const label = p.label ? `${p.label} — ${p.address || ""}` : (p.address || p.id);
                return (
                  <option
                    key={p.id}
                    value={p.id}
                    data-testid={`schedule-job-edit-property-${p.id}`}
                  >
                    {label}
                  </option>
                );
              })}
            </select>
          </div>
        ) : null}
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
        {/*
          Feb-2026 · Crew Phase A · Schedule Edit crew overlay.
          Hidden when the /crews endpoint returned no rows (tech
          sessions get [] via the role gate — silently hides).
        */}
        {crews.length > 0 ? (
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide"
                   style={{ color: colors.muted }}>
              Crew <span style={{ textTransform: "none",
                                     color: colors.onSurfaceSecondary }}>
                (optional overlay)
              </span>
            </label>
            <select
              value={form.crew_id || ""}
              onChange={set("crew_id")}
              className="w-full px-3.5 py-2.5 rounded-lg outline-none text-sm mt-1"
              style={{
                backgroundColor: colors.surface, color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid="schedule-job-edit-crew"
            >
              <option value="">No crew</option>
              {crews.map((c) => {
                const memberCount = (c.members || c.tech_ids || []).length;
                const label = memberCount
                  ? `${c.name} · ${memberCount} member${memberCount === 1 ? "" : "s"}`
                  : c.name;
                return (
                  <option key={c.id} value={c.id}
                          data-testid={`schedule-job-edit-crew-item-${c.id}`}>
                    {label}
                  </option>
                );
              })}
            </select>
          </div>
        ) : null}
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
