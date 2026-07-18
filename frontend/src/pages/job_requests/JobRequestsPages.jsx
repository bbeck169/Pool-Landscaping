import React, { useEffect, useState } from 'react';
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Check, X as XIcon, Send } from 'lucide-react';
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import { PageHeader, Button, Modal, TextInput, Skeleton, EmptyState, Toast, Chip } from "@/components/ui-kit";

/**
 * Phase 56.4 — Job Request pages.
 *
 *   /request-job                    — tech / admin quick-action form
 *   /admin/job-requests             — admin table with approve/reject/convert
 *
 * Both mount from `App.js`. Backend endpoints under `/api/job-requests`
 * enforce RBAC: techs see only their own requests, admins see all.
 */

const PRIORITY_TONES = { urgent: "warning", normal: "brand" };
const STATUS_TONES = {
  pending: "warning",
  approved: "success",
  rejected: "error",
  converted: "brand",
};

export function RequestJobPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [customers, setCustomers] = useState([]);
  const [form, setForm] = useState({
    customer_id: "",
    customer_name_hint: "",
    customer_phone_hint: "",
    address_hint: "",
    service_type: "",
    scheduled_preference: "asap",
    priority: "normal",
    notes: "",
  });
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    // Techs may not have /customers access (Phase 56.2 blocks tech role
    // from the list) — swallow errors silently and fall back to hint-only.
    api.get("/customers?is_active=true").then(setCustomers).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e?.target?.value }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.service_type.trim()) {
      setToast({ tone: "error", message: "Service type is required" });
      return;
    }
    if (!form.customer_id && !form.customer_name_hint.trim() && !form.address_hint.trim()) {
      setToast({ tone: "error", message: "Pick a customer or add a name/address hint" });
      return;
    }
    setBusy(true);
    try {
      const res = await api.post("/job-requests", form);
      setToast({ tone: "success", message: `Request submitted (${res.id.slice(0, 8)}…). Admin will review.` });
      setTimeout(() => navigate("/"), 800);
    } catch (err) {
      setToast({ tone: "error", message: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="request-job-page">
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-1 text-sm font-semibold mb-4"
        style={{ color: colors.muted }}
      >
        <ArrowLeft size={14} /> Back
      </button>
      <PageHeader title="Request a Job" subtitle="Spotted work in the field? Route it through admin approval." />

      <form onSubmit={submit} className="space-y-4" data-testid="request-job-form">
        <div className="rounded-2xl p-5 space-y-3"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <div>
            <label className="text-xs font-semibold block mb-1" style={{ color: colors.onSurfaceSecondary }}>
              EXISTING CUSTOMER
            </label>
            <select
              value={form.customer_id}
              onChange={set("customer_id")}
              className="w-full px-3 py-2.5 rounded-lg text-sm"
              style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
              data-testid="rj-customer"
            >
              <option value="">— New / unknown (fill in the hints below) —</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>{c.name} · {c.phone || c.email || c.address || ""}</option>
              ))}
            </select>
          </div>
          <TextInput label="CUSTOMER NAME (hint)" value={form.customer_name_hint} onChange={set("customer_name_hint")} testid="rj-name-hint" />
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="CUSTOMER PHONE (hint)" value={form.customer_phone_hint} onChange={set("customer_phone_hint")} testid="rj-phone-hint" />
            <TextInput label="ADDRESS (hint)" value={form.address_hint} onChange={set("address_hint")} testid="rj-address-hint" />
          </div>
        </div>

        <div className="rounded-2xl p-5 space-y-3"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <TextInput label="SERVICE TYPE *" value={form.service_type} onChange={set("service_type")} testid="rj-service" />
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold block mb-1" style={{ color: colors.onSurfaceSecondary }}>WHEN</label>
              <select value={form.scheduled_preference} onChange={set("scheduled_preference")}
                      className="w-full px-3 py-2.5 rounded-lg text-sm"
                      style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="rj-when">
                <option value="asap">ASAP</option>
                <option value="this_week">This week</option>
                <option value="next_week">Next week</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold block mb-1" style={{ color: colors.onSurfaceSecondary }}>PRIORITY</label>
              <select value={form.priority} onChange={set("priority")}
                      className="w-full px-3 py-2.5 rounded-lg text-sm"
                      style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="rj-priority">
                <option value="normal">Normal</option>
                <option value="urgent">Urgent</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs font-semibold block mb-1" style={{ color: colors.onSurfaceSecondary }}>NOTES</label>
            <textarea value={form.notes} onChange={set("notes")} rows={4}
                      className="w-full px-3 py-2 rounded-lg text-sm"
                      style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="rj-notes" />
          </div>
        </div>

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={(e) => { e.preventDefault(); navigate(-1); }}>Cancel</Button>
          <Button type="submit" disabled={busy} testid="rj-submit">
            {busy ? "Submitting…" : (<><Send size={14} /> Submit request</>)}
          </Button>
        </div>
      </form>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}


