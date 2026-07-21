import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Plus,
  Mail,
  MessageSquare,
  Copy,
  Save,
  Trash2,
  X as XIcon,
  Eye,
  ChevronDown,
} from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";

/**
 * Feb-2026 · Marketing Slice M3 — Template library admin page.
 *
 * Reusable per-tenant email + SMS templates. M5 drip sequences and
 * (later) M2 campaigns will consume this store; this page is the
 * standalone edit surface.
 */
const CHANNEL_OPTIONS = [
  { v: "email", l: "Email" },
  { v: "sms", l: "SMS" },
];
const CATEGORY_OPTIONS = [
  "service_completed",
  "invoice_sent",
  "past_due",
  "welcome",
  "review_request",
  "general",
];

export default function MarketingTemplatesLibraryPage() {
  const [rows, setRows] = useState([]);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ channel: "", category: "", active: "" });
  const [editing, setEditing] = useState(null);   // template row or {} for new

  const load = () => {
    const p = new URLSearchParams();
    if (filters.channel) p.set("channel", filters.channel);
    if (filters.category) p.set("category", filters.category);
    if (filters.active) p.set("active", filters.active);
    setLoading(true);
    api
      .get(`/marketing/templates?${p.toString()}`)
      .then((r) => {
        setRows(r.templates || []);
        setCount(r.count || 0);
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  };
  useEffect(load, [filters]);

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-6"
         data-testid="marketing-templates-page">
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: colors.onSurface }}>
            Templates
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            {count} template{count === 1 ? "" : "s"} — reusable across campaigns and drips.
          </p>
        </div>
        <button
          onClick={() => setEditing({})}
          className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white"
          style={{ background: brandGradientCss }}
          data-testid="template-create-btn"
        >
          <Plus size={16} /> New template
        </button>
      </div>

      <div
        className="rounded-xl p-3 mb-4 grid grid-cols-2 sm:grid-cols-3 gap-2"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <FilterSelect
          label="CHANNEL"
          value={filters.channel}
          onChange={(v) => setFilters((f) => ({ ...f, channel: v }))}
          options={[{ v: "", l: "Any" }, ...CHANNEL_OPTIONS]}
          testid="tmpl-filter-channel"
        />
        <FilterSelect
          label="CATEGORY"
          value={filters.category}
          onChange={(v) => setFilters((f) => ({ ...f, category: v }))}
          options={[{ v: "", l: "Any" },
                     ...CATEGORY_OPTIONS.map((c) => ({ v: c, l: c }))]}
          testid="tmpl-filter-category"
        />
        <FilterSelect
          label="ACTIVE"
          value={filters.active}
          onChange={(v) => setFilters((f) => ({ ...f, active: v }))}
          options={[
            { v: "", l: "Any" },
            { v: "true", l: "Active" },
            { v: "false", l: "Inactive" },
          ]}
          testid="tmpl-filter-active"
        />
      </div>

      <div
        className="rounded-2xl overflow-hidden"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        {loading ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>Loading…</div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-sm text-center" style={{ color: colors.muted }}>
            No templates yet.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr style={{ borderBottom: `1px solid ${colors.divider}` }}>
                {["Name", "Channel", "Category", "Active", "Updated"].map((h) => (
                  <th key={h}
                      className="text-left py-2 px-3 text-xs font-bold uppercase tracking-wide"
                      style={{ color: colors.muted }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.id}
                  onClick={() => setEditing(r)}
                  className="cursor-pointer hover:brightness-95"
                  style={{ borderBottom: `1px solid ${colors.divider}` }}
                  data-testid={`template-row-${r.id}`}
                >
                  <td className="py-3 px-3" style={{ color: colors.onSurface }}>
                    {r.name}
                    {r.system ? (
                      <span
                        className="ml-2 text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                        style={{ backgroundColor: "#DBEAFE", color: "#1E3A8A" }}
                      >
                        SEED
                      </span>
                    ) : null}
                  </td>
                  <td className="py-3 px-3">
                    <ChannelBadge channel={r.channel} />
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.onSurfaceSecondary }}>
                    {r.category}
                  </td>
                  <td className="py-3 px-3">
                    <span
                      className="text-[10px] font-bold px-1.5 py-0.5 rounded-full"
                      style={{
                        backgroundColor: r.active ? "#DCFCE7" : "#FEE2E2",
                        color: r.active ? "#166534" : "#991B1B",
                      }}
                    >
                      {r.active ? "ACTIVE" : "INACTIVE"}
                    </span>
                  </td>
                  <td className="py-3 px-3" style={{ color: colors.muted }}>
                    {String(r.updated_at || "").slice(0, 10)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing !== null ? (
        <TemplateEditor
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      ) : null}
    </div>
  );
}


