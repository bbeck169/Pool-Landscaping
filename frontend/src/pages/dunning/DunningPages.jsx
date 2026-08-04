/**
 * Phase 22 · Dunning — 3 admin pages in one file (Settings, Queue,
 * Analytics). All admin-only; nav gate is enforced in App.js AdminOnly.
 */
import React, { useEffect, useState } from "react";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Save, RotateCcw, Send, Pause, Mail, MessageSquare, TrendingDown, Calendar } from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

/* ─── SETTINGS ──────────────────────────────────────────────────────── */
export default function DunningSettings() {
  const nav = useNavigate();
  const [s, setS] = useState(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const load = async () => setS(await api.get("/dunning/settings"));
  useEffect(() => { load(); }, []);

  if (!s) return <div className="p-6 text-sm"
                        style={{ color: colors.muted }}>Loading…</div>;

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/dunning/settings", {
        enabled: s.enabled, stages: s.stages,
        escalation: s.escalation,
        stripe_payment_link_enabled: s.stripe_payment_link_enabled,
      });
      setMsg("Saved."); setTimeout(() => setMsg(""), 2000);
    } catch (e) { setMsg(e.message || "Save failed"); }
    finally { setSaving(false); }
  };

  const reset = async () => {
    if (!(await mustConfirm({ title: "Reset cadence?", description: "Reset all cadence + escalation to defaults?", tone: "danger" }))) return;
    const r = await api.post("/dunning/settings/reset-defaults");
    setS(r);
    setMsg("Reset."); setTimeout(() => setMsg(""), 2000);
  };

  const updateStage = (idx, patch) => {
    const next = [...s.stages];
    next[idx] = { ...next[idx], ...patch };
    setS({ ...s, stages: next });
  };
  const toggleChannel = (idx, ch) => {
    const cur = s.stages[idx].channels || [];
    updateStage(idx, {
      channels: cur.includes(ch)
        ? cur.filter((c) => c !== ch)
        : [...cur, ch],
    });
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="dunning-settings">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Dunning · settings
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Automated invoice reminder cadence and escalation flags. Runs
            hourly.
          </p>
        </div>
        <button onClick={reset} disabled={saving}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="dun-reset">
          <RotateCcw size={14} /> Reset defaults
        </button>
        <button onClick={save} disabled={saving}
                className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-1"
                style={{ background: brandGradientCss, color: "#fff" }}
                data-testid="dun-save">
          <Save size={14} /> {saving ? "Saving…" : "Save changes"}
        </button>
      </div>

      {msg && (
        <div className="mb-4 p-3 rounded-xl text-sm"
             style={{ backgroundColor: "#DCFCE7", color: "#166534" }}
             data-testid="dun-msg">{msg}</div>
      )}

      <div className="rounded-2xl p-4 mb-4"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <label className="flex items-center gap-3">
          <input type="checkbox" checked={s.enabled}
            onChange={(e) => setS({ ...s, enabled: e.target.checked })}
            data-testid="dun-enabled" />
          <div>
            <div className="font-bold" style={{ color: colors.onSurface }}>
              Automated dunning enabled
            </div>
            <div className="text-xs" style={{ color: colors.muted }}>
              When off, the hourly scanner skips this tenant entirely.
            </div>
          </div>
        </label>
      </div>

      <div className="rounded-2xl p-4 mb-4 grid grid-cols-2 gap-3"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <label>
          <div className="text-xs font-bold mb-1"
               style={{ color: colors.muted }}>
            "At risk" threshold (days past due)
          </div>
          <input type="number" value={s.escalation.at_risk_days}
            onChange={(e) => setS({ ...s,
              escalation: { ...s.escalation,
                             at_risk_days: parseInt(e.target.value) || 0 }})}
            className="w-full p-2 rounded-lg text-sm"
            style={{ backgroundColor: colors.background,
                      border: `1px solid ${colors.border}` }}
            data-testid="dun-at-risk" />
        </label>
        <label>
          <div className="text-xs font-bold mb-1"
               style={{ color: colors.muted }}>
            "In collections" threshold (days past due)
          </div>
          <input type="number" value={s.escalation.in_collections_days}
            onChange={(e) => setS({ ...s,
              escalation: { ...s.escalation,
                             in_collections_days: parseInt(e.target.value) || 0 }})}
            className="w-full p-2 rounded-lg text-sm"
            style={{ backgroundColor: colors.background,
                      border: `1px solid ${colors.border}` }}
            data-testid="dun-in-collections" />
        </label>
      </div>

      <h2 className="text-lg font-bold mb-2"
          style={{ color: colors.onSurface }}>
        Stages
      </h2>
      {s.stages.map((stage, i) => (
        <div key={stage.id}
             className="rounded-2xl p-4 mb-3"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
             data-testid={`dun-stage-${stage.id}`}>
          <div className="flex items-center gap-3 mb-2">
            <div className="flex-1">
              <input value={stage.name}
                onChange={(e) => updateStage(i, { name: e.target.value })}
                className="w-full p-1 text-lg font-bold bg-transparent"
                style={{ color: colors.onSurface, outline: "none" }} />
              <div className="text-[10px] font-mono"
                   style={{ color: colors.muted }}>{stage.id}</div>
            </div>
            <label className="text-xs" style={{ color: colors.muted }}>
              Offset days
              <input type="number" value={stage.offset_days}
                onChange={(e) => updateStage(i,
                  { offset_days: parseInt(e.target.value) || 0 })}
                className="ml-2 w-20 p-1 rounded text-sm"
                style={{ backgroundColor: colors.background,
                          border: `1px solid ${colors.border}` }} />
            </label>
            <div className="flex gap-1">
              {[["email", Mail], ["sms", MessageSquare]].map(([ch, Icon]) => {
                const on = stage.channels?.includes(ch);
                return (
                  <button key={ch}
                          onClick={() => toggleChannel(i, ch)}
                          className="px-2 py-1 text-xs font-bold rounded-lg flex items-center gap-1"
                          style={{
                            backgroundColor: on
                              ? colors.brandTertiary : colors.background,
                            color: on ? colors.brand : colors.muted,
                            border: `1px solid ${on ? colors.brand : colors.border}`,
                          }}
                          data-testid={`dun-stage-${stage.id}-${ch}`}>
                    <Icon size={10} />{ch}
                  </button>
                );
              })}
            </div>
          </div>
          <label className="block mb-2">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Subject template</div>
            <input value={stage.subject_template}
              onChange={(e) => updateStage(i,
                { subject_template: e.target.value })}
              className="w-full p-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }} />
          </label>
          <label className="block mb-2">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>Email body template</div>
            <textarea rows={4} value={stage.body_template}
              onChange={(e) => updateStage(i,
                { body_template: e.target.value })}
              className="w-full p-2 rounded-lg text-sm font-mono"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }} />
          </label>
          <label className="block">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>SMS template</div>
            <textarea rows={2} value={stage.sms_template || ""}
              onChange={(e) => updateStage(i,
                { sms_template: e.target.value })}
              className="w-full p-2 rounded-lg text-sm font-mono"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }} />
          </label>
        </div>
      ))}

      <div className="text-xs mt-4" style={{ color: colors.muted }}>
        Available variables: {"{customer_name}"}, {"{invoice_number}"},{" "}
        {"{invoice_total}"}, {"{due_date}"}, {"{days_past_due}"},{" "}
        {"{payment_link}"}, {"{tenant_name}"}, {"{tenant_phone}"}
      </div>
    </div>
  );
}

