/**
 * SO-A · Feb-2026 — MARCO Suggestions React hook.
 *
 * Owns the "load top-N recommendations + apply" state machine so
 * CalendarSchedule.jsx can stay a thin consumer.  Exposed in tests
 * directly so we don't need to mount the whole 3.4kLOC page.
 */
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api } from "@/api";

export function useMarcoRecommendations({
  jobId, targetDate, autoFetch = true, maxSuggestions = 3,
}) {
  const [state, setState] = useState({
    loading: false, error: null, result: null,
  });

  const fetchRecommendations = useCallback(async () => {
    if (!jobId || !targetDate) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const result = await api.post("/schedule/ai-recommendation", {
        job_id: jobId, target_date: targetDate,
        max_suggestions: maxSuggestions,
      });
      setState({ loading: false, error: null, result });
    } catch (e) {
      const status = e?.status || e?.data?.status || null;
      const code = e?.data?.detail?.error_code
        || e?.data?.error_code || null;
      if (status === 429 || code === "schedule_ai_rate_limit_exceeded") {
        const retry = e?.data?.detail?.retry_after_seconds
          || e?.data?.retry_after_seconds || 60;
        toast.error(
          `Suggestion budget exceeded — retry in ${retry}s.`,
        );
      } else if (code === "target_job_missing_coords") {
        toast.error(
          "This job has no address coordinates yet — geocode it first.",
        );
      }
      setState({
        loading: false,
        error: e?.data?.detail?.message
          || e?.data?.message || e?.message || "unknown_error",
        result: null,
      });
    }
  }, [jobId, targetDate, maxSuggestions]);

  useEffect(() => {
    if (autoFetch) fetchRecommendations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, targetDate, autoFetch]);

  const applySuggestion = useCallback(async (suggestion) => {
    if (!suggestion || !state.result) return null;
    try {
      const resp = await api.post("/schedule/apply-recommendation", {
        job_id: state.result.job_id,
        technician_id: suggestion.technician_id,
        insertion_index: suggestion.insertion_index,
        source_recommendation: {
          detour_minutes: suggestion.detour_minutes,
          detour_miles: suggestion.detour_miles,
          rank: suggestion.rank,
          score: suggestion.score,
        },
      });
      if (resp.status === "applied") {
        toast.success(
          `Assigned to ${suggestion.technician_name}. Route updated.`,
        );
      } else {
        toast.info(
          "Suggestion queued for admin approval.",
        );
      }
      return resp;
    } catch (e) {
      toast.error(
        `Apply failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
      return null;
    }
  }, [state.result]);

  return {
    loading: state.loading,
    error: state.error,
    result: state.result,
    refetch: fetchRecommendations,
    applySuggestion,
  };
}
