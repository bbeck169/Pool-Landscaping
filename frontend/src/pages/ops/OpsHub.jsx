import React, { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Users2, Truck, Route, Wrench, ClipboardList, Timer, Clock, Calendar,
  Activity, DollarSign, Waves, Package, History, BarChart3, Layers, PlayCircle,
  ArrowLeft, Plus, Check, X, Trash2, RefreshCw, MapPin, ChevronRight,
} from "lucide-react";
import { api } from "@/api";
import { colors, money, brandGradientCss } from "@/theme";
import { useAuth } from "@/auth";
import {
  PageHeader, Button, Skeleton, StatusPill, Chip, EmptyState, TextInput, Modal, Toast, TagChip,
} from "@/components/ui-kit";
import { useAttendance } from "@/hooks/useAttendance";
import WorkstreamJobDrawer from "@/pages/ops/WorkstreamJobDrawer";

/* ═══ Ops hub – one page, many tabs. Kept compact by construction. ═══ */

const SECTIONS = [
  { k: "dispatch",   label: "Dispatch",     icon: Truck },
  { k: "schedule",   label: "Schedule",     icon: Calendar },
  { k: "routes",     label: "Routes",       icon: Route },
  { k: "workstream", label: "Work Stream",  icon: Activity },
  { k: "crews",      label: "Crews",        icon: Users2 },
  { k: "team",       label: "Team",         icon: Users2 },
  { k: "timesheets", label: "Timesheets",   icon: ClipboardList },
  { k: "timeclock",  label: "Timeclock",    icon: Clock },
  { k: "coverage",   label: "Coverage",     icon: MapPin },
  { k: "maintenance",label: "Maintenance",  icon: Waves },
  { k: "pool",       label: "Pool Service", icon: Waves },
  { k: "equipment",  label: "Equipment",    icon: Wrench },
  { k: "pricebook",  label: "Price Book",   icon: Package },
  { k: "loghistory", label: "Log History",  icon: History },
  { k: "timers",     label: "Job Timers",   icon: Timer },
  { k: "avgtime",    label: "Avg Job Time", icon: BarChart3 },
];

export default function OpsHub() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const tab = params.get("t") || "dispatch";
  const setTab = (k) => { const s = new URLSearchParams(params); s.set("t", k); setParams(s, { replace: true }); };

  const isTech = user?.role === "technician";
  const allowed = isTech ? ["schedule", "routes", "timesheets"] : SECTIONS.map((s) => s.k);
  const filtered = SECTIONS.filter((s) => allowed.includes(s.k));

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6" data-testid="ops-hub">
      <PageHeader title="Operations" subtitle="Dispatch, routes, crews, timesheets & more." />
      <nav className="flex flex-wrap gap-2 mb-4">
        {filtered.map((s) => (
          <button
            key={s.k}
            onClick={() => setTab(s.k)}
            className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-full transition"
            style={{
              backgroundColor: tab === s.k ? colors.brandTertiary : colors.surface,
              color: tab === s.k ? colors.onBrandTertiary : colors.onSurfaceSecondary,
              border: `1px solid ${tab === s.k ? colors.brandTertiary : colors.border}`,
            }}
            data-testid={`ops-tab-${s.k}`}
          >
            <s.icon size={12} /> {s.label}
          </button>
        ))}
      </nav>

      {tab === "dispatch"    && <Dispatch />}
      {tab === "schedule"    && <SchedulePage />}
      {tab === "routes"      && <Routes />}
      {tab === "workstream"  && <Workstream />}
      {tab === "crews"       && <Crews />}
      {tab === "team"        && <TeamRoster />}
      {tab === "timesheets"  && <Timesheets />}
      {tab === "timeclock"   && <Timeclock />}
      {tab === "coverage"    && <Coverage />}
      {tab === "maintenance" && <Maintenance />}
      {tab === "pool"        && <PoolService />}
      {tab === "equipment"   && <Equipment />}
      {tab === "pricebook"   && <PriceBook />}
      {tab === "loghistory"  && <LogHistory />}
      {tab === "timers"      && <JobTimers />}
      {tab === "avgtime"     && <AvgJobTime />}
    </div>
  );
}

