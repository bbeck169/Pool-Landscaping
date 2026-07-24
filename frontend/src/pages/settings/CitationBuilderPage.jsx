import React from "react";
import { toast } from "sonner";
import {
  RefreshCw, Search, ExternalLink, Pencil, Save, X, AlertTriangle,
  CheckCircle2, MapPin, Globe, Users, Share2, Award, Star,
  TrendingUp, TrendingDown, ArrowRight, Mic, Copy, Info, ChevronDown,
} from "lucide-react";
import { api } from "@/api";
import { colors, brandGradientCss } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";

/**
 * Feb-2026 · Phase 22 — Citation Builder.
 *
 * Native BrightLocal-style tracker for the tenant's presence across
 * ~50 directories.  Backed by /api/citations/* endpoints.  Admin-only
 * per the route guard in ``App.js``.
 */

const CATEGORY_META = {
  search:   { label: "Search",   Icon: Search,   tint: "#0284C7" },
  maps:     { label: "Maps",     Icon: MapPin,   tint: "#16A34A" },
  social:   { label: "Social",   Icon: Share2,   tint: "#7C3AED" },
  local:    { label: "Local",    Icon: Users,    tint: "#EA580C" },
  industry: { label: "Industry", Icon: Award,    tint: "#DB2777" },
  reviews:  { label: "Reviews",  Icon: Star,     tint: "#CA8A04" },
  other:    { label: "Other",    Icon: Globe,    tint: "#64748B" },
};

const STATUS_META = {
  not_started:  { label: "Not started",  bg: "#F1F5F9", fg: "#475569" },
  in_progress:  { label: "In progress",  bg: "#DBEAFE", fg: "#1E40AF" },
  submitted:    { label: "Submitted",    bg: "#E0E7FF", fg: "#4338CA" },
  live:         { label: "Live",         bg: "#DCFCE7", fg: "#166534" },
  needs_update: { label: "Needs update", bg: "#FEE2E2", fg: "#991B1B" },
  rejected:     { label: "Rejected",     bg: "#FEF3C7", fg: "#92400E" },
  "n/a":        { label: "N/A",          bg: "#F1F5F9", fg: "#64748B" },
};

const CATEGORY_ORDER = ["all", "search", "maps", "social", "local", "industry", "reviews"];
const STATUS_ORDER = ["all", "not_started", "in_progress", "submitted", "live", "needs_update", "rejected"];


function relativeAge(iso) {
  if (!iso) return "Never";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "Never";
  const diffMs = Date.now() - t;
  const day = 24 * 3600 * 1000;
  const days = Math.floor(diffMs / day);
  if (days < 1) return "Today";
  if (days === 1) return "1 day ago";
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  if (months === 1) return "1 month ago";
  return `${months} months ago`;
}


