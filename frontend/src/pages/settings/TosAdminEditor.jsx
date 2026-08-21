/**
 * Feb-2026 · Slice 2B — Multi-ToS Admin Editor.
 *
 * Two-tab admin UI (Pool / Landscaping) that manages ToS documents
 * via the 2A backend at:
 *   * ``GET  /admin/tos-documents?service_type={pool|landscaping}``
 *   * ``POST /admin/tos-documents``
 *   * ``PUT  /admin/tos-documents/{id}``
 *   * ``POST /admin/tos-documents/{id}/publish``
 *
 * Auth: admin OR super_admin only (routed via ``<AdminOnly>``).
 *
 * Editor: TipTap 2.11 (already in ``package.json``) with StarterKit +
 * Underline + Link. External links are auto-normalised to
 * ``target="_blank" rel="noopener noreferrer"`` on save (both here
 * and again in the backend sanitizer as defense-in-depth).
 *
 * Version history: superseded rows are read-only. Editing a
 * published version is forbidden (409 from backend) — surface the
 * inline banner + a "Create new draft" CTA.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Link from "@tiptap/extension-link";
import { toast } from "sonner";
import {
  ArrowLeft, Bold, Italic, Underline as UnderlineIcon,
  Heading1, Heading2, Heading3, List, ListOrdered,
  Link2, Link2Off, Undo2, Redo2, AlertTriangle,
  FileText, History, CheckCircle2,
} from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";


const SERVICE_TYPES = [
  { key: "pool", label: "Pool ToS" },
  { key: "landscaping", label: "Landscaping ToS" },
];


function _fmtWhen(iso) {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return iso;
  return dt.toLocaleString();
}


function _tiptapExtensions() {
  return [
    StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
    Underline,
    Link.configure({
      openOnClick: false,
      HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
    }),
  ];
}


function TosToolbar({ editor, disabled }) {
  if (!editor) return null;
  const btn = (isActive, testid, onClick, Icon, label) => (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      title={label}
      aria-label={label}
      data-testid={testid}
      className="p-2 rounded-md disabled:opacity-40"
      style={{
        backgroundColor: isActive ? colors.brandTertiary : colors.surface,
        color: isActive ? colors.onBrandTertiary : colors.onSurface,
        border: `1px solid ${colors.border}`,
      }}
    >
      <Icon size={14} />
    </button>
  );
  const setLink = () => {
    const url = window.prompt("Link URL:");
    if (url === null) return;
    if (!url) {
      editor.chain().focus().unsetLink().run();
    } else {
      editor.chain().focus().extendMarkRange("link").setLink({ href: url }).run();
    }
  };
  return (
    <div
      className="flex flex-wrap gap-1 p-2 rounded-t-lg"
      style={{
        backgroundColor: colors.surfaceSubtle,
        border: `1px solid ${colors.border}`,
        borderBottom: "none",
      }}
      data-testid="tos-editor-toolbar"
    >
      {btn(editor.isActive("bold"), "tos-tool-bold",
           () => editor.chain().focus().toggleBold().run(), Bold, "Bold")}
      {btn(editor.isActive("italic"), "tos-tool-italic",
           () => editor.chain().focus().toggleItalic().run(), Italic, "Italic")}
      {btn(editor.isActive("underline"), "tos-tool-underline",
           () => editor.chain().focus().toggleUnderline().run(),
           UnderlineIcon, "Underline")}
      <span style={{ width: 1, backgroundColor: colors.border, margin: "0 4px" }} />
      {btn(editor.isActive("heading", { level: 1 }), "tos-tool-h1",
           () => editor.chain().focus().toggleHeading({ level: 1 }).run(),
           Heading1, "Heading 1")}
      {btn(editor.isActive("heading", { level: 2 }), "tos-tool-h2",
           () => editor.chain().focus().toggleHeading({ level: 2 }).run(),
           Heading2, "Heading 2")}
      {btn(editor.isActive("heading", { level: 3 }), "tos-tool-h3",
           () => editor.chain().focus().toggleHeading({ level: 3 }).run(),
           Heading3, "Heading 3")}
      <span style={{ width: 1, backgroundColor: colors.border, margin: "0 4px" }} />
      {btn(editor.isActive("bulletList"), "tos-tool-bullet",
           () => editor.chain().focus().toggleBulletList().run(),
           List, "Bulleted list")}
      {btn(editor.isActive("orderedList"), "tos-tool-ordered",
           () => editor.chain().focus().toggleOrderedList().run(),
           ListOrdered, "Numbered list")}
      <span style={{ width: 1, backgroundColor: colors.border, margin: "0 4px" }} />
      {btn(editor.isActive("link"), "tos-tool-link", setLink, Link2, "Link")}
      {btn(false, "tos-tool-unlink",
           () => editor.chain().focus().unsetLink().run(), Link2Off, "Unlink")}
      <span style={{ width: 1, backgroundColor: colors.border, margin: "0 4px" }} />
      {btn(false, "tos-tool-undo",
           () => editor.chain().focus().undo().run(), Undo2, "Undo")}
      {btn(false, "tos-tool-redo",
           () => editor.chain().focus().redo().run(), Redo2, "Redo")}
    </div>
  );
}


function PublishConfirmDialog({ open, serviceType, onConfirm, onCancel, publishing }) {
  if (!open) return null;
  const label = serviceType === "pool" ? "pool" : "landscaping";
  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(15,23,42,0.5)" }}
      data-testid="tos-publish-confirm"
    >
      <div
        className="w-full max-w-md rounded-2xl p-6"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
        }}
      >
        <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
          Publish new Terms of Service?
        </h2>
        <p className="text-sm mt-2" style={{ color: colors.muted }}>
          This will notify all customers with active {label} service. Continue?
        </p>
        <div className="flex justify-end gap-2 mt-6">
          <button
            type="button"
            onClick={onCancel}
            disabled={publishing}
            data-testid="tos-publish-cancel"
            className="px-4 py-2 rounded-md text-sm"
            style={{
              backgroundColor: colors.surfaceSubtle,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={publishing}
            data-testid="tos-publish-confirm-btn"
            className="px-4 py-2 rounded-md text-sm font-semibold"
            style={{
              backgroundColor: colors.brand,
              color: colors.onBrand,
            }}
          >
            {publishing ? "Publishing…" : "Publish"}
          </button>
        </div>
      </div>
    </div>
  );
}


function EmptyDraftHint({ onNewDraft }) {
  return (
    <div
      className="rounded-xl p-6 text-center"
      style={{
        backgroundColor: colors.surface,
        border: `1px dashed ${colors.border}`,
      }}
      data-testid="tos-no-draft-hint"
    >
      <p className="text-sm" style={{ color: colors.muted }}>
        No draft loaded. Start a new draft — the published version stays
        live until you publish this one.
      </p>
      <button
        type="button"
        onClick={onNewDraft}
        data-testid="tos-new-draft"
        className="mt-4 px-4 py-2 rounded-md text-sm font-semibold"
        style={{ backgroundColor: colors.brand, color: colors.onBrand }}
      >
        Create new draft
      </button>
    </div>
  );
}


export default function TosAdminEditor() {
  const nav = useNavigate();
  const [tab, setTab] = useState("pool");
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [title, setTitle] = useState("");
  const [effectiveDate, setEffectiveDate] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);

  const editor = useEditor({
    extensions: _tiptapExtensions(),
    content: "",
    editable: true,
  });

  // Segment documents by status for the tab.
  const { publishedDoc, draftDocs, supersededDocs } = useMemo(() => {
    const p = documents.find((d) => d.status === "published") || null;
    const drafts = documents.filter((d) => d.status === "draft");
    const superseded = documents.filter((d) => d.status === "superseded");
    return { publishedDoc: p, draftDocs: drafts, supersededDocs: superseded };
  }, [documents]);

  const selected = useMemo(
    () => documents.find((d) => d.id === selectedId) || null,
    [documents, selectedId],
  );
  const editingPublished =
    selected && selected.status && selected.status !== "draft";

  // Load documents for the active tab.
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setSaveError("");
    api
      .get(`/admin/tos-documents?service_type=${tab}`)
      .then((r) => {
        if (!alive) return;
        const docs = Array.isArray(r?.documents) ? r.documents : [];
        setDocuments(docs);
        // Auto-select the newest draft if any; else the published; else null.
        const firstDraft = docs.find((d) => d.status === "draft");
        const pub = docs.find((d) => d.status === "published");
        setSelectedId(firstDraft?.id || pub?.id || null);
      })
      .catch((e) => {
        if (!alive) return;
        toast.error(`Failed to load ToS documents: ${e?.message || e}`);
        setDocuments([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [tab]);

  // Sync the editor with the selected document.
  useEffect(() => {
    if (!editor) return;
    if (!selected) {
      editor.commands.setContent("");
      setTitle("");
      setEffectiveDate("");
      editor.setEditable(true);
      return;
    }
    editor.commands.setContent(selected.content_html || "");
    setTitle(selected.title || "");
    setEffectiveDate(selected.effective_date || "");
    editor.setEditable(selected.status === "draft");
  }, [editor, selected]);

  const startNewDraft = () => {
    setSelectedId(null);
    setSaveError("");
    setTitle("");
    setEffectiveDate("");
    if (editor) {
      editor.commands.setContent("");
      editor.setEditable(true);
    }
  };

  const buildBody = () => ({
    service_type: tab,
    title: title.trim(),
    effective_date: effectiveDate || null,
    content_html: editor ? editor.getHTML() : "",
    content_json: editor ? editor.getJSON() : null,
  });

  const onSaveDraft = async () => {
    if (saving || !editor) return;
    setSaving(true);
    setSaveError("");
    try {
      const body = buildBody();
      let fresh;
      if (selectedId && !editingPublished) {
        // Update existing draft.
        fresh = await api.put(`/admin/tos-documents/${selectedId}`, body);
      } else {
        // Create new draft.
        fresh = await api.post(`/admin/tos-documents`, body);
      }
      const listResp = await api.get(`/admin/tos-documents?service_type=${tab}`);
      setDocuments(listResp?.documents || []);
      setSelectedId(fresh.id);
      toast.success(`Draft saved (v${fresh.version})`);
    } catch (e) {
      const detail = e?.detail || e?.data?.detail;
      const msg =
        detail === "only_draft_documents_are_editable"
          ? "Published versions can't be edited. Create a new draft to make changes."
          : detail || e?.message || "Save failed.";
      setSaveError(msg);
    } finally {
      setSaving(false);
    }
  };

  const onPublish = async () => {
    if (!selectedId || publishing) return;
    setPublishing(true);
    try {
      const fresh = await api.post(
        `/admin/tos-documents/${selectedId}/publish`,
        {},
      );
      const listResp = await api.get(`/admin/tos-documents?service_type=${tab}`);
      setDocuments(listResp?.documents || []);
      setSelectedId(fresh.id);
      setConfirmOpen(false);
      toast.success(`Published v${fresh.version}`);
    } catch (e) {
      const detail = e?.detail || e?.data?.detail || e?.message;
      toast.error(`Publish failed: ${detail}`);
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div
      className="p-4 md:p-8 max-w-6xl mx-auto"
      data-testid="tos-admin-editor"
    >
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={() => nav(-1)}
          className="p-2 rounded-lg hover:brightness-95"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="tos-back"
        >
          <ArrowLeft size={16} />
        </button>
        <div>
          <h1
            className="text-2xl md:text-3xl font-bold"
            style={{ color: colors.onSurface }}
          >
            Terms of Service
          </h1>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Manage the Pool and Landscaping ToS shown to customers on
            first login. Publishing notifies affected customers.
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-4" role="tablist">
        {SERVICE_TYPES.map((s) => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-selected={tab === s.key}
            onClick={() => setTab(s.key)}
            data-testid={`tos-tab-${s.key}`}
            className="px-4 py-2 rounded-lg text-sm font-semibold"
            style={{
              backgroundColor:
                tab === s.key ? colors.brand : colors.surface,
              color: tab === s.key ? colors.onBrand : colors.onSurface,
              border: `1px solid ${
                tab === s.key ? colors.brand : colors.border
              }`,
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Editor column */}
        <div className="lg:col-span-3 space-y-4">
          {/* Published header */}
          {publishedDoc ? (
            <div
              className="rounded-xl p-3 flex items-center gap-3"
              style={{
                backgroundColor: "#ECFDF5",
                border: "1px solid #A7F3D0",
                color: "#065F46",
              }}
              data-testid="tos-published-banner"
            >
              <CheckCircle2 size={16} />
              <div className="text-sm">
                <b>v{publishedDoc.version}</b> published by{" "}
                {publishedDoc.published_by || "system"} on{" "}
                {_fmtWhen(publishedDoc.published_at)}
              </div>
            </div>
          ) : (
            <div
              className="rounded-xl p-3 flex items-center gap-3"
              style={{
                backgroundColor: colors.surfaceSubtle,
                border: `1px solid ${colors.border}`,
                color: colors.muted,
              }}
              data-testid="tos-published-empty-banner"
            >
              <FileText size={16} />
              <div className="text-sm">
                No {tab} ToS has been published yet.
              </div>
            </div>
          )}

          {editingPublished ? (
            <div
              className="rounded-xl p-3 flex items-start gap-2 text-sm"
              style={{
                backgroundColor: "#FEF3C7",
                border: "1px solid #FDE68A",
                color: "#78350F",
              }}
              data-testid="tos-editing-published-banner"
            >
              <AlertTriangle size={16} className="mt-0.5" />
              <div>
                <b>Read-only.</b> This is a{" "}
                {selected.status === "published" ? "published" : "superseded"}
                {" "}version. Create a new draft to make changes.
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={startNewDraft}
                    data-testid="tos-editing-published-new-draft"
                    className="px-3 py-1.5 rounded-md text-xs font-semibold"
                    style={{ backgroundColor: colors.brand, color: colors.onBrand }}
                  >
                    Create new draft
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          {loading ? (
            <div
              className="animate-pulse h-64 rounded-xl"
              style={{ backgroundColor: colors.surfaceSubtle }}
            />
          ) : !selected && !editor?.isEditable ? null : (
            <>
              {!selected ? null : null}
              <div>
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>
                  Title
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  disabled={editingPublished}
                  data-testid="tos-title-input"
                  className="mt-1 w-full rounded-md px-2 py-2 text-sm"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                />
              </div>
              <div>
                <label className="text-xs font-semibold" style={{ color: colors.muted }}>
                  Effective date
                </label>
                <input
                  type="date"
                  value={effectiveDate || ""}
                  onChange={(e) => setEffectiveDate(e.target.value)}
                  disabled={editingPublished}
                  data-testid="tos-effective-date-input"
                  className="mt-1 rounded-md px-2 py-2 text-sm"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                />
              </div>
              <div>
                <TosToolbar editor={editor} disabled={editingPublished} />
                <div
                  className="rounded-b-lg p-3 min-h-[280px] text-sm"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                    borderTop: "none",
                    outline: "none",
                  }}
                >
                  <EditorContent
                    editor={editor}
                    data-testid="tos-editor-content"
                  />
                </div>
              </div>

              {saveError ? (
                <div
                  className="rounded-md p-2 text-sm flex items-start gap-2"
                  style={{
                    backgroundColor: "#FEE2E2",
                    color: "#991B1B",
                    border: "1px solid #FCA5A5",
                  }}
                  data-testid="tos-save-error"
                >
                  <AlertTriangle size={14} className="mt-0.5" />
                  <span>{saveError}</span>
                </div>
              ) : null}

              <div className="flex flex-wrap gap-2 justify-end">
                <button
                  type="button"
                  onClick={startNewDraft}
                  data-testid="tos-start-new-draft"
                  className="px-4 py-2 rounded-md text-sm"
                  style={{
                    backgroundColor: colors.surfaceSubtle,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                >
                  New draft
                </button>
                <button
                  type="button"
                  onClick={onSaveDraft}
                  disabled={saving || editingPublished}
                  data-testid="tos-save-draft"
                  className="px-4 py-2 rounded-md text-sm font-semibold disabled:opacity-40"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.brand}`,
                  }}
                >
                  {saving ? "Saving…" : "Save draft"}
                </button>
                <button
                  type="button"
                  disabled={
                    editingPublished || !selectedId || publishing
                  }
                  onClick={() => setConfirmOpen(true)}
                  data-testid="tos-publish"
                  className="px-4 py-2 rounded-md text-sm font-semibold disabled:opacity-40"
                  style={{
                    backgroundColor: colors.brand,
                    color: colors.onBrand,
                  }}
                >
                  Publish
                </button>
              </div>
            </>
          )}

          {!loading && draftDocs.length === 0 && !editingPublished ? (
            <EmptyDraftHint onNewDraft={startNewDraft} />
          ) : null}
        </div>

        {/* Sidebar — drafts + version history */}
        <div className="space-y-4">
          <div
            className="rounded-xl p-3"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
            }}
          >
            <div
              className="text-xs font-semibold uppercase tracking-wide mb-2"
              style={{ color: colors.muted }}
            >
              Drafts
            </div>
            {draftDocs.length === 0 ? (
              <div className="text-xs" style={{ color: colors.muted }}>
                No drafts.
              </div>
            ) : (
              <ul className="space-y-1">
                {draftDocs.map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(d.id)}
                      data-testid={`tos-draft-row-${d.id}`}
                      className="w-full text-left text-sm rounded-md px-2 py-1.5"
                      style={{
                        backgroundColor:
                          selectedId === d.id
                            ? colors.brandTertiary
                            : "transparent",
                        color:
                          selectedId === d.id
                            ? colors.onBrandTertiary
                            : colors.onSurface,
                      }}
                    >
                      v{d.version} · {d.title || "Untitled"}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div
            className="rounded-xl p-3"
            style={{
              backgroundColor: colors.surface,
              border: `1px solid ${colors.border}`,
            }}
          >
            <div
              className="text-xs font-semibold uppercase tracking-wide mb-2 flex items-center gap-1"
              style={{ color: colors.muted }}
            >
              <History size={12} /> Version history
            </div>
            {supersededDocs.length === 0 ? (
              <div className="text-xs" style={{ color: colors.muted }}>
                No superseded versions yet.
              </div>
            ) : (
              <ul className="space-y-1">
                {supersededDocs.map((d) => (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(d.id)}
                      data-testid={`tos-history-row-${d.id}`}
                      className="w-full text-left text-xs rounded-md px-2 py-1.5"
                      style={{
                        backgroundColor:
                          selectedId === d.id
                            ? colors.brandTertiary
                            : "transparent",
                        color:
                          selectedId === d.id
                            ? colors.onBrandTertiary
                            : colors.onSurface,
                      }}
                    >
                      v{d.version} · published{" "}
                      {_fmtWhen(d.published_at)}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <PublishConfirmDialog
        open={confirmOpen}
        serviceType={tab}
        onConfirm={onPublish}
        onCancel={() => setConfirmOpen(false)}
        publishing={publishing}
      />
    </div>
  );
}
