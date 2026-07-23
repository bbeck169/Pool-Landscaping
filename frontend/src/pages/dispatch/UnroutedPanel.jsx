// Phase 17 · Feb-2026 — Unrouted customers panel + Suggest button.
//
// Renders active customers who are NOT on the current day/tech
// route. Each row can request a smart-suggestion via
// ``POST /api/dispatch/suggest-route`` — the response is inlined
// under the row so the admin can apply directly.
import React from "react";
import { toast } from "sonner";
import {
  AlertCircle, Sparkles, ChevronDown, ChevronUp, MapPin, Check, PlusCircle,
} from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

const REASON_LABEL = {
  no_service_day: "No service day",
  no_tech_assigned: "No tech assigned",
  not_on_this_day: "Not on this day",
};

const CONFIDENCE_TONE = {
  high: { bg: "#DCFCE7", fg: "#166534", border: "#86EFAC" },
  medium: { bg: "#DBEAFE", fg: "#1E40AF", border: "#93C5FD" },
  low: { bg: "#FEF3C7", fg: "#92400E", border: "#FDE68A" },
};

export default function UnroutedPanel({
  items = [],
  onApply = () => {},
  onSelect = () => {},
}) {
  const [open, setOpen] = React.useState(true);
  const [suggestions, setSuggestions] = React.useState({});   // {customer_id: {suggestion, alternatives}}
  const [showAlts, setShowAlts] = React.useState({});
  const [suggestingAll, setSuggestingAll] = React.useState(false);

  const requestSuggest = async (customerIds) => {
    try {
      const res = await api.post("/dispatch/suggest-route", {
        customer_ids: customerIds,
      });
      const next = { ...suggestions };
      (res?.items || []).forEach((r) => { next[r.customer_id] = r; });
      setSuggestions(next);
      return res;
    } catch (e) {
      toast.error(`Suggest failed: ${e.message || e}`);
      return null;
    }
  };

  const onSuggestAll = async () => {
    setSuggestingAll(true);
    try {
      await requestSuggest(items.map((i) => i.customer_id));
    } finally { setSuggestingAll(false); }
  };

  const onApplyHighConfidence = async () => {
    let applied = 0;
    for (const [cid, s] of Object.entries(suggestions)) {
      const top = s?.suggestion;
      if (top && top.confidence === "high") {
        onApply({ customer_id: cid, suggestion: top });
        applied += 1;
      }
    }
    toast.success(`Applied ${applied} high-confidence suggestion(s).`);
  };

  if (!items.length) {
    return (
      <div
        className="rounded-xl p-3"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="dispatch-unrouted-empty"
      >
        <div
          className="text-xs uppercase tracking-wide font-semibold mb-1 flex items-center gap-1"
          style={{ color: colors.muted }}
        >
          <AlertCircle size={12} /> Unrouted customers (0)
        </div>
        <div className="text-xs" style={{ color: colors.muted }}>
          Everyone active is on a route. Nice.
        </div>
      </div>
    );
  }

  return (
    <div
      className="rounded-xl p-3 space-y-2"
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid="dispatch-unrouted-panel"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between text-xs uppercase tracking-wide font-semibold"
        style={{ color: colors.muted }}
        data-testid="dispatch-unrouted-toggle"
      >
        <span className="flex items-center gap-1">
          <AlertCircle size={12} /> Unrouted customers
          <span
            className="ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold"
            style={{ backgroundColor: "#F97316", color: "#fff" }}
            data-testid="dispatch-unrouted-count"
          >
            {items.length}
          </span>
        </span>
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>
      {open && (
        <>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onSuggestAll}
              disabled={suggestingAll}
              className="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded-md text-xs font-semibold hover:brightness-95 disabled:opacity-60"
              style={{
                backgroundColor: colors.brand, color: "#fff",
              }}
              data-testid="dispatch-unrouted-suggest-all"
            >
              <Sparkles size={11} /> {suggestingAll ? "…" : "Suggest all"}
            </button>
            <button
              type="button"
              onClick={onApplyHighConfidence}
              className="px-2 py-1 rounded-md text-xs font-semibold hover:brightness-95"
              style={{
                backgroundColor: "#DCFCE7", color: "#166534",
                border: "1px solid #86EFAC",
              }}
              data-testid="dispatch-unrouted-apply-high"
            >
              <Check size={11} className="inline mr-0.5" /> Apply high
            </button>
          </div>
          <ul className="space-y-1.5" data-testid="dispatch-unrouted-list">
            {items.map((it) => {
              const s = suggestions[it.customer_id];
              const showAlt = showAlts[it.customer_id];
              return (
                <li
                  key={it.customer_id}
                  className="rounded-lg p-2"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid={`dispatch-unrouted-row-${it.customer_id}`}
                >
                  <button
                    type="button"
                    onClick={() => onSelect(it.customer_id)}
                    className="w-full text-left"
                    data-testid={`dispatch-unrouted-select-${it.customer_id}`}
                  >
                    <div className="text-xs font-semibold truncate"
                         style={{ color: colors.onSurface }}>
                      {it.name || "(unnamed)"}
                    </div>
                    <div className="text-[11px] flex items-center gap-1 truncate"
                         style={{ color: colors.muted }}>
                      <MapPin size={10} />
                      {it.address || "No address"}
                    </div>
                  </button>
                  <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                    <span
                      className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full"
                      style={{
                        backgroundColor: "#FEE2E2", color: "#991B1B",
                        border: "1px solid #FECACA",
                      }}
                      data-testid={`dispatch-unrouted-reason-${it.customer_id}`}
                    >
                      {REASON_LABEL[it.reason] || it.reason}
                    </span>
                    <button
                      type="button"
                      onClick={() => requestSuggest([it.customer_id])}
                      className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md hover:brightness-95 flex items-center gap-1"
                      style={{
                        backgroundColor: colors.brand, color: "#fff",
                      }}
                      data-testid={`dispatch-unrouted-suggest-${it.customer_id}`}
                    >
                      <Sparkles size={10} /> Suggest
                    </button>
                    <button
                      type="button"
                      onClick={() => onApply({ customer_id: it.customer_id })}
                      className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md hover:brightness-95 flex items-center gap-1"
                      style={{
                        backgroundColor: colors.surface, color: colors.onSurface,
                        border: `1px solid ${colors.border}`,
                      }}
                      data-testid={`dispatch-unrouted-assign-${it.customer_id}`}
                    >
                      <PlusCircle size={10} /> Assign
                    </button>
                  </div>
                  {s?.suggestion ? (
                    <SuggestionCard
                      customerId={it.customer_id}
                      top={s.suggestion}
                      alternatives={s.alternatives}
                      showAlt={showAlt}
                      onToggleAlt={() => setShowAlts((cur) => ({
                        ...cur, [it.customer_id]: !cur[it.customer_id],
                      }))}
                      onApply={onApply}
                    />
                  ) : null}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

function SuggestionCard({ customerId, top, alternatives = [], showAlt, onToggleAlt, onApply }) {
  const tone = CONFIDENCE_TONE[top.confidence] || CONFIDENCE_TONE.low;
  return (
    <div
      className="mt-1.5 rounded-md p-2"
      style={{ backgroundColor: "#EFF6FF", border: "1px solid #BFDBFE" }}
      data-testid={`dispatch-unrouted-suggestion-${customerId}`}
    >
      <div className="text-xs font-semibold" style={{ color: "#1E3A8A" }}>
        Best fit: <strong>{top.tech_name}</strong> · {top.day_label} ·{" "}
        pos {top.insertion_index + 1} (+{Math.round(top.added_seconds / 60)} min)
      </div>
      <div className="text-[11px] mt-0.5" style={{ color: "#1E40AF" }}>
        {top.rationale}
      </div>
      <div className="mt-1 flex items-center gap-1.5">
        <span
          className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
          style={{ backgroundColor: tone.bg, color: tone.fg, border: `1px solid ${tone.border}` }}
          data-testid={`dispatch-unrouted-confidence-${customerId}`}
        >
          {top.confidence}
        </span>
        <button
          type="button"
          onClick={() => onApply({ customer_id: customerId, suggestion: top })}
          className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md hover:brightness-95"
          style={{ backgroundColor: "#1D4ED8", color: "#fff" }}
          data-testid={`dispatch-unrouted-apply-suggestion-${customerId}`}
        >
          Apply
        </button>
        {alternatives?.length ? (
          <button
            type="button"
            onClick={onToggleAlt}
            className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md hover:brightness-95"
            style={{ backgroundColor: "#F1F5F9", color: "#0F172A", border: "1px solid #CBD5E1" }}
            data-testid={`dispatch-unrouted-toggle-alts-${customerId}`}
          >
            {showAlt ? "Hide alts" : `Show ${alternatives.length} more`}
          </button>
        ) : null}
      </div>
      {showAlt && alternatives?.length ? (
        <ul className="mt-1.5 space-y-1"
            data-testid={`dispatch-unrouted-alts-${customerId}`}>
          {alternatives.map((alt, i) => (
            <li key={i} className="text-[11px] flex items-center gap-1.5"
                style={{ color: "#1E3A8A" }}>
              {alt.tech_name} · {alt.day_label} (+{Math.round(alt.added_seconds/60)} min)
              <button
                type="button"
                onClick={() => onApply({ customer_id: customerId, suggestion: alt })}
                className="text-[10px] px-1 py-0.5 rounded-md hover:brightness-95"
                style={{ backgroundColor: "#1D4ED8", color: "#fff" }}
              >
                Apply
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