export default function CitationBuilderPage() {
  const [rows, setRows] = React.useState(null); // null=loading, [] loaded
  const [summary, setSummary] = React.useState(null);
  const [voiceScore, setVoiceScore] = React.useState(null);
  const [category, setCategory] = React.useState("all");
  const [status, setStatus] = React.useState("all");
  const [search, setSearch] = React.useState("");
  const [driftOnly, setDriftOnly] = React.useState(false);
  const [problemsOnly, setProblemsOnly] = React.useState(false); // drift + duplicates
  const [highWeightNotStartedOnly, setHwNotStartedOnly] = React.useState(false);
  const [sortBy, setSortBy] = React.useState("weight"); // weight | verified | impressions
  const [selected, setSelected] = React.useState(() => new Set());
  const [editingDirId, setEditingDirId] = React.useState(null);
  const [bulkBusy, setBulkBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [list, sum, voice] = await Promise.all([
        api.get("/citations/tenant"),
        api.get("/citations/tenant/summary"),
        api.get("/citations/tenant/voice-score"),
      ]);
      setRows(Array.isArray(list?.citations) ? list.citations : []);
      setSummary(sum || null);
      setVoiceScore(voice || null);
    } catch (e) {
      toast.error(e?.message || "Failed to load citations");
      setRows([]);
    }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const filtered = React.useMemo(() => {
    if (!rows) return [];
    const q = search.trim().toLowerCase();
    const out = rows.filter((r) => {
      const d = r.directory || {};
      if (category !== "all" && d.category !== category) return false;
      if (status !== "all" && (r.status || "not_started") !== status) return false;
      const hasDrift = !!r.nap_drift_detected;
      const openDupes = (r.duplicate_urls || []).filter(
        (u) => !["suppressed", "confirmed"].includes((u.status || "").toLowerCase())
      );
      if (driftOnly && !hasDrift) return false;
      if (problemsOnly && !hasDrift && openDupes.length === 0) return false;
      if (highWeightNotStartedOnly &&
          !((d.weight || 0) >= 8 && (r.status || "not_started") === "not_started")) {
        return false;
      }
      if (q && !(d.name || "").toLowerCase().includes(q)) return false;
      return true;
    });
    if (sortBy === "verified") {
      out.sort((a, b) => (a.last_verified_at || "").localeCompare(b.last_verified_at || ""));
    } else if (sortBy === "impressions") {
      out.sort((a, b) => (b.impressions_last_30d || 0) - (a.impressions_last_30d || 0));
    } else {
      out.sort((a, b) => (b.directory?.weight || 0) - (a.directory?.weight || 0));
    }
    return out;
  }, [rows, category, status, search, driftOnly, problemsOnly,
       highWeightNotStartedOnly, sortBy]);

  const editing = React.useMemo(() => {
    if (!editingDirId) return null;
    return (rows || []).find((r) => r.directory_id === editingDirId) || null;
  }, [editingDirId, rows]);

  const toggleSelect = (id) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const runBulkVerify = async () => {
    if (selected.size === 0) {
      toast.message("Select at least one directory to verify.");
      return;
    }
    setBulkBusy(true);
    try {
      const ids = Array.from(selected);
      const res = await api.post("/citations/tenant/bulk-mark-verified", {
        directory_ids: ids,
      });
      toast.success(`${res?.verified || 0} directories verified`);
      setSelected(new Set());
      load();
    } catch (e) {
      toast.error(e?.message || "Bulk verify failed");
    } finally {
      setBulkBusy(false);
    }
  };

  const saveEdit = async (directoryId, patch) => {
    try {
      await api.patch(`/citations/tenant/${directoryId}`, patch);
      toast.success("Saved");
      setEditingDirId(null);
      load();
    } catch (e) {
      toast.error(e?.message || "Save failed");
      throw e;
    }
  };

  const verifyOne = async (directoryId) => {
    try {
      await api.post(`/citations/tenant/${directoryId}/mark-verified`);
      toast.success("Marked verified");
      setEditingDirId(null);
      load();
    } catch (e) {
      toast.error(e?.message || "Verify failed");
    }
  };

  return (
    <SafeScrollContainer
      className="p-6 max-w-6xl mx-auto"
      data-testid="citation-builder-page"
    >
      <Header />
      <KpiStrip summary={summary} />

      <FilterBar
        category={category} onCategory={setCategory}
        status={status} onStatus={setStatus}
        search={search} onSearch={setSearch}
        driftOnly={driftOnly} onDriftOnly={setDriftOnly}
        selectedCount={selected.size}
        onBulkVerify={runBulkVerify}
        onRefresh={load}
        bulkBusy={bulkBusy}
      />

      {rows === null ? (
        <div
          className="h-64 rounded-2xl animate-pulse"
          style={{ backgroundColor: colors.surfaceSecondary }}
          data-testid="citation-builder-loading"
        />
      ) : filtered.length === 0 && rows.length === 0 ? (
        <EmptyState />
      ) : filtered.length === 0 ? (
        <div
          className="rounded-2xl p-8 text-center"
          style={{
            backgroundColor: colors.surface,
            border: `1px dashed ${colors.border}`,
            color: colors.muted,
          }}
          data-testid="citation-builder-no-matches"
        >
          No directories match your filters.
        </div>
      ) : (
        <ul
          className="space-y-2"
          data-testid="citation-builder-list"
        >
          {filtered.map((row) => (
            <CitationRow
              key={row.directory_id}
              row={row}
              selected={selected.has(row.directory_id)}
              onToggle={() => toggleSelect(row.directory_id)}
              onEdit={() => setEditingDirId(row.directory_id)}
            />
          ))}
        </ul>
      )}

      {editing ? (
        <EditSheet
          key={editing.directory_id}
          row={editing}
          onClose={() => setEditingDirId(null)}
          onSave={(patch) => saveEdit(editing.directory_id, patch)}
          onVerify={() => verifyOne(editing.directory_id)}
        />
      ) : null}
    </SafeScrollContainer>
  );
}


function Header() {
  return (
    <div className="mb-4">
      <h1
        className="text-2xl font-bold mb-1"
        style={{ color: colors.onSurface }}
        data-testid="citation-builder-title"
      >
        Citation Builder
      </h1>
      <p className="text-sm" style={{ color: colors.muted }}>
        Track your business listings across 50+ directories.
      </p>
    </div>
  );
}


