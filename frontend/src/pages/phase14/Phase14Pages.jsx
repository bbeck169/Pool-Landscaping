import React, { useEffect, useState } from "react";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { Link, useParams, useNavigate } from "react-router-dom";
import { Link2, Share2 } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import { useAuth } from "@/auth";
import TrainingCertsPanel from "@/pages/training/TrainingCertsPanel";
import BusinessCard from "@/components/business-card/BusinessCard";

/* Phase 14 pages — Communication thread deep view · Technician profile · Form builder. */

const BASE = process.env.REACT_APP_BACKEND_URL;

function Card({ children, testid, className = "" }) {
  return (
    <div className={`rounded-2xl bg-white p-5 ${className}`} style={{ border: `1px solid ${colors.border}` }} data-testid={testid}>
      {children}
    </div>
  );
}
function Chip({ children, tone = "default" }) {
  const bg = { default: colors.surfaceSecondary, brand: colors.brandTertiary, warn: "#FEF3C7", err: "#FEE2E2" }[tone] || colors.surfaceSecondary;
  const fg = { default: colors.onSurfaceSecondary, brand: colors.onBrandTertiary, warn: "#854D0E", err: "#991B1B" }[tone] || colors.onSurfaceSecondary;
  return <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: bg, color: fg }}>{children}</span>;
}
function Toast({ text }) {
  if (!text) return null;
  return <div className="fixed bottom-6 right-6 z-50 px-4 py-2 rounded-xl text-sm text-white shadow-lg" style={{ backgroundColor: colors.onSurface }}>{text}</div>;
}

/* ═══════════════════════════════════════════════════════════════════
   1. Communication Thread Deep View
   ═══════════════════════════════════════════════════════════════════ */