/* ─── shared helpers ─── */
function Card({ children, testid }) {
  return (
    <div className="rounded-2xl p-5" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid={testid}>
      {children}
    </div>
  );
}

function useList(url, deps = []) {
  const [rows, setRows] = useState(null);
  const [tick, setTick] = useState(0);
  const refresh = () => setTick((t) => t + 1);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { let live = true; api.get(url).then((r) => live && setRows(r || [])).catch(() => live && setRows([])); return () => { live = false; }; }, [url, tick, ...deps]);
  return [rows, refresh];
}

/* ═══════════ Dispatch board ═══════════ */
function Dispatch() {
  const [jobs, refresh] = useList("/jobs");
  const [techs] = useList("/technicians");
  const [crews] = useList("/crews");
  const [picking, setPicking] = useState(null);
  const [toast, setToast] = useState(null);
  const cols = { unassigned: [], assigned: [], progress: [] };
  (jobs || []).forEach((j) => {
    if (!j.technician_id) cols.unassigned.push(j);
    else if (j.status === "active") cols.progress.push(j);
    else cols.assigned.push(j);
  });
  const assign = async (jid, techId) => {
    try { await api.put(`/jobs/${jid}`, { technician_id: techId }); setToast({ tone: "success", message: "Assigned" }); refresh(); }
    catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3" data-testid="dispatch-board">
      {[["Unassigned", "unassigned"], ["Assigned", "assigned"], ["In Progress", "progress"]].map(([label, k]) => (
        <div key={k} className="rounded-2xl p-3" style={{ backgroundColor: colors.surfaceSecondary, minHeight: 240 }}>
          <div className="text-xs uppercase font-semibold mb-2" style={{ color: colors.muted }}>{label} · {cols[k].length}</div>
          <div className="space-y-2">
            {cols[k].map((j) => (
              <div key={j.id} className="rounded-xl p-3 text-sm" style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }} data-testid={`dispatch-card-${j.id}`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="font-semibold truncate" style={{ color: colors.onSurface }}>{j.title}</div>
                  <StatusPill status={j.status} />
                </div>
                <div className="text-xs mt-1" style={{ color: colors.muted }}>{j.customer_name} · {j.address || "—"}</div>
                <div className="mt-2 flex items-center justify-between">
                  <span className="text-xs" style={{ color: colors.muted }}>{j.technician_name || "Unassigned"}</span>
                  <button onClick={() => setPicking(j)} className="text-xs font-semibold" style={{ color: colors.brand }} data-testid={`dispatch-assign-${j.id}`}>Reassign</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
      <Modal open={!!picking} onClose={() => setPicking(null)} title="Assign to technician">
        <ul className="space-y-1">
          {(techs || []).map((t) => (
            <li key={t.id}>
              <button onClick={() => { assign(picking.id, t.id); setPicking(null); }} className="w-full text-left px-3 py-2 rounded-lg text-sm hover:brightness-95" style={{ backgroundColor: colors.surfaceSecondary }} data-testid={`assign-${t.id}`}>{t.name}</button>
            </li>
          ))}
        </ul>
      </Modal>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

/* ═══════════ Schedule (day view) ═══════════ */
function SchedulePage() {
  const { user } = useAuth();
  const att = useAttendance();
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [jobs, refresh] = useList(`/jobs`, [date]);
  const dayJobs = (jobs || []).filter((j) => (j.scheduled_date || "").startsWith(date));
  const locked = user?.role === "technician" && !att.clockedIn;
  return (
    <Card testid="schedule-page">
      <div className="flex items-center gap-2 mb-3">
        <TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} testid="sched-date" />
        <Button variant="ghost" onClick={refresh}><RefreshCw size={14} /></Button>
      </div>
      {locked ? <p className="text-sm mb-3" style={{ color: "#92400E" }}>🔒 Clock in on mobile to open jobs</p> : null}
      {dayJobs.length === 0 ? <EmptyState title="No jobs scheduled" /> :
       <ul className="space-y-2">{dayJobs.map((j) => (
         <li key={j.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary, opacity: locked ? 0.55 : 1 }} data-testid={`sched-${j.id}`}>
           <div className="flex-1"><div className="font-semibold text-sm">{j.title}</div><div className="text-xs" style={{ color: colors.muted }}>{j.technician_name || "Unassigned"} · {j.customer_name}</div></div>
           <StatusPill status={j.status} />
         </li>
       ))}</ul>}
    </Card>
  );
}

/* ═══════════ Routes ═══════════ */
function Routes() {
  const [techs] = useList("/technicians");
  const [techId, setTechId] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [order, setOrder] = useState(null);
  const [toast, setToast] = useState(null);
  const load = async () => {
    const j = await api.get("/jobs").catch(() => []);
    const filtered = (j || []).filter((x) => (x.scheduled_date || "").startsWith(date) && (!techId || x.technician_id === techId));
    filtered.sort((a, b) => (a.route_order ?? 999) - (b.route_order ?? 999));
    setOrder(filtered);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [techId, date]);
  const move = (i, dir) => { const arr = [...order]; const j = i + dir; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; setOrder(arr); };
  const optimize = async () => {
    setBusy(true);
    try { const r = await api.post("/routes/optimize", { tech_id: techId || null, date }); setToast({ tone: "success", message: `Optimized (${r.method})` }); await load(); }
    catch (e) { setToast({ tone: "error", message: e.message }); }
    finally { setBusy(false); }
  };
  const save = async () => {
    try { await api.post("/jobs/reorder", { job_ids: order.map((j) => j.id) }); setToast({ tone: "success", message: "Order saved" }); }
    catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  return (
    <Card testid="routes-page">
      <div className="flex flex-wrap gap-2 mb-3">
        <TextInput type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <select value={techId} onChange={(e) => setTechId(e.target.value)} className="text-xs font-semibold px-3 py-2 rounded-lg" style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }} data-testid="routes-tech">
          <option value="">All techs</option>
          {(techs || []).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <Button onClick={optimize} disabled={busy} testid="routes-optimize"><Route size={14} /> {busy ? "Optimizing…" : "Auto-optimize"}</Button>
        <Button variant="ghost" onClick={save} testid="routes-save">Save order</Button>
      </div>
      {order === null ? <Skeleton style={{ height: 160 }} /> :
       order.length === 0 ? <EmptyState title="No jobs for that day/tech" /> :
       <ol className="space-y-2">{order.map((j, i) => (
         <li key={j.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary }} data-testid={`route-${j.id}`}>
           <span className="w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center" style={{ background: brandGradientCss, color: "#fff" }}>{i + 1}</span>
           <div className="flex-1"><div className="font-semibold text-sm">{j.title}</div><div className="text-xs" style={{ color: colors.muted }}>{j.address || "—"}</div></div>
           <button onClick={() => move(i, -1)} className="opacity-70">↑</button>
           <button onClick={() => move(i, 1)} className="opacity-70">↓</button>
           <a target="_blank" rel="noreferrer" href={`https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(j.address || "")}`} className="text-xs font-semibold" style={{ color: colors.brand }}>Navigate</a>
         </li>
       ))}</ol>}
      <Toast toast={toast} onClose={() => setToast(null)} />
    </Card>
  );
}

/* ═══════════ Work Stream ═══════════ */
function Workstream() {
  const navigate = useNavigate();
  const [rows] = useList("/activity");
  const [drawerJobId, setDrawerJobId] = useState(null);
  const [paymentInfo, setPaymentInfo] = useState(null);

  const openRow = (a) => {
    const ref = a.related_ref || {};
    const t = ref.type;
    const id = ref.id;
    if (!t || !id) return;
    if (t === "job") setDrawerJobId(id);
    else if (t === "invoice") navigate(`/invoices/${id}`);
    else if (t === "quote") navigate(`/quotes/${id}`);
    else if (t === "customer") navigate(`/customers/${id}`);
    else if (t === "communication") navigate(`/communication/${id}`);
    else if (t === "payment") setPaymentInfo({ ...a });
    else if (t === "review") setPaymentInfo({ ...a }); // reuse compact modal
    else if (t === "lead") navigate(`/leads`);
  };

  return (
    <Card testid="workstream-page">
      {rows === null ? <Skeleton style={{ height: 200 }} /> :
       rows.length === 0 ? <EmptyState icon={Activity} title="No activity yet" /> :
       <ul className="space-y-1 text-sm">
         {rows.slice(0, 100).map((a) => {
           const clickable = !!(a.related_ref && a.related_ref.id);
           return (
             <li key={(a.related_ref?.id || "") + a.at + a.type}
                 onClick={() => clickable && openRow(a)}
                 className={"flex items-center gap-2 p-2 rounded-lg " + (clickable ? "cursor-pointer hover:brightness-95 transition" : "")}
                 style={{ borderBottom: `1px solid ${colors.divider}` }}
                 data-testid={`workstream-row-${a.related_ref?.type || "none"}-${a.related_ref?.id || ""}`}>
               <Chip label={a.type} tone="brand" />
               <div className="flex-1">
                 <div style={{ color: colors.onSurface }}>{a.note || a.summary || a.title || a.type}</div>
                 <div className="text-xs" style={{ color: colors.muted }}>{a.detail || ""}{a.detail ? " · " : ""}{a.at || a.created_at}</div>
               </div>
               {clickable && <ChevronRight size={14} style={{ color: colors.muted }} />}
             </li>
           );
         })}
       </ul>}
      {drawerJobId && (
        <WorkstreamJobDrawer jobId={drawerJobId} onClose={() => setDrawerJobId(null)} />
      )}
      {paymentInfo && (
        <Modal open onClose={() => setPaymentInfo(null)}
               title={paymentInfo.title || "Details"}
               footer={<Button onClick={() => setPaymentInfo(null)}>Close</Button>}>
          <div className="space-y-2 text-sm" data-testid="workstream-info-modal">
            <div style={{ color: colors.onSurface }}>{paymentInfo.detail}</div>
            <div className="text-xs" style={{ color: colors.muted }}>{paymentInfo.at}</div>
          </div>
        </Modal>
      )}
    </Card>
  );
}

/* ═══════════ Crews ═══════════ */
function Crews() {
  const [rows, refresh] = useList("/crews");
  const [techs] = useList("/technicians");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({ name: "", color: "#0284C7", tech_ids: [] });
  const [toast, setToast] = useState(null);
  const openNew = () => { setEditing(null); setForm({ name: "", color: "#0284C7", tech_ids: [] }); setOpen(true); };
  const openEdit = (c) => { setEditing(c); setForm({ name: c.name, color: c.color || "#0284C7", tech_ids: c.tech_ids || [] }); setOpen(true); };
  const save = async () => {
    try {
      if (editing) await api.put(`/crews/${editing.id}`, form);   // PATCH endpoint mapped to PUT via router; use fetch-style below
    } catch {}
    try {
      if (editing) {
        // Use api.request via api.post PATCH not directly available — call via fetch:
        const token = localStorage.getItem("token");
        await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/crews/${editing.id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify(form),
        });
      } else {
        await api.post("/crews", form);
      }
      setOpen(false); refresh();
      setToast({ tone: "success", message: "Saved" });
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  const del = async (cid) => { try { await api.del(`/crews/${cid}`); refresh(); } catch (e) { setToast({ tone: "error", message: e.message }); } };
  return (
    <Card testid="crews-page">
      <div className="flex justify-between mb-3">
        <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Crews · {(rows || []).length}</div>
        <Button onClick={openNew} testid="crews-new"><Plus size={14} /> New crew</Button>
      </div>
      {rows === null ? <Skeleton style={{ height: 160 }} /> :
       rows.length === 0 ? <EmptyState icon={Users2} title="No crews yet" hint="Group techs into color-coded crews for the route board." /> :
       <ul className="space-y-2">
         {rows.map((c) => (
           <li key={c.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary }} data-testid={`crew-${c.id}`}>
             <span className="w-3 h-3 rounded-full" style={{ backgroundColor: c.color }} />
             <div className="flex-1"><div className="font-semibold">{c.name}</div><div className="text-xs" style={{ color: colors.muted }}>{(c.members || []).map((m) => m.name).join(", ") || "No members yet"}</div></div>
             <button onClick={() => openEdit(c)} style={{ color: colors.brand }} className="text-xs font-semibold">Edit</button>
             <button onClick={() => del(c.id)} style={{ color: colors.error }}><Trash2 size={14} /></button>
           </li>
         ))}
       </ul>}
      <Modal open={open} onClose={() => setOpen(false)} title={editing ? "Edit crew" : "New crew"}
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={save} testid="crew-save">Save</Button></>}>
        <div className="space-y-3">
          <TextInput label="NAME" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} testid="crew-name" />
          <TextInput label="COLOR (hex)" value={form.color} onChange={(e) => setForm({ ...form, color: e.target.value })} />
          <div>
            <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>MEMBERS</div>
            <div className="flex flex-wrap gap-2">
              {(techs || []).map((t) => {
                const on = form.tech_ids.includes(t.id);
                return (
                  <button key={t.id} onClick={() => setForm({ ...form, tech_ids: on ? form.tech_ids.filter((x) => x !== t.id) : [...form.tech_ids, t.id] })}
                    className="text-xs font-semibold px-3 py-1 rounded-full"
                    style={{ backgroundColor: on ? colors.brandTertiary : colors.surfaceSecondary, color: on ? colors.onBrandTertiary : colors.muted, border: `1px solid ${colors.border}` }}
                    data-testid={`crew-tech-${t.id}`}>{t.name}</button>
                );
              })}
            </div>
          </div>
        </div>
      </Modal>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </Card>
  );
}

/* ═══════════ Team ═══════════ */
function TeamRoster() {
  const [rows] = useList("/team");
  return (
    <Card testid="team-page">
      {rows === null ? <Skeleton style={{ height: 160 }} /> :
       (rows.length === 0 ? <EmptyState title="No team members" /> :
        <ul className="space-y-2">{rows.map((r) => (
          <li key={r.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary }}>
            <div className="w-9 h-9 rounded-full flex items-center justify-center text-white font-bold" style={{ background: brandGradientCss }}>{(r.name || "?")[0]}</div>
            <div className="flex-1"><div className="font-semibold">{r.name}</div><div className="text-xs" style={{ color: colors.muted }}>{r.email || ""}</div></div>
            <Chip label={r.role || "member"} tone="brand" />
          </li>
        ))}</ul>)}
    </Card>
  );
}

/* ═══════════ Timesheets ═══════════ */
function Timesheets() {
  const [rows, refresh] = useList("/timesheets");
  const [toast, setToast] = useState(null);
  const act = async (tid, action) => { try { await api.post(`/timesheets/${tid}/action`, { action }); refresh(); setToast({ tone: "success", message: action }); } catch (e) { setToast({ tone: "error", message: e.message }); } };
  return (
    <Card testid="timesheets-page">
      {rows === null ? <Skeleton style={{ height: 200 }} /> :
       rows.length === 0 ? <EmptyState icon={ClipboardList} title="No timesheets yet" /> :
       <table className="w-full text-sm" data-testid="timesheets-table">
         <thead><tr style={{ backgroundColor: colors.surfaceSecondary }}>
           <th className="text-left px-2 py-2 font-semibold">Tech</th>
           <th className="text-left px-2 py-2 font-semibold">Date</th>
           <th className="text-right px-2 py-2 font-semibold">Hours</th>
           <th className="text-right px-2 py-2 font-semibold">Review</th>
           <th className="text-right px-2 py-2 font-semibold">Actions</th>
         </tr></thead>
         <tbody>{rows.map((r) => (
           <tr key={r.id} style={{ borderTop: `1px solid ${colors.divider}` }}>
             <td className="px-2 py-2">{r.technician_name || r.technician_id?.slice(0, 6)}</td>
             <td className="px-2 py-2">{r.date}</td>
             <td className="px-2 py-2 text-right">{r.hours ?? "—"}</td>
             <td className="px-2 py-2 text-right"><Chip label={r.review_status || "pending"} tone={r.review_status === "approved" ? "success" : r.review_status === "disputed" ? "danger" : "neutral"} /></td>
             <td className="px-2 py-2 text-right">
               <button onClick={() => act(r.id, "approve")} className="text-xs font-semibold mr-2" style={{ color: colors.success }} data-testid={`ts-approve-${r.id}`}>Approve</button>
               <button onClick={() => act(r.id, "dispute")} className="text-xs font-semibold" style={{ color: colors.error }}>Dispute</button>
             </td>
           </tr>
         ))}</tbody>
       </table>}
      <Toast toast={toast} onClose={() => setToast(null)} />
    </Card>
  );
}

/* ═══════════ Timeclock ═══════════ */
function Timeclock() {
  const [data, setData] = useState(null);
  const load = () => api.get("/timeclock/today").then(setData).catch(() => setData({ rows: [] }));
  useEffect(() => { load(); }, []);
  return (
    <Card testid="timeclock-page">
      {!data ? <Skeleton style={{ height: 160 }} /> :
       <ul className="space-y-2">{(data.rows || []).map((r) => (
         <li key={r.technician_id} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary }} data-testid={`tc-${r.technician_id}`}>
           <span className={`w-2 h-2 rounded-full`} style={{ backgroundColor: r.clocked_in ? colors.success : r.clocked_out ? colors.muted : colors.borderStrong }} />
           <div className="flex-1"><div className="font-semibold text-sm">{r.technician_name}</div><div className="text-xs" style={{ color: colors.muted }}>{r.clocked_in ? `Clocked in @ ${r.clock_in_at?.slice(11, 16)}` : r.clocked_out ? `Clocked out · ${r.hours}h` : "Not clocked in"}</div></div>
         </li>
       ))}</ul>}
    </Card>
  );
}

