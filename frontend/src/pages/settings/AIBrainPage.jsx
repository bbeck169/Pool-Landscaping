// Feb-2026 · Item 4 — Admin AI Brain settings page.
//
// Lists every ``ai_knowledge_base`` entry (company profile, FAQs,
// policies, custom) with a Markdown editor on the right. Admin-only.
// Uses ConfirmDeleteDialog for soft-deletion so nothing goes away
// with a stray click.
import React from "react";
import { toast } from "sonner";
import { Plus, Save, Trash2, Sparkles, TrendingUp, PlusCircle, Bell,
          Image as ImageIcon, MessageSquare, Gauge, Star, RefreshCw } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import ConfirmDeleteDialog from "@/components/common/ConfirmDeleteDialog";

const KIND_OPTIONS = [
  { key: "company_profile", label: "Company profile" },
  { key: "faq",             label: "FAQ" },
  { key: "policy",          label: "Policy" },
  { key: "custom",          label: "Custom" },
];

export default function AIBrainPage() {
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [activeId, setActiveId] = React.useState(null);
  const [draft, setDraft] = React.useState(null);
  const [saving, setSaving] = React.useState(false);
  const [deleteId, setDeleteId] = React.useState(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/ai/knowledge");
      setItems(res?.items || []);
      if (!activeId && (res?.items || []).length) {
        setActiveId(res.items[0].id);
        setDraft(res.items[0]);
      }
    } catch (e) {
      toast.error(`Failed to load AI brain: ${e.message || e}`);
    } finally { setLoading(false); }
  }, [activeId]);
  React.useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps -- Phase 41.3 mount-only + explicit param deps

  const selectItem = (row) => { setActiveId(row.id); setDraft(row); };

  const createNew = async () => {
    try {
      const row = await api.post("/ai/knowledge", {
        kind: "custom", title: "New entry",
        content_md: "# New entry\n\nWrite about your business here.",
        is_active: true, tags: [],
      });
      await load(); setActiveId(row.id); setDraft(row);
      toast.success("Entry created");
    } catch (e) {
      toast.error(`Create failed: ${e.message || e}`);
    }
  };

  const save = async () => {
    if (!draft?.id) return;
    setSaving(true);
    try {
      const patch = {
        kind: draft.kind, title: draft.title,
        content_md: draft.content_md, is_active: draft.is_active,
        tags: draft.tags || [],
      };
      await api.patch(`/ai/knowledge/${draft.id}`, patch);
      toast.success("Saved");
      await load();
    } catch (e) {
      toast.error(`Save failed: ${e.message || e}`);
    } finally { setSaving(false); }
  };

  const confirmDelete = async () => {
    if (!deleteId) return;
    try {
      await api.delete(`/ai/knowledge/${deleteId}`);
      toast.success("Deleted");
      setActiveId(null); setDraft(null); setDeleteId(null);
      await load();
    } catch (e) {
      toast.error(`Delete failed: ${e.message || e}`);
      setDeleteId(null);
    }
  };

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-4"
         data-testid="ai-brain-page">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight"
              style={{ color: colors.onSurface }}
              data-testid="ai-brain-title">
            <Sparkles size={20} className="inline mr-2 -mt-0.5"
                       style={{ color: colors.brand }} />
            AI Brain
          </h1>
          <p className="text-sm" style={{ color: colors.muted }}>
            Everything the AI Copilot + marketing suggestions know about your company.
          </p>
        </div>
        <button
          type="button"
          onClick={createNew}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold hover:brightness-95"
          style={{ backgroundColor: colors.brand, color: "#fff" }}
          data-testid="ai-brain-new-btn"
        ><Plus size={14} /> New entry</button>
      </div>

      <WeeklyAIEmployeesSummary />

      <TopQuestionsWidget onSaveToKnowledge={async (q) => {
        try {
          const row = await api.post("/ai/knowledge", {
            kind: "faq",
            title: q.prompt.length > 80 ? `${q.prompt.slice(0, 77)}…` : q.prompt,
            content_md: `**Q:** ${q.prompt}\n\n**A:** ${q.last_response || ""}`.trim(),
            is_active: true, tags: ["from_copilot"],
          });
          await load();
          setActiveId(row.id); setDraft(row);
          toast.success("Added to knowledge base — review before publishing");
        } catch (e) {
          toast.error(`Save failed: ${e.message || e}`);
        }
      }} />

      <DailyDigestToggle />

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <div className="lg:col-span-1 rounded-xl p-2 max-h-[70vh] overflow-y-auto"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="ai-brain-list">
          {loading ? (
            <div className="text-xs p-2" style={{ color: colors.muted }}>Loading…</div>
          ) : items.length === 0 ? (
            <div className="text-xs p-2" style={{ color: colors.muted }}>
              No knowledge yet. Click "New entry".
            </div>
          ) : items.map((it) => (
            <button
              key={it.id}
              type="button"
              onClick={() => selectItem(it)}
              className="w-full text-left rounded-md px-2 py-2 mb-1 hover:brightness-95"
              style={{
                backgroundColor: activeId === it.id ? colors.brandTertiary : "transparent",
                border: `1px solid ${activeId === it.id ? colors.brand : "transparent"}`,
              }}
              data-testid={`ai-brain-item-${it.id}`}
            >
              <div className="text-xs font-semibold truncate"
                   style={{ color: colors.onSurface }}>{it.title}</div>
              <div className="text-[11px]" style={{ color: colors.muted }}>
                {it.kind} · {it.is_active ? "active" : "inactive"}
              </div>
            </button>
          ))}
        </div>

        <div className="lg:col-span-3 rounded-xl p-4 space-y-3"
             style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
             data-testid="ai-brain-editor">
          {draft ? (
            <>
              <div className="grid gap-2 md:grid-cols-2">
                <div>
                  <div className="text-[11px] uppercase tracking-wide font-semibold mb-0.5"
                       style={{ color: colors.muted }}>Title</div>
                  <input
                    type="text"
                    value={draft.title || ""}
                    onChange={(e) => setDraft({ ...draft, title: e.target.value })}
                    className="w-full rounded px-2 py-1.5 text-sm focus:outline-none"
                    style={{
                      backgroundColor: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid="ai-brain-title-input"
                  />
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wide font-semibold mb-0.5"
                       style={{ color: colors.muted }}>Kind</div>
                  <select
                    value={draft.kind || "custom"}
                    onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
                    className="w-full rounded px-2 py-1.5 text-sm focus:outline-none"
                    style={{
                      backgroundColor: colors.surfaceSecondary,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid="ai-brain-kind-select"
                  >
                    {KIND_OPTIONS.map((o) => (
                      <option key={o.key} value={o.key}>{o.label}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wide font-semibold mb-0.5"
                     style={{ color: colors.muted }}>Content (Markdown)</div>
                <textarea
                  value={draft.content_md || ""}
                  onChange={(e) => setDraft({ ...draft, content_md: e.target.value })}
                  rows={16}
                  className="w-full rounded px-3 py-2 text-sm font-mono focus:outline-none"
                  style={{
                    backgroundColor: colors.surfaceSecondary,
                    color: colors.onSurface,
                    border: `1px solid ${colors.border}`,
                  }}
                  data-testid="ai-brain-content-input"
                />
              </div>
              <label className="flex items-center gap-2 text-sm"
                     style={{ color: colors.onSurface }}>
                <input
                  type="checkbox"
                  checked={!!draft.is_active}
                  onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
                  data-testid="ai-brain-active-checkbox"
                /> Active (included in AI system prompt)
              </label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={save}
                  disabled={saving}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-semibold text-white hover:brightness-95 disabled:opacity-50"
                  style={{ backgroundColor: colors.brand }}
                  data-testid="ai-brain-save-btn"
                >
                  <Save size={13} /> {saving ? "Saving…" : "Save"}
                </button>
                <button
                  type="button"
                  onClick={() => setDeleteId(draft.id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-semibold hover:brightness-95"
                  style={{
                    backgroundColor: "#FEF2F2", color: "#991B1B",
                    border: "1px solid #FECACA",
                  }}
                  data-testid="ai-brain-delete-btn"
                >
                  <Trash2 size={13} /> Delete
                </button>
              </div>
            </>
          ) : (
            <div className="text-sm" style={{ color: colors.muted }}>
              Pick an entry on the left or click "New entry" above.
            </div>
          )}
        </div>
      </div>

      <ConfirmDeleteDialog
        open={!!deleteId}
        title="Delete knowledge entry?"
        body="This entry will be removed from the AI system prompt. This action can be recovered by an engineer if needed within 30 days."
        requireTypeConfirm={true}
        typeConfirmString="DELETE"
        onCancel={() => setDeleteId(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

// Feb-2026 · Item 4 bonus — "Top admin questions" widget.
// Reads /api/ai/copilot/top-questions?days=30 and lets admins
// promote a common question straight into the knowledge base.
function TopQuestionsWidget({ onSaveToKnowledge }) {
  const [items, setItems] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    api.get("/ai/copilot/top-questions?days=30&limit=10")
      .then((r) => { if (alive) setItems(r?.items || []); })
      .catch((e) => { if (alive) setError(e.message || "Failed to load"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  return (
    <div className="rounded-xl p-4 space-y-2"
         style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
         data-testid="ai-brain-top-questions">
      <div className="flex items-center gap-2">
        <TrendingUp size={14} style={{ color: colors.brand }} />
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Top admin questions (last 30 days)
        </div>
      </div>
      {loading ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="ai-brain-top-questions-loading">Loading…</div>
      ) : error ? (
        <div className="text-xs" style={{ color: "#B91C1C" }}
             data-testid="ai-brain-top-questions-error">{error}</div>
      ) : items.length === 0 ? (
        <div className="text-xs" style={{ color: colors.muted }}
             data-testid="ai-brain-top-questions-empty">
          No copilot activity yet. Try asking questions in the AI Copilot.
        </div>
      ) : (
        <div className="space-y-1"
             data-testid="ai-brain-top-questions-list">
          {items.map((q, idx) => (
            <div key={idx}
                 className="flex items-start gap-2 rounded-md p-2"
                 style={{ backgroundColor: colors.surfaceSecondary,
                            border: `1px solid ${colors.border}` }}
                 data-testid={`ai-brain-top-question-${idx}`}>
              <div className="flex-shrink-0 text-[10px] font-bold uppercase rounded px-1.5 py-0.5"
                   style={{ backgroundColor: colors.brandTertiary,
                              color: colors.brand }}>
                ×{q.count}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold truncate"
                     style={{ color: colors.onSurface }}>
                  {q.prompt}
                </div>
                <div className="text-[10px]" style={{ color: colors.muted }}>
                  Last asked {(q.last_asked_at || "").slice(0, 10)}
                </div>
              </div>
              <button
                type="button"
                onClick={() => onSaveToKnowledge(q)}
                className="flex-shrink-0 flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-md hover:brightness-95"
                style={{ backgroundColor: colors.brand, color: "#fff" }}
                data-testid={`ai-brain-top-question-save-${idx}`}
              >
                <PlusCircle size={11} /> Add to KB
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Feb-2026 · smart enhancement — Weekly AI Employees summary tile.
// Full-width gradient hero showing what the AI has done in the
// last 7 days: drafts generated, reviews answered, latest SEO
// score, weekly star delta.
function WeeklyAIEmployeesSummary() {
  const [data, setData] = React.useState(null);
  const [card, setCard] = React.useState(null);
  const [refreshing, setRefreshing] = React.useState(false);

  const load = React.useCallback(async (bust = false) => {
    setRefreshing(true);
    try {
      const [r, c] = await Promise.all([
        api.get(`/ai/employees/weekly-summary${bust ? "?refresh=1" : ""}`),
        card ? Promise.resolve(card) : api.get("/tenants/business-card").catch(() => null),
      ]);
      setData(r);
      if (!card && c) setCard(c);
    } catch (_e) { /* graceful */ }
    finally { setRefreshing(false); }
  }, [card]);
  React.useEffect(() => { load(false); }, [load]);

  if (!data) return null;

  const from = card?.gradient_from || "#0EA5E9";
  const to = card?.gradient_to || "#16A34A";
  const grad = `linear-gradient(135deg, ${from} 0%, ${to} 100%)`;
  const rel = (iso) => {
    if (!iso) return "";
    const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60)  return `${s}s ago`;
    if (s < 3600) return `${Math.round(s / 60)}m ago`;
    return `${Math.round(s / 3600)}h ago`;
  };
  const showSeo   = data.seo_score_latest != null;
  const showDelta = data.star_delta != null;
  const deltaPositive = (data.star_delta || 0) >= 0;

  const Pill = ({ icon: Icon, label, testid }) => (
    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-white text-xs font-semibold"
         style={{ backgroundColor: "rgba(255,255,255,0.22)",
                    border: "1px solid rgba(255,255,255,0.32)" }}
         data-testid={testid}>
      <Icon size={13} /> {label}
    </div>
  );

  return (
    <div className="rounded-2xl p-4 sm:p-5 relative overflow-hidden"
         style={{ background: grad, color: "rgba(255,255,255,0.95)" }}
         data-testid="ai-employees-weekly-summary">
      <div className="text-sm font-semibold mb-2">
        This week your AI employees did:
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Pill icon={ImageIcon}
               label={`${data.drafts_generated} draft${data.drafts_generated === 1 ? "" : "s"} generated`}
               testid="ai-week-drafts" />
        <Pill icon={MessageSquare}
               label={`${data.reviews_answered} review${data.reviews_answered === 1 ? "" : "s"} answered`}
               testid="ai-week-reviews" />
        {showSeo ? (
          <Pill icon={Gauge}
                 label={`${data.seo_score_latest}/100 SEO score`}
                 testid="ai-week-seo" />
        ) : null}
        {showDelta ? (
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
               style={{ backgroundColor: deltaPositive ? "#DCFCE7" : "#FEE2E2",
                          color: deltaPositive ? "#166534" : "#991B1B" }}
               data-testid="ai-week-star-delta">
            <Star size={13} fill={deltaPositive ? "#16A34A" : "#B91C1C"} />
            {deltaPositive ? "+" : ""}{data.star_delta}★ weekly delta
          </div>
        ) : null}
      </div>
      <div className="flex items-center gap-3 mt-3 text-[11px] opacity-90">
        <span data-testid="ai-week-updated">Updated {rel(data.generated_at)}.</span>
        <button
          type="button"
          onClick={() => load(true)}
          disabled={refreshing}
          className="underline flex items-center gap-1"
          data-testid="ai-week-refresh"
        >
          <RefreshCw size={10} className={refreshing ? "animate-spin" : ""} /> Refresh
        </button>
      </div>
    </div>
  );
}

// Feb-2026 · Phase 20 P2 — Admin toggle for the daily review digest.
function DailyDigestToggle() {
  const [enabled, setEnabled] = React.useState(null);
  const [saving, setSaving] = React.useState(false);
  React.useEffect(() => {
    api.get("/ai/settings/daily-review-digest")
      .then((r) => setEnabled(!!r?.enabled))
      .catch(() => setEnabled(true));
  }, []);
  const toggle = async () => {
    if (enabled === null) return;
    setSaving(true);
    try {
      const next = !enabled;
      await api.patch("/ai/settings/daily-review-digest", { enabled: next });
      setEnabled(next);
      toast.success(next ? "Daily review digest enabled" : "Digest disabled");
    } catch (e) {
      toast.error(`Toggle failed: ${e.message || e}`);
    } finally { setSaving(false); }
  };
  return (
    <div className="rounded-xl p-3 flex items-center gap-3"
         style={{ backgroundColor: colors.surface,
                    border: `1px solid ${colors.border}` }}
         data-testid="ai-brain-digest-toggle">
      <Bell size={14} style={{ color: colors.brand }} />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          Daily review digest email
        </div>
        <div className="text-xs" style={{ color: colors.muted }}>
          Sends an 8am (Phoenix) summary of yesterday's reviews with an AI-suggested reply per row.
        </div>
      </div>
      <button
        type="button"
        onClick={toggle}
        disabled={saving || enabled === null}
        className="text-xs font-semibold px-3 py-1.5 rounded-md hover:brightness-95 disabled:opacity-60"
        style={{ backgroundColor: enabled ? colors.brand : colors.surfaceSecondary,
                   color: enabled ? "#fff" : colors.onSurface,
                   border: `1px solid ${colors.border}` }}
        data-testid="ai-brain-digest-toggle-btn"
      >
        {enabled === null ? "…" : enabled ? "On" : "Off"}
      </button>
    </div>
  );
}
