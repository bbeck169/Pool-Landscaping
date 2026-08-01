/**
 * Phase 14b · Feb-2026 — Past bulk-charge runs list + detail.
 *
 * Routes:
 *   /admin/finance/bulk-charge-runs            — list (newest first)
 *   /admin/finance/bulk-charge-runs/:runId     — detail (per-row results)
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

import { Button } from "../../components/ui/button";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function _dollars(c) {
  return `$${((c || 0) / 100).toFixed(2)}`;
}

function _authHeader() {
  const t = typeof window !== "undefined" ? window.localStorage.getItem("token") : "";
  return { Authorization: `Bearer ${t}` };
}

export function BulkChargeRunsList() {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/invoices/bulk-charge-runs?limit=100`, {
        headers: _authHeader(),
      });
      const j = await r.json().catch(() => ({}));
      setRuns(j.runs || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div
      className="mx-auto max-w-6xl p-6"
      data-testid="bulk-charge-runs-page"
    >
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Bulk charge runs</h1>
          <p className="text-sm text-slate-500">
            History of every bulk charge-card-on-file batch initiated from the
            Invoices page. Dry-runs are logged alongside real charges.
          </p>
        </div>
        <Button variant="ghost" onClick={() => navigate("/invoices")} data-testid="bulk-runs-back">
          <ArrowLeft size={14} /> Back to invoices
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : runs.length === 0 ? (
        <p className="text-sm text-slate-500" data-testid="bulk-runs-empty">
          No bulk charge runs yet.
        </p>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-600">
              <tr>
                <th className="px-3 py-2 text-left font-semibold">Started</th>
                <th className="px-3 py-2 text-left font-semibold">Kind</th>
                <th className="px-3 py-2 text-right font-semibold">Selected</th>
                <th className="px-3 py-2 text-right font-semibold">Charged</th>
                <th className="px-3 py-2 text-right font-semibold">Skipped</th>
                <th className="px-3 py-2 text-right font-semibold">Failed</th>
                <th className="px-3 py-2 text-right font-semibold">Amount</th>
                <th className="px-3 py-2 text-right font-semibold"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {runs.map((run) => (
                <tr key={run.run_id} data-testid={`bulk-run-row-${run.run_id}`}>
                  <td className="px-3 py-2 text-slate-700">
                    {new Date(run.started_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    {run.dry_run ? (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-700">
                        Dry run
                      </span>
                    ) : (
                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-emerald-800">
                        Real
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-700">
                    {run.invoice_count}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-700">
                    {run.summary?.charged ?? 0}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-700">
                    {run.summary?.skipped ?? 0}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-700">
                    {run.summary?.failed ?? 0}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-700">
                    {_dollars(run.summary?.total_amount_charged_cents || 0)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <a
                      href={`/admin/finance/bulk-charge-runs/${run.run_id}`}
                      className="text-xs font-semibold text-blue-700 underline"
                      data-testid={`bulk-run-open-${run.run_id}`}
                    >
                      Open
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function BulkChargeRunDetail() {
  const { runId } = useParams();
  const [run, setRun] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/invoices/bulk-charge-runs/${runId}`, {
        headers: _authHeader(),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) setErr(j.detail || `HTTP ${r.status}`);
      else setRun(j);
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl p-6" data-testid="bulk-charge-run-detail-page">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">
            Bulk charge run {runId?.slice(0, 8)}…
          </h1>
        </div>
        <Button
          variant="ghost"
          onClick={() => navigate("/admin/finance/bulk-charge-runs")}
          data-testid="bulk-run-detail-back"
        >
          <ArrowLeft size={14} /> Back
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : err ? (
        <p className="text-sm text-red-700" data-testid="bulk-run-detail-error">
          {err}
        </p>
      ) : run ? (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <_Kpi label="Kind" value={run.dry_run ? "Dry run" : "Real"} />
            <_Kpi label="Selected" value={run.invoice_count} />
            <_Kpi label="Charged" value={run.summary?.charged ?? 0} />
            <_Kpi
              label="Total charged"
              value={_dollars(run.summary?.total_amount_charged_cents)}
            />
          </div>
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-slate-600">
                <tr>
                  <th className="px-3 py-2 text-left font-semibold">Invoice</th>
                  <th className="px-3 py-2 text-left font-semibold">Status</th>
                  <th className="px-3 py-2 text-left font-semibold">Charge / error</th>
                  <th className="px-3 py-2 text-right font-semibold">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(run.results || []).map((r) => (
                  <tr key={r.invoice_id}>
                    <td className="px-3 py-2 font-mono text-[11px] text-slate-700">
                      {r.invoice_id}
                    </td>
                    <td className="px-3 py-2 text-slate-700">{r.status}{r.skip_reason ? ` · ${r.skip_reason}` : ""}</td>
                    <td className="px-3 py-2 text-slate-700">
                      {r.charge_id ? (
                        <code className="text-[11px]">{r.charge_id}</code>
                      ) : r.error_code ? (
                        <span className="text-red-700">
                          {r.error_code}
                          {r.error_message ? `: ${r.error_message.slice(0, 80)}` : ""}
                        </span>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-3 py-2 text-right text-slate-700">
                      {r.amount_charged_cents
                        ? _dollars(r.amount_charged_cents)
                        : r.amount_cents
                        ? _dollars(r.amount_cents)
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}

function _Kpi({ label, value }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="text-[10px] font-semibold uppercase text-slate-500">
        {label}
      </div>
      <div className="mt-0.5 text-lg font-bold text-slate-900">{value}</div>
    </div>
  );
}
