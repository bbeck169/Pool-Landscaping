/**
 * Phase SEO-B · Feb-2026 — Outreach templates management.
 *
 * Sits at ``/admin/outreach/templates``. Admin+/manager only.
 * Standard list/create/edit/archive with a variable palette that
 * shows the placeholders supported by the send pipeline.
 */
import React from "react";
import { toast } from "sonner";
import {
  Plus, X, Archive, ArchiveRestore, Edit3, Save,
} from "lucide-react";
import { api } from "@/api";

const VARS = [
  "{{contact_name}}", "{{their_domain}}", "{{our_page_url}}",
  "{{desired_anchor}}", "{{target_page_url}}",
];

function TemplateEditor({ open, initial, onClose, onSaved }) {
  const [form, setForm] = React.useState(
    initial || { name: "", subject: "", body_html: "" });
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    setForm(initial || { name: "", subject: "", body_html: "" });
  }, [initial, open]);
  if (!open) return null;
  const save = async () => {
    if (!form.name || !form.subject || !form.body_html) {
      toast.error("All fields required"); return;
    }
    setBusy(true);
    try {
      if (initial?.id) {
        const r = await api.patch(`/outreach/templates/${initial.id}`, form);
        onSaved?.(r);
      } else {
        const r = await api.post("/outreach/templates", form);
        onSaved?.(r);
      }
      toast.success("Saved");
      onClose();
    } catch (e) {
      toast.error("Save failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
         data-testid="template-editor-modal"
         onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">
            {initial?.id ? "Edit template" : "New template"}
          </h3>
          <button type="button" onClick={onClose} aria-label="Close"
                  data-testid="template-editor-close">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-3">
          <input placeholder="Template name (e.g. Editorial pitch v1)"
                 value={form.name}
                 onChange={(e) => setForm({ ...form, name: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="template-name" />
          <input placeholder="Subject"
                 value={form.subject}
                 onChange={(e) => setForm({ ...form, subject: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="template-subject" />
          <textarea placeholder="Body (HTML allowed)"
                    value={form.body_html} rows={10}
                    onChange={(e) => setForm({ ...form, body_html: e.target.value })}
                    className="w-full px-3 py-2 border border-zinc-200 rounded text-sm font-mono"
                    data-testid="template-body" />
        </div>
        <div className="mt-3 p-3 border border-zinc-200 rounded bg-zinc-50">
          <div className="text-xs text-zinc-500 mb-2">
            Variables (click to insert):
          </div>
          <div className="flex flex-wrap gap-1">
            {VARS.map((v) => (
              <button key={v} type="button"
                      onClick={() => setForm((f) => ({
                        ...f, body_html: `${f.body_html}${v}` }))}
                      className="text-[11px] px-2 py-0.5 rounded bg-white border border-zinc-200 hover:bg-sky-50 hover:border-sky-300"
                      data-testid={`template-var-${v.replace(/[^a-z_]/g, "")}`}>
                {v}
              </button>
            ))}
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-6">
          <button type="button" onClick={onClose}
                  className="px-4 py-2 rounded border border-zinc-200 text-sm">
            Cancel
          </button>
          <button type="button" onClick={save} disabled={busy}
                  className="inline-flex items-center gap-1 px-4 py-2 rounded bg-sky-600 text-white text-sm disabled:opacity-50"
                  data-testid="template-save">
            <Save size={14} /> {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}


export default function TemplatesPage() {
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [includeArchived, setIncludeArchived] = React.useState(false);
  const [editorOpen, setEditorOpen] = React.useState(false);
  const [editing, setEditing] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get(
        `/outreach/templates?include_archived=${includeArchived}`);
      setItems(r?.items || []);
    } catch (e) {
      toast.error("Load failed", { description: e?.message });
    } finally { setLoading(false); }
  }, [includeArchived]);

  React.useEffect(() => { load(); }, [load]);

  const archive = async (t) => {
    if (!confirm(`Archive "${t.name}"?`)) return;
    try {
      await api.del(`/outreach/templates/${t.id}`);
      toast.success("Archived");
      await load();
    } catch (e) {
      toast.error("Failed", { description: e?.message });
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="templates-page">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="templates-title">Outreach Templates</h1>
          <p className="text-sm text-zinc-500 mt-1">
            Reusable email templates. Use{" "}
            <code>{"{{contact_name}}"}</code>,{" "}
            <code>{"{{their_domain}}"}</code>, etc. as placeholders.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-zinc-500 inline-flex items-center gap-1">
            <input type="checkbox" checked={includeArchived}
                    onChange={(e) => setIncludeArchived(e.target.checked)}
                    data-testid="templates-show-archived" />
            Show archived
          </label>
          <button type="button"
                  onClick={() => { setEditing(null); setEditorOpen(true); }}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm font-medium"
                  data-testid="templates-new-btn">
            <Plus size={14} /> New template
          </button>
        </div>
      </header>

      <div className="bg-white border border-zinc-200 rounded-lg shadow-sm"
           data-testid="templates-list">
        {loading ? (
          <div className="p-6 text-sm text-zinc-500">Loading…</div>
        ) : items.length === 0 ? (
          <div className="p-6 text-sm text-zinc-500"
               data-testid="templates-empty">
            No templates yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-zinc-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2">Name</th>
                <th className="text-left px-4 py-2">Subject</th>
                <th className="text-left px-4 py-2">Variables</th>
                <th className="text-right px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id} className="border-t border-zinc-100"
                    data-testid={`template-row-${t.id}`}>
                  <td className="px-4 py-2 font-medium">
                    {t.name}{" "}
                    {t.archived && (
                      <span className="text-[10px] bg-zinc-200 text-zinc-700 px-1.5 py-0.5 rounded-full ml-1">
                        archived
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-zinc-700 truncate max-w-[300px]"
                      title={t.subject}>
                    {t.subject}
                  </td>
                  <td className="px-4 py-2 text-xs text-zinc-500">
                    {(t.variables || []).join(", ") || "—"}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <button type="button"
                            onClick={() => { setEditing(t); setEditorOpen(true); }}
                            className="text-sky-600 hover:underline text-xs mr-3"
                            data-testid={`template-edit-${t.id}`}>
                      <Edit3 size={12} className="inline" /> Edit
                    </button>
                    {!t.archived && (
                      <button type="button" onClick={() => archive(t)}
                              className="text-red-600 hover:underline text-xs"
                              data-testid={`template-archive-${t.id}`}>
                        <Archive size={12} className="inline" /> Archive
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <TemplateEditor open={editorOpen} initial={editing}
                       onClose={() => setEditorOpen(false)}
                       onSaved={load} />
    </div>
  );
}