function KpiStrip({ summary }) {
  const score = summary?.weighted_completeness_score ?? 0;
  const live = summary?.live_count ?? 0;
  const drift = summary?.nap_drift_count ?? 0;
  const oldest = summary?.oldest_last_verified_at;

  return (
    <div
      className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4"
      data-testid="citation-builder-kpis"
    >
      <ScoreDonut score={score} />
      <KpiTile
        testid="citation-kpi-live"
        label="Live listings"
        value={live}
        Icon={CheckCircle2}
        tint="#16A34A"
      />
      <KpiTile
        testid="citation-kpi-drift"
        label="NAP drift"
        value={drift}
        Icon={AlertTriangle}
        tint={drift > 0 ? "#DC2626" : "#64748B"}
      />
      <KpiTile
        testid="citation-kpi-oldest"
        label="Oldest verification"
        value={relativeAge(oldest)}
        Icon={RefreshCw}
        tint="#0284C7"
      />
    </div>
  );
}


function ScoreDonut({ score }) {
  const pct = Math.max(0, Math.min(100, Number(score) || 0));
  const R = 30;
  const C = 2 * Math.PI * R;
  const offset = C - (pct / 100) * C;
  return (
    <div
      className="rounded-xl p-4 flex items-center gap-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="citation-kpi-score"
    >
      <svg width="80" height="80" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r={R} stroke="#E2E8F0" strokeWidth="10" fill="none" />
        <circle
          cx="40" cy="40" r={R}
          stroke="#0284C7" strokeWidth="10" fill="none"
          strokeDasharray={C}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 40 40)"
        />
        <text
          x="40" y="45"
          textAnchor="middle"
          fontSize="16"
          fontWeight="700"
          fill={colors.onSurface}
          data-testid="citation-kpi-score-value"
        >
          {pct.toFixed(0)}
        </text>
      </svg>
      <div>
        <div
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: colors.muted }}
        >
          Completeness
        </div>
        <div
          className="text-lg font-bold"
          style={{ color: colors.onSurface }}
        >
          {pct.toFixed(0)} / 100
        </div>
      </div>
    </div>
  );
}


function KpiTile({ testid, label, value, Icon, tint }) {
  return (
    <div
      className="rounded-xl p-4"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testid}
    >
      <div className="flex items-center gap-2 mb-1">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ backgroundColor: `${tint}22`, color: tint }}
          aria-hidden="true"
        >
          <Icon size={16} />
        </div>
        <div
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: colors.muted }}
        >
          {label}
        </div>
      </div>
      <div
        className="text-2xl font-bold"
        style={{ color: colors.onSurface }}
      >
        {value}
      </div>
    </div>
  );
}


function FilterBar({
  category, onCategory, status, onStatus, search, onSearch,
  driftOnly, onDriftOnly, selectedCount, onBulkVerify, onRefresh, bulkBusy,
}) {
  return (
    <div
      className="rounded-xl p-3 mb-3"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid="citation-filter-bar"
    >
      <div className="flex flex-wrap gap-2 items-center mb-2">
        {CATEGORY_ORDER.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onCategory(c)}
            className="px-3 py-1 rounded-full text-xs font-semibold transition"
            style={{
              backgroundColor: category === c ? colors.brand : colors.surfaceSecondary,
              color: category === c ? "#fff" : colors.onSurface,
              border: `1px solid ${category === c ? colors.brand : colors.border}`,
            }}
            data-testid={`citation-filter-cat-${c}`}
          >
            {c === "all" ? "All" : (CATEGORY_META[c]?.label || c)}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <select
          value={status}
          onChange={(e) => onStatus(e.target.value)}
          className="px-2 py-1.5 rounded-lg border text-sm"
          style={{
            borderColor: colors.border,
            backgroundColor: colors.surface,
            color: colors.onSurface,
          }}
          data-testid="citation-filter-status"
        >
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All statuses" : (STATUS_META[s]?.label || s)}
            </option>
          ))}
        </select>

        <div className="relative flex-1 min-w-[160px]">
          <input
            type="text"
            placeholder="Search directories…"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className="w-full pl-8 pr-2 py-1.5 rounded-lg border text-sm"
            style={{
              borderColor: colors.border,
              backgroundColor: colors.surface,
              color: colors.onSurface,
            }}
            data-testid="citation-filter-search"
          />
          <Search
            size={14}
            style={{ position: "absolute", left: 8, top: 10, color: colors.muted }}
          />
        </div>

        <label
          className="inline-flex items-center gap-2 text-sm select-none"
          style={{ color: colors.onSurface }}
        >
          <input
            type="checkbox"
            checked={driftOnly}
            onChange={(e) => onDriftOnly(e.target.checked)}
            data-testid="citation-filter-drift-only"
          />
          NAP drift only
        </label>

        <button
          type="button"
          onClick={onBulkVerify}
          disabled={selectedCount === 0 || bulkBusy}
          className="ml-auto px-3 py-1.5 rounded-lg text-sm font-semibold text-white disabled:opacity-50 disabled:cursor-not-allowed"
          style={{ backgroundColor: colors.brand }}
          data-testid="citation-bulk-verify"
        >
          {bulkBusy ? "Verifying…" : `Mark ${selectedCount} verified`}
        </button>

        <button
          type="button"
          onClick={onRefresh}
          className="px-3 py-1.5 rounded-lg text-sm font-semibold"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
          }}
          data-testid="citation-refresh"
          aria-label="Refresh"
        >
          <RefreshCw size={14} />
        </button>
      </div>
    </div>
  );
}


