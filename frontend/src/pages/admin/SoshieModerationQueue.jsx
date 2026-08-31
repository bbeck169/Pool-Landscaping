/**
 * Phase F3 · Feb-2026 — Soshie Moderation Queue.
 *
 * Admin surface for reviewing posts that the LLM moderation gate
 * flagged or blocked. Shows platform, scheduled time, preview,
 * LLM decision + reasons pill, and Approve / Reject actions.
 *
 * Route: /admin/soshie/moderation
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { ShieldAlert, Clock, RefreshCw } from "lucide-react";
import { api } from "../../api";
import { colors } from "../../theme";
import { Button, PageHeader } from "../../components/ui-kit";
import ArmToDelete from "../../components/ui/ArmToDelete";

const STATUS_TABS = [
  { value: "awaiting_review", label: "Awaiting review" },
  { value: "blocked",         label: "Blocked" },
  { value: "rejected",        label: "Rejected" },
];

function ReasonPills({ reasons }) {
  if (!reasons || reasons.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {reasons.map((r, i) => (
        <span
          key={`${r}-${i}`}
          className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-semibold"
          style={{ background: "#FEE2E2", color: colors.error,
                   border: "1px solid #FCA5A5" }}
          data-testid={`moderation-reason-${i}`}
        >
          {r}
        </span>
      ))}
    </div>
  );
}

function DecisionPill({ decision }) {
  const tone = decision === "block"
    ? { bg: "#FEE2E2", fg: colors.error, border: "#FCA5A5" }
    : { bg: "#FEF3C7", fg: "#78350F", border: "#FDE68A" };
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-bold uppercase"
      style={{ background: tone.bg, color: tone.fg,
               border: `1px solid ${tone.border}` }}
      data-testid={`moderation-decision-${decision || "unknown"}`}
    >
      {decision || "flag"}
    </span>
  );
}

export default function SoshieModerationQueuePage() {
  const [tab, setTab] = useState("awaiting_review");
  const [posts, setPosts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const res = await api.get(`/soshie/moderation/queue?status=${tab}`);
      setPosts(res?.posts || []);
    } catch (e) {
      setError(e?.message || "Failed to load moderation queue");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  const approve = async (post) => {
    setBusyId(post.id);
    try {
      await api.post(`/soshie/moderation/${post.id}/approve`);
      toast.success(`Approved · queued for publish (${post.platform})`);
      await load();
    } catch (e) {
      toast.error(e?.message || "Approve failed");
    } finally {
      setBusyId(null);
    }
  };

  const reject = async (post) => {
    setBusyId(post.id);
    try {
      await api.post(`/soshie/moderation/${post.id}/reject`, {
        reason: "admin_reject",
      });
      toast.success("Post rejected");
      await load();
    } catch (e) {
      toast.error(e?.message || "Reject failed");
    } finally {
      setBusyId(null);
    }
  };

  const counts = useMemo(() => ({ [tab]: posts.length }), [tab, posts]);

  return (
    <div className="p-6" data-testid="soshie-moderation-page">
      <PageHeader
        title="Soshie Moderation"
        subtitle="Review flagged or blocked social posts before they publish."
        right={(
          <Button
            variant="ghost"
            onClick={load}
            testid="soshie-moderation-refresh"
          >
            <RefreshCw size={12} /> Refresh
          </Button>
        )}
      />

      <div
        className="mt-4 inline-flex rounded-lg p-1 gap-1"
        style={{ background: colors.surfaceSecondary,
                 border: `1px solid ${colors.border}` }}
        data-testid="soshie-moderation-tabs"
      >
        {STATUS_TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className="px-3 py-1 rounded-md text-xs font-semibold"
            style={tab === t.value
              ? { background: colors.surface, color: colors.onSurface,
                  border: `1px solid ${colors.border}` }
              : { background: "transparent", color: colors.muted }}
            data-testid={`soshie-moderation-tab-${t.value}`}
          >
            {t.label}
            {tab === t.value ? ` · ${counts[t.value] ?? 0}` : ""}
          </button>
        ))}
      </div>

      {error ? (
        <div className="mt-4 p-3 rounded-lg text-sm"
             style={{ background: "#FEE2E2", color: colors.error,
                      border: "1px solid #FCA5A5" }}
             data-testid="soshie-moderation-error">
          {error}
        </div>
      ) : null}

      <div className="mt-4 flex flex-col gap-3"
           data-testid="soshie-moderation-list">
        {loading && posts.length === 0 ? (
          <div className="p-6 text-sm text-center"
               style={{ color: colors.muted }}
               data-testid="soshie-moderation-loading">
            Loading…
          </div>
        ) : posts.length === 0 ? (
          <div className="p-8 text-sm text-center rounded-xl"
               style={{ background: colors.surfaceSecondary,
                        color: colors.muted,
                        border: `1px solid ${colors.border}` }}
               data-testid="soshie-moderation-empty">
            <ShieldAlert size={20} className="mx-auto mb-2"
                         style={{ color: colors.muted }} />
            Nothing in the {tab.replace("_", " ")} queue.
          </div>
        ) : posts.map((p) => (
          <div key={p.id}
               className="p-4 rounded-xl flex flex-col gap-2"
               style={{ background: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid={`soshie-moderation-row-${p.id}`}>
            <div className="flex items-start gap-3">
              {p.media_url ? (
                <img src={p.media_url} alt=""
                     className="w-16 h-16 rounded-md object-cover"
                     style={{ border: `1px solid ${colors.border}` }} />
              ) : (
                <div className="w-16 h-16 rounded-md flex items-center justify-center"
                     style={{ background: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}`,
                              color: colors.muted }}>
                  <ShieldAlert size={20} />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-bold uppercase"
                        style={{ color: colors.onSurface }}>
                    {p.platform || "unknown"}
                  </span>
                  <span className="inline-flex items-center gap-1 text-[11px]"
                        style={{ color: colors.muted }}>
                    <Clock size={11} />
                    {p.scheduled_at
                      ? new Date(p.scheduled_at).toLocaleString()
                      : "—"}
                  </span>
                  <DecisionPill decision={p.moderation_decision} />
                </div>
                <div className="mt-1 text-sm"
                     style={{ color: colors.onSurface }}
                     data-testid={`soshie-moderation-preview-${p.id}`}>
                  {p.preview || "(no preview)"}
                </div>
                <ReasonPills reasons={p.moderation_reasons} />
              </div>
            </div>
            {tab !== "rejected" ? (
              <div className="flex items-center gap-2 justify-end">
                <Button
                  onClick={() => approve(p)}
                  disabled={busyId === p.id}
                  testid={`soshie-moderation-approve-${p.id}`}
                >
                  Approve &amp; publish
                </Button>
                <ArmToDelete
                  count={1}
                  catastrophicThreshold={9999}
                  disabled={busyId === p.id}
                  onConfirm={() => reject(p)}
                  label="Reject"
                  testIdPrefix={`soshie-moderation-reject-${p.id}`}
                  size="sm"
                />
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
