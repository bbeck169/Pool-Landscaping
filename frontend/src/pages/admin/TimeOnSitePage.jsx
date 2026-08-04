/**
 * Phase G5b · Feb-2026 — Time-on-Site report page.
 *
 * Displays attribution counts strip + top jobs by total time-on-site
 * with a click-through drawer showing attributed stops for a job.
 */
import React from "react";
import { toast } from "sonner";
import { RefreshCw, Users, Clock, X, Play } from "lucide-react";
import { api } from "@/api";

function _fmtHMS(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${s}s`;
}

function _fmtTime(ts) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

function CountsStrip({ counts }) {
  const items = [
    { key: "pending",       label: "Pending",       tone: "text-zinc-700" },
    { key: "auto_linked",   label: "Auto linked",   tone: "text-emerald-700" },
    { key: "manual_linked", label: "Manual linked", tone: "text-sky-700" },
    { key: "no_match",      label: "No match",      tone: "text-amber-700" },
    { key: "unlinked",      label: "Unlinked",      tone: "text-zinc-500" },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3"
         data-testid="tos-counts-strip">
      {items.map((it) => (
        <div key={it.key}
             className="bg-white border border-zinc-200 rounded-lg p-3 shadow-sm"
             data-testid={`tos-count-${it.key}`}>
          <div className="text-xs text-zinc-500">{it.label}</div>
          <div className={`text-2xl font-semibold ${it.tone}`}>
            {counts?.[it.key] ?? 0}
          </div>
        </div>
      ))}
    </div>
  );
}

function JobDrawer({ jobId, onClose }) {
  const [detail, setDetail] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  React.useEffect(() => {
    if (!jobId) return;
    setLoading(true);
    api.get(`/admin/gps/attribution/job/${jobId}`)
      .then((r) => setDetail(r))
      .catch((e) => toast.error("Load failed", { description: e?.message }))
      .finally(() => setLoading(false));
  }, [jobId]);
  if (!jobId) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-end sm:items-center justify-center p-4"
         data-testid="tos-job-drawer" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-xl w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold" data-testid="tos-job-drawer-title">
            {detail?.job_name || "Job"}
          </h3>
          <button type="button" onClick={onClose} aria-label="Close"
            data-testid="tos-job-drawer-close"><X size={18} /></button>
        </div>
        {loading || !detail ? (
          <div className="text-sm text-zinc-500">Loading…</div>
        ) : (
          <>
            <div className="text-sm text-zinc-600 mb-2">
              {detail.customer_name || "—"}
              {detail.scheduled_date ? ` · ${detail.scheduled_date}` : ""}
            </div>
            <div className="flex items-center gap-4 text-sm mb-4">
              <div className="inline-flex items-center gap-1"
                   data-testid="tos-job-total-dur">
                <Clock size={14} /> {_fmtHMS(detail.total_stop_duration_s)} total
              </div>
              <div className="inline-flex items-center gap-1"
                   data-testid="tos-job-unique-techs">
                <Users size={14} /> {detail.unique_techs} tech
                {detail.unique_techs === 1 ? "" : "s"}
              </div>
            </div>
            {detail.attributed_stops.length === 0 ? (
              <div className="text-sm text-zinc-500"
                   data-testid="tos-job-nostops">No stops attributed.</div>
            ) : (
              <ul className="divide-y divide-zinc-100 border border-zinc-200 rounded"
                  data-testid="tos-job-stops">
                {detail.attributed_stops.map((s) => (
                  <li key={s.id} className="flex items-center gap-3 p-2 text-sm"
                      data-testid={`tos-job-stop-${s.id}`}>
                    <span className="font-mono text-xs text-zinc-500">
                      {(s.started_at || "").slice(11, 16)} –
                      {" "}{(s.ended_at || "").slice(11, 16)}
                    </span>
                    <span className="flex-1 truncate">{s.user_name || s.user_id}</span>
                    <span className="text-xs text-zinc-500">
                      {_fmtHMS(s.duration_s)}
                    </span>
                    {typeof s.attribution_distance_m === "number" ? (
                      <span className="text-xs text-zinc-400">
                        ±{Math.round(s.attribution_distance_m)} m
                      </span>
                    ) : (
                      <span className="text-xs text-zinc-400">manual</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function TimeOnSitePage() {
  const [summary, setSummary] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [range, setRange] = React.useState("week");
  const [running, setRunning] = React.useState(false);
  const [drawerJob, setDrawerJob] = React.useState(null);
  const [forbidden, setForbidden] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get(`/admin/gps/attribution/summary?range=${range}`);
      setSummary(r);
      setForbidden(false);
    } catch (e) {
      if ((e?.message || "").includes("403")) setForbidden(true);
      else toast.error("Load failed", { description: e?.message });
    } finally { setLoading(false); }
  }, [range]);

  React.useEffect(() => { load(); }, [load]);

  const runBatch = async () => {
    setRunning(true);
    try {
      const r = await api.post("/admin/gps/attribution/run-batch");
      toast.success(`Batch: ${r.auto_linked} linked, ${r.no_match} unmatched`);
      load();
    } catch (e) {
      toast.error("Batch failed", { description: e?.message });
    } finally { setRunning(false); }
  };

  if (forbidden) {
    return (
      <div className="p-6" data-testid="tos-forbidden">
        <h1 className="text-2xl font-semibold text-zinc-900">Access denied</h1>
        <p className="text-sm text-zinc-500 mt-2">
          You don't have permission to view time-on-site reports.
        </p>
      </div>
    );
  }

  const topJobs = summary?.top_jobs_by_time_on_site || [];

  return (
    <div className="p-6 space-y-4" data-testid="tos-page">
      <header className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="tos-title">Time on Site</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Techs' driver stops attributed to scheduled jobs by
            proximity. Manually override on the Driver Activity page.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select value={range} onChange={(e) => setRange(e.target.value)}
            className="px-3 py-1.5 border border-zinc-200 rounded text-sm"
            data-testid="tos-range-select">
            <option value="day">Day</option>
            <option value="week">Week</option>
            <option value="month">Month</option>
          </select>
          <button type="button" onClick={load}
            className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-200 rounded text-sm hover:bg-zinc-50"
            data-testid="tos-refresh">
            <RefreshCw size={14} /> Refresh
          </button>
          <button type="button" onClick={runBatch} disabled={running}
            className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm disabled:opacity-50"
            data-testid="tos-run-batch">
            <Play size={14} /> {running ? "Running…" : "Run batch"}
          </button>
        </div>
      </header>

      <CountsStrip counts={summary?.counts} />

      <div className="bg-white border border-zinc-200 rounded-lg shadow-sm overflow-hidden"
           data-testid="tos-top-jobs">
        <div className="px-4 py-2 text-sm font-medium text-zinc-800 border-b border-zinc-100">
          Top jobs by time on site — {range}
        </div>
        {loading ? (
          <div className="p-6 text-sm text-zinc-500">Loading…</div>
        ) : topJobs.length === 0 ? (
          <div className="p-6 text-sm text-zinc-500"
               data-testid="tos-empty">
            No attributed stops in this window.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-zinc-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2">Job</th>
                <th className="text-left px-4 py-2">Customer</th>
                <th className="text-left px-4 py-2">Scheduled</th>
                <th className="text-right px-4 py-2">Stops</th>
                <th className="text-right px-4 py-2">Total time</th>
                <th className="text-right px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {topJobs.map((j) => (
                <tr key={j.job_id} className="border-t border-zinc-100"
                    data-testid={`tos-top-job-row-${j.job_id}`}>
                  <td className="px-4 py-2 font-medium">
                    <button type="button"
                      onClick={() => setDrawerJob(j.job_id)}
                      className="text-left hover:underline"
                      data-testid={`tos-open-job-${j.job_id}`}>
                      {j.job_name}
                    </button>
                  </td>
                  <td className="px-4 py-2 text-zinc-700">
                    {j.customer_name || "—"}
                  </td>
                  <td className="px-4 py-2 text-zinc-500 text-xs">
                    {j.scheduled_date || "—"}
                  </td>
                  <td className="px-4 py-2 text-right text-zinc-700">
                    {j.stop_count}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-zinc-700">
                    {_fmtHMS(j.total_stop_duration_s)}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button type="button"
                      onClick={() => setDrawerJob(j.job_id)}
                      className="text-sky-600 hover:underline text-xs"
                      data-testid={`tos-details-${j.job_id}`}>
                      Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {drawerJob && (
        <JobDrawer jobId={drawerJob} onClose={() => setDrawerJob(null)} />
      )}
    </div>
  );
}
