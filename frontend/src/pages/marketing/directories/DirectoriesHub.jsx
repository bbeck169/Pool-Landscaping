/**
 * Directories · Hub (D2 · Feb 2026)
 * -----------------------------------------------------------------
 * Landing dashboard for the Directories subsystem.
 *
 * Backend response shapes reused here (kept in sync with D1 tester
 * notes so future refactors don't drift the contract):
 *   GET  /api/directories/health
 *     → { overall_score, coverage_score, avg_nap_match_score,
 *          total_directories_available, submitted_count, verified_count,
 *          needs_update_count, in_progress_count, rejected_count,
 *          not_started_count, top_priority_missing:[{slug,name,category,priority}],
 *          last_scan_at }
 *   POST /api/directories/scan/run
 *     → { id, tenant_id, started_at, completed_at, directories_checked[],
 *          summary:{total_matched,total_mismatched,total_not_found},
 *          avg_score, run_type }
 *   POST /api/directories/submissions
 *     → { id, tenant_id, directory_slug, status, ... }  (idempotent)
 */
import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  ArrowLeft, Play, MapPin, RefreshCw, ListChecks, Gauge, AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

function scoreColor(score) {
  if (score == null) return colors.muted;
  if (score >= 80) return "#10b981"; // emerald
  if (score >= 50) return "#f59e0b"; // amber
  return "#ef4444";                    // red
}

function StatCard({ label, value, hint, testid }) {
  return (
    <div className="rounded-xl p-4"
         style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
         data-testid={testid}>
      <div className="text-xs uppercase tracking-wide" style={{ color: colors.muted }}>{label}</div>
      <div className="text-2xl font-bold mt-1" style={{ color: colors.onSurface }}>{value}</div>
      {hint ? <div className="text-[11px] mt-0.5" style={{ color: colors.muted }}>{hint}</div> : null}
    </div>
  );
}

export default function DirectoriesHub() {
  const nav = useNavigate();
  const [health, setHealth] = useState(null);
  const [busy, setBusy] = useState(false);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/directories/health");
      setHealth(r);
    } catch (e) {
      toast.error(e?.message || "Failed to load health");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const claim = async (slug) => {
    setBusy(true);
    try {
      await api.post("/directories/submissions", { directory_slug: slug });
      toast.success(`Started submission for ${slug}`);
      await load();
      nav("/marketing/directories/submissions");
    } catch (e) {
      toast.error(e?.message || "Failed to start submission");
    }
    setBusy(false);
  };

  const runScan = async () => {
    setScanning(true);
    try {
      const run = await api.post("/directories/scan/run", {});
      // Backend runs synchronously and returns the completed row —
      // ``completed_at`` is always set on success. If we ever move
      // to async, we'd poll GET /scan/runs/{id} here for
      // ``completed_at`` before showing the summary.
      const s = run?.summary || {};
      toast.success(
        `Scan complete. ${s.total_matched ?? 0} verified, ${s.total_mismatched ?? 0} mismatched, ${s.total_not_found ?? 0} not found.`
      );
      await load();
    } catch (e) {
      toast.error(e?.message || "Scan failed");
    }
    setScanning(false);
  };

  const overall = Number(health?.overall_score || 0);
  const scanAt = health?.last_scan_at
    ? new Date(health.last_scan_at).toLocaleString()
    : "never";

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-4"
          data-testid="directories-hub">
      <div className="flex items-center gap-3 mb-2">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            <ListChecks className="inline w-6 h-6 mr-2" />
            Directories & Citation Health
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Track your business listings across {health?.total_directories_available ?? "…"} directories.
            Cleaner NAP data means more inbound search leads.
          </p>
        </div>
        <Link to="/marketing/directories/nap-profile"
              className="text-xs px-3 py-2 rounded-lg border"
              style={{ borderColor: colors.border }}
              data-testid="directories-nap-link">
          <MapPin className="inline w-3 h-3 mr-1" /> Edit NAP Profile
        </Link>
        <Button onClick={runScan} disabled={scanning} data-testid="directories-scan-btn">
          {scanning
            ? <><RefreshCw className="w-4 h-4 mr-1 animate-spin" /> Scanning…</>
            : <><Play className="w-4 h-4 mr-1" /> Run scan now</>}
        </Button>
      </div>

      {/* Score hero */}
      <div className="rounded-2xl p-6 flex items-center gap-6 flex-wrap"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            data-testid="directories-score-hero">
        <div className="flex items-center gap-4">
          <Gauge className="w-10 h-10" style={{ color: scoreColor(overall) }} />
          <div>
            <div className="text-5xl font-black leading-none"
                  style={{ color: scoreColor(overall) }}
                  data-testid="directories-overall-score">
              {overall.toFixed(0)}
              <span className="text-xl font-normal" style={{ color: colors.muted }}> / 100</span>
            </div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>
              Overall citation health · last scan: {scanAt}
            </div>
          </div>
        </div>
        <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Verified" value={health?.verified_count ?? 0} testid="stat-verified" />
          <StatCard label="Submitted" value={health?.submitted_count ?? 0} testid="stat-submitted" />
          <StatCard label="Needs update" value={health?.needs_update_count ?? 0} testid="stat-needs-update" />
          <StatCard label="Not started" value={health?.not_started_count ?? 0} testid="stat-not-started" />
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 text-xs flex-wrap" style={{ color: colors.muted }}>
        <span className="inline-flex items-center gap-1">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "#10b981" }} /> 80+ Excellent
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "#f59e0b" }} /> 50–79 Improving
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "#ef4444" }} /> Below 50 Needs work
        </span>
      </div>

      {/* Missing high-priority list */}
      <div className="rounded-2xl p-4"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="directories-missing-panel">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              <AlertCircle className="inline w-4 h-4 mr-1" /> Top priority missing
            </h2>
            <p className="text-xs" style={{ color: colors.muted }}>
              These directories are the fastest wins. Click to start a submission.
            </p>
          </div>
          <Link to="/marketing/directories/submissions"
                className="text-xs px-3 py-1.5 rounded-lg border"
                style={{ borderColor: colors.border }}
                data-testid="directories-open-submissions">
            Open Submissions →
          </Link>
        </div>
        {(!health?.top_priority_missing || health.top_priority_missing.length === 0) && (
          <div className="text-sm text-center py-6" style={{ color: colors.muted }}>
            You've covered every directory in the catalogue — nice.
          </div>
        )}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {(health?.top_priority_missing || []).map((d) => (
            <button key={d.slug}
                    onClick={() => claim(d.slug)}
                    disabled={busy}
                    className="text-left p-3 rounded-lg hover:brightness-95 transition"
                    style={{ backgroundColor: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}` }}
                    data-testid={`missing-${d.slug}`}>
              <div className="flex items-center justify-between">
                <div className="font-semibold text-sm">{d.name}</div>
                <Badge variant="outline" className="text-[10px]">P{d.priority}</Badge>
              </div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                {d.category?.replace(/_/g, " ")}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