/* ═══════════ Coverage / Maintenance / Pool ═══════════ */
function Coverage() { return <SimplePage endpoint="/coverage/active" title="Coverage" empty="No active coverage" render={(r) => r.route || r.name || r.id} />; }
function Maintenance() {
  const [ov, setOv] = useState(null);
  useEffect(() => { api.get("/maintenance/overview").then(setOv).catch(() => setOv({})); }, []);
  return (
    <Card testid="maintenance-page">
      {!ov ? <Skeleton style={{ height: 120 }} /> :
       <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
         <MetaTile label="Due this week" value={ov.due_this_week ?? 0} />
         <MetaTile label="Overdue" value={ov.overdue ?? 0} tone={colors.error} />
         <MetaTile label="Scheduled" value={ov.scheduled ?? 0} />
         <MetaTile label="Chemistry alerts" value={ov.chemistry_alerts ?? 0} />
       </div>}
    </Card>
  );
}
function PoolService() { return <SimplePage endpoint="/maintenance/records" title="Pool service records" empty="No records" render={(r) => `${r.customer_name || r.customer_id} — ${r.date || r.at}`} />; }
function MetaTile({ label, value, tone }) {
  return (<div className="rounded-xl p-3" style={{ backgroundColor: colors.surfaceSecondary }}>
    <div className="text-xs uppercase font-semibold" style={{ color: tone || colors.muted }}>{label}</div>
    <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>{value}</div></div>);
}

