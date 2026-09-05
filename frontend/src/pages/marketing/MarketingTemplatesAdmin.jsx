/**
 * Phase 9B · Feb 2026 — Marketing Templates admin.
 *
 * Two-route surface:
 *   * ``/marketing/templates``       — list (table)
 *   * ``/marketing/templates/:id``   — detail (3-column: meta / editor / preview)
 *
 * Preview + test-send are wired to the Phase 9A backend endpoints. When
 * the preview returns non-empty ``unresolved_tokens`` the red-chip
 * "Fix missing merge tags" banner renders above the preview; each chip
 * has an × that removes ALL literal ``{{TOKEN}}`` occurrences (case-
 * insensitive) from the body and re-previews.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Mail, MessageSquare, Plus, X as XIcon, ArrowLeft, Save, Trash2,
  RotateCcw, Send, Loader2, AlertCircle, CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { mustConfirm } from "@/components/ui/confirm-dialog";
import { TemplateEditor, computeSmsSegments } from "@/components/marketing/TemplateEditor";
import { MergeTagPalette } from "@/components/marketing/MergeTagPalette";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";

const CATEGORY_OPTIONS = [
  { v: "service_completed", l: "Service Completed" },
  { v: "invoice_sent", l: "Invoice Sent" },
  { v: "past_due", l: "Past Due" },
  { v: "welcome", l: "Welcome" },
  { v: "review_request", l: "Review Request" },
  { v: "general", l: "General" },
];


// ═══════════════════════════ List page ════════════════════════════════
export default function MarketingTemplatesListPage() {
  const nav = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState({ channel: "", category: "", active: "" });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter.channel) params.set("channel", filter.channel);
      if (filter.category) params.set("category", filter.category);
      if (filter.active !== "") params.set("active", filter.active);
      const res = await api.get(`/marketing/templates?${params}`);
      setRows(res.templates || []);
    } catch (e) {
      toast.error(e.message || "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  async function createNew() {
    try {
      const res = await api.post("/marketing/templates", {
        name: "New template",
        channel: "email",
        category: "general",
        subject: "New template",
        body: "<p>Start editing…</p>",
      });
      nav(`/marketing/templates/${res.id}`);
    } catch (e) {
      toast.error(e.message || "Create failed");
    }
  }

  const toggleActive = async (row, next) => {
    try {
      const updated = await api.patch(`/marketing/templates/${row.id}`, { active: next });
      setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, ...updated } : r)));
    } catch (e) {
      toast.error(e.message || "Toggle failed");
    }
  };

  return (
    <div className="min-h-screen bg-zinc-50" data-testid="templates-list-page">
      <div className="bg-white border-b border-zinc-200">
        <div className="max-w-7xl mx-auto px-6 py-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-900">
              Marketing templates
            </h1>
            <p className="text-sm text-zinc-500 mt-0.5">
              Reusable email + SMS templates with merge-tag rendering.
            </p>
          </div>
          <button
            onClick={createNew}
            data-testid="templates-new-btn"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800"
          >
            <Plus className="w-4 h-4" />
            New template
          </button>
        </div>
        <div className="max-w-7xl mx-auto px-6 pb-4 flex items-center gap-2">
          <select value={filter.channel}
                  onChange={(e) => setFilter({ ...filter, channel: e.target.value })}
                  data-testid="templates-filter-channel"
                  className="px-3 py-1.5 rounded-lg border border-zinc-200 text-sm bg-white">
            <option value="">All channels</option>
            <option value="email">Email</option>
            <option value="sms">SMS</option>
          </select>
          <select value={filter.category}
                  onChange={(e) => setFilter({ ...filter, category: e.target.value })}
                  data-testid="templates-filter-category"
                  className="px-3 py-1.5 rounded-lg border border-zinc-200 text-sm bg-white">
            <option value="">All categories</option>
            {CATEGORY_OPTIONS.map((c) => (
              <option key={c.v} value={c.v}>{c.l}</option>
            ))}
          </select>
          <select value={filter.active}
                  onChange={(e) => setFilter({ ...filter, active: e.target.value })}
                  data-testid="templates-filter-active"
                  className="px-3 py-1.5 rounded-lg border border-zinc-200 text-sm bg-white">
            <option value="">Any state</option>
            <option value="true">Active only</option>
            <option value="false">Inactive only</option>
          </select>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-6">
        <div className="bg-white rounded-xl border border-zinc-200 overflow-hidden">
          <div className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-200 bg-zinc-50 text-xs uppercase tracking-wide text-zinc-500">
            <div className="col-span-5">Name</div>
            <div className="col-span-2">Channel</div>
            <div className="col-span-2">Category</div>
            <div className="col-span-2">Last updated</div>
            <div className="col-span-1 text-right">Active</div>
          </div>
          {loading && (
            <div className="py-10 text-center text-sm text-zinc-500">Loading…</div>
          )}
          {!loading && rows.length === 0 && (
            <div className="py-10 text-center text-sm text-zinc-400"
                 data-testid="templates-list-empty">
              No templates. Click <em>New template</em> to create one.
            </div>
          )}
          {!loading && rows.map((r) => (
            <div key={r.id}
                 data-testid={`templates-row-${r.id}`}
                 className="grid grid-cols-12 gap-2 px-4 py-3 border-b border-zinc-100 items-center hover:bg-zinc-50/70 cursor-pointer"
                 onClick={() => nav(`/marketing/templates/${r.id}`)}>
              <div className="col-span-5 text-sm text-zinc-900 truncate">
                {r.name}
                {r.system && (
                  <span className="ml-2 inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700">
                    System
                  </span>
                )}
              </div>
              <div className="col-span-2 flex items-center gap-1.5 text-sm text-zinc-700">
                {r.channel === "email"
                  ? <Mail className="w-4 h-4" />
                  : <MessageSquare className="w-4 h-4" />}
                {r.channel}
              </div>
              <div className="col-span-2 text-sm text-zinc-500">{r.category}</div>
              <div className="col-span-2 text-sm text-zinc-500 truncate">
                {r.updated_at ? new Date(r.updated_at).toLocaleDateString() : "—"}
              </div>
              <div className="col-span-1 flex justify-end">
                <input
                  type="checkbox"
                  checked={!!r.active}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => toggleActive(r, e.target.checked)}
                  data-testid={`templates-row-active-${r.id}`}
                  className="w-4 h-4 rounded"
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}


// ═══════════════════════════ Detail page ══════════════════════════════
export function MarketingTemplateDetailPage() {
  const { id } = useParams();
  const nav = useNavigate();

  const [row, setRow] = useState(null);
  const [loading, setLoading] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [subjectMerge, setSubjectMerge] = useState(false);
  const subjRef = useRef(null);

  const [preview, setPreview] = useState({ subject: "", body: "", missing: [], unresolved: [] });
  const [testTo, setTestTo] = useState("");
  const [testSending, setTestSending] = useState(false);
  const [lastSent, setLastSent] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const t = await api.get(`/marketing/templates/${id}`);
      setRow(t);
      setDirty(false);
    } catch (e) {
      toast.error(e.message || "Failed to load template");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // Debounced preview.
  const debounceRef = useRef(null);
  useEffect(() => {
    if (!row) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.post(`/marketing/templates/${id}/preview`, {});
        setPreview({
          subject: res.subject_rendered || "",
          body: res.body_rendered || "",
          missing: res.missing_vars || [],
          unresolved: res.unresolved_tokens || [],
        });
      } catch (_e) {
        // Preview failures are non-fatal — just log to state.
        setPreview((p) => ({ ...p, missing: [], unresolved: [] }));
      }
    }, 500);
    return () => clearTimeout(debounceRef.current);
    // Re-preview whenever the persisted row changes (post-save).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row?.body, row?.subject, id]);

  const patchLocal = (patch) => {
    setRow((r) => ({ ...r, ...patch }));
    setDirty(true);
  };

  async function save() {
    if (!row) return;
    setSaving(true);
    try {
      // Send both body and body_html — backend accepts body_html as
      // alias; explicit body still wins when both are supplied.
      // Feb-2026 P0 fix — include ``channel`` in the payload. The
      // Item-2 ship added the Email/SMS toggle but the save handler
      // never forwarded the toggled value, so switching to SMS
      // appeared to work in the UI but the persisted row stayed on
      // ``email`` and the backend's ``_validate_shape`` still
      // required a subject → silent failure OR 422 on save.
      const payload = {
        name: row.name,
        category: row.category,
        channel: row.channel,
        subject: row.channel === "sms" ? null : row.subject,
        body: row.body,
        body_html: row.body,
        active: row.active,
      };
      const updated = await api.patch(`/marketing/templates/${id}`, payload);
      setRow(updated);
      setDirty(false);
      toast.success("Template saved");
    } catch (e) {
      toast.error(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function revert() {
    if (!row?.system) return;
    const ok = await mustConfirm({
      title: "Revert to factory defaults?",
      description: "Your customisations will be replaced with the current factory version.",
      tone: "danger", confirmText: "Revert",
    });
    if (!ok) return;
    try {
      const res = await api.post(`/marketing/templates/${id}/revert`, {});
      setRow(res);
      setDirty(false);
      toast.success("Reverted to defaults");
    } catch (e) {
      toast.error(e.message || "Revert failed");
    }
  }

  async function del() {
    if (!row || row.system) return;
    const ok = await mustConfirm({
      title: "Delete this template?",
      description: "The template will be removed from the marketing library. History rows already sent stay intact.",
      tone: "danger", confirmText: "Delete", requireTypeConfirm: true,
    });
    if (!ok) return;
    try {
      await api.del(`/marketing/templates/${id}`);
      toast.success("Deleted");
      nav("/marketing/templates");
    } catch (e) {
      toast.error(e.message || "Delete failed");
    }
  }

  async function testSend() {
    if (!row || !testTo.trim()) return;
    setTestSending(true);
    try {
      const res = await api.post(`/marketing/templates/${id}/test-send`, {
        to: testTo.trim(),
      });
      setLastSent(res);
      if (res.ok) toast.success("Test send OK");
      else toast.error(res.error_message || "Test send reported failure");
    } catch (e) {
      const msg = e.message || "Test send failed";
      if (/429|too many/i.test(msg)) {
        toast.error("Rate-limited — wait 60s and try again.");
      } else {
        toast.error(msg);
      }
    } finally {
      setTestSending(false);
    }
  }

  // Remove all case-insensitive occurrences of `{{TOKEN}}` from the body.
  function removeUnresolvedToken(token) {
    if (!row) return;
    const rgx = new RegExp("\\{\\{\\s*" + escapeRegex(token) + "\\s*\\}\\}", "gi");
    const nextBody = (row.body || "").replace(rgx, "");
    const nextSubject = (row.subject || "").replace(rgx, "");
    patchLocal({ body: nextBody, subject: nextSubject });
  }

  function insertIntoSubjectAtCursor(text) {
    const el = subjRef.current;
    if (!el) {
      patchLocal({ subject: (row.subject || "") + text });
      return;
    }
    const s = el.selectionStart, e = el.selectionEnd;
    const nextSubject = (row.subject || "").slice(0, s) + text + (row.subject || "").slice(e);
    patchLocal({ subject: nextSubject });
    setTimeout(() => {
      el.focus();
      const c = s + text.length;
      el.setSelectionRange(c, c);
    }, 0);
  }

  if (loading || !row) {
    return (
      <div className="min-h-screen bg-zinc-50 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-zinc-50 pb-8" data-testid="template-detail-page">
      {/* Top bar */}
      <div className="bg-white border-b border-zinc-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center gap-3">
          <Link to="/marketing/templates"
                data-testid="template-detail-back"
                className="p-2 rounded-lg hover:bg-zinc-100 text-zinc-600">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1 min-w-0">
            <div className="text-sm text-zinc-500 uppercase tracking-wide">
              {row.channel} · {row.category}
              {row.system && (
                <span className="ml-2 inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700">
                  System
                </span>
              )}
            </div>
            <input
              value={row.name || ""}
              onChange={(e) => patchLocal({ name: e.target.value })}
              data-testid="template-detail-name"
              className="w-full text-lg font-semibold text-zinc-900 bg-transparent focus:outline-none"
            />
          </div>
          {row.system && (
            <button
              onClick={revert}
              data-testid="template-detail-revert"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm border border-zinc-200 text-zinc-700 hover:bg-zinc-50"
            >
              <RotateCcw className="w-4 h-4" />
              Revert
            </button>
          )}
          {!row.system && (
            <button
              onClick={del}
              data-testid="template-detail-delete"
              // Phase K54.1 · Feb-2026 — promoted from outlined-red
              // (text-red-600 + border-red-200) to the solid
              // ``colors.destructive`` spec.  Matches the K54
              // shadcn ``Button variant="destructive"`` surface so
              // every Delete/Remove affordance across the app
              // reads identically.
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm text-white bg-[#DC2626] hover:bg-[#B91C1C] active:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#EF4444] focus-visible:ring-offset-1 disabled:opacity-55 shadow-sm"
            >
              <Trash2 className="w-4 h-4" />
              Delete
            </button>
          )}
          <button
            onClick={save}
            disabled={!dirty || saving}
            data-testid="template-detail-save"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="max-w-7xl mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left — metadata */}
        <div className="lg:col-span-3 space-y-4">
          <MetaField label="Category">
            <select
              value={row.category}
              onChange={(e) => patchLocal({ category: e.target.value })}
              data-testid="template-detail-category"
              className="w-full px-3 py-2 rounded-lg border border-zinc-200 text-sm"
            >
              {CATEGORY_OPTIONS.map((c) => (
                <option key={c.v} value={c.v}>{c.l}</option>
              ))}
            </select>
          </MetaField>
          <MetaField label="Channel">
            {/*
              Feb-2026 · Channel picker (was locked to Email). Backend
              already supports Email + SMS on ``ALLOWED_CHANNELS`` —
              ``PATCH /api/marketing/templates/{id}`` accepts a
              ``channel`` change and re-runs ``_validate_shape`` so
              SMS mode drops the Subject validation. Segmented pill
              matches the site's other Email/SMS toggles.
            */}
            <div className="inline-flex rounded-lg border border-zinc-200 overflow-hidden text-sm">
              {[
                { v: "email", l: "Email", Icon: Mail,
                   testid: "id-template-channel-email" },
                { v: "sms", l: "SMS", Icon: MessageSquare,
                   testid: "id-template-channel-sms" },
              ].map(({ v, l, Icon, testid }) => {
                const active = row.channel === v;
                return (
                  <button
                    key={v}
                    type="button"
                    onClick={() => {
                      if (row.channel === v) return;
                      // Switching to SMS drops the Subject; switching
                      // to Email seeds one if the row lost it during
                      // a prior SMS session.
                      const patch = { channel: v };
                      if (v === "sms") patch.subject = null;
                      if (v === "email" && !row.subject) {
                        patch.subject = row.name || "Subject";
                      }
                      patchLocal(patch);
                    }}
                    data-testid={testid}
                    className={
                      "flex items-center gap-1.5 px-3 py-2 " +
                      (active
                        ? "bg-zinc-900 text-white"
                        : "bg-white text-zinc-600 hover:bg-zinc-50")
                    }
                  >
                    <Icon className="w-4 h-4" /> {l}
                  </button>
                );
              })}
            </div>
          </MetaField>
          <MetaField label="Active">
            <label className="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={!!row.active}
                onChange={(e) => patchLocal({ active: e.target.checked })}
                data-testid="template-detail-active"
                className="w-4 h-4 rounded"
              />
              <span className="text-sm text-zinc-700">Enabled</span>
            </label>
          </MetaField>
          {row.updated_at && (
            <div className="text-xs text-zinc-400">
              Last updated {new Date(row.updated_at).toLocaleString()}
            </div>
          )}
        </div>

        {/* Middle — editor */}
        <div className="lg:col-span-5 space-y-3">
          {row.channel === "email" && (
            <div>
              <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
                Subject
              </div>
              <div className="flex items-center gap-2">
                <input
                  ref={subjRef}
                  value={row.subject || ""}
                  onChange={(e) => patchLocal({ subject: e.target.value })}
                  data-testid="template-detail-subject"
                  className="flex-1 px-3 py-2 rounded-lg border border-zinc-200 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-300"
                  placeholder="Subject — merge tags allowed"
                />
                <button
                  type="button"
                  onClick={() => setSubjectMerge(true)}
                  data-testid="template-detail-subject-merge"
                  className="inline-flex items-center gap-1 px-2 py-2 rounded-lg text-xs font-medium text-zinc-700 bg-white border border-zinc-200 hover:bg-zinc-50"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Tag
                </button>
              </div>
            </div>
          )}

          <TemplateEditor
            mode={row.channel === "sms" ? "sms" : "email"}
            value={row.body || ""}
            onChange={(v) => patchLocal({ body: v })}
          />
        </div>

        {/* Right — preview + test-send */}
        <div className="lg:col-span-4 space-y-4">
          {preview.unresolved && preview.unresolved.length > 0 && (
            <Alert variant="destructive" data-testid="unresolved-tokens-banner">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Fix missing merge tags</AlertTitle>
              <AlertDescription>
                <div className="text-sm mb-2">
                  These tags aren't valid and won't be substituted:
                </div>
                <div className="flex flex-wrap gap-1">
                  {preview.unresolved.map((tok) => (
                    <button
                      key={tok}
                      onClick={() => removeUnresolvedToken(tok)}
                      title="Not a valid merge tag — click × to remove all occurrences from this template."
                      data-testid={`unresolved-chip-${tok}`}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700 hover:bg-red-200"
                    >
                      {`{{${tok}}}`}
                      <XIcon className="w-3 h-3" />
                    </button>
                  ))}
                </div>
              </AlertDescription>
            </Alert>
          )}

          <div className="rounded-xl border border-zinc-200 bg-white overflow-hidden"
               data-testid="template-preview-panel">
            <div className="px-4 py-2 border-b border-zinc-100 text-xs uppercase tracking-wide text-zinc-500">
              Preview
            </div>
            {row.channel === "email" ? (
              <div className="p-4 space-y-3">
                <div>
                  <div className="text-xs text-zinc-400 uppercase mb-0.5">Subject</div>
                  <div className="font-medium text-zinc-900" data-testid="preview-subject">
                    {preview.subject || <span className="text-zinc-400">(no subject)</span>}
                  </div>
                </div>
                <div className="rounded-lg border border-zinc-100 bg-white overflow-hidden">
                  <iframe
                    title="email-preview"
                    srcDoc={`<html><head><style>body{font-family:Inter,system-ui,Arial;color:#111;padding:12px;font-size:14px;} img{max-width:100%;}</style></head><body>${preview.body || ""}</body></html>`}
                    data-testid="preview-body-iframe"
                    className="w-full min-h-[240px] border-0"
                  />
                </div>
              </div>
            ) : (
              <div className="p-6">
                <div className="mx-auto max-w-xs bg-zinc-100 rounded-3xl p-3">
                  <div className="bg-white rounded-2xl px-4 py-3 shadow-sm text-sm text-zinc-800"
                       data-testid="preview-sms-bubble">
                    {preview.body || <span className="text-zinc-400">(no message)</span>}
                  </div>
                  <div className="mt-2 text-[10px] text-zinc-500 text-center">
                    {computeSmsSegments(preview.body || "").segments} segment(s)
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-zinc-200 bg-white p-4">
            <div className="text-xs uppercase tracking-wide text-zinc-500 mb-2">
              Test send
            </div>
            <div className="flex items-center gap-2">
              <input
                type={row.channel === "email" ? "email" : "tel"}
                value={testTo}
                onChange={(e) => setTestTo(e.target.value)}
                data-testid="template-testsend-to"
                placeholder={row.channel === "email" ? "you@example.com" : "+15551234567"}
                className="flex-1 px-3 py-2 rounded-lg border border-zinc-200 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-300"
              />
              <button
                onClick={testSend}
                disabled={testSending || !testTo.trim()}
                data-testid="template-testsend-btn"
                className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-zinc-900 text-white text-sm hover:bg-zinc-800 disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
                {testSending ? "Sending…" : "Send"}
              </button>
            </div>
            {lastSent && (
              <div className="mt-2 text-xs flex items-center gap-1.5"
                   data-testid="template-testsend-result">
                {lastSent.ok ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-green-600" />
                ) : (
                  <AlertCircle className="w-3.5 h-3.5 text-red-600" />
                )}
                <span className="text-zinc-600">
                  {lastSent.provider || "—"} · {lastSent.provider_status || "—"}
                  {lastSent.provider_response_id ? ` · ${lastSent.provider_response_id}` : ""}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      <MergeTagPalette
        open={subjectMerge}
        onOpenChange={setSubjectMerge}
        onInsert={(token) => insertIntoSubjectAtCursor(token)}
      />
    </div>
  );
}


function MetaField({ label, children }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-zinc-500 mb-1">
        {label}
      </div>
      {children}
    </div>
  );
}

function escapeRegex(s) {
  return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
