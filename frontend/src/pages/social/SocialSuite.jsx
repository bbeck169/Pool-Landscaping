/**
 * Phase 18A · Social Suite (Composer, Calendar, Library, Drafts).
 * Admin/marketing only. Posts stay draft/scheduled until Phase 18B wires OAuth.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import {
  Facebook, Instagram, Twitter, Linkedin, Youtube, MapPin, Globe,
  Music2, Send, Sparkles, ImageIcon, CalendarDays, Trash2, Copy, Edit,
  Save, Clock, Plug, ChevronLeft, ChevronRight, X, Upload,
} from "lucide-react";

const NETWORKS = [
  { key: "facebook",  label: "Facebook Pages",     icon: Facebook,  limit: 5000 },
  { key: "instagram", label: "Instagram Business", icon: Instagram, limit: 2200 },
  { key: "twitter",   label: "X (Twitter)",        icon: Twitter,   limit: 280 },
  { key: "linkedin",  label: "LinkedIn Company",   icon: Linkedin,  limit: 3000 },
  { key: "tiktok",    label: "TikTok Business",    icon: Music2,    limit: 2200 },
  { key: "youtube",   label: "YouTube",            icon: Youtube,   limit: 5000 },
  { key: "gbp",       label: "Google Business",    icon: MapPin,    limit: 1500 },
  { key: "pinterest", label: "Pinterest",          icon: ImageIcon, limit: 500 },
  { key: "threads",   label: "Threads",            icon: Globe,     limit: 500 },
];
const NET_MAP = Object.fromEntries(NETWORKS.map(n => [n.key, n]));

const Card = ({ children, className = "", testId }) => (
  <div className={`rounded-2xl ${className}`}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
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
const BtnPrimary = ({ children, testId, ...rest }) => (
  <button className="px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50 flex items-center gap-1"
          style={{ background: brandGradientCss }} data-testid={testId} {...rest}>{children}</button>
);
const BtnGhost = ({ children, testId, ...rest }) => (
  <button className="px-3 py-2 rounded-xl text-sm font-semibold flex items-center gap-1"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                   border: `1px solid ${colors.border}` }}
          data-testid={testId} {...rest}>{children}</button>
);

/* ═══════════ COMPOSER ═══════════ */
export function ComposerPage() {
  const [caption, setCaption] = useState("");
  const [hashtags, setHashtags] = useState([]);
  const [selected, setSelected] = useState(new Set(["facebook", "instagram"]));
  const [scheduledAt, setScheduledAt] = useState("");
  const [firstComment, setFirstComment] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [aiTopic, setAiTopic] = useState("");
  const [aiResults, setAiResults] = useState(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  const toggle = (k) => {
    const s = new Set(selected);
    s.has(k) ? s.delete(k) : s.add(k);
    setSelected(s);
  };
  const tightestLimit = useMemo(() => {
    const nets = [...selected];
    if (!nets.length) return 5000;
    return Math.min(...nets.map((k) => NET_MAP[k]?.limit ?? 5000));
  }, [selected]);
  const overLimit = caption.length > tightestLimit;

  const doAi = async () => {
    if (!aiTopic.trim()) return;
    setAiBusy(true);
    try {
      const r = await api.post("/social/ai/caption", {
        topic: aiTopic, networks: [...selected],
      });
      setAiResults(r);
    } catch (e) { alert(e.message); }
    finally { setAiBusy(false); }
  };

  const save = async (asSchedule) => {
    if (!selected.size) { alert("Pick at least one network"); return; }
    if (asSchedule && !scheduledAt) { alert("Pick a date/time"); return; }
    setSaving(true);
    try {
      await api.post("/social/posts", {
        networks: [...selected], caption, hashtags,
        scheduled_at: asSchedule ? new Date(scheduledAt).toISOString() : null,
        first_comment: firstComment || null,
      });
      setToast(asSchedule ? "Scheduled" : "Saved as draft");
      setCaption(""); setHashtags([]); setScheduledAt(""); setFirstComment("");
      setTimeout(() => setToast(""), 2500);
    } catch (e) { alert(e.message); }
    finally { setSaving(false); }
  };

  return (
    <Section title="Composer"
             subtitle="Write once, publish to many. Drafts & schedules stored — publishing lands in Phase 18B.">
      {toast && (
        <div className="mb-3 px-3 py-2 rounded-lg text-sm font-semibold"
             style={{ backgroundColor: "#DCFCE7", color: colors.success }}
             data-testid="composer-toast">{toast}</div>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* LEFT — caption + schedule */}
        <Card className="p-5" testId="composer-left">
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-bold uppercase tracking-wider" style={{ color: colors.muted }}>Caption</label>
            <BtnGhost onClick={() => setAiOpen(true)} testId="composer-ai-suggest">
              <Sparkles size={14}/> AI Suggest
            </BtnGhost>
          </div>
          <textarea rows={8} value={caption} onChange={(e) => setCaption(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg text-sm mb-1"
                    style={{ border: `1px solid ${colors.border}` }}
                    data-testid="composer-caption"/>
          <div className="text-xs mb-4" style={{ color: overLimit ? colors.error : colors.muted }}>
            {caption.length} / {tightestLimit} chars (tightest network limit)
          </div>

          {hashtags.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-3" data-testid="composer-hashtags">
              {hashtags.map((h, i) => (
                <span key={i} className="text-xs px-2 py-0.5 rounded-full flex items-center gap-1"
                      style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
                  {h}
                  <button onClick={() => setHashtags(hashtags.filter((_, j) => j !== i))}>
                    <X size={10}/>
                  </button>
                </span>
              ))}
            </div>
          )}

          <label className="text-xs font-bold uppercase tracking-wider mb-1 block" style={{ color: colors.muted }}>Schedule</label>
          <input type="datetime-local" value={scheduledAt}
                 onChange={(e) => setScheduledAt(e.target.value)}
                 className="w-full px-3 py-2 rounded-lg text-sm mb-3"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid="composer-schedule-at"/>
          <label className="text-xs font-bold uppercase tracking-wider mb-1 block" style={{ color: colors.muted }}>First comment (optional)</label>
          <input value={firstComment} onChange={(e) => setFirstComment(e.target.value)}
                 className="w-full px-3 py-2 rounded-lg text-sm mb-4"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid="composer-first-comment"/>
          <div className="flex gap-2 flex-wrap">
            <BtnGhost onClick={() => save(false)} disabled={saving || !caption.trim()}
                     testId="composer-save-draft"><Save size={14}/> Save Draft</BtnGhost>
            <BtnPrimary onClick={() => save(true)} disabled={saving || !caption.trim()}
                        testId="composer-schedule">
              <Clock size={14}/> Schedule
            </BtnPrimary>
            <button disabled title="Available in Phase 18B"
                    className="px-3 py-2 rounded-xl text-sm font-semibold opacity-40 cursor-not-allowed"
                    style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                             border: `1px solid ${colors.border}` }}
                    data-testid="composer-publish-now-disabled">
              <Send size={14} className="inline"/> Publish Now (available in Phase 18B)
            </button>
          </div>
        </Card>

        {/* RIGHT — network picker + preview */}
        <Card className="p-5" testId="composer-right">
          <label className="text-xs font-bold uppercase tracking-wider mb-2 block" style={{ color: colors.muted }}>Target Networks</label>
          <div className="grid grid-cols-2 gap-2 mb-4" data-testid="composer-network-grid">
            {NETWORKS.map((n) => {
              const Icon = n.icon;
              const on = selected.has(n.key);
              return (
                <button key={n.key} onClick={() => toggle(n.key)}
                        className="flex items-center gap-2 p-3 rounded-xl text-sm font-semibold text-left"
                        style={{
                          backgroundColor: on ? colors.brandTertiary : colors.surfaceSecondary,
                          color: on ? colors.onBrandTertiary : colors.onSurface,
                          border: `1px solid ${on ? colors.brand : colors.border}`,
                        }}
                        data-testid={`composer-net-${n.key}`}>
                  <Icon size={16}/>
                  <div className="flex-1">
                    <div>{n.label}</div>
                    <div className="text-[10px] font-normal opacity-75 flex items-center gap-1">
                      <Plug size={9}/> Not connected
                    </div>
                  </div>
                </button>
              );
            })}
          </div>

          <label className="text-xs font-bold uppercase tracking-wider mb-2 block" style={{ color: colors.muted }}>Live Previews</label>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {[...selected].map((k) => {
              const n = NET_MAP[k]; const Icon = n.icon;
              return (
                <div key={k} className="p-3 rounded-xl" data-testid={`composer-preview-${k}`}
                     style={{ backgroundColor: colors.surfaceSecondary,
                              border: `1px solid ${colors.border}` }}>
                  <div className="flex items-center gap-2 mb-1">
                    <Icon size={14} style={{ color: colors.brand }}/>
                    <div className="text-xs font-bold" style={{ color: colors.onSurface }}>{n.label}</div>
                  </div>
                  <div className="text-sm whitespace-pre-wrap" style={{ color: colors.onSurface }}>
                    {(caption || "Your caption preview will appear here…").slice(0, n.limit)}
                  </div>
                  {hashtags.length > 0 && (
                    <div className="text-xs mt-1" style={{ color: colors.brand }}>
                      {hashtags.join(" ")}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      </div>

      {/* AI drawer */}
      {aiOpen && (
        <div className="fixed inset-0 z-40 flex items-end md:items-center justify-center p-2"
             style={{ backgroundColor: "rgba(0,0,0,0.55)" }}
             onClick={() => setAiOpen(false)}
             data-testid="composer-ai-modal">
          <div className="w-full max-w-lg rounded-2xl p-5"
               style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
               onClick={(e) => e.stopPropagation()}>
            <div className="text-base font-bold mb-3" style={{ color: colors.onSurface }}>
              <Sparkles size={16} className="inline mr-1"/> AI Caption Generator
            </div>
            <label className="text-xs font-bold uppercase tracking-wider mb-1 block" style={{ color: colors.muted }}>Topic</label>
            <textarea rows={3} value={aiTopic} onChange={(e) => setAiTopic(e.target.value)}
                      placeholder="e.g. Weekly pool service tips for AZ summer"
                      className="w-full px-3 py-2 rounded-lg text-sm mb-3"
                      style={{ border: `1px solid ${colors.border}` }}
                      data-testid="composer-ai-topic"/>
            <BtnPrimary onClick={doAi} disabled={aiBusy || !aiTopic.trim()}
                        testId="composer-ai-run">
              <Sparkles size={14}/> {aiBusy ? "Generating…" : "Generate"}
            </BtnPrimary>
            {aiResults && (
              <div className="mt-4 space-y-2">
                {aiResults.mocked && (
                  <div className="text-xs px-2 py-1 rounded font-bold uppercase tracking-wide inline-block"
                       style={{ backgroundColor: "#FEF3C7", color: "#92400E" }}
                       data-testid="composer-ai-mocked">MOCK MODE</div>
                )}
                {(aiResults.captions || []).map((c, i) => (
                  <div key={i} className="p-3 rounded-xl"
                       style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                       data-testid={`composer-ai-variant-${i}`}>
                    <div className="text-sm mb-2 whitespace-pre-wrap" style={{ color: colors.onSurface }}>{c}</div>
                    <button className="text-xs font-bold" style={{ color: colors.brand }}
                            onClick={() => { setCaption(c); setAiOpen(false); }}
                            data-testid={`composer-ai-insert-${i}`}>Insert →</button>
                  </div>
                ))}
                {aiResults.hashtags?.length > 0 && (
                  <div className="mt-2">
                    <button className="text-xs font-bold" style={{ color: colors.brand }}
                            onClick={() => { setHashtags([...new Set([...hashtags, ...aiResults.hashtags])]); setAiOpen(false); }}
                            data-testid="composer-ai-use-hashtags">
                      Use hashtags ({aiResults.hashtags.length})
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}

/* ═══════════ CALENDAR ═══════════ */
export function CalendarPage() {
  const [ym, setYm] = useState(() => { const d = new Date(); return { y: d.getFullYear(), m: d.getMonth() + 1 }; });
  const [data, setData] = useState({ posts: [] });
  useEffect(() => {
    api.get(`/social/calendar?year=${ym.y}&month=${ym.m}`).then(setData).catch(() => {});
  }, [ym]);
  const daysIn = new Date(ym.y, ym.m, 0).getDate();
  const firstDow = new Date(ym.y, ym.m - 1, 1).getDay();
  const cells = [...Array(firstDow).fill(null), ...Array.from({ length: daysIn }, (_, i) => i + 1)];
  const postsByDay = useMemo(() => {
    const m = {};
    (data.posts || []).forEach((p) => {
      if (!p.scheduled_at) return;
      const d = new Date(p.scheduled_at).getDate();
      (m[d] = m[d] || []).push(p);
    });
    return m;
  }, [data]);
  const monthName = new Date(ym.y, ym.m - 1, 1).toLocaleDateString([], { month: "long", year: "numeric" });

  return (
    <Section title="Content Calendar" subtitle="Drag & drop scheduled posts across days."
             right={
               <div className="flex gap-2">
                 <BtnGhost onClick={() => setYm(ym.m === 1 ? { y: ym.y - 1, m: 12 } : { y: ym.y, m: ym.m - 1 })}
                           testId="cal-prev"><ChevronLeft size={14}/></BtnGhost>
                 <div className="px-3 py-2 rounded-xl text-sm font-bold"
                      style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}>
                   {monthName}
                 </div>
                 <BtnGhost onClick={() => setYm(ym.m === 12 ? { y: ym.y + 1, m: 1 } : { y: ym.y, m: ym.m + 1 })}
                           testId="cal-next"><ChevronRight size={14}/></BtnGhost>
               </div>
             }>
      <Card className="p-3" testId="social-calendar">
        <div className="grid grid-cols-7 gap-1 mb-1">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
            <div key={d} className="text-xs font-bold text-center uppercase tracking-wide"
                 style={{ color: colors.muted }}>{d}</div>
          ))}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {cells.map((day, i) => (
            <div key={i}
                 onDragOver={(e) => e.preventDefault()}
                 onDrop={async (e) => {
                   const pid = e.dataTransfer.getData("text/plain");
                   if (!pid || !day) return;
                   const d = new Date(ym.y, ym.m - 1, day, 9, 0);
                   await api.post(`/social/posts/${pid}/reschedule`,
                                   { scheduled_at: d.toISOString() });
                   const r = await api.get(`/social/calendar?year=${ym.y}&month=${ym.m}`);
                   setData(r);
                 }}
                 className="rounded-lg p-1 min-h-[92px]"
                 style={{ backgroundColor: day ? colors.surface : "transparent",
                          border: day ? `1px solid ${colors.border}` : "none" }}
                 data-testid={day ? `cal-day-${day}` : `cal-empty-${i}`}>
              {day && (
                <>
                  <div className="text-xs font-bold mb-1" style={{ color: colors.muted }}>{day}</div>
                  {(postsByDay[day] || []).map((p) => (
                    <div key={p.id}
                         draggable
                         onDragStart={(e) => e.dataTransfer.setData("text/plain", p.id)}
                         className="text-[10px] p-1 rounded mb-1 cursor-grab active:cursor-grabbing"
                         style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
                         title={p.caption_preview}
                         data-testid={`cal-post-${p.id}`}>
                      {p.networks.slice(0, 3).join(" · ")}
                    </div>
                  ))}
                </>
              )}
            </div>
          ))}
        </div>
      </Card>
    </Section>
  );
}

/* ═══════════ MEDIA LIBRARY ═══════════ */
export function LibraryPage() {
  const [items, setItems] = useState([]);
  const [filter, setFilter] = useState("");
  const load = async () => setItems(await api.get(`/social/media${filter ? `?type=${filter}` : ""}`));
  useEffect(() => { load(); }, [filter]);
  const handleFiles = async (files) => {
    for (const f of files) {
      const b64 = await new Promise((res) => {
        const r = new FileReader(); r.onload = () => res(r.result); r.readAsDataURL(f);
      });
      await api.post("/social/media", { url: b64, mime: f.type, size_bytes: f.size, tags: [] });
    }
    load();
  };
  return (
    <Section title="Media Library" subtitle="Upload images/videos and tag them for reuse."
             right={
               <div className="flex gap-2">
                 {["", "image", "video"].map((f) => (
                   <button key={f || "all"} onClick={() => setFilter(f)}
                           className="px-3 py-2 rounded-xl text-xs font-bold uppercase"
                           style={{ backgroundColor: filter === f ? colors.brand : colors.surface,
                                    color: filter === f ? "#fff" : colors.onSurface,
                                    border: `1px solid ${colors.border}` }}
                           data-testid={`lib-filter-${f || "all"}`}>
                     {f || "All"}
                   </button>
                 ))}
                 <label className="px-3 py-2 rounded-xl text-sm font-bold text-white flex items-center gap-1 cursor-pointer"
                        style={{ background: brandGradientCss }}>
                   <Upload size={14}/> Upload
                   <input type="file" multiple accept="image/*,video/*" className="hidden"
                          onChange={(e) => handleFiles([...e.target.files])}
                          data-testid="lib-upload-input"/>
                 </label>
               </div>
             }>
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        {items.map((m) => (
          <Card key={m.id} className="p-2" testId={`lib-item-${m.id}`}>
            {m.mime?.startsWith("image/") ? (
              <img src={m.url} alt="" className="w-full h-24 object-cover rounded-lg"/>
            ) : (
              <div className="w-full h-24 flex items-center justify-center rounded-lg"
                   style={{ backgroundColor: colors.surfaceSecondary }}>
                <ImageIcon size={20} style={{ color: colors.muted }}/>
              </div>
            )}
            <div className="text-[10px] mt-1 truncate" style={{ color: colors.muted }}>{m.mime}</div>
            <button onClick={async () => { await api.del(`/social/media/${m.id}`); load(); }}
                    className="text-xs mt-1 font-semibold" style={{ color: colors.error }}
                    data-testid={`lib-del-${m.id}`}>
              <Trash2 size={11} className="inline"/> Delete
            </button>
          </Card>
        ))}
        {items.length === 0 && (
          <div className="col-span-full text-sm" style={{ color: colors.muted }} data-testid="lib-empty">
            No media uploaded yet.
          </div>
        )}
      </div>
    </Section>
  );
}

/* ═══════════ DRAFTS/SCHEDULED LIST ═══════════ */
export function DraftsPage() {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("");
  const navigate = useNavigate();
  const load = async () => setRows(await api.get(`/social/posts${status ? `?status=${status}` : ""}`));
  useEffect(() => { load(); }, [status]);
  const dup = async (id) => { await api.post(`/social/posts/${id}/duplicate`); load(); };
  const del = async (id) => { if (confirm("Delete post?")) { await api.del(`/social/posts/${id}`); load(); } };
  return (
    <Section title="Drafts & Scheduled" subtitle="Manage everything that's not yet published."
             right={
               <select value={status} onChange={(e) => setStatus(e.target.value)}
                       className="px-3 py-2 rounded-xl text-sm"
                       style={{ border: `1px solid ${colors.border}` }}
                       data-testid="drafts-status-filter">
                 <option value="">All</option>
                 <option value="draft">Draft</option>
                 <option value="scheduled">Scheduled</option>
                 <option value="published">Published</option>
                 <option value="failed">Failed</option>
               </select>
             }>
      <Card className="overflow-x-auto" testId="drafts-table">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
              <th className="text-left p-3 font-semibold">Caption</th>
              <th className="text-left p-3 font-semibold">Networks</th>
              <th className="text-left p-3 font-semibold">Schedule</th>
              <th className="text-left p-3 font-semibold">Status</th>
              <th className="text-right p-3 font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${colors.border}` }}
                  data-testid={`draft-row-${r.id}`}>
                <td className="p-3 max-w-md" style={{ color: colors.onSurface }}>
                  <div className="line-clamp-2">{r.caption || "—"}</div>
                </td>
                <td className="p-3 text-xs" style={{ color: colors.muted }}>
                  {(r.networks || []).join(", ")}
                </td>
                <td className="p-3 text-xs" style={{ color: colors.onSurfaceSecondary }}>
                  {r.scheduled_at ? new Date(r.scheduled_at).toLocaleString() : "—"}
                </td>
                <td className="p-3">
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase"
                        style={{
                          backgroundColor: r.status === "scheduled" ? "#DBEAFE"
                                          : r.status === "published" ? "#DCFCE7"
                                          : r.status === "failed" ? "#FEE2E2"
                                          : colors.surfaceSecondary,
                          color: r.status === "scheduled" ? "#1E40AF"
                                : r.status === "published" ? colors.success
                                : r.status === "failed" ? colors.error
                                : colors.muted,
                        }}>
                    {r.status}
                  </span>
                </td>
                <td className="p-3 text-right">
                  <div className="flex gap-1 justify-end">
                    <button onClick={() => dup(r.id)} className="p-1" style={{ color: colors.brand }}
                            data-testid={`draft-dup-${r.id}`}><Copy size={13}/></button>
                    <button onClick={() => del(r.id)} className="p-1" style={{ color: colors.error }}
                            data-testid={`draft-del-${r.id}`}><Trash2 size={13}/></button>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={5} className="p-6 text-center text-sm" style={{ color: colors.muted }}
                      data-testid="drafts-empty">No posts yet.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </Section>
  );
}