/* ═══════════ Equipment (with requests) ═══════════ */
function Equipment() {
  const [tab, setTab] = useState("requests");
  const [reqs, refresh] = useList("/equipment-requests");
  const [toast, setToast] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [form, setForm] = useState({ equipment_type: "", issue: "", priority: "normal" });
  const act = async (rid, action, extra) => { try { await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/equipment-requests/${rid}`, { method: "PATCH", headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("token")}` }, body: JSON.stringify({ action, ...(extra || {}) }) }); refresh(); setToast({ tone: "success", message: action }); } catch (e) { setToast({ tone: "error", message: e.message }); } };
  const create = async () => { try { await api.post("/equipment-requests", form); setAddOpen(false); setForm({ equipment_type: "", issue: "", priority: "normal" }); refresh(); } catch (e) { setToast({ tone: "error", message: e.message }); } };
  return (
    <Card testid="equipment-page">
      <div className="flex justify-between mb-3">
        <div className="flex gap-2">
          <button onClick={() => setTab("requests")} className="text-xs font-semibold px-3 py-1 rounded-full" style={{ backgroundColor: tab === "requests" ? colors.brandTertiary : colors.surfaceSecondary }}>Requests</button>
        </div>
        <Button variant="ghost" onClick={() => setAddOpen(true)} testid="eq-new">
          <Plus size={14} /> New request
        </Button>
      </div>
      {reqs === null ? <Skeleton style={{ height: 160 }} /> :
       reqs.length === 0 ? <EmptyState icon={Wrench} title="No requests" /> :
       <ul className="space-y-2">{reqs.map((r) => (
         <li key={r.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary }} data-testid={`eq-${r.id}`}>
           <div className="flex-1"><div className="font-semibold text-sm">{r.equipment_type}</div><div className="text-xs" style={{ color: colors.muted }}>{r.issue}</div></div>
           <Chip label={r.status} tone={r.status === "approved" ? "success" : r.status === "rejected" ? "danger" : "warning"} />
           {r.status === "pending" ? <>
             <button onClick={() => act(r.id, "approve", { cost_estimate: 0 })} className="text-xs font-semibold" style={{ color: colors.success }} data-testid={`eq-approve-${r.id}`}>Approve</button>
             <button onClick={() => act(r.id, "reject", { reason: "n/a" })} className="text-xs font-semibold" style={{ color: colors.error }}>Reject</button>
           </> : null}
         </li>
       ))}</ul>}
      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="New equipment request"
        footer={<><Button variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button><Button onClick={create}>Create</Button></>}>
        <div className="space-y-2">
          <TextInput label="EQUIPMENT TYPE" value={form.equipment_type} onChange={(e) => setForm({ ...form, equipment_type: e.target.value })} />
          <TextInput label="ISSUE" value={form.issue} onChange={(e) => setForm({ ...form, issue: e.target.value })} />
        </div>
      </Modal>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </Card>
  );
}

