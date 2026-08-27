/**
 * Feb 2026 · Phase 2 Custom Trigger Builder · LiveMatchPreview.
 *
 * Right-hand panel that shows the live match count for the current
 * (unsaved) trigger by calling
 * ``POST /api/marketing/sequences/{sid}/preview-matches`` with
 * ``trigger_override``. 500ms debounce so we don't hammer the
 * server on every keystroke.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Zap, Users, Loader2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { buildTriggerPayload } from "./helpers";


export function LiveMatchPreview({ sequenceId, trigger, enabled = true, testIdPrefix = "trigger-preview" }) {
  const [state, setState] = useState({ loading: false, data: null, error: "" });
  const debounceRef = useRef(null);

  // Signature we compare against — trigger a fetch only when the
  // payload actually changed.
  const payload = useMemo(() => buildTriggerPayload(trigger), [trigger]);
  const signature = useMemo(() => JSON.stringify(payload), [payload]);
  const canPreview = !!sequenceId && enabled && (payload.conditions || []).length > 0;

  useEffect(() => {
    if (!canPreview) {
      setState({ loading: false, data: null, error: "" });
      return undefined;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setState((s) => ({ ...s, loading: true, error: "" }));
      try {
        const res = await api.post(
          `/marketing/sequences/${sequenceId}/preview-matches`,
          { trigger_override: payload, limit: 25 },
          20000,
        );
        setState({ loading: false, data: res, error: "" });
      } catch (e) {
        setState({ loading: false, data: null, error: e?.message || "Preview failed" });
      }
    }, 500);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, sequenceId, canPreview]);

  const count = state.data?.match_count ?? null;
  const sample = state.data?.sample || [];
  const truncated = !!state.data?.truncated;

  return (
    <div
      className="rounded-xl p-4 h-full flex flex-col"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px solid ${colors.divider}`,
      }}
      data-testid={`${testIdPrefix}-wrap`}
    >
      <div className="flex items-center gap-2 mb-3">
        <Zap size={14} style={{ color: colors.accent.emerald[600] }} />
        <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
          Live match preview
        </div>
      </div>

      {!canPreview ? (
        <div
          className="flex-1 text-sm flex items-center justify-center text-center px-4"
          style={{ color: colors.muted }}
          data-testid={`${testIdPrefix}-idle`}
        >
          Add a condition to see match count.
        </div>
      ) : state.loading && !state.data ? (
        <div
          className="flex-1 flex items-center justify-center gap-2 text-sm"
          style={{ color: colors.muted }}
          data-testid={`${testIdPrefix}-loading`}
        >
          <Loader2 size={14} className="animate-spin" /> Counting matches…
        </div>
      ) : state.error ? (
        <div
          className="text-sm p-3 rounded-lg"
          style={{ color: colors.error, backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid={`${testIdPrefix}-error`}
        >
          {state.error}
        </div>
      ) : (
        <>
          <div
            className="text-4xl font-bold leading-tight"
            style={{
              color: count > 0 ? colors.accent.emerald[600] : colors.muted,
            }}
            data-testid={`${testIdPrefix}-count`}
          >
            {count === null ? "–" : count.toLocaleString()}
          </div>
          <div className="text-xs mb-3" style={{ color: colors.muted }}>
            {count === 0
              ? "No customers match right now"
              : `customer${count === 1 ? "" : "s"} would match today`}
            {truncated ? ` · showing sample of ${sample.length}` : ""}
            {state.loading ? (
              <span data-testid={`${testIdPrefix}-loading-inline`}> · refreshing…</span>
            ) : null}
          </div>

          {sample.length > 0 ? (
            <div
              className="flex-1 overflow-y-auto rounded-lg"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={`${testIdPrefix}-sample-list`}
            >
              {sample.map((row, i) => (
                <div
                  key={row.customer_id || i}
                  className="px-3 py-2 flex items-center gap-2 text-sm"
                  style={{
                    borderBottom: i === sample.length - 1 ? "none" : `1px solid ${colors.divider}`,
                  }}
                  data-testid={`${testIdPrefix}-sample-item-${i}`}
                >
                  <Users size={12} style={{ color: colors.muted }} />
                  <div className="flex-1 min-w-0">
                    <div className="truncate font-semibold" style={{ color: colors.onSurface }}>
                      {row.name || "Unnamed"}
                    </div>
                    {row.reason ? (
                      <div className="truncate text-[11px]" style={{ color: colors.muted }}>
                        {row.reason}
                      </div>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          ) : count === 0 ? (
            <div
              className="flex-1 text-sm flex items-center justify-center text-center"
              style={{ color: colors.muted }}
              data-testid={`${testIdPrefix}-empty`}
            >
              Loosen a filter or pick a different event to widen the audience.
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
