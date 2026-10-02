import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Trash2, MapPin, Clock, User, FileDown, Mail, RotateCw, Play, Check, AlertTriangle, Camera, X as XIcon, Plus } from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import { colors, money } from "@/theme";
import { formatCustomerName } from "@/utils/formatCustomerName";
import { Button, Skeleton, StatusPill, Chip, Modal, TextInput, Toast } from "@/components/ui-kit";
import { useAuth } from "@/auth";
import { useAttendance } from "@/hooks/useAttendance";
import JobCostingPanel from "@/pages/budget/JobCostingPanel";
import MediaUploader from "@/components/media/MediaUploader";
import LineItemsSection from "@/pages/jobs/LineItemsSection";
import TimelineSection from "@/pages/jobs/TimelineSection";
import JobBeforeAfterPhotos from "@/components/jobs/JobBeforeAfterPhotos";
import ClickToCallButton from "@/components/telephony/ClickToCallButton";
import HardDeleteModal from "@/components/hard_delete/HardDeleteModal";
import { CustomerLink, AddressLink } from "@/components/customer";
// 2026-10-02 · Jobs Overhaul Phase 3a — inline Customer edit tile.
// Reused as-is from JobNew (same hydration + testid naming
// convention). TODO(jobs-overhaul-phase-3c): extract shared
// InlineEditTile if a second surface needs it.
import { CustomerCombobox } from "@/components/customers/CustomerCombobox";
import JobNew from "@/pages/jobs/JobNew";
// Feb-2026 · Slice 6 — 24h post-completion edit window UI.
import JobEditPanel from "@/pages/jobs/JobEditPanel";
// Phase C1 · Feb-2026 — admin follow-up controls (Sales Pipeline
// Follow-up column feeder). Rendered only for admin / super_admin /
// manager; techs never see it. Backend PATCH gate enforces the same.
import FollowUpEditor from "@/pages/jobs/FollowUpEditor";
// Feb-2026 · N5-T1 · PageHeader adoption sweep (Option A: replace).
import PageHeader from "@/components/layout/PageHeader";
// CHEM-LOCK · Feb-2026 — admin "Unlock for Edit" button + modal.
import JobUnlockButton from "@/pages/jobs/JobUnlockButton";

