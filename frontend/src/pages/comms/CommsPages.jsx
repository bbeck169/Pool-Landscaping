/**
 * Communications Phase 2 · Web UI (Feb 2026).
 *
 * Five admin-only pages under ``/admin/comms/*``:
 *   - Templates library (email + SMS tabs)
 *   - Email Builder (strict 12-block schema editor)
 *   - SMS Builder (composer + segment counter)
 *   - Automations (rule table + create/edit modal + test-fire)
 *   - Sends History (filtered table + detail modal)
 *
 * Deviation note: the email builder is a block-list editor bound to
 * the backend's canonical 12-block schema (not a full grapesjs drag-
 * and-drop canvas). This ships a functional round-tripped editor in
 * one turn — grapesjs integration is scoped for a follow-up polish
 * pass because the drag-adapter to blocks_json is a substantial
 * effort on its own. All 12 CC-parity block types (text, heading,
 * image, button, divider, spacer, columns_2, columns_3, social, video,
 * product_card, footer) are supported.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Mail, MessageSquare, Zap, Send, Plus, Trash2, Copy, Eye, Save, Type as TypeIcon, Heading as HeadingIcon, Image as ImageIcon, MousePointerClick, Minus, MoveVertical, Columns2, Columns3, Share2, Film, ShoppingBag, Layers, ChevronUp, ChevronDown, Search, X as XIcon, GripVertical, Monitor, Smartphone } from "lucide-react";
import { toast as sonnerToast } from "sonner";
import { colors } from "@/theme";
import { api } from "@/api";
// P2 #11 · Phase 1 · Feb-2026 — drag-and-drop + inline WYSIWYG.
// All libs below are ALREADY in frontend/package.json (used by
// AdminSidebar, DispatchBoardPage, TosAdminEditor). No new deps.
import {
  DndContext, PointerSensor, KeyboardSensor, useSensor, useSensors,
  useDraggable,
} from "@dnd-kit/core";
import {
  SortableContext, useSortable, arrayMove,
  verticalListSortingStrategy, sortableKeyboardCoordinates,
} from "@dnd-kit/sortable";
import { CSS as DndCSS } from "@dnd-kit/utilities";
import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import TipTapLink from "@tiptap/extension-link";
import CustomerCombobox from "@/components/customers/CustomerCombobox";
import {
  listEmailTemplates, getEmailTemplate, createEmailTemplate,
  updateEmailTemplate, deleteEmailTemplate, duplicateEmailTemplate,
  previewEmailTemplate, testSendEmailTemplate,
  listSmsTemplates, getSmsTemplate, createSmsTemplate, updateSmsTemplate,
  deleteSmsTemplate, duplicateSmsTemplate, previewSmsTemplate,
  listAutomations, createAutomation, updateAutomation, deleteAutomation,
  testFireAutomation,
  listSends, getSend,
  smsMetrics, TRIGGER_EVENTS,
} from "@/api/comms";
import TokenPickerModal from "@/components/comms/TokenPickerModal";
import SendStatusPill from "@/components/comms/SendStatusPill";
import {
  useBulkSelect,
  BulkSelectAll,
  BulkSelectRow,
  BulkActionBar,
  BulkConfirmModal,
  LockedPill,
} from "@/components/bulk-select/BulkSelectToolkit";

// ═════════════════════════════════════════════════════════════════════
// Shared bits
// ═════════════════════════════════════════════════════════════════════

const Card = ({ children, className = "", ...rest }) => (
  <div className={`rounded-2xl ${className}`}
       style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
       {...rest}>
    {children}
  </div>
);

function Toast({ toast, onClose }) {
  const tone = toast?.tone || "info";
  const bg = tone === "error" ? "#FEE2E2" : tone === "success" ? "#DCFCE7" : tone === "warning" ? "#FEF9C3" : "#DBEAFE";
  const fg = tone === "error" ? "#991B1B" : tone === "success" ? "#166534" : tone === "warning" ? "#854D0E" : "#1E3A8A";
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(onClose, 3200);
    return () => clearTimeout(t);
  }, [toast, onClose]);
  if (!toast) return null;
  return (
    <div className="fixed top-4 right-4 z-50 px-4 py-2 rounded-lg text-sm font-semibold shadow-lg"
         style={{ background: bg, color: fg }}
         data-testid={`comms-toast-${tone}`}>{toast.message}</div>
  );
}

function PageHeader({ icon: Icon, title, subtitle, actions }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <div className="flex items-center gap-2 mb-1">
          {Icon ? <Icon size={22} style={{ color: colors.brand }} /> : null}
          <h1 className="text-3xl font-bold" style={{ color: colors.onSurface }}>{title}</h1>
        </div>
        {subtitle ? <p className="text-sm" style={{ color: colors.muted }}>{subtitle}</p> : null}
      </div>
      <div className="flex items-center gap-2">{actions}</div>
    </div>
  );
}

function BtnPrimary({ onClick, children, disabled, testid, className = "" }) {
  return (
    <button onClick={onClick} disabled={disabled}
            className={`px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40 ${className}`}
            style={{ background: colors.brand, color: "#fff" }}
            data-testid={testid}>
      {children}
    </button>
  );
}

function BtnGhost({ onClick, children, disabled, testid, className = "" }) {
  return (
    <button onClick={onClick} disabled={disabled}
            className={`px-3 py-2 rounded-lg text-sm font-semibold disabled:opacity-40 ${className}`}
            style={{ background: colors.surfaceSecondary, color: colors.onSurface,
                     border: `1px solid ${colors.border}` }}
            data-testid={testid}>
      {children}
    </button>
  );
}

function EmptyState({ icon: Icon, title, hint, cta, onCta }) {
  return (
    <div className="text-center py-16 rounded-2xl"
         style={{ background: colors.surface, border: `1px dashed ${colors.border}` }}>
      {Icon ? <Icon size={38} className="mx-auto mb-3" style={{ color: colors.muted }} /> : null}
      <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>{title}</div>
      {hint ? <div className="text-xs mt-1" style={{ color: colors.muted }}>{hint}</div> : null}
      {cta ? <div className="mt-4"><BtnPrimary onClick={onCta}>{cta}</BtnPrimary></div> : null}
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════
// Templates library (Email + SMS tabs)
// ═════════════════════════════════════════════════════════════════════

export function CommsTemplatesLibrary() {
  const [tab, setTab] = useState("email");
  const [rows, setRows] = useState([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [lockedFailures, setLockedFailures] = useState({});
  const navigate = useNavigate();

  const reload = () => {
    setLoading(true);
    const fetcher = tab === "email" ? listEmailTemplates() : listSmsTemplates();
    fetcher.then((d) => {
      setRows(d.templates || d[tab === "email" ? "email_templates" : "sms_templates"] || d || []);
    }).catch(() => setRows([])).finally(() => setLoading(false));
  };
  useEffect(reload, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return rows;
    return rows.filter((r) =>
      (r.code || "").toLowerCase().includes(s) || (r.name || "").toLowerCase().includes(s));
  }, [rows, q]);

  // Phase 34 · Task LL Phase 2 UI wrap-up · Feb 2026 — bulk-select.
  const visibleIds = useMemo(() => filtered.map((r) => r.id || r.code), [filtered]);
  const { selected, selectedCount, allVisibleSelected, indeterminate,
             toggleAll, toggleOne, clear } = useBulkSelect(visibleIds);
  const bulkEndpoint = tab === "email" ? "/email-templates" : "/sms-templates";
  const applyFailures = (failed) => {
    if (!failed?.length) return;
    const map = {};
    failed.forEach((f) => { map[f.id] = f.reason; });
    setLockedFailures(map);
    setTimeout(() => setLockedFailures({}), 10000);
  };
  const doBulkDelete = async () => {
    setBusy(true);
    try {
      const res = await api.post(`${bulkEndpoint}/bulk-delete`, {
        ids: Array.from(selected),
      });
      applyFailures(res.failed);
      const okC = res.deleted_count || 0;
      const failC = (res.failed || []).length;
      if (failC === 0) sonnerToast.success(`${okC} template${okC === 1 ? "" : "s"} deleted`);
      else sonnerToast(`${okC} deleted · ${failC} locked`, {
        description: (res.failed || []).slice(0, 3).map((f) => f.reason).join(" · "),
      });
      clear(); setConfirmOpen(false); reload();
    } catch (e) { sonnerToast.error(e?.message || "Bulk delete failed"); }
    finally { setBusy(false); }
  };
  const doBulkCategory = async (nextCategory) => {
    try {
      const res = await api.post(`${bulkEndpoint}/bulk-update`, {
        ids: Array.from(selected), patch: { category: nextCategory },
      });
      applyFailures(res.failed);
      sonnerToast.success(`${res.updated_count || 0} → ${nextCategory}`);
      clear(); reload();
    } catch (e) { sonnerToast.error(e?.message || "Category update failed"); }
  };

  const onDuplicate = async (code) => {
    try {
      const dup = tab === "email" ? await duplicateEmailTemplate(code) : await duplicateSmsTemplate(code);
      setToast({ tone: "success", message: `Duplicated → ${dup.code || "new template"}` });
      reload();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  const onDelete = async (code) => {
    if (!window.confirm(`Delete template "${code}"?`)) return;
    try {
      if (tab === "email") await deleteEmailTemplate(code); else await deleteSmsTemplate(code);
      setToast({ tone: "success", message: "Deleted" });
      reload();
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="comms-templates-library">
      <PageHeader
        icon={Layers}
        title="Communications library"
        subtitle="Manage all email and SMS templates for this workspace."
        actions={
          <BtnPrimary testid="comms-templates-new"
                       onClick={() => navigate(tab === "email" ? "/admin/comms/email/new" : "/admin/comms/sms/new")}>
            <span className="inline-flex items-center gap-1"><Plus size={14} /> New {tab === "email" ? "email" : "SMS"}</span>
          </BtnPrimary>
        }
      />

      <div className="flex items-center gap-2 mb-4">
        <button onClick={() => setTab("email")}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: tab === "email" ? colors.brand : colors.surface,
                         color: tab === "email" ? "#fff" : colors.onSurface,
                         border: `1px solid ${colors.border}` }}
                data-testid="comms-tab-email">
          <span className="inline-flex items-center gap-1.5"><Mail size={13} /> Email</span>
        </button>
        <button onClick={() => setTab("sms")}
                className="px-4 py-2 rounded-lg text-sm font-semibold"
                style={{ background: tab === "sms" ? colors.brand : colors.surface,
                         color: tab === "sms" ? "#fff" : colors.onSurface,
                         border: `1px solid ${colors.border}` }}
                data-testid="comms-tab-sms">
          <span className="inline-flex items-center gap-1.5"><MessageSquare size={13} /> SMS</span>
        </button>
        <div className="ml-4 flex items-center gap-2 flex-1 max-w-md">
          <Search size={14} style={{ color: colors.searchIcon }} />
          <input value={q} onChange={(e) => setQ(e.target.value)}
                 placeholder="Search templates…"
                 className="w-full text-sm px-2 py-1.5 rounded outline-none"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}`,
                          color: colors.onSurface }}
                 data-testid="comms-templates-search" />
        </div>
      </div>

      {loading ? (
        <div className="text-sm py-12 text-center" style={{ color: colors.muted }}>Loading…</div>
      ) : filtered.length === 0 ? (
        <EmptyState icon={Mail}
                    title={`No ${tab === "email" ? "email" : "SMS"} templates match`}
                    hint="Get started by creating a template."
                    cta={`Create your first ${tab === "email" ? "email" : "SMS"} template`}
                    onCta={() => navigate(tab === "email" ? "/admin/comms/email/new" : "/admin/comms/sms/new")} />
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 w-8">
                  <BulkSelectAll checked={allVisibleSelected}
                                   indeterminate={indeterminate}
                                   onChange={toggleAll} />
                </th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Name</th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Code</th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Type</th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Updated</th>
                <th className="text-right px-4 py-2 font-semibold" style={{ color: colors.muted }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((r) => {
                const rowId = r.id || r.code;
                return (
                <tr key={r.code} style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`comms-template-row-${r.code}`}>
                  <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                    <BulkSelectRow id={rowId} checked={selected.has(rowId)}
                                      onChange={() => toggleOne(rowId)} />
                  </td>
                  <td className="px-4 py-2.5 font-semibold" style={{ color: colors.onSurface }}>
                    {r.name || r.code}
                    {lockedFailures[rowId] ? (
                      <LockedPill reason={lockedFailures[rowId]}
                                    testid={`bulk-locked-pill-${rowId}`} />
                    ) : null}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs" style={{ color: colors.muted }}>{r.code}</td>
                  <td className="px-4 py-2.5">
                    {r.is_system ? (
                      <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                            style={{ background: "#DBEAFE", color: "#1E3A8A", border: "1px solid #93C5FD" }}>System</span>
                    ) : (
                      <span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                            style={{ background: colors.surface, color: colors.muted, border: `1px solid ${colors.border}` }}>Custom</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-xs" style={{ color: colors.muted }}>{(r.updated_at || r.created_at || "").slice(0, 10)}</td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <Link to={tab === "email" ? `/admin/comms/email/${encodeURIComponent(r.code)}` : `/admin/comms/sms/${encodeURIComponent(r.code)}`}
                          className="text-xs font-semibold mr-3"
                          style={{ color: colors.brand }}
                          data-testid={`comms-template-edit-${r.code}`}>Edit</Link>
                    <button className="text-xs font-semibold mr-3"
                            style={{ color: colors.onSurface }}
                            onClick={() => onDuplicate(r.code)}
                            data-testid={`comms-template-duplicate-${r.code}`}>Duplicate</button>
                    {!r.is_system ? (
                      <button className="text-xs font-semibold"
                              style={{ color: "#991B1B" }}
                              onClick={() => onDelete(r.code)}
                              data-testid={`comms-template-delete-${r.code}`}>Delete</button>
                    ) : null}
                  </td>
                </tr>
              );})}
            </tbody>
          </table>
        </Card>
      )}
      <Toast toast={toast} onClose={() => setToast(null)} />
      <BulkActionBar
        selectedCount={selectedCount}
        onClear={clear}
        actions={[
          { key: "category", label: "Change category",
            dropdown: [
              { value: "transactional", label: "Transactional" },
              { value: "marketing", label: "Marketing" },
              { value: "notification", label: "Notification" },
            ],
            onClick: (v) => doBulkCategory(v) },
          { key: "delete", label: "Delete selected", tone: "danger",
            onClick: () => setConfirmOpen(true) },
        ]}
      />
      <BulkConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onConfirm={doBulkDelete}
        title={`Delete ${selectedCount} template${selectedCount === 1 ? "" : "s"}?`}
        description="Templates used by an active drip automation will be locked and skipped — archive them from the drip instead."
        confirmLabel={busy ? "Deleting…" : `Delete ${selectedCount}`}
        busy={busy}
      />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════
// Email builder (block-list editor + right-side property panel)
// ═════════════════════════════════════════════════════════════════════

const EMAIL_BLOCK_PALETTE = [
  { type: "text",         label: "Text",         icon: TypeIcon,      defaults: { html: "<p>Write your message here.</p>", padding: "12px 24px", text_color: "#222" } },
  { type: "heading",      label: "Heading",      icon: HeadingIcon,   defaults: { text: "Heading", level: 1, alignment: "left", color: "#0f6ed1", padding: "16px 24px" } },
  { type: "image",        label: "Image",        icon: ImageIcon,     defaults: { url: "", alt: "", alignment: "center", width_pct: 100, padding: "12px 24px" } },
  { type: "button",       label: "Button",       icon: MousePointerClick, defaults: { label: "Click me", link_url: "", alignment: "left", background_color: "#0f6ed1", text_color: "#fff", border_radius: "6px", padding: "12px 24px" } },
  { type: "divider",      label: "Divider",      icon: Minus,         defaults: { color: "#e5e7eb", padding: "12px 24px" } },
  { type: "spacer",       label: "Spacer",       icon: MoveVertical,  defaults: { height_px: 20 } },
  { type: "columns_2",    label: "2 columns",    icon: Columns2,      defaults: { left_html: "<p>Left</p>", right_html: "<p>Right</p>", padding: "12px 24px" } },
  { type: "columns_3",    label: "3 columns",    icon: Columns3,      defaults: { left_html: "<p>Left</p>", middle_html: "<p>Middle</p>", right_html: "<p>Right</p>", padding: "12px 24px" } },
  { type: "social",       label: "Social",       icon: Share2,        defaults: { links: { facebook: "", twitter: "", instagram: "" }, alignment: "center", padding: "16px 24px" } },
  { type: "video",        label: "Video",        icon: Film,          defaults: { thumbnail_url: "", link_url: "", padding: "12px 24px" } },
  { type: "product_card", label: "Product card", icon: ShoppingBag,   defaults: { image_url: "", title: "", description: "", cta_label: "Learn more", link_url: "", padding: "16px 24px" } },
  { type: "footer",       label: "Footer",       icon: Layers,        defaults: { html: "<p>{{company.name}} · {{company.address}}<br><a href=\"{{unsubscribe_url}}\">Unsubscribe</a></p>", padding: "16px 24px", text_color: "#666" } },
];

function newBlock(type) {
  const spec = EMAIL_BLOCK_PALETTE.find((b) => b.type === type);
  return { type, ...(spec?.defaults || {}) };
}

function renderBlockPreview(block) {
  const pad = block.padding || "12px 24px";
  const s = { padding: pad };
  switch (block.type) {
    case "text":
      return <div style={{ ...s, color: block.text_color || "#222" }}
                  dangerouslySetInnerHTML={{ __html: block.html || "" }} />;
    case "heading": {
      const HTag = ["h1", "h2", "h3"][Math.min(2, Math.max(0, (block.level || 1) - 1))];
      return React.createElement(HTag, { style: { ...s, textAlign: block.alignment || "left", color: block.color || "#111" } }, block.text || "");
    }
    case "image":
      return <div style={{ ...s, textAlign: block.alignment || "center" }}>
        {block.url ? <img src={block.url} alt={block.alt || ""} style={{ maxWidth: `${block.width_pct || 100}%`, display: "inline-block" }} />
         : <div style={{ background: "#f3f4f6", padding: "24px", color: "#9ca3af", fontSize: 12 }}>Image URL not set</div>}
      </div>;
    case "button":
      return <div style={{ ...s, textAlign: block.alignment || "left" }}>
        <span style={{ background: block.background_color || "#0f6ed1", color: block.text_color || "#fff",
                        padding: "10px 20px", borderRadius: block.border_radius || 6, display: "inline-block", fontWeight: 600 }}>
          {block.label || "Button"}
        </span>
      </div>;
    case "divider":
      return <div style={s}><hr style={{ border: 0, borderTop: `1px solid ${block.color || "#e5e7eb"}` }} /></div>;
    case "spacer":
      return <div style={{ height: block.height_px || 20 }} />;
    case "columns_2":
      return <div style={{ ...s, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div dangerouslySetInnerHTML={{ __html: block.left_html || "" }} />
        <div dangerouslySetInnerHTML={{ __html: block.right_html || "" }} />
      </div>;
    case "columns_3":
      return <div style={{ ...s, display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
        <div dangerouslySetInnerHTML={{ __html: block.left_html || "" }} />
        <div dangerouslySetInnerHTML={{ __html: block.middle_html || "" }} />
        <div dangerouslySetInnerHTML={{ __html: block.right_html || "" }} />
      </div>;
    case "social":
      return <div style={{ ...s, textAlign: block.alignment || "center", color: "#374151", fontSize: 12 }}>
        Social links: {Object.entries(block.links || {}).filter(([, v]) => v).map(([k]) => k).join(" · ") || "(none set)"}
      </div>;
    case "video":
      return <div style={{ ...s, textAlign: "center" }}>
        {block.thumbnail_url ? <img src={block.thumbnail_url} alt="video thumbnail" style={{ maxWidth: "100%" }} /> : <div style={{ background: "#111", color: "#fff", padding: 24 }}>▶ Video</div>}
      </div>;
    case "product_card":
      return <div style={{ ...s, display: "grid", gridTemplateColumns: "80px 1fr", gap: 12, background: "#f9fafb", padding: 16, borderRadius: 8 }}>
        {block.image_url ? <img src={block.image_url} alt="" style={{ width: 80, height: 80, objectFit: "cover" }} /> : <div style={{ width: 80, height: 80, background: "#e5e7eb" }} />}
        <div>
          <div style={{ fontWeight: 700 }}>{block.title || "Product"}</div>
          <div style={{ fontSize: 13, color: "#374151" }}>{block.description}</div>
          <div style={{ marginTop: 8, color: "#0f6ed1", fontWeight: 600 }}>{block.cta_label || "Learn more"}</div>
        </div>
      </div>;
    case "footer":
      return <div style={{ ...s, color: block.text_color || "#666", fontSize: 12 }}
                  dangerouslySetInnerHTML={{ __html: block.html || "" }} />;
    default:
      return <div style={s}>Unknown block</div>;
  }
}

const FIELD_SPECS = {
  text: [{ k: "html", type: "textarea" }, { k: "padding" }, { k: "text_color" }],
  heading: [{ k: "text" }, { k: "level", type: "number" }, { k: "alignment" }, { k: "color" }, { k: "padding" }],
  image: [{ k: "url" }, { k: "alt" }, { k: "alignment" }, { k: "width_pct", type: "number" }, { k: "padding" }],
  button: [{ k: "label" }, { k: "link_url" }, { k: "alignment" }, { k: "background_color" }, { k: "text_color" }, { k: "border_radius" }, { k: "padding" }],
  divider: [{ k: "color" }, { k: "padding" }],
  spacer: [{ k: "height_px", type: "number" }],
  columns_2: [{ k: "left_html", type: "textarea" }, { k: "right_html", type: "textarea" }, { k: "padding" }],
  columns_3: [{ k: "left_html", type: "textarea" }, { k: "middle_html", type: "textarea" }, { k: "right_html", type: "textarea" }, { k: "padding" }],
  social: [{ k: "alignment" }, { k: "padding" }],
  video: [{ k: "thumbnail_url" }, { k: "link_url" }, { k: "padding" }],
  product_card: [{ k: "image_url" }, { k: "title" }, { k: "description", type: "textarea" }, { k: "cta_label" }, { k: "link_url" }, { k: "padding" }],
  footer: [{ k: "html", type: "textarea" }, { k: "padding" }, { k: "text_color" }],
};

// ═════════════════════════════════════════════════════════════════════
// P2 #11 · Phase 1 · Feb-2026 — helpers for drag-and-drop builder,
// inline WYSIWYG, brand-color-aware new-block defaults, and the
// Phase 1 test-send button.
// ═════════════════════════════════════════════════════════════════════

// ── Brand-primary binding (Q5-A hardening) ────────────────────────────
//
// Fetches the tenant's ``brand_primary`` once per editor mount via the
// existing ``GET /api/tenants/current`` endpoint. The value is applied
// ONLY to new blocks via ``_newBlockWithBrand`` — existing authored
// blocks that already have a ``color`` / ``background_color`` set on
// them are NEVER retroactively mutated (byte-identical round-trip is a
// hard requirement). Fallback to the pre-brand hard-coded colors in
// ``EMAIL_BLOCK_PALETTE`` when ``brand_primary`` is empty.

function _useBrandPrimary() {
  const [primary, setPrimary] = useState(null);
  useEffect(() => {
    let cancelled = false;
    api.get("/tenants/current")
      .then((t) => {
        if (cancelled) return;
        const bp = (t && (t.brand_primary || (t.branding || {}).brand_primary)) || null;
        setPrimary(bp);
      })
      .catch(() => { /* silent — fall back to EMAIL_BLOCK_PALETTE defaults */ });
    return () => { cancelled = true; };
  }, []);
  return primary;
}


