import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Users2, Truck, Route, Wrench, ClipboardList, Timer, Clock, Calendar, Activity, Waves, Package, History, BarChart3, Plus, Trash2, RefreshCw, MapPin, ChevronRight, Link2, Share2, MoreVertical, KeyRound, Eye, EyeOff, Copy as CopyIcon, Undo2, ShieldAlert, Loader2, DollarSign } from "lucide-react";
import { api } from "@/api";
import { SUPPLIER_METADATA } from "@/pages/settings/supplier_metadata";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { colors, money, brandGradientCss } from "@/theme";
import { useAuth } from "@/auth";
import { usePermissions } from "@/hooks/usePermissions";
import { PageHeader, Button, Skeleton, StatusPill, Chip, EmptyState, TextInput, Modal, Toast } from "@/components/ui-kit";
import { useAttendance } from "@/hooks/useAttendance";
import WorkstreamJobDrawer from "@/pages/ops/WorkstreamJobDrawer";

/* ═══ Ops hub – one page, many tabs. Kept compact by construction. ═══ */


// Feb-2026 · Crew color-picker presets. 12 hand-picked hues that stay
// legible on both light and dark theme surfaces. Users can still paste
// an arbitrary hex via the fallback text input.
const CREW_COLOR_PRESETS = [
  "#0284C7", "#7C3AED", "#DB2777", "#DC2626",
  "#EA580C", "#CA8A04", "#16A34A", "#059669",
  "#0891B2", "#4338CA", "#475569", "#0F766E",
];

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
  // Phase 22 · Feb 2026 — Menu Route fallback. When the caller lands
  // on a dedicated path like ``/team`` or ``/crews`` without an
  // explicit ``?t=…`` query, fall back to a tab derived from the
  // pathname's first segment. Keeps external / bookmarked links honest
  // and matches the sidebar semantics (``/team?t=team`` etc).
  const pathTab = (() => {
    const seg = (typeof window !== "undefined" && window.location.pathname
                    ? window.location.pathname.split("/").filter(Boolean)[0]
                    : "") || "";
    const KNOWN = new Set([
      "dispatch", "schedule", "routes", "workstream", "crews", "team",
      "timesheets", "timeclock", "coverage", "maintenance",
      "equipment", "pricebook", "loghistory", "timers", "avgtime",
    ]);
    return KNOWN.has(seg) ? seg : "";
  })();
  const tab = params.get("t") || pathTab || "dispatch";
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
  const [_crews] = useList("/crews");
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
  const [routeMeta, setRouteMeta] = useState({ tech_name: null, tech_color_hex: null });
  const [toast, setToast] = useState(null);
  const load = async () => {
    // Feb-2026 · Routes tab wiring · when a specific tech is selected,
    // use the enrichment endpoint (single call, tech name + color
    // baked into the response, deleted-customer address fallback).
    // "All techs" keeps the legacy /jobs client-filter path.
    if (techId) {
      const r = await api.get(`/routes/${techId}/stops?date=${date}`).catch(() => null);
      if (r) {
        const mapped = (r.stops || []).map((s) => ({
          id: s.job_id,
          title: s.title,
          // Ops Routes bug-fix · Feb-2026 — keep the RAW field names so
          // the render fallback chain can walk them explicitly instead
          // of collapsing everything into `customer_name` (which used
          // to shadow real customer identity with an address).
          customer_display_name: s.customer_display_name || null,
          customer_name: s.customer_name || null,
          billing_name: s.billing_name || null,
          service_address: s.service_address || null,
          technician_name: r.tech_name || null,
          technician_color_hex: r.tech_color_hex || null,
          address: s.address,
          scheduled_date: date,
          route_order: s.route_order ?? 999,
          status: s.status,
        })).sort((a, b) => a.route_order - b.route_order);
        setRouteMeta({ tech_name: r.tech_name, tech_color_hex: r.tech_color_hex });
        setOrder(mapped);
        return;
      }
    }
    setRouteMeta({ tech_name: null, tech_color_hex: null });
    const j = await api.get("/jobs").catch(() => []);
    const filtered = (j || []).filter((x) => (x.scheduled_date || "").startsWith(date) && (!techId || x.technician_id === techId));
    filtered.sort((a, b) => (a.route_order ?? 999) - (b.route_order ?? 999));
    setOrder(filtered);
  };
  useEffect(() => { load(); }, [techId, date]); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps
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
       <ol className="space-y-2">{order.map((j, i) => {
         // Feb-2026 · Ops Routes bug-fix — customer name is the primary
         // line. Fallback chain per user spec:
         //   customer_display_name → customer_name → billing_name →
         //   service_address → "(no customer)".
         // Title stays SECONDARY (with address). Fixes the tester
         // screenshot where "Weekly Pool Cleaning" was rendering as
         // the bold primary line.
         const primary = (
           j.customer_display_name
           || j.customer_name
           || j.billing_name
           || j.service_address
           || "(no customer)"
         ).toString().trim();
         const secondary = j.title || j.service_type || "";
         const techLabel = j.technician_name || "Unassigned";
         const techColor = j.technician_color_hex || null;
         return (
         <li key={j.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ backgroundColor: colors.surfaceSecondary }} data-testid={`route-${j.id}`}>
           <span className="w-6 h-6 rounded-full text-xs font-bold flex items-center justify-center" style={{ background: brandGradientCss, color: "#fff" }}>{i + 1}</span>
           <div className="flex-1">
             <div className="font-semibold text-sm"
                  data-testid={`ops-route-${j.id}-customer`}>
               {primary}
             </div>
             <div className="text-xs flex items-center gap-1.5" style={{ color: colors.muted }}>
               {techColor ? (
                 <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: techColor }} aria-hidden="true" />
               ) : null}
               <span data-testid={`route-${j.id}-tech`}>{techLabel}</span>
               {secondary ? (<><span>·</span><span>{secondary}</span></>) : null}
               <span>·</span>
               <span>{j.address || "—"}</span>
             </div>
           </div>
           <button onClick={() => move(i, -1)} className="opacity-70">↑</button>
           <button onClick={() => move(i, 1)} className="opacity-70">↓</button>
           <a target="_blank" rel="noreferrer" href={`https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(j.address || "")}`} className="text-xs font-semibold" style={{ color: colors.brand }}>Navigate</a>
         </li>
         );
       })}</ol>}
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
  const [wsToast, setWsToast] = useState("");
  const [params, setParams] = useSearchParams();
  const { can } = usePermissions();

  const showToast = (t) => { setWsToast(t); setTimeout(() => setWsToast(""), 2600); };

  // On mount / when ?open= changes, auto-open the corresponding drawer/modal.
  useEffect(() => {
    const open = params.get("open");
    if (!open) {
      setDrawerJobId(null);
      setPaymentInfo(null);
      return;
    }
    const [type, id] = open.split(":");
    if (!type || !id) return;
    if (type === "job") {
      if (can && can("jobs", "read") === false) {
        showToast("You don't have permission to view this activity");
        _mergeParams({ open: null }, { replace: true });
        setTimeout(() => navigate("/"), 800);
        return;
      }
      setDrawerJobId(id);
    } else if (type === "payment" || type === "review") {
      // Compact info modal — try to find the row in the current feed for context.
      const match = (rows || []).find((r) => r?.related_ref?.type === type && r?.related_ref?.id === id);
      setPaymentInfo(match || { title: type === "payment" ? "Payment" : "Review", detail: `#${id.slice(0, 8)}`, at: "" });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params, rows]);

  const _mergeParams = (patch, opts) => {
    const s = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => {
      if (v === null || v === undefined || v === "") s.delete(k);
      else s.set(k, v);
    });
    setParams(s, opts);
  };

  const openRow = (a) => {
    const ref = a.related_ref || {};
    const t = ref.type;
    const id = ref.id;
    if (!t || !id) return;
    if (t === "job") {
      setDrawerJobId(id);
      _mergeParams({ open: `job:${id}` });
    } else if (t === "invoice") navigate(`/invoices/${id}`);
    else if (t === "quote") navigate(`/quotes/${id}`);
    else if (t === "customer") navigate(`/customers/${id}`);
    else if (t === "communication") navigate(`/communication/${id}`);
    else if (t === "payment") {
      setPaymentInfo({ ...a });
      _mergeParams({ open: `payment:${id}` });
    } else if (t === "review") {
      setPaymentInfo({ ...a });
      _mergeParams({ open: `review:${id}` });
    } else if (t === "lead") navigate(`/leads`);
  };

  const closeDrawer = () => {
    setDrawerJobId(null);
    _mergeParams({ open: null });
  };
  const closeModal = () => {
    setPaymentInfo(null);
    _mergeParams({ open: null });
  };

  const shareCurrent = async () => {
    const url = window.location.href;
    if (navigator.share) {
      try { await navigator.share({ title: paymentInfo?.title || "Activity", url }); return; } catch {}
    }
    try {
      await navigator.clipboard.writeText(url);
      showToast("Link copied — anyone with access can view this activity");
    } catch { showToast("Could not copy link"); }
  };

  const copyCurrent = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      showToast("Link copied — anyone with access can view this activity");
    } catch { showToast("Could not copy link"); }
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
        <WorkstreamJobDrawer
          jobId={drawerJobId}
          onClose={closeDrawer}
          onShareToast={showToast}
          onPermissionDenied={() => {
            showToast("You don't have permission to view this activity");
            setDrawerJobId(null);
            _mergeParams({ open: null }, { replace: true });
            setTimeout(() => navigate("/"), 800);
          }}
        />
      )}
      {paymentInfo && (
        <Modal open onClose={closeModal}
               title={paymentInfo.title || "Details"}
               footer={<>
                 <Button variant="ghost" onClick={copyCurrent} testid="ws-info-copy">
                   <Link2 size={12} /> Copy link
                 </Button>
                 <Button variant="ghost" onClick={shareCurrent} testid="ws-info-share">
                   <Share2 size={12} /> Share
                 </Button>
                 <Button onClick={closeModal}>Close</Button>
               </>}>
          <div className="space-y-2 text-sm" data-testid="workstream-info-modal">
            <div style={{ color: colors.onSurface }}>{paymentInfo.detail}</div>
            <div className="text-xs" style={{ color: colors.muted }}>{paymentInfo.at}</div>
          </div>
        </Modal>
      )}
      {wsToast && (
        <div className="fixed bottom-6 right-6 z-[70] px-4 py-2 rounded-xl text-sm text-white shadow-lg"
             style={{ backgroundColor: colors.onSurface }}
             data-testid="workstream-toast">
          {wsToast}
        </div>
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
    // Feb-2026 · Crew-save P0 fix. The prior implementation did TWO
    // things: (1) ``api.put('/crews/…')`` inside a try/except that
    // silently swallowed the 405 (no PUT route on the backend), and
    // (2) a raw ``fetch(..., PATCH)`` that DOESN'T throw on 4xx/5xx —
    // so a server-side rejection surfaced as a false "Saved" toast
    // and the members never landed. Use ``api.patch`` which routes
    // through the standard ``request()`` wrapper (throws on ≥400) so
    // failures now surface as red toasts and successes actually
    // round-trip.
    try {
      if (editing) {
        await api.patch(`/crews/${editing.id}`, form);
      } else {
        await api.post("/crews", form);
      }
      setOpen(false); refresh();
      setToast({ tone: "success", message: "Saved" });
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  const del = async (cid) => {
    const ok = await mustConfirm({
      title: "Delete this crew?",
      description: "Jobs assigned to this crew will be unassigned. Techs remain intact.",
      tone: "danger", confirmText: "Delete",
    });
    if (!ok) return;
    try { await api.del(`/crews/${cid}`); refresh(); } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
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
          {/* Feb-2026 · Crew color picker parity with Team members.
              12-swatch grid + hex fallback. No new deps — same
              pattern as ``ColorSwatchInline`` for users. Backend
              ``crews.color`` already exists in the schema. */}
          <div>
            <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>COLOR</div>
            <div className="flex flex-wrap gap-2 mb-2" data-testid="crew-color-swatches">
              {CREW_COLOR_PRESETS.map((hex) => {
                const active = (form.color || "").toUpperCase() === hex.toUpperCase();
                return (
                  <button key={hex} type="button" onClick={() => setForm({ ...form, color: hex })}
                          data-testid={`crew-color-swatch-${hex.slice(1).toLowerCase()}`}
                          aria-label={`Set crew color ${hex}`}
                          className="w-6 h-6 rounded-full transition-transform"
                          style={{ backgroundColor: hex,
                                    outline: active ? `2px solid ${colors.onSurface}` : "none",
                                    outlineOffset: "2px" }} />
                );
              })}
            </div>
            <TextInput label="HEX (custom)" value={form.color}
                        onChange={(e) => setForm({ ...form, color: e.target.value })}
                        testid="crew-color-hex" />
          </div>
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
// Phase 56.3.B / 56.3.C — canonical 4-option Role picker.
// Mirrors backend `_ROLE_DEPT_COMBOS` in `routers/team.py`. Any drift must
// be a synchronous change in both places.
const ROLE_OPTIONS = [
  { value: "pool_tech",       label: "Pool Tech",       role: "technician", department: "pool",
    badgeBg: "#DBEAFE", badgeFg: "#1E3A8A", filterColor: "#1E3A8A" },
  { value: "landscape_tech",  label: "Landscape Tech",  role: "technician", department: "landscaping",
    badgeBg: "#DCFCE7", badgeFg: "#166534", filterColor: "#166534" },
  // Feb-2026 · Cross-trained tech (pool + landscape). Non-admin — this
  // is distinct from the admin+both "All" combo below (which grants
  // admin RBAC plus dual tech surface). Backend combo enum:
  // ("technician","both") = "Tech (Both)" — see routers/team.py.
  { value: "tech_both",       label: "Tech (Both)",     role: "technician", department: "both",
    badgeBg: "#CCFBF1", badgeFg: "#0F766E", filterColor: "#0F766E" },
  { value: "admin",           label: "Admin",           role: "admin",      department: null,
    badgeBg: "#F3E8FF", badgeFg: "#6B21A8", filterColor: "#6B21A8" },
  // Feb-2026 · Relabelled from the terse "All" — matches the backend
  // canonical label `_ROLE_DEPT_COMBOS[("admin","both")]` verbatim so
  // there is no drift between the picker chip, the badge, the toast
  // and the audit log.
  { value: "all",             label: "All (Admin + Pool + Landscape)", role: "admin", department: "both",
    badgeBg: "#FEF3C7", badgeFg: "#92400E", filterColor: "#92400E" },
];

function _roleKey(user) {
  const role = (user?.role || "").toLowerCase();
  const dept = (user?.department || "").toLowerCase();
  if (role === "super_admin") return "super_admin";
  if (role === "admin" && dept === "both") return "all";
  if (role === "admin") return "admin";
  // Feb-2026 · cross-trained tech comes BEFORE the single-dept checks
  // so a stored `technician + both` row resolves to the new
  // "Tech (Both)" combo instead of falling through to "unassigned".
  if (role === "technician" && dept === "both") return "tech_both";
  if (role === "technician" && dept === "pool") return "pool_tech";
  if (role === "technician" && dept === "landscaping") return "landscape_tech";
  return "unassigned";
}


function TeamRoster() {
  const { user: me } = useAuth();
  // Phase-Team · Feb-2026 — super_admin-only "Show deleted" toggle that
  // flips the roster query to include soft-deleted rows.
  const [showDeleted, setShowDeleted] = useState(false);
  const [rows, refresh] = useList(
    showDeleted ? "/team?include_deleted=true" : "/team",
    [showDeleted],
  );
  const [filter, setFilter] = useState("all");
  const [savingId, setSavingId] = useState(null);
  const [toast, setToast] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [tempPasswordShown, setTempPasswordShown] = useState(null); // { email, password }
  // Phase-Team · Feb-2026 — kebab-menu dialog targets.
  const [resetTarget, setResetTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const myRole = (me?.role || "").toLowerCase();
  const isAdmin = myRole === "admin" || myRole === "super_admin";
  const isSuperAdmin = myRole === "super_admin";

  const filtered = useMemo(() => {
    if (!rows) return null;
    return rows.filter((r) => {
      const k = _roleKey(r);
      if (filter === "all") return true;
      if (filter === "unassigned") return k === "unassigned";
      // Feb-2026 · P1 fix — the "All (Both)" chip's filter key was
      // ``all_both`` but ``_roleKey`` never returns that string
      // (roles are ``pool_tech`` / ``landscape_tech`` / ``tech_both``
      // for techs, and ``all`` for the admin+both edge case). The
      // old ``k === filter`` fallback silently returned ``[]``.
      // Per product intent — "All (Both)" surfaces every tech
      // regardless of specialty, matching the modern department
      // enum semantics.
      if (filter === "all_both") {
        return k === "pool_tech" || k === "landscape_tech" || k === "tech_both";
      }
      return k === filter;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, filter]);

  const applyRole = async (u, optValue) => {
    const opt = ROLE_OPTIONS.find((o) => o.value === optValue);
    if (!opt) return;
    setSavingId(u.id);
    try {
      await api.patch(`/users/${u.id}`, { role: opt.role, department: opt.department });
      setToast({ tone: "success", message: `${u.name || u.email} → ${opt.label}` });
      refresh();
    } catch (e) {
      setToast({ tone: "error", message: e?.message || "Failed to update" });
    } finally {
      setSavingId(null);
    }
  };

  // Phase 21 · Feb 2026 · Addition B — display color PATCH. Optimistic
  // in the picker component; this handler is the source of truth for
  // the toast + refresh cycle.
  const applyColor = async (u, hex) => {
    try {
      await api.patch(`/users/${u.id}`, { display_color_hex: hex });
      setToast({
        tone: "success",
        message: hex ? `Color set for ${u.name || u.email}` : `Color cleared for ${u.name || u.email}`,
      });
      refresh();
    } catch (e) {
      setToast({ tone: "error", message: e?.message || "Failed to update color" });
      throw e; // let the popover know to revert its optimistic state
    }
  };

  // Feb-2026 · web-side companion to the mobile Clock-In screen. Admin
  // toggles ``users.auto_clockin_enabled`` on any technician row. The
  // switch renders read-only on non-technician rows (there's nothing to
  // clock into) but stays visible for parity so the UI never surprises
  // an admin looking for the control. Optimistic — the parent list is
  // refreshed on success and a toast surfaces failures without rolling
  // back the row visually (rare, and refresh will re-sync anyway).
  const applyAutoClockin = async (u, nextVal) => {
    try {
      await api.patch(`/users/${u.id}`, { auto_clockin_enabled: !!nextVal });
      setToast({
        tone: "success",
        message: `Auto clock-in ${nextVal ? "on" : "off"} for ${u.name || u.email}`,
      });
      refresh();
    } catch (e) {
      setToast({ tone: "error", message: e?.message || "Failed to update auto clock-in" });
      throw e;
    }
  };

  const _CHIPS = [
    { key: "all",            label: "All roles" },
    { key: "pool_tech",      label: "Pool Tech" },
    { key: "landscape_tech", label: "Landscape Tech" },
    { key: "admin",          label: "Admin" },
    { key: "all",            label: "All (Both)", altKey: "all_admin_both" }, // note: intentional duplicate label — filter still "all"
    { key: "unassigned",     label: "Unassigned" },
  ];
  // Deduplicate: the "All (Both)" chip filters by `all_admin_both` (custom
  // key). We fix that below to filter to `admin+both` only.
  const _CHIPS_FIXED = [
    { key: "all",            label: "All roles" },
    { key: "pool_tech",      label: "Pool Tech" },
    { key: "landscape_tech", label: "Landscape Tech" },
    { key: "admin",          label: "Admin" },
    { key: "all",            label: "All (Both)" }, // handled via roleKey === "all"
    { key: "unassigned",     label: "Unassigned" },
  ];

  return (
    <Card testid="team-page">
      {/* Header row — filter chips (left) + Add Team Member (right). */}
      <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap" data-testid="team-filter-row">
          {[
            { key: "all",            label: "All roles" },
            { key: "pool_tech",      label: "Pool Tech" },
            { key: "landscape_tech", label: "Landscape Tech" },
            // Feb-2026 · cross-trained tech filter chip. Filters rows
            // whose `_roleKey()` returns "tech_both" — the base
            // `filtered` useMemo above already handles `k === filter`
            // for any non-special key, so no sub-filter needed.
            { key: "tech_both",      label: "Tech (Both)" },
            { key: "admin",          label: "Admin" },
            { key: "all_both",       label: "All (Both)" },
            { key: "unassigned",     label: "Unassigned" },
          ].map((c) => {
            // "All roles" (`all`) shows everything. "All (Both)" is a distinct
            // chip that filters to admin+both only — we internally use key
            // `all_both` and remap to the roleKey `all`.
            const active = filter === c.key || (c.key === "all_both" && filter === "all_both");
            return (
              <button
                key={`${c.key}-${c.label}`}
                onClick={() => setFilter(c.key)}
                className="text-xs font-semibold px-2.5 py-1 rounded-full border transition"
                style={{
                  borderColor: active ? colors.brand : colors.border,
                  backgroundColor: active ? colors.brand : "transparent",
                  color: active ? "#fff" : colors.onSurface,
                }}
                data-testid={`team-filter-${c.key}`}
              >
                {c.label}
              </button>
            );
          })}
        </div>
        {isAdmin ? (
          <div className="flex items-center gap-2">
            {isSuperAdmin ? (
              <label
                className="flex items-center gap-1.5 text-xs font-semibold cursor-pointer select-none"
                style={{ color: colors.onSurface }}
                data-testid="team-show-deleted-label"
              >
                <input
                  type="checkbox"
                  checked={showDeleted}
                  onChange={(e) => setShowDeleted(e.target.checked)}
                  data-testid="team-show-deleted-toggle"
                />
                Show deleted
              </label>
            ) : null}
            <Button onClick={() => setAddOpen(true)} testid="team-add-btn">
              <Plus size={14} /> Add Team Member
            </Button>
          </div>
        ) : null}
      </div>

      {filtered === null ? (
        <Skeleton style={{ height: 160 }} />
      ) : filtered.length === 0 ? (
        <EmptyState title="No team members" />
      ) : (
        <ul className="space-y-2">
          {filtered
            .filter((r) => {
              if (filter === "all_both") return _roleKey(r) === "all";
              return true;
            })
            .map((r) => {
              const key = _roleKey(r);
              const opt = ROLE_OPTIONS.find((o) => o.value === key);
              // super_admin — read-only chip, no dropdown.
              const isSuper = key === "super_admin";
              // Self-demotion protection — hide the dropdown on the caller's row.
              const isSelf = r.id === me?.id;
              const isDeleted = !!r.deleted_at;
              const targetRole = (r.role || "").toLowerCase();
              const targetIsTech = targetRole === "technician";
              // Phase-Team · Feb-2026 — kebab-menu permission matrix.
              // Frontend hides items the caller can't act on; the backend
              // re-enforces every check so a hand-crafted request still 403s.
              const canReset = !isSelf && !isDeleted && (
                isSuperAdmin ? true
                : myRole === "admin" ? targetIsTech
                : false);
              const canDelete = !isSelf && !isDeleted && (
                isSuperAdmin ? true
                : myRole === "admin" ? targetIsTech
                : false);
              const canUndelete = isSuperAdmin && isDeleted;
              const anyKebab = canReset || canDelete || canUndelete;
              return (
                <li
                  key={r.id}
                  className="flex items-center gap-3 p-3 rounded-xl"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    opacity: isDeleted ? 0.55 : 1,
                  }}
                  data-testid={`team-row-${r.id}`}
                >
                  <div
                    className="w-9 h-9 rounded-full flex items-center justify-center text-white font-bold"
                    style={{ background: brandGradientCss }}
                  >
                    {(r.name || "?")[0]}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold truncate">
                      {r.name || r.email || "—"}
                      {isSelf ? <span className="text-xs ml-1" style={{ color: colors.muted }}>(you)</span> : null}
                      {isDeleted ? (
                        <span
                          className="text-[9px] ml-2 uppercase font-bold px-1.5 py-0.5 rounded"
                          style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                          data-testid={`team-row-deleted-badge-${r.id}`}
                        >
                          Deleted
                        </span>
                      ) : null}
                    </div>
                    <div className="text-xs" style={{ color: colors.muted }}>{r.email || ""}</div>
                  </div>

                  {/* Phase 21 · Feb 2026 · Addition B — display color swatch.
                      Admin can click to open a compact popover, pick a
                      hex, and PATCH `users.display_color_hex`. Non-admin
                      viewers see the swatch read-only. */}
                  <TechColorSwatch
                    user={r}
                    editable={isAdmin && !isSuper}
                    onChange={(hex) => applyColor(r, hex)}
                  />

                  {/* Feb-2026 · Team page Auto Clock-In toggle. Admin flips
                      ``users.auto_clockin_enabled`` for technician rows;
                      non-tech rows render an inert dash so the column
                      still aligns across the roster. Hidden entirely on
                      the caller's own row so admins toggle their prefs
                      via the mobile Clock-In screen instead. */}
                  <TechAutoClockinToggle
                    user={r}
                    editable={isAdmin && !isSuper && !isSelf}
                    onChange={(nextVal) => applyAutoClockin(r, nextVal)}
                  />

                  {/* Colored role badge (always visible). */}
                  {opt ? (
                    <span
                      className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded"
                      style={{ backgroundColor: opt.badgeBg, color: opt.badgeFg }}
                      data-testid={`team-role-badge-${r.id}`}
                    >
                      {opt.label}
                    </span>
                  ) : isSuper ? (
                    <span
                      className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded"
                      style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
                      data-testid={`team-role-badge-${r.id}`}
                    >
                      Super Admin
                    </span>
                  ) : (
                    <span
                      className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded"
                      style={{ backgroundColor: "#F3F4F6", color: colors.muted }}
                      data-testid={`team-role-badge-${r.id}`}
                    >
                      Unassigned
                    </span>
                  )}

                  {/* Role dropdown — hidden for super_admin and self. */}
                  {isAdmin && !isSuper && !isSelf && !isDeleted ? (
                    <select
                      value={opt?.value || ""}
                      onChange={(e) => applyRole(r, e.target.value)}
                      disabled={savingId === r.id}
                      className="text-xs rounded px-1 py-0.5 border"
                      style={{
                        borderColor: colors.border,
                        backgroundColor: "#fff",
                        color: colors.onSurface,
                        opacity: savingId === r.id ? 0.6 : 1,
                      }}
                      data-testid={`team-role-select-${r.id}`}
                    >
                      <option value="">— Choose role —</option>
                      {ROLE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  ) : null}

                  {/* Phase-Team · Feb-2026 — kebab menu for admin actions.
                      Rendered only when the caller can act on this row
                      per the permission matrix. Undelete is super_admin only
                      and only surfaces on soft-deleted rows. */}
                  {anyKebab ? (
                    <TeamRowKebab
                      row={r}
                      canReset={canReset}
                      canDelete={canDelete}
                      canUndelete={canUndelete}
                      onReset={() => setResetTarget(r)}
                      onDelete={() => setDeleteTarget(r)}
                      onUndelete={async () => {
                        try {
                          await api.post(`/users/${r.id}/undelete`, {});
                          setToast({ tone: "success",
                                       message: `Restored ${r.name || r.email}` });
                          refresh();
                        } catch (e) {
                          setToast({ tone: "error",
                                       message: e?.message || "Undelete failed" });
                        }
                      }}
                    />
                  ) : null}
                </li>
              );
            })}
        </ul>
      )}

      {/* Phase-Team · Feb-2026 — reset password + delete confirm dialogs. */}
      <ResetPasswordDialog
        target={resetTarget}
        onClose={() => setResetTarget(null)}
        onDone={(msg) => {
          setResetTarget(null);
          setToast({ tone: "success", message: msg });
          refresh();
        }}
        onError={(msg) => setToast({ tone: "error", message: msg })}
      />
      <DeleteTeamMemberDialog
        target={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDone={(name) => {
          setDeleteTarget(null);
          setToast({ tone: "success", message: `Removed ${name}` });
          refresh();
        }}
        onError={(msg) => setToast({ tone: "error", message: msg })}
      />

      <AddTeamMemberModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={(res) => {
          setAddOpen(false);
          refresh();
          if (res?.temp_password) {
            setTempPasswordShown({ email: res.email, password: res.temp_password });
          } else {
            setToast({ tone: "success", message: `Team member ${res?.email || "added"}` });
          }
        }}
        onError={(msg) => setToast({ tone: "error", message: msg })}
      />

      <Modal
        open={!!tempPasswordShown}
        onClose={() => setTempPasswordShown(null)}
        title="Team member created"
        testid="team-add-temp-password"
        footer={
          <Button onClick={() => setTempPasswordShown(null)} testid="team-add-temp-close">
            Done
          </Button>
        }
      >
        {tempPasswordShown ? (
          <div className="space-y-2 text-sm" style={{ color: colors.onSurface }}>
            <p style={{ color: colors.onSurfaceSecondary }}>
              Copy these credentials and share them with the new team member.
              This temp password is shown once and cannot be retrieved later.
            </p>
            <div
              className="rounded-lg p-3 font-mono text-sm"
              style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
            >
              <div><strong>Email:</strong> {tempPasswordShown.email}</div>
              <div><strong>Temp password:</strong> <code data-testid="team-add-temp-value">{tempPasswordShown.password}</code></div>
            </div>
            <p className="text-xs" style={{ color: colors.muted }}>
              Invite email delivery is MOCKED — a real email will be sent once the email integration is fully wired.
            </p>
          </div>
        ) : null}
      </Modal>

      <Toast toast={toast} onClose={() => setToast(null)} />
    </Card>
  );
}


/**
 * Phase-Team · Feb-2026 — kebab menu (⋮) for admin actions on a team row.
 *
 * The parent (``TeamRoster``) computes ``canReset``, ``canDelete`` and
 * ``canUndelete`` from the caller's role vs the target's role +
 * ``deleted_at``. The kebab is only rendered when at least one action
 * is available — the roster mount decides visibility per-row.
 */
function TeamRowKebab({ row, canReset, canDelete, canUndelete,
                          onReset, onDelete, onUndelete }) {
  const [open, setOpen] = useState(false);
  const btnRef = React.useRef(null);
  const menuRef = React.useRef(null);
  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e) => {
      if (menuRef.current?.contains(e.target)) return;
      if (btnRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  return (
    <div className="relative">
      <button
        ref={btnRef}
        type="button"
        aria-label="Team row actions"
        onClick={() => setOpen((v) => !v)}
        className="w-8 h-8 rounded-full flex items-center justify-center hover:bg-black/5"
        style={{ color: colors.onSurface }}
        data-testid={`team-row-kebab-${row.id}`}
      >
        <MoreVertical size={16} />
      </button>
      {open ? (
        <div
          ref={menuRef}
          className="absolute right-0 top-9 z-30 min-w-[210px] rounded-lg shadow-lg py-1"
          style={{ backgroundColor: "#FFFFFF",
                     border: `1px solid ${colors.border}` }}
          data-testid={`team-row-kebab-menu-${row.id}`}
          role="menu"
        >
          {canReset ? (
            <button
              type="button"
              onClick={() => { setOpen(false); onReset(); }}
              className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 hover:bg-black/5"
              style={{ color: colors.onSurface }}
              data-testid={`team-row-reset-btn-${row.id}`}
            >
              <KeyRound size={13} /> Reset password
            </button>
          ) : null}
          {canDelete ? (
            <button
              type="button"
              onClick={() => { setOpen(false); onDelete(); }}
              className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 hover:bg-red-50"
              style={{ color: "#B91C1C" }}
              data-testid={`team-row-delete-btn-${row.id}`}
            >
              <Trash2 size={13} /> Delete team member
            </button>
          ) : null}
          {canUndelete ? (
            <button
              type="button"
              onClick={() => { setOpen(false); onUndelete(); }}
              className="w-full text-left px-3 py-2 text-sm flex items-center gap-2 hover:bg-black/5"
              style={{ color: "#166534" }}
              data-testid={`team-row-undelete-btn-${row.id}`}
            >
              <Undo2 size={13} /> Undelete
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}


/**
 * Phase-Team · Feb-2026 — Reset Password dialog with two modes:
 *  1. "Set custom password" — admin types a password (≥ 8 chars, at least
 *     one letter + one digit) with a show/hide toggle.
 *  2. "Auto-generate temporary password" — backend mints a 16-char strong
 *     password, returns it once for the admin to copy + share.
 *
 * The endpoint (``POST /users/{id}/reset-password``) always flips
 * ``must_change_password_on_next_login=true`` so the user is forced
 * to pick their own password on next login regardless of mode.
 */
function ResetPasswordDialog({ target, onClose, onDone, onError }) {
  const [mode, setMode] = useState("custom");   // "custom" | "auto"
  const [pw, setPw] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tempResult, setTempResult] = useState(null);   // { pw }
  React.useEffect(() => {
    if (!target) return;
    setMode("custom"); setPw(""); setShowPw(false);
    setBusy(false); setTempResult(null);
  }, [target?.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!target) return null;

  const customValid = pw.length >= 8 && /[A-Za-z]/.test(pw) && /\d/.test(pw);

  const submit = async () => {
    if (mode === "custom" && !customValid) {
      onError?.("Password must be at least 8 chars with 1 letter and 1 digit.");
      return;
    }
    setBusy(true);
    try {
      const body = mode === "auto"
        ? { auto_generate: true }
        : { new_password: pw };
      const r = await api.post(`/users/${target.id}/reset-password`, body);
      if (mode === "auto") {
        setTempResult({ pw: r?.temporary_password || "" });
      } else {
        onDone?.(`Password reset for ${target.name || target.email}`);
      }
    } catch (e) {
      onError?.(e?.message || "Reset failed");
    } finally { setBusy(false); }
  };

  const copyTemp = async () => {
    try {
      await navigator.clipboard.writeText(tempResult.pw);
      onDone?.("Temporary password copied to clipboard");
    } catch { onError?.("Clipboard blocked"); }
  };

  const footer = tempResult ? (
    <>
      <Button variant="ghost" onClick={onClose} testid="team-reset-close">Done</Button>
      <Button onClick={copyTemp} testid="team-reset-copy-temp">
        <CopyIcon size={13} /> Copy
      </Button>
    </>
  ) : (
    <>
      <Button variant="ghost" onClick={onClose} disabled={busy} testid="team-reset-cancel">
        Cancel
      </Button>
      <Button onClick={submit} disabled={busy} testid="team-reset-submit">
        {busy ? <><Loader2 size={13} className="animate-spin" /> Working…</>
          : <><KeyRound size={13} /> Reset password</>}
      </Button>
    </>
  );

  return (
    <Modal
      open={!!target}
      onClose={busy ? undefined : onClose}
      title={`Reset password · ${target.name || target.email}`}
      testid="team-reset-modal"
      footer={footer}
    >
      {tempResult ? (
        <div className="space-y-3 text-sm" style={{ color: colors.onSurface }}>
          <div
            className="rounded-lg p-3"
            style={{ backgroundColor: "#FEF3C7",
                       border: "1px solid #FDE68A", color: "#854D0E" }}
            data-testid="team-reset-temp-warning"
          >
            <ShieldAlert size={14} className="inline mr-1" />
            This password is shown once and cannot be retrieved later. Copy
            + share it with {target.name || target.email} now.
          </div>
          <div
            className="rounded-lg p-3 font-mono text-sm break-all"
            style={{ backgroundColor: colors.surfaceSecondary,
                       border: `1px solid ${colors.border}` }}
          >
            <code data-testid="team-reset-temp-value">{tempResult.pw}</code>
          </div>
          <div className="text-xs" style={{ color: colors.muted }}>
            The user must choose a new password on next login.
          </div>
        </div>
      ) : (
        <div className="space-y-3 text-sm" style={{ color: colors.onSurface }}>
          <div className="flex rounded-lg overflow-hidden"
               style={{ border: `1px solid ${colors.border}` }}
               data-testid="team-reset-mode-toggle">
            {[
              { k: "custom", label: "Set custom password" },
              { k: "auto",   label: "Auto-generate temp" },
            ].map((o) => (
              <button
                key={o.k}
                type="button"
                onClick={() => setMode(o.k)}
                className="flex-1 px-3 py-1.5 text-xs font-semibold"
                style={{
                  backgroundColor: mode === o.k ? colors.brand : "transparent",
                  color: mode === o.k ? "#fff" : colors.onSurface,
                }}
                data-testid={`team-reset-mode-${o.k}`}
              >
                {o.label}
              </button>
            ))}
          </div>

          {mode === "custom" ? (
            <div className="space-y-1">
              <label
                htmlFor="team-reset-pw"
                className="text-[10px] font-semibold uppercase tracking-wider"
                style={{ color: colors.muted }}
              >
                New password
              </label>
              <div className="flex gap-2">
                <input
                  id="team-reset-pw"
                  type={showPw ? "text" : "password"}
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  className="flex-1 px-3 py-2 rounded-lg border text-sm"
                  style={{ borderColor: colors.border,
                              backgroundColor: colors.surface,
                              color: colors.onSurface }}
                  data-testid="team-reset-pw-input"
                />
                <button
                  type="button"
                  onClick={() => setShowPw((v) => !v)}
                  className="px-2 rounded-lg"
                  style={{ backgroundColor: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}`,
                              color: colors.onSurface }}
                  data-testid="team-reset-pw-visibility"
                  aria-label={showPw ? "Hide password" : "Show password"}
                >
                  {showPw ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <div className="text-[11px]"
                   style={{ color: customValid ? "#166534" : colors.muted }}
                   data-testid="team-reset-pw-hint">
                Minimum 8 chars, at least 1 letter and 1 digit.
              </div>
            </div>
          ) : (
            <div
              className="rounded-lg p-3 text-xs"
              style={{ backgroundColor: colors.surfaceSecondary,
                          border: `1px dashed ${colors.border}`,
                          color: colors.onSurfaceSecondary }}
              data-testid="team-reset-auto-hint"
            >
              A 16-char secure temporary password will be generated. The
              user will be forced to choose a new password on next login.
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}


/**
 * Phase-Team · Feb-2026 — soft-delete confirm dialog.
 *
 * Explicit destructive variant, red primary. Calls
 * ``POST /users/{id}/soft-delete`` — the backend soft-deletes the
 * user, reassigns scheduled jobs to the "unassigned" placeholder,
 * and cancels active route overrides.
 */
function DeleteTeamMemberDialog({ target, onClose, onDone, onError }) {
  const [busy, setBusy] = useState(false);
  React.useEffect(() => { if (target) setBusy(false); }, [target?.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!target) return null;

  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/users/${target.id}/soft-delete`, {});
      onDone?.(target.name || target.email);
    } catch (e) {
      onError?.(e?.message || "Delete failed");
    } finally { setBusy(false); }
  };

  return (
    <Modal
      open={!!target}
      onClose={busy ? undefined : onClose}
      title={`Delete team member?`}
      testid="team-delete-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}
                  testid="team-delete-cancel">Cancel</Button>
          <Button variant="danger" onClick={submit} disabled={busy}
                  testid="team-delete-submit">
            {busy ? <><Loader2 size={13} className="animate-spin" /> Deleting…</>
              : <><Trash2 size={13} /> Delete team member</>}
          </Button>
        </>
      }
    >
      <div className="space-y-2 text-sm" style={{ color: colors.onSurface }}>
        <p>
          Are you sure you want to delete{" "}
          <b>{target.name || target.email || target.id}</b>?
        </p>
        <p style={{ color: colors.onSurfaceSecondary }}>
          They will be hidden from all rosters and their active jobs will
          be reassigned to the "Unassigned" placeholder. This can be
          undone by a super_admin.
        </p>
      </div>
    </Modal>
  );
}



/**
 * Phase 21 · Feb 2026 · Addition B — Compact color swatch + inline
 * picker popover for the Team roster row.
 *
 * Reads / writes ``users.display_color_hex`` via ``onChange`` (bound
 * to ``applyColor`` in ``TeamRoster``). Optimistic — the swatch flips
 * to the new color the moment the user clicks Save; if the PATCH
 * throws, the parent's promise rejects and we revert.
 */
export function TechColorSwatch({ user, editable, onChange }) {
  const [open, setOpen] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [draft, setDraft] = React.useState(
    (user.display_color_hex || "#0EA5E9").toUpperCase(),
  );
  React.useEffect(() => {
    setDraft((user.display_color_hex || "#0EA5E9").toUpperCase());
  }, [user.display_color_hex]);

  const currentColor = user.display_color_hex || null;

  const save = async (hex) => {
    setSaving(true);
    try {
      await onChange(hex);
      setOpen(false);
    } catch {
      /* parent toasted; keep popover open so user can retry */
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => editable && setOpen((v) => !v)}
        title={editable ? "Set display color" : "Display color"}
        aria-label={editable ? "Set display color" : "Display color"}
        className="w-6 h-6 rounded-md border shrink-0"
        style={{
          backgroundColor: currentColor || "transparent",
          borderColor: colors.border,
          borderStyle: currentColor ? "solid" : "dashed",
          cursor: editable ? "pointer" : "default",
        }}
        data-testid={`team-row-color-swatch-${user.id}`}
        data-color={currentColor || "unset"}
      >
        {!currentColor ? (
          <span className="text-[10px]" style={{ color: colors.muted }}>—</span>
        ) : null}
      </button>
      {open && editable ? (
        <div
          className="absolute z-50 mt-1 right-0 rounded-xl shadow-lg p-3 w-56"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid={`team-color-picker-popover-${user.id}`}
        >
          <div className="text-xs font-semibold mb-2" style={{ color: colors.onSurface }}>
            Display color
          </div>
          <div className="flex items-center gap-2 mb-3">
            <input
              type="color"
              value={draft}
              onChange={(e) => setDraft(e.target.value.toUpperCase())}
              className="w-10 h-10 rounded cursor-pointer"
              data-testid={`team-color-picker-input-${user.id}`}
            />
            <code
              className="text-xs px-2 py-1 rounded"
              style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}
            >
              {draft}
            </code>
          </div>
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              onClick={() => save(null)}
              disabled={saving || !currentColor}
              className="text-xs px-2 py-1 rounded font-semibold"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: currentColor ? colors.onSurface : colors.muted,
                opacity: !currentColor ? 0.5 : 1,
              }}
              data-testid={`team-color-picker-clear-${user.id}`}
            >
              Clear
            </button>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setOpen(false)}
                disabled={saving}
                className="text-xs px-2 py-1 rounded"
                style={{ color: colors.muted }}
                data-testid={`team-color-picker-cancel-${user.id}`}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => save(draft)}
                disabled={saving}
                className="text-xs px-3 py-1 rounded font-bold text-white"
                style={{ backgroundColor: colors.brand }}
                data-testid={`team-color-picker-save-${user.id}`}
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}


/**
 * Feb-2026 · Team page Auto Clock-In toggle.
 *
 * Renders a compact switch that PATCHes ``users.auto_clockin_enabled``
 * for the row's user. On non-technician rows the switch is inert (no
 * onClick, dimmed, `aria-disabled`) because the field is only
 * meaningful for techs — but the column stays visible so the roster's
 * columns align across role types.
 *
 * Optimistic — flips the local ``val`` immediately on click, then
 * awaits the parent's ``onChange`` (which owns the toast + refresh
 * cycle). On rejection the local state reverts.
 *
 * Exported for the unit test suite in
 * ``src/test/team-autoclockin-toggle.test.jsx``.
 */
export function TechAutoClockinToggle({ user, editable, onChange }) {
  const isTech = (user?.role || "").toLowerCase() === "technician";
  const initialVal = user?.auto_clockin_enabled === true;
  const [val, setVal] = React.useState(initialVal);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    setVal(user?.auto_clockin_enabled === true);
  }, [user?.auto_clockin_enabled]);

  // Non-tech rows: render an inert dash so the column aligns but the
  // switch cannot be flipped. Admins who want to see auto-clockin on
  // an admin/unassigned row need to first set the role to technician.
  if (!isTech) {
    return (
      <span
        className="text-[10px] font-semibold px-2 py-0.5 rounded"
        style={{
          backgroundColor: colors.surfaceSecondary,
          color: colors.muted,
          minWidth: 44,
          textAlign: "center",
        }}
        aria-label="Auto clock-in unavailable — not a technician"
        data-testid={`team-row-autoclockin-toggle-${user.id}`}
        data-value="unavailable"
      >
        —
      </span>
    );
  }

  const disabled = !editable || saving;

  const toggle = async () => {
    if (disabled) return;
    const next = !val;
    setVal(next); // optimistic
    setSaving(true);
    try {
      await onChange(next);
    } catch {
      setVal((cur) => !cur); // revert on failure
    } finally {
      setSaving(false);
    }
  };

  return (
    <button
      type="button"
      onClick={toggle}
      role="switch"
      aria-checked={val}
      aria-label={`Auto clock-in ${val ? "on" : "off"} for ${user.name || user.email}`}
      title={editable ? "Toggle auto clock-in" : "Auto clock-in (read-only)"}
      className="relative inline-flex items-center rounded-full transition"
      style={{
        width: 40,
        height: 22,
        backgroundColor: val ? colors.brand : "#CBD5E1",
        opacity: disabled ? 0.6 : 1,
        cursor: disabled ? "not-allowed" : "pointer",
      }}
      data-testid={`team-row-autoclockin-toggle-${user.id}`}
      data-value={val ? "on" : "off"}
      data-saving={saving ? "1" : "0"}
      disabled={disabled}
    >
      <span
        className="inline-block rounded-full bg-white shadow"
        style={{
          width: 18,
          height: 18,
          transform: val ? "translateX(20px)" : "translateX(2px)",
          transition: "transform 120ms ease",
        }}
      />
    </button>
  );
}


function AddTeamMemberModal({ open, onClose, onCreated, onError }) {
  const [form, setForm] = useState({
    first_name: "", last_name: "", email: "", phone: "",
    role_option: "pool_tech", send_invite_email: true,
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setForm({
        first_name: "", last_name: "", email: "", phone: "",
        role_option: "pool_tech", send_invite_email: true,
      });
    }
  }, [open]);

  const set = (k) => (e) => {
    const v = e?.target?.type === "checkbox" ? e.target.checked : e?.target?.value;
    setForm((f) => ({ ...f, [k]: v }));
  };

  const submit = async () => {
    const first = form.first_name.trim();
    const last = form.last_name.trim();
    const email = form.email.trim().toLowerCase();
    if (!first || !last) {
      onError?.("First and last name are required");
      return;
    }
    if (!email || !email.includes("@")) {
      onError?.("A valid email is required");
      return;
    }
    const opt = ROLE_OPTIONS.find((o) => o.value === form.role_option);
    if (!opt) {
      onError?.("Pick a role");
      return;
    }
    setBusy(true);
    try {
      const res = await api.post("/users", {
        first_name: first,
        last_name: last,
        email,
        phone: form.phone.trim() || null,
        role: opt.role,
        department: opt.department,
        send_invite_email: !!form.send_invite_email,
      });
      onCreated?.(res);
    } catch (e) {
      onError?.(e?.message || "Failed to add team member");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={() => (busy ? null : onClose())}
      title="Add Team Member"
      testid="team-add-modal"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={submit} disabled={busy} testid="team-add-submit">
            {busy ? "Adding…" : "Add Team Member"}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="FIRST NAME *" value={form.first_name} onChange={set("first_name")} testid="team-add-first" />
          <TextInput label="LAST NAME *" value={form.last_name} onChange={set("last_name")} testid="team-add-last" />
        </div>
        <TextInput label="EMAIL *" type="email" value={form.email} onChange={set("email")} testid="team-add-email" />
        <TextInput label="PHONE (optional)" value={form.phone} onChange={set("phone")} testid="team-add-phone" />
        <div>
          <label
            className="text-xs font-semibold tracking-wide mb-1 block"
            style={{ color: colors.onSurfaceSecondary }}
          >
            ROLE *
          </label>
          <select
            value={form.role_option}
            onChange={set("role_option")}
            className="w-full px-3 py-2.5 rounded-lg text-sm"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="team-add-role"
          >
            {ROLE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            Pool Tech / Landscape Tech: field-only. Admin: office-only. All: admin + full tech surface.
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.send_invite_email}
            onChange={set("send_invite_email")}
            data-testid="team-add-invite-checkbox"
          />
          <span style={{ color: colors.onSurface }}>
            Send invite email (currently MOCKED — logs to delivery table)
          </span>
        </label>
      </div>
    </Modal>
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
// Phase 54f · Feb-2026 — SupplierBadge for the pricebook row.
// One consistent color per slug so operators can eyeball the source
// of every line item at a glance. Tailwind palette below stays in
// sync with any dark-mode class overrides via the ``colors`` module.
const SUPPLIER_BADGE_COLORS = {
  poolcorp:    { bg: "#DBEAFE", fg: "#1E3A8A" }, // blue
  siteone:     { bg: "#DCFCE7", fg: "#166534" }, // green
  ewing:       { bg: "#FEF3C7", fg: "#92400E" }, // amber
  heritage:    { bg: "#EDE9FE", fg: "#5B21B6" }, // violet
  epoolsupply: { bg: "#FCE7F3", fg: "#9D174D" }, // pink
  manual:      { bg: "#E5E7EB", fg: "#374151" }, // slate
};

function SupplierBadge({ slug, testid }) {
  const meta = slug ? SUPPLIER_METADATA[slug] : null;
  const label = meta?.display_name || (slug ? slug : "Manual");
  const palette = SUPPLIER_BADGE_COLORS[slug || "manual"]
                  || SUPPLIER_BADGE_COLORS.manual;
  return (
    <span
      className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-semibold"
      style={{ backgroundColor: palette.bg, color: palette.fg }}
      data-testid={testid}
    >
      {label}
    </span>
  );
}


export function PriceBook() {
  const [rows, refresh] = useList("/items");
  const [open, setOpen] = useState(false);
  // Phase 56-b · Aug-2026 — Multi-supplier pricing form state.
  //   ``income_category_id`` drives which suppliers appear in the
  //   grid; ``supplier_prices`` is an object keyed by slug → dollar
  //   string ("" = empty, excluded from payload).
  const [form, setForm] = useState({
    name: "", category: "Pool", unit: "each", unit_price: 0,
    tax_rate: 0, wholesale_price: 0, labor_cost_default: 0,
    service_category_id: "", income_category_id: "",
    supplier_prices: {},
    // Feb-2026 · Pricebook item_type — default "product" preserves
    // existing lock-price behaviour. Flipping to "service" hides
    // supplier UI and unlocks unit_price on estimate/invoice lines.
    item_type: "product",
  });
  const [toast, setToast] = useState(null);
  // Aug-2026 · Fix P1 — Pricebook create requires ``service_category_id``.
  // Fetch the active service categories once on mount and expose
  // them to the "New item" modal's <select>. Archived categories
  // are filtered client-side so a category recently retired won't
  // still appear as a picker option even if the server response
  // included it. If the fetch fails or the list is empty, disable
  // Save and show an inline hint linking to /settings/service-
  // categories so an admin can seed one.
  const [serviceCats, setServiceCats] = useState(null); // null = loading, [] = empty, [...] = loaded
  const [serviceCatsError, setServiceCatsError] = useState("");
  useEffect(() => {
    api.get("/service-categories")
      .then((r) => {
        const raw = Array.isArray(r) ? r : (r?.categories || r?.items || []);
        setServiceCats(raw.filter((c) => !c.is_archived));
      })
      .catch((e) => setServiceCatsError(e?.message || "Failed to load service categories"));
  }, []);

  // Phase 56-b · Aug-2026 — Income Categories + Pricebook Suppliers
  // feed the Add-item modal supplier grid + the list summary line.
  // Both fetched once on mount; refetched only if the user re-opens
  // the modal after a supplier CRUD change (out of scope for 56-b).
  const [incomeCats, setIncomeCats] = useState([]);      // [{id, name, is_archived}]
  const [pricebookSuppliers, setPricebookSuppliers] = useState([]);  // all non-deleted suppliers
  useEffect(() => {
    (async () => {
      try {
        const r = await api.get("/income-categories");
        const raw = Array.isArray(r) ? r : (r?.items || []);
        setIncomeCats(raw.filter((c) => !c.is_archived));
      } catch { setIncomeCats([]); }
    })();
    (async () => {
      try {
        const r = await api.get("/pricebook/suppliers");
        setPricebookSuppliers(Array.isArray(r) ? r : []);
      } catch { setPricebookSuppliers([]); }
    })();
  }, []);
  // Suppliers for the currently-selected income_category on the
  // Add-item modal — active + non-deleted only.
  const modalSuppliers = useMemo(() => {
    if (!form.income_category_id) return [];
    return pricebookSuppliers.filter(
      (s) => s.income_category_id === form.income_category_id &&
             !s.deleted_at && s.is_active !== false,
    );
  }, [pricebookSuppliers, form.income_category_id]);
  // Phase 54f · Feb-2026 — supplier column + filter.
  //
  // ``SUPPLIER_META`` is looked up per-row for the badge label + color.
  // Filter is client-side to keep the backend contract additive-only
  // (no ``?supplier_id=`` query-param needed on ``/items``). If we ever
  // switch to server-side, replace ``filteredRows`` with a fetch.
  const [supplierFilter, setSupplierFilter] = useState("all");
  const filteredRows = useMemo(() => {
    const src = rows || [];
    if (supplierFilter === "all") return src;
    if (supplierFilter === "manual")
      return src.filter((r) => !r.supplier_id);
    // Filter by supplier slug — items have supplier_slug pinned at
    // sync time via ``services.suppliers.sync.apply_products``.
    return src.filter((r) => (r.supplier_slug || "") === supplierFilter);
  }, [rows, supplierFilter]);
  // PB1 · Feb-2026 — internal cost columns visible only to admins.
  // Uses ``useAuth`` from the app context to gate the two new columns
  // + the two new form fields. Non-admins still see the rest of the
  // row (name, price, edit) but never see wholesale or labor cost.
  const authCtx = useAuth() || {};
  const role = authCtx.user?.role || "";
  const showInternalCols = role === "admin" || role === "super_admin";
  // Phase 34 · Task LL Phase 2 · Feb 2026 — Pricebook frontend polish.
  // Bulk-select state + inline row edit state.
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editDraft, setEditDraft] = useState({});
  // Phase 56-b · Aug-2026 — per-row Supplier Prices edit modal.
  // Opens separately from the inline row-edit so we can render the
  // full N-supplier grid comfortably. Deleted suppliers linked to
  // the item are shown but their input is read-only + labelled.
  const [pricesModalRow, setPricesModalRow] = useState(null);
  const [pricesDraft, setPricesDraft] = useState({});   // slug → dollar string
  const [pricesBusy, setPricesBusy] = useState(false);
  const visibleIds = filteredRows.map((r) => r.id);
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every((id) => selectedIds.has(id));
  const indeterminate = visibleIds.some((id) => selectedIds.has(id)) && !allVisibleSelected;
  const selectedCount = selectedIds.size;
  const toggleAll = () => setSelectedIds((prev) => {
    const next = new Set(prev);
    if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
    else visibleIds.forEach((id) => next.add(id));
    return next;
  });
  const toggleOne = (id) => setSelectedIds((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const clearSelection = () => setSelectedIds(new Set());
  const doBulkDelete = async () => {
    setBusy(true);
    try {
      const res = await api.post("/pricebook/bulk-delete", { ids: Array.from(selectedIds) });
      const ok = res.deleted_count || 0;
      const failCount = (res.failed || []).length;
      clearSelection(); setConfirmOpen(false); refresh();
      if (failCount === 0) setToast({ tone: "success", message: `${ok} item${ok === 1 ? "" : "s"} archived` });
      else setToast({ tone: "warning", message: `${ok} archived · ${failCount} locked`, description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · ") });
    } catch (e) {
      setToast({ tone: "error", message: e.message || "Bulk delete failed" });
    } finally { setBusy(false); }
  };
  const startEdit = (row) => {
    setEditingId(row.id);
    setEditDraft({
      name: row.name || "", category: row.category || "", unit: row.unit || "",
      unit_price: row.unit_price || 0,
      tax_rate: row.tax_rate || 0, active: row.active !== false,
      wholesale_price: row.wholesale_price || 0,
      labor_cost_default: row.labor_cost_default || 0,
    });
  };
  const saveEdit = async (rowId) => {
    // Phase 34 · Task LL follow-up · Feb 2026 — client-side validation
    // mirrors the backend's PATCH /api/items/{iid} guards. Keeps error
    // toast copy identical to the server so QA regressions surface
    // the same message regardless of where the check fires.
    // Phase 56-e · Aug-2026 — legacy ``cost`` removed. Wholesale +
    // labor cost + tax rate are the surviving numeric fields.
    const taxN = Number(editDraft.tax_rate);
    const wpN = Number(editDraft.wholesale_price ?? 0);
    const laborN = Number(editDraft.labor_cost_default ?? 0);
    if (Number.isNaN(taxN) || taxN < 0 || taxN > 100) {
      setToast({ tone: "error", message: "Tax rate must be between 0 and 100" });
      return;
    }
    if (Number.isNaN(wpN) || wpN < 0) {
      setToast({ tone: "error", message: "Wholesale must be a number ≥ 0" });
      return;
    }
    if (Number.isNaN(laborN) || laborN < 0) {
      setToast({ tone: "error", message: "Labor cost must be a number ≥ 0" });
      return;
    }
    try {
      await api.patch(`/items/${rowId}`, {
        ...editDraft,
        unit_price: Number(editDraft.unit_price) || 0,
        tax_rate: taxN,
        wholesale_price: wpN,
        labor_cost_default: laborN,
      });
      setEditingId(null); setEditDraft({}); refresh();
      setToast({ tone: "success", message: "Item updated" });
    } catch (e) {
      setToast({ tone: "error", message: e.message || "Update failed" });
    }
  };
  const cancelEdit = () => { setEditingId(null); setEditDraft({}); };

  // Phase 56-b · Aug-2026 — Supplier Prices modal handlers.
  const openPrices = (row) => {
    // Seed the draft from the row's persisted supplier_prices —
    // cents→dollars, keyed by slug.
    const seed = {};
    for (const p of row.supplier_prices || []) {
      seed[p.supplier_slug] = ((p.cost_cents || 0) / 100).toFixed(2);
    }
    setPricesDraft(seed);
    setPricesModalRow(row);
  };
  const closePrices = () => {
    if (pricesBusy) return;
    setPricesModalRow(null);
    setPricesDraft({});
  };
  const savePrices = async () => {
    if (!pricesModalRow) return;
    setPricesBusy(true);
    try {
      const supplier_prices = Object.entries(pricesDraft)
        .map(([slug, raw]) => {
          const v = String(raw ?? "").trim();
          if (v === "") return null;
          const dollars = Number(v);
          if (Number.isNaN(dollars) || dollars < 0) return null;
          return { supplier_slug: slug,
                    cost_cents: Math.round(dollars * 100) };
        })
        .filter(Boolean);
      await api.patch(`/items/${pricesModalRow.id}`, { supplier_prices });
      setToast({ tone: "success", message: "Supplier prices updated" });
      setPricesModalRow(null);
      setPricesDraft({});
      refresh();
    } catch (e) {
      const detail = e?.data?.detail;
      const msg = (detail && detail.error === "supplier_income_category_mismatch")
        ? `Supplier "${detail.supplier_slug}" belongs to ${detail.expected_category}, not this item's category.`
        : (e?.message || "Save failed");
      setToast({ tone: "error", message: msg });
    } finally { setPricesBusy(false); }
  };
  const save = async () => {
    // Phase 56-e · Aug-2026 — legacy ``cost`` field removed.
    const taxN = Number(form.tax_rate);
    if (!form.service_category_id) {
      setToast({ tone: "error", message: "Please select a service category" });
      return;
    }
    if (Number.isNaN(taxN) || taxN < 0 || taxN > 100) {
      setToast({ tone: "error", message: "Tax rate must be between 0 and 100" });
      return;
    }
    // Phase 56-b · Aug-2026 — Multi-supplier payload assembly.
    // Only include suppliers where the user typed a non-empty value.
    // Empty / whitespace / 0 with blank → excluded. Dollars→cents.
    const supplier_prices = Object.entries(form.supplier_prices || {})
      .map(([slug, raw]) => {
        const v = String(raw ?? "").trim();
        if (v === "") return null;
        const dollars = Number(v);
        if (Number.isNaN(dollars) || dollars < 0) return null;
        return { supplier_slug: slug,
                  cost_cents: Math.round(dollars * 100) };
      })
      .filter(Boolean);
    // Feb-2026 P0 fix — client-side guard mirroring the backend's
    // ``supplier_prices_without_income_category`` 400. Without this,
    // any stale ``supplier_prices`` state (e.g. race between the
    // income-cat reset and a Save click) surfaces as an unfriendly
    // raw JSON error toast. Also gates the button visually below.
    if (supplier_prices.length > 0 && !form.income_category_id) {
      setToast({
        tone: "error",
        message: "Pick an Income Category before entering supplier prices, or clear the supplier price fields.",
      });
      return;
    }
    try {
      // Feb-2026 · item_type — services must NOT carry any supplier
      // or cost data. Send null / [] so the backend accept path is
      // clean even if the form state has stale numbers.
      const isService = form.item_type === "service";
      await api.post("/items", {
        ...form,
        unit_price: Number(form.unit_price) || 0,
        tax_rate: taxN,
        item_type: form.item_type || "product",
        income_category_id: isService ? null : (form.income_category_id || null),
        supplier_prices: isService ? [] : supplier_prices,
        wholesale_price: isService ? null : (Number(form.wholesale_price) || 0),
        labor_cost_default: isService ? null : (Number(form.labor_cost_default) || 0),
      });
      setOpen(false);
      setForm({
        name: "", category: "Pool", unit: "each", unit_price: 0,
        tax_rate: 0, service_category_id: "",
        income_category_id: "", supplier_prices: {},
        item_type: "product",
      });
      refresh();
    } catch (e) {
      // Feb-2026 P0 fix — unwrap the backend's structured error payload
      // (``{detail: {error, message, ...}}``) into a human toast rather
      // than dumping the raw JSON stringified onto the user.
      let msg = e?.message || "Save failed";
      try {
        const parsed = typeof msg === "string" && msg.startsWith("{")
          ? JSON.parse(msg) : null;
        const d = parsed?.detail ?? parsed;
        if (d?.error === "supplier_prices_without_income_category") {
          msg = "Pick an Income Category before entering supplier prices.";
        } else if (d?.error === "supplier_income_category_mismatch") {
          msg = `Supplier ${d.supplier_slug} isn't configured for the "${d.expected_category}" income category. Pick a different supplier or income category.`;
        } else if (d?.error === "unknown_supplier") {
          msg = `Supplier ${d.supplier_slug} isn't configured for this tenant.`;
        } else if (d?.error === "duplicate_supplier_slug") {
          msg = `Duplicate supplier row: ${d.supplier_slug}.`;
        } else if (d?.error === "invalid_cost_cents") {
          msg = `Invalid cost value for ${d.supplier_slug || "supplier"}.`;
        } else if (d?.message) {
          msg = d.message;
        }
      } catch { /* keep raw msg */ }
      setToast({ tone: "error", message: msg });
    }
  };
  // BUG B fix (Feb-2026) — soft-delete a pricebook row with a
  // HEAVY (type "DELETE") confirmation.
  const delRow = async (row) => {
    const ok = await mustConfirm({
      title: `Delete "${row.name}"?`,
      description: `Pricebook item will be archived. Historical invoices/quotes that reference "${row.name}" keep working, but it will no longer appear as an option on new estimates.`,
      tone: "danger", confirmText: "Delete", requireTypeConfirm: true,
    });
    if (!ok) return;
    try {
      await api.del(`/pricebook/${row.id}`);
      refresh();
      setToast({ tone: "success", message: `${row.name} archived` });
    } catch (e) {
      setToast({ tone: "error", message: e.message || "Delete failed" });
    }
  };
  return (
    <Card testid="pricebook-page">
      <div className="flex justify-between items-center mb-3">
        <div className="flex items-center gap-3">
          <input
            type="checkbox"
            checked={allVisibleSelected}
            ref={(el) => { if (el) el.indeterminate = indeterminate; }}
            onChange={toggleAll}
            aria-label="Select all pricebook items"
            data-testid="bulk-select-all"
            className="cursor-pointer"
          />
          <div className="text-xs uppercase font-semibold" style={{ color: colors.muted }}>
            Items · {filteredRows.length}
            {supplierFilter !== "all" && (
              <span className="ml-1"
                    style={{ color: colors.muted }}>
                / {(rows || []).length} total
              </span>
            )}
          </div>
          <select
            value={supplierFilter}
            onChange={(e) => setSupplierFilter(e.target.value)}
            className="ml-2 px-2 py-1 rounded-md text-xs"
            style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surface }}
            data-testid="pb-supplier-filter"
          >
            <option value="all">All suppliers</option>
            <option value="manual">Manual (no supplier)</option>
            {Object.keys(SUPPLIER_METADATA)
              .filter((slug) => !SUPPLIER_METADATA[slug].coming_in)
              .map((slug) => (
                <option key={slug} value={slug}>
                  {SUPPLIER_METADATA[slug].display_name}
                </option>
              ))}
          </select>
        </div>
        <Button onClick={() => setOpen(true)} testid="pb-new"><Plus size={14} /> Add new item</Button>
      </div>
      {rows === null ? <Skeleton style={{ height: 160 }} /> :
       <ul className="divide-y" style={{ borderColor: colors.divider }}>
         {filteredRows.map((r) => (
           <li key={r.id} className="py-2 flex items-center gap-3"
                data-testid={`pb-row-${r.id}`}
                style={{ backgroundColor: selectedIds.has(r.id) ? "#EFF6FF" : "transparent" }}>
             <input
               type="checkbox"
               checked={selectedIds.has(r.id)}
               onChange={() => toggleOne(r.id)}
               aria-label={`Select ${r.name}`}
               data-testid={`bulk-select-row-${r.id}`}
               className="cursor-pointer"
             />
             {editingId === r.id ? (
               <>
                 <input value={editDraft.name}
                          onChange={(e) => setEditDraft({ ...editDraft, name: e.target.value })}
                          className="flex-1 border px-2 py-1 text-sm rounded"
                          data-testid={`pb-edit-name-${r.id}`} />
                 <input value={editDraft.category}
                          onChange={(e) => setEditDraft({ ...editDraft, category: e.target.value })}
                          className="w-24 border px-2 py-1 text-sm rounded"
                          data-testid={`pb-edit-category-${r.id}`} />
                 <input value={editDraft.unit}
                          onChange={(e) => setEditDraft({ ...editDraft, unit: e.target.value })}
                          className="w-20 border px-2 py-1 text-sm rounded"
                          data-testid={`pb-edit-unit-${r.id}`}
                          placeholder="unit"
                          aria-label="Unit"
                          title="Unit" />
                 <input value={editDraft.unit_price} type="number" step="0.01" min="0"
                          onChange={(e) => setEditDraft({ ...editDraft, unit_price: e.target.value })}
                          className="w-24 border pl-5 pr-2 py-1 text-sm rounded text-right"
                          data-testid={`pb-edit-price-${r.id}`}
                          aria-label="Unit price ($)"
                          title="Unit price ($)" />
                 <input value={editDraft.tax_rate} type="number" step="0.01" min="0" max="100"
                          onChange={(e) => setEditDraft({ ...editDraft, tax_rate: e.target.value })}
                          className="w-20 border px-2 py-1 text-sm rounded text-right"
                          data-testid={`pb-edit-tax-${r.id}`}
                          placeholder="tax %"
                          aria-label="Tax rate (%)"
                          title="Tax rate (%)" />
                {showInternalCols ? (
                  <>
                    <input value={editDraft.wholesale_price ?? 0} type="number" step="0.01" min="0"
                             onChange={(e) => setEditDraft({ ...editDraft, wholesale_price: e.target.value })}
                             className="w-24 border px-2 py-1 text-sm rounded text-right"
                             data-testid={`pb-edit-wholesale-${r.id}`}
                             placeholder="wholesale"
                             aria-label="Wholesale price ($, internal)"
                             title="Wholesale — internal only" />
                    <input value={editDraft.labor_cost_default ?? 0} type="number" step="0.01" min="0"
                             onChange={(e) => setEditDraft({ ...editDraft, labor_cost_default: e.target.value })}
                             className="w-24 border px-2 py-1 text-sm rounded text-right"
                             data-testid={`pb-edit-labor-${r.id}`}
                             placeholder="labor"
                             aria-label="Labor cost ($, internal)"
                             title="Labor cost — internal only" />
                  </>
                ) : null}
                 <button onClick={() => saveEdit(r.id)}
                          className="text-xs font-bold text-white px-2 py-1 rounded"
                          style={{ backgroundColor: "#16A34A" }}
                          data-testid={`pb-edit-save-${r.id}`}>Save</button>
                 <button onClick={cancelEdit}
                          className="text-xs font-semibold px-2 py-1"
                          data-testid={`pb-edit-cancel-${r.id}`}>Cancel</button>
               </>
             ) : (
               <>
                 <div className="flex-1">
                   <div className="text-sm font-semibold">{r.name}</div>
                   <div className="text-xs flex items-center gap-2" style={{ color: colors.muted }}>
                     <span>{r.category} · {r.unit}</span>
                     <SupplierBadge slug={r.supplier_slug} testid={`pb-supplier-badge-${r.id}`} />
                   </div>
                   {/* Phase 56-b · Aug-2026 — Multi-supplier summary. */}
                   <SupplierPriceSummary row={r} testid={`pb-supplier-summary-${r.id}`} />
                 </div>
                 <div className="font-semibold">{money(r.unit_price)}</div>
                {showInternalCols ? (
                  <>
                    <div className="text-xs font-mono w-20 text-right"
                          style={{ color: colors.muted }}
                          data-testid={`pb-view-wholesale-${r.id}`}
                          title="Wholesale — internal only">
                      W {money(r.wholesale_price || 0)}
                    </div>
                    <div className="text-xs font-mono w-20 text-right"
                          style={{ color: colors.muted }}
                          data-testid={`pb-view-labor-${r.id}`}
                          title="Labor cost — internal only">
                      L {money(r.labor_cost_default || 0)}
                    </div>
                  </>
                ) : null}
                 <button onClick={() => startEdit(r)}
                            className="text-xs font-semibold underline"
                            style={{ color: colors.muted }}
                            data-testid={`pb-edit-${r.id}`}>Edit</button>
                 <button
                   type="button"
                   onClick={() => openPrices(r)}
                   className="p-1.5 rounded-md hover:bg-slate-100"
                   title="Supplier prices"
                   data-testid={`pb-prices-${r.id}`}
                 >
                   <DollarSign size={14} style={{ color: colors.brand }} />
                 </button>
                 <button
                   type="button"
                   onClick={() => delRow(r)}
                   className="p-1.5 rounded-md hover:bg-red-50"
                   title="Delete"
                   data-testid={`pb-delete-${r.id}`}
                 >
                   <Trash2 size={14} style={{ color: "#B91C1C" }} />
                 </button>
               </>
             )}
           </li>
         ))}
       </ul>}

      {/* Phase 34 · Task LL Phase 2 · bulk-select action bar. */}
      {selectedCount > 0 ? (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 rounded-2xl shadow-2xl flex items-center gap-3 px-4 py-3 z-40"
             style={{ backgroundColor: colors.onSurface, color: "#FFFFFF",
                       border: "1px solid rgba(255,255,255,0.08)" }}
             data-testid="bulk-action-bar">
          <div className="text-sm font-semibold" data-testid="bulk-action-bar-count">
            {selectedCount} selected
          </div>
          <button type="button" onClick={() => setConfirmOpen(true)} disabled={busy}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold"
                    style={{ backgroundColor: "#DC2626", color: "#FFFFFF" }}
                    data-testid="bulk-delete-button">
            <Trash2 size={12} /> Delete selected
          </button>
          <button type="button" onClick={clearSelection}
                    className="text-xs font-semibold underline"
                    style={{ color: "rgba(255,255,255,0.85)" }}
                    data-testid="bulk-clear-selection">
            Clear selection
          </button>
        </div>
      ) : null}

      {confirmOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
              style={{ background: "rgba(15,23,42,0.55)" }}
              onMouseDown={(e) => { if (e.target === e.currentTarget) setConfirmOpen(false); }}
              data-testid="bulk-delete-confirm-modal">
          <div className="w-full max-w-md rounded-2xl p-6 shadow-2xl bg-white">
            <h2 className="text-lg font-bold">
              Delete {selectedCount} pricebook item{selectedCount === 1 ? "" : "s"}?
            </h2>
            <p className="text-sm mt-1" style={{ color: colors.muted }}>
              Items referenced by active invoices/estimates/autobilling
              plans will show as "locked" and remain unchanged.
              This can be restored from the archive.
            </p>
            <div className="mt-5 flex items-center justify-end gap-2">
              <button type="button" onClick={() => setConfirmOpen(false)}
                        className="px-4 py-2 rounded-xl text-sm font-semibold bg-slate-100"
                        data-testid="bulk-delete-cancel">Cancel</button>
              <button type="button" onClick={doBulkDelete} disabled={busy}
                        className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
                        style={{ backgroundColor: "#DC2626" }}
                        data-testid="bulk-delete-confirm-btn">
                {busy ? "Deleting…" : `Delete ${selectedCount}`}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      <Modal open={open} onClose={() => setOpen(false)} title="New item"
        footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={save} testid="pb-new-save" disabled={
          !form.service_category_id
          || (serviceCats !== null && serviceCats.length === 0)
          // Feb-2026 P0 fix — block Save when supplier_prices carries
          // any non-empty value but no income_category is picked.
          || (!form.income_category_id
              && Object.values(form.supplier_prices || {})
                   .some((v) => String(v ?? "").trim() !== ""))
        }>Save</Button></>}>
        <div className="space-y-2">
          <TextInput label="NAME" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} testid="pb-new-name" />
          {/* Aug-2026 · Fix P1 — required service category picker. */}
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wide mb-1"
                    style={{ color: colors.muted }}>
              Service Category *
            </label>
            <select
              value={form.service_category_id}
              onChange={(e) => setForm({ ...form, service_category_id: e.target.value })}
              className="w-full px-3 py-2 rounded-md text-sm"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="pb-new-service-category"
              disabled={serviceCats === null || (serviceCats !== null && serviceCats.length === 0)}
            >
              <option value="">
                {serviceCats === null ? "Loading…" : "Select a service category…"}
              </option>
              {(serviceCats || []).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            {serviceCatsError ? (
              <div className="text-xs mt-1" style={{ color: "#B91C1C" }}
                    data-testid="pb-new-service-category-error">
                {serviceCatsError}
              </div>
            ) : null}
            {serviceCats !== null && serviceCats.length === 0 && !serviceCatsError ? (
              <div className="text-xs mt-1" style={{ color: "#B45309" }}
                    data-testid="pb-new-service-category-empty">
                No service categories available. Ask an admin to add one at
                {" "}<a href="/settings/service-categories" className="underline">
                  /settings/service-categories
                </a>.
              </div>
            ) : null}
          </div>
          {/* Phase 56-b · Aug-2026 — Income Category picker.
              Drives which suppliers appear in the grid below.
              Switching this dropdown wipes the supplier_prices state
              so stale entries from a different category can't leak.
              Feb-2026 · hidden entirely when item_type=service. */}
          {form.item_type !== "service" ? (
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-wide mb-1"
                    style={{ color: colors.muted }}>
              Income Category *
            </label>
            <select
              value={form.income_category_id}
              onChange={(e) => setForm({
                ...form,
                income_category_id: e.target.value,
                supplier_prices: {},
              })}
              className="w-full px-3 py-2 rounded-md text-sm"
              style={{ background: colors.surface,
                        border: `1px solid ${colors.border}`,
                        color: colors.onSurface }}
              data-testid="pb-new-income-category"
            >
              <option value="">Select an income category…</option>
              {incomeCats.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          ) : null}
          <TextInput label="CATEGORY" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} testid="pb-new-category" />
          <TextInput label="UNIT" value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })} testid="pb-new-unit" />
          <TextInput label="UNIT PRICE ($)" type="number" step="0.01" min="0" value={form.unit_price} onChange={(e) => setForm({ ...form, unit_price: e.target.value })} testid="pb-new-price" />
          {/* Legacy ``cost``/``tax_rate`` — kept in form state for
              backend contract, hidden from UI per preflight §3. */}
          <TextInput label="TAX RATE (%)" type="number" step="0.01" min="0" max="100" value={form.tax_rate} onChange={(e) => setForm({ ...form, tax_rate: e.target.value })} testid="pb-new-tax" />
          {/* Feb-2026 · item_type toggle. Products keep locked pricing
              + supplier costs; services allow per-customer price
              overrides on estimates and invoices. Renders BEFORE the
              supplier grid so the grid can hide when Service picked. */}
          <div className="pt-2">
            <div className="text-[10px] font-bold uppercase tracking-wide mb-1"
                  style={{ color: colors.muted }}>Type</div>
            <div className="inline-flex rounded-lg border overflow-hidden"
                  style={{ borderColor: colors.divider }}
                  data-testid="pb-new-type-toggle">
              {[{ v: "product", label: "Product" },
                { v: "service", label: "Service" }].map((opt) => {
                const on = form.item_type === opt.v;
                return (
                  <button key={opt.v} type="button"
                    data-testid={`pb-new-type-${opt.v}`}
                    onClick={() => setForm({
                      ...form, item_type: opt.v,
                      // Flipping to service scrubs supplier state
                      // client-side so the send matches the backend
                      // reject rules — no stale supplier fields.
                      ...(opt.v === "service" ? {
                        income_category_id: "",
                        supplier_prices: {},
                        wholesale_price: 0,
                        labor_cost_default: 0,
                      } : {}),
                    })}
                    className="px-3 py-1.5 text-xs font-semibold"
                    style={{
                      background: on ? colors.brand : colors.surface,
                      color: on ? "#fff" : colors.onSurface,
                    }}>
                    {opt.label}
                  </button>
                );
              })}
            </div>
            {form.item_type === "service" ? (
              <div className="text-xs mt-2"
                    style={{ color: colors.muted }}
                    data-testid="pb-new-service-helper">
                Service prices are editable per-customer on estimates
                and invoices.
              </div>
            ) : null}
          </div>
          {/* Phase 56-b · Supplier prices grid. Only renders when the
              user picks an income_category. Empty grid (unknown cat)
              stays hidden. Feb-2026 · also hides when item_type is
              service — services carry NO supplier data. */}
          {form.item_type !== "service" && form.income_category_id && modalSuppliers.length > 0 ? (
            <div className="pt-3 mt-2"
                  style={{ borderTop: `1px solid ${colors.divider}` }}
                  data-testid="pb-new-supplier-grid">
              <div className="text-[10px] font-bold uppercase tracking-wide mb-2"
                    style={{ color: colors.muted }}>
                {(incomeCats.find((c) => c.id === form.income_category_id) || {}).name}
                {" "}Supplier Prices
              </div>
              <div className="space-y-1.5">
                {modalSuppliers.map((s) => (
                  <div key={s.id}
                        className="flex items-center gap-2"
                        data-testid={`pb-new-supplier-row-${s.slug}`}>
                    <label className="text-xs font-semibold flex-1"
                            style={{ color: colors.onSurface }}>
                      {s.display_name}
                    </label>
                    <span className="text-xs" style={{ color: colors.muted }}>$</span>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      value={form.supplier_prices[s.slug] ?? ""}
                      onChange={(e) => setForm({
                        ...form,
                        supplier_prices: {
                          ...form.supplier_prices,
                          [s.slug]: e.target.value,
                        },
                      })}
                      placeholder="0.00"
                      className="w-24 border px-2 py-1 text-sm rounded text-right"
                      data-testid={`pb-new-supplier-input-${s.slug}`}
                      aria-label={`${s.display_name} price`}
                    />
                  </div>
                ))}
              </div>
              <p className="text-[10px] mt-2" style={{ color: colors.muted }}>
                Leave a supplier blank to skip it. You can edit prices
                per supplier later via the "Prices" button on each row.
              </p>
            </div>
          ) : null}
        </div>
      </Modal>
      {/* Phase 56-b · Aug-2026 — Supplier Prices edit modal per row.
          Opens from the "$" icon on each list row. Pre-populates
          from the item's ``supplier_prices`` (cents → dollar string).
          Deleted suppliers whose prices are already on the item
          appear as read-only rows with a "(deleted supplier)" pill. */}
      {pricesModalRow ? (
        <SupplierPricesEditModal
          row={pricesModalRow}
          incomeCats={incomeCats}
          pricebookSuppliers={pricebookSuppliers}
          draft={pricesDraft}
          onChange={setPricesDraft}
          onClose={closePrices}
          onSave={savePrices}
          busy={pricesBusy}
        />
      ) : null}
      <Toast toast={toast} onClose={() => setToast(null)} />
    </Card>
  );
}

// ─── Phase 56-b · Aug-2026 — SupplierPriceSummary ───────────────────────
// Compact one-liner rendered below the row's category / unit line.
// Uses money() so it matches the rest of Ops Hub's currency format.
function SupplierPriceSummary({ row, testid }) {
  const prices = Array.isArray(row?.supplier_prices) ? row.supplier_prices : [];
  if (prices.length === 0) {
    return (
      <div className="text-[11px] italic mt-0.5"
            style={{ color: colors.muted }}
            data-testid={testid}>
        No supplier prices set
      </div>
    );
  }
  const cents = prices.map((p) => Number(p.cost_cents) || 0);
  const lo = Math.min(...cents) / 100;
  const hi = Math.max(...cents) / 100;
  const range = lo === hi
    ? `at ${money(lo)}`
    : `min ${money(lo)} · max ${money(hi)}`;
  return (
    <div className="text-[11px] mt-0.5"
          style={{ color: colors.muted }}
          data-testid={testid}>
      {prices.length} supplier price{prices.length === 1 ? "" : "s"} · {range}
    </div>
  );
}


// ─── Phase 56-b · Aug-2026 — SupplierPricesEditModal ────────────────────
// Per-row supplier prices grid. Renders EVERY supplier for the item's
// income_category (active + non-deleted) PLUS any deleted suppliers
// whose prices are already on this item (read-only "(deleted)" pill).
function SupplierPricesEditModal({
  row, incomeCats, pricebookSuppliers,
  draft, onChange, onClose, onSave, busy,
}) {
  const cat = incomeCats.find((c) => c.id === row.income_category_id);
  const catName = cat?.name || "Uncategorized";
  const activeSuppliers = pricebookSuppliers.filter(
    (s) => s.income_category_id === row.income_category_id &&
           !s.deleted_at && s.is_active !== false,
  );
  const activeSlugSet = new Set(activeSuppliers.map((s) => s.slug));
  const orphanRows = (row.supplier_prices || [])
    .filter((p) => !activeSlugSet.has(p.supplier_slug))
    .map((p) => {
      const meta = pricebookSuppliers.find(
        (s) => s.slug === p.supplier_slug,
      );
      return {
        slug: p.supplier_slug,
        display_name: meta?.display_name || p.supplier_slug,
        cost_cents: p.cost_cents,
      };
    });

  const setSlugValue = (slug, val) => onChange({ ...draft, [slug]: val });

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      data-testid="pb-prices-modal"
    >
      <div
        className="w-full max-w-md rounded-2xl p-6 shadow-2xl bg-white max-h-[85vh] overflow-y-auto"
        style={{ border: `1px solid ${colors.border}` }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-3">
          <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
            Supplier prices — {row.name}
          </h2>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Income category:{" "}
            <span className="font-semibold"
                  data-testid="pb-prices-modal-category">
              {catName}
            </span>
          </p>
        </div>

        {!row.income_category_id ? (
          <div className="rounded-lg p-3 text-xs"
                style={{ background: "#FEF3C7", color: "#92400E",
                          border: "1px solid #FCD34D" }}
                data-testid="pb-prices-modal-uncategorized">
            This item has no income category set. Assign one via the
            row's Edit button before adding supplier prices.
          </div>
        ) : (
          <div className="space-y-1.5">
            {activeSuppliers.length === 0 && orphanRows.length === 0 ? (
              <div className="text-xs italic"
                    style={{ color: colors.muted }}
                    data-testid="pb-prices-modal-empty">
                No suppliers configured for {catName}. Ask an admin to
                add one at{" "}
                <a href="/settings/pricebook-suppliers"
                    className="underline">
                  /settings/pricebook-suppliers
                </a>.
              </div>
            ) : null}
            {activeSuppliers.map((s) => (
              <div key={s.id}
                    className="flex items-center gap-2"
                    data-testid={`pb-prices-modal-row-${s.slug}`}>
                <label className="text-xs font-semibold flex-1"
                        style={{ color: colors.onSurface }}>
                  {s.display_name}
                </label>
                <span className="text-xs" style={{ color: colors.muted }}>$</span>
                <input
                  type="number"
                  step="0.01"
                  min="0"
                  value={draft[s.slug] ?? ""}
                  onChange={(e) => setSlugValue(s.slug, e.target.value)}
                  placeholder="0.00"
                  className="w-24 border px-2 py-1 text-sm rounded text-right"
                  data-testid={`pb-prices-modal-input-${s.slug}`}
                  aria-label={`${s.display_name} price`}
                />
              </div>
            ))}
            {orphanRows.map((o) => (
              <div key={o.slug}
                    className="flex items-center gap-2"
                    data-testid={`pb-prices-modal-orphan-${o.slug}`}
                    style={{ opacity: 0.7 }}>
                <label className="text-xs font-semibold flex-1"
                        style={{ color: colors.onSurface }}>
                  {o.display_name}
                  <span
                    className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] font-bold uppercase"
                    style={{ backgroundColor: "#E5E7EB", color: "#6B7280" }}
                    data-testid={`pb-prices-modal-orphan-pill-${o.slug}`}
                  >
                    Deleted supplier
                  </span>
                </label>
                <span className="text-xs" style={{ color: colors.muted }}>$</span>
                <input
                  type="text"
                  value={((o.cost_cents || 0) / 100).toFixed(2)}
                  readOnly
                  disabled
                  className="w-24 border px-2 py-1 text-sm rounded text-right"
                  style={{ background: colors.surface,
                            color: colors.muted }}
                  data-testid={`pb-prices-modal-orphan-input-${o.slug}`}
                />
              </div>
            ))}
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-slate-100"
            data-testid="pb-prices-modal-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={busy || !row.income_category_id}
            className="px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60"
            style={{ backgroundColor: colors.brand }}
            data-testid="pb-prices-modal-save"
          >
            {busy ? "Saving…" : "Save prices"}
          </button>
        </div>
      </div>
    </div>
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
function JobTimers() {
  // Feb-2026 · P37b — surface GPS-arrival / service-report-submit
  // origin badges next to the job title so dispatchers can see at a
  // glance which timers auto-started vs manual.
  //
  // Feb-2026 · P37b.1 — start-method filter chip row above the
  // list so dispatchers can slice the active-timer set by how the
  // timer started. "manual" bucket also includes null / undefined /
  // legacy pre-P37 rows that were started by the manual UI.
  const [methodFilter, setMethodFilter] = React.useState("all");

  const _matches = (j) => {
    if (methodFilter === "all") return true;
    if (methodFilter === "auto") return j.timer_start_method === "gps_arrival";
    // "manual" bucket = anything that isn't gps_arrival, including
    // null / undefined / "manual" / any future start method.
    return j.timer_start_method !== "gps_arrival";
  };

  const _chip = (key, label) => {
    const active = methodFilter === key;
    return (
      <button
        key={key}
        type="button"
        onClick={() => setMethodFilter(key)}
        data-testid={`job-timer-filter-${key}`}
        className="text-xs font-semibold px-3 py-1 rounded-full transition"
        style={{
          background: active ? colors.brand : colors.surfaceSecondary,
          color: active ? "#fff" : colors.onSurface,
          border: `1px solid ${active ? colors.brand : colors.border}`,
          marginRight: 6,
        }}
      >
        {label}
      </button>
    );
  };

  return (
    <>
      <div
        className="mb-2 flex items-center gap-1"
        data-testid="job-timer-filter-row"
      >
        {_chip("all", "All")}
        {_chip("auto", "Auto")}
        {_chip("manual", "Manual")}
      </div>
      <SimplePage endpoint="/jobs" title="Active timers" empty="No active timers"
        filter={(j) => j.status === "active" && j.timer_started_at && _matches(j)}
        render={(j) => (
          <span data-testid={`job-timer-row-${j.id}`}>
            {j.title} — {j.technician_name} — started {j.timer_started_at}
            {j.timer_start_method === "gps_arrival" ? (
              <span
                data-testid={`timer-start-badge-${j.id}`}
                style={{ marginLeft: 8, padding: "1px 6px",
                           background: "#E0F2FE", color: "#075985",
                           borderRadius: 4, fontSize: 11, fontWeight: 600 }}
              >
                Started {new Date(j.timer_started_at).toTimeString().slice(0,5)} via GPS arrival
              </span>
            ) : null}
            {j.timer_stop_method === "service_report_submitted" ? (
              <span
                data-testid={`timer-stop-badge-${j.id}`}
                style={{ marginLeft: 6, padding: "1px 6px",
                           background: "#F1F5F9", color: "#334155",
                           borderRadius: 4, fontSize: 11, fontWeight: 600 }}
              >
                Stopped via service report
              </span>
            ) : j.timer_stop_method === "job_completed" ? (
              <span
                data-testid={`timer-stop-badge-${j.id}`}
                style={{ marginLeft: 6, padding: "1px 6px",
                           background: "#F1F5F9", color: "#334155",
                           borderRadius: 4, fontSize: 11, fontWeight: 600 }}
              >
                Stopped via job completion
              </span>
            ) : null}
          </span>
        )} />
    </>
  );
}
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
function SimplePage({ endpoint, _title, empty, render, filter }) {
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
