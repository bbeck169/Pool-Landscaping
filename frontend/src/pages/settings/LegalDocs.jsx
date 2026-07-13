import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { ArrowLeft, Save, FileText, ChevronRight } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

export function LegalDocsList() {
  const nav = useNavigate();
  const [rows, setRows] = useState(null);

  useEffect(() => {
    api.get("/legal").then((r) => setRows(Array.isArray(r) ? r : [])).catch(() => setRows([]));
  }, []);

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="legal-docs-list">
      <div className="flex items-center gap-3 mb-6">
        <button onClick={() => nav(-1)}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            Legal Documents
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Terms of Service, Privacy Policy, and other customer-facing legal copy.
          </p>
        </div>
      </div>

      {rows === null ? (
        <div className="animate-pulse h-24 rounded-2xl" style={{ backgroundColor: colors.surfaceTertiary }} />
      ) : rows.length === 0 ? (
        <div className="text-sm p-8 text-center rounded-2xl"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}>
          No legal documents yet.
        </div>
      ) : (
        <ul className="space-y-2">
          {rows.map((d) => (
            <li key={d.slug}>
              <Link
                to={`/settings/legal/${d.slug}`}
                className="flex items-center gap-3 p-4 rounded-2xl hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid={`legal-row-${d.slug}`}>
                <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                     style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}>
                  <FileText size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{d.title}</div>
                  <div className="text-xs mt-0.5" style={{ color: colors.muted }}>
                    <code style={{ backgroundColor: colors.surfaceTertiary, padding: "1px 4px", borderRadius: 4 }}>
                      {d.slug}
                    </code> · v{d.version} · Effective {d.effective_date || "—"}
                  </div>
                </div>
                <ChevronRight size={16} style={{ color: colors.muted }} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LegalDocEditor() {
  const { slug } = useParams();
  const nav = useNavigate();
  const [doc, setDoc] = useState(null);
  const [form, setForm] = useState({ title: "", body_markdown: "", effective_date: "" });
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState("");

  const load = () => {
    api.get(`/legal/${slug}`).then((d) => {
      setDoc(d);
      setForm({
        title: d.title || "",
        body_markdown: d.body_markdown || "",
        effective_date: d.effective_date || "",
      });
    }).catch(() => {});
  };
  useEffect(load, [slug]);

  const save = async () => {
    setSaving(true);
    try {
      const r = await api.put(`/legal/${slug}`, form);
      setDoc(r);
      setToast(`Saved · now v${r.version}`);
    } catch (e) {
      setToast(e.message);
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(""), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  if (!doc) return <div className="p-8 text-sm" style={{ color: colors.muted }}>Loading…</div>;

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto" data-testid="legal-doc-editor">
      <div className="flex items-center gap-3 mb-6 flex-wrap">
        <button onClick={() => nav("/settings/legal")}
                className="p-2 rounded-lg hover:brightness-95"
                style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
                data-testid="legal-back">
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1">
          <h1 className="text-2xl md:text-3xl font-bold" style={{ color: colors.onSurface }}>
            {doc.title}
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Version {doc.version} · Last updated {(doc.updated_at || "").slice(0, 10)} · slug{" "}
            <code style={{ backgroundColor: colors.surfaceTertiary, padding: "1px 4px", borderRadius: 4 }}>
              {doc.slug}
            </code>
          </p>
        </div>
        <button onClick={save} disabled={saving}
                className="flex items-center gap-1.5 px-4 py-2 text-sm font-semibold rounded-lg disabled:opacity-60"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid="legal-save">
          <Save size={13} /> {saving ? "Saving…" : "Save"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
        <label className="md:col-span-1">
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Title</div>
          <input value={form.title}
                 onChange={(e) => setForm({ ...form, title: e.target.value })}
                 className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="legal-title" />
        </label>
        <label className="md:col-span-1">
          <div className="text-xs font-semibold mb-1" style={{ color: colors.muted }}>Effective date</div>
          <input type="date" value={form.effective_date}
                 onChange={(e) => setForm({ ...form, effective_date: e.target.value })}
                 className="w-full px-3 py-2 rounded-lg text-sm"
                 style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="legal-effective" />
        </label>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="rounded-2xl p-4"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>MARKDOWN</div>
          <textarea
            rows={24}
            value={form.body_markdown}
            onChange={(e) => setForm({ ...form, body_markdown: e.target.value })}
            className="w-full px-3 py-2 text-xs font-mono rounded-lg outline-none"
            style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}`, color: colors.onSurface, minHeight: 480 }}
            data-testid="legal-body" />
        </div>
        <div className="rounded-2xl p-4"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}>
          <div className="text-xs font-semibold mb-2" style={{ color: colors.muted }}>PREVIEW</div>
          <div className="prose prose-sm max-w-none overflow-y-auto"
               style={{ color: colors.onSurface, maxHeight: 520, lineHeight: 1.6 }}
               data-testid="legal-preview">
            <ReactMarkdown
              components={{
                h2: ({ node, ...props }) => <h2 className="text-xl font-bold mt-5 mb-2" {...props} />,
                h3: ({ node, ...props }) => <h3 className="text-base font-bold mt-4 mb-1.5" {...props} />,
                p: ({ node, ...props }) => <p className="text-sm mb-2.5" {...props} />,
                ul: ({ node, ...props }) => <ul className="list-disc pl-5 mb-2.5 space-y-1" {...props} />,
                li: ({ node, ...props }) => <li className="text-sm" {...props} />,
                strong: ({ node, ...props }) => <strong className="font-bold" {...props} />,
                hr: () => <hr className="my-4" style={{ borderColor: colors.border }} />,
              }}
            >
              {form.body_markdown}
            </ReactMarkdown>
          </div>
        </div>
      </div>

      {toast ? (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 px-4 py-2.5 rounded-xl text-sm font-semibold shadow-lg"
             style={{ backgroundColor: colors.onSurface, color: "#fff" }}
             data-testid="legal-toast">
          {toast}
        </div>
      ) : null}
    </div>
  );
}
