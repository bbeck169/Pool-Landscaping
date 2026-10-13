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
import { useAuth } from "@/auth";
import ClickToCallButton from "@/components/telephony/ClickToCallButton";
import { Phone, Mail, MapPin, Calendar, User, CheckCircle2, XCircle, MessageSquarePlus, AlertTriangle, ChevronLeft, RefreshCw, Bell, MessageCircle, FileText } from "lucide-react";
import LeadComposeModal from "./LeadComposeModal";
import { PhoneLink, AddressLink } from "@/components/customer";

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

// P2 #4 · Feb-2026 — Lightweight status pill for the Linked Quotes
// mini-list. Mirrors the quote-status vocabulary used across the admin
// quote-detail header pill (draft / sent / accepted / declined / etc.).
// Unknown values fall through to a neutral slate pill.
const _QUOTE_STATUS_COLORS = {
  draft: "bg-slate-100 text-slate-700",
  sent: "bg-sky-100 text-sky-800",
  accepted: "bg-emerald-100 text-emerald-800",
  declined: "bg-rose-100 text-rose-800",
  paid: "bg-emerald-100 text-emerald-800",
  unpaid: "bg-amber-100 text-amber-800",
  overdue: "bg-rose-100 text-rose-800",
};
function QuoteStatusPill({ status }) {
  const normalized = (status || "").toLowerCase();
  const cls = _QUOTE_STATUS_COLORS[normalized] || "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}
      data-testid={`lead-linked-quote-status-${normalized || "unknown"}`}
    >
      {normalized ? normalized.replace(/_/g, " ") : "—"}
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

// Phase K63.finalize · Feb-2026 — resend confirmation modal for the
// K63 lead-alert refire button on this page.
function ResendNotificationsDialog({ leadId, busy, result, onClose, onConfirm }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          data-testid="resend-notifications-dialog"
          onClick={onClose}>
      <div className="bg-white rounded-xl shadow-lg max-w-lg w-full p-5"
            onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-1">Resend lead alerts</h3>
        <p className="text-sm text-slate-600 mb-3">
          Refire the K63 SMS + email fan-out for lead
          <span className="font-mono ml-1">{leadId?.slice(0, 8)}</span> to every
          opted-in recipient. This <b>bypasses idempotency</b> —
          recipients who already received an alert for this lead
          will get another one.
        </p>
        {result ? (
          <div className="text-xs bg-emerald-50 border border-emerald-200 rounded p-3 mb-3"
                 data-testid="resend-notifications-result">
            <div className="font-semibold text-emerald-900 mb-1">
              Queued · SMS: {result.sms_queued || 0} · Email: {result.email_queued || 0}
            </div>
            {(result.dispatched || []).length > 0 ? (
              <ul className="text-emerald-800 space-y-0.5">
                {(result.dispatched || []).map((d, i) => (
                  <li key={i} data-testid={`resend-notifications-row-${i}`}>
                    <span className="uppercase font-mono">{d.channel}</span>
                    <span className="mx-1">→</span>
                    <span className="font-mono">{d.recipient}</span>
                    <span className="ml-2 text-emerald-700">({d.status})</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-emerald-700">
                No opted-in recipients configured. Add some in
                Settings → Notifications → Lead Alerts.
              </div>
            )}
          </div>
        ) : null}
        <div className="mt-3 flex justify-end gap-2">
          <button onClick={onClose}
                    className="px-3 py-1.5 rounded border border-slate-300 text-sm"
                    data-testid="resend-notifications-cancel">
            {result ? "Close" : "Cancel"}
          </button>
          {!result && (
            <button onClick={onConfirm} disabled={busy}
                      className="px-3 py-1.5 rounded bg-indigo-600 hover:bg-indigo-700 text-white text-sm disabled:opacity-50"
                      data-testid="resend-notifications-confirm">
              {busy ? "Sending…" : "Resend now"}
            </button>
          )}
        </div>
      </div>
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
  const { user } = useAuth();
  const isAdmin = ["admin", "super_admin", "owner"].includes(user?.role);
  const canCompose = ["admin", "super_admin", "owner", "manager"].includes(user?.role);
  const [lead, setLead] = useState(null);
  const [loading, setLoading] = useState(true);
  const [noteText, setNoteText] = useState("");
  const [conversion, setConversion] = useState(null);
  const [resendOpen, setResendOpen] = useState(false);
  const [resendBusy, setResendBusy] = useState(false);
  const [resendResult, setResendResult] = useState(null);
  const [lostOpen, setLostOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Phase L3 · Feb-2026 — compose modal + communication timeline.
  const [composeChannel, setComposeChannel] = useState(null);   // "sms" | "email" | null
  const [commItems, setCommItems] = useState([]);
  const [commCursor, setCommCursor] = useState(null);
  const [commHasMore, setCommHasMore] = useState(false);
  const [commLoading, setCommLoading] = useState(false);
  // P2 #4 · Feb-2026 — Linked quotes mini-list (admin-only panel).
  // Populated lazily from GET /leads/<id>/quotes once the lead itself
  // resolves. Fail-open: fetch error leaves ``linkedQuotes`` null;
  // the panel simply does not render.
  const [linkedQuotes, setLinkedQuotes] = useState(null);

  const loadCommunications = useCallback(async (opts = {}) => {
    setCommLoading(true);
    try {
      const query = new URLSearchParams({ limit: "50" });
      if (opts.cursor) query.set("cursor", opts.cursor);
      const res = await api.get(`/leads/${id}/communications?${query.toString()}`);
      const items = res?.items || [];
      setCommItems((prev) => opts.cursor ? [...prev, ...items] : items);
      setCommCursor(res?.next_cursor || null);
      setCommHasMore(!!res?.has_more);
    } catch (e) {
      toast.error("Failed to load communications", { description: e?.message || "" });
    } finally {
      setCommLoading(false);
    }
  }, [id]);

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
  // Only load communications once the lead itself has resolved
  // (avoids a spurious "Failed to load communications" toast when
  // the caller drops us on a URL whose ``:id`` doesn't exist).
  useEffect(() => {
    if (lead?.id) loadCommunications();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lead?.id]);

  // P2 #4 · Feb-2026 — fetch linked-quotes mini-list after the lead
  // resolves AND only when the quotes_count badge indicates there's
  // something to show (avoids an empty network call for brand-new leads).
  useEffect(() => {
    if (!lead?.id) return;
    if (!(lead.quotes_count > 0)) {
      setLinkedQuotes(null);
      return;
    }
    api.get(`/leads/${lead.id}/quotes?limit=10`).then((res) => {
      setLinkedQuotes(res || { items: [], total: 0, limit: 10 });
    }).catch(() => { setLinkedQuotes(null); });
  }, [lead?.id, lead?.quotes_count]);

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
        {canCompose && (
          <>
            <button
              type="button"
              disabled={!lead?.phone}
              onClick={() => lead?.phone && setComposeChannel("sms")}
              title={lead?.phone ? "Send SMS to this lead" : "No phone on file"}
              aria-label={`Send SMS to ${lead?.name || "lead"}`}
              className="inline-flex items-center gap-1 px-2 py-1 border border-slate-300 rounded text-xs hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="lead-detail-send-sms"
            >
              <MessageCircle size={12} /> Send SMS
            </button>
            <button
              type="button"
              disabled={!lead?.email}
              onClick={() => lead?.email && setComposeChannel("email")}
              title={lead?.email ? "Send email to this lead" : "No email on file"}
              aria-label={`Send email to ${lead?.name || "lead"}`}
              className="inline-flex items-center gap-1 px-2 py-1 border border-slate-300 rounded text-xs hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="lead-detail-send-email"
            >
              <Mail size={12} /> Send Email
            </button>
          </>
        )}
        {isAdmin && (
          <button
            onClick={() => { setResendResult(null); setResendOpen(true); }}
            className="inline-flex items-center gap-1 px-2 py-1 border border-slate-300 rounded text-xs hover:bg-slate-50"
            data-testid="lead-resend-notifications-btn"
            title="Refire the K63 lead-alert fan-out (SMS + email) for this lead"
          >
            <Bell size={12} /> Resend alerts
          </button>
        )}
        <button onClick={load}
                  className="inline-flex items-center gap-1 px-2 py-1 border border-slate-300 rounded text-xs hover:bg-slate-50">
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {resendOpen && (
        <ResendNotificationsDialog
          leadId={id}
          busy={resendBusy}
          result={resendResult}
          onClose={() => setResendOpen(false)}
          onConfirm={async () => {
            setResendBusy(true);
            try {
              const r = await api.post(`/admin/leads/${id}/resend-notifications`);
              setResendResult(r);
              toast.success(
                `Resend queued — ${r.sms_queued || 0} SMS + ${r.email_queued || 0} email`,
              );
            } catch (e) {
              toast.error(e?.message || "Resend failed");
            } finally {
              setResendBusy(false);
            }
          }}
        />
      )}

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
                    <div data-testid="lead-phone"><PhoneLink phone={lead.phone} /></div>
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
              {(() => {
                const line1 = lead.service_address || lead.address;
                const hasCSZ = !!(lead.city || lead.state || lead.zip);
                const hasAnyAddress = !!(line1 || hasCSZ);
                const _lat = lead.latitude;
                const _lng = lead.longitude;
                const hasLatLng = _lat !== undefined && _lat !== null
                                    && _lng !== undefined && _lng !== null;
                if (!hasAnyAddress) {
                  // Phase P0.5 · Feb-2026 — explicit empty-state so
                  // ops can tell "visitor skipped this field" apart
                  // from "the UI is dropping data".
                  return (
                    <div className="flex items-start gap-2"
                          data-testid="lead-address-empty">
                      <MapPin size={14} className="mt-0.5 text-slate-500" />
                      <div className="text-slate-500 italic">No address provided</div>
                    </div>
                  );
                }
                return (
                  <>
                    {line1 ? (
                      <div className="flex items-start gap-2">
                        <MapPin size={14} className="mt-0.5 text-slate-500" />
                        <div data-testid="lead-address">
                          <AddressLink
                            address={{
                              line1,
                              city: lead.city,
                              state: lead.state,
                              zip: lead.zip,
                            }}
                          >
                            {line1}
                          </AddressLink>
                        </div>
                      </div>
                    ) : null}
                    {/* K63 · Feb-2026 — Data-parity fill-in.  Widget
                        forms already persist ``city``, ``state``,
                        ``zip``, ``company_name`` onto ``leads`` but
                        the pre-K63 detail view never surfaced them.
                        Kept hidden when all three are empty (per
                        Phase P0.5 direction — the outer empty-state
                        line covers that case instead). */}
                    {hasCSZ ? (
                      <div className="flex items-start gap-2 text-xs text-slate-500 ml-6"
                            data-testid="lead-city-state-zip">
                        {[lead.city, lead.state, lead.zip].filter(Boolean).join(", ")}
                      </div>
                    ) : null}
                    {/* Phase P0.5 · Feb-2026 — lat/lng hint next to
                        address for pin-drop verification. Rendered
                        ONLY when both coordinates are present. */}
                    {hasLatLng ? (
                      <div className="flex items-start gap-2 text-xs text-slate-500 ml-6"
                            data-testid="lead-latlng">
                        <span aria-hidden="true">📍</span>
                        <span>{Number(_lat).toFixed(4)}, {Number(_lng).toFixed(4)}</span>
                      </div>
                    ) : null}
                  </>
                );
              })()}
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

          {/* Phase L3 · Feb-2026 — Communication Timeline (SMS + email
              + status changes + inbound RC SMS matched to this lead). */}
          <div className="rounded-xl border border-slate-200 bg-white p-4"
               data-testid="lead-communication-timeline">
            <div className="text-sm font-semibold mb-2 flex items-center justify-between">
              <span>Communication Timeline</span>
              <button
                type="button"
                onClick={() => loadCommunications()}
                className="text-xs text-slate-500 hover:text-slate-800 inline-flex items-center gap-1"
                data-testid="lead-communication-timeline-refresh"
                aria-label="Refresh communication timeline"
              >
                <RefreshCw size={12} /> Refresh
              </button>
            </div>
            <div className="space-y-2">
              {commLoading && commItems.length === 0 ? (
                <div className="text-sm text-slate-400">Loading…</div>
              ) : commItems.length === 0 ? (
                <div className="text-sm text-slate-400">No communications yet.</div>
              ) : (
                commItems.map((it, i) => (
                  <CommTimelineItem key={it.id || `${it.type}-${i}`} item={it} />
                ))
              )}
            </div>
            {commHasMore && (
              <div className="mt-3 flex justify-center">
                <button
                  type="button"
                  onClick={() => loadCommunications({ cursor: commCursor })}
                  disabled={commLoading}
                  className="px-3 py-1 rounded border border-slate-300 text-xs hover:bg-slate-50 disabled:opacity-50"
                  data-testid="lead-communication-timeline-load-more"
                >
                  {commLoading ? "Loading…" : "Load more"}
                </button>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT — actions */}
        <div className="lg:col-span-1 space-y-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold mb-3">Actions</div>
            {/* LEAD-CREATE-QUOTE · Feb-2026 — primary indigo entry
                 to the full quote builder, pre-populated with the
                 lead's name + address via the Phase-2 Quote-to-Lead
                 Recipient URL contract. Admin-only (matches the
                 backend ``POST /quotes`` ``require_admin`` dep so
                 the gate on both sides stays identical — see the
                 ROUTE-GUARD-AUDIT ticket for the broader parity
                 principle). Small count badge renders when the lead
                 already has one or more lead-recipient quotes
                 attached; count arrives on the ``GET /leads/{lid}``
                 payload as ``quotes_count``. */}
            {isAdmin && (
              <button
                type="button"
                onClick={() => nav(
                  `/quotes/new?recipient_type=lead&recipient_id=${id}`,
                )}
                disabled={busy}
                className="w-full mb-2 px-3 py-2 rounded bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium disabled:opacity-50 inline-flex items-center justify-center gap-1.5"
                data-testid="lead-create-quote"
              >
                <FileText size={14} />
                Create Quote
                {lead.quotes_count ? (
                  <span
                    className="ml-1 inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-white/25 text-white text-[11px] font-semibold"
                    data-testid="lead-create-quote-count"
                  >
                    {lead.quotes_count}
                  </span>
                ) : null}
              </button>
            )}
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

          {/* P2 #4 · Feb-2026 — Linked Quotes mini-list. Renders only
              when the backend has non-empty quotes_count AND the lazy
              fetch succeeded. Admin-only (matches the Create Quote
              button gate). Status pills + click-through to the quote
              detail. "View all" link visible when total > rendered. */}
          {isAdmin && linkedQuotes && (linkedQuotes.items || []).length > 0 ? (
            <div
              className="rounded-xl border border-slate-200 bg-white p-4"
              data-testid="lead-linked-quotes-panel"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="text-sm font-semibold">
                  Linked Quote{linkedQuotes.total === 1 ? "" : "s"}
                </div>
                <span
                  className="text-xs text-slate-500"
                  data-testid="lead-linked-quotes-count"
                >
                  {linkedQuotes.total}
                </span>
              </div>
              <ul className="space-y-2">
                {(linkedQuotes.items || []).map((q) => (
                  <li key={q.id}>
                    <button
                      type="button"
                      onClick={() => nav(`/quotes/${q.id}`)}
                      className="w-full text-left px-3 py-2 rounded border border-slate-200 hover:bg-slate-50 flex items-center justify-between gap-2"
                      data-testid={`lead-linked-quote-row-${q.id}`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate">
                          {q.title || "(untitled)"}
                        </div>
                        <div className="text-xs text-slate-500">
                          ${Number(q.total || 0).toFixed(2)}
                          {q.reparented ? " · reparented" : ""}
                        </div>
                      </div>
                      <QuoteStatusPill status={q.status} />
                    </button>
                  </li>
                ))}
              </ul>
              {linkedQuotes.total > (linkedQuotes.items || []).length ? (
                <button
                  type="button"
                  onClick={() => nav(`/quotes?lead=${lead.id}`)}
                  className="mt-3 w-full text-xs font-semibold text-indigo-600 hover:underline"
                  data-testid="lead-linked-quotes-view-all"
                >
                  View all {linkedQuotes.total} →
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <CloseLostDialog open={lostOpen} onConfirm={closeLost}
                          onClose={() => setLostOpen(false)} busy={busy} />

      {composeChannel && (
        <LeadComposeModal
          lead={lead}
          channel={composeChannel}
          onClose={() => setComposeChannel(null)}
          onSent={() => loadCommunications()}
        />
      )}
    </div>
  );
}


// ─── Phase L3 · communication timeline row ─────────────────────────
function CommTimelineItem({ item }) {
  const type = item.type || "status_change";
  const iconMeta = {
    sms:            { bg: "#DCFCE7", fg: "#166534", label: "SMS" },
    email:          { bg: "#DBEAFE", fg: "#1E3A8A", label: "Email" },
    status_change:  { bg: "#F1F5F9", fg: "#475569", label: "Status change" },
  }[type] || { bg: "#F1F5F9", fg: "#475569", label: type };
  const when = item.created_at ? new Date(item.created_at).toLocaleString() : "";
  const isInbound = item.direction === "inbound";
  return (
    <div
      className="border-l-2 pl-3 py-2"
      style={{ borderColor: iconMeta.fg + "55" }}
      data-testid={`lead-comm-item-${type}`}
    >
      <div className="flex items-center gap-2">
        <span
          className="inline-flex items-center text-[10px] font-semibold px-2 py-0.5 rounded-full uppercase"
          style={{ background: iconMeta.bg, color: iconMeta.fg }}
        >
          {iconMeta.label}
          {isInbound ? " · inbound" : ""}
        </span>
        {item.status ? (
          <span className="text-[11px] text-slate-500">
            {item.status}
          </span>
        ) : null}
        <span className="text-xs text-slate-400 ml-auto">{when}</span>
      </div>
      {item.subject ? (
        <div className="text-sm font-medium text-slate-800 mt-1">{item.subject}</div>
      ) : null}
      {item.body ? (
        <div className="text-sm text-slate-700 mt-1 whitespace-pre-wrap">
          {item.body.length > 400 ? item.body.slice(0, 400) + "…" : item.body}
        </div>
      ) : null}
      {item.error ? (
        <div className="text-xs text-rose-700 mt-1">Error: {item.error}</div>
      ) : null}
    </div>
  );
}