export function CommunicationThread() {
  const { id } = useParams();
  const [thread, setThread] = useState(null);
  const [reply, setReply] = useState("");
  const [channel, setChannel] = useState("portal");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");

  const load = () => {
    api.get(`/communications/${id}`)
      .then((r) => { setThread(r); setChannel(r?.channel || (r?.messages?.[r?.messages?.length - 1]?.channel) || "portal"); })
      .catch(() => setThread({ _error: true }));
  };
  useEffect(load, [id]);

  const send = async () => {
    if (!reply.trim()) return;
    setBusy(true);
    try {
      await api.post(`/communications/${id}/reply`, { text: reply, channel });
      setReply("");
      setToast("Sent");
      load();
    } catch (e) { setToast(e.message); }
    finally { setBusy(false); }
  };

  const draftAi = async () => {
    setBusy(true);
    try {
      const r = await api.post("/ai-ops/employees/ava/chat", {
        message: `Draft a concise, warm reply for this ${channel} thread. Recent context: ${(thread?.messages || []).slice(-3).map((m) => `${m.role || m.direction || "?"}: ${m.text || m.body || ""}`).join("\n")}`,
      });
      setReply(r?.response || "");
    } catch (e) { setToast(e.message); }
    finally { setBusy(false); }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setToast("Link copied — anyone with access can view this activity");
    } catch { setToast("Could not copy link"); }
  };
  const shareLink = async () => {
    const url = window.location.href;
    if (navigator.share) {
      try { await navigator.share({ title: thread?.subject || "Conversation", url }); return; } catch {}
    }
    copyLink();
  };
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  if (!thread) return <div className="p-8 text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading thread…</div>;
  if (thread._error) return <div className="p-8 text-sm" style={{ color: colors.error }}>Thread not found.</div>;

  const messages = thread.messages || [];

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto space-y-4" data-testid="communication-thread-page">
      <div className="flex items-center gap-3">
        <Link to="/notifications" className="text-sm font-semibold" style={{ color: colors.brand }}>← Inbox</Link>
        <div className="flex-1">
          <h1 className="text-xl font-bold">{thread.subject || thread.customer_name || "Conversation"}</h1>
          <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>
            {thread.customer_name && <Chip>{thread.customer_name}</Chip>}
            {" "}<Chip tone="brand">{thread.channel || channel}</Chip>
            {thread.unread && <> · <Chip tone="warn">Unread</Chip></>}
          </div>
        </div>
        <button onClick={copyLink}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surfaceSecondary }}
                title="Copy link" data-testid="thread-copy-link">
          <Link2 size={14} />
        </button>
        <button onClick={shareLink}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surfaceSecondary }}
                title="Share" data-testid="thread-share">
          <Share2 size={14} />
        </button>
      </div>

      <Card testid="thread-messages">
        {messages.length === 0 && <div className="text-sm text-center py-8" style={{ color: colors.onSurfaceSecondary }}>No messages yet.</div>}
        {messages.map((m, i) => (
          <div key={m.id || i} className="py-3 border-b last:border-0" style={{ borderColor: colors.border }} data-testid={`thread-msg-${i}`}>
            <div className="flex items-center gap-2 text-xs" style={{ color: colors.onSurfaceSecondary }}>
              <span className="font-semibold">{m.from || m.author || m.direction || "—"}</span>
              <Chip>{m.channel || channel}</Chip>
              <span>{(m.created_at || "").slice(0, 16).replace("T", " ")}</span>
            </div>
            <div className="mt-1 text-sm whitespace-pre-line">{m.text || m.body || m.content || ""}</div>
          </div>
        ))}
      </Card>

      <Card testid="thread-composer">
        <div className="flex items-center gap-2 mb-2">
          <label className="text-xs font-semibold">Reply via</label>
          <select value={channel} onChange={(e) => setChannel(e.target.value)}
                  className="px-2 py-1 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }} data-testid="thread-channel">
            {["portal", "email", "sms"].map((c) => <option key={c}>{c}</option>)}
          </select>
          <button onClick={draftAi} disabled={busy}
                  className="ml-auto px-3 py-1 rounded-lg text-xs font-semibold"
                  style={{ backgroundColor: colors.surfaceSecondary }} data-testid="thread-ai-draft">
            ✨ Draft with AI
          </button>
        </div>
        <textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={4} placeholder="Type your reply…"
                  className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}
                  data-testid="thread-input" />
        <button onClick={send} disabled={busy || !reply.trim()}
                className="mt-2 px-4 py-2 rounded-xl text-sm font-semibold text-white"
                style={{ backgroundColor: colors.brand, opacity: busy ? 0.6 : 1 }}
                data-testid="thread-send">
          {busy ? "Sending…" : "Send reply"}
        </button>
      </Card>

      <Toast text={toast} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   2. Technician Profile (6-tab admin view)
   ═══════════════════════════════════════════════════════════════════ */
const TECH_TABS = [
  { k: "overview", label: "Overview" },
  { k: "jobs", label: "Assigned Jobs" },
  { k: "timesheets", label: "Timesheets" },
  { k: "d2d", label: "D2D" },
  { k: "attendance", label: "Attendance" },
  { k: "performance", label: "Performance" },
  { k: "certs", label: "Certifications" },
];

