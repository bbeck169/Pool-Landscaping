// Phase 8 · Feb 2026 — Lead detail page.
//
// Route: /leads/:id (admin + manager). Three-column layout:
//   left: contact + service info + status pill
//   middle: notes editor + timeline
//   right: action buttons (Mark Contacted / Quoted / On Hold, Close Won,
//          Close Lost with reason dialog, Archive)
//
// After a successful Close Won a green banner links to the merged /
// created customer page.
import React, { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { api } from "@/api";
import { toast } from "sonner";
import ClickToCallButton from "@/components/telephony/ClickToCallButton";
import { Phone, Mail, MapPin, Calendar, User, CheckCircle2, XCircle, MessageSquarePlus, AlertTriangle, ChevronLeft, RefreshCw } from "lucide-react";

// Phase 34 · Task CC · Feb 2026 — canonical snake_case status enum.
// Values MUST match backend `_CANONICAL_STATUSES` in routers/leads.py.
const STATUS_ORDER = ["new", "contacted", "quoted", "closed_won", "closed_lost"];
const STATUS_LABEL = {
  "new": "New",
  "contacted": "Contacted",
  "quoted": "Quoted",
  "closed_won": "Closed – Won",
  "closed_lost": "Closed – Lost",
};
const STATUS_COLORS = {
  "new": "bg-sky-100 text-sky-800",
  "contacted": "bg-amber-100 text-amber-800",
  "quoted": "bg-violet-100 text-violet-800",
  "closed_won": "bg-emerald-100 text-emerald-800",
  "closed_lost": "bg-slate-200 text-slate-700",
};
const SOURCE_LABEL = {
  website_form: "Website form",
  admin_manual: "Manual entry",
  phone: "Phone call",
  walk_in: "Walk-in",
  referral: "Referral",
  widget_chat: "Widget chat",
  import: "Imported",
};

function StatusPill({ status }) {
  const cls = STATUS_COLORS[status] || "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}
            data-testid="lead-status-pill">
      {STATUS_LABEL[status] || status || "—"}
    </span>
  );
}

function TimelineEntry({ ev }) {
  const label = {
    created: "Lead created",
    status_change: `Status → ${ev.payload?.to || "?"}`,
    note_added: "Note added",
    converted_to_customer: "Converted to customer",
    archived: "Archived",
  }[ev.kind] || ev.kind;
  const when = ev.ts ? new Date(ev.ts).toLocaleString() : "";
  return (
    <div className="border-l-2 border-slate-200 pl-3 py-2" data-testid={`timeline-${ev.kind}`}>
      <div className="text-sm font-medium text-slate-800">{label}</div>
      <div className="text-xs text-slate-500">{when}</div>
      {ev.kind === "note_added" && (
        <div className="text-sm text-slate-700 mt-1 whitespace-pre-wrap">
          {ev.payload?.text}
        </div>
      )}
      {ev.kind === "status_change" && ev.payload?.loss_reason && (
        <div className="text-xs text-rose-700 mt-1">Reason: {ev.payload.loss_reason}</div>
      )}
    </div>
  );
}

