/**
 * SO-A · Feb-2026 — MARCO Suggestions right-side drawer.
 *
 * Auto-fires when a job is selected on the schedule.  Renders the
 * top-3 recommendation cards, empty/loading/error states, and the
 * rate-limit chip.  All the network + state machinery lives in
 * :file:`lib/marcoRecommendations.js` so this component stays
 * presentation-focused.
 */
import React from "react";
import { Sparkles, X as XIcon, Zap, Loader2 } from "lucide-react";
import { Button, Chip } from "@/components/ui-kit";
import { useMarcoRecommendations } from "@/lib/marcoRecommendations";

const RANK_MEDAL = ["🥇", "🥈", "🥉"];

function formatDetour(minutes, miles) {
  const min = Number.isFinite(minutes) ? minutes.toFixed(1) : "?";
  const mi = Number.isFinite(miles) ? miles.toFixed(1) : "?";
  return `+${min} min · +${mi} mi`;
}

function providerLabel(p) {
  if (p === "google") return "Google";
  if (p === "osrm") return "OSRM";
  return "Crow-flies";
}

function InsertionTimeline({ suggestion }) {
  const total = (suggestion.route_len ?? 0) + 1;
  const idx = suggestion.insertion_index;
  return (
    <div
      className="mt-2 flex items-center gap-1 text-[11px] font-mono"
      style={{ color: "#334155" }}
      data-testid={`marco-suggestion-timeline-${idx}`}
    >
      {Array.from({ length: total }).map((_, i) => {
        const isNew = i === idx;
        return (
          <React.Fragment key={i}>
            {i > 0 ? <span className="opacity-40">→</span> : null}
            {isNew ? (
              <span
                className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded"
                style={{ background: "#DCFCE7", color: "#166534",
                          border: "1px solid #BBF7D0" }}
                data-testid={`marco-suggestion-timeline-new-${idx}`}
              >
                NEW
              </span>
            ) : (
              <span className="opacity-70">{i > idx ? i : i + 1}</span>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

function SuggestionCard({ suggestion, applyMode, onApply, busy }) {
  const label = applyMode === "one_click"
    ? "Apply Optimization"
    : "Suggest Reassignment";
  const medal = RANK_MEDAL[(suggestion.rank ?? 1) - 1] || "🎯";
  return (
    <div
      className="rounded-xl border p-3 space-y-2"
      style={{ borderColor: "#E2E8F0", background: "#FFFFFF" }}
      data-testid={`marco-suggestion-card-${suggestion.rank}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span
            className="text-lg leading-none"
            data-testid={`marco-suggestion-medal-${suggestion.rank}`}
          >
            {medal}
          </span>
          <div className="min-w-0">
            <div
              className="text-sm font-bold truncate"
              data-testid={`marco-suggestion-tech-${suggestion.rank}`}
            >
              {suggestion.technician_name}
            </div>
            <div className="text-[11px] opacity-70 truncate">
              Insertion at position {suggestion.insertion_index + 1}
            </div>
          </div>
        </div>
        <Chip
          label={formatDetour(
            suggestion.detour_minutes, suggestion.detour_miles,
          )}
          tone={suggestion.detour_minutes < 5 ? "success" : "brand"}
          testid={`marco-suggestion-detour-${suggestion.rank}`}
        />
      </div>
      <div
        className="text-sm"
        style={{ color: "#1F2937" }}
        data-testid={`marco-suggestion-plainenglish-${suggestion.rank}`}
      >
        {suggestion.plain_english}
      </div>
      <InsertionTimeline suggestion={suggestion} />
      <div className="flex items-center justify-between pt-1">
        <Chip
          label={providerLabel(suggestion.provider_used)}
          tone="neutral"
          testid={`marco-suggestion-provider-${suggestion.rank}`}
        />
        <Button
          variant={applyMode === "one_click" ? "primary" : "ghost"}
          onClick={() => onApply(suggestion)}
          disabled={busy}
          testid={`marco-suggestion-apply-${suggestion.rank}`}
        >
          {busy ? (
            <><Loader2 size={12} className="animate-spin" /> Applying…</>
          ) : (
            <><Zap size={12} /> {label}</>
          )}
        </Button>
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div
      className="space-y-3"
      data-testid="marco-suggestions-loading"
    >
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="rounded-xl border p-3 space-y-2 animate-pulse"
          style={{ borderColor: "#E2E8F0", background: "#F8FAFC" }}
          data-testid={`marco-suggestions-skeleton-${i}`}
        >
          <div className="h-4 w-3/4 rounded"
                style={{ background: "#E2E8F0" }} />
          <div className="h-3 w-1/2 rounded"
                style={{ background: "#E2E8F0" }} />
          <div className="h-3 w-full rounded"
                style={{ background: "#E2E8F0" }} />
        </div>
      ))}
    </div>
  );
}

export function MarcoSuggestionsPanel({
  jobId, targetDate, onClose, onApplied, autoFetch = true,
}) {
  const {
    loading, error, result, refetch, applySuggestion,
  } = useMarcoRecommendations({
    jobId, targetDate, autoFetch,
  });
  const [applying, setApplying] = React.useState(null);

  const handleApply = async (suggestion) => {
    setApplying(suggestion.rank);
    const resp = await applySuggestion(suggestion);
    setApplying(null);
    if (resp && onApplied) await onApplied(resp);
  };

  return (
    <aside
      className="fixed top-14 right-0 h-[calc(100vh-3.5rem)] w-[380px] shadow-xl border-l overflow-y-auto z-40"
      style={{ background: "#FFFFFF", borderColor: "#E2E8F0" }}
      data-testid="marco-suggestions-panel"
    >
      <header
        className="sticky top-0 z-10 px-4 py-3 flex items-center justify-between border-b"
        style={{ background: "#FFFFFF", borderColor: "#E2E8F0" }}
      >
        <div className="flex items-center gap-2">
          <Sparkles size={18} style={{ color: "#7C3AED" }} />
          <div>
            <div className="text-sm font-bold">MARCO Suggestions</div>
            <div className="text-[11px] opacity-60">
              Best-fit techs for {targetDate}
            </div>
          </div>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="text-lg opacity-60 hover:opacity-100"
            data-testid="marco-suggestions-close"
            aria-label="Close"
          >
            <XIcon size={18} />
          </button>
        ) : null}
      </header>

      <div className="p-4 space-y-3">
        {loading ? <LoadingSkeleton /> : null}

        {!loading && error ? (
          <div
            className="rounded-lg border p-3 text-sm"
            style={{ borderColor: "#FCA5A5", background: "#FEE2E2",
                      color: "#991B1B" }}
            data-testid="marco-suggestions-error"
          >
            {error}
            <div className="mt-2">
              <Button
                variant="ghost"
                onClick={refetch}
                testid="marco-suggestions-retry"
              >
                Retry
              </Button>
            </div>
          </div>
        ) : null}

        {!loading && !error && result
          && (result.suggestions || []).length === 0 ? (
          <div
            className="text-sm opacity-70 p-6 text-center rounded-lg"
            style={{ background: "#F8FAFC" }}
            data-testid="marco-suggestions-empty"
          >
            No optimizations found for {targetDate}. Try selecting a
            different date or checking fleet enablement.
          </div>
        ) : null}

        {!loading && !error && result
          && (result.suggestions || []).length > 0 ? (
          <>
            {result.plain_english_source
              && result.plain_english_source !== "llm" ? (
              <div
                className="text-[11px] opacity-60"
                data-testid="marco-suggestions-fallback-notice"
              >
                Deterministic template used ({result.plain_english_source}).
              </div>
            ) : null}
            {(result.suggestions || []).map((s) => (
              <SuggestionCard
                key={s.rank}
                suggestion={s}
                applyMode={result.apply_mode}
                onApply={handleApply}
                busy={applying === s.rank}
              />
            ))}
          </>
        ) : null}
      </div>

      <footer
        className="sticky bottom-0 z-10 px-4 py-2 border-t text-[11px]"
        style={{ background: "#F8FAFC", borderColor: "#E2E8F0",
                  color: "#334155" }}
        data-testid="marco-suggestions-footer"
      >
        Budget: 10 suggestions/min
        {result?.rate_limit ? ` · ${result.rate_limit.remaining} left` : null}
        {result?.provider_used ? ` · via ${providerLabel(result.provider_used)}` : null}
      </footer>
    </aside>
  );
}

export default MarcoSuggestionsPanel;
