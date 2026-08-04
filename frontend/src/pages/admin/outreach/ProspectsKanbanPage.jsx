/**
 * Phase SEO-B · Feb-2026 — Backlink Outreach Kanban.
 *
 * Two-panel screen:
 *   • Header — pipeline counts, search box, status filter,
 *     "New prospect" button, "Import CSV" button.
 *   • Board — 5 columns (pending → contacted → replied → link_placed
 *     → declined). ``@dnd-kit`` drag-and-drop between columns fires
 *     PATCH ``/outreach/prospects/{id}`` with the new status.
 *
 * Selecting a card opens a right-hand detail drawer with editable
 * fields, message history, and a "Send email" action that opens the
 * ``SendEmailModal``.
 *
 * The ``ImportCsvModal`` handles file selection + dry-run preview.
 * The ``NewProspectModal`` covers manual entry.
 */
import React from "react";
import { toast } from "sonner";
import {
  DndContext, closestCenter, KeyboardSensor, PointerSensor,
  useSensor, useSensors,
} from "@dnd-kit/core";
import {
  useSortable, SortableContext, verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Plus, Upload, Search, X, Mail, RefreshCw, Trash2, Send } from "lucide-react";
import { api } from "@/api";

const COLUMNS = [
  { id: "pending",     label: "Pending",      fg: "#075985", bg: "#E0F2FE" },
  { id: "contacted",   label: "Contacted",    fg: "#92400E", bg: "#FEF3C7" },
  { id: "replied",     label: "Replied",      fg: "#065F46", bg: "#DCFCE7" },
  { id: "link_placed", label: "Link placed",  fg: "#3730A3", bg: "#E0E7FF" },
  { id: "declined",    label: "Declined",     fg: "#7F1D1D", bg: "#FEE2E2" },
];

function _fmtTs(ts) {
  if (!ts) return "—";
  try { return new Date(ts).toLocaleDateString(); } catch { return ts; }
}

// ─── Sortable card ─────────────────────────────────────────────────

function ProspectCard({ prospect, onOpen }) {
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: prospect.id, data: { status: prospect.status } });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
  };
  return (
    <div ref={setNodeRef} style={style}
         className="bg-white border border-zinc-200 rounded-md p-3 shadow-sm hover:shadow-md transition-shadow cursor-grab"
         data-testid={`prospect-card-${prospect.id}`}>
      <div className="flex items-start justify-between gap-2 mb-1"
           {...attributes} {...listeners}>
        <span className="text-sm font-semibold truncate max-w-[70%]"
              title={prospect.domain}>
          {prospect.domain}
        </span>
        <button type="button"
                onClick={(e) => { e.stopPropagation(); onOpen(prospect.id); }}
                className="text-sky-600 hover:underline text-xs shrink-0"
                data-testid={`prospect-open-${prospect.id}`}>
          Open
        </button>
      </div>
      <div className="text-xs text-zinc-600 truncate"
           title={prospect.contact_email || ""}>
        {prospect.contact_name || "(no contact)"}
        {prospect.contact_role ? ` · ${prospect.contact_role}` : ""}
      </div>
      {prospect.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {prospect.tags.slice(0, 4).map((t) => (
            <span key={t}
                  className="inline-block bg-zinc-100 text-zinc-700 text-[10px] font-medium rounded-full px-2 py-0.5">
              {t}
            </span>
          ))}
        </div>
      )}
      {prospect.last_activity_at && (
        <div className="text-[10px] text-zinc-500 mt-2">
          Last touch: {_fmtTs(prospect.last_activity_at)}
        </div>
      )}
    </div>
  );
}

// ─── Column (drop target) ─────────────────────────────────────────

