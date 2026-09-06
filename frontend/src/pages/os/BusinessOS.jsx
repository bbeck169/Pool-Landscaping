import React, { useEffect, useState, useCallback } from "react";
import { NavLink, Outlet } from 'react-router-dom';
import { api } from "@/api";
import { colors, gradients } from "@/theme";
import { Compass, Zap, Users, ClipboardList, Trello, Rocket, Calendar, Plus, Sparkles, X, Circle, Trash2, Save } from "lucide-react";

/* ────────────────────────────────────────────────────────────────────
   Shared UI primitives
   ──────────────────────────────────────────────────────────────────── */
const Card = ({ children, className = "", testId }) => (
  <div
    className={`rounded-2xl ${className}`}
    style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
    data-testid={testId}
  >
    {children}
  </div>
);

const BtnPrimary = ({ children, testId, ...rest }) => (
  <button
    className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50 flex items-center gap-1"
    style={{ background: gradients.navyToGreen.css }}
    data-testid={testId}
    {...rest}
  >
    {children}
  </button>
);

const BtnGhost = ({ children, testId, ...rest }) => (
  <button
    className="px-3 py-2 rounded-xl text-sm font-semibold"
    style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
             border: `1px solid ${colors.border}` }}
    data-testid={testId}
    {...rest}
  >
    {children}
  </button>
);

