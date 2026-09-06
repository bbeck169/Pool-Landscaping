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
import React, { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Mail, MessageSquare, Zap, Send, Plus, Trash2, Copy, Eye, Save, Type as TypeIcon, Heading as HeadingIcon, Image as ImageIcon, MousePointerClick, Minus, MoveVertical, Columns2, Columns3, Share2, Film, ShoppingBag, Layers, ChevronUp, ChevronDown, Search, X as XIcon } from "lucide-react";
import { toast as sonnerToast } from "sonner";
import { colors } from "@/theme";
import { api } from "@/api";
import CustomerCombobox from "@/components/customers/CustomerCombobox";
import {
  listEmailTemplates, getEmailTemplate, createEmailTemplate,
  updateEmailTemplate, deleteEmailTemplate, duplicateEmailTemplate,
  previewEmailTemplate,
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
          <Search size={14} style={{ color: colors.muted }} />
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

export function CommsEmailBuilder() {
  const { code: routeCode } = useParams();
  const navigate = useNavigate();
  const isNew = !routeCode || routeCode === "new";
  const [code, setCode] = useState(isNew ? "" : routeCode);
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [blocks, setBlocks] = useState([]);
  const [selectedIdx, setSelectedIdx] = useState(null);
  const [tokenPicker, setTokenPicker] = useState(null); // {onInsert}
  const [preview, setPreview] = useState(null);
  const [toast, setToast] = useState(null);
  const [busy, setBusy] = useState(false);
  const [isSystem, setIsSystem] = useState(false);

  useEffect(() => {
    if (isNew) return;
    getEmailTemplate(routeCode).then((d) => {
      setCode(d.code); setName(d.name || ""); setSubject(d.subject || "");
      setBlocks(Array.isArray(d.blocks_json) ? d.blocks_json : []);
      setIsSystem(!!d.is_system);
    }).catch((e) => setToast({ tone: "error", message: e.message }));
  }, [routeCode, isNew]);

  const addBlock = (type) => {
    const b = newBlock(type);
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
    const payload = { code: code.trim(), name: name.trim(), subject, blocks_json: blocks };
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
        </div>
      </Card>

      <div className="grid grid-cols-12 gap-4">
        {/* Palette */}
        <Card className="col-span-12 md:col-span-2 p-3">
          <div className="text-xs font-bold uppercase tracking-wider mb-2" style={{ color: colors.muted }}>Blocks</div>
          <div className="grid grid-cols-2 md:grid-cols-1 gap-2">
            {EMAIL_BLOCK_PALETTE.map((b) => (
              <button key={b.type} onClick={() => addBlock(b.type)}
                      className="flex items-center gap-2 text-xs px-2 py-1.5 rounded text-left"
                      style={{ background: colors.surfaceSecondary, border: `1px solid ${colors.border}`,
                               color: colors.onSurface }}
                      data-testid={`comms-email-add-${b.type}`}>
                <b.icon size={13} /> {b.label}
              </button>
            ))}
          </div>
        </Card>

        {/* Canvas */}
        <Card className="col-span-12 md:col-span-7 p-4">
          <div className="text-xs font-bold uppercase tracking-wider mb-3" style={{ color: colors.muted }}>Canvas</div>
          <div className="rounded-lg overflow-hidden" style={{ background: "#fff", border: `1px solid ${colors.border}` }}>
            {blocks.length === 0 ? (
              <div className="text-center py-16" style={{ color: colors.muted, fontSize: 13 }}>
                Drop-in blocks from the left to start building.
              </div>
            ) : blocks.map((b, i) => (
              <div key={i}
                   onClick={() => setSelectedIdx(i)}
                   className="relative cursor-pointer"
                   style={{ outline: selectedIdx === i ? `2px solid ${colors.brand}` : "none",
                            outlineOffset: -2 }}
                   data-testid={`comms-email-block-${i}`}>
                {renderBlockPreview(b)}
                {selectedIdx === i ? (
                  <div className="absolute top-1 right-1 flex items-center gap-1 bg-white rounded px-1 py-0.5 shadow"
                       onClick={(e) => e.stopPropagation()}>
                    <button onClick={() => moveBlock(i, -1)} title="Move up"
                            data-testid={`comms-block-up-${i}`}><ChevronUp size={12} /></button>
                    <button onClick={() => moveBlock(i, 1)} title="Move down"
                            data-testid={`comms-block-down-${i}`}><ChevronDown size={12} /></button>
                    <button onClick={() => removeBlock(i)} title="Delete"
                            data-testid={`comms-block-remove-${i}`}><Trash2 size={12} color="#991B1B" /></button>
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </Card>

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
              {selectedSpec.map((f) => {
                const val = selected[f.k] ?? "";
                const change = (v) => updateBlockField(selectedIdx, f.k, f.type === "number" ? Number(v) : v);
                return (
                  <label key={f.k} className="block">
                    <div className="text-[11px] font-bold uppercase tracking-wider mb-0.5 flex items-center justify-between"
                         style={{ color: colors.muted }}>
                      <span>{f.k}</span>
                      {f.type === "textarea" ? (
                        <button className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                                style={{ background: colors.brand, color: "#fff" }}
                                onClick={() => setTokenPicker({ onInsert: insertIntoBlockHtml(selectedIdx, f.k) })}
                                data-testid={`comms-email-token-${f.k}`}>
                          {"{ } Token"}
                        </button>
                      ) : null}
                    </div>
                    {f.type === "textarea" ? (
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

      <TokenPickerModal open={!!tokenPicker} onClose={() => setTokenPicker(null)}
                        onInsert={tokenPicker?.onInsert || (() => {})} />
      <PreviewModal preview={preview} onClose={() => setPreview(null)} kind="email" />
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

function PreviewModal({ preview, onClose, kind }) {
  if (!preview) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
         style={{ background: "rgba(0,0,0,0.55)" }} onClick={onClose}
         data-testid="comms-preview-modal">
      <div className="rounded-2xl w-full max-w-2xl overflow-hidden shadow-xl"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           onClick={(e) => e.stopPropagation()}>
        <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="font-bold" style={{ color: colors.onSurface }}>Preview</div>
          <button onClick={onClose}><XIcon size={18} style={{ color: colors.muted }} /></button>
        </div>
        <div className="p-4 space-y-3">
          {kind === "email" ? (
            <>
              <div className="text-xs" style={{ color: colors.muted }}>
                <strong>Subject:</strong> {preview.subject || preview.resolved_subject || ""}
              </div>
              <div className="rounded" style={{ border: `1px solid ${colors.border}`, background: "#fff", padding: 8, maxHeight: 500, overflow: "auto" }}
                   dangerouslySetInnerHTML={{ __html: preview.body_html || preview.html || "(no body)" }} />
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
