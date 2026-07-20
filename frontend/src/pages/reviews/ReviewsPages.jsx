/**
 * Reviews Subsystem · Phase 2 (Web UI) · Feb 2026.
 *
 * Four admin-only pages under ``/admin/reviews/*``:
 *   - Dashboard     (KPI cards, leaderboard, recent reviews table)
 *   - Requests      (filterable table + New Review Request modal)
 *   - Platforms     (Google/Facebook/Yelp/BBB/custom rows + editor)
 *   - Widget mgmt   (preview + copy-embed snippet + direct URL)
 *
 * Public routes shipped alongside (Public* export):
 *   - PublicReviewLanding   (/reviews/r/:token   — magic-link CX flow)
 *   - PublicReviewsWidget   (/reviews/:slug      — full-page widget)
 */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Star, MessageSquare, Users as UsersIcon, TrendingUp, Trash2,
  Plus, X as XIcon, RefreshCw, Search, Copy, ExternalLink, ChevronUp,
  ChevronDown, Send, Globe, Award, Loader2, CheckCircle2, AlertTriangle,
} from "lucide-react";
import { colors } from "@/theme";
import { api } from "@/api";
import {
  listPlatforms, createPlatform, updatePlatform, deletePlatform,
  listRequests, createRequest, resendRequest,
  listReviews, updateReview, deleteReview,
  getStats, getLeaderboard,
  syncPlatformNow, getLatestSyncPerPlatform,
  PLATFORMS, OUTCOMES, SENT_VIA_OPTIONS,
} from "@/api/reviews";
import { StarRatingDisplay } from "@/components/reviews/StarRatingDisplay";
import { PlatformIcon } from "@/components/reviews/PlatformIcon";
import { OutcomePill } from "@/components/reviews/OutcomePill";
import { ReviewCard } from "@/components/reviews/ReviewCard";

// ═════════════════════════════════════════════════════════════════════
// Shared bits (kept local — mirrors Comms Phase 2 conventions)
// ═════════════════════════════════════════════════════════════════════

const Card = ({ children, className = "", ...rest }) => (
  <div className={`rounded-2xl ${className}`}
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
        {...rest}>
    {children}
  </div>
);

function Toast({ toast, onClose }) {
  const tone = toast?.tone || "info";
  const bg = tone === "error" ? "#FEE2E2" : tone === "success" ? "#DCFCE7" : tone === "warning" ? "#FEF9C3" : "#DBEAFE";
  const fg = tone === "error" ? "#991B1B" : tone === "success" ? "#166534" : tone === "warning" ? "#854D0E" : "#1E3A8A";
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(onClose, 3200);
    return () => clearTimeout(t);
  }, [toast, onClose]);
  if (!toast) return null;
  return (
    <div className="fixed top-4 right-4 z-50 px-4 py-2 rounded-lg text-sm font-semibold shadow-lg"
          style={{ background: bg, color: fg }}
          data-testid={`reviews-toast-${tone}`}>{toast.message}</div>
  );
}