function _newBlockWithBrand(type, brandPrimary) {
  const base = newBlock(type);
  if (!brandPrimary) return base;
  // Only override the color-bearing fields that read as "brand"
  // affordances. All other fields (padding, text, alt, etc.) keep
  // the palette-level defaults so authors see consistent whitespace
  // regardless of brand selection.
  if (type === "heading") {
    return { ...base, color: brandPrimary };
  }
  if (type === "button") {
    return { ...base, background_color: brandPrimary, text_color: "#fff" };
  }
  return base;
}


// ── TipTap inline WYSIWYG (Q3-A) ──────────────────────────────────────
//
// Thin wrapper over ``@tiptap/react`` that mirrors the extension set
// used by ``pages/settings/TosAdminEditor.jsx:54-62`` (StarterKit +
// Underline + Link) — no new deps. The ``html`` mode emits serialized
// HTML on blur / update; ``text`` mode emits plain text (used for
// heading.text so the server-side ``_H`` HTML-escape in
// ``services/comm_tokens.py::_render_block`` keeps producing identical
// output to the pre-Phase-1 textarea / input flow).
//
// Byte-identical round-trip guarantee: if the author never focuses the
// editor, ``onUpdate`` never fires and the parent state (and therefore
// the serialized ``blocks_json`` payload) retains the ORIGINAL value
// verbatim. See
// ``frontend/src/pages/comms/__tests__/CommsEmailBuilder.phase1.test.jsx``
// for the vitest case locking this invariant.