function CloseLostDialog({ open, onConfirm, onClose, busy }) {
  const [reason, setReason] = useState("");
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
           data-testid="close-lost-dialog">
      <div className="bg-white rounded-xl shadow-lg max-w-md w-full p-5">
        <h3 className="text-lg font-semibold mb-2">Close as Lost</h3>
        <p className="text-sm text-slate-600 mb-3">
          Why did we lose this lead? (min 3 characters)
        </p>
        <textarea
          className="w-full border border-slate-300 rounded p-2 text-sm h-24"
          value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="Chose competitor / price / no response…"
          data-testid="close-lost-reason"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={onClose}
                    className="px-3 py-1.5 rounded border border-slate-300 text-sm"
                    data-testid="close-lost-cancel">Cancel</button>
          <button onClick={() => onConfirm(reason.trim())}
                    disabled={busy || reason.trim().length < 3}
                    className="px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-700 text-white text-sm disabled:opacity-50"
                    data-testid="close-lost-confirm">
            {busy ? "Closing…" : "Close Lost"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function LeadDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [lead, setLead] = useState(null);
  const [loading, setLoading] = useState(true);
  const [noteText, setNoteText] = useState("");
  const [conversion, setConversion] = useState(null);
  const [lostOpen, setLostOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const l = await api.get(`/leads/${id}`);
      setLead(l);
      if (l.converted_customer_id) {
        setConversion({ customer_id: l.converted_customer_id, was_merged: false });
      }
    } catch (e) {
      toast.error("Failed to load lead", { description: e?.message || "" });
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const setStatus = async (status) => {
    setBusy(true);
    try {
      const updated = await api.patch(`/leads/${id}`, { status });
      setLead(updated);
      toast.success(`Marked ${STATUS_LABEL[status] || status}`);
    } catch (e) {
      toast.error("Update failed", { description: e?.message || "" });
    } finally {
      setBusy(false);
    }
  };

  const addNote = async () => {
    const t = noteText.trim();
    if (!t) return;
    setBusy(true);
    try {
      const updated = await api.post(`/leads/${id}/note`, { text: t });
      setLead(updated);
      setNoteText("");
      toast.success("Note added");
    } catch (e) {
      toast.error("Note failed", { description: e?.message || "" });
    } finally {
      setBusy(false);
    }
  };

  const closeWon = async () => {
    setBusy(true);
    try {
      const res = await api.post(`/leads/${id}/close-won`);
      setConversion(res);
      toast.success(res.was_merged ? "Merged into existing customer" : "New customer created");
      load();
    } catch (e) {
      toast.error("Convert failed", { description: e?.message || "" });
    } finally {
      setBusy(false);
    }
  };

  const closeLost = async (reason) => {
    setBusy(true);
    try {
      const updated = await api.post(`/leads/${id}/close-lost`, { loss_reason: reason });
      setLead(updated);
      setLostOpen(false);
      toast.success("Lead closed as lost");
    } catch (e) {
      toast.error("Close Lost failed", { description: e?.message || "" });
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <div className="p-6 text-slate-500" data-testid="lead-detail-loading">Loading…</div>;
  }
  if (!lead) {
    return <div className="p-6 text-slate-500">Lead not found.</div>;
  }

  const timeline = [...(lead.timeline || [])].reverse();

  return (
    <div className="p-4 sm:p-6 max-w-7xl mx-auto" data-testid="lead-detail-page">
      <div className="flex items-center gap-3 mb-4">
        <button onClick={() => nav(-1)}
                  className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900"
                  data-testid="lead-detail-back">
          <ChevronLeft size={16} /> Back
        </button>
        <div className="flex-1" />
        <button onClick={load}
                  className="inline-flex items-center gap-1 px-2 py-1 border border-slate-300 rounded text-xs hover:bg-slate-50">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {conversion?.customer_id && (
        <div className="mb-4 rounded-lg bg-emerald-50 border border-emerald-200 p-3 flex items-center justify-between"
               data-testid="conversion-banner">
          <div className="flex items-center gap-2 text-emerald-800 text-sm">
            <CheckCircle2 size={16} />
            {conversion.was_merged ? "Merged into existing customer" : "New customer created"} — customer #{conversion.customer_id.slice(0, 8)}
          </div>
          <Link to={`/customers/${conversion.customer_id}`}
                  className="text-emerald-800 underline text-sm font-medium"
                  data-testid="conversion-banner-link">
            Open customer →
          </Link>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* LEFT — contact + service */}
        <div className="lg:col-span-1 space-y-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-center justify-between mb-2">
              <h1 className="text-lg font-bold" data-testid="lead-name">{lead.name}</h1>
              <StatusPill status={lead.status} />
            </div>
            <div className="text-xs text-slate-500 uppercase mb-1">
              Source · {SOURCE_LABEL[lead.source] || lead.source || "—"}
            </div>
            {lead.service_interest && (
              <div className="text-xs text-slate-500 uppercase mb-2">
                Interest · {lead.service_interest}
              </div>
            )}
            <div className="space-y-1.5 text-sm">
              {lead.phone && (
                <div className="flex items-start gap-2">
                  <Phone size={14} className="mt-0.5 text-slate-500" />
                  <div className="flex-1">
                    <div data-testid="lead-phone">{lead.phone}</div>
                    <div className="mt-1">
                      <ClickToCallButton
                        phoneNumber={lead.phone}
                        entityKind="lead" entityId={lead.id}
                        label="Call" size="sm"
                        testIdPrefix="lead-detail-call"
                      />
                    </div>
                  </div>
                </div>
              )}
              {lead.email && (
                <div className="flex items-center gap-2">
                  <Mail size={14} className="text-slate-500" />
                  <a href={`mailto:${lead.email}`} className="text-sky-700 hover:underline break-all"
                     data-testid="lead-email">{lead.email}</a>
                </div>
              )}
              {(lead.service_address || lead.address) && (
                <div className="flex items-start gap-2">
                  <MapPin size={14} className="mt-0.5 text-slate-500" />
                  <div data-testid="lead-address">{lead.service_address || lead.address}</div>
                </div>
              )}
              {/* K63 · Feb-2026 — Data-parity fill-in.  Widget forms
                  already persist ``city``, ``state``, ``zip``,
                  ``company_name`` onto ``leads`` but the pre-K63
                  detail view never surfaced them, so the ops team
                  had to open the raw lead record to see the full
                  intake. These four lines fix that. */}
              {(lead.city || lead.state || lead.zip) ? (
                <div className="flex items-start gap-2 text-xs text-slate-500 ml-6"
                      data-testid="lead-city-state-zip">
                  {[lead.city, lead.state, lead.zip].filter(Boolean).join(", ")}
                </div>
              ) : null}
              {lead.company_name ? (
                <div className="flex items-center gap-2 text-xs text-slate-500"
                      data-testid="lead-company-name">
                  <User size={12} className="text-slate-500" />
                  {lead.company_name}
                </div>
              ) : null}
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <Calendar size={12} /> Created {lead.created_at?.slice(0, 10) || "—"}
              </div>
              {lead.converted_customer_id && (
                <div className="flex items-center gap-2 text-xs text-emerald-700">
                  <User size={12} /> Converted to customer
                </div>
              )}
              {lead.loss_reason && (
                <div className="flex items-start gap-2 text-xs text-rose-700 mt-2">
                  <AlertTriangle size={12} className="mt-0.5" /> {lead.loss_reason}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* MIDDLE — notes editor + timeline */}
        <div className="lg:col-span-2 space-y-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold mb-2 flex items-center gap-1">
              <MessageSquarePlus size={14} /> Add note
            </div>
            <textarea
              className="w-full border border-slate-300 rounded p-2 text-sm h-20"
              value={noteText} onChange={(e) => setNoteText(e.target.value)}
              placeholder="Called them, left VM…"
              data-testid="lead-note-input"
            />
            <div className="mt-2 flex justify-end">
              <button onClick={addNote}
                        disabled={busy || !noteText.trim()}
                        className="px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-700 text-white text-sm disabled:opacity-50"
                        data-testid="lead-note-submit">
                Add note
              </button>
            </div>
            {lead.notes && (
              <div className="mt-3 pt-3 border-t border-slate-100">
                <div className="text-xs font-medium text-slate-500 mb-1">All notes</div>
                <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans"
                     data-testid="lead-notes-display">{lead.notes}</pre>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold mb-2">Timeline</div>
            <div className="space-y-1" data-testid="lead-timeline">
              {timeline.length === 0 && (
                <div className="text-sm text-slate-400">No events yet.</div>
              )}
              {timeline.map((ev, i) => <TimelineEntry key={i} ev={ev} />)}
            </div>
          </div>
        </div>

        {/* RIGHT — actions */}
        <div className="lg:col-span-1 space-y-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold mb-3">Actions</div>
            <button onClick={closeWon}
                      disabled={busy || lead.status === "closed_won"}
                      className="w-full mb-2 px-3 py-2 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium disabled:opacity-50"
                      data-testid="lead-close-won">
              <CheckCircle2 size={14} className="inline mr-1" />
              Close Won → Convert
            </button>
            <button onClick={() => setLostOpen(true)}
                      disabled={busy || lead.status === "closed_lost"}
                      className="w-full mb-2 px-3 py-2 rounded bg-rose-600 hover:bg-rose-700 text-white text-sm font-medium disabled:opacity-50"
                      data-testid="lead-close-lost">
              <XCircle size={14} className="inline mr-1" />
              Close Lost
            </button>
            <div className="grid grid-cols-2 gap-2 mt-3">
              {STATUS_ORDER.filter((s) => !s.startsWith("closed_")).map((s) => (
                <button key={s} onClick={() => setStatus(s)}
                          disabled={busy || lead.status === s}
                          className="px-2 py-1.5 rounded border border-slate-300 text-xs hover:bg-slate-50 disabled:opacity-50"
                          data-testid={`lead-status-${s.replace(/_/g, "-")}`}>
                  {STATUS_LABEL[s] || s}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <CloseLostDialog open={lostOpen} onConfirm={closeLost}
                          onClose={() => setLostOpen(false)} busy={busy} />
    </div>
  );
}
