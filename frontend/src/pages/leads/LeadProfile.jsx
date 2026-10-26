/**
 * Ticket Z1 · Feb-2026 — Lead Profile page.
 *
 * Phase 1 of 5 (Z1-Z5).  Scope-locked to: route + layout +
 * hydrated contact info + requested service + status/notes
 * migration from the pre-existing LeadDetailDrawer. SMS/Email
 * send, Quote create, Communication history, Auto-convert all
 * deferred to Z2-Z5 (footer bar renders DISABLED placeholders
 * with "Coming in next phase" tooltip to reserve the layout).
 *
 * Visual target: lightweight ``/customers/:id``-shaped profile
 * (NOT the LeadDetailDrawer side-panel + NOT the admin-gated
 * 880-line /admin/leads/:id LeadDetail page).  Preserved:
 *   * Status enum + dropdown options (same canonical status list
 *     the drawer uses — status editing lives inside the Notes/
 *     Status card below the 4-card grid).
 *   * Notes save endpoint (``PUT /api/leads/{id}`` with
 *     ``{status, notes}``) + behaviour.
 *   * "Convert to customer" wiring (``POST /api/leads/{id}/convert``).
 *   * Permission gate (admin + manager — matches
 *     ``_require_leads_role`` on the BE).
 *
 * Form submission requested-service text comes from the
 * joined ``/leads/{id}/raw-submission`` endpoint
 * (``lead.meta.submission_id → form_submissions.values``).
 * Legacy pre-P17 leads with no linked submission render ``—``.
 */
import React, { useEffect, useState, useCallback, useMemo } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { toast } from "sonner";
import {
  Phone, Mail, MapPin, ClipboardList, ChevronLeft, Trash2,
  Edit3, UserPlus, Send, Plus, LayoutGrid,
} from "lucide-react";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { colors } from "@/theme";
import { mustConfirm } from "@/components/ui/confirm-dialog";


const STATUS_ORDER = [
  "new", "contacted", "quoted", "closed_won", "closed_lost",
];
const STATUS_LABEL = {
  new: "New", contacted: "Contacted", quoted: "Quoted",
  closed_won: "Closed – Won", closed_lost: "Closed – Lost",
};
const STATUS_PILL_CLASS = {
  new:          "bg-sky-100 text-sky-800",
  contacted:    "bg-amber-100 text-amber-800",
  quoted:       "bg-violet-100 text-violet-800",
  closed_won:   "bg-emerald-100 text-emerald-800",
  closed_lost:  "bg-slate-200 text-slate-700",
};


// Candidate keys the submission ``values`` object might carry
// for the "requested service" free text.  Ordered: ``services_
// requested`` is the modern widget-form field name; the fallbacks
// cover legacy marketing-form shapes.  Pre-audit found no fixed
// key — different form schemas emit different keys.
const REQUESTED_SERVICE_KEYS = [
  "services_requested", "service_requested", "requested_service",
  "service", "services", "service_type", "message", "inquiry",
  "description", "notes", "comments",
];


