import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Play, Save, AlertTriangle } from "lucide-react";
import { api } from "@/api";
import { colors, money } from "@/theme";

function Card({ children, className = "", testId }) {
  return (
    <div
      className={`rounded-2xl ${className}`}
      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      data-testid={testId}
    >
      {children}
    </div>
  );
}

function Toast({ msg, onDone }) {
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(onDone, 3500);
    return () => clearTimeout(t);
  }, [msg, onDone]);
  if (!msg) return null;
  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg"
         style={{ backgroundColor: colors.onSurface, color: "#fff" }}
         data-testid="late-fee-toast">
      {msg}
    </div>
  );
}

export default function LateFeesSettings() {
  const nav = useNavigate();
  const [cfg, setCfg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [toast, setToast] = useState("");
  const [lastRun, setLastRun] = useState(null);

  useEffect(() => {
    api.get("/settings/late-fees")
      .then((r) => { setCfg(r); setLoading(false); })
      .catch((e) => { setToast(e.message); setLoading(false); });
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put("/settings/late-fees", {
        enabled: !!cfg.enabled,
        amount: Number(cfg.amount),
        grace_days: parseInt(cfg.grace_days, 10),
      });
      setCfg(r);
      setToast("Settings saved");
    } catch (e) { setToast(e.message); }
    finally { setSaving(false); }
  };

  const runNow = async () => {
    setRunning(true);
    try {
      const r = await api.post("/finances/late-fees/run", {});
      setLastRun(r);
      if (r.skipped === "disabled") {
        setToast("Late fees are disabled — 0 invoices assessed");
      } else {
        setToast(`Assessed ${r.assessed} invoice${r.assessed === 1 ? "" : "s"}`);
      }
    } catch (e) { setToast(e.message); }
    finally { setRunning(false); }
  };

  if (loading) return (
    <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>
  );

  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="late-fees-settings-page">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="back-btn">
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            Automatic Late Fees
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Daily job that assesses a one-time flat fee on invoices past their grace period.
          </p>
        </div>
      </div>

      <Card className="p-6 mb-4" testId="late-fees-form">
        <label className="flex items-center justify-between mb-5">
          <div>
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>Enable automatic assessment</div>
            <div className="text-xs mt-0.5" style={{ color: colors.muted }}>Runs daily at 02:00 UTC and can be triggered manually.</div>
          </div>
          <button onClick={() => setCfg({ ...cfg, enabled: !cfg.enabled })}
                  className="w-11 h-6 rounded-full relative transition"
                  style={{ backgroundColor: cfg.enabled ? colors.brand : colors.surfaceTertiary }}
                  data-testid="lf-enabled-toggle">
            <span className="absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow"
                  style={{ left: cfg.enabled ? 22 : 2 }} />
          </button>
        </label>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          <label>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Fee amount (USD)</div>
            <input type="number" min={0} step="0.01" value={cfg.amount}
                   onChange={(e) => setCfg({ ...cfg, amount: e.target.value })}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="lf-amount" />
          </label>
          <label>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Grace period (days past due)</div>
            <input type="number" min={0} step={1} value={cfg.grace_days}
                   onChange={(e) => setCfg({ ...cfg, grace_days: e.target.value })}
                   className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                   style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="lf-grace-days" />
          </label>
        </div>

        <div className="flex justify-between items-center pt-4"
             style={{ borderTop: `1px solid ${colors.border}` }}>
          <div className="text-xs" style={{ color: colors.muted }}>
            Current: {cfg.enabled ? "ON" : "OFF"} · {money(cfg.amount)} · {cfg.grace_days} day grace
          </div>
          <div className="flex gap-2">
            <button onClick={runNow} disabled={running}
                    className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                    style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="lf-run-now">
              <Play size={13} /> {running ? "Running…" : "Run now"}
            </button>
            <button onClick={save} disabled={saving}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                    style={{ backgroundColor: colors.brand, color: "#fff" }}
                    data-testid="lf-save">
              <Save size={13} /> {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </Card>

      {lastRun && (
        <Card className="p-4" testId="lf-last-run">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle size={14} style={{ color: colors.brand }} />
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>Last manual run</div>
          </div>
          <div className="text-sm" style={{ color: colors.onSurface }}>
            {lastRun.skipped === "disabled" ? (
              <span style={{ color: colors.muted }}>Skipped — feature disabled.</span>
            ) : (
              <>Assessed <b>{lastRun.assessed}</b> invoice{lastRun.assessed === 1 ? "" : "s"}.</>
            )}
          </div>
          {(lastRun.invoice_ids || []).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {lastRun.invoice_ids.map((iid) => (
                <a key={iid} href={`/invoices/${iid}`}
                   className="text-xs px-2 py-1 rounded-md hover:brightness-95"
                   style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}>
                  {iid.slice(0, 8)}…
                </a>
              ))}
            </div>
          )}
        </Card>
      )}

      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}