/* ═══════════ Price Book ═══════════ */
function PriceBook() {
  const [rows, refresh] = useList("/items");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ name: "", category: "Pool", unit: "each", unit_price: 0 });
  const [toast, setToast] = useState(null);
  const save = async () => { try { await api.post("/items", { ...form, unit_price: Number(form.unit_price) || 0 }); setOpen(false); refresh(); } catch (e) { setToast({ tone: "error", message: e.message }); } };
  return (
    <Card testid="pricebook-page">
      <div className="flex justify-between mb-3">
        <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>Items · {(rows || []).length}</div>
        <Button onClick={() => setOpen(true)} testid="pb-new"><Plus size={14} /> New item</Button>
      </div>
      {rows === null ? <Skeleton style={{ height: 160 }} /> :
       <ul className="divide-y" style={{ borderColor: colors.divider }}>
         {rows.map((r) => (<li key={r.id} className="py-2 flex items-center gap-3"><div className="flex-1"><div className="text-sm font-semibold">{r.name}</div><div className="text-xs" style={{ color: colors.muted }}>{r.category} · {r.unit}</div></div><div className="font-semibold">{money(r.unit_price)}</div></li>))}
       </ul>}
      <Modal open={open} onClose={() => setOpen(false)} title="New item"
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={save}>Save</Button></>}>
        <div className="space-y-2">
          <TextInput label="NAME" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <TextInput label="CATEGORY" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
          <TextInput label="UNIT" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} />
          <TextInput label="UNIT PRICE" type="number" step="0.01" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} />
        </div>
      </Modal>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </Card>
  );
}