export function TechnicianProfile() {
  const { id } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [tab, setTab] = useState("overview");
  const [tech, setTech] = useState(null);
  const [perf, setPerf] = useState(null);
  const [attendance, setAttendance] = useState([]);
  const [knocks, setKnocks] = useState([]);
  const [err, setErr] = useState("");

  const isSelf = user?.role === "technician" && (user?.id === id || user?.technician_id === id);
  const isAdmin = user?.role === "admin";
  const canView = isAdmin || isSelf;

  useEffect(() => {
    if (!canView) { navigate("/"); return; }
    api.get(`/technicians/${id}`).then(setTech).catch((e) => setErr(e.message));
    api.get(`/technicians/${id}/performance`).then(setPerf).catch(() => {});
    api.get("/attendance/history").then((r) => setAttendance(Array.isArray(r) ? r.filter((a) => a.technician_id === id || a.tech_id === id) : [])).catch(() => {});
    api.get("/d2d/knocks").then((r) => setKnocks(Array.isArray(r) ? r.filter((k) => k.tech_id === id) : [])).catch(() => {});
  }, [id, canView, navigate]);

  if (err) return <div className="p-8 text-sm" style={{ color: colors.error }}>{err}</div>;
  if (!tech) return <div className="p-8 text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading technician…</div>;

  const jobs = tech.jobs || [];

  // Tech-role users see a subset (overview + timesheets + attendance only).
  const visibleTabs = isSelf && !isAdmin
    ? TECH_TABS.filter((t) => ["overview", "timesheets", "attendance", "certs"].includes(t.k))
    : TECH_TABS;

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-4" data-testid="technician-profile-page">
      {/* Feb-2026 · Item 6 — Company business card at the top of the
          tech profile so field techs can share it with customers on
          the spot. */}
      <div className="max-w-md" data-testid="tech-business-card-slot">
        <BusinessCard variant="compact" />
      </div>
      <div className="flex items-center gap-4">
        <div className="w-16 h-16 rounded-full flex items-center justify-center text-2xl font-black text-white" style={{ backgroundColor: colors.brand }}>
          {(tech.name || "?").slice(0, 1).toUpperCase()}
        </div>
        <div className="flex-1">
          <h1 className="text-2xl font-bold">{tech.name}</h1>
          <div className="text-sm flex items-center gap-2" style={{ color: colors.onSurfaceSecondary }}>
            <Chip>{tech.role || "technician"}</Chip>
            {tech.active !== false ? <Chip tone="brand">Active</Chip> : <Chip tone="err">Inactive</Chip>}
            {tech.phone && <span>📞 {tech.phone}</span>}
            {tech.email && <span>✉ {tech.email}</span>}
          </div>
        </div>
      </div>

      <div className="flex gap-2 flex-wrap border-b" style={{ borderColor: colors.border }}>
        {visibleTabs.map((t) => (
          <button key={t.k} onClick={() => setTab(t.k)}
                  className="px-3 py-2 text-sm font-semibold border-b-2 -mb-px"
                  style={{ borderColor: tab === t.k ? colors.brand : "transparent",
                           color: tab === t.k ? colors.brand : colors.onSurfaceSecondary }}
                  data-testid={`tech-tab-${t.k}`}>{t.label}</button>
        ))}
      </div>

      {tab === "overview" && (
        <Card>
          <Row label="Hire date" value={(tech.hire_date || "").slice(0, 10) || "—"} />
          <Row label="Service areas" value={(tech.service_areas || []).join(", ") || "—"} />
          <Row label="Certifications" value={(tech.certifications || []).join(", ") || "—"} />
          <Row label="Direct manager" value={tech.manager || "—"} />
          <Row label="Alert phone" value={tech.alert_phone || tech.phone || "—"} />
          <Row label="Notes" value={tech.notes || "—"} />
        </Card>
      )}

      {tab === "jobs" && (
        <Card testid="tech-jobs">
          {jobs.length === 0 && <div className="text-sm text-center py-6" style={{ color: colors.onSurfaceSecondary }}>No assigned jobs.</div>}
          {jobs.slice(0, 30).map((j) => (
            <div key={j.id} className="py-2 border-b last:border-0 flex items-center gap-3" style={{ borderColor: colors.border }}>
              <Chip tone={j.status === "completed" ? "brand" : j.status === "in_progress" ? "warn" : "default"}>{j.status || "scheduled"}</Chip>
              <div className="flex-1">
                <div className="font-semibold text-sm">{j.title || j.customer_name}</div>
                <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{(j.scheduled_date || "").slice(0, 10)} · ${j.price || 0}</div>
              </div>
              <Link to={`/jobs/${j.id}`} className="text-xs font-semibold" style={{ color: colors.brand }}>Open →</Link>
            </div>
          ))}
        </Card>
      )}

      {tab === "timesheets" && (
        <Card>
          <div className="text-sm mb-2 font-semibold">Last 8 weeks</div>
          <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
            Detailed weekly grid available on the Timesheets page — filter to {tech.name}.
          </div>
          <Link to={`/timesheets?tech=${id}`} className="mt-3 inline-block text-xs font-semibold" style={{ color: colors.brand }}>Open Timesheets →</Link>
        </Card>
      )}

      {tab === "d2d" && (
        <Card testid="tech-d2d">
          <div className="text-sm mb-2 font-semibold">Canvassing knocks (last 100)</div>
          {knocks.length === 0 && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>No knocks recorded.</div>}
          {knocks.slice(0, 15).map((k) => (
            <div key={k.id} className="py-1 text-sm flex items-center gap-2 border-b last:border-0" style={{ borderColor: colors.border }}>
              <Chip>{k.disposition}</Chip><span className="flex-1 truncate">{k.address || "—"}</span>
              <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{(k.created_at || "").slice(0, 10)}</span>
            </div>
          ))}
        </Card>
      )}

      {tab === "attendance" && (
        <Card testid="tech-attendance">
          {attendance.length === 0 && <div className="text-sm text-center py-6" style={{ color: colors.onSurfaceSecondary }}>No entries.</div>}
          {attendance.slice(0, 30).map((a) => (
            <div key={a.id || a._id} className="py-1 text-sm flex items-center gap-2 border-b last:border-0" style={{ borderColor: colors.border }}>
              <span className="w-24 font-semibold text-xs">{(a.created_at || "").slice(0, 10)}</span>
              <Chip>{a.event || a.type}</Chip>
              <span className="text-xs" style={{ color: colors.onSurfaceSecondary }}>{a.notes || ""}</span>
            </div>
          ))}
        </Card>
      )}

      {tab === "performance" && (
        <Card testid="tech-performance">
          {!perf && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Computing…</div>}
          {perf && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <PerfTile label="Jobs (90d)" value={perf.total_jobs} />
              <PerfTile label="Completed" value={perf.completed_jobs} />
              <PerfTile label="Completion %" value={`${perf.completion_rate}%`} />
              <PerfTile label="On-time %" value={`${perf.on_time_rate}%`} />
              <PerfTile label="Avg duration" value={`${perf.avg_duration_min} min`} />
              <PerfTile label="Avg rating" value={perf.avg_customer_rating ?? "—"} />
            </div>
          )}
        </Card>
      )}

      {tab === "certs" && (
        <TrainingCertsPanel
          userId={id}
          isOwnProfile={isSelf}
          isAdminViewer={isAdmin}
        />
      )}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex py-2 border-b last:border-0" style={{ borderColor: colors.border }}>
      <div className="w-40 text-xs uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>{label}</div>
      <div className="flex-1 text-sm">{value}</div>
    </div>
  );
}
function PerfTile({ label, value }) {
  return (
    <div className="rounded-xl p-3" style={{ backgroundColor: colors.surfaceSecondary }}>
      <div className="text-xs uppercase tracking-wider" style={{ color: colors.onSurfaceSecondary }}>{label}</div>
      <div className="font-bold text-2xl">{value}</div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   3. Public Form Builder
   ═══════════════════════════════════════════════════════════════════ */
const FIELD_TYPES = [
  { k: "text",     label: "Short text" },
  { k: "textarea", label: "Long text" },
  { k: "email",    label: "Email" },
  { k: "tel",      label: "Phone" },
  { k: "number",   label: "Number" },
  { k: "checkbox", label: "Checkbox" },
  { k: "select",   label: "Dropdown" },
  { k: "date",     label: "Date" },
];

export function FormsList() {
  const [rows, setRows] = useState(null);
  useEffect(() => { api.get("/forms").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  const create = async () => {
    const r = await api.post("/forms", { name: "Untitled form", status: "draft", fields: [], destination: "lead" });
    window.location.href = `/forms/${r.id}`;
  };
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-4" data-testid="forms-list">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold">Public Forms</h1>
        <button onClick={create} className="px-4 py-2 rounded-xl text-sm font-semibold text-white" style={{ backgroundColor: colors.brand }} data-testid="forms-new">+ New form</button>
      </div>
      <Card>
        {rows === null && <div className="text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>}
        {rows && rows.length === 0 && <div className="text-sm text-center py-6" style={{ color: colors.onSurfaceSecondary }}>No forms yet.</div>}
        {rows && rows.map((f) => (
          <div key={f.id} className="py-2 border-b last:border-0 flex items-center gap-3" style={{ borderColor: colors.border }}>
            <div className="flex-1">
              <div className="font-semibold text-sm">{f.name}</div>
              <div className="text-xs" style={{ color: colors.onSurfaceSecondary }}>Slug: {f.slug} · {f.submissions || 0} submissions</div>
            </div>
            <Chip tone={f.status === "published" ? "brand" : "default"}>{f.status || "draft"}</Chip>
            <Link to={`/forms/${f.id}`} className="text-xs font-semibold" style={{ color: colors.brand }}>Edit →</Link>
            {f.slug && <a href={`/f/${f.slug}`} target="_blank" rel="noreferrer" className="text-xs font-semibold" style={{ color: colors.brandSecondary }}>Public ↗</a>}
          </div>
        ))}
      </Card>
    </div>
  );
}

export function FormEditor() {
  const { id } = useParams();
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");
  const [subs, setSubs] = useState([]);

  useEffect(() => {
    api.get(`/forms/${id}`).then(setForm);
    api.get(`/forms/${id}/submissions`).then((r) => setSubs(Array.isArray(r) ? r : []));
  }, [id]);

  const patch = (k, v) => setForm({ ...form, [k]: v });
  const addField = (type) => setForm({ ...form, fields: [...(form.fields || []), {
    id: crypto.randomUUID(), name: `field_${(form.fields || []).length + 1}`,
    label: FIELD_TYPES.find((t) => t.k === type)?.label || type, type, required: false, options: [],
  }] });
  const updateField = (fid, patch) => setForm({
    ...form, fields: (form.fields || []).map((f) => f.id === fid ? { ...f, ...patch } : f),
  });
  const removeField = (fid) => setForm({ ...form, fields: (form.fields || []).filter((f) => f.id !== fid) });
  const save = async () => {
    setSaving(true);
    try {
      await api.patch(`/forms/${id}`, form);
      setToast("Saved");
    } catch (e) { setToast(e.message); }
    finally { setSaving(false); }
  };
  const publish = async () => {
    setForm({ ...form, status: "published" });
    setSaving(true);
    try { await api.patch(`/forms/${id}`, { ...form, status: "published" }); setToast("Published"); }
    catch (e) { setToast(e.message); }
    finally { setSaving(false); }
  };
  const del = async () => {
    if (!(await mustConfirm({ title: "Delete this form?", tone: "danger" }))) return;
    await api.del(`/forms/${id}`);
    window.location.href = "/forms";
  };

  if (!form) return <div className="p-8 text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading form…</div>;

  const publicUrl = `${window.location.origin}/f/${form.slug || form.id}`;

  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto space-y-4" data-testid="form-editor">
      <div className="flex items-center gap-3">
        <Link to="/forms" className="text-sm font-semibold" style={{ color: colors.brand }}>← Forms</Link>
        <input value={form.name || ""} onChange={(e) => patch("name", e.target.value)}
               className="text-xl font-bold flex-1 px-2 py-1 rounded" style={{ border: `1px solid ${colors.border}` }}
               data-testid="form-name" />
        <button onClick={save} disabled={saving} className="px-4 py-2 rounded-lg text-sm font-semibold text-white" style={{ backgroundColor: colors.brand, opacity: saving ? 0.6 : 1 }} data-testid="form-save">Save</button>
        <button onClick={publish} disabled={saving} className="px-4 py-2 rounded-lg text-sm font-semibold text-white" style={{ backgroundColor: colors.brandSecondary }} data-testid="form-publish">Publish</button>
        <button onClick={del} className="px-3 py-2 rounded-lg text-sm font-semibold" style={{ backgroundColor: "#FEE2E2", color: colors.error }} data-testid="form-delete">Delete</button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card>
          <div className="text-sm font-bold mb-2">Add field</div>
          <div className="grid grid-cols-2 gap-2">
            {FIELD_TYPES.map((t) => (
              <button key={t.k} onClick={() => addField(t.k)}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold text-left"
                      style={{ backgroundColor: colors.surfaceSecondary }}
                      data-testid={`form-add-${t.k}`}>+ {t.label}</button>
            ))}
          </div>
          <div className="mt-4 text-sm font-bold mb-2">Form settings</div>
          <label className="text-xs font-semibold block mb-1">Destination</label>
          <select value={form.destination || "lead"} onChange={(e) => patch("destination", e.target.value)}
                  className="w-full px-3 py-2 rounded-lg text-sm mb-2" style={{ border: `1px solid ${colors.border}` }}
                  data-testid="form-destination">
            <option value="lead">Create a Lead</option>
            <option value="customer">Create a Customer</option>
            <option value="quote_request">Create a Quote request</option>
          </select>
          <label className="text-xs font-semibold block mb-1">Notify emails (comma-separated)</label>
          <input value={(form.notify_emails || []).join(",")} onChange={(e) => patch("notify_emails", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))}
                 className="w-full px-3 py-2 rounded-lg text-sm mb-2" style={{ border: `1px solid ${colors.border}` }} data-testid="form-notify" />
          <label className="text-xs font-semibold block mb-1">Redirect URL after submit</label>
          <input value={form.redirect_url || ""} onChange={(e) => patch("redirect_url", e.target.value)}
                 className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }} data-testid="form-redirect" />

          <div className="mt-4 text-sm font-bold mb-1">Embed</div>
          <div className="text-xs mb-1" style={{ color: colors.onSurfaceSecondary }}>Public URL:</div>
          <input readOnly value={publicUrl} onFocus={(e) => e.target.select()}
                 className="w-full px-3 py-1 rounded-lg text-xs font-mono" style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surfaceSecondary }}
                 data-testid="form-public-url" />
          <div className="text-xs mt-2 mb-1" style={{ color: colors.onSurfaceSecondary }}>Iframe:</div>
          <textarea readOnly rows={2} value={`<iframe src="${publicUrl}" style="width:100%;height:640px;border:0"></iframe>`}
                    onFocus={(e) => e.target.select()}
                    className="w-full px-3 py-1 rounded-lg text-xs font-mono" style={{ border: `1px solid ${colors.border}`, backgroundColor: colors.surfaceSecondary }}
                    data-testid="form-embed" />
        </Card>

        <Card className="lg:col-span-2">
          <div className="text-sm font-bold mb-2">Fields</div>
          {(form.fields || []).length === 0 && (
            <div className="text-sm text-center py-8" style={{ color: colors.onSurfaceSecondary }}>Add fields from the palette →</div>
          )}
          {(form.fields || []).map((f) => (
            <div key={f.id} className="p-3 mb-2 rounded-lg" style={{ border: `1px solid ${colors.border}` }} data-testid={`form-field-${f.id}`}>
              <div className="flex items-center gap-2">
                <input value={f.label || ""} onChange={(e) => updateField(f.id, { label: e.target.value })}
                       placeholder="Label"
                       className="flex-1 px-2 py-1 rounded text-sm" style={{ border: `1px solid ${colors.border}` }} />
                <input value={f.name || ""} onChange={(e) => updateField(f.id, { name: e.target.value })}
                       placeholder="Name"
                       className="w-32 px-2 py-1 rounded text-sm font-mono" style={{ border: `1px solid ${colors.border}` }} />
                <Chip>{f.type}</Chip>
                <label className="text-xs flex items-center gap-1">
                  <input type="checkbox" checked={!!f.required} onChange={(e) => updateField(f.id, { required: e.target.checked })} />required
                </label>
                <button onClick={() => removeField(f.id)} className="text-xs font-semibold" style={{ color: colors.error }}>Remove</button>
              </div>
              {f.type === "select" && (
                <input value={(f.options || []).join(",")} onChange={(e) => updateField(f.id, { options: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                       placeholder="Options, comma-separated"
                       className="mt-2 w-full px-2 py-1 rounded text-xs" style={{ border: `1px solid ${colors.border}` }} />
              )}
            </div>
          ))}
        </Card>
      </div>

      <Card testid="form-submissions">
        <div className="text-sm font-bold mb-2">Submissions ({subs.length})</div>
        {subs.length === 0 && <div className="text-sm text-center py-4" style={{ color: colors.onSurfaceSecondary }}>None yet.</div>}
        {subs.slice(0, 10).map((s) => (
          <div key={s.id} className="py-1 text-xs border-b last:border-0" style={{ borderColor: colors.border }}>
            <span className="font-semibold">{(s.created_at || "").slice(0, 16).replace("T", " ")}</span>
            {" · "}
            {Object.entries(s.values || {}).slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(" · ")}
          </div>
        ))}
      </Card>

      <Toast text={toast} />
    </div>
  );
}

/* Public form renderer at /f/:slug — anonymous. */
export function PublicForm() {
  const { slug } = useParams();
  const [form, setForm] = useState(null);
  const [values, setValues] = useState({});
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    fetch(`${BASE}/api/public/forms/${slug}`)
      .then((r) => r.ok ? r.json() : Promise.reject(r.status))
      .then(setForm)
      .catch(() => setErr("Form not found or unpublished"));
  }, [slug]);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await fetch(`${BASE}/api/public/forms/${slug}/submit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      });
      const data = await r.json();
      if (data?.redirect_url) window.location.href = data.redirect_url;
      else setSubmitted(true);
    } catch (e2) { setErr(e2.message); }
    finally { setBusy(false); }
  };

  if (err) return <div className="min-h-screen flex items-center justify-center text-sm" style={{ color: colors.onSurfaceSecondary }}>{err}</div>;
  if (!form) return <div className="min-h-screen flex items-center justify-center text-sm" style={{ color: colors.onSurfaceSecondary }}>Loading…</div>;
  if (submitted) return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="max-w-md text-center bg-white rounded-3xl p-8 shadow-xl" style={{ border: `1px solid ${colors.border}` }}>
        <div className="text-5xl mb-2">✓</div>
        <div className="text-xl font-bold">Thanks — we'll be in touch!</div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ background: `linear-gradient(135deg, ${colors.brand}0F 0%, #fff 100%)` }} data-testid="public-form">
      <form onSubmit={submit} className="max-w-lg w-full bg-white rounded-3xl p-6 shadow-xl space-y-3" style={{ border: `1px solid ${colors.border}` }}>
        <h1 className="text-2xl font-bold">{form.name}</h1>
        {(form.fields || []).map((f) => (
          <div key={f.id}>
            <label className="text-xs font-semibold block mb-1">
              {f.label}{f.required && <span style={{ color: colors.error }}> *</span>}
            </label>
            {f.type === "textarea" ? (
              <textarea required={f.required} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                        rows={3} className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }} />
            ) : f.type === "select" ? (
              <select required={f.required} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }}>
                <option value="">Choose…</option>
                {(f.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : f.type === "checkbox" ? (
              <input type="checkbox" onChange={(e) => setValues({ ...values, [f.name]: e.target.checked })} />
            ) : (
              <input type={f.type === "text" ? "text" : f.type} required={f.required}
                     onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}
                     className="w-full px-3 py-2 rounded-lg text-sm" style={{ border: `1px solid ${colors.border}` }} />
            )}
          </div>
        ))}
        <button disabled={busy} type="submit"
                className="w-full py-2 rounded-xl text-sm font-semibold text-white"
                style={{ backgroundColor: colors.brand, opacity: busy ? 0.6 : 1 }}
                data-testid="public-form-submit">
          {busy ? "Submitting…" : "Submit"}
        </button>
      </form>
    </div>
  );
}
