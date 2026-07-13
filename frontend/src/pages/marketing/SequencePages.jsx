import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Plus, Play, Pause, X, Users } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

function Card({ children, className = "", testId }) {
  return <div className={`rounded-2xl ${className}`}
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid={testId}>{children}</div>;
}

export function SequencesList() {
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/sequences").then((r) => setRows(r || [])); }, []);
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="sequences-list">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>Sequences</h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>Automated multi-step flows triggered by events.</p>
        </div>
        <Link to="/marketing/sequences/new"
              className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-lg"
              style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="new-seq-btn">
          <Plus size={14} /> New sequence
        </Link>
      </div>
      {rows.map((s) => (
        <Link key={s.id} to={`/marketing/sequences/${s.id}`}
              className="block rounded-2xl p-4 mb-2 hover:brightness-95"
              style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
              data-testid={`seq-row-${s.id}`}>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <div className="font-semibold" style={{ color: colors.onSurface }}>{s.name}</div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                trigger: <b>{s.trigger}</b> · {s.steps_count} steps · {s.enrolled_count} enrolled
              </div>
            </div>
            <span className="px-2 py-0.5 rounded-md text-xs font-bold"
                  style={{ backgroundColor: s.active ? "#DCFCE7" : colors.surfaceTertiary,
                           color: s.active ? "#16A34A" : colors.muted }}>
              {s.active ? "active" : "paused"}
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}

const TRIGGERS = ["customer_created", "job_completed", "invoice_created",
                  "invoice_overdue_30", "quote_sent", "quote_approved", "manual"];

export function SequenceNew() {
  const nav = useNavigate();
  const [form, setForm] = useState({
    name: "New Sequence", trigger: "customer_created",
    steps: [{ delay_days: 0, action_type: "email", template_slug: "welcome-email", notes: "" }],
    active: true,
  });
  const save = async () => {
    const s = await api.post("/sequences", form);
    nav(`/marketing/sequences/${s.id}`);
  };
  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="sequence-new">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav("/marketing/sequences")}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>New Sequence</h1>
      </div>
      <Card className="p-5 space-y-3">
        <label>
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Name</div>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                 className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="sn-name" />
        </label>
        <label>
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Trigger</div>
          <select value={form.trigger} onChange={(e) => setForm({ ...form, trigger: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="sn-trigger">
            {TRIGGERS.map((t) => <option key={t}>{t}</option>)}
          </select>
        </label>
        <div>
          <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>Steps</div>
          {form.steps.map((st, i) => (
            <div key={i} className="grid grid-cols-4 gap-2 mb-2" data-testid={`sn-step-${i}`}>
              <input type="number" value={st.delay_days}
                     onChange={(e) => setForm({ ...form, steps: form.steps.map((s, idx) =>
                       idx === i ? { ...s, delay_days: parseInt(e.target.value || 0, 10) } : s) })}
                     placeholder="Delay (days)"
                     className="px-3 py-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
              <select value={st.action_type}
                      onChange={(e) => setForm({ ...form, steps: form.steps.map((s, idx) =>
                        idx === i ? { ...s, action_type: e.target.value } : s) })}
                      className="px-3 py-2 rounded-lg text-sm"
                      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}>
                {["email", "sms", "task", "ai_reply"].map((a) => <option key={a}>{a}</option>)}
              </select>
              <input value={st.notes || ""} placeholder="Notes"
                     onChange={(e) => setForm({ ...form, steps: form.steps.map((s, idx) =>
                       idx === i ? { ...s, notes: e.target.value } : s) })}
                     className="px-3 py-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
              <button onClick={() => setForm({ ...form, steps: form.steps.filter((_, idx) => idx !== i) })}
                      className="px-3 py-2 rounded-lg text-sm" style={{ color: colors.error }}>
                <X size={14} />
              </button>
            </div>
          ))}
          <button onClick={() => setForm({ ...form, steps: [...form.steps, { delay_days: 3, action_type: "email", notes: "" }] })}
                  className="text-xs font-semibold" style={{ color: colors.brand }} data-testid="sn-add-step">
            + Add step
          </button>
        </div>
        <div className="flex justify-end">
          <button onClick={save} className="px-4 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="sn-save">Create</button>
        </div>
      </Card>
    </div>
  );
}

export function SequenceDetail() {
  const { id } = useParams();
  const [seq, setSeq] = useState(null);
  const [enr, setEnr] = useState([]);
  const [custId, setCustId] = useState("");
  const [customers, setCustomers] = useState([]);
  const [msg, setMsg] = useState("");
  const load = async () => {
    const s = await api.get(`/sequences/${id}`);
    setSeq(s);
    const e = await api.get(`/sequences/${id}/enrollments`);
    setEnr(e || []);
  };
  useEffect(() => { load(); api.get("/customers").then((r) => setCustomers(Array.isArray(r) ? r : [])); }, [id]);
  const enroll = async () => {
    if (!custId) return;
    await api.post(`/sequences/${id}/enroll?customer_id=${custId}`, {});
    setMsg("Enrolled"); load();
  };
  const pause = async () => { await api.post(`/sequences/${id}/${seq.active ? "pause" : "resume"}`, {}); load(); };
  if (!seq) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="sequence-detail">
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>{seq.name}</h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            trigger: <b>{seq.trigger}</b> · {(seq.steps || []).length} steps
          </p>
        </div>
        <button onClick={pause} className="px-3 py-2 rounded-lg text-sm font-semibold"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="seq-toggle">
          {seq.active ? <><Pause size={14} className="inline mr-1" /> Pause</> : <><Play size={14} className="inline mr-1" /> Resume</>}
        </button>
      </div>
      <Card className="p-4 mb-4">
        <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>Steps</div>
        {(seq.steps || []).map((s, i) => (
          <div key={i} className="py-2 flex items-center gap-3"
               style={{ borderTop: i ? `1px solid ${colors.border}` : "none" }}
               data-testid={`seq-step-${i}`}>
            <div className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
                 style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>{i + 1}</div>
            <div className="flex-1">
              <div className="text-sm" style={{ color: colors.onSurface }}>
                Day {s.delay_days} — <b>{s.action_type}</b>
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>{s.notes || s.template_slug || "—"}</div>
            </div>
          </div>
        ))}
      </Card>
      <Card className="p-4 mb-4">
        <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>Enroll a customer</div>
        <div className="flex gap-2">
          <select value={custId} onChange={(e) => setCustId(e.target.value)}
                  className="flex-1 px-3 py-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="seq-enroll-select">
            <option value="">Choose customer…</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button onClick={enroll} disabled={!custId}
                  className="px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="seq-enroll-btn">
            Enroll
          </button>
        </div>
        {msg ? <div className="text-xs mt-2" style={{ color: colors.success }}>{msg}</div> : null}
      </Card>
      <Card className="p-4">
        <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>Enrollments ({enr.length})</div>
        {enr.map((e) => {
          const cust = customers.find((c) => c.id === e.customer_id);
          return (
            <div key={e.id} className="py-2 text-sm flex items-center justify-between"
                 style={{ borderTop: `1px solid ${colors.border}` }} data-testid={`enr-${e.id}`}>
              <div>
                <div style={{ color: colors.onSurface }}>{cust?.name || e.customer_id.slice(0, 8)}</div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  step {e.current_step + 1} · next: {(e.next_action_at || "").slice(0, 16)}
                </div>
              </div>
              <span className="text-xs" style={{ color: colors.muted }}>{e.status}</span>
            </div>
          );
        })}
        {enr.length === 0 && <div className="text-xs py-4" style={{ color: colors.muted }}>No enrollments yet.</div>}
      </Card>
    </div>
  );
}