function CitationRow({ row, selected, onToggle, onEdit }) {
  const d = row.directory || {};
  const meta = CATEGORY_META[d.category] || CATEGORY_META.other;
  const sMeta = STATUS_META[row.status] || STATUS_META.not_started;
  const weight = Math.max(1, Math.min(5, Math.round((d.weight || 1) / 2)));
  const stars = "★".repeat(weight) + "☆".repeat(5 - weight);
  return (
    <li
      className="rounded-xl p-3 flex items-center gap-3 flex-wrap sm:flex-nowrap"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${row.nap_drift_detected ? "#DC2626" : colors.border}`,
      }}
      data-testid={`citation-row-${d.slug}`}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={onToggle}
        className="shrink-0"
        aria-label={`Select ${d.name}`}
        data-testid={`citation-row-select-${d.slug}`}
      />

      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
        style={{ backgroundColor: `${meta.tint}22`, color: meta.tint }}
        aria-hidden="true"
      >
        <meta.Icon size={17} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="font-semibold truncate"
            style={{ color: colors.onSurface }}
            data-testid={`citation-row-name-${d.slug}`}
          >
            {d.name}
          </span>
          <span
            className="text-[10px]"
            style={{ color: "#CA8A04" }}
            title={`SEO weight ${d.weight}/10`}
            data-testid={`citation-row-stars-${d.slug}`}
          >
            {stars}
          </span>
          <span
            className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded"
            style={{ backgroundColor: `${meta.tint}22`, color: meta.tint }}
          >
            {meta.label}
          </span>
        </div>
        <div
          className="text-[11px] mt-0.5 flex items-center gap-2 flex-wrap"
          style={{ color: colors.muted }}
        >
          <span
            data-testid={`citation-row-verified-${d.slug}`}
            title={row.last_verified_at || "Never verified"}
          >
            Verified: {relativeAge(row.last_verified_at)}
          </span>
          {row.listing_url ? (
            <a
              href={row.listing_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex items-center gap-1 text-[11px] underline"
              style={{ color: colors.brand }}
              data-testid={`citation-row-listing-${d.slug}`}
            >
              Listing <ExternalLink size={11} />
            </a>
          ) : null}
        </div>
      </div>

      <span
        className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded whitespace-nowrap"
        style={{ backgroundColor: sMeta.bg, color: sMeta.fg }}
        data-testid={`citation-row-status-${d.slug}`}
      >
        {sMeta.label}
      </span>

      {row.nap_drift_detected ? (
        <span
          className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded whitespace-nowrap"
          style={{ backgroundColor: "#FEE2E2", color: "#991B1B" }}
          data-testid={`citation-row-drift-${d.slug}`}
          title="NAP drift detected — your business info changed since last verification"
        >
          ⚠ Drift
        </span>
      ) : null}

      {d.url ? (
        <a
          href={d.url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold"
          style={{
            backgroundColor: colors.surfaceSecondary,
            color: colors.onSurface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid={`citation-row-open-${d.slug}`}
        >
          <ExternalLink size={12} /> Open
        </a>
      ) : null}

      <button
        type="button"
        onClick={onEdit}
        className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-semibold text-white"
        style={{ backgroundColor: colors.brand }}
        data-testid={`citation-row-edit-${d.slug}`}
        aria-label={`Edit ${d.name}`}
      >
        <Pencil size={12} /> Edit
      </button>
    </li>
  );
}


function EditSheet({ row, onClose, onSave, onVerify }) {
  const [status, setStatus] = React.useState(row.status || "not_started");
  const [listingUrl, setListingUrl] = React.useState(row.listing_url || "");
  const [notes, setNotes] = React.useState(row.notes || "");
  const [saving, setSaving] = React.useState(false);

  const submit = async (e) => {
    e?.preventDefault?.();
    setSaving(true);
    try {
      await onSave({ status, listing_url: listingUrl, notes });
    } catch { /* toast already shown */ }
    finally { setSaving(false); }
  };

  const d = row.directory || {};
  return (
    <div
      className="fixed inset-0 z-[60] flex items-stretch justify-end"
      style={{ background: "rgba(15,23,42,0.55)" }}
      onMouseDown={onClose}
      data-testid="citation-edit-sheet"
    >
      <form
        onMouseDown={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-md h-full flex flex-col shadow-2xl"
        style={{ backgroundColor: colors.surface }}
      >
        <div
          className="px-5 py-4 flex items-center justify-between"
          style={{
            borderBottom: `1px solid ${colors.border}`,
            background: brandGradientCss,
            color: "#fff",
          }}
        >
          <div className="min-w-0">
            <div className="text-xs opacity-90">Editing citation</div>
            <div
              className="text-lg font-bold truncate"
              data-testid="citation-edit-title"
            >
              {d.name}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: "rgba(255,255,255,0.18)" }}
            data-testid="citation-edit-close"
          >
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
          <div>
            <label
              htmlFor="citation-edit-status"
              className="text-xs font-semibold block mb-1"
              style={{ color: colors.onSurface }}
            >
              Status
            </label>
            <select
              id="citation-edit-status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                borderColor: colors.border,
                backgroundColor: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="citation-edit-status"
            >
              {STATUS_ORDER.filter((s) => s !== "all").map((s) => (
                <option key={s} value={s}>{STATUS_META[s].label}</option>
              ))}
            </select>
          </div>
          <div>
            <label
              htmlFor="citation-edit-listing-url"
              className="text-xs font-semibold block mb-1"
              style={{ color: colors.onSurface }}
            >
              Listing URL
            </label>
            <input
              id="citation-edit-listing-url"
              type="url"
              value={listingUrl}
              onChange={(e) => setListingUrl(e.target.value)}
              placeholder="https://…"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                borderColor: colors.border,
                backgroundColor: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="citation-edit-listing-url"
            />
          </div>
          <div>
            <label
              htmlFor="citation-edit-notes"
              className="text-xs font-semibold block mb-1"
              style={{ color: colors.onSurface }}
            >
              Notes
            </label>
            <textarea
              id="citation-edit-notes"
              rows={4}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                borderColor: colors.border,
                backgroundColor: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="citation-edit-notes"
            />
          </div>
          {row.nap_drift_detected ? (
            <div
              className="rounded-lg p-2 text-sm flex items-start gap-2"
              style={{
                backgroundColor: "#FEE2E2",
                color: "#991B1B",
                border: "1px solid #FCA5A5",
              }}
            >
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <div>
                <b>NAP drift detected.</b> Your business info changed since
                the last verification. Update the listing to match, then
                click "Mark verified" to snapshot the new NAP.
              </div>
            </div>
          ) : null}
        </div>
        <div
          className="px-5 py-3 flex items-center justify-between gap-2"
          style={{
            borderTop: `1px solid ${colors.border}`,
            backgroundColor: colors.surfaceSecondary,
          }}
        >
          <button
            type="button"
            onClick={onVerify}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-lg text-sm font-semibold"
            style={{
              backgroundColor: "#DCFCE7",
              color: "#166534",
              border: "1px solid #86EFAC",
            }}
            data-testid="citation-edit-verify"
          >
            <CheckCircle2 size={14} /> Mark verified
          </button>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-2 rounded-lg text-sm font-semibold"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
                color: colors.onSurface,
              }}
              data-testid="citation-edit-cancel"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-1 px-4 py-2 rounded-lg text-sm font-bold text-white disabled:opacity-60 disabled:cursor-not-allowed"
              style={{ backgroundColor: colors.brand }}
              data-testid="citation-edit-save"
            >
              <Save size={14} /> {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}


function EmptyState() {
  return (
    <div
      className="rounded-2xl p-8 text-center"
      style={{
        backgroundColor: colors.surface,
        border: `1px dashed ${colors.border}`,
      }}
      data-testid="citation-builder-empty"
    >
      <div
        className="w-12 h-12 rounded-full mx-auto mb-3 flex items-center justify-center"
        style={{ backgroundColor: "#DBEAFE", color: "#1E40AF" }}
      >
        <Globe size={22} />
      </div>
      <div className="font-semibold" style={{ color: colors.onSurface }}>
        Start with Google Business Profile
      </div>
      <div className="text-sm mt-1" style={{ color: colors.muted }}>
        Claim your Google Business Profile listing first, then work down
        the list by weight — the highest-value directories are at the top.
      </div>
    </div>
  );
}
