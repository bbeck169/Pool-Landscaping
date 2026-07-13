import React, { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Plus, Send, Bell, CheckSquare, Bot, Phone, Shield, Users } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function Card({ children, className = "", testId }) {
  return <div className={`rounded-2xl ${className}`}
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid={testId}>{children}</div>;
}
function H({ title, subtitle, right }) {
  const nav = useNavigate();
  return (
    <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
      <div className="flex items-center gap-3">
        <button onClick={() => nav(-1)} className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
          {subtitle ? <p className="text-xs mt-0.5" style={{ color: colors.muted }}>{subtitle}</p> : null}
        </div>
      </div>
      {right}
    </div>
  );
}

// ─── AI Employees ──────────────────────────────────────────────────────────
export function AiEmployeesList() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/ai-ops/employees").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="ai-employees-list">
      <H title="AI Employees" subtitle="Persistent AI personas with role-specific prompts + guardrails" />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {rows.map((e) => (
          <Link key={e.id} to={`/ai-employees/${e.id}`}
                className="rounded-2xl p-4 hover:brightness-95 flex items-start gap-3"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`ai-emp-${e.slug}`}>
            <div className="text-3xl">{e.avatar || "🤖"}</div>
            <div>
              <div className="font-semibold" style={{ color: colors.onSurface }}>{e.name}</div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>{e.role}</div>
              <div className="text-xs mt-1" style={{ color: colors.muted }}>
                {e.enabled ? "✓ active" : "○ disabled"} · {e.memory_scope}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function AiEmployeeDetail() {
  const { id } = useParams();
  const [emp, setEmp] = useState(null);
  const [thread, setThread] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  useEffect(() => { api.get(`/ai-ops/employees/${id}`).then(setEmp); }, [id]);
  const send = async () => {
    if (!input.trim()) return;
    const userMsg = { role: "user", content: input };
    setMsgs([...msgs, userMsg]);
    const r = await api.post(`/ai-ops/employees/${id}/chat`, { message: input, thread_id: thread });
    setThread(r.thread_id);
    setMsgs([...msgs, userMsg, { role: "assistant", content: r.response }]);
    setInput("");
  };
  if (!emp) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="ai-employee-detail">
      <H title={`${emp.avatar} ${emp.name}`} subtitle={`${emp.role} · ${emp.memory_scope}`} />
      <Card className="p-4 mb-4">
        <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>System prompt</div>
        <div className="text-sm" style={{ color: colors.onSurface }}>{emp.system_prompt}</div>
        {(emp.guardrails || []).length > 0 && (
          <>
            <div className="text-xs font-semibold mt-3 mb-1" style={{ color: colors.muted }}>Guardrails</div>
            <ul className="list-disc pl-5 text-sm" style={{ color: colors.onSurface }}>
              {emp.guardrails.map((g, i) => <li key={i}>{g}</li>)}
            </ul>
          </>
        )}
      </Card>
      <Card className="p-4" testId="ai-chat">
        <div className="text-sm font-semibold mb-3" style={{ color: colors.onSurface }}>Test drive</div>
        <div className="space-y-2 mb-3 max-h-72 overflow-y-auto">
          {msgs.map((m, i) => (
            <div key={i} className="text-sm" style={{ color: m.role === "user" ? colors.brand : colors.onSurface }}>
              <b>{m.role === "user" ? "You" : emp.name}:</b> {m.content}
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <input value={input} onChange={(e) => setInput(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && send()}
                 className="flex-1 px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="ai-chat-input" />
          <button onClick={send} className="px-3 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="ai-chat-send">
            <Send size={14} />
          </button>
        </div>
      </Card>
    </div>
  );
}

// ─── Tasks ─────────────────────────────────────────────────────────────────
export function TasksPage() {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: "", priority: "med" });
  const load = () => api.get(`/tasks${status ? `?status=${status}` : ""}`).then((r) => setRows(r || []));
  useEffect(() => { load(); }, [status]); // eslint-disable-line
  const create = async () => {
    if (!form.title.trim()) return;
    await api.post("/tasks", form); setForm({ title: "", priority: "med" }); setCreating(false); load();
  };
  const complete = async (t) => { await api.post(`/tasks/${t.id}/complete`, {}); load(); };
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="tasks-page">
      <H title="Tasks" subtitle="Manual + system-created (sequence escalations)"
         right={<button onClick={() => setCreating(true)} className="px-3 py-2 rounded-lg text-sm font-semibold"
                        style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="task-new">
                  <Plus size={14} className="inline mr-1" /> New task
                </button>} />
      <div className="flex gap-2 mb-4">
        {["", "open", "in_progress", "done"].map((s) => (
          <button key={s || "all"} onClick={() => setStatus(s)}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold"
                  style={{ backgroundColor: status === s ? colors.brand : colors.surfaceSecondary,
                           color: status === s ? "#fff" : colors.onSurface,
                           border: `1px solid ${status === s ? colors.brand : colors.border}` }}
                  data-testid={`task-filter-${s || "all"}`}>
            {s || "all"}
          </button>
        ))}
      </div>
      {creating && (
        <Card className="p-4 mb-3">
          <input placeholder="Task title" value={form.title}
                 onChange={(e) => setForm({ ...form, title: e.target.value })}
                 className="w-full px-3 py-2 rounded-lg text-sm mb-2"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="task-title-input" />
          <div className="flex gap-2">
            <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}
                    className="px-3 py-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}>
              {["low", "med", "high", "urgent"].map((p) => <option key={p}>{p}</option>)}
            </select>
            <button onClick={create} className="px-3 py-2 rounded-lg text-sm font-semibold"
                    style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="task-create-btn">Create</button>
          </div>
        </Card>
      )}
      {rows.map((t) => (
        <Card key={t.id} className="p-3 mb-2 flex items-center gap-3" testId={`task-row-${t.id}`}>
          <input type="checkbox" checked={t.status === "done"}
                 onChange={() => t.status !== "done" && complete(t)}
                 data-testid={`task-complete-${t.id}`} />
          <div className="flex-1">
            <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{t.title}</div>
            <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
              {t.priority} · {t.source} · {t.status}
            </div>
            {t.description ? <div className="text-xs mt-1" style={{ color: colors.muted }}>{t.description}</div> : null}
          </div>
        </Card>
      ))}
      {rows.length === 0 && <Card className="p-8 text-center text-sm" testId="tasks-empty">
        <div style={{ color: colors.muted }}>No tasks match.</div>
      </Card>}
    </div>
  );
}

// ─── Notifications ─────────────────────────────────────────────────────────
export function NotificationsPage() {
  const [rows, setRows] = useState([]);
  const load = () => api.get("/notifications").then((r) => setRows(r || []));
  useEffect(() => { load(); }, []);
  const readAll = async () => { await api.post("/notifications/read-all", {}); load(); };
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="notifications-page">
      <H title="Notifications"
         right={<button onClick={readAll} className="px-3 py-2 rounded-lg text-sm font-semibold"
                        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                        data-testid="mark-all-read">Mark all read</button>} />
      {rows.map((n) => (
        <Card key={n.id} className="p-3 mb-2" testId={`notif-${n.id}`}>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full"
                 style={{ backgroundColor: n.read ? colors.surfaceTertiary : colors.brand }} />
            <div className="flex-1">
              <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{n.title}</div>
              <div className="text-xs" style={{ color: colors.muted }}>{n.body}</div>
            </div>
          </div>
        </Card>
      ))}
      {rows.length === 0 && <Card className="p-8 text-center text-sm">
        <div style={{ color: colors.muted }}>No notifications.</div>
      </Card>}
    </div>
  );
}