function _tiptapExtensions() {
  return [
    StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
    Underline,
    TipTapLink.configure({
      openOnClick: false,
      HTMLAttributes: { rel: "noopener noreferrer", target: "_blank" },
    }),
  ];
}


function _RichTextField({ value, mode, onChange, testid, rows = 4 }) {
  // ``mode`` ∈ {"html","text"}. HTML blocks pass through getHTML();
  // plain-text blocks pass through getText() to preserve the
  // server-side HTML-escape contract.
  const editor = useEditor({
    extensions: _tiptapExtensions(),
    content: value || "",
    onUpdate: ({ editor: ed }) => {
      const next = mode === "text" ? ed.getText() : ed.getHTML();
      onChange(next);
    },
    editorProps: {
      attributes: {
        "data-testid": testid,
        role: "textbox",
        "aria-multiline": "true",
        style: `min-height:${rows * 22}px;outline:none;padding:6px 8px;`,
      },
    },
  });
  // Re-sync the editor content if the parent swaps to a different
  // block (selectedIdx change) and the authored value lives there.
  useEffect(() => {
    if (editor && value !== undefined && value !== null) {
      // Only resync if the external value differs from the editor's
      // current serialization — prevents cursor-jump on every parent
      // re-render.
      const current = mode === "text" ? editor.getText() : editor.getHTML();
      if (current !== value) {
        editor.commands.setContent(value || "", /* emitUpdate */ false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, value, mode]);
  return (
    <div
      className="rounded"
      style={{
        background: colors.surface,
        border: `1px solid ${colors.border}`,
        color: colors.onSurface,
        fontSize: 12,
      }}
    >
      <EditorContent editor={editor} />
    </div>
  );
}


// ── Drag-and-drop (Q2-A — parallel click-to-add + drag) ───────────────
//
// Palette items are ``useDraggable`` sources. Canvas items are a
// ``SortableContext`` using ``verticalListSortingStrategy`` so blocks
// reorder on drop. The click-to-add path at ``addBlock`` is preserved
// verbatim (same test IDs ``comms-email-add-{type}``) for backwards
// compat with the existing pinsColoring / vitest suite.

function _PaletteDraggable({ palette, onClickAdd }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `palette-${palette.type}`,
    data: { kind: "palette", blockType: palette.type },
  });
  const Icon = palette.icon;
  return (
    <button
      type="button"
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={() => onClickAdd(palette.type)}
      className="flex items-center gap-2 text-xs px-2 py-1.5 rounded text-left"
      style={{
        background: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
        color: colors.onSurface,
        opacity: isDragging ? 0.5 : 1,
        cursor: "grab",
      }}
      data-testid={`comms-email-add-${palette.type}`}
      data-drag-source={`comms-email-drag-${palette.type}`}
    >
      <Icon size={13} /> {palette.label}
    </button>
  );
}


function _SortableBlockCard({
  block, idx, selected, onSelect, onMoveUp, onMoveDown, onRemove,
}) {
  const {
    attributes, listeners, setNodeRef, transform, transition, isDragging,
  } = useSortable({ id: `block-${idx}` });
  const style = {
    transform: DndCSS.Transform.toString(transform),
    transition,
    outline: selected ? `2px solid ${colors.brand}` : "none",
    outlineOffset: -2,
    opacity: isDragging ? 0.6 : 1,
    position: "relative",
    cursor: "pointer",
  };
  return (
    <div
      ref={setNodeRef}
      style={style}
      onClick={() => onSelect(idx)}
      data-testid={`comms-email-block-${idx}`}
    >
      {renderBlockPreview(block)}
      {/* Dedicated drag handle — do NOT make the whole card
           draggable (conflicts with inspector focus + click-to-select).
           Keyboard-sortable support comes free with @dnd-kit. */}
      <button
        type="button"
        {...listeners}
        {...attributes}
        onClick={(e) => e.stopPropagation()}
        aria-label={`Drag ${block.type} block`}
        className="absolute top-1 left-1 p-0.5 rounded"
        style={{
          background: "rgba(255,255,255,0.9)",
          border: `1px solid ${colors.border}`,
          cursor: "grab",
        }}
        data-testid={`comms-email-drag-handle-${idx}`}
      >
        <GripVertical size={12} />
      </button>
      {selected ? (
        <div
          className="absolute top-1 right-1 flex items-center gap-1 bg-white rounded px-1 py-0.5 shadow"
          onClick={(e) => e.stopPropagation()}
        >
          <button onClick={() => onMoveUp(idx)} title="Move up"
                  data-testid={`comms-block-up-${idx}`}><ChevronUp size={12} /></button>
          <button onClick={() => onMoveDown(idx)} title="Move down"
                  data-testid={`comms-block-down-${idx}`}><ChevronDown size={12} /></button>
          <button onClick={() => onRemove(idx)} title="Delete"
                  data-testid={`comms-block-remove-${idx}`}>
            <Trash2 size={12} color="#991B1B" />
          </button>
        </div>
      ) : null}
    </div>
  );
}


// ─── P2 #11 · Phase 2 (TD-42) · Feb-2026 — column nesting controls ───
//
// Per-column Flat → Nested one-way migration surface rendered inside
// the Properties inspector when a ``columns_2`` / ``columns_3`` block
// is selected.  The backend renderer already walks ``children`` (and
// falls back to flat ``*_html``) so this UI only has to flip the
// data shape:
//
//     block.props.left_html = "<p>Hi</p>"
//     block.children[0] = []
//        → click "Convert left to nested blocks"
//     block.props.left_html = ""
//     block.children[0] = [{type:"text", props:{html:"<p>Hi</p>"}}]
//
// After conversion the author can add further nested blocks via the
// "Add text block" affordance.  Reverting back to Flat is NOT offered
// — it would silently drop any additional children the author
// added.  See TD-48 for the canvas-side drag-zone follow-up.

const _COLUMN_SLOTS = {
  columns_2: [
    { key: "left_html", label: "Left column", idx: 0 },
    { key: "right_html", label: "Right column", idx: 1 },
  ],
  columns_3: [
    { key: "left_html", label: "Left column", idx: 0 },
    { key: "middle_html", label: "Middle column", idx: 1 },
    { key: "right_html", label: "Right column", idx: 2 },
  ],
};


function _ColumnNestingControls({ block, blockIdx, setBlocks }) {
  const slots = _COLUMN_SLOTS[block.type] || [];
  const children = Array.isArray(block.children)
    ? block.children
    : slots.map(() => []);

  const migrateToNested = (slot) => {
    setBlocks((xs) => xs.map((b, i) => {
      if (i !== blockIdx) return b;
      const nextChildren = [...(b.children || slots.map(() => []))];
      // Ensure arrays exist for every slot (schema invariant).
      while (nextChildren.length < slots.length) nextChildren.push([]);
      const flat = (b[slot.key] || "").trim();
      nextChildren[slot.idx] = flat
        ? [{ type: "text", props: { html: flat } }]
        : [];
      const nextProps = { ...b, children: nextChildren };
      nextProps[slot.key] = "";  // clear the flat value
      return nextProps;
    }));
  };

  const addNestedText = (slot) => {
    setBlocks((xs) => xs.map((b, i) => {
      if (i !== blockIdx) return b;
      const nextChildren = [...(b.children || slots.map(() => []))];
      while (nextChildren.length < slots.length) nextChildren.push([]);
      nextChildren[slot.idx] = [
        ...nextChildren[slot.idx],
        { type: "text", props: { html: "<p>New text</p>" } },
      ];
      return { ...b, children: nextChildren };
    }));
  };

  return (
    <div
      className="rounded p-2 space-y-2"
      style={{
        background: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={`comms-email-column-nesting-${blockIdx}`}
    >
      <div className="text-[11px] font-bold uppercase tracking-wider"
           style={{ color: colors.muted }}>
        Column mode
      </div>
      {slots.map((slot) => {
        const kids = children[slot.idx] || [];
        const isNested = kids.length > 0;
        return (
          <div key={slot.key} className="flex items-center justify-between gap-2">
            <div className="text-xs" style={{ color: colors.onSurface }}>
              <strong>{slot.label}</strong>
              <span className="ml-1" style={{ color: colors.muted }}>
                {isNested ? `nested · ${kids.length} block${kids.length === 1 ? "" : "s"}` : "flat HTML"}
              </span>
            </div>
            {isNested ? (
              <button
                type="button"
                onClick={() => addNestedText(slot)}
                className="text-[10px] font-bold px-2 py-0.5 rounded"
                style={{ background: colors.brand, color: "#fff" }}
                data-testid={`comms-email-column-add-${blockIdx}-${slot.idx}`}
              >
                + Text
              </button>
            ) : (
              <button
                type="button"
                onClick={() => migrateToNested(slot)}
                className="text-[10px] font-bold px-2 py-0.5 rounded"
                style={{
                  background: colors.surface,
                  border: `1px solid ${colors.border}`,
                  color: colors.onSurface,
                }}
                data-testid={`comms-email-column-convert-${blockIdx}-${slot.idx}`}
              >
                → Nested
              </button>
            )}
          </div>
        );
      })}
      <div className="text-[10px]" style={{ color: colors.muted }}>
        Nested blocks render inside the column at send time.
        Columns-inside-columns are not supported.
      </div>
    </div>
  );
}


// Field keys that render as inline WYSIWYG in the Phase 1 inspector.
// Q3-A: text + heading + footer + columns_* HTML slots. The ``mode``
// value controls the serialization — plain text for heading.text (to
// preserve the HTML-escape contract on the server renderer), HTML for
// everything else.
const _RICH_FIELDS = {
  text: { html: "html" },
  footer: { html: "html" },
  heading: { text: "text" },
  columns_2: { left_html: "html", right_html: "html" },
  columns_3: { left_html: "html", middle_html: "html", right_html: "html" },
};


export function CommsEmailBuilder() {
  const { code: routeCode } = useParams();
  const navigate = useNavigate();
  const isNew = !routeCode || routeCode === "new";
  const [code, setCode] = useState(isNew ? "" : routeCode);
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  // P2 #11 · Phase 2 (TD-43) — preheader input value.
  const [previewText, setPreviewText] = useState("");
  // P2 #11 · Phase 2 (TD-44) — UTM admin modal visibility.
  const [showUtmModal, setShowUtmModal] = useState(false);
  const [blocks, setBlocks] = useState([]);
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [tokenPicker, setTokenPicker] = useState(null); // {onInsert}
  const [preview, setPreview] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [isSystem, setIsSystem] = useState(false);
  // P2 #11 · Phase 1 — brand-primary auto-binding on NEW blocks
  // (existing blocks are NEVER retroactively mutated).
  const brandPrimary = _useBrandPrimary();
  // P2 #11 · Phase 1 — Q7-A viewport toggle in the preview modal.
  const [previewViewport, setPreviewViewport] = useState("desktop");
  // P2 #11 · Phase 1 — Q6-A inline test-send panel state.
  const [showTestSend, setShowTestSend] = useState(false);
  const [testSendTo, setTestSendTo] = useState("");
  const [testSending, setTestSending] = useState(false);
  // P2 #11 · Phase 1 — @dnd-kit sensors with keyboard-sortable
  // support (comes free from @dnd-kit/sortable).
  const dndSensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );

  useEffect(() => {
    if (isNew) return;
    getEmailTemplate(routeCode).then((d) => {
      setCode(d.code); setName(d.name || ""); setSubject(d.subject || "");
      setPreviewText(d.preview_text || "");  // P2 #11 Phase 2 (TD-43)
      setBlocks(Array.isArray(d.blocks_json) ? d.blocks_json : []);
      setIsSystem(!!d.is_system);
    }).catch((e) => setToast({ tone: "error", message: e.message }));
  }, [routeCode, isNew]);

  const addBlock = (type) => {
    // P2 #11 · Phase 1 — new blocks pick up ``brand_primary`` on
    // color-bearing fields (heading.color, button.background_color).
    // Existing blocks loaded from the server are NOT mutated.
    const b = _newBlockWithBrand(type, brandPrimary);
    setBlocks((xs) => [...xs, b]);
    setSelectedIdx(blocks.length);
  };
  const moveBlock = (i, delta) => {
    setBlocks((xs) => {
      const j = i + delta;
      if (j < 0 || j >= xs.length) return xs;
      const next = xs.slice();
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
    setSelectedIdx((s) => (s == null ? s : (s + delta)));
  };
  const removeBlock = (i) => {
    setBlocks((xs) => xs.filter((_, idx) => idx !== i));
    setSelectedIdx(null);
  };
  const updateBlockField = (idx, key, value) => {
    setBlocks((xs) => xs.map((b, i) => i === idx ? { ...b, [key]: value } : b));
  };

  const save = async () => {
    if (!code.trim() || !name.trim()) { setToast({ tone: "error", message: "Code and name are required" }); return; }
    setBusy(true);
    const payload = {
      code: code.trim(),
      name: name.trim(),
      subject,
      blocks_json: blocks,
      // P2 #11 · Phase 2 (TD-43) — Send empty-string on save so the
      // server's PATCH handler clears the preview_text field to
      // null (treats "" as explicit clear).
      preview_text: previewText,
    };
    try {
      if (isNew) {
        const saved = await createEmailTemplate(payload);
        setToast({ tone: "success", message: `Saved · ${saved.code}` });
        navigate(`/admin/comms/email/${encodeURIComponent(saved.code)}`, { replace: true });
      } else {
        await updateEmailTemplate(routeCode, payload);
        setToast({ tone: "success", message: "Saved" });
      }
    } catch (e) { setToast({ tone: "error", message: e.message }); } finally { setBusy(false); }
  };
  const duplicate = async () => {
    try {
      const d = await duplicateEmailTemplate(routeCode);
      setToast({ tone: "success", message: `Duplicated · ${d.code}` });
      navigate(`/admin/comms/email/${encodeURIComponent(d.code)}`);
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  const doPreview = async () => {
    try {
      const d = await previewEmailTemplate(isNew ? "__unsaved__" : routeCode);
      setPreview(d);
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  const insertIntoSubject = (t) => setSubject((s) => (s || "") + t);
  const insertIntoBlockHtml = (idx, key) => (t) => {
    const b = blocks[idx];
    updateBlockField(idx, key, (b[key] || "") + t);
  };

  // P2 #11 · Phase 1 — Dnd handler. Handles both intents:
  //   * Palette → Canvas drop  (data.kind === "palette") → append
  //     a new block to the end of the canvas with brand-color
  //     binding.
  //   * Canvas → Canvas reorder (data.kind === undefined, sortable
  //     item ids ``block-{idx}``) → arrayMove the dragged index
  //     to the target index.
  const onDragEnd = (event) => {
    const { active, over } = event;
    if (!over) return;
    if (active?.data?.current?.kind === "palette") {
      addBlock(active.data.current.blockType);
      return;
    }
    const fromId = String(active.id || "");
    const toId = String(over.id || "");
    if (!fromId.startsWith("block-") || !toId.startsWith("block-")) return;
    const from = Number(fromId.slice("block-".length));
    const to = Number(toId.slice("block-".length));
    if (from === to || Number.isNaN(from) || Number.isNaN(to)) return;
    setBlocks((xs) => arrayMove(xs, from, to));
    setSelectedIdx((s) => {
      if (s == null) return s;
      if (s === from) return to;
      if (from < s && s <= to) return s - 1;
      if (to <= s && s < from) return s + 1;
      return s;
    });
  };

  // P2 #11 · Phase 1 — Q6-A test-send handler.
  const sendTest = async () => {
    if (isNew) {
      setToast({ tone: "error",
                  message: "Save the template before sending a test." });
      return;
    }
    setTestSending(true);
    try {
      const res = await testSendEmailTemplate(
        routeCode, (testSendTo || "").trim() || undefined,
      );
      const r = res?.recipient || "(you)";
      setToast({ tone: "success", message: `Test sent to ${r}` });
      // 2-second cooldown to avoid double-fires on fast UIs.
      setTimeout(() => setTestSending(false), 2000);
    } catch (e) {
      setTestSending(false);
      const msg = (e?.data?.detail?.msg)
        || (typeof e?.data?.detail === "string" ? e.data.detail : null)
        || e?.message || "Test send failed";
      setToast({ tone: "error", message: msg });
    }
  };

  const selected = selectedIdx != null ? blocks[selectedIdx] : null;
  const selectedSpec = selected ? FIELD_SPECS[selected.type] || [] : [];

  return (
    <div className="max-w-full mx-auto p-4" data-testid="comms-email-builder">
      <PageHeader
        icon={Mail}
        title={isNew ? "New email template" : `Edit · ${code}`}
        subtitle={isSystem ? "System template — editable but shipped with the platform." : null}
        actions={
          <>
            <BtnGhost onClick={() => navigate("/admin/comms/templates")} testid="comms-back-library">Back</BtnGhost>
            <BtnGhost onClick={doPreview} testid="comms-email-preview"><Eye size={12} className="inline mr-1" /> Preview</BtnGhost>
            {!isNew ? (
              <BtnGhost
                onClick={() => setShowTestSend((v) => !v)}
                testid="comms-email-test-send-toggle"
              >
                <Send size={12} className="inline mr-1" /> Test send
              </BtnGhost>
            ) : null}
            {!isNew ? <BtnGhost onClick={duplicate} testid="comms-email-duplicate"><Copy size={12} className="inline mr-1" /> Duplicate</BtnGhost> : null}
            <BtnPrimary onClick={save} disabled={busy} testid="comms-email-save"><Save size={12} className="inline mr-1" /> Save</BtnPrimary>
          </>
        }
      />

      <Card className="p-4 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="block">
            <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>Code</div>
            <input value={code} onChange={(e) => setCode(e.target.value)} disabled={!isNew}
                   className="w-full text-sm px-2 py-1.5 rounded font-mono"
                   style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="comms-email-code" />
          </label>
          <label className="block">
            <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>Name</div>
            <input value={name} onChange={(e) => setName(e.target.value)}
                   className="w-full text-sm px-2 py-1.5 rounded"
                   style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="comms-email-name" />
          </label>
          <label className="block">
            <div className="text-xs font-bold uppercase tracking-wider mb-1 flex items-center justify-between" style={{ color: colors.muted }}>
              <span>Subject</span>
              <button className="text-[10px] font-bold px-2 py-0.5 rounded"
                      style={{ background: colors.brand, color: "#fff" }}
                      onClick={() => setTokenPicker({ onInsert: insertIntoSubject })}
                      data-testid="comms-email-subject-token">
                {"{ } Token"}
              </button>
            </div>
            <input value={subject} onChange={(e) => setSubject(e.target.value)}
                   className="w-full text-sm px-2 py-1.5 rounded"
                   style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                   data-testid="comms-email-subject" />
          </label>
          {/* P2 #11 · Phase 2 (TD-43) — preheader input. 150-char
               hard cap matches the Pydantic validator at
               ``routers/comms.py::EmailTemplateIn.preview_text``.
               Omitted / empty → server stores null + renderer
               skips the preheader span entirely. */}
          <label className="block">
            <div
              className="text-xs font-bold uppercase tracking-wider mb-1 flex items-center justify-between"
              style={{ color: colors.muted }}
            >
              <span>Preview text</span>
              <span className="text-[10px] font-normal normal-case tracking-normal"
                    style={{ color: colors.muted }}
                    data-testid="comms-email-preview-text-counter">
                {previewText.length} / 150
              </span>
            </div>
            <input
              value={previewText}
              onChange={(e) => setPreviewText(e.target.value.slice(0, 150))}
              placeholder="Shown in inbox preview under the subject line."
              className="w-full text-sm px-2 py-1.5 rounded"
              style={{
                background: colors.surface,
                border: `1px solid ${colors.border}`,
                color: colors.onSurface,
              }}
              maxLength={150}
              data-testid="comms-email-preview-text"
            />
          </label>
          {/* P2 #11 · Phase 2 (TD-44) — UTM admin modal trigger. */}
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => setShowUtmModal(true)}
              className="text-xs underline"
              style={{ color: colors.muted }}
              data-testid="comms-email-utm-settings"
            >
              UTM link settings
            </button>
          </div>
        </div>
      </Card>

      {/* P2 #11 · Phase 2 (TD-44) — UTM admin modal. */}
      {showUtmModal ? (
        <_UtmSettingsModal
          onClose={() => setShowUtmModal(false)}
          onSaved={(_v) => setToast({ tone: "success",
                                       message: "UTM settings saved" })}
        />
      ) : null}

      <div className="grid grid-cols-12 gap-4">
        {/* P2 #11 · Phase 1 · Feb-2026 — DnD-aware palette + canvas.
             Palette items are useDraggable sources; the canvas is
             a SortableContext. Click-to-add is preserved as a
             parallel affordance (Q2-A). */}
        <DndContext sensors={dndSensors} onDragEnd={onDragEnd}>
          {/* Palette */}
          <Card className="col-span-12 md:col-span-2 p-3">
            <div className="text-xs font-bold uppercase tracking-wider mb-2"
                 style={{ color: colors.muted }}>Blocks</div>
            <div className="grid grid-cols-2 md:grid-cols-1 gap-2"
                 data-testid="comms-email-palette">
              {EMAIL_BLOCK_PALETTE.map((b) => (
                <_PaletteDraggable key={b.type} palette={b}
                                   onClickAdd={addBlock} />
              ))}
            </div>
          </Card>

          {/* Canvas */}
          <Card className="col-span-12 md:col-span-7 p-4">
            <div className="text-xs font-bold uppercase tracking-wider mb-3"
                 style={{ color: colors.muted }}>Canvas</div>
            <div className="rounded-lg overflow-hidden"
                 style={{ background: "#fff",
                           border: `1px solid ${colors.border}` }}
                 data-testid="comms-email-canvas">
              {blocks.length === 0 ? (
                <div className="text-center py-16"
                     style={{ color: colors.muted, fontSize: 13 }}>
                  Drop-in blocks from the left to start building.
                </div>
              ) : (
                <SortableContext
                  items={blocks.map((_, i) => `block-${i}`)}
                  strategy={verticalListSortingStrategy}
                >
                  {blocks.map((b, i) => (
                    <_SortableBlockCard
                      key={i}
                      block={b}
                      idx={i}
                      selected={selectedIdx === i}
                      onSelect={setSelectedIdx}
                      onMoveUp={(j) => moveBlock(j, -1)}
                      onMoveDown={(j) => moveBlock(j, 1)}
                      onRemove={removeBlock}
                    />
                  ))}
                </SortableContext>
              )}
            </div>
          </Card>
        </DndContext>

        {/* Property panel */}
        <Card className="col-span-12 md:col-span-3 p-3">
          <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors.muted }}>Properties</div>
          {!selected ? (
            <div className="text-xs" style={{ color: colors.muted }}>
              Select a block on the canvas to edit its properties.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="text-sm font-bold" style={{ color: colors.onSurface }}>{selected.type}</div>
              {/* P2 #11 · Phase 2 (TD-42) · Feb-2026 — Flat ↔ Nested
                   per-column conversion.  One-way migration: the
                   per-column ``*_html`` flat string gets wrapped in
                   a single ``text`` child block and ``*_html`` is
                   cleared.  Reverse direction is NOT offered (would
                   silently drop any blocks the author added to
                   ``children[i]``).  See TD-48 for the canvas-side
                   drop-zone follow-up. */}
              {(selected.type === "columns_2" || selected.type === "columns_3") ? (
                <_ColumnNestingControls
                  block={selected}
                  blockIdx={selectedIdx}
                  setBlocks={setBlocks}
                />
              ) : null}
              {selectedSpec.map((f) => {
                const val = selected[f.k] ?? "";
                const change = (v) => updateBlockField(selectedIdx, f.k, f.type === "number" ? Number(v) : v);
                // P2 #11 · Phase 1 · Q3-A — inline WYSIWYG for the
                // text / heading / footer / column rich fields; all
                // other fields keep the structured input/textarea
                // affordance.
                const richMode = (_RICH_FIELDS[selected.type] || {})[f.k];
                return (
                  <label key={f.k} className="block">
                    <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5 flex items-center justify-between"
                         style={{ color: colors.muted }}>
                      <span>{f.k}</span>
                      {(f.type === "textarea" || richMode) ? (
                        <button className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                                style={{ background: colors.brand, color: "#fff" }}
                                onClick={() => setTokenPicker({ onInsert: insertIntoBlockHtml(selectedIdx, f.k) })}
                                data-testid={`comms-email-token-${f.k}`}>
                          {"{ } Token"}
                        </button>
                      ) : null}
                    </div>
                    {richMode ? (
                      <_RichTextField
                        value={val}
                        mode={richMode}
                        onChange={change}
                        testid={`comms-email-field-${f.k}`}
                        rows={4}
                      />
                    ) : f.type === "textarea" ? (
                      <textarea value={val} onChange={(e) => change(e.target.value)} rows={4}
                                className="w-full text-xs px-2 py-1 rounded font-mono"
                                style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                                data-testid={`comms-email-field-${f.k}`} />
                    ) : (
                      <input type={f.type || "text"} value={val} onChange={(e) => change(e.target.value)}
                             className="w-full text-xs px-2 py-1 rounded"
                             style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                             data-testid={`comms-email-field-${f.k}`} />
                    )}
                  </label>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      {/* P2 #11 · Phase 1 · Q6-A — inline test-send panel. Opens
           above the token picker modal; the recipient defaults to
           the admin's own email on the server (empty ``to`` falls
           back to ``current_user.email``). */}
      {showTestSend && !isNew ? (
        <div
          className="mt-3 rounded-lg p-3 flex items-center gap-2 flex-wrap"
          style={{
            background: colors.surfaceSecondary,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="comms-email-test-send-panel"
        >
          <span className="text-xs font-bold uppercase tracking-wider"
                style={{ color: colors.muted }}>
            Send test to
          </span>
          <input
            type="email"
            value={testSendTo}
            onChange={(e) => setTestSendTo(e.target.value)}
            placeholder="(your email)"
            className="text-xs px-2 py-1.5 rounded flex-1 min-w-[200px]"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="comms-email-test-send-input"
          />
          <BtnPrimary
            onClick={sendTest}
            disabled={testSending}
            testid="comms-email-test-send-submit"
          >
            {testSending ? "Sending…" : "Send"}
          </BtnPrimary>
          <BtnGhost
            onClick={() => { setShowTestSend(false); setTestSendTo(""); }}
            testid="comms-email-test-send-cancel"
          >
            Cancel
          </BtnGhost>
        </div>
      ) : null}

      <TokenPickerModal open={!!tokenPicker} onClose={() => setTokenPicker(null)}
                        onInsert={tokenPicker?.onInsert || (() => {})} />
      <PreviewModal preview={preview} onClose={() => setPreview(null)} kind="email"
                    viewport={previewViewport} onViewportChange={setPreviewViewport} />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════
// SMS Builder
// ═════════════════════════════════════════════════════════════════════

export function CommsSmsBuilder() {
  const { code: routeCode } = useParams();
  const navigate = useNavigate();
  const isNew = !routeCode || routeCode === "new";
  const [code, setCode] = useState(isNew ? "" : routeCode);
  const [name, setName] = useState("");
  const [body, setBody] = useState("");
  const [mediaUrl, setMediaUrl] = useState("");
  const [tokenPicker, setTokenPicker] = useState(false);
  const [preview, setPreview] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [isSystem, setIsSystem] = useState(false);

  useEffect(() => {
    if (isNew) return;
    getSmsTemplate(routeCode).then((d) => {
      setCode(d.code); setName(d.name || ""); setBody(d.body || "");
      setMediaUrl(d.media_url || "");
      setIsSystem(!!d.is_system);
    }).catch((e) => setToast({ tone: "error", message: e.message }));
  }, [routeCode, isNew]);

  const metrics = smsMetrics(body);
  const save = async () => {
    if (!code.trim() || !name.trim() || !body.trim()) {
      setToast({ tone: "error", message: "Code, name and body are required" }); return;
    }
    setBusy(true);
    const payload = { code: code.trim(), name: name.trim(), body, media_url: mediaUrl || null };
    try {
      if (isNew) {
        const saved = await createSmsTemplate(payload);
        setToast({ tone: "success", message: "Saved" });
        navigate(`/admin/comms/sms/${encodeURIComponent(saved.code)}`, { replace: true });
      } else {
        await updateSmsTemplate(routeCode, payload);
        setToast({ tone: "success", message: "Saved" });
      }
    } catch (e) { setToast({ tone: "error", message: e.message }); } finally { setBusy(false); }
  };
  const duplicate = async () => {
    try {
      const d = await duplicateSmsTemplate(routeCode);
      setToast({ tone: "success", message: `Duplicated · ${d.code}` });
      navigate(`/admin/comms/sms/${encodeURIComponent(d.code)}`);
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };
  const doPreview = async () => {
    try {
      const d = await previewSmsTemplate(isNew ? "__unsaved__" : routeCode);
      setPreview(d);
    } catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  return (
    <div className="max-w-3xl mx-auto p-4 md:p-6" data-testid="comms-sms-builder">
      <PageHeader
        icon={MessageSquare}
        title={isNew ? "New SMS template" : `Edit · ${code}`}
        subtitle={isSystem ? "System template — editable but shipped with the platform." : null}
        actions={
          <>
            <BtnGhost onClick={() => navigate("/admin/comms/templates")}>Back</BtnGhost>
            <BtnGhost onClick={doPreview} testid="comms-sms-preview"><Eye size={12} className="inline mr-1" /> Preview</BtnGhost>
            {!isNew ? <BtnGhost onClick={duplicate} testid="comms-sms-duplicate"><Copy size={12} className="inline mr-1" /> Duplicate</BtnGhost> : null}
            <BtnPrimary onClick={save} disabled={busy} testid="comms-sms-save"><Save size={12} className="inline mr-1" /> Save</BtnPrimary>
          </>
        }
      />
      <Card className="p-4 space-y-3">
        <label className="block">
          <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>Code</div>
          <input value={code} onChange={(e) => setCode(e.target.value)} disabled={!isNew}
                 className="w-full text-sm px-2 py-1.5 rounded font-mono"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="comms-sms-code" />
        </label>
        <label className="block">
          <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>Name</div>
          <input value={name} onChange={(e) => setName(e.target.value)}
                 className="w-full text-sm px-2 py-1.5 rounded"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="comms-sms-name" />
        </label>
        <label className="block">
          <div className="text-xs font-bold uppercase tracking-wider mb-1 flex items-center justify-between" style={{ color: colors.muted }}>
            <span>Body</span>
            <button className="text-[10px] font-bold px-2 py-0.5 rounded"
                    style={{ background: colors.brand, color: "#fff" }}
                    onClick={() => setTokenPicker(true)}
                    data-testid="comms-sms-token">
              {"{ } Token"}
            </button>
          </div>
          <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={5}
                    className="w-full text-sm px-2 py-1.5 rounded font-mono"
                    style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="comms-sms-body" />
          <div className="text-[11px] mt-1 flex items-center gap-3" style={{ color: colors.muted }}
               data-testid="comms-sms-metrics">
            <span><strong style={{ color: colors.onSurface }}>{metrics.chars}</strong> chars</span>
            <span><strong style={{ color: colors.onSurface }}>{metrics.segments}</strong> segment{metrics.segments !== 1 ? "s" : ""}</span>
            <span>{metrics.encoding}</span>
          </div>
        </label>
        <label className="block">
          <div className="text-xs font-bold uppercase tracking-wider mb-1" style={{ color: colors.muted }}>Media URL (MMS · optional)</div>
          <input value={mediaUrl} onChange={(e) => setMediaUrl(e.target.value)}
                 placeholder="https://…"
                 className="w-full text-sm px-2 py-1.5 rounded"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="comms-sms-media" />
          {mediaUrl ? (
            <div className="mt-2 rounded overflow-hidden" style={{ maxWidth: 200, border: `1px solid ${colors.border}` }}>
              <img src={mediaUrl} alt="MMS preview" style={{ maxWidth: "100%", display: "block" }} />
            </div>
          ) : null}
        </label>
      </Card>
      <TokenPickerModal open={tokenPicker} onClose={() => setTokenPicker(false)}
                        onInsert={(t) => setBody((b) => b + t)} />
      <PreviewModal preview={preview} onClose={() => setPreview(null)} kind="sms" />
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

// ─── P2 #11 · Phase 2 (TD-44) · Feb-2026 — UTM admin modal ───────────
function _UtmSettingsModal({ onClose, onSaved }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [utm, setUtm] = useState({
    utm_source: "", utm_medium: "", utm_campaign: "",
    utm_content: "", utm_term: "",
  });
  const [source, setSource] = useState("module_default");
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    api.get("/comms/tenants/current/email-utm").then((d) => {
      if (cancelled) return;
      setEnabled(Boolean(d.link_wrapping_enabled));
      const vals = d.utm_defaults || {};
      setUtm({
        utm_source: vals.utm_source || "",
        utm_medium: vals.utm_medium || "",
        utm_campaign: vals.utm_campaign || "",
        utm_content: vals.utm_content || "",
        utm_term: vals.utm_term || "",
      });
      setSource(d.defaults_source || "module_default");
    }).catch((e) => setErr(e?.message || "load failed"))
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const utm_defaults = {};
      for (const [k, v] of Object.entries(utm)) {
        if ((v || "").trim()) utm_defaults[k] = v.trim();
      }
      const res = await api.patch(
        "/comms/tenants/current/email-utm",
        { utm_defaults, link_wrapping_enabled: enabled },
      );
      onSaved?.(res);
      onClose();
    } catch (e) {
      setErr(e?.data?.detail?.msg || e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    setUtm({ utm_source: "", utm_medium: "", utm_campaign: "",
             utm_content: "", utm_term: "" });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      data-testid="comms-email-utm-modal"
    >
      <div
        className="rounded-2xl w-full max-w-xl shadow-xl overflow-hidden"
        style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="px-4 py-3 flex items-center justify-between"
          style={{ borderBottom: `1px solid ${colors.border}` }}
        >
          <div className="font-bold" style={{ color: colors.onSurface }}>
            UTM link settings
          </div>
          <button onClick={onClose}>
            <XIcon size={18} style={{ color: colors.muted }} />
          </button>
        </div>
        <div className="p-4 space-y-3">
          {loading ? (
            <div className="text-xs" style={{ color: colors.muted }}>
              Loading…
            </div>
          ) : (
            <>
              <label className="flex items-center gap-2 text-xs"
                     style={{ color: colors.onSurface }}>
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                  data-testid="comms-email-utm-enabled"
                />
                Enable link wrapping on outbound email
              </label>
              <div className="text-[11px]" style={{ color: colors.muted }}>
                Source: <strong>{source}</strong>. Supported placeholders
                in values: <code>{"{{template.code}}"}</code>.
              </div>
              {["utm_source", "utm_medium", "utm_campaign",
                "utm_content", "utm_term"].map((k) => (
                <label key={k} className="block">
                  <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5"
                       style={{ color: colors.muted }}>
                    {k}
                  </div>
                  <input
                    value={utm[k]}
                    onChange={(e) => setUtm((v) => ({ ...v, [k]: e.target.value }))}
                    className="w-full text-xs px-2 py-1 rounded"
                    style={{
                      background: colors.surface,
                      border: `1px solid ${colors.border}`,
                      color: colors.onSurface,
                    }}
                    data-testid={`comms-email-utm-${k}`}
                  />
                </label>
              ))}
              {err ? (
                <div className="text-xs" style={{ color: "#991B1B" }}>
                  {err}
                </div>
              ) : null}
            </>
          )}
        </div>
        <div
          className="px-4 py-3 flex items-center justify-between"
          style={{ borderTop: `1px solid ${colors.border}` }}
        >
          <button
            type="button"
            onClick={reset}
            className="text-xs underline"
            style={{ color: colors.muted }}
            data-testid="comms-email-utm-reset"
          >
            Clear overrides (use module defaults)
          </button>
          <button
            type="button"
            onClick={save}
            disabled={saving || loading}
            className="text-xs font-bold px-3 py-1.5 rounded"
            style={{ background: colors.brand, color: "#fff",
                     opacity: (saving || loading) ? 0.6 : 1 }}
            data-testid="comms-email-utm-save"
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}


function PreviewModal({ preview, onClose, kind, viewport = "desktop", onViewportChange }) {
  if (!preview) return null;
  // P2 #11 · Phase 1 · Q7-A — viewport-width toggle for the email
  // preview iframe. Desktop ≈ 600px (matches ``_CONTAINER_STYLE``
  // in ``services/comm_tokens.py`` renderer); Mobile ≈ 375px to
  // simulate an iPhone-14 viewport without requiring a real client.
  const previewWidth = viewport === "mobile" ? 375 : 600;
  const htmlSrc = preview.body_html || preview.html || "(no body)";
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
         style={{ background: "rgba(0,0,0,0.55)" }} onClick={onClose}
         data-testid="comms-preview-modal">
      <div className="rounded-2xl w-full max-w-3xl overflow-hidden shadow-xl"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           onClick={(e) => e.stopPropagation()}>
        <div className="px-4 py-3 flex items-center justify-between gap-2 flex-wrap" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="font-bold" style={{ color: colors.onSurface }}>Preview</div>
          {kind === "email" && onViewportChange ? (
            <div className="flex items-center gap-1 rounded"
                 style={{ background: colors.surfaceSecondary,
                           border: `1px solid ${colors.border}`, padding: 2 }}
                 role="tablist"
                 aria-label="Preview viewport"
                 data-testid="comms-preview-viewport-toggle">
              <button
                type="button"
                role="tab"
                aria-selected={viewport === "desktop"}
                onClick={() => onViewportChange("desktop")}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded"
                style={{
                  background: viewport === "desktop" ? colors.brand : "transparent",
                  color: viewport === "desktop" ? "#fff" : colors.onSurface,
                }}
                data-testid="comms-preview-viewport-desktop"
              >
                <Monitor size={12} /> Desktop
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={viewport === "mobile"}
                onClick={() => onViewportChange("mobile")}
                className="flex items-center gap-1 text-xs px-2 py-1 rounded"
                style={{
                  background: viewport === "mobile" ? colors.brand : "transparent",
                  color: viewport === "mobile" ? "#fff" : colors.onSurface,
                }}
                data-testid="comms-preview-viewport-mobile"
              >
                <Smartphone size={12} /> Mobile
              </button>
            </div>
          ) : null}
          <button onClick={onClose}><XIcon size={18} style={{ color: colors.muted }} /></button>
        </div>
        <div className="p-4 space-y-3">
          {kind === "email" ? (
            <>
              <div className="text-xs" style={{ color: colors.muted }}>
                <strong>Subject:</strong> {preview.subject || preview.resolved_subject || ""}
              </div>
              <div
                className="flex justify-center overflow-auto rounded"
                style={{ background: "#f4f4f4", padding: 12, maxHeight: 560 }}
              >
                <iframe
                  title="Email preview"
                  srcDoc={htmlSrc}
                  width={previewWidth}
                  height={520}
                  style={{
                    border: `1px solid ${colors.border}`,
                    background: "#fff",
                    transition: "width 120ms ease",
                  }}
                  data-testid="comms-preview-iframe"
                  data-viewport={viewport}
                />
              </div>
            </>
          ) : (
            <div className="text-sm font-mono p-3 rounded"
                 style={{ background: colors.surfaceSecondary, color: colors.onSurface, whiteSpace: "pre-wrap" }}>
              {preview.body || preview.resolved_body || "(no body)"}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════
// Automations page
// ═════════════════════════════════════════════════════════════════════

export function CommsAutomationsPage() {
  const [rows, setRows] = useState([]);
  const [emails, setEmails] = useState([]);
  const [smsRows, setSmsRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [toast, setToast] = useState(null);
  const [testTarget, setTestTarget] = useState(null);

  const reload = () => {
    setLoading(true);
    Promise.all([listAutomations(), listEmailTemplates(), listSmsTemplates()])
      .then(([a, e, s]) => {
        setRows(a.automations || a.automation_rules || a || []);
        setEmails(e.templates || e.email_templates || e || []);
        setSmsRows(s.templates || s.sms_templates || s || []);
      }).catch(() => {}).finally(() => setLoading(false));
  };
  useEffect(reload, []);

  const onDelete = async (code) => {
    if (!window.confirm(`Delete automation "${code}"?`)) return;
    try { await deleteAutomation(code); setToast({ tone: "success", message: "Deleted" }); reload(); }
    catch (e) { setToast({ tone: "error", message: e.message }); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="comms-automations-page">
      <PageHeader
        icon={Zap}
        title="Automations"
        subtitle="Fire templates automatically when trigger events occur."
        actions={<BtnPrimary onClick={() => setEditing({})} testid="comms-automation-new"><Plus size={12} className="inline mr-1" /> New rule</BtnPrimary>}
      />
      {loading ? (
        <div className="text-sm py-12 text-center" style={{ color: colors.muted }}>Loading…</div>
      ) : rows.length === 0 ? (
        <EmptyState icon={Zap} title="No automation rules yet" hint="Trigger emails or SMS from job/invoice events." cta="Create your first rule" onCta={() => setEditing({})} />
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: colors.surfaceSecondary }}>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Name</th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Trigger</th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Channel</th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Template</th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Delay</th>
                <th className="text-left px-4 py-2 font-semibold" style={{ color: colors.muted }}>Active</th>
                <th className="text-right px-4 py-2 font-semibold" style={{ color: colors.muted }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code} style={{ borderTop: `1px solid ${colors.border}` }}
                    data-testid={`comms-automation-row-${r.code}`}>
                  <td className="px-4 py-2.5 font-semibold" style={{ color: colors.onSurface }}>{r.name || r.code}</td>
                  <td className="px-4 py-2.5 font-mono text-xs" style={{ color: colors.muted }}>{r.trigger_event}</td>
                  <td className="px-4 py-2.5"><span className="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded"
                          style={{ background: r.channel === "email" ? "#DBEAFE" : "#FEF3C7",
                                   color: r.channel === "email" ? "#1E3A8A" : "#854D0E",
                                   border: `1px solid ${r.channel === "email" ? "#93C5FD" : "#FDE68A"}` }}>{r.channel}</span></td>
                  <td className="px-4 py-2.5 font-mono text-xs" style={{ color: colors.muted }}>{r.template_code}</td>
                  <td className="px-4 py-2.5 text-xs" style={{ color: colors.muted }}>{r.send_delay_minutes || 0}m</td>
                  <td className="px-4 py-2.5">{r.active ? "✓" : "—"}</td>
                  <td className="px-4 py-2.5 text-right whitespace-nowrap">
                    <button className="text-xs font-semibold mr-3" style={{ color: colors.brand }}
                            onClick={() => setEditing(r)}
                            data-testid={`comms-automation-edit-${r.code}`}>Edit</button>
                    <button className="text-xs font-semibold mr-3" style={{ color: colors.onSurface }}
                            onClick={() => setTestTarget(r)}
                            data-testid={`comms-automation-test-${r.code}`}>Test fire</button>
                    <button className="text-xs font-semibold" style={{ color: "#991B1B" }}
                            onClick={() => onDelete(r.code)}
                            data-testid={`comms-automation-delete-${r.code}`}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {editing !== null ? (
        <AutomationFormModal rule={editing} emails={emails} smsRows={smsRows}
                              onClose={() => setEditing(null)}
                              onSaved={() => { setEditing(null); reload(); setToast({ tone: "success", message: "Saved" }); }} />
      ) : null}
      {testTarget ? (
        <TestFireModal rule={testTarget} onClose={() => setTestTarget(null)}
                        onFired={(msg) => { setTestTarget(null); setToast({ tone: "success", message: msg }); }} />
      ) : null}
      <Toast toast={toast} onClose={() => setToast(null)} />
    </div>
  );
}

function AutomationFormModal({ rule, emails, smsRows, onClose, onSaved }) {
  const isNew = !rule?.code;
  const [form, setForm] = useState({
    code: rule?.code || "",
    name: rule?.name || "",
    description: rule?.description || "",
    trigger_event: rule?.trigger_event || TRIGGER_EVENTS[0],
    trigger_conditions: rule?.trigger_conditions ? JSON.stringify(rule.trigger_conditions, null, 2) : "{}",
    channel: rule?.channel || "email",
    template_code: rule?.template_code || "",
    send_delay_minutes: rule?.send_delay_minutes || 0,
    active: rule?.active !== false,
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const templates = form.channel === "email" ? emails : smsRows;

  const save = async () => {
    setErr("");
    let conds;
    try { conds = JSON.parse(form.trigger_conditions || "{}"); }
    catch { setErr("trigger_conditions must be valid JSON"); return; }
    setBusy(true);
    const payload = {
      code: form.code.trim(), name: form.name.trim(), description: form.description,
      trigger_event: form.trigger_event, trigger_conditions: conds,
      channel: form.channel, template_code: form.template_code,
      send_delay_minutes: Number(form.send_delay_minutes) || 0, active: form.active,
    };
    try {
      if (isNew) await createAutomation(payload); else await updateAutomation(rule.code, payload);
      onSaved();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
         style={{ background: "rgba(0,0,0,0.55)" }} onClick={onClose}
         data-testid="comms-automation-modal">
      <div className="rounded-2xl w-full max-w-xl overflow-hidden shadow-xl"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           onClick={(e) => e.stopPropagation()}>
        <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="font-bold" style={{ color: colors.onSurface }}>{isNew ? "New automation" : `Edit · ${rule.code}`}</div>
          <button onClick={onClose}><XIcon size={18} style={{ color: colors.muted }} /></button>
        </div>
        <div className="p-4 space-y-3 max-h-[70vh] overflow-y-auto">
          {err ? <div className="text-xs px-3 py-2 rounded" style={{ background: "#FEE2E2", color: "#991B1B" }}>{err}</div> : null}
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5" style={{ color: colors.muted }}>Code</div>
              <input value={form.code} onChange={(e) => set("code", e.target.value)} disabled={!isNew}
                     className="w-full text-xs px-2 py-1 rounded font-mono"
                     style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                     data-testid="comms-auto-form-code" />
            </label>
            <label className="block">
              <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5" style={{ color: colors.muted }}>Name</div>
              <input value={form.name} onChange={(e) => set("name", e.target.value)}
                     className="w-full text-xs px-2 py-1 rounded"
                     style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                     data-testid="comms-auto-form-name" />
            </label>
          </div>
          <label className="block">
            <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5" style={{ color: colors.muted }}>Description</div>
            <input value={form.description} onChange={(e) => set("description", e.target.value)}
                   className="w-full text-xs px-2 py-1 rounded"
                   style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5" style={{ color: colors.muted }}>Trigger</div>
              <select value={form.trigger_event} onChange={(e) => set("trigger_event", e.target.value)}
                      className="w-full text-xs px-2 py-1 rounded"
                      style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="comms-auto-form-trigger">
                {TRIGGER_EVENTS.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </label>
            <label className="block">
              <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5" style={{ color: colors.muted }}>Channel</div>
              <select value={form.channel} onChange={(e) => set("channel", e.target.value)}
                      className="w-full text-xs px-2 py-1 rounded"
                      style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="comms-auto-form-channel">
                <option value="email">email</option><option value="sms">sms</option>
              </select>
            </label>
          </div>
          <label className="block">
            <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5" style={{ color: colors.muted }}>Template</div>
            <select value={form.template_code} onChange={(e) => set("template_code", e.target.value)}
                    className="w-full text-xs px-2 py-1 rounded"
                    style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                    data-testid="comms-auto-form-template">
              <option value="">— select a template —</option>
              {templates.map((t) => <option key={t.code} value={t.code}>{t.name || t.code}</option>)}
            </select>
          </label>
          <label className="block">
            <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5" style={{ color: colors.muted }}>Trigger conditions (JSON)</div>
            <textarea value={form.trigger_conditions} onChange={(e) => set("trigger_conditions", e.target.value)}
                      rows={4}
                      className="w-full text-xs px-2 py-1 rounded font-mono"
                      style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                      data-testid="comms-auto-form-conds" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5" style={{ color: colors.muted }}>Delay (min)</div>
              <input type="number" value={form.send_delay_minutes} onChange={(e) => set("send_delay_minutes", e.target.value)}
                     className="w-full text-xs px-2 py-1 rounded"
                     style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }} />
            </label>
            <label className="flex items-end gap-2">
              <input type="checkbox" checked={form.active} onChange={(e) => set("active", e.target.checked)}
                     data-testid="comms-auto-form-active" />
              <span className="text-xs" style={{ color: colors.onSurface }}>Active</span>
            </label>
          </div>
        </div>
        <div className="px-4 py-3 flex items-center justify-end gap-2" style={{ borderTop: `1px solid ${colors.border}` }}>
          <BtnGhost onClick={onClose}>Cancel</BtnGhost>
          <BtnPrimary onClick={save} disabled={busy} testid="comms-auto-form-save">Save</BtnPrimary>
        </div>
      </div>
    </div>
  );
}

function TestFireModal({ rule, onClose, onFired }) {
  const [customers, setCustomers] = useState([]);
  const [recipient, setRecipient] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    api.get("/customers?is_active=true").then((rows) => setCustomers(rows || [])).catch(() => setCustomers([]));
  }, []);
  const fire = async () => {
    setBusy(true); setErr("");
    try {
      const d = await testFireAutomation(rule.code, recipient);
      onFired(`Test fired · send ${d.send_id || d.id || "queued"}`);
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
         style={{ background: "rgba(0,0,0,0.55)" }} onClick={onClose}>
      <div className="rounded-2xl w-full max-w-md p-4 shadow-xl"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           onClick={(e) => e.stopPropagation()}
           data-testid="comms-auto-testfire-modal">
        <div className="font-bold mb-2" style={{ color: colors.onSurface }}>Test fire · {rule.code}</div>
        {err ? <div className="text-xs px-3 py-2 rounded mb-2" style={{ background: "#FEE2E2", color: "#991B1B" }}>{err}</div> : null}
        <div className="text-xs mb-1" style={{ color: colors.muted }}>Recipient customer</div>
        <div className="mb-3">
          <CustomerCombobox
            value={recipient}
            onChange={setRecipient}
            customers={customers}
            testid="comms-auto-testfire-customer"
            placeholder="— select customer —"
          />
        </div>
        <div className="flex justify-end gap-2">
          <BtnGhost onClick={onClose}>Cancel</BtnGhost>
          <BtnPrimary onClick={fire} disabled={!recipient || busy} testid="comms-auto-testfire-go">Fire</BtnPrimary>
        </div>
      </div>
    </div>
  );
}

// ═════════════════════════════════════════════════════════════════════
// Sends History
// ═════════════════════════════════════════════════════════════════════

export function CommsSendsHistoryPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [kind, setKind] = useState("");
  const [status, setStatus] = useState("");
  const [recipientQ, setRecipientQ] = useState("");
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);

  const reload = () => {
    setLoading(true);
    listSends({ kind: kind || undefined, status: status || undefined,
                recipient: recipientQ || undefined, limit: 100 })
      .then((d) => setRows(d.sends || d || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(reload, [kind, status, recipientQ]); // eslint-disable-line react-hooks/exhaustive-deps

  const openDetail = async (row) => {
    setSelected(row);
    try { setDetail(await getSend(row.id)); }
    catch { setDetail(row); }
  };

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-6" data-testid="comms-sends-page">
      <PageHeader icon={Send} title="Sends history" subtitle="Every email + SMS delivery attempt." />

      <Card className="p-3 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <select value={kind} onChange={(e) => setKind(e.target.value)}
                  className="text-xs px-2 py-1.5 rounded"
                  style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="comms-sends-filter-kind">
            <option value="">All kinds</option>
            <option value="email">Email</option><option value="sms">SMS</option>
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}
                  className="text-xs px-2 py-1.5 rounded"
                  style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                  data-testid="comms-sends-filter-status">
            <option value="">All statuses</option>
            <option value="queued">Queued</option><option value="sent">Sent</option>
            <option value="mocked">Mocked</option><option value="failed">Failed</option>
            <option value="opted_out">Opted out</option><option value="missing_key">Missing key</option>
          </select>
          <input value={recipientQ} onChange={(e) => setRecipientQ(e.target.value)}
                 placeholder="Recipient contains…"
                 className="text-xs px-2 py-1.5 rounded"
                 style={{ background: colors.surface, border: `1px solid ${colors.border}`, color: colors.onSurface }}
                 data-testid="comms-sends-filter-recipient" />
          <div className="text-xs self-center" style={{ color: colors.muted }}>{rows.length} rows</div>
        </div>
      </Card>

      {loading ? (
        <div className="text-sm py-12 text-center" style={{ color: colors.muted }}>Loading…</div>
      ) : rows.length === 0 ? (
        <EmptyState icon={Send} title="No sends yet" hint="Send a template or fire an automation to see records here." />
      ) : (
        <Card>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ background: colors.surfaceSecondary }}>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>Kind</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>Template</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>Recipient</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>Status</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>Automation</th>
                <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.muted }}>Sent at</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} style={{ borderTop: `1px solid ${colors.border}`, cursor: "pointer" }}
                    onClick={() => openDetail(r)}
                    data-testid={`comms-sends-row-${r.id}`}>
                  <td className="px-3 py-2 text-xs">{r.kind}</td>
                  <td className="px-3 py-2 font-mono text-xs" style={{ color: colors.muted }}>{r.template_code}</td>
                  <td className="px-3 py-2 text-xs" style={{ color: colors.onSurface }}>{r.recipient_address || r.recipient_id || ""}</td>
                  <td className="px-3 py-2"><SendStatusPill status={r.status} /></td>
                  <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>{r.automation_code || ""}</td>
                  <td className="px-3 py-2 text-xs" style={{ color: colors.muted }}>{(r.sent_at || r.queued_at || "").slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {selected ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
             style={{ background: "rgba(0,0,0,0.55)" }} onClick={() => { setSelected(null); setDetail(null); }}
             data-testid="comms-sends-detail-modal">
          <div className="rounded-2xl w-full max-w-3xl max-h-[85vh] overflow-hidden shadow-xl"
               style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
               onClick={(e) => e.stopPropagation()}>
            <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.border}` }}>
              <div className="font-bold" style={{ color: colors.onSurface }}>
                {selected.kind} · {selected.template_code} · <SendStatusPill status={selected.status} />
              </div>
              <button onClick={() => { setSelected(null); setDetail(null); }}><XIcon size={18} style={{ color: colors.muted }} /></button>
            </div>
            <div className="p-4 overflow-y-auto space-y-3 max-h-[70vh]">
              <div className="text-xs" style={{ color: colors.muted }}>
                Recipient: <strong style={{ color: colors.onSurface }}>{selected.recipient_address || selected.recipient_id}</strong>
              </div>
              {detail?.error ? <div className="text-xs px-3 py-2 rounded" style={{ background: "#FEE2E2", color: "#991B1B" }}>{detail.error}</div> : null}
              {detail?.provider_message_id ? (
                <div className="text-xs" style={{ color: colors.muted }}>
                  Provider message id: <span className="font-mono" style={{ color: colors.onSurface }}>{detail.provider_message_id}</span>
                </div>
              ) : null}
              {selected.kind === "email" ? (
                <>
                  <div className="text-xs" style={{ color: colors.muted }}><strong>Subject:</strong> {detail?.subject || selected.subject}</div>
                  <div className="rounded" style={{ border: `1px solid ${colors.border}`, background: "#fff", padding: 8 }}
                       dangerouslySetInnerHTML={{ __html: (detail?.body_html || detail?.rendered_body || selected.body_html) || "(body not stored)" }} />
                </>
              ) : (
                <div className="text-sm font-mono p-3 rounded" style={{ background: colors.surfaceSecondary, whiteSpace: "pre-wrap", color: colors.onSurface }}>
                  {(detail?.body_text || detail?.rendered_body || selected.body_text) || "(body not stored)"}
                </div>
              )}
              {detail?.tokens_resolved ? (
                <details className="text-xs">
                  <summary style={{ color: colors.muted }}>Resolved tokens</summary>
                  <pre className="mt-1 p-2 rounded font-mono"
                       style={{ background: colors.surfaceSecondary, color: colors.onSurface,
                                border: `1px solid ${colors.border}`, whiteSpace: "pre-wrap" }}>
                    {JSON.stringify(detail.tokens_resolved, null, 2)}
                  </pre>
                </details>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