function FilterSelect({ label, value, onChange, options, testid }) {
  return (
    <label className="flex flex-col gap-1">
      <span
        className="text-[10px] font-bold uppercase tracking-wider"
        style={{ color: colors.muted }}
      >{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-2 py-1.5 rounded-lg text-sm outline-none"
        style={{
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid={testid}
      >
        {options.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
      </select>
    </label>
  );
}


function ChannelBadge({ channel }) {
  const isEmail = channel === "email";
  return (
    <span
      className="inline-flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded-full"
      style={{
        backgroundColor: isEmail ? "#DBEAFE" : "#F1F5F9",
        color: isEmail ? "#1E3A8A" : "#334155",
      }}
    >
      {isEmail ? <Mail size={11} /> : <MessageSquare size={11} />}
      {String(channel || "").toUpperCase()}
    </span>
  );
}


function TemplateEditor({ initial, onClose, onSaved }) {
  const isNew = !initial?.id;
  const [row, setRow] = useState(() => ({
    name: initial?.name || "",
    channel: initial?.channel || "email",
    category: initial?.category || "general",
    subject: initial?.subject || "",
    body: initial?.body || "",
    active: initial?.active ?? true,
  }));
  const [preview, setPreview] = useState({ subject: "", body: "", missing: [] });
  const [variables, setVariables] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bodyRef = useRef(null);

  useEffect(() => {
    api.get("/marketing/templates/variables").then((r) => setVariables(r.variables || []));
  }, []);

  // Debounced preview — server-side render.  For a NEW template we
  // can't call ``/{id}/preview`` yet, so we render client-side using
  // the same Mustache regex.  Once saved, the server-side preview
  // takes over on subsequent keystrokes.
  useEffect(() => {
    const t = setTimeout(() => {
      if (initial?.id) {
        api
          .post(`/marketing/templates/${initial.id}/preview`, {})
          .then((r) => setPreview({
            subject: r.subject_rendered || "",
            body: r.body_rendered || "",
            missing: r.missing_vars || [],
          }))
          .catch(() => {});
      } else {
        const { rendered: subj, missing: sMiss } =
          clientRender(row.subject || "");
        const { rendered: bod, missing: bMiss } =
          clientRender(row.body || "");
        const smsStripped =
          row.channel === "sms" ? bod.replace(/<[^>]+>/g, "") : bod;
        setPreview({
          subject: row.channel === "email" ? subj : "",
          body: smsStripped,
          missing: Array.from(new Set([...sMiss, ...bMiss])).sort(),
        });
      }
    }, 260);
    return () => clearTimeout(t);
  }, [row.subject, row.body, row.channel, initial?.id]);

  const insertVar = (name) => {
    const insertion = `{{${name}}}`;
    const el = bodyRef.current;
    if (!el) {
      setRow((r) => ({ ...r, body: (r.body || "") + insertion }));
      return;
    }
    const start = el.selectionStart ?? row.body.length;
    const end = el.selectionEnd ?? row.body.length;
    const next =
      (row.body || "").slice(0, start) + insertion + (row.body || "").slice(end);
    setRow((r) => ({ ...r, body: next }));
    // Restore cursor
    setTimeout(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = start + insertion.length;
    }, 0);
  };

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      if (isNew) {
        await api.post("/marketing/templates", row);
      } else {
        await api.patch(`/marketing/templates/${initial.id}`, row);
      }
      onSaved?.();
    } catch (err) {
      setError(err?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  const del = async () => {
    if (!initial?.id) return;
    if (!window.confirm("Deactivate this template?")) return;
    setBusy(true);
    try {
      await api.delete(`/marketing/templates/${initial.id}`);
      onSaved?.();
    } catch (err) {
      setError(err?.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
      data-testid="template-edit-modal"
    >
      <div
        className="w-full sm:w-[720px] h-full shadow-2xl flex flex-col"
        style={{
          backgroundColor: colors.surface,
          borderLeft: `1px solid ${colors.border}`,
        }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between px-5 pt-4 pb-3"
          style={{ borderBottom: `1px solid ${colors.divider}` }}
        >
          <div>
            <div className="text-xs" style={{ color: colors.muted }}>
              {isNew ? "New template" : "Edit template"}
            </div>
            <h2 className="text-lg font-bold" style={{ color: colors.onSurface }}>
              {row.name || "Untitled"}
            </h2>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg" style={{ color: colors.muted }} aria-label="Close">
            <XIcon size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 grid md:grid-cols-2 gap-5">
          <div className="space-y-3">
            <Field label="NAME">
              <input
                type="text"
                value={row.name}
                onChange={(e) => setRow((r) => ({ ...r, name: e.target.value }))}
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="template-name-input"
              />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="CHANNEL">
                <select
                  value={row.channel}
                  onChange={(e) => setRow((r) => ({ ...r, channel: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="template-channel-select"
                >
                  {CHANNEL_OPTIONS.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
                </select>
              </Field>
              <Field label="CATEGORY">
                <select
                  value={row.category}
                  onChange={(e) => setRow((r) => ({ ...r, category: e.target.value }))}
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="template-category-select"
                >
                  {CATEGORY_OPTIONS.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </Field>
            </div>
            {row.channel === "email" ? (
              <Field label="SUBJECT">
                <input
                  type="text"
                  value={row.subject}
                  onChange={(e) => setRow((r) => ({ ...r, subject: e.target.value }))}
                  placeholder="Your subject… supports {{customer.first_name}}"
                  className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                  style={{
                    backgroundColor: colors.surface,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="template-subject-input"
                />
              </Field>
            ) : null}
            <Field label="BODY">
              <textarea
                ref={bodyRef}
                value={row.body}
                onChange={(e) => setRow((r) => ({ ...r, body: e.target.value }))}
                rows={12}
                placeholder="Write your message… insert variables with the button above."
                className="w-full px-3 py-2 rounded-lg text-sm outline-none font-mono"
                style={{
                  backgroundColor: colors.surface,
                  color: colors.onSurface,
                  border: `1px solid ${colors.border}`,
                }}
                data-testid="template-body-input"
              />
            </Field>
            <InsertVariableButton
              variables={variables}
              onInsert={insertVar}
            />
          </div>

          {/* Live preview */}
          <div
            className="rounded-xl p-4"
            style={{
              backgroundColor: colors.surfaceSecondary,
              border: `1px solid ${colors.divider}`,
            }}
            data-testid="template-preview-pane"
          >
            <div className="flex items-center gap-2 mb-3" style={{ color: colors.muted }}>
              <Eye size={14} />
              <span className="text-[10px] font-bold uppercase tracking-wider">
                LIVE PREVIEW
              </span>
              <ChannelBadge channel={row.channel} />
            </div>
            {row.channel === "email" ? (
              <div className="mb-3">
                <div className="text-[10px] font-bold uppercase tracking-wide"
                     style={{ color: colors.muted }}>SUBJECT</div>
                <div className="text-sm font-semibold mt-0.5"
                     style={{ color: colors.onSurface }}
                     data-testid="template-preview-subject">
                  {preview.subject || <span style={{ color: colors.muted }}>(empty)</span>}
                </div>
              </div>
            ) : null}
            <div className="text-[10px] font-bold uppercase tracking-wide"
                 style={{ color: colors.muted }}>BODY</div>
            <pre
              className="text-sm mt-0.5 whitespace-pre-wrap font-sans"
              style={{ color: colors.onSurface }}
              data-testid="template-preview-body"
            >
              {preview.body || (
                <span style={{ color: colors.muted }}>(empty)</span>
              )}
            </pre>
            {preview.missing.length > 0 ? (
              <div
                className="mt-3 rounded-lg p-2 text-xs"
                style={{
                  backgroundColor: "#FEF3C7",
                  color: "#92400E",
                  border: "1px solid #FCD34D",
                }}
                data-testid="template-preview-missing"
              >
                <div className="font-bold mb-1">Missing variables</div>
                <div className="font-mono">
                  {preview.missing.join(", ")}
                </div>
              </div>
            ) : null}
          </div>
        </div>

        {error ? (
          <div className="px-5 pb-2 text-sm" style={{ color: colors.error }}>{error}</div>
        ) : null}
        <div
          className="p-4 flex items-center justify-between gap-2"
          style={{ borderTop: `1px solid ${colors.divider}` }}
        >
          <div>
            {!isNew ? (
              <button
                onClick={del}
                disabled={busy}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
                style={{
                  backgroundColor: colors.surfaceSecondary,
                  color: colors.error,
                }}
              >
                <Trash2 size={14} /> Deactivate
              </button>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-sm font-semibold"
              style={{
                backgroundColor: colors.surfaceSecondary,
                color: colors.onSurface,
              }}
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={busy}
              className="inline-flex items-center gap-1 px-4 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-50"
              style={{ background: colors.brand }}
              data-testid="template-save-btn"
            >
              <Save size={14} /> {busy ? "Saving…" : "Save template"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}


function Field({ label, children }) {
  return (
    <label className="block">
      <span
        className="text-[10px] font-bold uppercase tracking-wider mb-1 block"
        style={{ color: colors.muted }}
      >{label}</span>
      {children}
    </label>
  );
}


function InsertVariableButton({ variables, onInsert }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold"
        style={{
          backgroundColor: colors.surfaceSecondary,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
        data-testid="template-insert-var-btn"
      >
        <Copy size={12} /> Insert variable <ChevronDown size={12} />
      </button>
      {open ? (
        <div
          className="absolute z-10 mt-1 w-72 rounded-xl shadow-lg overflow-hidden"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
        >
          {variables.length === 0 ? (
            <div className="p-3 text-xs" style={{ color: colors.muted }}>
              Loading…
            </div>
          ) : (
            <ul className="max-h-64 overflow-y-auto">
              {variables.map((v) => (
                <li key={v.name}>
                  <button
                    type="button"
                    onClick={() => {
                      onInsert(v.name);
                      setOpen(false);
                    }}
                    className="w-full text-left px-3 py-2 hover:brightness-95"
                    style={{ backgroundColor: colors.surface }}
                    data-testid={`template-insert-var-${v.name}`}
                  >
                    <div className="text-xs font-mono font-bold"
                         style={{ color: colors.brand }}>
                      {`{{${v.name}}}`}
                    </div>
                    <div className="text-[11px]"
                         style={{ color: colors.muted }}>{v.description}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}


// ─── Client-side preview for unsaved templates ─────────────────────────────
const _TOKEN_RE = /\{\{\s*([A-Za-z_][\w.]*)\s*\}\}/g;
const _CTX = {
  customer: {
    first_name: "Sam",
    last_name: "Preview",
    full_name: "Sam Preview",
    email: "sam@example.com",
    phone: "+1 (555) 010-4444",
    balance_due: "$142.00",
  },
  next_service_date: "2026-08-05",
  next_service_type: "Pool Cleaning",
  tenant: {
    name: "Pool & Landscaping of Vistancia",
    phone: "+1 (623) 555-0100",
    google_review_url: "https://g.page/r/example/review",
  },
};
function _dig(obj, path) {
  let cur = obj;
  for (const seg of path.split(".")) {
    if (cur == null) return undefined;
    cur = cur[seg];
  }
  return cur;
}
function clientRender(body) {
  const missing = [];
  const rendered = String(body || "").replace(_TOKEN_RE, (_, path) => {
    const v = _dig(_CTX, path);
    if (v == null || v === "") { missing.push(path); return ""; }
    return String(v);
  });
  return { rendered, missing };
}
