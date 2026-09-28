/**
 * MTH-B · Feb-2026 — Revisions timeline + revert.
 *
 * Fetches ``GET /api/tenant-ai-rules/revisions`` and renders a
 * newest-first table.  Each row's "Revert" opens a reason modal
 * with a diff preview vs the current head.  Pagination surfaces
 * "Load more" when the tail hasn't been fetched (``count`` from
 * the server hits the page limit).
 *
 * "Categories changed" chips derive from a JSON diff against the
 * revision immediately newer in the list (rev N vs N-1) since the
 * MTH-A snapshot doesn't carry an explicit ``categories_changed``
 * field.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { RotateCcw, History } from "lucide-react";
import { api } from "@/api";
import { Button, Chip, Skeleton, EmptyState } from "@/components/ui-kit";
import RulesReasonModal from "./RulesReasonModal";

const CATEGORY_LABELS = {
  tone_voice: "Tone & Voice",
  auto_action_allowlist: "Auto-Actions",
  employee_enable_disable: "Employees",
  working_hours: "Working Hours",
  escalation_rules: "Escalation",
};

function categoriesChangedBetween(newer, older) {
  const a = newer?.rules || {};
  const b = older?.rules || {};
  const cats = new Set([
    ...Object.keys(a),
    ...Object.keys(b),
  ]);
  const out = [];
  cats.forEach((c) => {
    try {
      if (JSON.stringify(a[c]) !== JSON.stringify(b[c])) out.push(c);
    } catch {
      /* skip incomparable */
    }
  });
  return out;
}

