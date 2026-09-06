/**
 * Phase 20B.2 · Employee onboarding — templates editor, assignment queue,
 * and per-user "My onboarding" checklist. Bundled in one file for brevity.
 */
import React, { useEffect, useState } from 'react';
import { ClipboardCheck, Plus, Trash2, X, CheckCircle2, Circle, Users2, FileEdit } from "lucide-react";
import { api } from "@/api";
import { colors, gradients } from "@/theme";

/** ── /admin/onboarding/templates ─────────────────────────────────────── */
export function OnboardingTemplates() {
  const [rows, setRows] = useState([]);
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState("technician");
  const [steps, setSteps] = useState([{ title: "", kind: "task" }]);

  const load = () => api.get("/onboarding/templates").then(setRows);
  useEffect(() => { load(); }, []);

  const create = async () => {
    const clean = steps.filter((s) => s.title.trim());
    if (!name.trim() || clean.length === 0) return;
    await api.post("/onboarding/templates", { role, title: name, steps: clean });
    setShowNew(false); setName(""); setSteps([{ title: "", kind: "task" }]);
    load();
  };
  const remove = async (id) => { await api.del(`/onboarding/templates/${id}`); load(); };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="admin-onboarding-templates">
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <ClipboardCheck size={22} style={{ color: colors.brand }}/>
            <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
              Onboarding Templates
            </h1>
          </div>
          <p className="text-sm" style={{ color: colors.muted }}>
            Reusable checklists for new-hire onboarding. Default technician
            template is seeded automatically.
          </p>
        </div>
        <button onClick={() => setShowNew(true)}
                className="flex items-center gap-1.5 px-4 py-2 text-sm font-bold rounded-xl"
                style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                data-testid="tmpl-new-btn">
          <Plus size={14}/> New Template
        </button>
      </div>

      <div className="space-y-3">
        {rows.map((t) => (
          <div key={t.id} className="rounded-xl p-4 flex items-center gap-3"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
               data-testid={`tmpl-row-${t.id}`}>
            <FileEdit size={18} style={{ color: colors.brand }}/>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                {t.title}
                {t.is_default ? (
                  <span className="text-[9px] font-bold px-1.5 py-0.5 rounded ml-2 uppercase"
                        style={{ backgroundColor: colors.brand + "22", color: colors.brand }}>
                    Default
                  </span>
                ) : null}
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {t.role} · {(t.steps || []).length} steps
              </div>
            </div>
            {!t.is_default && (
              <button onClick={() => remove(t.id)}
                      className="p-2 rounded-lg"
                      style={{ color: "#DC2626" }}
                      data-testid={`tmpl-delete-${t.id}`}>
                <Trash2 size={14}/>
              </button>
            )}
          </div>
        ))}
      </div>

      {showNew && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-4"
             style={{ background: "rgba(0,0,0,0.5)" }}
             onClick={() => setShowNew(false)}>
          <div className="max-w-lg w-full p-6 rounded-2xl overflow-y-auto max-h-[85vh]"
               onClick={(e) => e.stopPropagation()}
               style={{ backgroundColor: colors.surface }}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold" style={{ color: colors.onSurface }}>New Template</h3>
              <button onClick={() => setShowNew(false)} style={{ color: colors.muted }}>
                <X size={18}/>
              </button>
            </div>
            <input value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="Template name"
                   className="w-full p-2.5 rounded-lg text-sm mb-2"
                   style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="tmpl-new-title" />
            <select value={role} onChange={(e) => setRole(e.target.value)}
                    className="w-full p-2.5 rounded-lg text-sm mb-3"
                    style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="tmpl-new-role">
              <option value="technician">Technician</option>
              <option value="admin">Admin</option>
              <option value="marketing">Marketing</option>
              <option value="generic">Generic</option>
            </select>
            <div className="text-xs font-bold uppercase mb-2" style={{ color: colors.muted }}>
              Steps
            </div>
            {steps.map((s, i) => (
              <div key={i} className="flex gap-2 mb-2">
                <input value={s.title}
                       onChange={(e) => {
                         const next = [...steps]; next[i].title = e.target.value;
                         setSteps(next);
                       }}
                       placeholder="Step title"
                       className="flex-1 p-2 text-sm rounded-lg"
                       style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
                <select value={s.kind}
                        onChange={(e) => {
                          const next = [...steps]; next[i].kind = e.target.value;
                          setSteps(next);
                        }}
                        className="p-2 text-sm rounded-lg"
                        style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}>
                  <option value="task">Task</option>
                  <option value="doc_upload">Doc upload</option>
                  <option value="video">Video</option>
                  <option value="policy_ack">Policy ack</option>
                </select>
              </div>
            ))}
            <button onClick={() => setSteps([...steps, { title: "", kind: "task" }])}
                    className="text-xs font-semibold mb-4"
                    style={{ color: colors.brand }}
                    data-testid="tmpl-new-add-step">
              + Add step
            </button>
            <button onClick={create}
                    className="w-full py-2 rounded-lg text-sm font-bold"
                    style={{ background: gradients.navyToGreen.css, color: "#fff" }}
                    data-testid="tmpl-new-submit">
              Create Template
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** ── /admin/onboarding/queue ─────────────────────────────────────────── */
export function OnboardingQueue() {
  const [rows, setRows] = useState([]);
  const [users, setUsers] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [assignUid, setAssignUid] = useState("");
  const [assignTid, setAssignTid] = useState("");

  const load = () => api.get("/onboarding/assignments").then(setRows);
  useEffect(() => {
    load();
    api.get("/team/users").then(setUsers).catch(() => {});
    api.get("/onboarding/templates").then(setTemplates);
  }, []);

  const assign = async () => {
    if (!assignUid || !assignTid) return;
    await api.post("/onboarding/assignments", { user_id: assignUid, template_id: assignTid });
    setAssignUid(""); setAssignTid("");
    load();
  };

  return (
    <div className="max-w-5xl mx-auto p-4 md:p-6" data-testid="admin-onboarding-queue">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <Users2 size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Onboarding Queue
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Track every employee's onboarding progress.
        </p>
      </div>

      <div className="rounded-2xl p-4 mb-6 grid grid-cols-3 gap-2 items-end"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <select value={assignUid} onChange={(e) => setAssignUid(e.target.value)}
                className="p-2 text-sm rounded-lg"
                style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="onbq-user">
          <option value="">— Choose employee —</option>
          {users.map((u) => <option key={u.id} value={u.id}>{u.name || u.email}</option>)}
        </select>
        <select value={assignTid} onChange={(e) => setAssignTid(e.target.value)}
                className="p-2 text-sm rounded-lg"
                style={{ backgroundColor: colors.background, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="onbq-tmpl">
          <option value="">— Choose template —</option>
          {templates.map((t) => <option key={t.id} value={t.id}>{t.title} ({t.role})</option>)}
        </select>
        <button onClick={assign}
                className="p-2 text-sm font-bold rounded-lg"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="onbq-assign">
          Assign
        </button>
      </div>

      <div className="space-y-2">
        {rows.map((r) => {
          const total = (r.template_snapshot?.steps || []).length;
          const done = Object.values(r.step_progress || {}).filter((s) => s.completed_at).length;
          const pct = total ? Math.round(100 * done / total) : 0;
          const u = users.find((x) => x.id === r.user_id) || {};
          return (
            <div key={r.id} className="rounded-xl p-4 flex items-center gap-4"
                 style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                 data-testid={`onbq-row-${r.id}`}>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
                  {u.name || u.email || r.user_id.slice(0, 8)}
                </div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  {r.template_snapshot?.title || "Template"} · {r.status}
                </div>
              </div>
              <div className="w-40">
                <div className="text-[10px] mb-1 flex justify-between"
                     style={{ color: colors.muted }}>
                  <span>{done}/{total}</span><span>{pct}%</span>
                </div>
                <div className="w-full h-2 rounded-full overflow-hidden"
                     style={{ backgroundColor: colors.background }}>
                  <div className="h-full" style={{ width: `${pct}%`, background: gradients.navyToGreen.css }} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** ── /onboarding/mine ─────────────────────────────────────────────────── */
export default function MyOnboarding() {
  const [rows, setRows] = useState([]);

  const load = () => api.get("/onboarding/assignments/mine").then(setRows);
  useEffect(load, []);

  const completeStep = async (a, sid) => {
    await api.post(`/onboarding/assignments/${a.id}/steps/${sid}/complete`);
    load();
  };

  if (rows.length === 0) return (
    <div className="max-w-3xl mx-auto p-6 text-center" data-testid="my-onboarding-empty">
      <ClipboardCheck size={40} className="mx-auto mb-3" style={{ color: colors.muted }} />
      <div className="text-sm" style={{ color: colors.muted }}>
        No active onboarding tasks. If you're a new hire, ask your admin
        to assign you a template.
      </div>
    </div>
  );

  return (
    <div className="max-w-3xl mx-auto p-4 md:p-6" data-testid="my-onboarding-page">
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-1">
          <ClipboardCheck size={22} style={{ color: colors.brand }}/>
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>
            Complete your onboarding
          </h1>
        </div>
        <p className="text-sm" style={{ color: colors.muted }}>
          Work through each step. Progress is saved automatically.
        </p>
      </div>

      {rows.map((a) => {
        const steps = a.template_snapshot?.steps || [];
        const done = Object.values(a.step_progress || {}).filter((s) => s.completed_at).length;
        const pct = steps.length ? Math.round(100 * done / steps.length) : 0;
        return (
          <div key={a.id} className="rounded-2xl p-4 mb-4"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between mb-4">
              <div className="text-sm font-bold" style={{ color: colors.onSurface }}>
                {a.template_snapshot?.title}
              </div>
              <div className="text-xs font-bold" style={{ color: colors.brand }}>
                {done} / {steps.length} · {pct}%
              </div>
            </div>
            <div className="space-y-2">
              {steps.map((s, i) => {
                const p = (a.step_progress || {})[s.id] || {};
                const isDone = !!p.completed_at;
                return (
                  <button key={s.id} onClick={() => !isDone && completeStep(a, s.id)}
                          disabled={isDone}
                          className="w-full text-left flex items-center gap-3 p-3 rounded-lg transition"
                          style={{
                            backgroundColor: isDone ? "#ECFDF5" : colors.background,
                            border: `1px solid ${isDone ? "#6EE7B7" : colors.border}`,
                          }}
                          data-testid={`my-onboarding-step-${a.id}-${i}`}>
                    {isDone ? (
                      <CheckCircle2 size={18} style={{ color: "#059669" }} />
                    ) : (
                      <Circle size={18} style={{ color: colors.muted }} />
                    )}
                    <div className="flex-1">
                      <div className="text-sm font-semibold"
                           style={{ color: isDone ? "#065F46" : colors.onSurface }}>
                        {s.title}
                      </div>
                      <div className="text-xs" style={{ color: colors.muted }}>
                        {s.kind} · {s.description}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
