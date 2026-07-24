/**
 * Phase 18A.1 — Social Suite extras: Approvals, Bulk CSV Upload,
 * Short Links, Brand Kit. Admin-only via router-level <AdminOnly> gate.
 */
import React, { useEffect, useRef, useState } from 'react';
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import {
  CheckCircle2, XCircle, MessageSquare, Send, Upload, Download,
  Link as LinkIcon, BarChart2, Palette, Save, Trash2, FolderPlus,
} from "lucide-react";

const Card = ({ children, className = "", testId }) => (
  <div className={`rounded-2xl ${className}`}
       style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
       data-testid={testId}>{children}</div>
);
const Section = ({ title, subtitle, right, children, testId }) => (
  <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid={testId}>
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
  <button className="px-3 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50 flex items-center gap-1"
          style={{ background: brandGradientCss }} data-testid={testId} {...rest}>{children}</button>
);
const BtnGhost = ({ children, testId, ...rest }) => (
  <button className="px-3 py-2 rounded-xl text-sm font-semibold flex items-center gap-1"
          style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface,
                   border: `1px solid ${colors.border}` }}
          data-testid={testId} {...rest}>{children}</button>
);
const StatusPill = ({ status }) => {
  const map = {
    pending: { bg: "#FEF3C7", fg: "#92400E" },
    approved: { bg: "#DCFCE7", fg: "#166534" },
    rejected: { bg: "#FEE2E2", fg: "#991B1B" },
    changes_requested: { bg: "#DBEAFE", fg: "#1E40AF" },
  };
  const c = map[status] || { bg: colors.surfaceSecondary, fg: colors.muted };
  return (
    <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase"
          style={{ backgroundColor: c.bg, color: c.fg }}>{status?.replace("_", " ")}</span>
  );
};