function PageHeader({ icon: Icon, title, subtitle, actions }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <div className="flex items-center gap-2 mb-1">
          {Icon ? <Icon size={22} style={{ color: colors.brand }} /> : null}
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
        </div>
        {subtitle ? <p className="text-sm" style={{ color: colors.muted }}>{subtitle}</p> : null}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

function BtnPrimary({ onClick, children, disabled, testid, className = "", type = "button" }) {
  return (
    <button onClick={onClick} disabled={disabled} type={type}
             className={`px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40 ${className}`}
             style={{ background: colors.brand, color: "#fff" }}
             data-testid={testid}>
      {children}
    </button>
  );
}

function BtnGhost({ onClick, children, disabled, testid, className = "", type = "button" }) {
  return (
    <button onClick={onClick} disabled={disabled} type={type}
             className={`px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-40 ${className}`}
             style={{ background: colors.surfaceSecondary, color: colors.onSurface,
                       border: `1px solid ${colors.border}` }}
             data-testid={testid}>
      {children}
    </button>
  );
}

function Modal({ open, onClose, title, children, footer, wide = false, testid }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(15,23,42,0.55)" }}
          onClick={onClose}
          data-testid={testid}>
      <div className={`rounded-2xl overflow-hidden w-full ${wide ? "max-w-3xl" : "max-w-lg"}`}
            style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
            onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b"
              style={{ borderColor: colors.border }}>
          <div className="text-base font-semibold" style={{ color: colors.onSurface }}>{title}</div>
          <button onClick={onClose} className="p-1 rounded-full hover:opacity-70"
                   data-testid="reviews-modal-close">
            <XIcon size={18} />
          </button>
        </div>
        <div className="p-5 max-h-[70vh] overflow-y-auto">{children}</div>
        {footer ? (
          <div className="px-5 py-3 border-t flex justify-end gap-2"
                style={{ borderColor: colors.border, background: colors.surfaceSecondary }}>
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function EmptyState({ icon: Icon, title, hint, cta, onCta, testid }) {
  return (
    <div className="text-center py-16 rounded-2xl"
          style={{ background: colors.surface, border: `1px dashed ${colors.border}` }}
          data-testid={testid}>
      {Icon ? <Icon size={38} className="mx-auto mb-3" style={{ color: colors.muted }} /> : null}
      <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{title}</div>
      {hint ? <div className="text-xs mt-1" style={{ color: colors.muted }}>{hint}</div> : null}
      {cta ? <div className="mt-4"><BtnPrimary onClick={onCta}>{cta}</BtnPrimary></div> : null}
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════
// Dashboard  →  /admin/reviews
// ═════════════════════════════════════════════════════════════════════

export function ReviewsDashboard() {
  const [stats, setStats] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [recent, setRecent] = useState([]);
  const [syncStrip, setSyncStrip] = useState(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [detail, setDetail] = useState(null); // review under edit

  const reload = () => {
    setLoading(true);
    Promise.allSettled([
      getStats(),
      getLeaderboard(1),
      listReviews({ limit: 20 }),
      getLatestSyncPerPlatform(),
    ]).then(([s, l, r, y]) => {
      setStats(s.status === "fulfilled" ? s.value : null);
      setLeaderboard(l.status === "fulfilled" ? l.value : []);
      setRecent(r.status === "fulfilled" ? r.value : []);
      setSyncStrip(y.status === "fulfilled" ? y.value : null);
    }).finally(() => setLoading(false));
  };
  useEffect(reload, []);

  const onSaveReview = async (updates) => {
    try {
      await updateReview(detail.id, updates);
      setToast({ tone: "success", message: "Review updated" });
      setDetail(null);
      reload();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  const onDeleteReview = async () => {
    if (!window.confirm("Delete this review permanently?")) return;
    try {
      await deleteReview(detail.id);
      setToast({ tone: "success", message: "Review deleted" });
      setDetail(null);
      reload();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="reviews-dashboard">
      <Toast toast={toast} onClose={() => setToast(null)} />
      <PageHeader
        icon={Star}
        title="Reviews"
        subtitle="Star-rating snapshot, top techs, and the latest customer feedback."
        actions={<BtnGhost onClick={reload} testid="reviews-dashboard-refresh">
          <span className="inline-flex items-center gap-1.5"><RefreshCw size={13} /> Refresh</span>
        </BtnGhost>}
      />

      {/* KPI cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <Kpi icon={Star} label="Average rating"
              value={stats ? stats.avg_star.toFixed(2) : "—"}
              hint={stats?.total ? `${stats.total} total reviews` : ""}
              accent
              testid="reviews-kpi-avg" />
        <Kpi icon={MessageSquare} label="Public reviews"
              value={stats?.count_public ?? "—"}
              hint={stats?.count_private != null
                ? `${stats.count_private} private note${stats.count_private === 1 ? "" : "s"}`
                : ""}
              testid="reviews-kpi-public" />
        <Kpi icon={TrendingUp} label="Past 30 days"
              value={stats?.delta_last_30d ?? "—"}
              hint="new reviews in the last month"
              testid="reviews-kpi-delta" />
      </div>

      {/* Sync status strip */}
      {syncStrip ? (
        <Card className="p-4 mb-6" data-testid="reviews-sync-strip">
          <div className="flex items-center justify-between mb-2">
            <div className="text-xs font-semibold uppercase tracking-wider"
                  style={{ color: colors.muted }}>External sync status</div>
            <div className="text-xs" style={{ color: colors.muted }}>Daily · 03:00 UTC</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {["google", "facebook", "yelp"].map((p) => {
              const row = syncStrip[p];
              const tone = row?.status === "ok" ? "#16A34A"
                          : row?.status === "error" ? "#DC2626"
                          : "#94A3B8";
              return (
                <div key={p}
                      className="inline-flex items-center gap-1.5 px-2 py-1 rounded-full"
                      style={{ background: colors.surfaceSecondary, border: `1px solid ${tone}` }}
                      data-testid={`reviews-sync-strip-${p}`}>
                  <span className="w-2 h-2 rounded-full" style={{ background: tone }} />
                  <span className="text-xs font-semibold capitalize" style={{ color: colors.onSurface }}>
                    {p}
                  </span>
                  <span className="text-[10px]" style={{ color: colors.muted }}>
                    · {row?.status || "never"}
                    {row?.ran_at ? ` · ${(row.ran_at || "").slice(0, 10)}` : ""}
                  </span>
                </div>
              );
            })}
          </div>
        </Card>
      ) : null}

      {/* Leaderboard */}
      <Card className="p-5 mb-6" data-testid="reviews-leaderboard">
        <div className="flex items-center justify-between mb-3">
          <div className="text-lg font-semibold" style={{ color: colors.onSurface }}>
            <span className="inline-flex items-center gap-2"><Award size={16} /> Tech leaderboard</span>
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            Sorted by average star · min 1 review
          </div>
        </div>
        {leaderboard.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: colors.muted }} className="text-left text-xs font-semibold uppercase tracking-wider">
                  <th className="py-2 pr-3">Tech</th>
                  <th className="py-2 pr-3">Average</th>
                  <th className="py-2 pr-3">Reviews</th>
                  <th className="py-2 pr-3">5-star</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((t) => (
                  <tr key={t.technician_id} className="border-t" style={{ borderColor: colors.border }}
                       data-testid={`reviews-leaderboard-row-${t.technician_id}`}>
                    <td className="py-2 pr-3 font-semibold" style={{ color: colors.onSurface }}>
                      {t.technician_name}
                    </td>
                    <td className="py-2 pr-3">
                      <StarRatingDisplay value={t.avg_star} size={14} showValue />
                    </td>
                    <td className="py-2 pr-3" style={{ color: colors.onSurface }}>{t.review_count}</td>
                    <td className="py-2 pr-3" style={{ color: colors.onSurface }}>{t.five_star_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-sm" style={{ color: colors.muted }}>
            {loading ? "Loading…" : "No tech has enough reviews yet — send a request to get started."}
          </div>
        )}
      </Card>

      {/* Recent reviews */}
      <Card className="p-5" data-testid="reviews-recent">
        <div className="flex items-center justify-between mb-3">
          <div className="text-lg font-semibold" style={{ color: colors.onSurface }}>Recent reviews</div>
          <div className="text-xs" style={{ color: colors.muted }}>Click a row to edit or respond</div>
        </div>
        {recent.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: colors.muted }} className="text-left text-xs font-semibold uppercase tracking-wider">
                  <th className="py-2 pr-3">Rating</th>
                  <th className="py-2 pr-3">Review</th>
                  <th className="py-2 pr-3">Platform</th>
                  <th className="py-2 pr-3">Reviewer</th>
                  <th className="py-2 pr-3">Date</th>
                  <th className="py-2 pr-3">Widget</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.id} className="border-t hover:opacity-80 cursor-pointer"
                       style={{ borderColor: colors.border }}
                       onClick={() => setDetail(r)}
                       data-testid={`reviews-recent-row-${r.id}`}>
                    <td className="py-2 pr-3"><StarRatingDisplay value={r.star_rating || 0} size={14} /></td>
                    <td className="py-2 pr-3 max-w-md truncate" style={{ color: colors.onSurface }}>
                      {r.review_text || <em style={{ color: colors.muted }}>No text</em>}
                    </td>
                    <td className="py-2 pr-3">
                      <span className="inline-flex items-center gap-1.5" style={{ color: colors.onSurface }}>
                        <PlatformIcon code={r.platform} size={13} />
                        <span className="capitalize">{r.platform || "—"}</span>
                      </span>
                    </td>
                    <td className="py-2 pr-3" style={{ color: colors.onSurface }}>{r.reviewer_name || "Anon"}</td>
                    <td className="py-2 pr-3" style={{ color: colors.muted }}>{(r.created_at || "").slice(0, 10)}</td>
                    <td className="py-2 pr-3">
                      <span className="text-xs font-semibold" style={{ color: r.visible_on_widget ? "#166534" : colors.muted }}>
                        {r.visible_on_widget ? "Yes" : "No"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={Star} title="No reviews yet"
                       hint="Once customers respond to a review request, they'll appear here."
                       testid="reviews-recent-empty" />
        )}
      </Card>

      <ReviewDetailModal review={detail}
                          onClose={() => setDetail(null)}
                          onSave={onSaveReview}
                          onDelete={onDeleteReview} />
    </div>
  );
}

function Kpi({ icon: Icon, label, value, hint, accent = false, testid }) {
  return (
    <div className="rounded-2xl p-4"
          style={{ background: accent ? "linear-gradient(135deg,#FEF3C7,#FDE68A)" : colors.surface,
                   border: `1px solid ${colors.border}` }}
          data-testid={testid}>
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider mb-2"
            style={{ color: colors.muted }}>
        <Icon size={13} /> {label}
      </div>
      <div className="text-3xl font-bold" style={{ color: colors.onSurface }}>{value}</div>
      {hint ? <div className="text-xs mt-1" style={{ color: colors.muted }}>{hint}</div> : null}
    </div>
  );
}

function ReviewDetailModal({ review, onClose, onSave, onDelete }) {
  const [response, setResponse] = useState("");
  const [visible, setVisible] = useState(true);
  useEffect(() => {
    if (review) {
      setResponse(review.admin_response || "");
      setVisible(review.visible_on_widget !== false);
    }
  }, [review]);
  if (!review) return null;
  return (
    <Modal open onClose={onClose} title="Review detail"
            testid="reviews-detail-modal"
            footer={<>
              <BtnGhost onClick={onDelete} testid="reviews-detail-delete">
                <span className="inline-flex items-center gap-1.5"><Trash2 size={13} /> Delete</span>
              </BtnGhost>
              <BtnGhost onClick={onClose}>Cancel</BtnGhost>
              <BtnPrimary onClick={() => onSave({ admin_response: response, visible_on_widget: visible })}
                            testid="reviews-detail-save">Save changes</BtnPrimary>
            </>}>
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <StarRatingDisplay value={review.star_rating || 0} size={22} showValue />
          <span className="inline-flex items-center gap-1.5 text-sm capitalize"
                 style={{ color: colors.muted }}>
            <PlatformIcon code={review.platform} size={14} /> {review.platform || "unknown"}
          </span>
        </div>
        <div className="rounded-lg p-3 text-sm"
              style={{ background: colors.surfaceSecondary, color: colors.onSurface }}>
          {review.review_text || <em style={{ color: colors.muted }}>No text provided.</em>}
        </div>
        <div className="text-xs" style={{ color: colors.muted }}>
          {review.reviewer_name || "Anonymous"} · {(review.created_at || "").slice(0, 16)}
        </div>

        <div>
          <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                  style={{ color: colors.muted }}>Admin response (public)</label>
          <textarea rows={4}
                     value={response} onChange={(e) => setResponse(e.target.value)}
                     className="w-full rounded-lg px-3 py-2 text-sm"
                     style={{ background: colors.surfaceSecondary, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                     placeholder="Say thanks, address concerns, share next steps…"
                     data-testid="reviews-detail-response" />
        </div>

        <label className="flex items-center gap-2 text-sm cursor-pointer"
                style={{ color: colors.onSurface }}>
          <input type="checkbox" checked={visible} onChange={(e) => setVisible(e.target.checked)}
                  data-testid="reviews-detail-visible" />
          <span>Show this review on the public widget</span>
        </label>
      </div>
    </Modal>
  );
}

// ═════════════════════════════════════════════════════════════════════
// Requests page  →  /admin/reviews/requests
// ═════════════════════════════════════════════════════════════════════

export function ReviewsRequestsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filterOutcome, setFilterOutcome] = useState("");
  const [q, setQ] = useState("");
  const [toast, setToast] = useState(null);
  const [showNew, setShowNew] = useState(false);
  const [detail, setDetail] = useState(null);

  const reload = () => {
    setLoading(true);
    listRequests(filterOutcome ? { status: filterOutcome } : {})
      .then((d) => setRows(d))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(reload, [filterOutcome]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return rows;
    return rows.filter((r) =>
      (r.customer_name || "").toLowerCase().includes(s) ||
      (r.customer_email || "").toLowerCase().includes(s));
  }, [rows, q]);

  const onResend = async (rid) => {
    try {
      await resendRequest(rid);
      setToast({ tone: "success", message: "Request resent" });
      reload();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="reviews-requests">
      <Toast toast={toast} onClose={() => setToast(null)} />
      <PageHeader
        icon={Send}
        title="Review requests"
        subtitle="Track every request you send and its outcome."
        actions={<BtnPrimary testid="reviews-request-new" onClick={() => setShowNew(true)}>
          <span className="inline-flex items-center gap-1"><Plus size={14} /> New request</span>
        </BtnPrimary>}
      />

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={filterOutcome} onChange={(e) => setFilterOutcome(e.target.value)}
                 className="rounded-lg px-3 py-2 text-sm"
                 style={{ background: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                 data-testid="reviews-requests-outcome">
          <option value="">All outcomes</option>
          {OUTCOMES.map((o) => <option key={o.code} value={o.code}>{o.label}</option>)}
        </select>
        <div className="flex items-center gap-2 flex-1 max-w-md">
          <Search size={14} style={{ color: colors.muted }} />
          <input value={q} onChange={(e) => setQ(e.target.value)}
                  placeholder="Search customer name or email…"
                  className="w-full rounded-lg px-3 py-2 text-sm"
                  style={{ background: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
                  data-testid="reviews-requests-search" />
        </div>
        <BtnGhost onClick={reload}><RefreshCw size={13} /></BtnGhost>
      </div>

      <Card className="p-0 overflow-hidden">
        {loading ? (
          <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>
        ) : filtered.length ? (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: colors.surfaceSecondary, color: colors.muted }}
                   className="text-left text-xs font-semibold uppercase tracking-wider">
                <th className="py-2 px-4">Customer</th>
                <th className="py-2 px-4">Tech</th>
                <th className="py-2 px-4">Sent via</th>
                <th className="py-2 px-4">Sent at</th>
                <th className="py-2 px-4">Rating</th>
                <th className="py-2 px-4">Outcome</th>
                <th className="py-2 px-4"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => (
                <tr key={r.id} className="border-t" style={{ borderColor: colors.border }}
                     data-testid={`reviews-request-row-${r.id}`}>
                  <td className="py-2 px-4 font-semibold cursor-pointer"
                       onClick={() => setDetail(r)}
                       style={{ color: colors.onSurface }}>
                    {r.customer_name || "—"}
                    {r.customer_email ? <div className="text-xs font-normal" style={{ color: colors.muted }}>{r.customer_email}</div> : null}
                  </td>
                  <td className="py-2 px-4" style={{ color: colors.onSurface }}>
                    {r.technician_name || <em style={{ color: colors.muted }}>—</em>}
                  </td>
                  <td className="py-2 px-4 capitalize" style={{ color: colors.onSurface }}>
                    {(r.sent_via || "").replace("_", " ")}
                  </td>
                  <td className="py-2 px-4" style={{ color: colors.muted }}>
                    {(r.sent_at || "").slice(0, 16).replace("T", " ")}
                  </td>
                  <td className="py-2 px-4">
                    {r.star_rating_submitted
                      ? <StarRatingDisplay value={r.star_rating_submitted} size={13} />
                      : <span style={{ color: colors.muted }}>—</span>}
                  </td>
                  <td className="py-2 px-4"><OutcomePill outcome={r.outcome} /></td>
                  <td className="py-2 px-4">
                    <div className="flex items-center gap-2 justify-end">
                      <BtnGhost testid={`reviews-request-resend-${r.id}`}
                                 onClick={() => onResend(r.id)}>
                        <span className="inline-flex items-center gap-1.5"><RefreshCw size={12} /> Resend</span>
                      </BtnGhost>
                      <BtnGhost onClick={() => setDetail(r)}>Open</BtnGhost>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState icon={Send} title="No requests yet"
                       hint="Send your first review request to a happy customer."
                       cta="New request" onCta={() => setShowNew(true)}
                       testid="reviews-requests-empty" />
        )}
      </Card>

      <NewRequestModal open={showNew}
                        onClose={() => setShowNew(false)}
                        onCreated={() => { setShowNew(false); reload(); setToast({ tone: "success", message: "Request sent" }); }}
                        onError={(m) => setToast({ tone: "error", message: m })} />

      <RequestDetailModal request={detail} onClose={() => setDetail(null)} onResend={onResend} />
    </div>
  );
}

function RequestDetailModal({ request, onClose, onResend }) {
  if (!request) return null;
  return (
    <Modal open onClose={onClose} title={`Request · ${request.customer_name || ""}`}
            testid="reviews-request-detail"
            footer={<>
              <BtnGhost onClick={() => onResend(request.id)}>
                <span className="inline-flex items-center gap-1.5"><RefreshCw size={13} /> Resend</span>
              </BtnGhost>
              <BtnGhost onClick={onClose}>Close</BtnGhost>
            </>}>
      <div className="space-y-3 text-sm" style={{ color: colors.onSurface }}>
        <Kv label="Customer" value={request.customer_name} sub={request.customer_email} />
        <Kv label="Technician" value={request.technician_name || "—"} />
        <Kv label="Sent via" value={(request.sent_via || "").replace("_", " ")} />
        <Kv label="Sent at" value={(request.sent_at || "").replace("T", " ").slice(0, 16)} />
        <Kv label="Expires at" value={(request.expires_at || "").replace("T", " ").slice(0, 16)} />
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>Outcome</div>
          <div className="mt-1"><OutcomePill outcome={request.outcome} /></div>
        </div>
        {request.star_rating_submitted ? (
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>Rating submitted</div>
            <div className="mt-1"><StarRatingDisplay value={request.star_rating_submitted} size={16} showValue /></div>
          </div>
        ) : null}
        {request.public_url ? (
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>Public link</div>
            <div className="mt-1 text-xs break-all">{request.public_url}</div>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

function Kv({ label, value, sub }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wider" style={{ color: colors.muted }}>{label}</div>
      <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{value || "—"}</div>
      {sub ? <div className="text-xs" style={{ color: colors.muted }}>{sub}</div> : null}
    </div>
  );
}

function NewRequestModal({ open, onClose, onCreated, onError }) {
  const [customerQuery, setCustomerQuery] = useState("");
  const [customerResults, setCustomerResults] = useState([]);
  const [customer, setCustomer] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState("");
  const [techs, setTechs] = useState([]);
  const [techId, setTechId] = useState("");
  const [sentVia, setSentVia] = useState("email");
  const [expedite, setExpedite] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      // Reset on close so the next open starts fresh.
      setCustomerQuery(""); setCustomerResults([]); setCustomer(null);
      setJobs([]); setJobId(""); setTechs([]); setTechId("");
      setSentVia("email"); setExpedite(false);
    } else {
      api.get("/technicians").then((d) => setTechs(Array.isArray(d) ? d : []))
                              .catch(() => setTechs([]));
    }
  }, [open]);

  useEffect(() => {
    if (!open || !customerQuery.trim()) {
      setCustomerResults([]);
      return undefined;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      api.get(`/customers?search=${encodeURIComponent(customerQuery)}&limit=15`)
        .then((d) => { if (!cancelled) setCustomerResults(Array.isArray(d) ? d.slice(0, 15) : []); })
        .catch(() => { if (!cancelled) setCustomerResults([]); });
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [customerQuery, open]);

  useEffect(() => {
    if (!customer?.id) { setJobs([]); setJobId(""); return; }
    api.get(`/jobs?customer_id=${encodeURIComponent(customer.id)}&limit=20`)
      .then((d) => setJobs(Array.isArray(d) ? d : (d?.jobs || [])))
      .catch(() => setJobs([]));
  }, [customer]);

  useEffect(() => {
    if (!jobId) return;
    const j = jobs.find((x) => x.id === jobId);
    if (j?.technician_id && !techId) setTechId(j.technician_id);
  }, [jobId, jobs]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async () => {
    if (!customer?.id) return onError && onError("Pick a customer first");
    setSubmitting(true);
    try {
      await createRequest({
        customer_id: customer.id,
        job_id: jobId || undefined,
        technician_id: techId || undefined,
        sent_via: sentVia,
        expedite,
      });
      onCreated && onCreated();
    } catch (e) {
      onError && onError(e.message);
    } finally { setSubmitting(false); }
  };

  return (
    <Modal open={open} onClose={onClose} title="Send a review request"
            wide
            testid="reviews-request-new-modal"
            footer={<>
              <BtnGhost onClick={onClose}>Cancel</BtnGhost>
              <BtnPrimary onClick={submit} disabled={submitting || !customer}
                           testid="reviews-request-new-submit">
                {submitting ? <span className="inline-flex items-center gap-1.5"><Loader2 size={13} className="animate-spin" /> Sending…</span> : "Send request"}
              </BtnPrimary>
            </>}>
      <div className="space-y-4">
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                  style={{ color: colors.muted }}>Customer</label>
          {customer ? (
            <div className="rounded-lg px-3 py-2 flex items-center justify-between"
                  style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                  data-testid="reviews-request-new-customer">
              <div>
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{customer.name}</div>
                <div className="text-xs" style={{ color: colors.muted }}>{customer.email || customer.phone || ""}</div>
              </div>
              <button onClick={() => { setCustomer(null); setJobs([]); }}
                       className="text-xs font-semibold"
                       style={{ color: colors.brand }}>Change</button>
            </div>
          ) : (
            <>
              <input value={customerQuery} onChange={(e) => setCustomerQuery(e.target.value)}
                      placeholder="Search customers by name or email…"
                      className="w-full rounded-lg px-3 py-2 text-sm"
                      style={{ background: colors.surface, color: colors.onSurface,
                                border: `1px solid ${colors.border}` }}
                      data-testid="reviews-request-new-customer-search" />
              {customerResults.length ? (
                <div className="mt-2 rounded-lg overflow-hidden"
                      style={{ background: colors.surface, border: `1px solid ${colors.border}` }}>
                  {customerResults.map((c) => (
                    <button key={c.id}
                             onClick={() => setCustomer(c)}
                             className="w-full text-left px-3 py-2 hover:opacity-70"
                             style={{ borderBottom: `1px solid ${colors.border}` }}
                             data-testid={`reviews-request-new-cust-${c.id}`}>
                      <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{c.name}</div>
                      <div className="text-xs" style={{ color: colors.muted }}>{c.email || c.phone || ""}</div>
                    </button>
                  ))}
                </div>
              ) : null}
            </>
          )}
        </div>

        {customer && jobs.length > 0 ? (
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                    style={{ color: colors.muted }}>Job (optional)</label>
            <select value={jobId} onChange={(e) => setJobId(e.target.value)}
                     className="w-full rounded-lg px-3 py-2 text-sm"
                     style={{ background: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                     data-testid="reviews-request-new-job">
              <option value="">— No specific job —</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.title || j.service_type || j.id} · {(j.scheduled_date || "").slice(0, 10)}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        <div>
          <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                  style={{ color: colors.muted }}>Technician (optional)</label>
          <select value={techId} onChange={(e) => setTechId(e.target.value)}
                   className="w-full rounded-lg px-3 py-2 text-sm"
                   style={{ background: colors.surface, color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                   data-testid="reviews-request-new-tech">
            <option value="">— Unassigned —</option>
            {techs.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                  style={{ color: colors.muted }}>Channel</label>
          <div className="flex flex-wrap gap-2">
            {SENT_VIA_OPTIONS.map((o) => (
              <button key={o.code} type="button"
                       onClick={() => setSentVia(o.code)}
                       className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                       style={{ background: sentVia === o.code ? colors.brand : colors.surface,
                                color: sentVia === o.code ? "#fff" : colors.onSurface,
                                border: `1px solid ${colors.border}` }}
                       data-testid={`reviews-request-new-via-${o.code}`}>
                {o.label}
              </button>
            ))}
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm cursor-pointer"
                style={{ color: colors.onSurface }}>
          <input type="checkbox" checked={expedite} onChange={(e) => setExpedite(e.target.checked)}
                  data-testid="reviews-request-new-expedite" />
          <span>Bypass 7-day rate limit (super-admin only)</span>
        </label>
      </div>
    </Modal>
  );
}

// ═════════════════════════════════════════════════════════════════════
// Platforms page  →  /admin/reviews/platforms
// ═════════════════════════════════════════════════════════════════════

export function ReviewsPlatformsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [editing, setEditing] = useState(null); // {} for new, dict for edit

  const reload = () => {
    setLoading(true);
    listPlatforms().then((d) => setRows(d.sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0))))
                     .catch(() => setRows([]))
                     .finally(() => setLoading(false));
  };
  useEffect(reload, []);

  const move = async (row, dir) => {
    const other = rows.find((r, i) =>
      dir === "up" ? i === rows.indexOf(row) - 1 : i === rows.indexOf(row) + 1);
    if (!other) return;
    try {
      await updatePlatform(row.id, { sort_order: other.sort_order || 0 });
      await updatePlatform(other.id, { sort_order: row.sort_order || 0 });
      reload();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  const [syncing, setSyncing] = useState(null);
  const SYNCABLE = new Set(["google", "facebook", "yelp"]);
  const onSyncNow = async (platform) => {
    setSyncing(platform);
    try {
      const summary = await syncPlatformNow(platform);
      const msg = summary.status === "ok"
        ? `Synced ${summary.fetched_count} · +${summary.new_count} new · ${summary.updated_count} updated`
        : `${platform}: ${summary.status}${summary.detail ? " — " + summary.detail : ""}`;
      setToast({ tone: summary.status === "ok" ? "success" : "warning", message: msg });
    } catch (e) { setToast({ tone: "error", message: e.message }); }
    finally { setSyncing(null); }
  };

  const onDelete = async (row) => {
    if (!window.confirm(`Delete "${row.display_name}"?`)) return;
    try {
      await deletePlatform(row.id);
      setToast({ tone: "success", message: "Platform removed" });
      reload();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  const onToggleActive = async (row) => {
    try {
      await updatePlatform(row.id, { is_active: !row.is_active });
      reload();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  return (
    <div className="max-w-4xl mx-auto p-4 md:p-6" data-testid="reviews-platforms">
      <Toast toast={toast} onClose={() => setToast(null)} />
      <PageHeader
        icon={Globe}
        title="Review platforms"
        subtitle="Configure where 4–5★ customers get sent to leave a public review."
        actions={<BtnPrimary testid="reviews-platform-new" onClick={() => setEditing({})}>
          <span className="inline-flex items-center gap-1"><Plus size={14} /> Add platform</span>
        </BtnPrimary>}
      />

      <Card className="p-0 overflow-hidden">
        {loading ? (
          <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>
        ) : rows.length ? (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: colors.surfaceSecondary, color: colors.muted }}
                   className="text-left text-xs font-semibold uppercase tracking-wider">
                <th className="py-2 px-4">Platform</th>
                <th className="py-2 px-4">Display name</th>
                <th className="py-2 px-4">Review URL</th>
                <th className="py-2 px-4 text-center">Active</th>
                <th className="py-2 px-4">Order</th>
                <th className="py-2 px-4"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={r.id} className="border-t"
                     style={{ borderColor: colors.border }}
                     data-testid={`reviews-platform-row-${r.id}`}>
                  <td className="py-2 px-4">
                    <span className="inline-flex items-center gap-2 capitalize" style={{ color: colors.onSurface }}>
                      <PlatformIcon code={r.platform} size={16} /> {r.platform}
                    </span>
                  </td>
                  <td className="py-2 px-4 font-semibold" style={{ color: colors.onSurface }}>
                    {r.display_name}
                  </td>
                  <td className="py-2 px-4">
                    <a href={r.review_url} target="_blank" rel="noreferrer"
                       className="text-xs inline-flex items-center gap-1"
                       style={{ color: colors.brand }}>
                      <ExternalLink size={12} /> Open
                    </a>
                  </td>
                  <td className="py-2 px-4 text-center">
                    <button onClick={() => onToggleActive(r)}
                             className="px-2 py-0.5 rounded-full text-xs font-semibold"
                             style={{ background: r.is_active ? "#DCFCE7" : "#F3F4F6",
                                      color: r.is_active ? "#166534" : "#4B5563" }}
                             data-testid={`reviews-platform-toggle-${r.id}`}>
                      {r.is_active ? "Active" : "Inactive"}
                    </button>
                  </td>
                  <td className="py-2 px-4">
                    <div className="inline-flex flex-col gap-0.5">
                      <button onClick={() => move(r, "up")} disabled={idx === 0}
                               className="p-0.5 disabled:opacity-30"
                               data-testid={`reviews-platform-up-${r.id}`}>
                        <ChevronUp size={14} />
                      </button>
                      <button onClick={() => move(r, "down")} disabled={idx === rows.length - 1}
                               className="p-0.5 disabled:opacity-30"
                               data-testid={`reviews-platform-down-${r.id}`}>
                        <ChevronDown size={14} />
                      </button>
                    </div>
                  </td>
                  <td className="py-2 px-4">
                    <div className="flex items-center gap-2 justify-end">
                      {SYNCABLE.has(r.platform) ? (
                        <BtnGhost
                          onClick={() => onSyncNow(r.platform)}
                          disabled={syncing === r.platform}
                          testid={`reviews-platform-sync-${r.platform}`}>
                          <span className="inline-flex items-center gap-1.5">
                            {syncing === r.platform
                              ? <Loader2 size={12} className="animate-spin" />
                              : <RefreshCw size={12} />}
                            Sync
                          </span>
                        </BtnGhost>
                      ) : null}
                      <BtnGhost onClick={() => setEditing(r)}
                                 testid={`reviews-platform-edit-${r.id}`}>Edit</BtnGhost>
                      <BtnGhost onClick={() => onDelete(r)}
                                 testid={`reviews-platform-delete-${r.id}`}>
                        <Trash2 size={13} />
                      </BtnGhost>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState icon={Globe} title="No platforms configured"
                       hint="Add Google, Facebook, Yelp, or a custom URL so happy customers can post a public review."
                       cta="Add first platform" onCta={() => setEditing({})}
                       testid="reviews-platforms-empty" />
        )}
      </Card>

      <PlatformEditModal
        row={editing}
        onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); reload();
          setToast({ tone: "success", message: "Platform saved" }); }}
        onError={(m) => setToast({ tone: "error", message: m })}
      />
    </div>
  );
}

function PlatformEditModal({ row, onClose, onSaved, onError }) {
  const [platform, setPlatform] = useState("google");
  const [displayName, setDisplayName] = useState("");
  const [reviewUrl, setReviewUrl] = useState("");
  const [sortOrder, setSortOrder] = useState(0);
  const [isActive, setIsActive] = useState(true);
  const [customSlug, setCustomSlug] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (row && row.id) {
      setPlatform(row.platform || "google");
      setDisplayName(row.display_name || "");
      setReviewUrl(row.review_url || "");
      setSortOrder(row.sort_order || 0);
      setIsActive(row.is_active !== false);
      setCustomSlug(row.custom_slug || "");
    } else {
      setPlatform("google");
      setDisplayName(""); setReviewUrl(""); setSortOrder(0);
      setIsActive(true); setCustomSlug("");
    }
  }, [row]);

  if (!row) return null;
  const editing = Boolean(row.id);

  const submit = async () => {
    if (!displayName.trim()) return onError && onError("Display name required");
    if (!/^https?:\/\//i.test(reviewUrl.trim())) return onError && onError("Review URL must start with http(s)://");
    setSubmitting(true);
    try {
      if (editing) {
        await updatePlatform(row.id, {
          display_name: displayName.trim(),
          review_url: reviewUrl.trim(),
          is_active: isActive,
          sort_order: sortOrder,
        });
      } else {
        await createPlatform({
          platform,
          display_name: displayName.trim(),
          review_url: reviewUrl.trim(),
          is_active: isActive,
          sort_order: sortOrder,
          custom_slug: platform === "custom" ? (customSlug || null) : null,
        });
      }
      onSaved && onSaved();
    } catch (e) { onError && onError(e.message); }
    finally { setSubmitting(false); }
  };

  return (
    <Modal open onClose={onClose}
            title={editing ? "Edit platform" : "Add platform"}
            testid="reviews-platform-modal"
            footer={<>
              <BtnGhost onClick={onClose}>Cancel</BtnGhost>
              <BtnPrimary onClick={submit} disabled={submitting}
                            testid="reviews-platform-save">
                {submitting ? "Saving…" : editing ? "Save changes" : "Add platform"}
              </BtnPrimary>
            </>}>
      <div className="space-y-3">
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                  style={{ color: colors.muted }}>Platform</label>
          <select value={platform} disabled={editing}
                   onChange={(e) => setPlatform(e.target.value)}
                   className="w-full rounded-lg px-3 py-2 text-sm"
                   style={{ background: colors.surface, color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                   data-testid="reviews-platform-code">
            {PLATFORMS.map((p) => <option key={p.code} value={p.code}>{p.label}</option>)}
          </select>
        </div>

        {platform === "custom" && !editing ? (
          <div>
            <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                    style={{ color: colors.muted }}>Custom slug</label>
            <input value={customSlug} onChange={(e) => setCustomSlug(e.target.value)}
                    placeholder="e.g. angi, homeadvisor"
                    className="w-full rounded-lg px-3 py-2 text-sm"
                    style={{ background: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="reviews-platform-custom-slug" />
          </div>
        ) : null}

        <div>
          <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                  style={{ color: colors.muted }}>Display name (shown to customers)</label>
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="Google"
                  className="w-full rounded-lg px-3 py-2 text-sm"
                  style={{ background: colors.surface, color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                  data-testid="reviews-platform-name" />
        </div>

        <div>
          <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                  style={{ color: colors.muted }}>Review URL</label>
          <input value={reviewUrl} onChange={(e) => setReviewUrl(e.target.value)}
                  placeholder="https://g.page/…/review"
                  className="w-full rounded-lg px-3 py-2 text-sm"
                  style={{ background: colors.surface, color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                  data-testid="reviews-platform-url" />
        </div>

        <div className="flex items-center gap-4">
          <div className="flex-1">
            <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
                    style={{ color: colors.muted }}>Sort order</label>
            <input type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value) || 0)}
                    className="w-full rounded-lg px-3 py-2 text-sm"
                    style={{ background: colors.surface, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                    data-testid="reviews-platform-order" />
          </div>
          <label className="flex items-center gap-2 text-sm cursor-pointer mt-6"
                  style={{ color: colors.onSurface }}>
            <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)}
                    data-testid="reviews-platform-active" />
            <span>Active</span>
          </label>
        </div>
      </div>
    </Modal>
  );
}

// ═════════════════════════════════════════════════════════════════════
// Widget management  →  /admin/reviews/widget
// ═════════════════════════════════════════════════════════════════════

export function ReviewsWidgetPage() {
  const [slug, setSlug] = useState("");
  const [toast, setToast] = useState(null);
  const backendOrigin = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");
  const previewUrl = slug ? `${backendOrigin}/api/reviews/public/widget/${encodeURIComponent(slug)}` : "";
  const embedSnippet = slug ?
`<!-- ${slug} — reviews widget -->
<div id="pool-crm-reviews"></div>
<script src="${backendOrigin}/api/reviews/public/widget/${encodeURIComponent(slug)}.js"
        defer></script>` : "";
  const publicPage = slug ? `${window.location.origin}/reviews/${encodeURIComponent(slug)}` : "";

  useEffect(() => {
    api.get("/tenants/current").then((t) => setSlug(t?.slug || ""))
                                 .catch(() => setSlug(""));
  }, []);

  const copy = async (text, label) => {
    try {
      await navigator.clipboard.writeText(text);
      setToast({ tone: "success", message: `${label} copied` });
    } catch (e) { setToast({ tone: "error", message: "Clipboard blocked" }); }
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="reviews-widget-page">
      <Toast toast={toast} onClose={() => setToast(null)} />
      <PageHeader
        icon={Globe}
        title="Widget & embed"
        subtitle="Show off your best reviews anywhere on the web — just copy the snippet."
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* LEFT: embed code + URLs */}
        <div className="space-y-4">
          <Card className="p-4" data-testid="reviews-widget-embed">
            <div className="text-xs font-semibold uppercase tracking-wider mb-2"
                  style={{ color: colors.muted }}>Embed snippet</div>
            <pre className="text-xs p-3 rounded-lg overflow-x-auto whitespace-pre-wrap break-all"
                  style={{ background: colors.surfaceSecondary, color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}>{embedSnippet || "(loading…)"}</pre>
            <div className="mt-2 flex justify-end">
              <BtnPrimary disabled={!embedSnippet}
                            testid="reviews-widget-copy-embed"
                            onClick={() => copy(embedSnippet, "Embed snippet")}>
                <span className="inline-flex items-center gap-1.5"><Copy size={13} /> Copy embed</span>
              </BtnPrimary>
            </div>
          </Card>

          <Card className="p-4" data-testid="reviews-widget-links">
            <div className="text-xs font-semibold uppercase tracking-wider mb-2"
                  style={{ color: colors.muted }}>Direct links</div>
            <div className="text-xs mb-1" style={{ color: colors.muted }}>Public widget page</div>
            <div className="flex items-center gap-2 mb-3">
              <code className="flex-1 text-xs p-2 rounded-lg overflow-x-auto"
                     style={{ background: colors.surfaceSecondary, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}>
                {publicPage || "(loading…)"}
              </code>
              <BtnGhost disabled={!publicPage}
                         testid="reviews-widget-copy-public"
                         onClick={() => copy(publicPage, "Public URL")}>
                <Copy size={13} />
              </BtnGhost>
              <a href={publicPage} target="_blank" rel="noreferrer">
                <BtnGhost><ExternalLink size={13} /></BtnGhost>
              </a>
            </div>

            <div className="text-xs mb-1" style={{ color: colors.muted }}>Raw JSON endpoint</div>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-xs p-2 rounded-lg overflow-x-auto"
                     style={{ background: colors.surfaceSecondary, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}>
                {previewUrl || "(loading…)"}
              </code>
              <BtnGhost disabled={!previewUrl}
                         testid="reviews-widget-copy-api"
                         onClick={() => copy(previewUrl, "API URL")}>
                <Copy size={13} />
              </BtnGhost>
              <a href={previewUrl} target="_blank" rel="noreferrer">
                <BtnGhost><ExternalLink size={13} /></BtnGhost>
              </a>
            </div>
          </Card>
        </div>

        {/* RIGHT: preview */}
        <Card className="p-4" data-testid="reviews-widget-preview">
          <div className="text-xs font-semibold uppercase tracking-wider mb-2"
                style={{ color: colors.muted }}>Live preview</div>
          {previewUrl ? (
            <WidgetLivePreview slug={slug} />
          ) : (
            <div className="text-sm" style={{ color: colors.muted }}>Loading tenant slug…</div>
          )}
        </Card>
      </div>
    </div>
  );
}

function WidgetLivePreview({ slug }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!slug) return;
    const base = process.env.REACT_APP_BACKEND_URL;
    fetch(`${base}/api/reviews/public/widget/${encodeURIComponent(slug)}?limit=6`)
      .then((r) => r.json())
      .then((d) => setData(d))
      .catch((e) => setErr(e.message));
  }, [slug]);

  if (err) return <div className="text-sm" style={{ color: colors.muted }}>Preview unavailable: {err}</div>;
  if (!data) return <div className="text-sm" style={{ color: colors.muted }}>Loading…</div>;

  return (
    <div>
      <div className="flex items-center gap-2 mb-3">
        <div className="text-3xl font-bold" style={{ color: colors.onSurface }}>
          {(data.avg_star || 0).toFixed(1)}
        </div>
        <StarRatingDisplay value={data.avg_star || 0} size={20} />
        <div className="text-xs" style={{ color: colors.muted }}>
          based on {data.total_public || 0} public reviews
        </div>
      </div>
      {(data.reviews || []).length ? (
        <div className="space-y-3">
          {(data.reviews || []).slice(0, 4).map((r, i) => (
            <ReviewCard key={i} review={r} testid={`reviews-widget-preview-card-${i}`} />
          ))}
        </div>
      ) : (
        <div className="text-sm" style={{ color: colors.muted }}>
          No public reviews yet — visible reviews will appear here once flagged as public + widget-visible.
        </div>
      )}
    </div>
  );
}

export default ReviewsDashboard;