export default function RevisionsTab({
  onReverted,
  pageSize = 25,
  autoLoad = true,
}) {
  const [revisions, setRevisions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [loadedLimit, setLoadedLimit] = useState(pageSize);
  const [totalReturned, setTotalReturned] = useState(0);
  const [revertOpen, setRevertOpen] = useState(false);
  const [pendingRev, setPendingRev] = useState(null);

  const load = useCallback(
    async (nextLimit) => {
      setLoading(true);
      try {
        const res = await api.get(
          `/tenant-ai-rules/revisions?limit=${nextLimit}`,
        );
        const arr = Array.isArray(res?.revisions) ? res.revisions : [];
        setRevisions(arr);
        setTotalReturned(arr.length);
      } catch (e) {
        toast.error(
          `Load revisions failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
        );
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (autoLoad) load(loadedLimit);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoLoad]);

  const changed = useMemo(() => {
    const out = new Map();
    // Revisions are newest-first — categories_changed for row i is
    // the diff between revisions[i] and revisions[i+1].
    for (let i = 0; i < revisions.length; i += 1) {
      const cats = categoriesChangedBetween(
        revisions[i],
        revisions[i + 1] || null,
      );
      out.set(revisions[i].revision_number, cats);
    }
    return out;
  }, [revisions]);

  const openRevert = (rev) => {
    setPendingRev(rev);
    setRevertOpen(true);
  };

  const doRevert = async (reason) => {
    if (!pendingRev) return;
    try {
      const res = await api.post(
        `/tenant-ai-rules/revert/${pendingRev.revision_number}`,
        { reason },
      );
      toast.success(
        `Reverted to revision #${pendingRev.revision_number}. New head: #${res?.revision_number}.`,
      );
      setRevertOpen(false);
      setPendingRev(null);
      await load(loadedLimit);
      if (onReverted) await onReverted();
    } catch (e) {
      toast.error(
        `Revert failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  const loadMore = () => {
    const next = loadedLimit + pageSize;
    setLoadedLimit(next);
    load(next);
  };

  return (
    <div className="space-y-4" data-testid="ai-rules-revisions-tab">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "#F1F5F9", color: "#334155" }}
          >
            <History size={16} />
          </div>
          <div>
            <div className="text-sm font-bold">Revisions</div>
            <div className="text-xs opacity-60">
              Every save writes an immutable snapshot. Revert to restore.
            </div>
          </div>
        </div>
        <div className="text-xs opacity-60" data-testid="ai-rules-revisions-count">
          {totalReturned} loaded
        </div>
      </div>

      {loading && revisions.length === 0 ? (
        <Skeleton className="h-32" />
      ) : revisions.length === 0 ? (
        <EmptyState
          icon={History}
          title="No revisions yet"
          hint="Save a rule change to create the first revision."
        />
      ) : (
        <div
          className="rounded-lg border overflow-hidden"
          style={{ borderColor: "#E2E8F0" }}
          data-testid="ai-rules-revisions-table"
        >
          <div
            className="grid grid-cols-12 text-[11px] font-semibold tracking-wide px-3 py-2"
            style={{ background: "#F1F5F9", color: "#334155" }}
          >
            <div className="col-span-1">#</div>
            <div className="col-span-3">TIMESTAMP</div>
            <div className="col-span-2">ACTOR</div>
            <div className="col-span-3">CATEGORIES</div>
            <div className="col-span-2">REASON</div>
            <div className="col-span-1 text-right">ACT</div>
          </div>
          {revisions.map((r) => {
            const cats = changed.get(r.revision_number) || [];
            return (
              <div
                key={r.revision_number}
                className="grid grid-cols-12 gap-2 items-start px-3 py-2 text-sm"
                style={{
                  borderTop: "1px solid #F1F5F9",
                }}
                data-testid={`ai-rules-revision-row-${r.revision_number}`}
              >
                <div className="col-span-1 font-mono text-xs">
                  #{r.revision_number}
                </div>
                <div className="col-span-3 text-xs opacity-80">
                  {r.last_updated_at || "—"}
                </div>
                <div className="col-span-2 text-xs">
                  {r.last_updated_by_name || "system"}
                </div>
                <div className="col-span-3 flex flex-wrap gap-1">
                  {cats.length === 0 ? (
                    <span className="text-xs opacity-50">—</span>
                  ) : (
                    cats.map((c) => (
                      <Chip
                        key={c}
                        label={CATEGORY_LABELS[c] || c}
                        tone="brand"
                        testid={`ai-rules-revision-row-${r.revision_number}-cat-${c}`}
                      />
                    ))
                  )}
                </div>
                <div className="col-span-2 text-xs opacity-80 line-clamp-2">
                  {r.last_update_reason || "—"}
                </div>
                <div className="col-span-1 flex justify-end">
                  <Button
                    variant="ghost"
                    onClick={() => openRevert(r)}
                    className="text-xs"
                    testid={`ai-rules-revision-row-${r.revision_number}-revert`}
                  >
                    <RotateCcw size={12} /> Revert
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {totalReturned >= loadedLimit ? (
        <div className="flex justify-center">
          <Button
            variant="ghost"
            onClick={loadMore}
            testid="ai-rules-revisions-load-more"
          >
            Load more
          </Button>
        </div>
      ) : null}

      <RulesReasonModal
        open={revertOpen}
        onClose={() => {
          setRevertOpen(false);
          setPendingRev(null);
        }}
        title={
          pendingRev
            ? `Revert to revision #${pendingRev.revision_number}?`
            : "Revert"
        }
        description="Reverting writes a NEW revision on top of history that clones the selected snapshot's rules. The revert itself is auditable."
        preview={
          pendingRev ? (
            <div className="text-xs" data-testid="ai-rules-revert-preview">
              <div>
                <strong>{CATEGORY_LABELS.tone_voice}:</strong>{" "}
                {pendingRev?.rules?.tone_voice?.style || "—"}
              </div>
              <div>
                <strong>{CATEGORY_LABELS.working_hours}:</strong>{" "}
                {pendingRev?.rules?.working_hours?.timezone || "—"} ·{" "}
                {(pendingRev?.rules?.working_hours?.windows || []).length}{" "}
                window(s)
              </div>
              <div>
                <strong>{CATEGORY_LABELS.escalation_rules}:</strong>{" "}
                {(pendingRev?.rules?.escalation_rules || []).length} rule(s)
              </div>
            </div>
          ) : null
        }
        onConfirm={doRevert}
        confirmLabel="Revert"
        confirmVariant="danger"
        testidPrefix="ai-rules-revert-reason"
      />
    </div>
  );
}

export { categoriesChangedBetween };