function Column({ col, prospects, onOpen }) {
  const { setNodeRef } = useSortable({
    id: `col-${col.id}`, data: { status: col.id, isColumn: true },
  });
  return (
    <div className="flex flex-col min-w-[260px] bg-zinc-50 rounded-lg p-3"
         data-testid={`prospect-column-${col.id}`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="inline-block rounded-full px-2 py-0.5 text-[11px] font-medium"
                style={{ background: col.bg, color: col.fg }}>
            {col.label}
          </span>
          <span className="text-xs text-zinc-500"
                data-testid={`prospect-col-count-${col.id}`}>
            {prospects.length}
          </span>
        </div>
      </div>
      <SortableContext items={prospects.map((p) => p.id)}
                        strategy={verticalListSortingStrategy}>
        <div ref={setNodeRef}
             className="flex flex-col gap-2 min-h-[80px]">
          {prospects.map((p) => (
            <ProspectCard key={p.id} prospect={p} onOpen={onOpen} />
          ))}
          {prospects.length === 0 && (
            <div className="text-xs text-zinc-400 italic py-6 text-center border border-dashed border-zinc-300 rounded"
                 data-testid={`prospect-col-empty-${col.id}`}>
              Drop here
            </div>
          )}
        </div>
      </SortableContext>
    </div>
  );
}

// ─── New prospect modal ────────────────────────────────────────────

function NewProspectModal({ open, onClose, onCreated }) {
  const [form, setForm] = React.useState({
    domain: "", contact_name: "", contact_email: "",
    contact_role: "editor",
    our_page_url: "", desired_anchor: "", notes: "",
  });
  const [busy, setBusy] = React.useState(false);
  if (!open) return null;
  const handleCreate = async () => {
    if (!form.domain.trim()) {
      toast.error("Domain is required"); return;
    }
    setBusy(true);
    try {
      const r = await api.post("/outreach/prospects", form);
      toast.success("Prospect added");
      onCreated?.(r);
      onClose();
      setForm({
        domain: "", contact_name: "", contact_email: "",
        contact_role: "editor",
        our_page_url: "", desired_anchor: "", notes: "" });
    } catch (e) {
      toast.error("Create failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
         data-testid="new-prospect-modal"
         onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">New prospect</h3>
          <button type="button" onClick={onClose} aria-label="Close"
                  data-testid="new-prospect-close"><X size={18} /></button>
        </div>
        <div className="space-y-3">
          <input placeholder="Domain (e.g. site.com)"
                 value={form.domain}
                 onChange={(e) => setForm({ ...form, domain: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="new-prospect-domain" />
          <div className="grid grid-cols-2 gap-2">
            <input placeholder="Contact name" value={form.contact_name}
                   onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
                   className="px-3 py-2 border border-zinc-200 rounded text-sm"
                   data-testid="new-prospect-name" />
            <input placeholder="Contact email" value={form.contact_email}
                   onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                   className="px-3 py-2 border border-zinc-200 rounded text-sm"
                   data-testid="new-prospect-email" />
          </div>
          <input placeholder="Our page URL"
                 value={form.our_page_url}
                 onChange={(e) => setForm({ ...form, our_page_url: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="new-prospect-ourpage" />
          <input placeholder="Desired anchor text"
                 value={form.desired_anchor}
                 onChange={(e) => setForm({ ...form, desired_anchor: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="new-prospect-anchor" />
          <textarea placeholder="Notes"
                    value={form.notes}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                    rows={2}
                    data-testid="new-prospect-notes" />
        </div>
        <div className="flex justify-end gap-2 mt-6">
          <button type="button" onClick={onClose}
                  className="px-4 py-2 rounded border border-zinc-200 text-sm">
            Cancel
          </button>
          <button type="button" onClick={handleCreate} disabled={busy}
                  className="px-4 py-2 rounded bg-sky-600 text-white text-sm font-medium disabled:opacity-50"
                  data-testid="new-prospect-submit">
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── CSV import modal ─────────────────────────────────────────────

function ImportCsvModal({ open, onClose, onImported }) {
  const [file, setFile] = React.useState(null);
  const [preview, setPreview] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    if (!open) { setFile(null); setPreview(null); }
  }, [open]);
  if (!open) return null;
  const submit = async (dryRun) => {
    if (!file) { toast.error("Choose a CSV first"); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const token = localStorage.getItem("token") || "";
      const tenantSlug = localStorage.getItem("tenant_slug") || "";
      const url = `${process.env.REACT_APP_BACKEND_URL}/api`
                  + `/outreach/prospects/bulk-import`
                  + `?dry_run=${dryRun ? "true" : "false"}`;
      const res = await fetch(url, {
        method: "POST",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...(tenantSlug ? { "X-Tenant-Slug": tenantSlug } : {}),
        },
        body: fd,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const r = await res.json();
      if (dryRun) { setPreview(r); }
      else {
        toast.success(`Imported ${r.created} created, ${r.updated} updated, ${r.skipped} skipped`);
        onImported?.();
        onClose();
      }
    } catch (e) {
      toast.error("Import failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
         data-testid="import-csv-modal"
         onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-lg w-full p-6"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Import prospects CSV</h3>
          <button type="button" onClick={onClose} aria-label="Close"
                  data-testid="import-csv-close"><X size={18} /></button>
        </div>
        <p className="text-xs text-zinc-500 mb-3">
          Expected columns: <code>domain,contact_name,contact_email,
          contact_role,tags,notes</code>. Duplicates (same domain+email)
          are updated; missing-domain rows are skipped.
        </p>
        <input type="file" accept=".csv"
               onChange={(e) => { setFile(e.target.files?.[0] || null); setPreview(null); }}
               className="text-sm"
               data-testid="import-csv-file" />
        {preview && (
          <div className="mt-4 p-3 border border-zinc-200 rounded text-xs bg-zinc-50 max-h-56 overflow-y-auto"
               data-testid="import-csv-preview">
            <div className="font-medium mb-2 text-zinc-800">
              Dry-run: {preview.created} new · {preview.updated} update ·{" "}
              {preview.skipped} skip
            </div>
            {(preview.preview || []).map((p, i) => (
              <div key={i} className="text-zinc-600">
                {p.action === "create" ? "+" : "↻"} {p.domain} · {p.email || "no email"}
              </div>
            ))}
          </div>
        )}
        <div className="flex justify-end gap-2 mt-6">
          <button type="button" onClick={onClose}
                  className="px-4 py-2 rounded border border-zinc-200 text-sm">
            Cancel
          </button>
          <button type="button" onClick={() => submit(true)}
                  disabled={busy || !file}
                  className="px-4 py-2 rounded border border-zinc-200 text-sm disabled:opacity-50"
                  data-testid="import-csv-dryrun">
            Dry-run
          </button>
          <button type="button" onClick={() => submit(false)}
                  disabled={busy || !file}
                  className="px-4 py-2 rounded bg-sky-600 text-white text-sm disabled:opacity-50"
                  data-testid="import-csv-submit">
            {busy ? "Importing…" : "Import"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Send email modal ─────────────────────────────────────────────

function SendEmailModal({ open, prospect, templates, onClose, onSent }) {
  const [templateId, setTemplateId] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    if (open) setTemplateId(templates?.[0]?.id || "");
  }, [open, templates]);
  if (!open || !prospect) return null;
  const tpl = templates.find((t) => t.id === templateId);

  const _render = (text) => {
    if (!text) return "";
    const vals = {
      contact_name: prospect.contact_name || "there",
      their_domain: prospect.domain || "",
      our_page_url: prospect.our_page_url || "",
      desired_anchor: prospect.desired_anchor || "",
      target_page_url: prospect.target_page_url || "",
    };
    return text.replace(/\{\{\s*(\w+)\s*\}\}/g,
      (_, k) => vals[k] ?? `{{${k}}}`);
  };

  const send = async () => {
    if (!templateId) { toast.error("Pick a template"); return; }
    setBusy(true);
    try {
      const r = await api.post(
        `/outreach/prospects/${prospect.id}/send`,
        { template_id: templateId });
      if (r.status === "sent") toast.success("Email sent");
      else toast.error("Send failed", { description: r.error });
      onSent?.(r);
      onClose();
    } catch (e) {
      toast.error("Send failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
         data-testid="send-email-modal"
         onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full p-6 max-h-[90vh] overflow-y-auto"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold">Send outreach email</h3>
          <button type="button" onClick={onClose} aria-label="Close"
                  data-testid="send-email-close"><X size={18} /></button>
        </div>
        <p className="text-xs text-zinc-500 mb-3">
          To: <strong>{prospect.contact_email || "—"}</strong> ·{" "}
          {prospect.domain}
        </p>
        <select value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
                className="w-full px-3 py-2 border border-zinc-200 rounded text-sm mb-3"
                data-testid="send-email-template-select">
          <option value="">Choose a template…</option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>{t.name}</option>
          ))}
        </select>
        {tpl && (
          <div className="border border-zinc-200 rounded p-3 bg-zinc-50"
               data-testid="send-email-preview">
            <div className="text-xs text-zinc-500 mb-1">Subject</div>
            <div className="text-sm font-medium mb-3"
                 data-testid="send-email-preview-subject">
              {_render(tpl.subject)}
            </div>
            <div className="text-xs text-zinc-500 mb-1">Body</div>
            <div className="text-sm whitespace-pre-wrap"
                 data-testid="send-email-preview-body">
              {_render(tpl.body_html)}
            </div>
          </div>
        )}
        <div className="flex justify-end gap-2 mt-6">
          <button type="button" onClick={onClose}
                  className="px-4 py-2 rounded border border-zinc-200 text-sm">
            Cancel
          </button>
          <button type="button" onClick={send}
                  disabled={busy || !templateId
                              || !prospect.contact_email}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded bg-sky-600 text-white text-sm font-medium disabled:opacity-50"
                  data-testid="send-email-submit">
            <Send size={14} /> {busy ? "Sending…" : "Send email"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Detail drawer ─────────────────────────────────────────────────

function DetailDrawer({ prospect, onClose, onChanged, onOpenSend }) {
  const [form, setForm] = React.useState(prospect);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => { setForm(prospect); }, [prospect]);
  if (!prospect) return null;
  const save = async () => {
    setSaving(true);
    try {
      const r = await api.patch(`/outreach/prospects/${prospect.id}`, {
        contact_name: form.contact_name,
        contact_email: form.contact_email,
        contact_role: form.contact_role,
        our_page_url: form.our_page_url,
        desired_anchor: form.desired_anchor,
        target_page_url: form.target_page_url,
        notes: form.notes,
      });
      toast.success("Saved");
      onChanged?.(r);
    } catch (e) {
      toast.error("Save failed", { description: e?.message });
    } finally {
      setSaving(false);
    }
  };
  const del = async () => {
    if (!confirm("Delete this prospect?")) return;
    try {
      await api.del(`/outreach/prospects/${prospect.id}`);
      toast.success("Deleted");
      onChanged?.(null);
      onClose?.();
    } catch (e) {
      toast.error("Delete failed", { description: e?.message });
    }
  };
  return (
    <div className="fixed inset-y-0 right-0 z-40 w-full max-w-md bg-white shadow-2xl overflow-y-auto"
         data-testid="prospect-detail-drawer">
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="min-w-0">
            <h3 className="text-lg font-semibold truncate"
                title={prospect.domain}>{prospect.domain}</h3>
            <div className="text-xs text-zinc-500">
              Status: {prospect.status}
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
                  data-testid="detail-drawer-close">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-3">
          <input placeholder="Contact name"
                 value={form.contact_name || ""}
                 onChange={(e) => setForm({ ...form, contact_name: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="detail-name" />
          <input placeholder="Contact email"
                 value={form.contact_email || ""}
                 onChange={(e) => setForm({ ...form, contact_email: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="detail-email" />
          <input placeholder="Contact role"
                 value={form.contact_role || ""}
                 onChange={(e) => setForm({ ...form, contact_role: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="detail-role" />
          <input placeholder="Our page URL"
                 value={form.our_page_url || ""}
                 onChange={(e) => setForm({ ...form, our_page_url: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="detail-ourpage" />
          <input placeholder="Desired anchor"
                 value={form.desired_anchor || ""}
                 onChange={(e) => setForm({ ...form, desired_anchor: e.target.value })}
                 className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                 data-testid="detail-anchor" />
          <textarea placeholder="Notes" value={form.notes || ""}
                    onChange={(e) => setForm({ ...form, notes: e.target.value })}
                    rows={3}
                    className="w-full px-3 py-2 border border-zinc-200 rounded text-sm"
                    data-testid="detail-notes" />
        </div>
        <div className="flex justify-between mt-4">
          <button type="button" onClick={del}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-red-600 hover:bg-red-50 text-sm"
                  data-testid="detail-delete">
            <Trash2 size={14} /> Delete
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={() => onOpenSend?.(prospect)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm"
                    data-testid="detail-send-email">
              <Mail size={14} /> Send email
            </button>
            <button type="button" onClick={save} disabled={saving}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-emerald-600 text-white text-sm disabled:opacity-50"
                    data-testid="detail-save">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>

        {/* Message history */}
        {(prospect.messages || []).length > 0 && (
          <div className="mt-6" data-testid="detail-messages">
            <h4 className="text-sm font-semibold mb-2">
              Message history ({prospect.messages.length})
            </h4>
            <div className="space-y-2 max-h-64 overflow-y-auto">
              {prospect.messages.map((m) => (
                <div key={m.id}
                     className="border border-zinc-200 rounded p-2 text-xs"
                     data-testid={`detail-message-${m.id}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium truncate">
                      {m.subject_rendered}
                    </span>
                    <span className={m.status === "sent"
                                      ? "text-emerald-600" : "text-red-600"}>
                      {m.status}
                    </span>
                  </div>
                  <div className="text-zinc-500 mt-1">
                    {_fmtTs(m.sent_at)} · to {m.to_email}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main page component ───────────────────────────────────────────

export default function ProspectsKanbanPage() {
  const [prospects, setProspects] = React.useState([]);
  const [pipeline, setPipeline] = React.useState(null);
  const [templates, setTemplates] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [search, setSearch] = React.useState("");
  const [showNew, setShowNew] = React.useState(false);
  const [showImport, setShowImport] = React.useState(false);
  const [_selectedId, setSelectedId] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [sendFor, setSendFor] = React.useState(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor));

  const loadAll = React.useCallback(async () => {
    setLoading(true);
    try {
      const [list, pipe, tpls] = await Promise.all([
        api.get(`/outreach/prospects?limit=500${
          search ? `&search=${encodeURIComponent(search)}` : ""}`),
        api.get("/outreach/pipeline"),
        api.get("/outreach/templates"),
      ]);
      setProspects(list?.items || []);
      setPipeline(pipe);
      setTemplates(tpls?.items || []);
    } catch (e) {
      toast.error("Load failed", { description: e?.message });
    } finally {
      setLoading(false);
    }
  }, [search]);

  React.useEffect(() => { loadAll(); }, [loadAll]);

  const openDetail = React.useCallback(async (id) => {
    setSelectedId(id);
    setSelected(null);
    try {
      const r = await api.get(`/outreach/prospects/${id}`);
      setSelected(r);
    } catch (e) {
      toast.error("Failed to load", { description: e?.message });
    }
  }, []);

  const byColumn = React.useMemo(() => {
    const m = { pending: [], contacted: [], replied: [],
                 link_placed: [], declined: [] };
    for (const p of prospects) {
      if (p.status === "unsubscribed") continue; // hidden filter
      if (m[p.status]) m[p.status].push(p);
    }
    return m;
  }, [prospects]);

  const handleDragEnd = async (event) => {
    const { active, over } = event;
    if (!active || !over) return;
    // Determine destination column: either dropped on another card
    // (use that card's status) or on a column container.
    let newStatus = null;
    if (over.data?.current?.isColumn) {
      newStatus = over.data.current.status;
    } else if (over.data?.current?.status) {
      newStatus = over.data.current.status;
    } else if (typeof over.id === "string" && over.id.startsWith("col-")) {
      newStatus = over.id.slice(4);
    }
    if (!newStatus) return;
    const prospect = prospects.find((p) => p.id === active.id);
    if (!prospect || prospect.status === newStatus) return;
    // Optimistic update.
    const before = prospects;
    setProspects((old) => old.map((p) =>
      p.id === prospect.id ? { ...p, status: newStatus } : p));
    try {
      await api.post(`/outreach/prospects/${prospect.id}/status`,
                      { status: newStatus });
      await loadAll();
    } catch (e) {
      toast.error("Move failed", { description: e?.message });
      setProspects(before);
    }
  };

  return (
    <div className="p-6 space-y-6" data-testid="prospects-kanban-page">
      <header className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-zinc-900"
              data-testid="prospects-kanban-title">
            Backlink Outreach
          </h1>
          <p className="text-sm text-zinc-500 mt-1">
            Track link-building prospects through the pipeline. Drag cards
            between columns to update status.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 px-3 py-1.5 border border-zinc-200 rounded bg-white">
            <Search size={14} className="text-zinc-400" />
            <input type="text" placeholder="Search…"
                   value={search}
                   onChange={(e) => setSearch(e.target.value)}
                   className="text-sm focus:outline-none"
                   data-testid="prospects-search" />
          </div>
          <button type="button" onClick={loadAll}
                  className="p-2 border border-zinc-200 rounded hover:bg-zinc-50"
                  data-testid="prospects-refresh"
                  aria-label="Refresh">
            <RefreshCw size={16} />
          </button>
          <button type="button" onClick={() => setShowImport(true)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 border border-zinc-200 rounded text-sm hover:bg-zinc-50"
                  data-testid="prospects-import-btn">
            <Upload size={14} /> Import CSV
          </button>
          <button type="button" onClick={() => setShowNew(true)}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 text-white text-sm font-medium"
                  data-testid="prospects-new-btn">
            <Plus size={14} /> New prospect
          </button>
        </div>
      </header>

      {/* Pipeline counts strip */}
      {pipeline && (
        <div className="flex items-center gap-4 text-sm bg-white border border-zinc-200 rounded-lg px-4 py-3 shadow-sm"
             data-testid="prospects-pipeline">
          {COLUMNS.map((c) => (
            <div key={c.id} className="flex items-center gap-2"
                 data-testid={`prospects-pipeline-${c.id}`}>
              <span className="inline-block rounded-full px-2 py-0.5 text-[11px] font-medium"
                    style={{ background: c.bg, color: c.fg }}>
                {c.label}
              </span>
              <span className="font-semibold">{pipeline[c.id] ?? 0}</span>
            </div>
          ))}
          <div className="ml-auto text-zinc-500 text-xs">
            Total: <strong className="text-zinc-800">{pipeline.total}</strong>
          </div>
        </div>
      )}

      {/* Kanban board */}
      {loading ? (
        <div className="p-6 text-sm text-zinc-500"
             data-testid="prospects-loading">
          Loading prospects…
        </div>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter}
                     onDragEnd={handleDragEnd}>
          <div className="flex gap-4 overflow-x-auto pb-4"
               data-testid="prospects-board">
            {COLUMNS.map((c) => (
              <Column key={c.id} col={c}
                       prospects={byColumn[c.id] || []}
                       onOpen={openDetail} />
            ))}
          </div>
        </DndContext>
      )}

      <NewProspectModal open={showNew}
                          onClose={() => setShowNew(false)}
                          onCreated={loadAll} />
      <ImportCsvModal open={showImport}
                        onClose={() => setShowImport(false)}
                        onImported={loadAll} />
      {selected && (
        <DetailDrawer prospect={selected}
                       onClose={() => { setSelected(null); setSelectedId(null); }}
                       onChanged={(fresh) => { setSelected(fresh); loadAll(); }}
                       onOpenSend={(p) => setSendFor(p)} />
      )}
      <SendEmailModal open={!!sendFor} prospect={sendFor}
                        templates={templates.filter((t) => !t.archived)}
                        onClose={() => setSendFor(null)}
                        onSent={() => { setSendFor(null); loadAll(); }} />
    </div>
  );
}