const Section = ({ title, subtitle, right, children }) => (
  <div className="p-4 md:p-8 max-w-7xl mx-auto">
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

/* ────────────────────────────────────────────────────────────────────
   /os · Business OS Layout (side sub-nav)
   ──────────────────────────────────────────────────────────────────── */
const OS_TABS = [
  { to: "/os",             label: "Overview",   icon: Compass },
  { to: "/os/sprints",     label: "Sprints",    icon: Rocket },
  { to: "/os/huddles",     label: "Huddles",    icon: Calendar },
  { to: "/os/scorecards",  label: "Scorecards", icon: Zap },
  { to: "/os/leanboards",  label: "LeanBoards", icon: Trello },
  { to: "/os/sops",        label: "SOPs",       icon: ClipboardList },
  { to: "/os/roles",       label: "Roles",      icon: Users },
];

export function BusinessOSLayout() {
  return (
    <div className="flex flex-col lg:flex-row gap-0" data-testid="business-os-layout">
      <aside
        className="lg:w-56 lg:min-h-[calc(100vh-0px)] p-4 lg:sticky lg:top-0"
        style={{
          // Phase K50 extension · Feb-2026 — full-width secondary
          // sub-nav (moves user between /os/sprints, /os/huddles,
          // /os/scorecards, …).  Qualifies as a menu bar under the
          // K50 rule and is themed via the single ``colors.nav``
          // token (no fresh hex).  Mobile drawer chrome remains
          // deferred per the K50 extension brief.
          borderRight: `1px solid ${colors.nav.border}`,
          backgroundColor: colors.nav.bg,
        }}
        data-testid="os-subnav"
      >
        <div className="text-xs font-bold uppercase tracking-wider mb-3"
             style={{ color: colors.nav.fgMuted }}>Business OS</div>
        <nav className="flex lg:flex-col gap-1 overflow-x-auto lg:overflow-visible">
          {OS_TABS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/os"}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-semibold whitespace-nowrap transition-colors duration-150 hover:bg-white/10"
              style={({ isActive }) => ({
                // Phase K52 Slice D · Feb-2026 — active tab on the
                // BusinessOS sub-nav renders on the K52 signature
                // gradient (emerald→sky), matching the sidebar rail
                // and the top-bar CategoryDropdown active state.
                // Idle = white on navy.
                background: isActive ? colors.gradient.css : "transparent",
                color: isActive ? colors.gradient.fg : colors.nav.fg,
                textShadow: isActive ? colors.gradient.textShadow : undefined,
              })}
              data-testid={`os-tab-${label.toLowerCase()}`}
            >
              <Icon size={16} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 min-w-0">
        <Outlet />
      </main>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /os · Four Pillars Overview
   ──────────────────────────────────────────────────────────────────── */
const Pillar = ({ title, tone, items }) => (
  <Card testId={`os-pillar-${title.toLowerCase()}`} className="p-5">
    <div className="flex items-center gap-2 mb-4">
      <span
        className="w-2 h-8 rounded-full"
        style={{ backgroundColor: tone }}
      />
      <div className="text-sm font-bold uppercase tracking-wide"
           style={{ color: colors.onSurface }}>{title}</div>
    </div>
    <div className="grid grid-cols-2 gap-3">
      {items.map((it, i) => (
        <div key={i}>
          <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>{it.value}</div>
          <div className="text-xs" style={{ color: colors.muted }}>{it.label}</div>
        </div>
      ))}
    </div>
  </Card>
);

export function OverviewPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    api.get("/os/overview").then((r) => { setData(r); setLoading(false); }).catch(() => setLoading(false));
  }, []);
  const ops = data?.ops || {};
  const finance = data?.finance || {};
  const people = data?.people || {};
  const customer = data?.customer || {};
  return (
    <Section
      title="Business OS"
      subtitle="Four Pillars — real-time snapshot of Ops / Finance / People / Customer."
    >
      {loading ? (
        <div style={{ color: colors.muted }} data-testid="os-loading">Loading…</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Pillar title="Ops" tone={colors.brand} items={[
            { label: "Open jobs", value: ops.open_jobs ?? 0 },
            { label: "Completed", value: ops.completed_jobs ?? 0 },
            { label: "Open tasks", value: ops.open_tasks ?? 0 },
            { label: "Latest sprint", value: ops.latest_sprint?.theme || "—" },
          ]}/>
          <Pillar title="Finance" tone={colors.brandSecondary} items={[
            { label: "Unpaid invoices", value: finance.unpaid_invoices ?? 0 },
            { label: "Paid invoices",   value: finance.paid_invoices ?? 0 },
          ]}/>
          <Pillar title="People" tone="#7C3AED" items={[
            { label: "Technicians",   value: people.technicians ?? 0 },
            { label: "Roles defined", value: people.roles_defined ?? 0 },
            { label: "SOPs",          value: people.sops ?? 0 },
          ]}/>
          <Pillar title="Customer" tone="#DC2626" items={[
            { label: "Customers", value: customer.total_customers ?? 0 },
            { label: "CSAT avg",  value: customer.csat_avg ?? "—" },
          ]}/>
        </div>
      )}
    </Section>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /os/sops · SOP Library
   ──────────────────────────────────────────────────────────────────── */
export function SopsPage() {
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(null);
  const [genOpen, setGenOpen] = useState(false);
  const load = () => api.get("/sops").then(setRows).catch(() => {});
  useEffect(() => { load(); }, []);

  return (
    <Section
      title="SOP Library"
      subtitle="Step-by-step playbooks for every recurring service."
      right={
        <div className="flex gap-2">
          <BtnGhost testId="sop-generate-btn" onClick={() => setGenOpen(true)}>
            <Sparkles size={14}/> Generate with Lana
          </BtnGhost>
          <BtnPrimary testId="sop-new-btn" onClick={() => setEditing({ title: "", content: "", category: "Pool" })}>
            <Plus size={14}/> New SOP
          </BtnPrimary>
        </div>
      }
    >
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3" data-testid="sop-grid">
        {rows.map((r) => (
          <Card key={r.id} testId={`sop-row-${r.slug}`} className="p-4">
            <div className="text-[11px] uppercase tracking-wider mb-1" style={{ color: colors.muted }}>
              {r.category} · v{r.version}
            </div>
            <div className="font-bold text-base mb-2" style={{ color: colors.onSurface }}>{r.title}</div>
            <pre className="text-xs whitespace-pre-wrap font-sans line-clamp-6" style={{ color: colors.onSurfaceSecondary }}>
              {r.content}
            </pre>
            <div className="flex justify-between items-center mt-3">
              <div className="text-xs" style={{ color: colors.muted }}>{r.owner_role || "—"}</div>
              <button className="text-xs font-semibold" style={{ color: colors.brand }}
                      onClick={() => setEditing(r)}
                      data-testid={`sop-edit-${r.slug}`}>
                Edit
              </button>
            </div>
          </Card>
        ))}
        {rows.length === 0 && <div style={{ color: colors.muted }} data-testid="sop-empty">No SOPs yet.</div>}
      </div>

      {editing && <SopEditorModal
        sop={editing}
        onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); load(); }}
      />}
      {genOpen && <SopGenerateModal
        onClose={() => setGenOpen(false)}
        onGenerated={(draft) => { setGenOpen(false); setEditing(draft); }}
      />}
    </Section>
  );
}

