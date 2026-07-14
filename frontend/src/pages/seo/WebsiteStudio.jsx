/**
 * Phase 17C.2 · Website Studio — page builder + AI auto-fill + publish.
 * List view at /admin/seo/studio, editor at /admin/seo/studio/:id.
 */
import React, { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Plus, Sparkles, Eye, Download, Send, FileText, X,
  Trash2, RefreshCw,
} from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

const SECTION_TYPES = [
  "hero", "features", "benefits", "services",
  "testimonials", "faq", "cta", "local_business_schema",
];

/* ─── LIST ──────────────────────────────────────────────────────────── */
export default function WebsiteStudio() {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    title: "", slug: "", target_keyword: "",
    meta_description: "", business_context: "",
  });
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/seo/studio/pages");
      setRows(r.items || []);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const create = async () => {
    setError("");
    setCreating(true);
    try {
      const p = await api.post("/seo/studio/pages", { ...form, sections: [] });
      setShowNew(false);
      nav(`/admin/seo/studio/${p.id}`);
    } catch (e) {
      setError(e.message || "Failed");
    } finally { setCreating(false); }
  };

  const slugify = (s) =>
    s.toLowerCase().trim()
     .replace(/[^a-z0-9\s-]/g, "")
     .replace(/\s+/g, "-").replace(/-+/g, "-").slice(0, 60);

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6"
         data-testid="website-studio-page">
      <div className="flex items-center gap-3 mb-6">
        <div className="flex-1">
          <h1 className="text-2xl font-bold flex items-center gap-2"
              style={{ color: colors.onSurface }}>
            <FileText size={22} style={{ color: colors.brand }} />
            Website Studio
          </h1>
          <p className="text-xs" style={{ color: colors.muted }}>
            Build SEO landing pages with AI-generated sections, then export
            or share the published URL.
          </p>
        </div>
        <button onClick={() => setShowNew(true)}
                className="px-4 py-2 text-sm font-bold rounded-xl flex items-center gap-2"
                style={{ background: brandGradientCss, color: "#fff" }}
                data-testid="studio-new-page-btn">
          <Plus size={14} /> New page
        </button>
      </div>

      {loading ? (
        <div className="p-8 text-center text-sm" style={{ color: colors.muted }}>
          Loading…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl p-10 text-center"
             style={{ backgroundColor: colors.surface,
                      border: `1px dashed ${colors.border}`,
                      color: colors.muted }}>
          No Studio pages yet.
        </div>
      ) : (
        <div className="rounded-2xl overflow-hidden"
             style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}>
          {rows.map((r, i) => (
            <div key={r.id}
                 onClick={() => nav(`/admin/seo/studio/${r.id}`)}
                 className="p-4 cursor-pointer flex items-center gap-3"
                 style={{ borderTop: i ? `1px solid ${colors.border}` : "none" }}
                 data-testid={`studio-row-${r.id}`}>
              <div className="flex-1 min-w-0">
                <div className="font-bold" style={{ color: colors.onSurface }}>
                  {r.title}
                </div>
                <div className="text-xs" style={{ color: colors.muted }}>
                  /{r.slug} · {r.target_keyword || "no keyword"}
                </div>
              </div>
              <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                    style={{
                      backgroundColor:
                        r.status === "published" ? "#DCFCE7" : "#FEF3C7",
                      color:
                        r.status === "published" ? "#166534" : "#92400E",
                    }}>
                {r.status}
              </span>
            </div>
          ))}
        </div>
      )}

      {showNew && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
             style={{ backgroundColor: "rgba(0,0,0,0.5)" }}>
          <div className="rounded-2xl p-6 max-w-md w-full"
               style={{ backgroundColor: colors.surface }}
               data-testid="studio-new-modal">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-bold">New page</h2>
              <button onClick={() => setShowNew(false)}>
                <X size={18} />
              </button>
            </div>
            {error && (
              <div className="text-xs mb-3 p-2 rounded-lg"
                   style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}>
                {error}
              </div>
            )}
            {[
              ["title", "Page title", "text"],
              ["slug", "URL slug (lowercase-with-dashes)", "text"],
              ["target_keyword", "Target keyword", "text"],
              ["meta_description", "Meta description", "text"],
              ["business_context", "Business context (used by AI)", "textarea"],
            ].map(([k, l, tp]) => (
              <label key={k} className="block mb-3">
                <div className="text-xs font-bold mb-1"
                     style={{ color: colors.muted }}>{l}</div>
                {tp === "textarea" ? (
                  <textarea rows={3} value={form[k] || ""}
                     onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                     className="w-full p-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`studio-new-${k}`} />
                ) : (
                  <input type="text" value={form[k] || ""}
                     onChange={(e) => setForm({
                       ...form,
                       [k]: k === "slug" ? slugify(e.target.value) : e.target.value,
                       ...(k === "title" && !form.slug
                            ? { slug: slugify(e.target.value) } : {}),
                     })}
                     className="w-full p-2 rounded-lg text-sm"
                     style={{ backgroundColor: colors.background,
                              border: `1px solid ${colors.border}` }}
                     data-testid={`studio-new-${k}`} />
                )}
              </label>
            ))}
            <button onClick={create} disabled={creating || !form.title || !form.slug}
                    className="w-full py-3 text-sm font-bold rounded-xl disabled:opacity-50"
                    style={{ background: brandGradientCss, color: "#fff" }}
                    data-testid="studio-new-submit">
              {creating ? "Creating…" : "Create page"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── EDITOR ────────────────────────────────────────────────────────── */
export function WebsiteStudioEditor() {
  const { id } = useParams();
  const nav = useNavigate();
  const [page, setPage] = useState(null);
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [autofilling, setAutofilling] = useState(false);
  const [message, setMessage] = useState("");

  const load = async () => {
    const p = await api.get(`/seo/studio/pages/${id}`);
    setPage(p);
  };
  useEffect(() => { load(); }, [id]);

  if (!page) return (
    <div className="p-6 text-sm" style={{ color: colors.muted }}>Loading…</div>
  );

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/seo/studio/pages/${id}`, {
        title: page.title,
        target_keyword: page.target_keyword,
        meta_description: page.meta_description,
        business_context: page.business_context,
        sections: page.sections,
      });
      setMessage("Saved");
    } finally { setSaving(false); }
    setTimeout(() => setMessage(""), 2500);
  };

  const publish = async () => {
    setPublishing(true);
    try {
      const r = await api.post(`/seo/studio/pages/${id}/publish`);
      await load();
      setMessage(`Published · ${r.preview_url}`);
    } finally { setPublishing(false); }
  };

  const autoFill = async () => {
    if (!page.business_context || !page.target_keyword) {
      setMessage("Enter business context + target keyword first.");
      return;
    }
    setAutofilling(true);
    try {
      const r = await api.post(`/seo/studio/pages/${id}/auto-fill`, {
        business_context: page.business_context,
        target_keyword: page.target_keyword,
      });
      if (r.mocked) setMessage("AI unavailable — no content generated.");
      else setMessage(`AI generated ${r.count} sections.`);
      await load();
    } finally { setAutofilling(false); }
  };

  const addSection = (type) => {
    setPage({ ...page,
      sections: [...(page.sections || []),
                  { type, heading: "", subheading: "", body: "", items: [] }],
    });
  };

  const updateSection = (idx, patch) => {
    const s = [...page.sections];
    s[idx] = { ...s[idx], ...patch };
    setPage({ ...page, sections: s });
  };

  const removeSection = (idx) => {
    setPage({ ...page,
      sections: page.sections.filter((_, i) => i !== idx),
    });
  };

  const download = async (format) => {
    const base = process.env.REACT_APP_BACKEND_URL;
    const url = `${base}/api/seo/studio/pages/${id}/export?format=${format}`;
    const token = localStorage.getItem("token") || "";
    const tenant = localStorage.getItem("tenant_slug") || "";
    const r = await fetch(url, {
      headers: { Authorization: `Bearer ${token}`, "X-Tenant-Slug": tenant },
    });
    const blob = await r.blob();
    const dl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = dl;
    a.download = `studio-${page.slug}.${format === "markdown" ? "md" : format}`;
    a.click();
    URL.revokeObjectURL(dl);
  };

  const previewUrl = `${process.env.REACT_APP_BACKEND_URL}/api/preview/studio/${page.slug}`;

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6"
         data-testid="studio-editor-page">
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <button onClick={() => nav("/admin/seo/studio")}
                className="p-2 rounded-lg"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <input value={page.title || ""}
             onChange={(e) => setPage({ ...page, title: e.target.value })}
             className="text-2xl font-bold w-full bg-transparent border-b border-transparent focus:border-slate-300 outline-none"
             style={{ color: colors.onSurface }}
             data-testid="studio-editor-title" />
          <p className="text-xs" style={{ color: colors.muted }}>
            /{page.slug} · status: <b>{page.status}</b>
          </p>
        </div>
        <button onClick={autoFill} disabled={autofilling}
                className="px-3 py-2 text-sm font-bold rounded-xl flex items-center gap-2 disabled:opacity-60"
                style={{ background: brandGradientCss, color: "#fff" }}
                data-testid="studio-auto-fill-btn">
          <Sparkles size={14} /> {autofilling ? "Filling…" : "AI Auto-Fill"}
        </button>
        <button onClick={save} disabled={saving}
                className="px-3 py-2 text-sm font-bold rounded-xl"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="studio-save-btn">
          {saving ? "Saving…" : "Save"}
        </button>
        <button onClick={publish} disabled={publishing}
                className="px-3 py-2 text-sm font-bold rounded-xl"
                style={{ backgroundColor: "#059669", color: "#fff" }}
                data-testid="studio-publish-btn">
          {publishing ? "Publishing…" : "Publish"}
        </button>
      </div>

      {message && (
        <div className="mb-4 p-3 rounded-xl text-sm break-all"
             style={{ backgroundColor: "#EFF6FF", color: "#1E40AF",
                      border: "1px solid #BFDBFE" }}
             data-testid="studio-message">
          {message}
        </div>
      )}

      {/* Meta */}
      <div className="rounded-2xl p-4 mb-4"
           style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}>
        {[
          ["target_keyword", "Target keyword"],
          ["meta_description", "Meta description"],
          ["business_context", "Business context"],
        ].map(([k, l]) => (
          <label key={k} className="block mb-3 last:mb-0">
            <div className="text-xs font-bold mb-1"
                 style={{ color: colors.muted }}>{l}</div>
            <input value={page[k] || ""}
              onChange={(e) => setPage({ ...page, [k]: e.target.value })}
              className="w-full p-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }}
              data-testid={`studio-editor-${k}`} />
          </label>
        ))}
      </div>

      {/* Section palette */}
      <div className="mb-3 flex flex-wrap gap-1">
        {SECTION_TYPES.map((t) => (
          <button key={t} onClick={() => addSection(t)}
                  className="text-[11px] px-2 py-1 rounded-lg font-semibold"
                  style={{ backgroundColor: colors.surfaceTertiary || "#F1F5F9",
                            color: colors.onSurface,
                            border: `1px solid ${colors.border}` }}
                  data-testid={`studio-add-section-${t}`}>
            + {t}
          </button>
        ))}
      </div>

      {/* Sections */}
      <div className="space-y-3 mb-6">
        {(page.sections || []).map((s, idx) => (
          <div key={idx}
               className="rounded-2xl p-4"
               style={{ backgroundColor: colors.surface,
                        border: `1px solid ${colors.border}` }}
               data-testid={`studio-section-${idx}`}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[10px] px-2 py-0.5 rounded-full font-bold"
                    style={{ backgroundColor: "#EFF6FF", color: "#1E40AF" }}>
                {s.type}
              </span>
              <button onClick={() => removeSection(idx)}
                      className="ml-auto p-1 rounded"
                      style={{ color: "#DC2626" }}
                      data-testid={`studio-remove-section-${idx}`}>
                <Trash2 size={14} />
              </button>
            </div>
            <input placeholder="Heading" value={s.heading || ""}
              onChange={(e) => updateSection(idx, { heading: e.target.value })}
              className="w-full p-2 mb-2 rounded-lg text-sm font-bold"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }} />
            <input placeholder="Subheading" value={s.subheading || ""}
              onChange={(e) => updateSection(idx, { subheading: e.target.value })}
              className="w-full p-2 mb-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }} />
            <textarea placeholder="Body" rows={2} value={s.body || ""}
              onChange={(e) => updateSection(idx, { body: e.target.value })}
              className="w-full p-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.background,
                        border: `1px solid ${colors.border}` }} />
            {s.items && s.items.length > 0 && (
              <div className="mt-2 text-xs" style={{ color: colors.muted }}>
                {s.items.length} items ({Object.keys(s.items[0] || {}).join(", ")})
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Export bar */}
      <div className="flex gap-2 flex-wrap">
        <button onClick={() => download("html")}
                className="px-3 py-2 text-xs font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="studio-export-html">
          <Download size={12} /> Export HTML
        </button>
        <button onClick={() => download("markdown")}
                className="px-3 py-2 text-xs font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="studio-export-md">
          <Download size={12} /> Markdown
        </button>
        <button onClick={() => download("json")}
                className="px-3 py-2 text-xs font-bold rounded-xl flex items-center gap-1"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                data-testid="studio-export-json">
          <Download size={12} /> JSON
        </button>
        {page.status === "published" && (
          <a href={previewUrl} target="_blank" rel="noreferrer"
             className="px-3 py-2 text-xs font-bold rounded-xl flex items-center gap-1"
             style={{ backgroundColor: colors.brand, color: "#fff" }}
             data-testid="studio-open-preview">
            <Eye size={12} /> Open live preview
          </a>
        )}
      </div>
    </div>
  );
}
