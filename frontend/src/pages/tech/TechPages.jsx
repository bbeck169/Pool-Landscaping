/**
 * Phase 16C add-on · Tech-facing Huddle + Time Clock (web).
 * Minimal, tech-safe (no revenue), lets techs submit their yesterday/today/blockers
 * and see their own timesheet.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";
import { Send, CheckCircle2, LogIn, RefreshCw } from 'lucide-react';

const Card = ({ children, className = "", testId }) => (
  <div className={`rounded-2xl ${className}`}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);
const Section = ({ title, subtitle, right, children }) => (
  <div className="p-4 md:p-8 max-w-3xl mx-auto">
    <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
      <div>
        <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
        {subtitle && <p className="text-sm mt-1" style={{ color: colors.muted }}>{subtitle}</p>}
      </div>
      {right}
    </div>
    {children}
  </div>
);
const BtnPrimary = ({ children, testId, ...rest }) => (
  <button className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50 flex items-center gap-1"
          style={{ background: gradients.navyToGreen.css }} data-testid={testId} {...rest}>{children}</button>
);

/* ───── Tech Huddle Page ─────────────────────────────────── */
export function TechHuddlePage() {
  const today = new Date().toISOString().slice(0, 10);
  const [yesterday, setYesterday] = useState("");
  const [todayText, setTodayText] = useState("");
  const [blockers, setBlockers] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");

  const submit = async () => {
    setBusy(true);
    try {
      // find-or-create huddle for today
      const list = await api.get("/huddles").catch(() => []);
      let h = (list || []).find((x) => x.date === today);
      if (!h) h = await api.post("/huddles", { date: today, title: "Daily Huddle" });
      const lines = [
        ...yesterday.split("\n").map((s) => s.trim()).filter(Boolean).map((t) => `[Yesterday] ${t}`),
        ...todayText.split("\n").map((s) => s.trim()).filter(Boolean).map((t) => `[Today] ${t}`),
        ...blockers.split("\n").map((s) => s.trim()).filter(Boolean).map((t) => `[Blocker] ${t}`),
      ];
      for (const text of lines) {
        await api.post(`/huddles/${h.id}/action-items`,
                        { huddle_id: h.id, text });
      }
      setToast(`Posted ${lines.length} huddle note(s) for ${today}.`);
      setYesterday(""); setTodayText(""); setBlockers("");
      setTimeout(() => setToast(""), 3000);
    } catch (e) { alert(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Section title="Daily Huddle" subtitle={`${today} · your notes flow into the team's Business OS.`}>
      {toast && (
        <div className="mb-3 px-3 py-2 rounded-lg text-sm font-semibold"
             style={{ backgroundColor: "#DCFCE7", color: colors.success }}
             data-testid="tech-huddle-toast">
          <CheckCircle2 size={14} className="inline"/> {toast}
        </div>
      )}
      <div className="space-y-3">
        {[
          { key: "y", label: "What did you finish yesterday?", val: yesterday, set: setYesterday, tid: "huddle-yesterday" },
          { key: "t", label: "What are you doing today?",       val: todayText,  set: setTodayText,  tid: "huddle-today" },
          { key: "b", label: "Any blockers?",                    val: blockers,   set: setBlockers,   tid: "huddle-blockers" },
        ].map((f) => (
          <Card key={f.key} className="p-4">
            <label className="text-xs font-semibold uppercase tracking-wider mb-2 block"
                   style={{ color: colors.muted }}>{f.label}</label>
            <textarea rows={3} value={f.val} onChange={(e) => f.set(e.target.value)}
                      placeholder="One per line"
                      className="w-full px-3 py-2 rounded-lg text-sm"
                      style={{ border: `1px solid ${colors.border}` }}
                      data-testid={f.tid}/>
          </Card>
        ))}
      </div>
      <div className="flex justify-end mt-4">
        <BtnPrimary onClick={submit} disabled={busy} testId="tech-huddle-submit">
          <Send size={14}/> {busy ? "Posting…" : "Submit huddle"}
        </BtnPrimary>
      </div>
    </Section>
  );
}

/* ───── Tech Time Clock Page ────────────────────────────── */
export function TechTimeClockPage() {
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const load = async () => {
    setBusy(true);
    try { setRows(await api.get("/workforce/timesheets")); }
    finally { setBusy(false); }
  };
  useEffect(() => { load(); }, []);
  const openShift = rows.find((r) => !r.clock_out_at);

  return (
    <Section
      title="My Time Clock"
      subtitle="Your shifts, breaks, and mileage today. Clock in / out is on the mobile app."
      right={<button onClick={load}
                     className="px-3 py-2 rounded-xl text-sm font-semibold flex items-center gap-1"
                     style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                              border: `1px solid ${colors.border}` }}
                     data-testid="tech-tc-refresh">
              <RefreshCw size={14}/> Refresh
            </button>}
    >
      {openShift && (
        <Card className="p-4 mb-4" testId="tech-tc-open-shift">
          <div className="flex items-center gap-2">
            <LogIn size={16} style={{ color: colors.success }}/>
            <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
              Open shift · {openShift.job_title || openShift.job_id}
            </div>
          </div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            Clocked in at {new Date(openShift.clock_in_at).toLocaleTimeString()} — clock out on mobile.
          </div>
        </Card>
      )}
      <Card className="overflow-x-auto" testId="tech-tc-table">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
              <th className="text-left p-3 font-semibold">Date</th>
              <th className="text-left p-3 font-semibold">Job</th>
              <th className="text-right p-3 font-semibold">Hours</th>
              <th className="text-right p-3 font-semibold">Miles</th>
              <th className="text-left p-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${colors.border}` }}
                  data-testid={`tech-tc-row-${r.id}`}>
                <td className="p-3" style={{ color: colors.onSurface }}>{r.day}</td>
                <td className="p-3" style={{ color: colors.onSurfaceSecondary }}>
                  {r.job_title || r.job_id}
                </td>
                <td className="p-3 text-right font-semibold" style={{ color: colors.onSurface }}>{(r.hours || 0).toFixed(2)}</td>
                <td className="p-3 text-right" style={{ color: colors.onSurfaceSecondary }}>{(r.mileage_miles || 0).toFixed(2)}</td>
                <td className="p-3">
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wide"
                        style={{
                          backgroundColor: r.status === "approved" ? "#DCFCE7"
                                          : r.status === "rejected" ? "#FEE2E2"
                                          : colors.surfaceSecondary,
                          color: r.status === "approved" ? colors.success
                                : r.status === "rejected" ? colors.error
                                : colors.muted,
                        }}>
                    {r.status}
                  </span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && !busy && (
              <tr><td colSpan={5} className="p-6 text-center text-sm" style={{ color: colors.muted }}
                      data-testid="tech-tc-empty">
                No shifts yet.
              </td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </Section>
  );
}
