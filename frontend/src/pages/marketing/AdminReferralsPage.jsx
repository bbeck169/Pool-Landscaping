/**
 * Phase 10 · Feb 2026 — Admin referrals dashboard (`/admin/referrals`).
 *
 * Summary card, filter tabs, row actions (void / re-eligible), manual
 * watcher-run trigger.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  RefreshCw, X as XIcon, Play, CheckCircle2, AlertCircle,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";

const STATUS_PILL = {
  pending_conversion: { label: "Pending signup", bg: "#F4F4F5", fg: "#52525B" },
  pending_paid_window: { label: "Waiting 30d", bg: "#FFEDD5", fg: "#9A3412" },
  crediting_in_progress: { label: "Crediting…", bg: "#DBEAFE", fg: "#1D4ED8" },
  credited: { label: "Credited", bg: "#DCFCE7", fg: "#166534" },
  voided: { label: "Voided", bg: "#F4F4F5", fg: "#71717A" },
};

const TABS = [
  { v: "", l: "All" },
  { v: "pending_paid_window", l: "Pending" },
  { v: "credited", l: "Credited" },
  { v: "voided", l: "Voided" },
];


function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return String(iso).slice(0, 10); }
}


export default function AdminReferralsPage() {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("");
  const [voidRow, setVoidRow] = useState(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, l] = await Promise.all([
        api.get("/referrals/summary"),
        api.get(`/admin/referrals${tab ? `?status=${tab}` : ""}`),
      ]);
      setSummary(s);
      setRows(l.referrals || l.items || l || []);
    } catch (e) {
      toast.error(e.message || "Failed to load referrals");
    } finally {
      setLoading(false);
    }
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  async function runWatcher() {
    setRunning(true);
    try {
      const res = await api.post("/admin/referral-watcher/run", {});
      toast.success(
        `Watcher: ${res.credited?.length || 0} credited, ` +
        `${res.voided?.length || 0} voided, ${res.still_waiting || 0} waiting`
      );
      load();
    } catch (e) {
      toast.error(e.message || "Watcher run failed");
    } finally {
      setRunning(false);
    }
  }

  async function reEligible(row) {
    if (!window.confirm(`Re-eligible referral for ${row.referrer_name || row.id.slice(0, 8)}?`))
      return;
    try {
      await api.post(`/referrals/${row.id}/re-eligible`, {});
      toast.success("Referral is eligible again");
      load();
    } catch (e) {
      toast.error(e.message || "Failed");
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50" data-testid="admin-referrals-page">
      <div className="bg-white border-b border-zinc-200">
        <div className="max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-zinc-900">Referrals</h1>
            <p className="text-sm text-zinc-500 mt-0.5">
              30-day paid-window credits, powered by the referral watcher.
            </p>
          </div>
          <button onClick={runWatcher}
                  disabled={running}
                  data-testid="admin-referrals-run-watcher"
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-50">
            <Play className="w-4 h-4" />
            {running ? "Running…" : "Run watcher now"}
          </button>
        </div>

        {/* Summary strip */}
        {summary && (
          <div className="max-w-7xl mx-auto px-6 pb-5 grid grid-cols-2 md:grid-cols-5 gap-3">
            <SummaryCard label="Pending signup" value={summary.counts_by_status?.pending_conversion || 0}/>
            <SummaryCard label="Waiting 30d" value={summary.counts_by_status?.pending_paid_window || 0} accent="#EA580C"/>
            <SummaryCard label="Credited" value={summary.counts_by_status?.credited || 0} accent="#16A34A"/>
            <SummaryCard label="Voided" value={summary.counts_by_status?.voided || 0}/>
            <SummaryCard label="Total credited"
                          value={summary.total_credited_formatted || "$0.00"}
                          accent="#16A34A" isText/>
          </div>
        )}

        <div className="max-w-7xl mx-auto px-6 pb-4 flex items-center gap-1">
          {TABS.map((t) => (
            <button key={t.v || "all"}
                    onClick={() => setTab(t.v)}
                    data-testid={`admin-referrals-tab-${t.v || "all"}`}
                    className={`px-3 py-1 text-sm rounded-md transition ${
                      tab === t.v ? "bg-zinc-900 text-white" : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200"
                    }`}>
              {t.l}
            </button>
          ))}
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="bg-white rounded-xl border border-zinc-200 overflow-hidden">
          <div className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-200 bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
            <div className="col-span-3">Referrer</div>
            <div className="col-span-3">Referred</div>
            <div className="col-span-2">First paid</div>
            <div className="col-span-2">Status</div>
            <div className="col-span-2 text-right">Actions</div>
          </div>
          {loading && (
            <div className="py-10 text-center text-sm text-zinc-500">Loading…</div>
          )}
          {!loading && rows.length === 0 && (
            <div className="py-10 text-center text-sm text-zinc-400"
                 data-testid="admin-referrals-empty">
              No referrals match this filter.
            </div>
          )}
          {!loading && rows.map((r) => {
            const pill = STATUS_PILL[r.status] || STATUS_PILL.pending_conversion;
            return (
              <div key={r.id}
                   data-testid={`admin-referrals-row-${r.id}`}
                   className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-100 items-center hover:bg-zinc-50/70">
                <div className="col-span-3 text-sm text-zinc-900 truncate">
                  {r.referrer_name || r.referrer_customer_id?.slice(0, 8)}
                </div>
                <div className="col-span-3 text-sm text-zinc-500 truncate">
                  {r.referred_name || r.friend_name ||
                    r.converted_to_customer_id?.slice(0, 8) || "—"}
                </div>
                <div className="col-span-2 text-sm text-zinc-500">
                  {fmtDate(r.first_paid_at)}
                </div>
                <div className="col-span-2">
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                        style={{ background: pill.bg, color: pill.fg }}
                        title={r.voided_reason || ""}>
                    {pill.label}
                  </span>
                </div>
                <div className="col-span-2 flex items-center justify-end gap-1">
                  {r.status === "pending_paid_window" && (
                    <button onClick={() => setVoidRow(r)}
                            data-testid={`admin-referrals-void-${r.id}`}
                            className="px-2 py-1 rounded text-xs text-red-700 border border-red-200 hover:bg-red-50">
                      Void
                    </button>
                  )}
                  {r.status === "voided" && (
                    <button onClick={() => reEligible(r)}
                            data-testid={`admin-referrals-re-eligible-${r.id}`}
                            className="px-2 py-1 rounded text-xs text-zinc-800 border border-zinc-200 hover:bg-zinc-50">
                      Re-eligible
                    </button>
                  )}
                  {r.status === "credited" && (
                    <span className="inline-flex items-center gap-0.5 text-xs text-green-700">
                      <CheckCircle2 className="w-3 h-3" />
                      ${(r.credit_amount_cents || 0) / 100}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {voidRow && (
        <VoidDialog row={voidRow}
                     onClose={() => setVoidRow(null)}
                     onDone={() => { setVoidRow(null); load(); }}/>
      )}
    </div>
  );
}


function SummaryCard({ label, value, accent, isText }) {
  return (
    <div className="rounded-lg bg-white border border-zinc-200 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={`${isText ? "text-lg" : "text-2xl"} font-semibold`}
           style={{ color: accent || "#111827" }}>
        {value}
      </div>
    </div>
  );
}


function VoidDialog({ row, onClose, onDone }) {
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    try {
      await api.post(`/referrals/${row.id}/void`, {
        reason: reason.trim() || "manual",
      });
      toast.success("Referral voided");
      onDone();
    } catch (e) {
      toast.error(e.message || "Void failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => (!o && onClose())}>
      <DialogContent className="max-w-md"
                     data-testid="admin-referrals-void-dialog">
        <DialogHeader><DialogTitle>Void referral</DialogTitle></DialogHeader>
        <p className="text-sm text-zinc-500 mb-3">
          Void a pending referral. This is a manual action — the customer
          will not receive their $55 credit.
        </p>
        <label className="block text-xs uppercase tracking-wide text-zinc-500 mb-1">
          Reason
        </label>
        <input value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="e.g. duplicate signup, chargeback risk"
                data-testid="admin-referrals-void-reason"
                className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm" />
        <div className="mt-4 flex items-center justify-end gap-2">
          <button onClick={onClose}
                  className="px-4 py-2 rounded-lg text-sm text-zinc-700 hover:bg-zinc-100">Cancel</button>
          <button onClick={submit}
                  disabled={saving}
                  data-testid="admin-referrals-void-submit"
                  className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm hover:bg-red-700 disabled:opacity-50">
            {saving ? "Voiding…" : "Void referral"}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