export function AdminJobRequestsPage() {
  const [rows, setRows] = useState(null);
  const [status, setStatus] = useState("pending");
  const [toast, setToast] = useState(null);
  const [convertOpen, setConvertOpen] = useState(null);   // {req}
  const [rejectOpen, setRejectOpen] = useState(null);     // {req}

  const load = () => {
    setRows(null);
    const q = status ? `?status=${status}` : "";
    api.get(`/job-requests${q}`).then(setRows).catch(() => setRows([]));
  };
  useEffect(load, [status]);

  const approve = async (req) => {
    try {
      await api.patch(`/job-requests/${req.id}`, { status: "approved" });
      setToast({ tone: "success", message: "Approved — tech notified" });
      load();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="admin-job-requests">
      <PageHeader title="Job Requests" subtitle="Field-submitted work opportunities awaiting admin action." />

      <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="jr-filter-row">
        {["pending", "approved", "rejected", "converted", ""].map((s) => (
          <button key={s || "all"} onClick={() => setStatus(s)}
                  className="text-xs font-semibold px-2.5 py-1 rounded-full border transition"
                  style={{
                    borderColor: status === s ? colors.brand : colors.border,
                    backgroundColor: status === s ? colors.brand : "transparent",
                    color: status === s ? "#fff" : colors.onSurface,
                  }}
                  data-testid={`jr-filter-${s || "all"}`}>
            {s ? s.charAt(0).toUpperCase() + s.slice(1) : "All"}
          </button>
        ))}
      </div>

      {rows === null ? <Skeleton style={{ height: 200 }} /> :
       rows.length === 0 ? <EmptyState title="No job requests" hint="Field-submitted requests will appear here." /> :
       <div className="rounded-2xl overflow-hidden"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
         <table className="w-full text-sm" data-testid="jr-table">
           <thead>
             <tr style={{ backgroundColor: colors.surfaceSecondary }}>
               <th className="text-left px-3 py-2 font-semibold">Requested by</th>
               <th className="text-left px-3 py-2 font-semibold">Customer / hint</th>
               <th className="text-left px-3 py-2 font-semibold hidden md:table-cell">Service</th>
               <th className="text-left px-3 py-2 font-semibold hidden lg:table-cell">When</th>
               <th className="text-left px-3 py-2 font-semibold">Status</th>
               <th className="text-left px-3 py-2 font-semibold">Actions</th>
             </tr>
           </thead>
           <tbody>
             {rows.map((r) => (
               <tr key={r.id} style={{ borderTop: `1px solid ${colors.divider}` }} data-testid={`jr-row-${r.id}`}>
                 <td className="px-3 py-3">
                   <div className="font-semibold" style={{ color: colors.onSurface }}>{r.requested_by_name || "—"}</div>
                   <div className="text-xs" style={{ color: colors.muted }}>{new Date(r.created_at).toLocaleString()}</div>
                 </td>
                 <td className="px-3 py-3">
                   <div style={{ color: colors.onSurface }}>
                     {r.customer_name_hint || (r.customer_id ? "Existing customer" : "—")}
                   </div>
                   <div className="text-xs" style={{ color: colors.muted }}>
                     {r.address_hint || r.customer_phone_hint || ""}
                   </div>
                 </td>
                 <td className="px-3 py-3 hidden md:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                   {r.service_type || "—"}
                 </td>
                 <td className="px-3 py-3 hidden lg:table-cell" style={{ color: colors.onSurfaceSecondary }}>
                   <Chip label={r.scheduled_preference} tone="neutral" />
                   {r.priority === "urgent" ? <span className="ml-2"><Chip label="URGENT" tone={PRIORITY_TONES.urgent} /></span> : null}
                 </td>
                 <td className="px-3 py-3">
                   <Chip label={r.status} tone={STATUS_TONES[r.status] || "neutral"} />
                 </td>
                 <td className="px-3 py-3">
                   {r.status === "pending" ? (
                     <div className="flex gap-1">
                       <button onClick={() => approve(r)}
                               className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded"
                               style={{ color: "#166534", backgroundColor: "#DCFCE7", border: "1px solid #86EFAC" }}
                               data-testid={`jr-approve-${r.id}`}>
                         <Check size={12} /> Approve
                       </button>
                       <button onClick={() => setConvertOpen({ req: r })}
                               className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded"
                               style={{ color: "#fff", backgroundColor: colors.brand, border: 0 }}
                               data-testid={`jr-convert-${r.id}`}>
                         Convert →
                       </button>
                       <button onClick={() => setRejectOpen({ req: r, reason: "" })}
                               className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded"
                               style={{ color: "#991B1B", backgroundColor: "#FEF2F2", border: "1px solid #FCA5A5" }}
                               data-testid={`jr-reject-${r.id}`}>
                         <XIcon size={12} /> Reject
                       </button>
                     </div>
                   ) : r.status === "converted" && r.converted_job_id ? (
                     <a href={`/jobs/${r.converted_job_id}`} className="text-xs font-semibold underline" style={{ color: colors.brand }}>
                       View job
                     </a>
                   ) : null}
                 </td>
               </tr>
             ))}
           </tbody>
         </table>
       </div>}

      <ConvertModal req={convertOpen?.req} open={!!convertOpen} onClose={() => setConvertOpen(null)}
                    onDone={() => { setConvertOpen(null); load(); setToast({ tone: "success", message: "Converted to job" }); }}
                    onError={(m) => setToast({ tone: "error", message: m })} />
      <RejectModal req={rejectOpen?.req} open={!!rejectOpen} onClose={() => setRejectOpen(null)}
                    onDone={() => { setRejectOpen(null); load(); setToast({ tone: "success", message: "Request rejected" }); }}
                    onError={(m) => setToast({ tone: "error", message: m })} />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}


function ConvertModal({ req, open, onClose, onDone, onError }) {
  const [customers, setCustomers] = useState([]);
  const [form, setForm] = useState({
    customer_id: "", title: "", service_type: "", scheduled_date: "",
    technician_id: "", price: "", address: "", notes: "",
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open && req) {
      api.get("/customers?is_active=true").then(setCustomers).catch(() => {});
      setForm({
        customer_id: req.customer_id || "",
        title: `${req.service_type || "Service"} — ${req.customer_name_hint || "Field request"}`,
        service_type: req.service_type || "",
        scheduled_date: "",
        technician_id: "",
        price: "",
        address: req.address_hint || "",
        notes: req.notes || "",
      });
    }
  }, [open, req]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e?.target?.value }));

  const submit = async () => {
    if (!form.customer_id || !form.title || !form.service_type || !form.scheduled_date) {
      onError?.("Customer, title, service type and scheduled date are required");
      return;
    }
    setBusy(true);
    try {
      await api.post(`/job-requests/${req.id}/convert`, {
        ...form,
        price: form.price ? Number(form.price) : null,
        technician_id: form.technician_id || null,
      });
      onDone?.();
    } catch (e) { onError?.(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Modal open={open} onClose={() => (busy ? null : onClose())} title="Convert to Job"
           testid="jr-convert-modal"
           footer={<>
             <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
             <Button onClick={submit} disabled={busy} testid="jr-convert-submit">
               {busy ? "Converting…" : "Create Job"}
             </Button>
           </>}>
      {req ? (
        <div className="space-y-3">
          <div>
            <label className="text-xs font-semibold block mb-1" style={{ color: colors.onSurfaceSecondary }}>CUSTOMER *</label>
            <select value={form.customer_id} onChange={set("customer_id")}
                    className="w-full px-3 py-2.5 rounded-lg text-sm"
                    style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="jr-convert-customer">
              <option value="">— Pick a customer —</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <TextInput label="TITLE *" value={form.title} onChange={set("title")} testid="jr-convert-title" />
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="SERVICE TYPE *" value={form.service_type} onChange={set("service_type")} testid="jr-convert-service" />
            <TextInput label="SCHEDULED DATE * (YYYY-MM-DD)" value={form.scheduled_date} onChange={set("scheduled_date")} testid="jr-convert-date" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="PRICE" value={form.price} onChange={set("price")} testid="jr-convert-price" />
            <TextInput label="ADDRESS" value={form.address} onChange={set("address")} testid="jr-convert-address" />
          </div>
        </div>
      ) : null}
    </Modal>
  );
}


function RejectModal({ req, open, onClose, onDone, onError }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setReason(""); }, [open]);
  const submit = async () => {
    if (!reason.trim()) { onError?.("Reason is required"); return; }
    setBusy(true);
    try {
      await api.patch(`/job-requests/${req.id}`, { status: "rejected", rejection_reason: reason.trim() });
      onDone?.();
    } catch (e) { onError?.(e.message); }
    finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={() => (busy ? null : onClose())} title="Reject request"
           testid="jr-reject-modal"
           footer={<>
             <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
             <Button variant="danger" onClick={submit} disabled={busy} testid="jr-reject-submit">
               {busy ? "Rejecting…" : "Reject"}
             </Button>
           </>}>
      <div className="space-y-2">
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
          Tell the tech why this request wasn't approved. They'll get a notification with the reason.
        </p>
        <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={4}
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="jr-reject-reason" />
      </div>
    </Modal>
  );
}