/* ═══════════ Log history / Job Timers / Avg Job Time ═══════════ */
function LogHistory() {
  const [rows] = useList("/jobs");
  const completed = (rows || []).filter((j) => j.status === "completed").slice(0, 100);
  return (
    <Card testid="loghistory-page">
      {rows === null ? <Skeleton style={{ height: 160 }} /> :
       completed.length === 0 ? <EmptyState icon={History} title="No completed jobs yet" /> :
       <ul className="space-y-1 text-sm">{completed.map((j) => (
         <li key={j.id} className="flex items-center gap-3 p-2 rounded-lg" style={{ borderBottom: `1px solid ${colors.divider}` }}>
           <div className="flex-1"><div className="font-semibold">{j.title}</div><div className="text-xs" style={{ color: colors.muted }}>{j.customer_name} · {j.completed_at || j.scheduled_date}</div></div>
           <StatusPill status={j.status} />
         </li>))}</ul>}
    </Card>
  );
}
function JobTimers() { return <SimplePage endpoint="/jobs" title="Active timers" empty="No active timers" filter={(j) => j.status === "active" && j.timer_started_at} render={(j) => `${j.title} — ${j.technician_name} — started ${j.timer_started_at}`} />; }
function AvgJobTime() {
  const [rows] = useList("/jobs");
  const done = (rows || []).filter((j) => j.status === "completed" && j.duration_minutes);
  const byType = {};
  done.forEach((j) => { const k = j.service_type || "Other"; if (!byType[k]) byType[k] = []; byType[k].push(j.duration_minutes); });
  return (
    <Card testid="avgtime-page">
      {rows === null ? <Skeleton style={{ height: 160 }} /> :
       Object.keys(byType).length === 0 ? <EmptyState icon={BarChart3} title="Not enough data yet" hint="Once jobs have duration_minutes stamped, we'll compute averages here." /> :
       <ul className="space-y-2">{Object.entries(byType).map(([k, v]) => (
         <li key={k} className="p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary }}>
           <div className="text-sm font-semibold">{k}</div>
           <div className="text-xs" style={{ color: colors.muted }}>Avg {Math.round(v.reduce((s, x) => s + x, 0) / v.length)} min · {v.length} jobs</div>
         </li>))}</ul>}
    </Card>
  );
}

/* ═══════════ Compact list helper ═══════════ */
function SimplePage({ endpoint, title, empty, render, filter }) {
  const [rows] = useList(endpoint);
  const filtered = filter ? (rows || []).filter(filter) : (rows || []);
  return (
    <Card>
      {rows === null ? <Skeleton style={{ height: 160 }} /> :
       filtered.length === 0 ? <EmptyState title={empty} /> :
       <ul className="space-y-1 text-sm">{filtered.slice(0, 100).map((r, i) => (
         <li key={r.id || i} className="p-2 rounded-lg" style={{ borderBottom: `1px solid ${colors.divider}` }}>{render(r)}</li>
       ))}</ul>}
    </Card>
  );
}