/* ─── QUEUE ─────────────────────────────────────────────────────────── */
export function DunningQueue() {
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(7);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get(`/dunning/queue?days=${days}`);
      setItems(r.items || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [days]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps

  const sendNow = async (item) => {
    await api.post(`/dunning/invoices/${item.invoice_id}/send-reminder`,
                   { stage_id: item.stage_id });
    await load();
  };
  const pause = async (item) => {
    await api.post(`/dunning/pause/${item.invoice_id}`);
    await load();
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="dunning-queue">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <Calendar size={22} style={{ color: colors.brand }} />
            Dunning queue
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Reminders scheduled to fire in the next {days} days.
          </p>
        </div>
        <select value={days} onChange={(e) => setDays(parseInt(e.target.value))}
          className="px-3 py-2 text-sm rounded-xl"
          style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
          data-testid="dun-queue-days">
          {[3, 7, 14, 30].map((d) => (
            <option key={d} value={d}>Next {d} days</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm"
             style={{ color: colors.muted }}>Loading…</div>
      ) : items.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No reminders scheduled in this window.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          <table className="w-full text-sm">
            <thead style={{ backgroundColor: "#F1F5F9" }}>
              <tr>
                <th className="p-2 text-left">Fire date</th>
                <th className="p-2 text-left">Stage</th>
                <th className="p-2 text-left">Invoice</th>
                <th className="p-2 text-right">Amount</th>
                <th className="p-2 text-left">Channels</th>
                <th className="p-2"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`dun-queue-row-${it.invoice_id}-${it.stage_id}`}>
                  <td className="p-2 text-xs"
                      style={{ color: colors.onSurface }}>{it.fire_date}</td>
                  <td className="p-2 text-xs">
                    <div style={{ color: colors.onSurface }}>{it.stage_name}</div>
                    <div className="font-mono text-[10px]"
                         style={{ color: colors.muted }}>{it.stage_id}</div>
                  </td>
                  <td className="p-2 text-xs">
                    <div style={{ color: colors.onSurface }}>
                      {it.invoice_title || it.invoice_id.slice(0, 8)}
                    </div>
                    <div className="text-[10px]"
                         style={{ color: colors.muted }}>
                      {it.customer_name} · due {it.due_date}
                    </div>
                  </td>
                  <td className="p-2 text-right font-bold"
                      style={{ color: colors.onSurface }}>
                    ${it.amount.toFixed(2)}
                  </td>
                  <td className="p-2 text-xs">
                    {it.channels.map((c) => (
                      <span key={c}
                            className="mr-1 text-[10px] px-2 py-0.5 rounded-full font-bold"
                            style={{ backgroundColor: colors.brandTertiary,
                                      color: colors.brand }}>{c}</span>
                    ))}
                  </td>
                  <td className="p-2 flex gap-1">
                    <button onClick={() => sendNow(it)}
                            className="px-2 py-1 text-xs font-bold rounded flex items-center gap-1"
                            style={{ backgroundColor: colors.brand,
                                      color: "#fff" }}
                            data-testid={`dun-send-${it.invoice_id}`}>
                      <Send size={10} /> Send now
                    </button>
                    <button onClick={() => pause(it)}
                            className="px-2 py-1 text-xs font-bold rounded flex items-center gap-1"
                            style={{ backgroundColor: colors.background,
                                      color: colors.onSurface,
                                      border: `1px solid ${colors.border}` }}
                            data-testid={`dun-pause-${it.invoice_id}`}>
                      <Pause size={10} /> Pause
                    </button>
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

/* ─── ANALYTICS ─────────────────────────────────────────────────────── */
export function DunningAnalytics() {
  const nav = useNavigate();
  const [a, setA] = useState(null);

  useEffect(() => {
    api.get("/dunning/analytics/ar-aging").then(setA);
  }, []);

  if (!a) return <div className="p-6 text-sm"
                        style={{ color: colors.muted }}>Loading…</div>;

  const buckets = [
    ["Current", a.current, "#059669"],
    ["1-30 days", a.aging_30, "#F59E0B"],
    ["31-60 days", a.aging_60, "#EA580C"],
    ["61-90+ days", a.aging_90, "#DC2626"],
  ];
  const max = Math.max(...buckets.map((b) => b[1]), 1);

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6"
         data-testid="dunning-analytics">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/admin")} className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <TrendingDown size={22} style={{ color: colors.brand }} />
            AR aging
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Outstanding invoice balances by age bucket. Updated live.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        {[
          ["Total outstanding", `$${a.aging_total.toFixed(0)}`, colors.brand],
          ["DSO (days)", a.dso_days, colors.onSurface],
          ["Collection rate (30d)", `${a.collection_rate_30d}%`, "#059669"],
          ["At risk / collections",
             `${a.at_risk_count} / ${a.in_collections_count}`, "#DC2626"],
        ].map(([l, v, c], i) => (
          <div key={i} className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid={`dun-kpi-${i}`}>
            <div className="text-[10px] font-bold uppercase tracking-wider"
                 style={{ color: colors.muted }}>{l}</div>
            <div className="text-2xl font-bold mt-1"
                 style={{ color: c }}>{v}</div>
          </div>
        ))}
      </div>

      <div className="rounded-2xl p-5"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        <h2 className="text-lg font-bold mb-4"
            style={{ color: colors.onSurface }}>
          Aging buckets
        </h2>
        <div className="space-y-3">
          {buckets.map(([l, v, c]) => (
            <div key={l}>
              <div className="flex justify-between text-sm mb-1">
                <span style={{ color: colors.onSurface }}>{l}</span>
                <span className="font-bold"
                      style={{ color: colors.onSurface }}>
                  ${v.toFixed(2)}
                </span>
              </div>
              <div className="h-6 rounded-lg overflow-hidden"
                   style={{ backgroundColor: "#F1F5F9" }}>
                <div style={{ width: `${(v / max) * 100}%`,
                                height: "100%", backgroundColor: c,
                                transition: "width 0.4s" }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