function _pickRequestedService(rawSubmission) {
  const values = rawSubmission?.values || {};
  for (const k of REQUESTED_SERVICE_KEYS) {
    const v = values[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  // Fallback — surface every string value joined so operator
  // can at least read the free-text content.  Rare path.
  const strings = Object.entries(values)
    .filter(([, v]) => typeof v === "string" && v.trim())
    .map(([k, v]) => `${k}: ${v}`);
  return strings.length ? strings.join("\n") : "";
}


function StatusPill({ status, testId = "lead-profile-status-pill" }) {
  const cls = STATUS_PILL_CLASS[status] || "bg-slate-100 text-slate-700";
  return (
    <span
      className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${cls}`}
      data-testid={testId}
    >
      {STATUS_LABEL[status] || status || "—"}
    </span>
  );
}


function InfoCard({ icon: Icon, label, value, testId, multiline }) {
  return (
    <div
      className="rounded-lg p-4 flex flex-col gap-2"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testId}
    >
      <div
        className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider"
        style={{ color: colors.onSurfaceSecondary || "#52525B" }}
      >
        {Icon ? <Icon size={13} /> : null}
        <span>{label}</span>
      </div>
      {multiline ? (
        <div
          className="text-sm leading-relaxed whitespace-pre-wrap overflow-y-auto"
          style={{
            color: colors.onSurface, maxHeight: 180,
          }}
          data-testid={`${testId}-value`}
        >
          {value || "—"}
        </div>
      ) : (
        <div
          className="text-sm font-medium"
          style={{ color: colors.onSurface }}
          data-testid={`${testId}-value`}
        >
          {value || "—"}
        </div>
      )}
    </div>
  );
}


export default function LeadProfile() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth() || {};
  const [lead, setLead] = useState(null);
  const [rawSub, setRawSub] = useState(null);
  const [loading, setLoading] = useState(true);
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState("new");
  const [saving, setSaving] = useState(false);
  const [converting, setConverting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const l = await api.get(`/leads/${encodeURIComponent(id)}`);
      setLead(l);
      setNotes(l?.notes || "");
      setStatus(l?.status || "new");
      // Raw submission is best-effort — a 404 on legacy pre-P17
      // leads is expected + silent per the drawer's existing
      // behaviour.
      if (l?.meta?.submission_id) {
        try {
          const sub = await api.get(
            `/leads/${encodeURIComponent(id)}/raw-submission`,
          );
          setRawSub(sub);
        } catch { /* legacy lead — hide the submission source */ }
      }
    } catch (err) {
      toast.error(err?.message || "Failed to load lead");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const requestedService = useMemo(
    () => _pickRequestedService(rawSub),
    [rawSub],
  );

  const save = useCallback(async () => {
    setSaving(true);
    try {
      await api.put(`/leads/${encodeURIComponent(id)}`,
                      { status, notes });
      toast.success("Saved");
      await load();
    } catch (err) {
      toast.error(err?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }, [id, status, notes, load]);

  const convert = useCallback(async () => {
    const ok = await mustConfirm({
      title: `Convert "${lead?.name || lead?.email || "lead"}" into a customer?`,
      description: "The lead will be closed as converted and a new customer record created.",
      confirmText: "Convert",
    });
    if (!ok) return;
    setConverting(true);
    try {
      const res = await api.post(
        `/leads/${encodeURIComponent(id)}/convert`, {},
      );
      toast.success("Converted to customer");
      if (res?.customer_id) {
        navigate(`/customers/${encodeURIComponent(res.customer_id)}`);
      } else {
        await load();
      }
    } catch (err) {
      toast.error(err?.message || "Convert failed");
    } finally {
      setConverting(false);
    }
  }, [id, lead, navigate, load]);

  if (loading) {
    return (
      <div
        className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
        data-testid="lead-profile-skeleton"
      >
        <div className="animate-pulse h-6 w-48 rounded mb-4"
             style={{ background: colors.surfaceSecondary }} />
        <div className="animate-pulse h-16 w-full rounded mb-4"
             style={{ background: colors.surfaceSecondary }} />
      </div>
    );
  }
  if (!lead) {
    return (
      <div
        className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
        data-testid="lead-profile-not-found"
      >
        Lead not found.
      </div>
    );
  }

  const displayName = lead.name
    || [lead.first_name, lead.last_name].filter(Boolean).join(" ")
    || lead.email || "Lead";
  const address = lead.service_address || lead.address || "";
  const createdLabel = lead.created_at
    ? new Date(lead.created_at).toLocaleDateString()
    : "";

  return (
    <div
      className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
      data-testid="lead-profile"
      data-lead-id={lead.id}
    >
      {/* Breadcrumb */}
      <nav
        className="text-xs mb-2 flex items-center gap-1"
        style={{ color: colors.onSurfaceSecondary || "#52525B" }}
        data-testid="lead-profile-breadcrumb"
      >
        <Link to="/" className="hover:underline">Home</Link>
        <span>›</span>
        <Link to="/leads" className="hover:underline">Leads</Link>
        <span>›</span>
        <span style={{ color: colors.onSurface, fontWeight: 600 }}>
          {displayName}
        </span>
      </nav>

      {/* Back link */}
      <Link
        to="/leads"
        className="inline-flex items-center gap-1 text-sm mb-4 hover:underline"
        style={{ color: colors.onSurfaceSecondary || "#52525B" }}
        data-testid="lead-profile-back-link"
      >
        <ChevronLeft size={14} /> All leads
      </Link>

      {/* Header card */}
      <div
        className="rounded-xl p-5 mb-4"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="lead-profile-header"
      >
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <StatusPill status={lead.status || "new"} />
          {lead.source ? (
            <span
              className="text-[11px] px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: colors.surfaceSecondary || "#F4F4F5",
                color: colors.onSurface,
              }}
              data-testid="lead-profile-source-chip"
            >
              {lead.source}
            </span>
          ) : null}
          {createdLabel ? (
            <span
              className="text-[11px]"
              style={{ color: colors.onSurfaceSecondary || "#52525B" }}
              data-testid="lead-profile-created-at"
            >
              Created {createdLabel}
            </span>
          ) : null}
        </div>
        <h1
          className="text-3xl sm:text-4xl font-black tracking-tight uppercase"
          style={{ color: colors.onSurface }}
          data-testid="lead-profile-name"
        >
          {displayName}
        </h1>
        {address ? (
          <div
            className="mt-1 text-sm"
            style={{ color: colors.onSurfaceSecondary || "#52525B" }}
            data-testid="lead-profile-address-sub"
          >
            {address}
          </div>
        ) : null}
      </div>

      {/* 4-card info grid */}
      <div
        className="grid gap-3 mb-4"
        style={{
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        }}
        data-testid="lead-profile-info-grid"
      >
        <InfoCard
          icon={Phone}
          label="Phone"
          value={lead.phone}
          testId="lead-profile-phone-card"
        />
        <InfoCard
          icon={Mail}
          label="Email"
          value={lead.email}
          testId="lead-profile-email-card"
        />
        <InfoCard
          icon={MapPin}
          label="Address"
          value={address}
          testId="lead-profile-address-card"
        />
        <InfoCard
          icon={ClipboardList}
          label="Requested Service"
          value={requestedService}
          multiline
          testId="lead-profile-requested-service-card"
        />
      </div>

      {/* Notes + Status card */}
      <div
        className="rounded-xl p-4 mb-4"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="lead-profile-notes-card"
      >
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div
            className="text-[11px] font-semibold uppercase tracking-wider"
            style={{ color: colors.onSurfaceSecondary || "#52525B" }}
          >
            Status &amp; Notes
          </div>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="text-xs rounded border px-2 py-1"
            style={{
              borderColor: colors.border,
              backgroundColor: colors.surface,
              color: colors.onSurface,
            }}
            data-testid="lead-profile-status-select"
          >
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>{STATUS_LABEL[s]}</option>
            ))}
          </select>
        </div>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={6}
          placeholder="Internal notes…"
          className="w-full text-sm rounded border p-2"
          style={{
            borderColor: colors.border,
            backgroundColor: colors.surface,
            color: colors.onSurface,
          }}
          data-testid="lead-profile-notes-textarea"
        />
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="px-4 py-2 rounded font-semibold text-sm transition hover:brightness-95 disabled:opacity-60"
            style={{
              backgroundColor: colors.brand, color: "#fff",
              border: "1px solid " + (colors.brand || "#0284C7"),
            }}
            data-testid="lead-profile-save-btn"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* Action strip */}
      <div
        className="flex items-center gap-2 flex-wrap mb-4"
        data-testid="lead-profile-action-strip"
      >
        <button
          type="button"
          onClick={convert}
          disabled={converting}
          className="inline-flex items-center gap-1 px-3 py-2 rounded text-sm font-semibold transition hover:brightness-95 disabled:opacity-60"
          style={{
            backgroundColor: "#059669", color: "#fff",
            border: "1px solid #047857",
          }}
          data-testid="lead-profile-convert-btn"
        >
          <UserPlus size={14} />
          {converting ? "Converting…" : "Convert to customer"}
        </button>
        <Link
          to={`/leads?edit=${encodeURIComponent(lead.id)}`}
          className="inline-flex items-center gap-1 px-3 py-2 rounded text-sm font-semibold transition hover:brightness-95"
          style={{
            backgroundColor: colors.surface, color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="lead-profile-edit-link"
        >
          <Edit3 size={14} /> Edit
        </Link>
      </div>

      {/* Footer bar — DISABLED placeholders for Z2+ phases */}
      <div
        className="rounded-xl p-3 flex items-center gap-2 flex-wrap"
        style={{
          backgroundColor: colors.surfaceSecondary || "#F4F4F5",
          border: `1px solid ${colors.border}`,
        }}
        data-testid="lead-profile-footer-bar"
      >
        <button
          type="button"
          disabled
          title="Coming in next phase"
          className="inline-flex items-center gap-1 px-3 py-2 rounded text-sm font-semibold opacity-50 cursor-not-allowed"
          style={{
            backgroundColor: colors.surface, color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="lead-profile-footer-send-btn"
          data-phase-placeholder="z2"
        >
          <Send size={14} /> Send ▾
        </button>
        <button
          type="button"
          disabled
          title="Coming in next phase"
          className="inline-flex items-center gap-1 px-3 py-2 rounded text-sm font-semibold opacity-50 cursor-not-allowed"
          style={{
            backgroundColor: colors.surface, color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="lead-profile-footer-create-btn"
          data-phase-placeholder="z3"
        >
          <Plus size={14} /> + Create ▾
        </button>
        <button
          type="button"
          disabled
          title="Coming in next phase"
          className="inline-flex items-center gap-1 px-3 py-2 rounded text-sm font-semibold opacity-50 cursor-not-allowed"
          style={{
            backgroundColor: colors.surface, color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="lead-profile-footer-overview-btn"
          data-phase-placeholder="z4"
        >
          <LayoutGrid size={14} /> Overview ▾
        </button>
      </div>
    </div>
  );
}