/* ═══════════ APPROVALS QUEUE ═══════════ */
export function ApprovalsPage() {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("pending");
  const [busyId, setBusyId] = useState("");
  const [comment, setComment] = useState({});
  const [threadOpen, setThreadOpen] = useState(null);
  const [threadDraft, setThreadDraft] = useState("");

  const load = async () => {
    const r = await api.get(`/social/approvals?status=${encodeURIComponent(status)}`);
    setRows(r);
  };
  useEffect(() => { load(); /* eslint-disable-line */ }, [status]);

  const act = async (id, path, needsComment = false) => {
    const text = comment[id] || "";
    if (needsComment && !text.trim()) { alert("Comment required."); return; }
    setBusyId(id);
    try {
      await api.post(`/social/posts/${id}/${path}`, { comment: text });
      setComment((c) => ({ ...c, [id]: "" }));
      await load();
    } catch (e) { alert(e.message); }
    finally { setBusyId(""); }
  };

  const addThread = async (id) => {
    if (!threadDraft.trim()) return;
    await api.post(`/social/posts/${id}/comment`, { text: threadDraft });
    setThreadDraft("");
    await load();
  };

  return (
    <Section title="Approval Queue" testId="approvals-page"
             subtitle="Review posts submitted by your marketing team. Approve, reject, or request changes."
             right={
               <select value={status} onChange={(e) => setStatus(e.target.value)}
                       className="px-3 py-2 rounded-xl text-sm"
                       style={{ border: `1px solid ${colors.border}`, background: colors.surface, color: colors.onSurface }}
                       data-testid="approvals-status-filter">
                 <option value="pending">Pending</option>
                 <option value="approved">Approved</option>
                 <option value="rejected">Rejected</option>
                 <option value="changes_requested">Changes Requested</option>
               </select>
             }>
      <div className="space-y-3">
        {rows.map((a) => (
          <Card key={a.id} className="p-4" testId={`approval-${a.id}`}>
            <div className="flex items-start gap-4 flex-wrap">
              <div className="flex-1 min-w-[240px]">
                <div className="flex items-center gap-2 mb-1">
                  <StatusPill status={a.status} />
                  <span className="text-xs" style={{ color: colors.muted }}>
                    submitted {a.submitted_at ? new Date(a.submitted_at).toLocaleString() : "—"}
                  </span>
                </div>
                <div className="text-sm whitespace-pre-wrap" style={{ color: colors.onSurface }}
                     data-testid={`approval-caption-${a.id}`}>
                  {a.post_preview?.caption || "(no caption)"}
                </div>
                <div className="text-xs mt-1" style={{ color: colors.muted }}>
                  Networks: {(a.post_preview?.networks || []).join(", ") || "—"}
                  {a.post_preview?.scheduled_at ? ` · scheduled ${new Date(a.post_preview.scheduled_at).toLocaleString()}` : ""}
                </div>
                {a.comment && (
                  <div className="text-xs mt-2 p-2 rounded"
                       style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface }}>
                    <b>Last decision:</b> {a.comment}
                  </div>
                )}
              </div>
              {a.status === "pending" && (
                <div className="flex flex-col gap-2 w-full md:w-72">
                  <textarea rows={2} value={comment[a.post_id] || ""}
                            placeholder="Comment (required for reject / request changes)"
                            onChange={(e) => setComment((c) => ({ ...c, [a.post_id]: e.target.value }))}
                            className="px-2 py-1 rounded-lg text-xs"
                            style={{ border: `1px solid ${colors.border}` }}
                            data-testid={`approval-comment-${a.id}`}/>
                  <div className="flex gap-1 flex-wrap">
                    <BtnPrimary onClick={() => act(a.post_id, "approve")}
                                disabled={busyId === a.post_id}
                                testId={`approval-approve-${a.id}`}>
                      <CheckCircle2 size={13}/> Approve
                    </BtnPrimary>
                    <BtnGhost onClick={() => act(a.post_id, "request-changes", true)}
                              disabled={busyId === a.post_id}
                              testId={`approval-changes-${a.id}`}>
                      <MessageSquare size={13}/> Changes
                    </BtnGhost>
                    <BtnGhost onClick={() => act(a.post_id, "reject", true)}
                              disabled={busyId === a.post_id}
                              testId={`approval-reject-${a.id}`}>
                      <XCircle size={13}/> Reject
                    </BtnGhost>
                  </div>
                </div>
              )}
            </div>
            <div className="mt-3 pt-3" style={{ borderTop: `1px solid ${colors.border}` }}>
              <button onClick={() => setThreadOpen(threadOpen === a.id ? null : a.id)}
                      className="text-xs font-bold" style={{ color: colors.brand }}
                      data-testid={`approval-thread-toggle-${a.id}`}>
                Discussion ({(a.comment_thread || []).length})
              </button>
              {threadOpen === a.id && (
                <div className="mt-2 space-y-2">
                  {(a.comment_thread || []).map((c, i) => (
                    <div key={i} className="text-xs p-2 rounded"
                         style={{ backgroundColor: colors.surfaceSecondary }}>
                      <b style={{ color: colors.onSurface }}>{c.user_id?.slice(0, 8)}</b>
                      <span className="ml-1" style={{ color: colors.muted }}>{new Date(c.at).toLocaleString()}</span>
                      <div style={{ color: colors.onSurface }}>{c.text}</div>
                    </div>
                  ))}
                  <div className="flex gap-2">
                    <input value={threadDraft} onChange={(e) => setThreadDraft(e.target.value)}
                           placeholder="Add a comment…"
                           className="flex-1 px-2 py-1 rounded-lg text-xs"
                           style={{ border: `1px solid ${colors.border}` }}
                           data-testid={`approval-thread-input-${a.id}`}/>
                    <BtnPrimary onClick={() => addThread(a.post_id)} testId={`approval-thread-send-${a.id}`}>
                      <Send size={12}/>
                    </BtnPrimary>
                  </div>
                </div>
              )}
            </div>
          </Card>
        ))}
        {rows.length === 0 && (
          <Card className="p-8 text-center" testId="approvals-empty">
            <div style={{ color: colors.muted }}>Nothing here yet. Submit a post from the Composer.</div>
          </Card>
        )}
      </div>
    </Section>
  );
}

/* ═══════════ BULK CSV UPLOAD ═══════════ */
const CSV_HEADER = "caption,networks,scheduled_at,media_urls,hashtags,first_comment";
const CSV_SAMPLE = [
  CSV_HEADER,
  "Splash into July with 20% off pool cleaning,facebook;instagram,2026-07-20T09:00:00Z,https://cdn.example/img.jpg,#pool;#service,",
  "New landscape design consultations,linkedin,,,,",
].join("\n");

