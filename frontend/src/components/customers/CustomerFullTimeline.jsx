/**
 * Feb-2026 · Customer Communication Timeline — full history view.
 *
 * Phase B · Feb-2026 · Super Timeline —  admin/super_admin sessions
 * additionally see ``call`` (call_logs) and ``note`` (internal job
 * notes) sources merged into the feed. All other roles keep the
 * pre-B 4-source view and never see the new chips. A 403 response
 * (``insufficient_role_for_full_timeline``) is swallowed silently
 * and the caller falls back to the 4-source render — no red toast.
 *
 * Sources merged server-side from ``marketing_deliveries`` (email +
 * SMS), ``invoices`` and ``estimates`` (both live in the ``quotes``
 * collection under distinct ``doc_type`` values), plus ``call_logs``
 * and ``jobs`` (notes + internal_notes) for admin+ sessions.
 * Consumes:
 *
 *   * admin:  ``GET /api/customers/{id}/timeline``
 *   * portal: ``GET /api/customers/me/timeline``
 *
 * Both accept ``page``, ``page_size``, ``kind`` (CSV filter of
 * ``email,sms,invoice,estimate,call,note``), ``from``, ``to``.
 * Response shape:
 * ``{ items, page, page_size, total, total_pages, next_before }``.
 *
 * Pagination row is ALWAYS mounted (mirrors the portal service-
 * reports post-tester fix) so mobile tests + Vitest can locate the
 * testids regardless of ``total_pages``.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Mail, MessageSquare, FileText, Receipt, Clock, ExternalLink,
  Phone, StickyNote, PhoneIncoming, PhoneOutgoing, Play,
} from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "@/api";
import { useAuth } from "@/auth";
import { PhoneLink } from "@/components/customer/PhoneLink";
import { colors } from "@/theme";


// ═══════════════════════════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════════════════════════
function _relative(iso) {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return new Date(iso).toLocaleDateString();
}

// Phase B · Feb-2026 — ``call`` + ``note`` entries added. Icon
// colours pick from existing brand palette slots so the chip row
// stays visually consistent with the pre-B chips.
const _KIND_META = {
  email:    { label: "Email",          icon: Mail,          bg: "#DCFCE7", fg: "#166534" },
  sms:      { label: "SMS",            icon: MessageSquare, bg: "#FEE2E2", fg: "#991B1B" },
  invoice:  { label: "Invoice",        icon: Receipt,       bg: "#DBEAFE", fg: "#1E3A8A" },
  estimate: { label: "Estimate",       icon: FileText,      bg: "#FEF3C7", fg: "#92400E" },
  // Phase B chips — admin/super_admin only. The server also emits
  // ``source_type: "quote"`` for estimates (backward-compat map);
  // treat it as ``estimate`` visually.
  quote:    { label: "Estimate",       icon: FileText,      bg: "#FEF3C7", fg: "#92400E" },
  call:     { label: "Call",           icon: Phone,         bg: "#EDE9FE", fg: "#5B21B6" },
  note:     { label: "Internal Notes", icon: StickyNote,    bg: "#FEF9C3", fg: "#854D0E" },
};


function KindPill({ kind }) {
  const meta = _KIND_META[kind] || { label: kind, icon: Mail,
                                       bg: "#F1F5F9", fg: "#475569" };
  const Icon = meta.icon;
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
      style={{ background: meta.bg, color: meta.fg }}
      data-testid={`timeline-pill-${kind}`}
    >
      <Icon size={10} />
      {meta.label}
    </span>
  );
}


// ─── Row renderers per source type ─────────────────────────────────
function CallRow({ item, index, meta }) {
  const detail = item.detail || {};
  const direction = detail.direction || item.direction || "unknown";
  const DirIcon = direction === "inbound" ? PhoneIncoming : PhoneOutgoing;
  const otherParty = detail.other_party
    || (direction === "inbound" ? detail.from_number : detail.to_number)
    || "";
  const durationStr = detail.duration || item.duration_str || "";
  const recordingUrl = detail.recording_url || "";
  return (
    <div className="flex-1 min-w-0" data-testid={`timeline-call-${index}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <KindPill kind="call" />
        <span
          className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide rounded-full px-2 py-0.5"
          style={{ background: colors.surfaceSecondary,
                    color: colors.muted }}
          data-testid={`timeline-call-direction-${index}`}
        >
          <DirIcon size={10} />
          {direction}
        </span>
        <span className="text-xs" style={{ color: colors.muted }}
              title={item.occurred_at || item.created_at}>
          <Clock size={10} className="inline mr-1" />
          {_relative(item.occurred_at || item.created_at)}
        </span>
        {durationStr ? (
          <span className="text-xs font-semibold"
                style={{ color: colors.onSurface }}
                data-testid={`timeline-call-duration-${index}`}>
            {durationStr}
          </span>
        ) : null}
      </div>
      <div
        className="text-sm mt-1 font-medium"
        style={{ color: colors.onSurface }}
        data-testid={`timeline-subject-${index}`}
      >
        {direction === "inbound" ? "Call from" : "Call to"}{" "}
        {otherParty ? (
          <PhoneLink phone={otherParty} />
        ) : (
          <span style={{ color: colors.muted }}>unknown number</span>
        )}
      </div>
      {recordingUrl ? (
        <a
          href={recordingUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-[11px] font-semibold mt-1"
          style={{ color: meta.fg }}
          data-testid={`timeline-call-play-${index}`}
        >
          <Play size={12} />
          Play recording
        </a>
      ) : null}
    </div>
  );
}


function NoteRow({ item, index, meta }) {
  const detail = item.detail || {};
  const actor = item.actor || null;
  const body = detail.note_body || item.note_body || "";
  const noteKind = detail.note_kind || "visit";
  const jobId = detail.job_id || "";
  return (
    <div className="flex-1 min-w-0" data-testid={`timeline-note-${index}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <KindPill kind="note" />
        {actor ? (
          <>
            <span className="text-xs font-semibold"
                  style={{ color: colors.onSurface }}
                  data-testid={`timeline-note-author-${index}`}>
              {actor.display_name}
            </span>
            {actor.role ? (
              <span
                className="text-[10px] font-semibold uppercase tracking-wide rounded-full px-2 py-0.5"
                style={{ background: colors.surfaceSecondary,
                          color: colors.muted }}
                data-testid={`timeline-note-role-${index}`}
              >
                {actor.role}
              </span>
            ) : null}
          </>
        ) : null}
        <span
          className="text-[10px] font-semibold uppercase tracking-wide rounded-full px-2 py-0.5"
          style={{ background: noteKind === "internal"
                                ? "#FEF3C7" : "#F1F5F9",
                    color: noteKind === "internal"
                            ? "#92400E" : "#475569" }}
          data-testid={`timeline-note-kind-${index}`}
        >
          {noteKind}
        </span>
        <span className="text-xs" style={{ color: colors.muted }}
              title={item.occurred_at || item.created_at}>
          <Clock size={10} className="inline mr-1" />
          {_relative(item.occurred_at || item.created_at)}
        </span>
      </div>
      {jobId ? (
        <div className="text-[11px] mt-0.5">
          <Link
            to={`/jobs/${jobId}`}
            style={{ color: meta.fg }}
            data-testid={`timeline-note-joblink-${index}`}
          >
            Job {jobId.slice(0, 8)}
          </Link>
        </div>
      ) : null}
      {body ? (
        <div
          className="text-sm mt-1 whitespace-pre-wrap"
          style={{ color: colors.onSurface }}
          data-testid={`timeline-note-body-${index}`}
        >
          {body}
        </div>
      ) : null}
    </div>
  );
}


function DefaultRow({ item, index, meta }) {
  const hasUrl = !!item.url;
  const money = typeof item.total === "number" && item.total > 0
    ? `$${item.total.toFixed(2)}`
    : "";
  return (
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2 flex-wrap">
        <KindPill kind={item.kind} />
        <span
          className="text-xs"
          style={{ color: colors.muted }}
          title={item.occurred_at || item.created_at}
        >
          <Clock size={10} className="inline mr-1" />
          {_relative(item.occurred_at || item.created_at)}
        </span>
        {money ? (
          <span className="text-xs font-semibold"
                style={{ color: colors.onSurface }}>
            {money}
          </span>
        ) : null}
        {item.delivery_status ? (
          <span
            className="text-[10px] font-semibold uppercase tracking-wide rounded-full px-2 py-0.5"
            style={{ background: colors.surfaceSecondary,
                      color: colors.muted }}
          >
            {item.delivery_status}
          </span>
        ) : null}
      </div>
      <div
        className="text-sm mt-1 font-medium truncate"
        style={{ color: colors.onSurface }}
        data-testid={`timeline-subject-${index}`}
      >
        {hasUrl ? (
          <Link
            to={item.url}
            className="inline-flex items-center gap-1"
            style={{ color: meta.fg }}
            data-testid={`timeline-link-${index}`}
          >
            {item.subject} <ExternalLink size={12} />
          </Link>
        ) : item.subject}
      </div>
      {item.recipient ? (
        <div className="text-[11px] font-mono mt-0.5"
              style={{ color: colors.muted }}>
          to {item.recipient}
        </div>
      ) : null}
    </div>
  );
}


function Row({ item, index }) {
  const kind = (item.kind || item.source_type || "email").toLowerCase();
  const meta = _KIND_META[kind] || _KIND_META.email;
  let inner;
  if (kind === "call") inner = <CallRow item={item} index={index} meta={meta} />;
  else if (kind === "note") inner = <NoteRow item={item} index={index} meta={meta} />;
  else inner = <DefaultRow item={item} index={index} meta={meta} />;
  return (
    <li
      className="flex items-start gap-3 py-3"
      style={{ borderBottom: `1px solid ${colors.border}` }}
      data-testid={`timeline-row-${index}`}
    >
      <span
        className="mt-1 rounded-full shrink-0"
        style={{ width: 10, height: 10, background: meta.fg }}
        aria-hidden="true"
      />
      {inner}
    </li>
  );
}


// Phase B · Feb-2026 — chips are role-gated at build time. Admin +
// super_admin see all 6; every other role sees the pre-B 4.
const _BASE_CHIPS = ["all", "email", "sms", "invoice", "estimate"];
const _ADMIN_ONLY_CHIPS = ["call", "note"];
const _FULL_TIMELINE_ROLES = new Set(["admin", "super_admin"]);


export default function CustomerFullTimeline({ scope = "admin", customerId }) {
  const isAdmin = scope === "admin";
  const basePath = isAdmin
    ? `/customers/${customerId}/timeline`
    : `/customers/me/timeline`;
  // Phase B — role hook drives chip visibility + graceful 403 handling.
  const auth = useAuth();
  const role = String(auth?.user?.role || "").toLowerCase();
  const canSeeFullTimeline = _FULL_TIMELINE_ROLES.has(role);
  const kindChips = useMemo(
    () => (canSeeFullTimeline
      ? [..._BASE_CHIPS, ..._ADMIN_ONLY_CHIPS]
      : _BASE_CHIPS),
    [canSeeFullTimeline],
  );

  const [items, setItems]           = useState([]);
  const [page, setPage]             = useState(1);
  const [pageSize]                  = useState(20);
  const [total, setTotal]           = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [activeKind, setActiveKind] = useState("all");
  const [loading, setLoading]       = useState(true);
  const [err, setErr]               = useState("");

  const kindCsv = useMemo(
    () => (activeKind === "all" ? "" : activeKind),
    [activeKind],
  );

  const fetchPage = useCallback(async () => {
    if (isAdmin && !customerId) return;
    setLoading(true);
    setErr("");
    try {
      const qs = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (kindCsv) qs.set("kind", kindCsv);
      const r = await api.get(`${basePath}?${qs}`);
      setItems(r?.items || []);
      setTotal(r?.total || 0);
      setTotalPages(r?.total_pages || 0);
    } catch (e) {
      // Phase B · Feb-2026 — a 403 with detail
      // ``insufficient_role_for_full_timeline`` means the caller
      // isn't allowed the FULL feed. We silently render the empty
      // list and keep the (already-filtered) chip row as-is — no
      // red-toast regression for perfectly-legitimate customer/tech
      // sessions that happen to hit the admin endpoint's error path.
      const status = e?.status || e?.response?.status;
      const detail = e?.detail || e?.response?.data?.detail || "";
      if (status === 403 && detail === "insufficient_role_for_full_timeline") {
        setItems([]);
        setTotal(0);
        setTotalPages(0);
      } else {
        setErr(e?.message || "Couldn't load timeline");
      }
    } finally {
      setLoading(false);
    }
  }, [basePath, page, pageSize, kindCsv, isAdmin, customerId]);
  useEffect(() => { fetchPage(); }, [fetchPage]);

  // Reset page → 1 on any filter change.
  useEffect(() => { setPage(1); }, [activeKind]);

  // Phase B — filtered empty-state messaging per source type.
  const _emptyMessage = useMemo(() => {
    if (activeKind === "call") return "No calls yet for this customer.";
    if (activeKind === "note") return "No internal notes yet.";
    return "No timeline entries for this filter.";
  }, [activeKind]);

  return (
    <div data-testid={`full-timeline-${scope}`}>
      {/* Filter chips ───────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 mb-3"
            data-testid="timeline-filters">
        {kindChips.map((k) => {
          const on = activeKind === k;
          return (
            <button
              key={k}
              type="button"
              onClick={() => setActiveKind(k)}
              className="text-xs font-semibold rounded-full px-3 py-1 transition-colors"
              style={{
                background: on
                  ? (_KIND_META[k]?.fg || colors.brand || colors.onSurface)
                  : colors.surface,
                color: on ? colors.onBrand || "#FFFFFF" : colors.onSurface,
                border: `1px solid ${on ? "transparent" : colors.border}`,
              }}
              data-testid={`timeline-filter-${k}`}
            >
              {k === "all" ? "All" : (_KIND_META[k]?.label || k)}
            </button>
          );
        })}
      </div>

      {/* List ───────────────────────────────────────────────────── */}
      {loading ? (
        <div className="text-sm rounded-lg p-3"
              style={{ background: colors.surfaceSecondary,
                        color: colors.muted }}
              data-testid="timeline-loading">
          Loading timeline…
        </div>
      ) : err ? (
        <div className="text-sm rounded-lg p-3"
              style={{ background: "#FEE2E2", color: "#991B1B" }}
              data-testid="timeline-error">
          {err}
        </div>
      ) : items.length === 0 ? (
        <div className="text-sm rounded-lg p-6 text-center"
              style={{ background: colors.surfaceSecondary,
                        color: colors.muted,
                        border: `1px solid ${colors.border}` }}
              data-testid="timeline-empty">
          {_emptyMessage}
        </div>
      ) : (
        <ul className="list-none" data-testid="timeline-list">
          {items.map((it, i) => (
            <Row key={`${it.ref_type || it.source_type}-${it.ref_id || it.id}-${i}`}
                  item={it} index={i} />
          ))}
        </ul>
      )}

      {/* Pagination — always mounted ────────────────────────────── */}
      <div className="mt-4 flex items-center justify-between gap-2"
            data-testid="timeline-pagination">
        <button
          type="button"
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page <= 1}
          className="rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface, minHeight: 40 }}
          data-testid="timeline-pagination-prev"
        >
          ← Prev
        </button>
        <div className="text-sm" style={{ color: colors.muted }}
              data-testid="timeline-page-indicator">
          Page {page} of {Math.max(totalPages, 1)} ({total} total)
        </div>
        <button
          type="button"
          onClick={() => setPage((p) => Math.min(Math.max(totalPages, 1), p + 1))}
          disabled={page >= Math.max(totalPages, 1)}
          className="rounded-lg px-3 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
          style={{ border: `1px solid ${colors.border}`,
                    background: colors.surface, minHeight: 40 }}
          data-testid="timeline-pagination-next"
        >
          Next →
        </button>
      </div>
    </div>
  );
}