function SopEditorModal({ sop, onClose, onSaved }) {
  const [form, setForm] = useState(sop);
  const [saving, setSaving] = useState(false);
  const isNew = !sop.id;
  const save = async () => {
    setSaving(true);
    try {
      if (isNew) await api.post("/sops", form);
      else await api.put(`/sops/${sop.id}`, form);
      onSaved();
    } catch (e) { alert(e.message); }
    finally { setSaving(false); }
  };
  const del = async () => {
    if (!confirm("Delete this SOP?")) return;
    await api.del(`/sops/${sop.id}`);
    onSaved();
  };
  return (
    <Modal onClose={onClose} title={isNew ? "New SOP" : `Edit · ${sop.title}`} testId="sop-editor-modal">
      <Field label="Title">
        <input value={form.title || ""} onChange={(e) => setForm({ ...form, title: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sop-editor-title"/>
      </Field>
      <Field label="Category">
        <input value={form.category || ""} onChange={(e) => setForm({ ...form, category: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sop-editor-category"/>
      </Field>
      <Field label="Owner role slug">
        <input value={form.owner_role || ""} onChange={(e) => setForm({ ...form, owner_role: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sop-editor-owner"/>
      </Field>
      <Field label="Content">
        <textarea rows={10} value={form.content || ""} onChange={(e) => setForm({ ...form, content: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm font-mono"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sop-editor-content"/>
      </Field>
      <div className="flex justify-between items-center pt-2">
        {!isNew && (
          <button className="text-sm font-semibold" style={{ color: colors.error }}
                  onClick={del} data-testid="sop-delete-btn">
            <Trash2 size={14} className="inline"/> Delete
          </button>
        )}
        <div className="ml-auto flex gap-2">
          <BtnGhost testId="sop-cancel-btn" onClick={onClose}>Cancel</BtnGhost>
          <BtnPrimary testId="sop-save-btn" onClick={save} disabled={saving || !form.title}>
            <Save size={14}/> {isNew ? "Create" : "Save"}
          </BtnPrimary>
        </div>
      </div>
    </Modal>
  );
}

function SopGenerateModal({ onClose, onGenerated }) {
  const [form, setForm] = useState({ title: "", category: "Pool", hint: "" });
  const [busy, setBusy] = useState(false);
  const gen = async () => {
    setBusy(true);
    try {
      const r = await api.post("/sops/generate", form);
      onGenerated({ title: r.title, category: r.category, content: r.content, owner_role: "" });
    } catch (e) { alert(e.message); }
    finally { setBusy(false); }
  };
  return (
    <Modal onClose={onClose} title="Lana AI · Draft an SOP" testId="sop-generate-modal">
      <Field label="Title">
        <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sop-gen-title"/>
      </Field>
      <Field label="Category">
        <input value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sop-gen-category"/>
      </Field>
      <Field label="Hint (optional)">
        <textarea rows={3} value={form.hint} onChange={(e) => setForm({ ...form, hint: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sop-gen-hint"/>
      </Field>
      <div className="flex justify-end gap-2 pt-2">
        <BtnGhost onClick={onClose} testId="sop-gen-cancel">Cancel</BtnGhost>
        <BtnPrimary onClick={gen} disabled={busy || !form.title} testId="sop-gen-run">
          <Sparkles size={14}/> {busy ? "Drafting…" : "Draft"}
        </BtnPrimary>
      </div>
    </Modal>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /os/roles · Role Definitions
   ──────────────────────────────────────────────────────────────────── */
export function RolesPage() {
  const [rows, setRows] = useState([]);
  const [editing, setEditing] = useState(null);
  const load = () => api.get("/role-definitions").then(setRows).catch(() => {});
  useEffect(() => { load(); }, []);
  return (
    <Section
      title="Role Definitions"
      subtitle="Every seat in the business, with responsibilities + KPIs."
      right={<BtnPrimary onClick={() => setEditing({ title: "", responsibilities: [], kpis: [] })}
                        testId="role-new-btn"><Plus size={14}/> New role</BtnPrimary>}
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {rows.map((r) => (
          <Card key={r.id} testId={`role-row-${r.slug}`} className="p-4">
            <div className="text-[11px] uppercase tracking-wider mb-1" style={{ color: colors.muted }}>
              {r.reports_to ? `Reports to ${r.reports_to}` : "Top of hierarchy"}
            </div>
            <div className="font-bold text-base mb-2" style={{ color: colors.onSurface }}>{r.title}</div>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Responsibilities</div>
            <ul className="text-xs mb-2 list-disc pl-4" style={{ color: colors.onSurfaceSecondary }}>
              {(r.responsibilities || []).map((it, i) => <li key={i}>{it}</li>)}
            </ul>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>KPIs</div>
            <ul className="text-xs list-disc pl-4" style={{ color: colors.onSurfaceSecondary }}>
              {(r.kpis || []).map((it, i) => <li key={i}>{it}</li>)}
            </ul>
            <button className="text-xs font-semibold mt-3" style={{ color: colors.brand }}
                    onClick={() => setEditing(r)}
                    data-testid={`role-edit-${r.slug}`}>Edit</button>
          </Card>
        ))}
      </div>
      {editing && <RoleEditor role={editing} onClose={() => setEditing(null)}
                              onSaved={() => { setEditing(null); load(); }} />}
    </Section>
  );
}

function RoleEditor({ role, onClose, onSaved }) {
  const [form, setForm] = useState({
    ...role,
    responsibilities: (role.responsibilities || []).join("\n"),
    kpis: (role.kpis || []).join("\n"),
  });
  const isNew = !role.id;
  const save = async () => {
    const payload = {
      title: form.title,
      slug: form.slug,
      reports_to: form.reports_to,
      responsibilities: form.responsibilities.split("\n").map((s) => s.trim()).filter(Boolean),
      kpis: form.kpis.split("\n").map((s) => s.trim()).filter(Boolean),
    };
    try {
      if (isNew) await api.post("/role-definitions", payload);
      else await api.put(`/role-definitions/${role.id}`, payload);
      onSaved();
    } catch (e) { alert(e.message); }
  };
  return (
    <Modal onClose={onClose} title={isNew ? "New Role" : `Edit · ${role.title}`} testId="role-editor-modal">
      <Field label="Title">
        <input value={form.title || ""} onChange={(e) => setForm({ ...form, title: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="role-editor-title"/>
      </Field>
      <Field label="Reports to (role slug)">
        <input value={form.reports_to || ""} onChange={(e) => setForm({ ...form, reports_to: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="role-editor-reports-to"/>
      </Field>
      <Field label="Responsibilities (one per line)">
        <textarea rows={5} value={form.responsibilities}
               onChange={(e) => setForm({ ...form, responsibilities: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="role-editor-resp"/>
      </Field>
      <Field label="KPIs (one per line)">
        <textarea rows={4} value={form.kpis}
               onChange={(e) => setForm({ ...form, kpis: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="role-editor-kpis"/>
      </Field>
      <div className="flex justify-end gap-2 pt-2">
        <BtnGhost onClick={onClose} testId="role-cancel-btn">Cancel</BtnGhost>
        <BtnPrimary onClick={save} disabled={!form.title} testId="role-save-btn">
          <Save size={14}/> Save
        </BtnPrimary>
      </div>
    </Modal>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /os/scorecards · KPI Scorecards
   ──────────────────────────────────────────────────────────────────── */
const RAG = { green: "#16A34A", yellow: "#CA8A04", red: "#DC2626" };

export function ScorecardsPage() {
  const [rows, setRows] = useState([]);
  const load = () => api.get("/kpi-scorecards").then(setRows).catch(() => {});
  useEffect(() => { load(); }, []);
  const update = async (row, mIdx, patch) => {
    const metrics = row.metrics.map((m, i) => i === mIdx ? { ...m, ...patch } : m);
    await api.post("/kpi-scorecards", {
      role_slug: row.role_slug, role_title: row.role_title, metrics,
    });
    load();
  };
  return (
    <Section title="KPI Scorecards" subtitle="Green / yellow / red vs. target — updated by the team weekly.">
      <div className="space-y-4">
        {rows.map((row) => (
          <Card key={row.id} testId={`scorecard-${row.role_slug}`} className="p-5">
            <div className="text-base font-bold mb-3" style={{ color: colors.onSurface }}>
              {row.role_title}
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr style={{ color: colors.muted }}>
                  <th className="text-left font-semibold pb-2">Metric</th>
                  <th className="text-right font-semibold pb-2">Target</th>
                  <th className="text-right font-semibold pb-2">Actual</th>
                  <th className="text-right font-semibold pb-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {row.metrics.map((m, i) => (
                  <tr key={i} style={{ borderTop: `1px solid ${colors.border}` }}>
                    <td className="py-2" style={{ color: colors.onSurface }}>{m.label}</td>
                    <td className="text-right py-2">
                      <input type="number" value={m.target}
                             className="w-20 px-2 py-1 text-right rounded-md"
                             style={{ border: `1px solid ${colors.border}` }}
                             onBlur={(e) => update(row, i, { target: parseFloat(e.target.value) || 0 })}
                             defaultValue={m.target}
                             data-testid={`scorecard-target-${row.role_slug}-${i}`}
                             onChange={()=>{}}/>
                    </td>
                    <td className="text-right py-2">
                      <input type="number" defaultValue={m.actual}
                             className="w-20 px-2 py-1 text-right rounded-md"
                             style={{ border: `1px solid ${colors.border}` }}
                             onBlur={(e) => update(row, i, { actual: parseFloat(e.target.value) || 0 })}
                             data-testid={`scorecard-actual-${row.role_slug}-${i}`}
                             onChange={()=>{}}/>
                    </td>
                    <td className="text-right py-2">
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-bold text-white"
                            style={{ backgroundColor: RAG[m.status] || colors.muted }}
                            data-testid={`scorecard-rag-${row.role_slug}-${i}`}>
                        {(m.status || "").toUpperCase()}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        ))}
      </div>
    </Section>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /os/huddles · Crew Huddle
   ──────────────────────────────────────────────────────────────────── */
export function HuddlesPage() {
  const [rows, setRows] = useState([]);
  const [active, setActive] = useState(null);
  const [creating, setCreating] = useState(false);
  const load = () => api.get("/huddles").then(setRows).catch(() => {});
  useEffect(() => { load(); }, []);

  return (
    <Section
      title="Crew Huddles"
      subtitle="Daily Level-10s — Lana drafts your agenda, action items become tasks."
      right={<BtnPrimary onClick={() => setCreating(true)} testId="huddle-new-btn">
              <Plus size={14}/> New Huddle
            </BtnPrimary>}
    >
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card testId="huddle-list" className="p-4">
          <div className="text-sm font-bold mb-3" style={{ color: colors.muted }}>Recent</div>
          {rows.map((h) => (
            <button key={h.id} onClick={() => setActive(h)}
                    className="w-full text-left px-3 py-2 rounded-lg mb-1 hover:brightness-95"
                    style={{ backgroundColor: active?.id === h.id ? colors.brandTertiary : "transparent",
                             color: colors.onSurface }}
                    data-testid={`huddle-row-${h.date}`}>
              <div className="font-semibold text-sm">{h.date}</div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {h.title} · {(h.action_items || []).length} action item(s)
              </div>
            </button>
          ))}
          {rows.length === 0 && <div className="text-sm" style={{ color: colors.muted }}>No huddles yet.</div>}
        </Card>
        <div>{active && <HuddleDetail huddle={active} onChange={load}/>}</div>
      </div>
      {creating && <HuddleCreator onClose={() => setCreating(false)}
                                  onCreated={(h) => { setCreating(false); setActive(h); load(); }} />}
    </Section>
  );
}

function HuddleCreator({ onClose, onCreated }) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const create = async () => {
    const r = await api.post("/huddles", { date, title: "Daily Huddle" });
    onCreated(r);
  };
  return (
    <Modal onClose={onClose} title="New Huddle" testId="huddle-create-modal">
      <Field label="Date">
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="huddle-create-date"/>
      </Field>
      <div className="flex justify-end gap-2">
        <BtnGhost onClick={onClose}>Cancel</BtnGhost>
        <BtnPrimary onClick={create} testId="huddle-create-submit">Create</BtnPrimary>
      </div>
    </Modal>
  );
}

function HuddleDetail({ huddle: initial, onChange }) {
  const [huddle, setHuddle] = useState(initial);
  const [drafting, setDrafting] = useState(false);
  const [newAction, setNewAction] = useState("");
  useEffect(() => { setHuddle(initial); }, [initial]);
  const draft = async () => {
    setDrafting(true);
    try {
      const r = await api.post(`/huddles/${huddle.id}/agenda`);
      setHuddle({ ...huddle, agenda: r.agenda });
    } catch (e) { alert(e.message); }
    finally { setDrafting(false); }
  };
  const addAction = async () => {
    if (!newAction.trim()) return;
    const r = await api.post(`/huddles/${huddle.id}/action-items`, { huddle_id: huddle.id, text: newAction });
    setHuddle({ ...huddle, action_items: [...(huddle.action_items || []), r.action] });
    setNewAction("");
    onChange && onChange();
  };
  return (
    <Card testId="huddle-detail" className="p-5">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-sm font-bold" style={{ color: colors.onSurface }}>{huddle.title}</div>
          <div className="text-xs" style={{ color: colors.muted }}>{huddle.date}</div>
        </div>
        <BtnGhost onClick={draft} testId="huddle-draft-agenda-btn">
          <Sparkles size={14}/> {drafting ? "Drafting…" : "Draft with Lana"}
        </BtnGhost>
      </div>
      {huddle.agenda ? (
        <pre className="text-xs whitespace-pre-wrap font-sans p-3 rounded-lg mb-4"
             style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
             data-testid="huddle-agenda">
          {huddle.agenda}
        </pre>
      ) : (
        <div className="text-sm mb-4" style={{ color: colors.muted }}>No agenda yet — click Draft with Lana.</div>
      )}
      <div className="text-sm font-bold mb-2" style={{ color: colors.onSurface }}>Action Items</div>
      <div className="space-y-1 mb-3">
        {(huddle.action_items || []).map((a) => (
          <div key={a.id} className="flex items-center gap-2 text-sm" data-testid={`huddle-action-${a.id}`}>
            <Circle size={14} style={{ color: colors.muted }}/>
            <span style={{ color: colors.onSurface }}>{a.text}</span>
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        <input value={newAction} onChange={(e) => setNewAction(e.target.value)}
               placeholder="Add an action item…"
               className="flex-1 px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="huddle-action-input"/>
        <BtnPrimary onClick={addAction} testId="huddle-action-add">Add</BtnPrimary>
      </div>
    </Card>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /os/leanboards · LeanBoard kanban
   ──────────────────────────────────────────────────────────────────── */
export function LeanboardsPage() {
  const [boards, setBoards] = useState([]);
  const [active, setActive] = useState(null);
  useEffect(() => {
    api.get("/leanboards").then((r) => {
      setBoards(r);
      if (r.length) setActive(r[0]);
    }).catch(() => {});
  }, []);
  return (
    <Section title="LeanBoards" subtitle="Kanban tied to your SOPs — move cards through the flow.">
      <div className="flex gap-2 mb-4 overflow-x-auto">
        {boards.map((b) => (
          <button key={b.id} onClick={() => setActive(b)}
                  className="px-3 py-2 rounded-xl text-sm font-semibold whitespace-nowrap"
                  style={{ backgroundColor: active?.id === b.id ? colors.brandTertiary : colors.surfaceSecondary,
                           color: active?.id === b.id ? colors.onBrandTertiary : colors.onSurfaceSecondary }}
                  data-testid={`leanboard-tab-${b.slug}`}>
            {b.title}
          </button>
        ))}
      </div>
      {active && <BoardView board={active}/>}
    </Section>
  );
}

function BoardView({ board }) {
  const [cards, setCards] = useState([]);
  const [addingIn, setAddingIn] = useState(null);
  const [newCardTitle, setNewCardTitle] = useState("");
  const load = useCallback(() => {
    api.get(`/leanboards/${board.id}/cards`).then(setCards).catch(() => {});
  }, [board.id]);
  useEffect(() => { load(); }, [load]);
  const move = async (card, column) => {
    await api.post(`/leanboards/cards/${card.id}/move`, { column });
    load();
  };
  const add = async () => {
    if (!newCardTitle.trim() || !addingIn) return;
    await api.post(`/leanboards/${board.id}/cards`, {
      board_id: board.id, column: addingIn, title: newCardTitle,
    });
    setNewCardTitle(""); setAddingIn(null);
    load();
  };
  const del = async (id) => {
    if (!confirm("Delete card?")) return;
    await api.del(`/leanboards/cards/${id}`);
    load();
  };
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${board.columns.length}, minmax(220px, 1fr))` }}>
      {board.columns.map((col) => (
        <div key={col} className="rounded-2xl p-3"
             style={{ backgroundColor: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}` }}
             data-testid={`leanboard-col-${col}`}>
          <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors.muted }}>{col}</div>
          <div className="space-y-2">
            {cards.filter((c) => c.column === col).map((c) => (
              <div key={c.id} className="p-3 rounded-xl"
                   style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                   data-testid={`leanboard-card-${c.id}`}>
                <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>{c.title}</div>
                {c.body && <div className="text-xs mb-2" style={{ color: colors.muted }}>{c.body}</div>}
                <div className="flex items-center gap-1 flex-wrap">
                  {board.columns.filter((x) => x !== col).map((x) => (
                    <button key={x} onClick={() => move(c, x)}
                            className="text-[10px] px-2 py-0.5 rounded-full"
                            style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
                            data-testid={`leanboard-move-${c.id}-${x}`}>
                      → {x}
                    </button>
                  ))}
                  <button onClick={() => del(c.id)}
                          className="ml-auto text-[10px]" style={{ color: colors.error }}
                          data-testid={`leanboard-del-${c.id}`}>
                    <Trash2 size={12}/>
                  </button>
                </div>
              </div>
            ))}
            {addingIn === col ? (
              <div className="p-2 rounded-xl" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
                <input autoFocus value={newCardTitle} onChange={(e) => setNewCardTitle(e.target.value)}
                       className="w-full px-2 py-1 text-sm rounded-md mb-1"
                       style={{ border: `1px solid ${colors.border}` }}
                       data-testid={`leanboard-newcard-input-${col}`}/>
                <div className="flex gap-1">
                  <button onClick={add} className="text-xs font-semibold px-2 py-1 rounded"
                          style={{ backgroundColor: colors.brand, color: "#fff" }}
                          data-testid={`leanboard-newcard-add-${col}`}>Add</button>
                  <button onClick={() => setAddingIn(null)} className="text-xs" style={{ color: colors.muted }}>Cancel</button>
                </div>
              </div>
            ) : (
              <button onClick={() => setAddingIn(col)}
                      className="w-full text-xs font-semibold py-2 rounded-lg"
                      style={{ color: colors.muted, border: `1px dashed ${colors.border}` }}
                      data-testid={`leanboard-newcard-btn-${col}`}>
                <Plus size={12} className="inline"/> Add card
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ────────────────────────────────────────────────────────────────────
   /os/sprints · Sprint Planner
   ──────────────────────────────────────────────────────────────────── */
export function SprintsPage() {
  const [rows, setRows] = useState([]);
  const [creating, setCreating] = useState(false);
  const [active, setActive] = useState(null);
  const load = () => api.get("/sprints").then((r) => { setRows(r); if (r.length && !active) setActive(r[0]); }).catch(() => {});
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps
  return (
    <Section
      title="Sprint Planner"
      subtitle="Weekly plan → review → retro. One sprint = one week."
      right={<BtnPrimary onClick={() => setCreating(true)} testId="sprint-new-btn"><Plus size={14}/> New sprint</BtnPrimary>}
    >
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="p-4">
          <div className="text-sm font-bold mb-2" style={{ color: colors.muted }}>Sprints</div>
          {rows.map((s) => (
            <button key={s.id} onClick={() => setActive(s)}
                    className="w-full text-left px-3 py-2 rounded-lg mb-1"
                    style={{ backgroundColor: active?.id === s.id ? colors.brandTertiary : "transparent",
                             color: colors.onSurface }}
                    data-testid={`sprint-row-${s.week_start}`}>
              <div className="text-sm font-semibold">{s.week_start}</div>
              <div className="text-xs" style={{ color: colors.muted }}>{s.theme || "—"} · {s.state}</div>
            </button>
          ))}
          {rows.length === 0 && <div className="text-sm" style={{ color: colors.muted }}>No sprints yet.</div>}
        </Card>
        <div className="lg:col-span-2">
          {active && <SprintDetail sprint={active} onSaved={load}/>}
        </div>
      </div>
      {creating && <SprintCreator onClose={() => setCreating(false)}
                                   onCreated={(s) => { setCreating(false); setActive(s); load(); }} />}
    </Section>
  );
}

function SprintCreator({ onClose, onCreated }) {
  const [form, setForm] = useState({ week_start: new Date().toISOString().slice(0, 10),
                                    theme: "", goals: "" });
  const create = async () => {
    const goals = form.goals.split("\n").map((s) => s.trim()).filter(Boolean);
    const r = await api.post("/sprints", { week_start: form.week_start, theme: form.theme, goals });
    onCreated(r);
  };
  return (
    <Modal onClose={onClose} title="New Sprint" testId="sprint-create-modal">
      <Field label="Week start (Monday)">
        <input type="date" value={form.week_start}
               onChange={(e) => setForm({ ...form, week_start: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sprint-create-date"/>
      </Field>
      <Field label="Theme">
        <input value={form.theme}
               onChange={(e) => setForm({ ...form, theme: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sprint-create-theme"/>
      </Field>
      <Field label="Goals (one per line)">
        <textarea rows={4} value={form.goals}
               onChange={(e) => setForm({ ...form, goals: e.target.value })}
               className="w-full px-3 py-2 rounded-lg text-sm"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sprint-create-goals"/>
      </Field>
      <div className="flex justify-end gap-2">
        <BtnGhost onClick={onClose}>Cancel</BtnGhost>
        <BtnPrimary onClick={create} testId="sprint-create-submit">Create sprint</BtnPrimary>
      </div>
    </Modal>
  );
}

function SprintDetail({ sprint: initial, onSaved }) {
  const [sprint, setSprint] = useState(initial);
  const [review, setReview] = useState({
    wins: (initial.review?.wins || []).join("\n"),
    misses: (initial.review?.misses || []).join("\n"),
    retro_kaizen: (initial.review?.retro_kaizen || []).join("\n"),
    score: initial.review?.score || 7,
  });
  const [drafting, setDrafting] = useState(false);
  useEffect(() => {
    setSprint(initial);
    setReview({
      wins: (initial.review?.wins || []).join("\n"),
      misses: (initial.review?.misses || []).join("\n"),
      retro_kaizen: (initial.review?.retro_kaizen || []).join("\n"),
      score: initial.review?.score || 7,
    });
  }, [initial]);
  const saveReview = async () => {
    const body = {
      wins: review.wins.split("\n").map((s) => s.trim()).filter(Boolean),
      misses: review.misses.split("\n").map((s) => s.trim()).filter(Boolean),
      retro_kaizen: review.retro_kaizen.split("\n").map((s) => s.trim()).filter(Boolean),
      score: parseInt(review.score, 10) || null,
    };
    const r = await api.put(`/sprints/${sprint.id}/review`, body);
    setSprint(r);
    onSaved && onSaved();
  };
  const draftRetro = async () => {
    setDrafting(true);
    try {
      const r = await api.post(`/sprints/${sprint.id}/retro-ai`);
      setSprint({ ...sprint, retro_ai: r.retro });
    } catch (e) { alert(e.message); }
    finally { setDrafting(false); }
  };
  return (
    <Card className="p-5" testId="sprint-detail">
      <div className="text-sm font-bold" style={{ color: colors.onSurface }}>Week of {sprint.week_start}</div>
      <div className="text-xs mb-3" style={{ color: colors.muted }}>{sprint.theme || "—"}</div>
      <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Goals</div>
      <ul className="text-sm mb-4 list-disc pl-4" style={{ color: colors.onSurface }}>
        {(sprint.goals || []).map((g, i) => <li key={i}>{g}</li>)}
      </ul>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <Field label="Wins (one per line)">
          <textarea rows={4} value={review.wins}
                    onChange={(e) => setReview({ ...review, wins: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ border: `1px solid ${colors.border}` }}
                    data-testid="sprint-review-wins"/>
        </Field>
        <Field label="Misses">
          <textarea rows={4} value={review.misses}
                    onChange={(e) => setReview({ ...review, misses: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ border: `1px solid ${colors.border}` }}
                    data-testid="sprint-review-misses"/>
        </Field>
        <Field label="Kaizen (retro)">
          <textarea rows={4} value={review.retro_kaizen}
                    onChange={(e) => setReview({ ...review, retro_kaizen: e.target.value })}
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ border: `1px solid ${colors.border}` }}
                    data-testid="sprint-review-retro"/>
        </Field>
      </div>
      <div className="flex items-center gap-3 mb-3">
        <label className="text-xs font-semibold" style={{ color: colors.muted }}>Self-score</label>
        <input type="number" min="1" max="10" value={review.score}
               onChange={(e) => setReview({ ...review, score: e.target.value })}
               className="w-16 px-2 py-1 rounded-md text-sm text-right"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="sprint-review-score"/>
        <BtnPrimary onClick={saveReview} testId="sprint-review-save"><Save size={14}/> Save review</BtnPrimary>
        <BtnGhost onClick={draftRetro} testId="sprint-retro-ai">
          <Sparkles size={14}/> {drafting ? "Drafting…" : "Retro with Lana"}
        </BtnGhost>
      </div>

      {sprint.retro_ai && (
        <div className="text-sm font-bold mb-1" style={{ color: colors.onSurface }}>Lana retro</div>
      )}
      {sprint.retro_ai && (
        <pre className="text-xs whitespace-pre-wrap font-sans p-3 rounded-lg"
             style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
             data-testid="sprint-retro-ai">
          {sprint.retro_ai}
        </pre>
      )}
    </Card>
  );
}

/* ────────────────────────────────────────────────────────────────────
   Shared modal + field
   ──────────────────────────────────────────────────────────────────── */
function Modal({ onClose, title, children, testId }) {
  return (
    <div className="fixed inset-0 z-40 flex items-end md:items-center justify-center p-2"
         style={{ backgroundColor: "rgba(0,0,0,0.55)" }} data-testid={testId}>
      <div className="w-full max-w-lg rounded-2xl p-5"
           style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
        <div className="flex items-center justify-between mb-3">
          <div className="text-base font-bold" style={{ color: colors.onSurface }}>{title}</div>
          <button onClick={onClose} data-testid={`${testId}-close`}
                  style={{ color: colors.muted }}><X size={18}/></button>
        </div>
        <div className="space-y-3">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="text-xs font-semibold uppercase tracking-wider mb-1 block"
             style={{ color: colors.muted }}>{label}</label>
      {children}
    </div>
  );
}