// ─── Access Settings ───────────────────────────────────────────────────────
const GROUPS = ["Customers", "Jobs", "Invoices", "Payments", "Reports", "Marketing", "SEO", "GBP", "D2D", "Settings"];
const ROLES = ["admin", "technician", "customer", "marketer", "sales"];
export function AccessSettings() {
  const [matrix, setMatrix] = useState({});
  const [toast, setToast] = useState("");
  useEffect(() => { api.get("/permissions").then(setMatrix); }, []);
  const set = (role, group, val) => setMatrix({ ...matrix, [role]: { ...(matrix[role] || {}), [group]: val } });
  const save = async () => { await api.put("/permissions", matrix); setToast("Saved"); setTimeout(() => setToast(""), 2000); };
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="access-settings-page">
      <H title="Access Settings" subtitle="Role × feature-group permissions matrix"
         right={<button onClick={save} className="px-3 py-2 rounded-lg text-sm font-semibold"
                        style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="perm-save">Save</button>} />
      <Card className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              <th className="text-left px-3 py-2 text-xs font-semibold" style={{ color: colors.muted }}>Group</th>
              {ROLES.map((r) => (
                <th key={r} className="text-left px-3 py-2 text-xs font-semibold uppercase" style={{ color: colors.muted }}>{r}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {GROUPS.map((g) => (
              <tr key={g} style={{ borderTop: `1px solid ${colors.border}` }}>
                <td className="px-3 py-2 font-semibold text-sm" style={{ color: colors.onSurface }}>{g}</td>
                {ROLES.map((r) => (
                  <td key={r} className="px-3 py-2">
                    <select value={(matrix[r] || {})[g] || "none"}
                            onChange={(e) => set(r, g, e.target.value)}
                            className="px-2 py-1 rounded-lg text-xs"
                            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                            data-testid={`perm-${r}-${g}`}>
                      {["none", "read", "write"].map((v) => <option key={v}>{v}</option>)}
                    </select>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {toast && <div className="fixed bottom-6 left-1/2 -translate-x-1/2 px-4 py-2 rounded-xl text-sm font-semibold"
                     style={{ backgroundColor: colors.onSurface, color: "#fff" }} data-testid="perm-toast">{toast}</div>}
    </div>
  );
}

export function AccessHistory() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/audit-logs").then((r) => setRows(Array.isArray(r) ? r : [])).catch(() => setRows([])); }, []);
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="access-history-page">
      <H title="Access History" subtitle="Login + impersonation + permission changes" />
      <Card className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              {["When", "User", "Event", "Details"].map((h) => (
                <th key={h} className="text-left px-3 py-2 text-xs font-semibold uppercase" style={{ color: colors.muted }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 100).map((r, i) => (
              <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}>
                <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>{(r.created_at || r.timestamp || "").slice(0, 19)}</td>
                <td className="px-3 py-2" style={{ color: colors.onSurface }}>{r.user_email || r.user_id || "—"}</td>
                <td className="px-3 py-2 text-xs" style={{ color: colors.onSurface }}>{r.type || r.event || r.action}</td>
                <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>{r.message || JSON.stringify(r.meta || {}).slice(0, 60)}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={4} className="px-3 py-8 text-center text-sm" style={{ color: colors.muted }}>No audit entries.</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

// ─── RingCentral + Call Logs ───────────────────────────────────────────────
export function RingCentralSettings() {
  const [form, setForm] = useState({ webhook_url: "", api_key: "", account_id: "" });
  const [toast, setToast] = useState("");
  useEffect(() => { api.get("/settings/ringcentral").then((r) => setForm({ ...form, ...r })); }, []); // eslint-disable-line
  const save = async () => { await api.put("/settings/ringcentral", form); setToast("Saved"); setTimeout(() => setToast(""), 2000); };
  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="ringcentral-page">
      <H title="RingCentral" subtitle="Inbound call tracking + auto-lead capture" />
      <Card className="p-5 space-y-2">
        <input value={form.webhook_url || ""} onChange={(e) => setForm({ ...form, webhook_url: e.target.value })}
               placeholder="Webhook URL" className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
               data-testid="rc-url" />
        <input value={form.account_id || ""} onChange={(e) => setForm({ ...form, account_id: e.target.value })}
               placeholder="Account ID" className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
               data-testid="rc-acct" />
        <input type="password" value={form.api_key || ""} onChange={(e) => setForm({ ...form, api_key: e.target.value })}
               placeholder="API key" className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
               data-testid="rc-key" />
        <div className="flex justify-end gap-2">
          <button onClick={save} className="px-3 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="rc-save">Save</button>
        </div>
        {!form.configured && <div className="text-xs" style={{ color: colors.muted }}>
          Not configured yet — webhook still accepts payloads and creates call_logs.
        </div>}
      </Card>
      {toast && <div className="fixed bottom-6 left-1/2 -translate-x-1/2 px-4 py-2 rounded-xl text-sm font-semibold"
                     style={{ backgroundColor: colors.onSurface, color: "#fff" }}>{toast}</div>}
    </div>
  );
}

export function CallLogsPage() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/call-logs").then((r) => setRows(r || [])); }, []);
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="call-logs-page">
      <H title="Call Logs" subtitle="Inbound calls via RingCentral webhook" />
      <Card className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ backgroundColor: colors.surfaceSecondary }}>
              {["When", "From", "Customer", "Duration", "Recording"].map((h) => (
                <th key={h} className="text-left px-3 py-2 text-xs font-semibold uppercase" style={{ color: colors.muted }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderTop: `1px solid ${colors.border}` }}>
                <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>{(r.created_at || "").slice(0, 19)}</td>
                <td className="px-3 py-2" style={{ color: colors.onSurface }}>{r.from_number}</td>
                <td className="px-3 py-2" style={{ color: colors.onSurface }}>{r.customer_name || "—"}</td>
                <td className="px-3 py-2" style={{ color: colors.muted }}>{r.duration}s</td>
                <td className="px-3 py-2 text-xs">
                  {r.recording_url ? <a href={r.recording_url} className="hover:underline" style={{ color: colors.brand }}>listen</a> : "—"}
                </td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-8 text-center text-sm" style={{ color: colors.muted }}>No calls yet.</td></tr>}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
