import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Edit3,
  Trash2,
  MapPin,
  Clock,
  User,
  FileDown,
  Mail,
  RotateCw,
  Play,
  Check,
  AlertTriangle,
  Camera,
  X as XIcon,
} from "lucide-react";
import { api, TOKEN_KEY } from "@/api";
import { colors, money } from "@/theme";
import {
  PageHeader,
  Button,
  Skeleton,
  StatusPill,
  Chip,
  Modal,
  TextInput,
  Toast,
  EmptyState,
} from "@/components/ui-kit";
import { useAuth } from "@/auth";
import { useAttendance } from "@/hooks/useAttendance";

export default function JobDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const attendance = useAttendance();
  const [job, setJob] = useState(null);
  const [customer, setCustomer] = useState(null);
  const [toast, setToast] = useState(null);
  const [emailModal, setEmailModal] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [lightbox, setLightbox] = useState(null);

  const isTech = user?.role === "technician";
  const isAdmin = user?.role === "admin";
  const isCustomer = user?.role === "customer";
  const techLocked = isTech && !attendance.clockedIn;

  const load = async () => {
    try {
      const j = await api.get(`/jobs/${id}`);
      setJob(j);
      if (j.customer_id) {
        api.get(`/customers/${j.customer_id}`).then(setCustomer).catch(() => {});
      }
    } catch (e) {
      setToast({ tone: "error", message: e.message });
    }
  };
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

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
  const onReopen = () => act(`/jobs/${id}/reopen`);
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
            <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
              {job.title}
            </h1>
            <p className="text-sm mt-1" style={{ color: colors.onSurfaceSecondary }}>
              <span
                onClick={() => customer && navigate(`/customers/${customer.id}`)}
                className="font-semibold cursor-pointer hover:underline"
              >
                {job.customer_name}
              </span>
              <span className="mx-1.5">·</span>
              <MapPin size={12} className="inline" /> {job.address || "—"}
            </p>
          </div>
          {isAdmin ? (
            <div className="flex gap-2 flex-wrap">
              <Button variant="ghost" onClick={downloadWorkOrder} testid="jd-workorder">
                <FileDown size={14} /> Work Order
              </Button>
              <Button variant="ghost" onClick={() => setEmailModal(true)} testid="jd-email">
                <Mail size={14} /> Email
              </Button>
              <Button variant="danger" onClick={() => setConfirmDelete(true)} testid="jd-delete">
                <Trash2 size={14} /> Delete
              </Button>
            </div>
          ) : null}
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
              {["completed", "cancelled"].includes(job.status) ? (
                <Button onClick={onReopen} testid="jd-reopen">
                  <RotateCw size={14} /> Reopen
                </Button>
              ) : null}
              {job.status !== "cancelled" ? (
                <Button variant="ghost" onClick={onCancel} testid="jd-cancel">Cancel</Button>
              ) : null}
            </>
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
        </div>

        {/* Meta strip — Price hidden for technicians (Phase 16C add-on). */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-5">
          {[
            { icon: Clock, label: "Scheduled", value: job.scheduled_date || "Not scheduled" },
            { icon: User, label: "Technician", value: job.technician_name || "Unassigned" },
            ...(isTech ? [] : [{ icon: MapPin, label: "Price", value: money(job.price || 0) }]),
          ].map((c) => (
            <div
              key={c.label}
              className="rounded-xl p-3 flex items-start gap-2"
              style={{ backgroundColor: colors.surfaceSecondary }}
            >
              <c.icon size={14} className="mt-0.5" style={{ color: colors.muted }} />
              <div>
                <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>
                  {c.label}
                </div>
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                  {c.value}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

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

      {/* Photos */}
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