export function BulkUploadPage() {
  const [rows, setRows] = useState([]);
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState([]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef();

  const parseLocal = (text) => {
    const lines = text.split(/\r?\n/).filter((l) => l.trim());
    if (lines.length < 2) { setPreview([]); return; }
    const header = lines[0].split(",").map((h) => h.trim());
    const parsed = lines.slice(0, 21).slice(1).map((ln, i) => {
      const parts = ln.split(",");
      const obj = { _row: i + 2 };
      header.forEach((h, j) => obj[h] = (parts[j] || "").trim());
      return obj;
    });
    setPreview(parsed);
  };

  const onFile = async (f) => {
    setFile(f); setResult(null);
    const text = await f.text();
    parseLocal(text);
  };

  const upload = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const token = localStorage.getItem("token");
      const backend = process.env.REACT_APP_BACKEND_URL;
      const tenantSlug = localStorage.getItem("tenant_slug") || "";
      const r = await fetch(`${backend}/api/social/posts/bulk`, {
        method: "POST",
        body: fd,
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(tenantSlug ? { "X-Tenant-Slug": tenantSlug } : {}),
        },
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Upload failed");
      setResult(data);
    } catch (e) { alert(e.message); }
    finally { setBusy(false); }
  };

  const downloadTemplate = () => {
    const blob = new Blob([CSV_SAMPLE], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "social-bulk-template.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Section title="Bulk Upload" testId="bulk-upload-page"
             subtitle="Import up to 500 posts at once via CSV. Rows fail-open — errors are reported per row."
             right={
               <BtnGhost onClick={downloadTemplate} testId="bulk-download-template">
                 <Download size={13}/> CSV Template
               </BtnGhost>
             }>
      <Card className="p-6" testId="bulk-drop-card">
        <div className="text-center">
          <input ref={inputRef} type="file" accept=".csv,text/csv" className="hidden"
                 onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
                 data-testid="bulk-file-input"/>
          <button onClick={() => inputRef.current?.click()}
                  className="px-5 py-3 rounded-xl text-sm font-bold text-white"
                  style={{ background: brandGradientCss }}
                  data-testid="bulk-choose-btn">
            <Upload size={14} className="inline mr-1"/> Choose CSV
          </button>
          <div className="text-xs mt-2" style={{ color: colors.muted }}>
            {file ? file.name : "No file selected"}
          </div>
        </div>
      </Card>

      {preview.length > 0 && (
        <Card className="mt-4 overflow-x-auto" testId="bulk-preview-table">
          <table className="w-full text-xs">
            <thead>
              <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
                <th className="p-2 text-left">Row</th>
                <th className="p-2 text-left">Caption</th>
                <th className="p-2 text-left">Networks</th>
                <th className="p-2 text-left">Scheduled</th>
                <th className="p-2 text-left">Notes</th>
              </tr>
            </thead>
            <tbody>
              {preview.map((p) => {
                const errs = [];
                if (!(p.caption || "").trim()) errs.push("empty caption");
                if (!(p.networks || "").trim()) errs.push("no networks");
                return (
                  <tr key={p._row} style={{ borderBottom: `1px solid ${colors.border}` }}
                      data-testid={`bulk-preview-row-${p._row}`}>
                    <td className="p-2" style={{ color: colors.muted }}>{p._row}</td>
                    <td className="p-2 max-w-md truncate" style={{ color: colors.onSurface }}>{p.caption}</td>
                    <td className="p-2" style={{ color: colors.onSurface }}>{p.networks}</td>
                    <td className="p-2" style={{ color: colors.muted }}>{p.scheduled_at || "—"}</td>
                    <td className="p-2 text-xs" style={{ color: errs.length ? colors.error : colors.success }}>
                      {errs.length ? errs.join(", ") : "OK"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {preview.length >= 20 && (
            <div className="text-xs p-2" style={{ color: colors.muted }}>
              (Preview truncated at 20 rows — full file will be uploaded.)
            </div>
          )}
        </Card>
      )}

      {file && (
        <div className="mt-4 flex justify-end">
          <BtnPrimary onClick={upload} disabled={busy} testId="bulk-submit">
            <Send size={14}/> {busy ? "Uploading…" : "Create posts"}
          </BtnPrimary>
        </div>
      )}

      {result && (
        <Card className="mt-4 p-4" testId="bulk-result">
          <div className="text-sm font-bold" style={{ color: colors.success }}>
            {result.created} posts created
          </div>
          {result.errors?.length > 0 && (
            <div className="mt-2 text-xs" style={{ color: colors.error }}>
              <div className="font-bold mb-1">Errors ({result.errors.length})</div>
              <ul className="list-disc pl-5">
                {result.errors.map((e, i) => (
                  <li key={i}>Row {e.row}: {e.msg}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}
    </Section>
  );
}

/* ═══════════ SHORT LINKS ═══════════ */
export function ShortLinksPage() {
  const [rows, setRows] = useState([]);
  const [target, setTarget] = useState("");
  const [alias, setAlias] = useState("");
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState(null);

  const load = async () => setRows(await api.get("/social/short-links"));
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!target.trim()) return;
    setBusy(true);
    try {
      await api.post("/social/short-links", { target_url: target, alias: alias || undefined });
      setTarget(""); setAlias("");
      await load();
    } catch (e) { alert(e.message); }
    finally { setBusy(false); }
  };

  const del = async (id) => {
    if (!confirm("Delete this short link?")) return;
    await api.del(`/social/short-links/${id}`);
    await load();
  };

  const openStats = async (id) => setStats(await api.get(`/social/short-links/${id}/stats`));

  const copy = (u) => { navigator.clipboard?.writeText(u); };

  return (
    <Section title="Short Links" testId="short-links-page"
             subtitle="Track every URL you share. Redirects run through /api/r/{alias}.">
      <Card className="p-4 mb-4" testId="short-links-create">
        <div className="grid grid-cols-1 md:grid-cols-6 gap-2">
          <input placeholder="https://example.com/campaign"
                 value={target} onChange={(e) => setTarget(e.target.value)}
                 className="md:col-span-3 px-3 py-2 rounded-lg text-sm"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid="short-link-target"/>
          <input placeholder="custom-alias (optional)"
                 value={alias} onChange={(e) => setAlias(e.target.value)}
                 className="md:col-span-2 px-3 py-2 rounded-lg text-sm"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid="short-link-alias"/>
          <BtnPrimary onClick={create} disabled={busy || !target.trim()} testId="short-link-create-btn">
            <LinkIcon size={13}/> Shorten
          </BtnPrimary>
        </div>
      </Card>
      <Card className="overflow-x-auto" testId="short-links-table">
        <table className="w-full text-sm">
          <thead>
            <tr style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}>
              <th className="p-3 text-left font-semibold">Short URL</th>
              <th className="p-3 text-left font-semibold">Destination</th>
              <th className="p-3 text-left font-semibold">Clicks</th>
              <th className="p-3 text-right font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${colors.border}` }}
                  data-testid={`short-link-row-${r.id}`}>
                <td className="p-3 font-mono text-xs" style={{ color: colors.brand }}>{r.short_url}</td>
                <td className="p-3 max-w-md truncate" style={{ color: colors.onSurface }}>{r.target_url}</td>
                <td className="p-3" style={{ color: colors.onSurface }}>{r.clicks_total}</td>
                <td className="p-3 text-right">
                  <div className="flex gap-2 justify-end">
                    <BtnGhost onClick={() => copy(r.short_url)} testId={`short-link-copy-${r.id}`}>Copy</BtnGhost>
                    <BtnGhost onClick={() => openStats(r.id)} testId={`short-link-stats-${r.id}`}>
                      <BarChart2 size={13}/> Stats
                    </BtnGhost>
                    <BtnGhost onClick={() => del(r.id)} testId={`short-link-del-${r.id}`}>
                      <Trash2 size={13}/>
                    </BtnGhost>
                  </div>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={4} className="p-6 text-center text-sm" style={{ color: colors.muted }}
                      data-testid="short-links-empty">
                No short links yet. Create one above.
              </td></tr>
            )}
          </tbody>
        </table>
      </Card>

      {stats && (
        <div className="fixed inset-0 z-40 flex items-center justify-center p-3"
             style={{ backgroundColor: "rgba(0,0,0,0.55)" }} onClick={() => setStats(null)}
             data-testid="short-link-stats-modal">
          <Card className="w-full max-w-lg p-5" testId="short-link-stats-card">
            <div className="flex items-center justify-between mb-3">
              <div className="font-bold" style={{ color: colors.onSurface }}>Link stats</div>
              <button onClick={() => setStats(null)} style={{ color: colors.muted }}>✕</button>
            </div>
            <div className="text-xs font-mono mb-1" style={{ color: colors.brand }}>{stats.short_url}</div>
            <div className="text-xs mb-3 truncate" style={{ color: colors.muted }}>→ {stats.target_url}</div>
            <div className="text-4xl font-bold" style={{ color: colors.onSurface }}
                 data-testid="short-link-stats-clicks">{stats.clicks}</div>
            <div className="text-xs mb-4" style={{ color: colors.muted }}>total clicks</div>
            <div className="text-xs font-bold mb-1" style={{ color: colors.muted }}>Top referrers</div>
            <div className="space-y-1">
              {(stats.top_referrers || []).map((t) => (
                <div key={t.referrer} className="flex justify-between text-xs">
                  <span style={{ color: colors.onSurface }}>{t.referrer}</span>
                  <span style={{ color: colors.muted }}>{t.count}</span>
                </div>
              ))}
              {stats.top_referrers?.length === 0 && (
                <div className="text-xs" style={{ color: colors.muted }}>No clicks yet.</div>
              )}
            </div>
          </Card>
        </div>
      )}
    </Section>
  );
}

/* ═══════════ BRAND KIT ═══════════ */
export function BrandKitPage() {
  const [kit, setKit] = useState({});
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState("");
  useEffect(() => { api.get("/social/brand-kit").then(setKit).catch(() => {}); }, []);
  const save = async () => {
    setBusy(true);
    try {
      const saved = await api.put("/social/brand-kit", {
        primary_color: kit.primary_color,
        secondary_color: kit.secondary_color,
        accent_color: kit.accent_color,
        logo_url: kit.logo_url,
        font_family: kit.font_family,
        tagline: kit.tagline,
      });
      setKit(saved);
      setToast("Saved"); setTimeout(() => setToast(""), 2000);
    } catch (e) { alert(e.message); }
    finally { setBusy(false); }
  };
  return (
    <Section title="Brand Kit" testId="brand-kit-page"
             subtitle="Central colors, logo, and voice for every post you compose."
             right={<BtnPrimary onClick={save} disabled={busy} testId="brand-kit-save">
                     <Save size={13}/> Save
                    </BtnPrimary>}>
      {toast && (
        <div className="mb-3 px-3 py-2 rounded-lg text-sm font-semibold inline-block"
             style={{ backgroundColor: "#DCFCE7", color: colors.success }}
             data-testid="brand-kit-toast">{toast}</div>
      )}
      <Card className="p-6" testId="brand-kit-form">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { k: "primary_color", label: "Primary color" },
            { k: "secondary_color", label: "Secondary color" },
            { k: "accent_color", label: "Accent color" },
          ].map((f) => (
            <div key={f.k}>
              <label className="text-xs font-bold uppercase tracking-wider block mb-1"
                     style={{ color: colors.muted }}>{f.label}</label>
              <div className="flex items-center gap-2">
                <input type="color" value={kit[f.k] || "#2563EB"}
                       onChange={(e) => setKit({ ...kit, [f.k]: e.target.value })}
                       className="w-10 h-10 rounded-lg"
                       data-testid={`brand-color-${f.k}`}/>
                <input type="text" value={kit[f.k] || ""}
                       onChange={(e) => setKit({ ...kit, [f.k]: e.target.value })}
                       className="flex-1 px-2 py-2 rounded-lg text-sm"
                       style={{ border: `1px solid ${colors.border}` }}/>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-bold uppercase tracking-wider block mb-1"
                   style={{ color: colors.muted }}>Logo URL</label>
            <input value={kit.logo_url || ""}
                   onChange={(e) => setKit({ ...kit, logo_url: e.target.value })}
                   placeholder="https://cdn.plofv.com/logo.png"
                   className="w-full px-3 py-2 rounded-lg text-sm"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid="brand-logo-url"/>
          </div>
          <div>
            <label className="text-xs font-bold uppercase tracking-wider block mb-1"
                   style={{ color: colors.muted }}>Font family</label>
            <input value={kit.font_family || ""}
                   onChange={(e) => setKit({ ...kit, font_family: e.target.value })}
                   placeholder="Inter, Space Grotesk, ..."
                   className="w-full px-3 py-2 rounded-lg text-sm"
                   style={{ border: `1px solid ${colors.border}` }}
                   data-testid="brand-font"/>
          </div>
        </div>
        <div className="mt-4">
          <label className="text-xs font-bold uppercase tracking-wider block mb-1"
                 style={{ color: colors.muted }}>Tagline</label>
          <input value={kit.tagline || ""}
                 onChange={(e) => setKit({ ...kit, tagline: e.target.value })}
                 placeholder="Crystal-clear water, effortless yards."
                 className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ border: `1px solid ${colors.border}` }}
                 data-testid="brand-tagline"/>
        </div>
        <div className="mt-6 p-4 rounded-xl" data-testid="brand-preview"
             style={{ background: `linear-gradient(135deg, ${kit.primary_color || "#2563EB"}, ${kit.secondary_color || "#0EA5E9"})`,
                      color: "#fff" }}>
          <div className="text-xs uppercase opacity-80">Live preview</div>
          <div className="font-bold text-2xl mt-1"
               style={{ fontFamily: kit.font_family || undefined }}>
            {kit.tagline || "Add a tagline to see your brand voice ✨"}
          </div>
          {kit.logo_url && (
            <img src={kit.logo_url} alt="brand" className="h-10 mt-3 rounded"
                 onError={(e) => { e.currentTarget.style.display = "none"; }}/>
          )}
        </div>
      </Card>
    </Section>
  );
}
