import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Plus, Sparkles, Check, X, Send, Calendar as CalIcon, Image as ImageIcon,
  TrendingUp, Bot, Layers, MessageSquare, RefreshCw, Users, ClipboardList,
} from "lucide-react";
import { api } from "@/api";
import { colors } from '@/theme';

// Shared UI helpers ---------------------------------------------------------
function Card({ children, className = "", testId }) {
  return (
    <div className={`rounded-2xl ${className}`}
         style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
         data-testid={testId}>{children}</div>
  );
}
function Header({ title, subtitle, right, backTo }) {
  const nav = useNavigate();
  return (
    <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
      <div className="flex items-center gap-3">
        <button onClick={() => (backTo ? nav(backTo) : nav(-1))}
                className="p-2 rounded-lg hover:brightness-95"
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
function Toast({ msg, onDone }) {
  useEffect(() => { if (!msg) return; const t = setTimeout(onDone, 2600); return () => clearTimeout(t); }, [msg, onDone]);
  if (!msg) return null;
  return <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg"
              style={{ backgroundColor: colors.onSurface, color: "#fff" }} data-testid="mkt-toast">{msg}</div>;
}
function ChannelChip({ ch }) {
  const map = { facebook: "#1877F2", instagram: "#E1306C", x: "#000",
                nextdoor: "#00A65C", gbp: "#4285F4", google: "#4285F4",
                email: "#6B7280", sms: "#059669" };
  const bg = map[ch] || colors.brand;
  return <span className="px-2 py-0.5 rounded-md text-xs font-bold uppercase"
               style={{ backgroundColor: bg, color: "#fff" }}>{ch}</span>;
}

// ─── Marketing Hub landing ─────────────────────────────────────────────────
export function MarketingHub() {
  const tiles = [
    { to: "/marketing/campaigns", label: "Campaigns", icon: Sparkles, sub: "AI campaign briefs" },
    { to: "/marketing/posts", label: "Posts", icon: Layers, sub: "Multi-channel post generator" },
    { to: "/marketing/queue", label: "Approval Queue", icon: ClipboardList, sub: "Review pending drafts" },
    { to: "/marketing/calendar", label: "Content Calendar", icon: CalIcon, sub: "Schedule + publish" },
    { to: "/marketing/scheduling", label: "Scheduling Slots", icon: RefreshCw, sub: "Recurring post cadence" },
    { to: "/marketing/performance", label: "Performance", icon: TrendingUp, sub: "Engagement + reach" },
    { to: "/marketing/sequences", label: "Sequences", icon: Users, sub: "Automation flows" },
    { to: "/marketing/templates", label: "Templates", icon: Layers, sub: "Campaign + email + SMS" },
    { to: "/marketing/before-after", label: "Before & After", icon: ImageIcon, sub: "AI-composed share cards" },
    { to: "/marketing/autopilot", label: "AI Autopilot", icon: Bot, sub: "Draft copy + seasonal/invoice ladders" },
    { to: "/marketing/reviews", label: "Reviews", icon: MessageSquare, sub: "AI review reply drafts" },
    { to: "/marketing/brand", label: "Brand Memory", icon: Bot, sub: "Voice + persona + zips" },
  ];
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="marketing-hub">
      <h1 className="text-3xl md:text-4xl font-bold mb-1" style={{ color: colors.onSurface }}>Marketing Studio</h1>
      <p className="text-sm mb-6" style={{ color: colors.muted }}>AI-powered campaign, post, sequence, and content workflows.</p>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {tiles.map((t) => (
          <Link key={t.to} to={t.to} className="rounded-2xl p-5 hover:brightness-95 flex items-start gap-3"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`hub-${t.label.toLowerCase().replace(/\s+/g, "-")}`}>
            <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
                 style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
              <t.icon size={20} />
            </div>
            <div>
              <div className="font-semibold text-sm" style={{ color: colors.onSurface }}>{t.label}</div>
              <div className="text-xs mt-0.5" style={{ color: colors.muted }}>{t.sub}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}

// ─── Brand Memory ──────────────────────────────────────────────────────────
export function BrandMemory() {
  const [form, setForm] = useState(null);
  const [toast, setToast] = useState("");
  useEffect(() => { api.get("/marketing/brand").then(setForm).catch(() => {}); }, []);
  if (!form) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;
  const save = async () => {
    try { await api.put("/marketing/brand", form); setToast("Saved"); } catch (e) { setToast(e.message); }
  };
  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="brand-memory-page">
      <Header title="Brand Memory" subtitle="Injected as system context on every AI generation" />
      <Card className="p-5 space-y-3">
        {[
          ["business_name", "Business name", "input"],
          ["description", "Description", "textarea"],
          ["target_persona", "Target persona", "textarea"],
          ["tone", "Tone", "select"],
        ].map(([k, label, kind]) => (
          <label key={k} className="block">
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>{label}</div>
            {kind === "textarea" ? (
              <textarea rows={2} value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                        className="w-full px-3 py-2 rounded-lg text-sm"
                        style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                        data-testid={`brand-${k}`} />
            ) : kind === "select" ? (
              <select value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg text-sm"
                      style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid={`brand-${k}`}>
                {["Friendly", "Professional", "Playful", "Local Expert"].map((o) => <option key={o}>{o}</option>)}
              </select>
            ) : (
              <input value={form[k] || ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                     className="w-full px-3 py-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                     data-testid={`brand-${k}`} />
            )}
          </label>
        ))}
        <label className="block">
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Service ZIPs (comma-separated)</div>
          <input value={(form.service_zips || []).join(",")}
                 onChange={(e) => setForm({ ...form, service_zips: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
                 className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="brand-service_zips" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Primary color</div>
            <input type="color" value={form.primary_color || "#0284C7"}
                   onChange={(e) => setForm({ ...form, primary_color: e.target.value })}
                   className="w-full h-10 rounded-lg" data-testid="brand-primary_color" />
          </label>
          <label>
            <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Accent color</div>
            <input type="color" value={form.accent_color || "#16A34A"}
                   onChange={(e) => setForm({ ...form, accent_color: e.target.value })}
                   className="w-full h-10 rounded-lg" data-testid="brand-accent_color" />
          </label>
        </div>
        <div className="flex justify-end pt-2">
          <button onClick={save} className="px-4 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="brand-save">Save</button>
        </div>
      </Card>
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── Campaigns ─────────────────────────────────────────────────────────────
export function CampaignsList() {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  useEffect(() => { api.get("/marketing/campaigns").then((r) => setRows(Array.isArray(r) ? r : [])); }, []);
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="campaigns-list">
      <Header title="Campaigns" subtitle="AI-generated multi-channel campaign briefs" right={
        <button onClick={() => nav("/marketing/campaigns/new")}
                className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-lg"
                style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="new-campaign-btn">
          <Plus size={14} /> New campaign
        </button>} />
      {rows.length === 0 ? (
        <Card className="p-8 text-center text-sm" testId="empty-campaigns">
          <div style={{ color: colors.muted }}>No campaigns yet. Click "New campaign" to start.</div>
        </Card>
      ) : (
        <div className="space-y-2">{rows.map((c) => (
          <Link key={c.id} to={`/marketing/campaigns/${c.id}`}
                className="block rounded-2xl p-4 hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`campaign-row-${c.id}`}>
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="font-semibold" style={{ color: colors.onSurface }}>{c.goal}</div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {c.audience} · {(c.channels || []).length} channels · {c.status}
              </div>
            </div>
          </Link>
        ))}</div>
      )}
    </div>
  );
}

export function CampaignNew() {
  const nav = useNavigate();
  const [form, setForm] = useState({ goal: "", audience: "All customers",
                                     channels: ["email", "sms", "facebook", "instagram", "gbp"] });
  const submit = async () => {
    if (!form.goal.trim()) return;
    const c = await api.post("/marketing/campaigns", form);
    nav(`/marketing/campaigns/${c.id}`);
  };
  return (
    <div className="p-4 md:p-8 max-w-2xl mx-auto" data-testid="campaign-new">
      <Header title="New Campaign" subtitle="Define the brief, then generate multi-channel drafts" />
      <Card className="p-5 space-y-3">
        <label>
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Goal *</div>
          <textarea rows={3} value={form.goal}
                    onChange={(e) => setForm({ ...form, goal: e.target.value })}
                    placeholder="e.g. Fill 20 spring pool opening slots by April 1"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="cn-goal" />
        </label>
        <label>
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Audience</div>
          <select value={form.audience} onChange={(e) => setForm({ ...form, audience: e.target.value })}
                  className="w-full px-3 py-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="cn-audience">
            {["All customers", "VIP", "Waitlist", "By tag", "By zip"].map((o) => <option key={o}>{o}</option>)}
          </select>
        </label>
        <div>
          <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>Channels</div>
          <div className="flex flex-wrap gap-2">
            {["email", "sms", "facebook", "instagram", "nextdoor", "gbp", "x"].map((ch) => {
              const on = form.channels.includes(ch);
              return (
                <button key={ch} onClick={() => setForm({ ...form,
                  channels: on ? form.channels.filter((c) => c !== ch) : [...form.channels, ch] })}
                        className="px-3 py-1.5 text-xs font-semibold rounded-lg"
                        style={{ backgroundColor: on ? colors.brand : colors.surfaceSecondary,
                                 color: on ? "#fff" : colors.onSurface,
                                 border: `1px solid ${on ? colors.brand : colors.border}` }}
                        data-testid={`cn-ch-${ch}`}>{ch}</button>
              );
            })}
          </div>
        </div>
        <div className="flex justify-end pt-2">
          <button onClick={submit} disabled={!form.goal.trim()}
                  className="px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="cn-create">
            Create
          </button>
        </div>
      </Card>
    </div>
  );
}

export function CampaignDetail() {
  const { id } = useParams();
  const [c, setC] = useState(null);
  const [toast, setToast] = useState("");
  const [chatMsg, setChatMsg] = useState("");
  const [chatReplies, setChatReplies] = useState([]);
  const load = () => api.get(`/marketing/campaigns/${id}`).then(setC).catch(() => {});
  useEffect(() => { load(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!c) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;
  const generate = async () => {
    const r = await api.post(`/marketing/campaigns/${id}/generate`, {});
    setToast(`Generated ${r.generated} items · stubbed=${r.stubbed}`);
    await load();
  };
  const approveAll = async () => {
    const ids = (c.items || []).filter((i) => i.status === "pending_review").map((i) => i.id);
    if (!ids.length) return;
    await api.post("/marketing/queue/bulk-approve", ids);
    setToast(`Approved ${ids.length} items`); await load();
  };
  const agentChat = async () => {
    if (!chatMsg.trim()) return;
    const r = await api.post(`/marketing/campaigns/${id}/agent-chat`,
      { message: chatMsg, mentions: ["content-writer", "seo-specialist", "ads-copywriter"] });
    setChatReplies([...chatReplies, { me: chatMsg, replies: r.replies }]);
    setChatMsg("");
  };
  const pending = (c.items || []).filter((i) => i.status === "pending_review").length;
  const approved = (c.items || []).filter((i) => i.status === "approved").length;
  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto" data-testid="campaign-detail">
      <Header title={c.goal} subtitle={`${c.audience} · ${c.status}`} backTo="/marketing/campaigns"
              right={<div className="flex gap-2">
                <button onClick={generate} className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-lg"
                        style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="cd-generate">
                  <Sparkles size={14} /> Generate
                </button>
                {pending > 0 && (
                  <button onClick={approveAll} className="flex items-center gap-1.5 px-3 py-2 text-sm font-semibold rounded-lg"
                          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                          data-testid="cd-bulk-approve">
                    <Check size={14} /> Approve all
                  </button>
                )}
              </div>} />
      <div className="grid grid-cols-3 gap-3 mb-4">
        <Card className="p-4" testId="cd-pending"><div className="text-xs" style={{ color: colors.muted }}>Pending</div><div className="text-2xl font-bold" style={{ color: colors.onSurface }}>{pending}</div></Card>
        <Card className="p-4" testId="cd-approved"><div className="text-xs" style={{ color: colors.muted }}>Approved</div><div className="text-2xl font-bold" style={{ color: colors.brand }}>{approved}</div></Card>
        <Card className="p-4" testId="cd-total"><div className="text-xs" style={{ color: colors.muted }}>Total items</div><div className="text-2xl font-bold" style={{ color: colors.onSurface }}>{(c.items || []).length}</div></Card>
      </div>
      <Card className="p-4 mb-4">
        <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>Generated items</div>
        {(c.items || []).length === 0 ? (
          <div className="text-xs" style={{ color: colors.muted }}>No items yet. Click Generate.</div>
        ) : (c.items || []).map((it) => (
          <div key={it.id} className="py-2 border-t flex items-center gap-2" style={{ borderColor: colors.border }} data-testid={`cd-item-${it.id}`}>
            <ChannelChip ch={it.channel || it.type} />
            <div className="flex-1 text-xs" style={{ color: colors.onSurface }}>{(it.copy || it.subject || "").slice(0, 100)}</div>
            <span className="text-xs" style={{ color: colors.muted }}>{it.status}</span>
          </div>
        ))}
      </Card>
      <Card className="p-4">
        <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>AI Agent chat</div>
        <div className="text-xs mb-2" style={{ color: colors.muted }}>Mention @content-writer, @seo-specialist, @ads-copywriter</div>
        <div className="space-y-2 mb-2 max-h-72 overflow-y-auto">
          {chatReplies.map((row, i) => (
            <div key={i}>
              <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>You: {row.me}</div>
              {(row.replies || []).map((r, j) => (
                <div key={j} className="text-xs pl-3" style={{ color: colors.muted }}>{r.message}</div>
              ))}
            </div>
          ))}
        </div>
        <div className="flex gap-2">
          <input value={chatMsg} onChange={(e) => setChatMsg(e.target.value)}
                 placeholder="Draft a caption in a friendly tone…"
                 className="flex-1 px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="cd-chat-input" />
          <button onClick={agentChat} className="px-3 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="cd-chat-send">
            <Send size={14} />
          </button>
        </div>
      </Card>
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── Post generator ────────────────────────────────────────────────────────
export function Posts() {
  const [topic, setTopic] = useState("");
  const [channels, setChannels] = useState(["facebook", "instagram", "gbp"]);
  const [variants, setVariants] = useState([]);
  const [toast, setToast] = useState("");
  const gen = async () => {
    const r = await api.post("/marketing/posts/generate", { topic, channels });
    setVariants(r.variants || []);
    setToast(`Generated ${(r.variants || []).length} variants (stubbed=${r.stubbed})`);
  };
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="posts-page">
      <Header title="Post Generator" subtitle="Platform-tuned variants with per-channel length limits" />
      <Card className="p-5 mb-4 space-y-3">
        <label>
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Topic / paste URL</div>
          <textarea rows={3} value={topic} onChange={(e) => setTopic(e.target.value)}
                    placeholder="e.g. Fall algae prevention tips"
                    className="w-full px-3 py-2 rounded-lg text-sm"
                    style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="posts-topic" />
        </label>
        <div className="flex flex-wrap gap-2">
          {["facebook", "instagram", "gbp", "nextdoor", "x"].map((ch) => {
            const on = channels.includes(ch);
            return <button key={ch} onClick={() => setChannels(on ? channels.filter((c) => c !== ch) : [...channels, ch])}
                           className="px-3 py-1.5 text-xs font-semibold rounded-lg"
                           style={{ backgroundColor: on ? colors.brand : colors.surfaceSecondary,
                                    color: on ? "#fff" : colors.onSurface,
                                    border: `1px solid ${on ? colors.brand : colors.border}` }}
                           data-testid={`posts-ch-${ch}`}>{ch}</button>;
          })}
        </div>
        <div className="flex justify-end">
          <button onClick={gen} disabled={!topic.trim() || !channels.length}
                  className="px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-60"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="posts-generate">
            <Sparkles size={14} className="inline mr-1" /> Generate variants
          </button>
        </div>
      </Card>
      {variants.map((v) => (
        <Card key={v.id} className="p-4 mb-3" testId={`variant-${v.id}`}>
          <div className="flex items-center gap-2 mb-2">
            <ChannelChip ch={v.channel} />
            <span className="text-xs" style={{ color: colors.muted }}>limit {v.character_limit}</span>
          </div>
          <div className="text-sm" style={{ color: colors.onSurface }}>{v.copy}</div>
        </Card>
      ))}
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── Approval Queue ────────────────────────────────────────────────────────
export function ApprovalQueue() {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState({ status: "", channel: "" });
  const [selected, setSelected] = useState([]);
  const [toast, setToast] = useState("");
  const load = () => {
    const q = new URLSearchParams();
    if (filter.status) q.set("status", filter.status);
    if (filter.channel) q.set("channel", filter.channel);
    api.get(`/marketing/queue?${q.toString()}`).then((r) => setRows(Array.isArray(r) ? r : []));
  };
  useEffect(() => { load(); }, [filter.status, filter.channel]); // eslint-disable-line react-hooks/exhaustive-deps
  const approve = async (id) => { await api.post(`/marketing/queue/${id}/approve`, {}); setToast("Approved"); load(); };
  const reject = async (id) => {
    const reason = window.prompt("Reason (optional)") || "";
    await api.post(`/marketing/queue/${id}/reject`, { reason });
    setToast("Rejected"); load();
  };
  const bulkApprove = async () => {
    if (!selected.length) return;
    await api.post("/marketing/queue/bulk-approve", selected);
    setToast(`Approved ${selected.length}`); setSelected([]); load();
  };
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="approval-queue-page">
      <Header title="Approval Queue" subtitle="Nothing publishes without approval" right={
        selected.length ? <button onClick={bulkApprove}
          className="px-3 py-2 rounded-lg text-sm font-semibold"
          style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="bulk-approve-btn">
            Approve {selected.length}
          </button> : null} />
      <div className="flex gap-2 mb-4 flex-wrap">
        <select value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })}
                className="px-3 py-2 rounded-lg text-sm"
                style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="queue-filter-status">
          <option value="">All statuses</option>
          {["pending_review", "approved", "rejected", "scheduled", "published", "published_stubbed"].map((s) =>
            <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filter.channel} onChange={(e) => setFilter({ ...filter, channel: e.target.value })}
                className="px-3 py-2 rounded-lg text-sm"
                style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                data-testid="queue-filter-channel">
          <option value="">All channels</option>
          {["facebook", "instagram", "gbp", "nextdoor", "x", "email", "sms"].map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>
      {rows.length === 0 ? (
        <Card className="p-8 text-center text-sm" testId="queue-empty">
          <div style={{ color: colors.muted }}>No items match.</div>
        </Card>
      ) : rows.map((it) => (
        <Card key={it.id} className="p-3 mb-2 flex items-start gap-3" testId={`queue-item-${it.id}`}>
          <input type="checkbox" checked={selected.includes(it.id)}
                 onChange={() => setSelected(selected.includes(it.id) ? selected.filter((x) => x !== it.id) : [...selected, it.id])}
                 className="mt-1" data-testid={`queue-cb-${it.id}`} />
          <ChannelChip ch={it.channel || it.type} />
          <div className="flex-1">
            <div className="text-sm" style={{ color: colors.onSurface }}>{(it.copy || it.subject || "").slice(0, 200)}</div>
            <div className="text-xs mt-1" style={{ color: colors.muted }}>{it.type} · {it.status}</div>
          </div>
          {it.status === "pending_review" && (
            <div className="flex gap-1">
              <button onClick={() => approve(it.id)} className="p-1.5 rounded-lg"
                      style={{ backgroundColor: "#DCFCE7", color: "#16A34A" }} data-testid={`approve-${it.id}`}>
                <Check size={14} />
              </button>
              <button onClick={() => reject(it.id)} className="p-1.5 rounded-lg"
                      style={{ backgroundColor: "#FEE2E2", color: "#B91C1C" }} data-testid={`reject-${it.id}`}>
                <X size={14} />
              </button>
            </div>
          )}
        </Card>
      ))}
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── Calendar ──────────────────────────────────────────────────────────────
export function ContentCalendar() {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    api.get("/marketing/queue?status=scheduled").then((r) => setRows(r || []));
    api.get("/marketing/queue?status=approved").then((r) => setRows((prev) => [...prev, ...(r || [])]));
  }, []);
  const now = new Date();
  const days = Array.from({ length: 42 }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth(), 1 - new Date(now.getFullYear(), now.getMonth(), 1).getDay() + i);
    return d;
  });
  const byDay = useMemo(() => {
    const m = {};
    rows.forEach((r) => {
      const d = (r.scheduled_at || r.approved_at || r.created_at || "").slice(0, 10);
      if (!m[d]) m[d] = []; m[d].push(r);
    });
    return m;
  }, [rows]);
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="calendar-page">
      <Header title="Content Calendar" subtitle="Approved + scheduled posts across all channels" />
      <div className="grid grid-cols-7 gap-1 text-xs text-center mb-1" style={{ color: colors.muted }}>
        {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => <div key={d} className="font-semibold">{d}</div>)}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {days.map((d, i) => {
          const key = d.toISOString().slice(0, 10);
          const items = byDay[key] || [];
          const isToday = key === now.toISOString().slice(0, 10);
          return (
            <div key={i} className="rounded-lg p-2 min-h-24 text-xs"
                 style={{
                   backgroundColor: isToday ? colors.brandTertiary : colors.surface,
                   border: `1px solid ${colors.border}`,
                   opacity: d.getMonth() === now.getMonth() ? 1 : 0.4,
                 }}
                 data-testid={`cal-day-${key}`}>
              <div className="font-semibold mb-1" style={{ color: colors.onSurface }}>{d.getDate()}</div>
              {items.slice(0, 3).map((it) => (
                <div key={it.id} className="mb-0.5 truncate rounded px-1 py-0.5"
                     style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}>
                  {it.channel} · {(it.copy || "").slice(0, 22)}
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Scheduling ────────────────────────────────────────────────────────────
export function SchedulingConfig() {
  const [rows, setRows] = useState([]);
  const [ch, setCh] = useState("facebook");
  const [day, setDay] = useState("mon");
  const [hour, setHour] = useState(10);
  const [toast, setToast] = useState("");
  const load = () => api.get("/marketing/scheduling").then((r) => setRows(r || []));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const add = async () => {
    const existing = rows.find((r) => r.channel === ch);
    const slots = [...((existing && existing.slots) || []), { day_of_week: day, hour: Number(hour), minute: 0 }];
    await api.post("/marketing/scheduling", { channel: ch, slots });
    setToast("Slot added"); load();
  };
  return (
    <div className="p-4 md:p-8 max-w-3xl mx-auto" data-testid="scheduling-page">
      <Header title="Scheduling Slots" subtitle="Recurring cadence per channel" />
      <Card className="p-5 mb-4">
        <div className="grid grid-cols-4 gap-2 items-end">
          <select value={ch} onChange={(e) => setCh(e.target.value)} className="px-3 py-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="sch-channel">
            {["facebook", "instagram", "gbp", "nextdoor", "x"].map((c) => <option key={c}>{c}</option>)}
          </select>
          <select value={day} onChange={(e) => setDay(e.target.value)} className="px-3 py-2 rounded-lg text-sm"
                  style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="sch-day">
            {["mon", "tue", "wed", "thu", "fri", "sat", "sun"].map((d) => <option key={d}>{d}</option>)}
          </select>
          <input type="number" min={0} max={23} value={hour} onChange={(e) => setHour(e.target.value)}
                 className="px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="sch-hour" />
          <button onClick={add} className="px-3 py-2 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: colors.brand, color: "#fff" }} data-testid="sch-add">
            <Plus size={14} className="inline mr-1" /> Add
          </button>
        </div>
      </Card>
      {rows.map((r) => (
        <Card key={r.channel} className="p-4 mb-2" testId={`sch-row-${r.channel}`}>
          <div className="flex items-center gap-2 mb-2"><ChannelChip ch={r.channel} /></div>
          <div className="text-xs" style={{ color: colors.muted }}>
            {(r.slots || []).map((s) => `${s.day_of_week} ${s.hour}:${String(s.minute || 0).padStart(2, "0")}`).join(" · ") || "No slots"}
          </div>
        </Card>
      ))}
      <Toast msg={toast} onDone={() => setToast("")} />
    </div>
  );
}

// ─── Performance ───────────────────────────────────────────────────────────
export function Performance() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/marketing/performance").then(setData); }, []);
  if (!data) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;
  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto" data-testid="performance-page">
      <Header title="Performance" subtitle={data.note} />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        {[
          { l: "Published this month", v: data.published_this_month },
          { l: "Upcoming", v: data.upcoming_count },
          { l: "Avg engagement", v: `${(data.avg_engagement * 100).toFixed(1)}%` },
          { l: "Best channel", v: data.best_channel || "—" },
        ].map((k) => (
          <Card key={k.l} className="p-4" testId={`perf-${k.l.toLowerCase().replace(/\s+/g, "-")}`}>
            <div className="text-xs" style={{ color: colors.muted }}>{k.l}</div>
            <div className="text-2xl font-bold" style={{ color: colors.onSurface }}>{k.v}</div>
          </Card>
        ))}
      </div>
      <Card className="p-4">
        <div className="text-sm font-semibold mb-2" style={{ color: colors.onSurface }}>Engagement trend (mock)</div>
        <div className="text-xs" style={{ color: colors.muted }}>
          {(data.trend || []).slice(-4).map((t) => (
            <div key={t.week} className="flex justify-between py-1" style={{ borderTop: `1px solid ${colors.border}` }}>
              <span>{t.week}</span>
              <span>FB {t.facebook} · IG {t.instagram} · GBP {t.gbp}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ─── Templates ─────────────────────────────────────────────────────────────
export function TemplatesHub() {
  const [tab, setTab] = useState("campaigns");
  const [rows, setRows] = useState([]);
  useEffect(() => {
    api.get(`/marketing/templates/${tab}`).then((r) => setRows(r || []));
  }, [tab]);
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="templates-page">
      <Header title="Templates" subtitle="Prebuilt campaigns + reusable emails & SMS" />
      <div className="flex gap-2 mb-4">
        {["campaigns", "emails", "sms"].map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  className="px-3 py-1.5 rounded-lg text-sm font-semibold"
                  style={{ backgroundColor: tab === t ? colors.brand : colors.surfaceSecondary,
                           color: tab === t ? "#fff" : colors.onSurface,
                           border: `1px solid ${tab === t ? colors.brand : colors.border}` }}
                  data-testid={`tpl-tab-${t}`}>
            {t}
          </button>
        ))}
      </div>
      {rows.map((r) => (
        <Card key={r.slug} className="p-4 mb-2" testId={`tpl-row-${r.slug}`}>
          <div className="font-semibold" style={{ color: colors.onSurface }}>{r.name}</div>
          <div className="text-xs mt-1" style={{ color: colors.muted }}>
            {r.goal || r.subject || r.body?.slice(0, 100) || ""}
          </div>
        </Card>
      ))}
    </div>
  );
}

// ─── Reviews (stubbed AI reply drafts list) ────────────────────────────────
export function Reviews() {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    api.get("/marketing/queue?status=pending_review&channel=gbp").then((r) => setRows(r || []));
  }, []);
  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="reviews-page">
      <Header title="AI Review Reply Drafts" subtitle="Every review gets an AI-drafted reply for approval" />
      {rows.length === 0 ? (
        <Card className="p-8 text-center text-sm" testId="reviews-empty">
          <div style={{ color: colors.muted }}>No pending review-reply drafts.</div>
        </Card>
      ) : rows.map((r) => (
        <Card key={r.id} className="p-4 mb-2">
          <div className="text-sm">{r.copy}</div>
        </Card>
      ))}
    </div>
  );
}