// 2026-10-02 · Jobs Overhaul Phase 3a — click-to-edit meta tile.
//
// Component-local by design — only JobDetail renders inline-edit
// tiles today, and a cross-cutting hook would be premature.  See
// the ``TODO(jobs-overhaul-phase-3c)`` on the import block for the
// extraction trigger.
//
// Behaviour contract (locked by
// ``frontend/src/pages/jobs/__tests__/JobDetail.inlineEdit.test.jsx``):
//   * Read mode — renders ``display`` (string) + optional ``subline``.
//     Clicking the display enters edit mode when ``editable`` is true.
//   * Edit mode:
//       - ``editType="date"``   → <input type="date">
//       - ``editType="number"`` → <input type="number" step={step}>
//       - ``editType="select"`` → <select> fed from ``options``
//     Enter commits; Escape reverts to the pre-edit ``rawValue``;
//     blur also commits (via onCommit).  ``onCommit`` is awaited; if
//     it returns ``false`` the editor stays open so the user can
//     retry without re-opening.
//   * Testids: ``{testid}`` on the display, ``{testid}-input`` on
//     the editor, ``{testid}-select`` for the select variant.
function InlineEditTile({
  icon: Icon, label, display, subline = null,
  editable, editType, rawValue, options = null, step,
  onCommit, testid,
}) {
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(rawValue);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => { setDraft(rawValue); }, [rawValue, editing]);

  const open = () => {
    if (!editable || saving) return;
    setDraft(rawValue);
    setEditing(true);
  };
  const commit = async () => {
    if (saving) return;
    setSaving(true);
    const ok = await onCommit(draft);
    setSaving(false);
    if (ok !== false) setEditing(false);
  };
  const cancel = () => {
    setDraft(rawValue);
    setEditing(false);
  };
  const onKeyDown = (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    else if (e.key === "Escape") { e.preventDefault(); cancel(); }
  };

  const inputTestid = editType === "select"
    ? `${testid}-select` : `${testid}-input`;
  return (
    <div
      className="rounded-xl p-3 flex items-start gap-2"
      style={{ backgroundColor: colors.surfaceSecondary }}
      data-testid={`${testid}-tile`}
    >
      <Icon size={14} className="mt-0.5" style={{ color: colors.muted }} />
      <div className="min-w-0 flex-1">
        <div
          className="text-xs uppercase font-semibold"
          style={{ color: colors.muted }}
        >
          {label}
        </div>
        {editing ? (
          editType === "select" ? (
            <select
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={onKeyDown}
              disabled={saving}
              className="text-sm font-semibold px-1 py-0.5 rounded w-full"
              style={{
                background: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={inputTestid}
            >
              {(options || []).map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          ) : (
            <input
              autoFocus
              type={
                editType === "number"
                  ? "number"
                  : editType === "time"
                    ? "time"
                    : "date"
              }
              step={editType === "number" ? (step || "0.01") : undefined}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commit}
              onKeyDown={onKeyDown}
              disabled={saving}
              className="text-sm font-semibold px-1 py-0.5 rounded w-full"
              style={{
                background: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={inputTestid}
            />
          )
        ) : (
          <button
            type="button"
            onClick={open}
            disabled={!editable}
            className={
              "text-sm font-semibold text-left w-full "
              + (editable ? "cursor-pointer hover:underline" : "cursor-default")
            }
            style={{
              color: colors.onSurface,
              background: "transparent", border: 0, padding: 0,
            }}
            data-testid={testid}
            aria-label={editable ? `Edit ${label}` : label}
          >
            {display}
          </button>
        )}
        {subline ? (
          <div
            className="text-xs mt-0.5"
            style={{ color: colors.muted }}
            data-testid={`${testid}-subline`}
          >
            {subline}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const attendance = useAttendance();
  const [job, setJob] = useState(null);
  const [customer, setCustomer] = useState(null);
  const [detail, setDetail] = useState(null);
  const [toast, setToast] = useState(null);
  const [emailModal, setEmailModal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // HARD-DELETE · HD-B · Feb-2026 — "Move to Trash" flow uses the
  // HD-A endpoints in a shared modal.
  const [hardDeleteOpen, setHardDeleteOpen] = useState(false);
  const [lightbox, setLightbox] = useState(null);
  // Task L+P · Feb-2026 — independent lightbox state for the new
  // Service Report Photos section.  Separate from ``lightbox``
  // (which indexes into ``job.photos``) because SR photos are a
  // different data source (``detail.service_report_photos``);
  // keeping them independent preserves the existing ``jd-lightbox``
  // testid contract on the legacy grid and gives the SR grid its
  // own ``job-detail-sr-photos-lightbox`` testid.
  const [srLightbox, setSrLightbox] = useState(null);
  // Feb-2026 · "+ New Scheduled Job" quick-action. Reuses <JobNew>
  // in ``renderMode="modal"`` so there is exactly one form
  // component in the codebase (no fork). Pre-fill defaults are
  // derived from the current job so scheduling another visit for
  // the same customer/property/technician is a one-tap flow.
  const [createOpen, setCreateOpen] = useState(false);
  // Task M+P · Feb-2026 — optimistic in-flight disable for the
  // ``jd-reopen`` button. Prevents double-clicks from racing the
  // idempotency envelope on the backend + gives the UI an
  // immediate visual acknowledgement while the reopen POST is
  // pending.  Reset on success/error.
  const [reopening, setReopening] = useState(false);
  // 2026-10-02 · Jobs Overhaul Phase 3a — inline-edit state.
  //
  // Scheduled / Technician / Price tiles plus the Customer field in
  // the header are now click-to-edit via the component-local
  // ``InlineEditTile`` + ``<CustomerCombobox>`` swap.  State lives
  // here (not inside the tile) so a save-rollback can revert the
  // local ``job`` denorm (``technician_name`` / ``customer_name``)
  // alongside the raw id.
  //
  // TODO(jobs-overhaul-phase-3c): extract shared InlineEditTile if
  // a second surface needs it. Right now JobDetail is the only
  // consumer so inline-component is the right scope.
  const [techOptions, setTechOptions] = useState([]);
  const [customerOptions, setCustomerOptions] = useState([]);
  const [customerEditing, setCustomerEditing] = useState(false);

  const isTech = user?.role === "technician";
  // Feb-2026 · admin-gate parity with mobile — ``super_admin`` has
  // every ``admin`` capability, so the JobDetail admin action row
  // (Work Order, Email, Delete, "+ New Scheduled Job") must render
  // for it too. Prior version silently hid the whole row from
  // super_admin sessions, which is why the "+ New Scheduled Job"
  // wasn't visible in the screenshot verification pass.
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const isCustomer = user?.role === "customer";
  const techLocked = isTech && !attendance.clockedIn;
  // Phase K6 · Feb-2026 — Completed Job Unlock.  These four roles
  // (plus super_admin above) can edit already-completed jobs +
  // upload media + attach notes past the 24h edit window; every
  // mutation writes a Communication-Timeline audit row so the
  // change is discoverable on the customer page.  Non-K6 roles
  // (customer, viewer, marketer, sales …) remain locked out.
  const K6_UNLOCK_ROLES = new Set([
    "super_admin", "admin", "manager", "tech", "technician", "owner",
  ]);
  const canEditCompleted =
    !isCustomer
    && K6_UNLOCK_ROLES.has(user?.role || "")
    && (job?.status === "completed");

  // Task M+P · Feb-2026 — Tech-visible Reopen.
  //   * ``isAssignedTech`` is a **client-side approximation** of
  //     the F1 crew-aware gate the backend enforces
  //     (``services.authz.is_tech_authorized_on_job``). We can
  //     only cheaply compare the job's denormalised
  //     ``technician_id`` against the caller's tech id here —
  //     crew membership isn't part of the JobDetail payload, so
  //     a crew-only tech may not see the button even though the
  //     server would authorise them.  The server 403 is the
  //     authoritative gate; this heuristic just hides the
  //     button in the common (direct-assignment) case where we
  //     can already tell the user isn't the owner. UX-only
  //     approximation — NOT a security boundary.
  //   * ``canReopen`` = admin (completed OR cancelled) OR
  //     assigned tech (completed ONLY — E2 keeps ``cancelled``
  //     admin-only, matching the backend allowlist).
  const isAssignedTech =
    isTech
    && !!job?.technician_id
    && job.technician_id === (user?.technician_id || user?.id);
  const canReopen = (
    (isAdmin && ["completed", "cancelled"].includes(job?.status))
    || (isAssignedTech && job?.status === "completed")
  );

  const load = async () => {
    try {
      const j = await api.get(`/jobs/${id}`);
      setJob(j);
      if (j.customer_id) {
        api.get(`/customers/${j.customer_id}`).then(setCustomer).catch(() => {});
      }
      // Slice M5 aggregator — used for the Line Items / Timeline sections
      // and the K1 photo/video remaining-slot counters. Customers never
      // reach this endpoint (403); silently swallow to keep customer
      // read paths — /customer/jobs/{id} — working.
      if (!isCustomer) {
        api.get(`/jobs/${id}/detail`).then(setDetail).catch(() => setDetail(null));
      }
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // 2026-10-02 · Jobs Overhaul Phase 3a — hydrate the inline-edit
  // picker option lists.  Technicians fetched when the tile would
  // be editable (i.e. the caller is NOT a technician).  Customers
  // fetched only when the Customer combobox is actually opened so
  // we don't pay the GET on every JobDetail load.  Both silent-
  // failing to keep the page useful for roles that lack the list
  // endpoints (e.g. the 403 on ``/customers`` for the customer
  // role itself).
  useEffect(() => {
    if (isTech || isCustomer) return;
    api.get("/technicians").then(setTechOptions).catch(() => setTechOptions([]));
  }, [isTech, isCustomer]);
  useEffect(() => {
    if (!customerEditing) return;
    if (customerOptions.length > 0) return;
    api.get("/customers?is_active=true")
      .then(setCustomerOptions)
      .catch(() => setCustomerOptions([]));
  }, [customerEditing, customerOptions.length]);

  // 2026-10-02 · Jobs Overhaul Phase 3a — optimistic PUT with
  // rollback on 4xx/5xx.  ``patch`` is a thin wrapper around
  // ``api.put("/jobs/{id}", { field: value })`` that:
  //   1. snapshots the pre-edit ``job`` object,
  //   2. applies the optimistic mutation on the local ``job`` via
  //      ``setJob``,
  //   3. awaits the server response and swaps in the authoritative
  //      row on success (so denorm cascades like ``customer_name``
  //      from the backend reassignment path land in state),
  //   4. restores the snapshot on failure + raises a toast.
  // Returns ``true`` on success / ``false`` on failure so the
  // caller can tailor the UI (e.g. keep the editor open after a
  // failed save vs collapse on success).
  const saveInline = async (patch, optimistic) => {
    const snapshot = job;
    try {
      if (optimistic) setJob({ ...job, ...optimistic });
      const updated = await api.put(`/jobs/${id}`, patch);
      if (updated && typeof updated === "object" && updated.id) {
        setJob(updated);
      } else {
        // Server returned a non-row envelope (older shape).  Refetch.
        await load();
      }
      return true;
    } catch (e) {
      setJob(snapshot);
      setToast({
        tone: "error",
        message: e?.message || "Save failed — reverted",
      });
      return false;
    }
  };

  useEffect(() => {
    // Belt-and-suspenders redirect for techs without a clock-in
    if (isTech && !attendance.loading && !attendance.clockedIn) {
      setToast({ tone: "error", message: "Clock in to open jobs" });
      setTimeout(() => navigate("/jobs"), 800);
    }
  }, [isTech, attendance.loading, attendance.clockedIn, navigate]);

  const act = async (path, body) => {
    try {
      const res = body === undefined
        ? await api.post(path)
        : await api.post(path, body || {});
      setToast({ tone: "success", message: "Done" });
      await load();
      return res;
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const onArrive = () => act(`/jobs/${id}/arrive`, { lat: 0, lng: 0 });
  const onOnMyWay = () => act(`/jobs/${id}/on-my-way`, { lat: 0, lng: 0 });
  // Task M+P · Feb-2026 — tech-visible reopen with rich error
  // toasts, optimistic in-flight disable, and success-refetch so
  // the checklist auto-unlocks (backend cleared the SR
  // ``submitted_at`` in Commit 1). Server ``detail.message`` wins
  // over any client fallback copy (mirrors the Task J
  // precedence pattern) so backend-authored context (e.g.
  // "Only completed jobs can be reopened") always surfaces
  // verbatim.
  const onReopen = async () => {
    if (reopening) return;
    setReopening(true);
    try {
      await api.post(`/jobs/${id}/reopen`);
      setToast({ tone: "success", message: "Job reopened" });
      await load();
    } catch (e) {
      const status = e?.status;
      // ``err.data.detail`` shape reference — backend emits
      //   403 → {"code": "reopen_forbidden", "detail": <msg>}
      //   400 → "Only completed [or cancelled] jobs can be reopened"
      //         (plain string — surfaces via ``e.message``)
      //   409 → idempotency envelope conflict (rare; user retry)
      const detail = e?.data?.detail;
      const serverMsg =
        (detail && typeof detail === "object" && (detail.detail || detail.msg || detail.message))
        || (typeof detail === "string" ? detail : null)
        || e?.message;
      let toastMsg = serverMsg;
      if (status === 403) {
        toastMsg = "You aren't authorized to reopen this job.";
      } else if (status === 409) {
        toastMsg = "Cannot reopen — job is not in a reopenable state.";
      } else if (status === 400) {
        // Server-provided precondition string wins (e.g.
        // "Only completed jobs can be reopened"); fallback if
        // absent.
        toastMsg = serverMsg || "This job can't be reopened right now.";
      } else if (!status || status >= 500) {
        toastMsg = "Something went wrong. Please try again.";
      }
      setToast({ tone: "error", message: toastMsg });
    } finally {
      setReopening(false);
    }
  };
  const onComplete = async () => {
    try {
      await api.put(`/jobs/${id}`, { status: "completed" });
      setToast({ tone: "success", message: "Job completed" });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  const onCancel = async () => {
    try {
      await api.put(`/jobs/${id}`, { status: "cancelled" });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  const onDelete = async () => {
    try {
      await api.del(`/jobs/${id}`);
      setToast({ tone: "success", message: "Job deleted" });
      setTimeout(() => navigate("/jobs"), 400);
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const downloadWorkOrder = () => {
    const token = localStorage.getItem(TOKEN_KEY);
    // The PDF endpoint returns raw bytes; open in a new tab with an
    // authenticated fetch → blob URL so the JWT header is included.
    fetch(`${process.env.REACT_APP_BACKEND_URL}/api/jobs/${id}/work-order.pdf`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `work-order-${id.slice(0, 8)}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setToast({ tone: "error", message: e.message }));
  };

  if (!job) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <Skeleton style={{ height: 160 }} />
      </div>
    );
  }

  const fr = {
    checklist: job.checklist || [],
    chemicalReadings: job.chemical_readings || {},
    chemicalsAdded: job.chemicals_added || [],
    customerNotes: job.customer_notes || "",
    internalNotes: job.internal_notes || "",
  };

  const toggleChecklistItem = async (cid) => {
    if (techLocked) return;
    const next = fr.checklist.map((c) => (c.id === cid ? { ...c, done: !c.done } : c));
    try {
      await api.put(`/jobs/${id}/field-report`, { checklist: next });
      await load();
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };

  const canAct = !techLocked && !isCustomer;

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="job-detail">
      <button
        onClick={() => navigate("/jobs")}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> All jobs
      </button>

      {/* Feb-2026 · N5-T1 · PageHeader adoption. The job title
          + admin action row (New Scheduled Job / Work Order /
          Email / Delete) hoist into the shared <PageHeader/>.
          The identity chrome BELOW (StatusPill, service_type,
          customer link, address, click-to-call, meta strip, and
          the primary action bar) stays put — those are data-rich
          in-body chrome, not header chrome. */}
      <PageHeader
        title={job.title}
        actions={
          isAdmin ? (
            <div className="flex gap-2 flex-wrap" data-testid="jd-admin-action-row">
              <Button
                variant="ghost"
                onClick={() => setCreateOpen(true)}
                testid="jd-new-scheduled-job"
              >
                <Plus size={14} /> New Scheduled Job
              </Button>
              <Button variant="ghost" onClick={downloadWorkOrder} testid="jd-workorder">
                <FileDown size={14} /> Work Order
              </Button>
              <Button variant="ghost" onClick={() => setEmailModal(true)} testid="jd-email">
                <Mail size={14} /> Email
              </Button>
              <Button variant="danger" onClick={() => setConfirmDelete(true)} testid="jd-delete">
                <Trash2 size={14} /> Delete
              </Button>
              {/* HARD-DELETE · HD-B · Feb-2026 — routes through the
                  unified HD-A soft-delete surface. */}
              <Button
                variant="danger"
                onClick={() => setHardDeleteOpen(true)}
                testid="jd-hard-delete-btn"
              >
                <Trash2 size={14} /> Move to Trash
              </Button>
            </div>
          ) : null
        }
      />

      {/* Header */}
      <div
        className="rounded-2xl p-6 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <StatusPill status={job.status} />
              <span className="text-xs" style={{ color: colors.muted }}>
                {job.service_type}
              </span>
            </div>
            <p className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
              {customerEditing ? (
                /* 2026-10-02 · Jobs Overhaul Phase 3a — inline-edit
                    Customer field.  Combobox hydrates from the list
                    fetched by the ``customerEditing`` effect above
                    (same ``/customers?is_active=true`` endpoint
                    JobNew uses).  Save fires on ``onChange`` (same
                    as JobNew) — on 4xx/5xx the ``saveInline``
                    wrapper rolls back ``job`` state before the
                    denorm leaks into the header. Cancel = ✕ button
                    beside the combobox. */
                <span className="inline-flex items-center gap-2">
                  <span style={{ minWidth: 240, display: "inline-block" }}>
                    <CustomerCombobox
                      customers={customerOptions}
                      value={customer?.id || job?.customer_id || ""}
                      onChange={async (newCid) => {
                        if (!newCid || newCid === (customer?.id || job?.customer_id)) {
                          setCustomerEditing(false);
                          return;
                        }
                        const picked = customerOptions.find((c) => c.id === newCid);
                        const ok = await saveInline(
                          { customer_id: newCid },
                          {
                            customer_id: newCid,
                            customer_name: picked ? picked.name : "",
                            property_id: undefined,
                            address: "",
                          },
                        );
                        if (ok) {
                          setCustomerEditing(false);
                          if (picked) setCustomer(picked);
                        }
                      }}
                      testid="jd-customer-combobox"
                    />
                  </span>
                  <button
                    type="button"
                    onClick={() => setCustomerEditing(false)}
                    aria-label="Cancel customer edit"
                    className="text-xs underline"
                    style={{ color: colors.muted }}
                    data-testid="jd-customer-edit-cancel"
                  >
                    cancel
                  </button>
                </span>
              ) : (
                <>
                  <CustomerLink
                    customerId={customer?.id || job?.customer_id}
                    name={formatCustomerName(job)}
                    className="font-semibold"
                    data-testid="job-detail-customer-name"
                  />
                  {!isCustomer && !isTech ? (
                    <button
                      type="button"
                      onClick={() => setCustomerEditing(true)}
                      aria-label="Edit customer"
                      className="ml-1.5 text-xs underline"
                      style={{ color: colors.muted }}
                      data-testid="jd-customer-edit-btn"
                    >
                      edit
                    </button>
                  ) : null}
                </>
              )}
              <span className="mx-1.5">·</span>
              <MapPin size={12} className="inline" /> {job.address ? <AddressLink address={job.address} /> : "—"}
            </p>
            {/* Phase 6B · Feb 2026 — one-click call to the job's
                customer. Falls back to tel: for tech mobile-web. */}
            {(() => {
              const p =
                (customer && customer.mobiles && customer.mobiles[0]?.number_e164) ||
                customer?.phone || job.customer_phone;
              if (!p) return null;
              return (
                <div className="mt-2" data-testid="jd-click-to-call-wrapper">
                  <ClickToCallButton
                    phoneNumber={p}
                    entityKind="job"
                    entityId={job.id}
                    label="Call customer"
                    size="sm"
                    testIdPrefix="jd-click-to-call"
                  />
                </div>
              );
            })()}
          </div>
        </div>

        {/* Action bar */}
        <div className="flex flex-wrap gap-2 mt-5">
          {isAdmin ? (
            <>
              {job.status !== "completed" ? (
                <Button onClick={onComplete} testid="jd-complete">
                  <Check size={14} /> Complete
                </Button>
              ) : null}
              {job.status !== "cancelled" ? (
                <Button variant="ghost" onClick={onCancel} testid="jd-cancel">Cancel</Button>
              ) : null}
            </>
          ) : null}
          {/* Task M+P · Feb-2026 — Reopen surfaces for admin
              (completed OR cancelled) AND assigned technician
              (completed only, per E2).  Hoisted out of the admin
              branch so techs can self-serve a "missed reading /
              missed photo" fix; the backend F1 crew-aware gate
              is authoritative — 403 falls through to the toast
              matrix in ``onReopen``.  ``jd-reopen`` testid
              preserved verbatim so Task M+P Commit 2 pytest and
              downstream vitest continue to key off it. */}
          {canReopen ? (
            <Button onClick={onReopen} disabled={reopening} testid="jd-reopen">
              <RotateCw size={14} /> {reopening ? "Reopening…" : "Reopen"}
            </Button>
          ) : null}
          {isTech && canAct ? (
            <>
              <Button onClick={onOnMyWay} testid="jd-onmyway">
                <MapPin size={14} /> On My Way
              </Button>
              <Button onClick={onArrive} testid="jd-arrive">
                <Play size={14} /> Arrive
              </Button>
              <Button onClick={onComplete} testid="jd-tech-complete">
                <Check size={14} /> Complete
              </Button>
            </>
          ) : null}
          {techLocked ? (
            <div
              className="flex items-center gap-2 text-sm font-semibold px-3 py-2 rounded-lg"
              style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
              data-testid="jd-lock-notice"
            >
              🔒 Clock in on mobile to enable actions
            </div>
          ) : null}
          {/* CHEM-LOCK · Feb-2026 — Admin-only unlock button for
              submitted-and-locked jobs. Component internally decides
              whether to render (admin role + locked SR + not
              already unlocked). Placed at the tail of the action
              row so it never disturbs the primary action layout. */}
          <JobUnlockButton
            job={job}
            user={user}
            onUnlocked={() => load()}
          />
        </div>

        {/* Phase K6 · Feb-2026 — Editing-after-completion banner.
            Renders whenever the job is ``completed`` and the current
            user belongs to the K6 unlock set.  The banner sits
            directly above the meta strip + tabs so it's the FIRST
            thing an operator sees when they scroll into the edit
            controls.  Every subsequent PATCH is server-side logged
            to the Communication Timeline via
            ``audit_events.job_edited_after_completion``. */}
        {canEditCompleted ? (
          <div
            className="flex items-start gap-3 rounded-2xl p-3 mt-5"
            style={{ background: "#FEF3C7",
                        border: "1px solid #FCD34D",
                        color: "#78350F" }}
            role="status"
            data-testid="jd-k6-edit-after-completion-banner"
          >
            <span aria-hidden className="text-xl leading-none">🕒</span>
            <div className="text-sm">
              <div className="font-bold mb-0.5">
                Editing after completion — this will be logged
              </div>
              <div style={{ color: "#92400E" }}>
                This job is marked <b>completed</b>. Changes you make
                here (notes, media, price) are recorded on the
                customer's Communication Timeline with your name and
                the fields you touched. If a paid invoice is linked
                to this job, priced fields are blocked until the
                invoice is voided.
              </div>
            </div>
          </div>
        ) : null}

        {/* Meta strip — Price hidden for technicians (Phase 16C add-on).
            2026-10-02 · Jobs Overhaul Phase 3a — tiles are now
            inline-editable (Scheduled / Technician / Price). Click a
            tile to edit; Enter saves, Escape reverts, blur also
            saves.  Optimistic UI with rollback on 4xx/5xx via
            ``saveInline`` above.  Price gate preserves the existing
            ``isTech`` invariant — do NOT widen. */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-5">
          <InlineEditTile
            icon={Clock}
            label="Scheduled"
            display={job.scheduled_date || "Not scheduled"}
            subline={
              job.scheduled_start
                ? `Start: ${String(job.scheduled_start).slice(11, 16) || job.scheduled_start}`
                : null
            }
            editable={!isCustomer}
            editType="date"
            rawValue={job.scheduled_date || ""}
            onCommit={(v) =>
              saveInline(
                { scheduled_date: v || null },
                { scheduled_date: v },
              )
            }
            testid="jd-tile-scheduled"
          />
          {/*
            Feb-2026 · Crew-fallback in the Technician meta cell.
            Reads:
              1. ``technician_name`` (backend read-time cascade
                  fills this via ``resolve_technician_names`` when
                  ``technician_id`` is set but the denorm is stale).
              2. ``crew_name`` (denormalized on the job at
                  create/update — Crew Phase A) — surfaced as
                  "Crew: <name>" so an unassigned-tech-but-
                  assigned-crew job doesn't render as "Unassigned".
              3. Fallback "Unassigned" literal.
          */}
          <InlineEditTile
            icon={User}
            label="Technician"
            display={
              job.technician_name
                || (job.crew_name ? `Crew: ${job.crew_name}` : "Unassigned")
            }
            editable={!isTech && !isCustomer}
            editType="select"
            rawValue={job.technician_id || ""}
            options={[
              { value: "", label: "— Unassigned —" },
              ...techOptions.map((t) => ({
                value: t.id,
                label: t.name || t.email || t.id,
              })),
            ]}
            onCommit={(v) => {
              const picked = techOptions.find((t) => t.id === v);
              return saveInline(
                { technician_id: v || null },
                {
                  technician_id: v || null,
                  technician_name: picked
                    ? (picked.name || picked.email || "")
                    : (v ? job.technician_name : ""),
                },
              );
            }}
            testid="jd-tile-technician"
          />
          {isTech ? null : (
            <InlineEditTile
              icon={MapPin}
              label="Price"
              display={money(job.price || 0)}
              editable={!isCustomer}
              editType="number"
              step="0.01"
              rawValue={job.price != null ? String(job.price) : ""}
              onCommit={(v) => {
                const n = Number(v);
                if (Number.isNaN(n)) {
                  setToast({ tone: "error", message: "Price must be a number" });
                  return Promise.resolve(false);
                }
                return saveInline({ price: n }, { price: n });
              }}
              testid="jd-tile-price"
            />
          )}
        </div>
        {/* Feb-2026 · Jobs Overhaul Phase 3b — inline Start Time
            editor. Wraps into row 2 of the ``grid-cols-1 sm:grid-cols-3``
            above (admin sees 4 tiles total; tech sees 3). Disabled
            when ``scheduled_date`` is empty — the ISO synth
            requires a date half. On commit, builds the ISO via
            ``new Date(`${scheduled_date}T${hhmm}:00`).toISOString()``
            (UTC `Z` suffix — matches the existing fixture shape
            on ``scheduled_start`` writes elsewhere in the codebase).
            TODO(tenant-tz): synthesize scheduled_start in tenant
            local time once tenant tz is wired at the FE layer. */}
        <div
          className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-3"
          data-testid="jd-tile-start-time-row"
        >
          <InlineEditTile
            icon={Clock}
            label="Start Time"
            display={
              job.scheduled_start
                ? String(job.scheduled_start).slice(11, 16)
                  || String(job.scheduled_start)
                : (job.scheduled_date
                    ? "— Set start time —"
                    : "— Pick a date first —")
            }
            editable={!isCustomer && !!job.scheduled_date}
            editType="time"
            rawValue={
              job.scheduled_start
                ? String(job.scheduled_start).slice(11, 16)
                : ""
            }
            onCommit={(v) => {
              if (!v) {
                return saveInline(
                  { scheduled_start: null },
                  { scheduled_start: null },
                );
              }
              if (!job.scheduled_date) return Promise.resolve(false);
              let iso;
              try {
                iso = new Date(`${job.scheduled_date}T${v}:00`).toISOString();
              } catch (_e) {
                setToast({
                  tone: "error",
                  message: "Invalid start time",
                });
                return Promise.resolve(false);
              }
              return saveInline(
                { scheduled_start: iso },
                { scheduled_start: iso },
              );
            }}
            testid="jd-tile-start-time"
          />
        </div>
      </div>

      {/* K1 media counter chip — shows remaining photo/video slots so
          the tech knows the cap before opening the uploader. */}
      {detail?.media && !isCustomer ? (
        <div
          className="flex flex-wrap gap-2 mb-3"
          data-testid="jd-media-counters"
        >
          <span
            className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-full"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="jd-photo-counter"
          >
            <Camera size={11} /> {detail.media.photos_count}/{detail.media.photo_limit} photos
          </span>
          <span
            className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-full"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="jd-video-counter"
          >
            <Play size={11} /> {detail.media.videos_count}/{detail.media.video_limit} videos
          </span>
        </div>
      ) : null}

      {/* Slice K2 · Line Items (server-side pricing projection for tech) */}
      {!isCustomer ? (
        <LineItemsSection jobId={job.id} jobStatus={job.status} user={user} />
      ) : null}

      {/* Feb-2026 · Slice 6 — 24h post-completion edit window. Renders
          an Edit button + Edit History for admin / assigned tech.
          Customer view MUST NOT see the edit affordance (they view
          the read-only portal service report instead). */}
      {!isCustomer ? (
        <JobEditPanel
          job={job}
          onEdited={(fresh) => setJob(fresh)}
        />
      ) : null}

      {/* Field Report card */}
      <div
        className="rounded-2xl p-6 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <h2 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>
          Field Report
        </h2>
        {fr.checklist.length ? (
          <ul className="mb-4 space-y-1" data-testid="jd-checklist">
            {fr.checklist.map((c) => (
              <li key={c.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={!!c.done}
                  onChange={() => toggleChecklistItem(c.id)}
                  disabled={!canAct}
                  data-testid={`jd-check-${c.id}`}
                />
                <span
                  style={{
                    color: c.done ? colors.muted : colors.onSurface,
                    textDecoration: c.done ? "line-through" : "none",
                  }}
                >
                  {c.label}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm mb-3" style={{ color: colors.muted }}>
            No checklist yet.
          </p>
        )}

        {Object.keys(fr.chemicalReadings || {}).length ? (
          <div className="mb-4">
            <div className="text-xs uppercase font-semibold mb-1" style={{ color: colors.muted }}>
              Chemical readings
            </div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(fr.chemicalReadings).map(([k, v]) => (
                <Chip key={k} label={`${k.toUpperCase()} · ${v}`} tone="brand" />
              ))}
            </div>
          </div>
        ) : null}

        {(fr.chemicalsAdded || []).length ? (
          <div className="mb-4">
            <div className="text-xs uppercase font-semibold mb-1" style={{ color: colors.muted }}>
              Chemicals added
            </div>
            <ul className="text-sm" style={{ color: colors.onSurface }}>
              {fr.chemicalsAdded.map((ca, i) => (
                <li key={i}>
                  · {ca.chemical || ca.name} — {ca.amount || ca.amount_oz} {ca.unit || "oz"}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {job.notes ? (
          <div className="mb-4">
            <div className="text-xs uppercase font-semibold mb-1" style={{ color: colors.muted }}>
              Job notes
            </div>
            <p className="text-sm whitespace-pre-wrap" style={{ color: colors.onSurface }}>
              {job.notes}
            </p>
          </div>
        ) : null}
      </div>

      {/* Phase F2a · Before & After Photos (F0-native, purpose-scoped).
          Non-customer: full upload + delete UI. Customer (F2c.2): the
          same component in ``readOnly`` mode — upload is hidden, delete
          is disabled, and buckets that have no files are suppressed so
          the customer portal doesn't render an empty shell. */}
      <JobBeforeAfterPhotos jobId={job.id} user={user} readOnly={isCustomer} />

      {/* Photos */}
      {(user?.role === "admin" || user?.role === "super_admin") ? (
        <JobCostingPanel jobId={job.id} />
      ) : null}
      {(job.photos || []).length ? (
        <div
          className="rounded-2xl p-6 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <h3 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>
            Photos
          </h3>
          <div className="grid grid-cols-3 md:grid-cols-4 gap-2" data-testid="jd-photos">
            {job.photos.map((p, i) => (
              <button
                key={i}
                onClick={() => setLightbox(i)}
                className="aspect-square overflow-hidden rounded-lg"
                style={{ border: `1px solid ${colors.border}` }}
                data-testid={`jd-photo-${i}`}
              >
                <img
                  src={p.url || p.data_url || p}
                  alt=""
                  className="w-full h-full object-cover"
                />
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* Task L+P · Feb-2026 — Service Report Photos section.
          Renders photos uploaded via the SR flow (Phase-27 upload
          path) that DON'T live on ``job.photos[]``.  Adjacent to
          the existing Photos section (above) — deliberately NOT
          merged so a user can distinguish "photos taken during the
          service report" from "photos attached to the job".
          Backend-side dedupe (SR wins on id collision) ensures the
          same photo never appears in both grids.  Section is
          suppressed entirely when the array is empty; render
          semantics mirror the existing Photos section.
       */}
      {(detail?.service_report_photos || []).length ? (
        <div
          className="rounded-2xl p-6 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid="job-detail-sr-photos"
        >
          <h3 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>
            Service Report Photos
          </h3>
          <div className="grid grid-cols-3 md:grid-cols-4 gap-2">
            {detail.service_report_photos.map((p, i) => (
              <button
                key={p.id || i}
                onClick={() => setSrLightbox(i)}
                className="aspect-square overflow-hidden rounded-lg"
                style={{ border: `1px solid ${colors.border}` }}
                data-testid={`job-detail-sr-photo-${i}`}
                title={p.created_at || p.label || ""}
              >
                <img
                  src={p.url}
                  alt={p.label || ""}
                  className="w-full h-full object-cover"
                />
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* Videos — sits next to Photos in the Media section. Hidden for customers. */}
      {job.id && !isCustomer ? (
        <div
          className="rounded-2xl p-6 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <h3 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>
            Videos
          </h3>
          <MediaUploader
            entityKind="job"
            entityId={job.id}
            existingVideos={job.videos || []}
            readonly={techLocked}
            onUploaded={(v) => setJob((j) => ({ ...j, videos: [...(j?.videos || []), v] }))}
            onDeleted={(vid) => setJob((j) => ({
              ...j,
              videos: (j?.videos || []).map((x) => x.id === vid ? { ...x, is_deleted: true } : x),
            }))}
            onPatched={(v) => setJob((j) => ({
              ...j,
              videos: (j?.videos || []).map((x) => x.id === v.id ? { ...x, ...v } : x),
            }))}
          />
        </div>
      ) : null}

      {/* Issues */}
      {(job.issues || []).length ? (
        <div
          className="rounded-2xl p-6 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <h3 className="text-lg font-bold mb-3" style={{ color: colors.onSurface }}>
            Service Issues
          </h3>
          <ul className="space-y-2">
            {job.issues.map((iss) => (
              <li
                key={iss.id}
                className="rounded-lg p-3 flex items-start gap-2"
                style={{ backgroundColor: colors.surfaceSecondary }}
              >
                <AlertTriangle size={14} className="mt-0.5" style={{ color: "#A16207" }} />
                <div className="flex-1">
                  <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                    {iss.title || iss.summary}
                  </div>
                  {iss.detail ? (
                    <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                      {iss.detail}
                    </div>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Slice M5 · Timeline of workstream events for this job. */}
      {!isCustomer && detail?.timeline ? (
        <TimelineSection events={detail.timeline.events || []} />
      ) : null}

      {/* Phase C1 · Feb-2026 — admin follow-up controls. Renders
          only for admin / super_admin / manager; techs and portal
          customers never see it. Backend PATCH gate returns 403 for
          non-admin/manager roles so the client + server stay in
          lock-step. */}
      {(isAdmin || user?.role === "manager") && job ? (
        <FollowUpEditor
          job={job}
          onSaved={load}
          onToast={setToast}
        />
      ) : null}

      {/* Lightbox */}
      {lightbox !== null && (job.photos || []).length ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ backgroundColor: "rgba(0,0,0,0.85)" }}
          onClick={() => setLightbox(null)}
          data-testid="jd-lightbox"
        >
          <button
            className="absolute top-4 right-4 text-white"
            onClick={() => setLightbox(null)}
          >
            <XIcon size={28} />
          </button>
          <img
            src={
              (job.photos[lightbox] || {}).url ||
              (job.photos[lightbox] || {}).data_url ||
              job.photos[lightbox]
            }
            alt=""
            className="max-h-[85vh] max-w-full rounded-lg"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      ) : null}

      {/* Task L+P · Feb-2026 — Service Report Photos lightbox.
          Independent from the ``jd-lightbox`` above because it
          indexes into a different data source
          (``detail.service_report_photos``).  Keeps the existing
          ``jd-lightbox`` testid + click-to-enlarge contract on
          the legacy grid intact and gives the SR grid its own
          scoped testid for tester scripts. */}
      {srLightbox !== null && (detail?.service_report_photos || []).length ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ backgroundColor: "rgba(0,0,0,0.85)" }}
          onClick={() => setSrLightbox(null)}
          data-testid="job-detail-sr-photos-lightbox"
        >
          <button
            className="absolute top-4 right-4 text-white"
            onClick={() => setSrLightbox(null)}
          >
            <XIcon size={28} />
          </button>
          <img
            src={(detail.service_report_photos[srLightbox] || {}).url}
            alt=""
            className="max-h-[85vh] max-w-full rounded-lg"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      ) : null}

      <EmailWorkOrderModal
        open={emailModal}
        onClose={() => setEmailModal(false)}
        job={job}
        customer={customer}
        onDone={(msg, tone = "success") => {
          setEmailModal(false);
          setToast({ tone, message: msg });
        }}
      />

      <Modal
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title="Delete job?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button variant="danger" onClick={onDelete} testid="jd-confirm-delete">Delete</Button>
          </>
        }
      >
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
          This removes the job permanently.
        </p>
      </Modal>

      {/* HARD-DELETE · HD-B · Feb-2026 — "Move to Trash" modal. */}
      <HardDeleteModal
        open={hardDeleteOpen}
        entityType="job"
        entityId={id}
        entityLabel={job?.title}
        testidPrefix="jd-hard-delete"
        onClose={() => setHardDeleteOpen(false)}
        onSuccess={() => {
          setHardDeleteOpen(false);
          const parent = job?.customer_id ? `/customers/${job.customer_id}` : "/jobs";
          setTimeout(() => navigate(parent), 400);
        }}
        onBlocked={() => setHardDeleteOpen(false)}
      />

      {/* Feb-2026 · "+ New Scheduled Job" modal. Reuses <JobNew> in
          modal mode with pre-filled defaults inherited from the
          current job. On success we stay on the current job's
          detail page and surface a toast — matches the reference
          UX described in the product brief. */}
      <Modal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        title="Schedule another job"
        wide
      >
        <div data-testid="jd-new-scheduled-job-modal">
          <JobNew
            renderMode="modal"
            initialValues={{
              customer_id: job.customer_id || "",
              property_id: job.property_id || "",
              technician_id: job.technician_id || "",
              // Feb-2026 bug fix — service_type MUST start blank so
              // the admin re-picks it deliberately for the next
              // visit; carrying the parent job's service through
              // was a bug that shipped with the initial "+ New
              // Scheduled Job" cut.
              service_type: "",
              scheduled_date: new Date().toISOString().slice(0, 10),
            }}
            onCancel={() => setCreateOpen(false)}
            onCreated={(created) => {
              setCreateOpen(false);
              const when = created?.scheduled_date || "today";
              const who = job.customer_name || "customer";
              setToast({
                tone: "success",
                message: `Job scheduled for ${who} on ${when}`,
              });
            }}
          />
        </div>
      </Modal>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

function EmailWorkOrderModal({ open, onClose, job, customer, onDone }) {
  const [to, setTo] = useState("");
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setTo(customer?.email || "");
      setSubject(`Work Order · ${job?.title || "Service"}`);
    }
  }, [open, customer, job]);

  const send = async () => {
    setBusy(true);
    try {
      const res = await api.post(`/jobs/${job.id}/work-order/email`, { to, subject });
      if (res.sent) onDone(`Work order emailed to ${res.to}`);
      else if (res.reason === "resend-not-configured")
        onDone("Resend not configured — email skipped (dev mode)", "info");
      else onDone(res.reason || "Email failed", "error");
    } catch (e) {
      onDone(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Email Work Order"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={send} disabled={busy || !to} testid="jd-email-send">
            {busy ? "Sending…" : "Send"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <TextInput label="TO" value={to} onChange={(e) => setTo(e.target.value)} testid="jd-email-to" />
        <TextInput label="SUBJECT" value={subject} onChange={(e) => setSubject(e.target.value)} />
      </div>
    </Modal>
  );
}
