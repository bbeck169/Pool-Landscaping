import React from "react";
import { toast } from "sonner";
import { api } from "@/api";
import { colors } from "@/theme";
import SafeScrollContainer from "@/components/layout/SafeScrollContainer";
import AIDescriptionRewriteButton from "@/components/ai/AIDescriptionRewriteButton";
import {
  RefreshCw, Check, X, MapPin, ShieldCheck, ShieldAlert, Ban, ExternalLink,
} from "lucide-react";

/**
 * MR0 · Feb-2026 — Admin moderation queue for public check-ins.
 *
 * Two-panel layout on desktop, stacks on mobile:
 *   - Left: list of rows filtered by state (default pending_review).
 *   - Right: detail with editable fields + approve/reject/unpublish.
 *
 * Backing endpoints all under ``/api/admin/moderation/public-checkins``.
 */

const STATE_OPTIONS = [
  { value: "pending_review", label: "Pending review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "unpublished", label: "Unpublished" },
  { value: "all", label: "All" },
];

function _pill(state) {
  switch (state) {
    case "pending_review":
      return { bg: "#FEF3C7", fg: "#92400E", label: "Pending" };
    case "approved":
      return { bg: "#DCFCE7", fg: "#065F46", label: "Approved" };
    case "rejected":
      return { bg: "#FEE2E2", fg: "#7F1D1D", label: "Rejected" };
    case "unpublished":
      return { bg: "#E5E7EB", fg: "#374151", label: "Unpublished" };
    default:
      return { bg: colors.surfaceSecondary, fg: colors.muted, label: state };
  }
}

export default function ModerationCheckinsPage() {
  const [state, setState] = React.useState("pending_review");
  const [items, setItems] = React.useState([]);
  const [total, setTotal] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [selectedId, setSelectedId] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [busy, setBusy] = React.useState(false);

  // MR-QoL · Feb-2026 — Bulk selection state (pending list only).
  const [bulkSelected, setBulkSelected] = React.useState(new Set());
  const [bulkMode, setBulkMode] = React.useState(null); // "approve" | "reject" | null
  const [bulkNotes, setBulkNotes] = React.useState("");

  const [draft, setDraft] = React.useState(null);
  const [rejectNotes, setRejectNotes] = React.useState("");

  const loadList = React.useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get(
        `/admin/moderation/public-checkins?state=${encodeURIComponent(state)}&limit=200`,
      );
      const list = r?.items || [];
      setItems(list);
      setTotal(r?.total || 0);
      if (!selectedId && list.length > 0) setSelectedId(list[0].id);
    } catch (e) {
      toast.error("Failed to load queue", { description: e?.message });
    } finally {
      setLoading(false);
    }
  }, [state, selectedId]);

  React.useEffect(() => { loadList(); /* eslint-disable-next-line */ }, [state]);

  // MR-QoL · Feb-2026 — Bulk helpers (declared after loadList so we
  // can reference it in runBulk).
  React.useEffect(() => { setBulkSelected(new Set()); }, [items, state]);

  const toggleRow = (id) => {
    setBulkSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleAllVisible = () => {
    setBulkSelected((prev) => {
      const visibleIds = items.map((it) => it.id);
      const allSelected = visibleIds.every((id) => prev.has(id));
      return allSelected ? new Set() : new Set(visibleIds);
    });
  };
  const closeBulkModal = () => {
    setBulkMode(null); setBulkNotes(""); setBusy(false);
  };
  const runBulk = async () => {
    if (!bulkMode) return;
    const ids = Array.from(bulkSelected);
    if (ids.length === 0) return;
    if (bulkMode === "reject" && !bulkNotes.trim()) {
      toast.error("Reviewer notes required to reject");
      return;
    }
    setBusy(true);
    try {
      const url = `/admin/moderation/public-checkins/bulk-${bulkMode}`;
      const body = bulkMode === "reject"
        ? { ids, reviewer_notes: bulkNotes.trim() }
        : { ids, reviewer_notes: bulkNotes.trim() || null };
      const r = await api.post(url, body);
      const key = bulkMode === "reject" ? "rejected" : "approved";
      toast.success(`Bulk done · ${key} ${r[key] || 0}, skipped ${r.skipped || 0}`);
      closeBulkModal();
      setBulkSelected(new Set());
      loadList();
    } catch (e) {
      toast.error("Bulk action failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };

  React.useEffect(() => {
    let cancelled = false;
    if (!selectedId) { setSelected(null); return; }
    (async () => {
      try {
        const r = await api.get(
          `/admin/moderation/public-checkins/${encodeURIComponent(selectedId)}`,
        );
        if (cancelled) return;
        setSelected(r);
        setDraft({
          service_name: r.service_name || "",
          service_category: r.service_category || "",
          description: r.description || "",
          tags: (r.tags || []).join(", "),
        });
      } catch (e) {
        if (!cancelled) {
          toast.error("Failed to load detail", { description: e?.message });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  const dirty = selected && draft && (
    draft.service_name !== (selected.service_name || "") ||
    draft.service_category !== (selected.service_category || "") ||
    draft.description !== (selected.description || "") ||
    draft.tags !== (selected.tags || []).join(", ")
  );

  const canEdit = selected &&
    (selected.state === "pending_review" || selected.state === "approved");
  const isPending = selected?.state === "pending_review";
  const isApproved = selected?.state === "approved";

  const saveEdits = async () => {
    if (!selected || !dirty) return;
    setBusy(true);
    try {
      const body = {
        service_name: draft.service_name,
        service_category: draft.service_category || null,
        description: draft.description,
        tags: draft.tags.split(",").map((s) => s.trim()).filter(Boolean),
      };
      const r = await api.patch(
        `/admin/moderation/public-checkins/${selected.id}`, body,
      );
      setSelected(r);
      toast.success("Edits saved");
    } catch (e) {
      toast.error("Save failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };

  const doApprove = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const r = await api.post(
        `/admin/moderation/public-checkins/${selected.id}/approve`,
        { reviewer_notes: null },
      );
      setSelected(r);
      toast.success("Approved & published");
      loadList();
    } catch (e) {
      toast.error("Approve failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };

  const doReject = async () => {
    if (!selected) return;
    if (!rejectNotes.trim()) {
      toast.error("Reviewer notes required to reject");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post(
        `/admin/moderation/public-checkins/${selected.id}/reject`,
        { reviewer_notes: rejectNotes.trim() },
      );
      setSelected(r);
      setRejectNotes("");
      toast.success("Rejected");
      loadList();
    } catch (e) {
      toast.error("Reject failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };

  const doUnpublish = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const r = await api.post(
        `/admin/moderation/public-checkins/${selected.id}/unpublish`, {},
      );
      setSelected(r);
      toast.success("Unpublished");
      loadList();
    } catch (e) {
      toast.error("Unpublish failed", { description: e?.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeScrollContainer
      className="px-4 md:px-8 pt-6 space-y-4"
      data-testid="moderation-checkins-page"
    >
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1
            className="text-2xl font-semibold"
            style={{ color: colors.onSurface }}
            data-testid="moderation-checkins-title"
          >
            Check-in Moderation
          </h1>
          <p className="text-sm mt-1" style={{ color: colors.muted }}>
            Tech-submitted check-ins awaiting public display approval.
            House numbers are hidden automatically on approval.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={state}
            onChange={(e) => { setState(e.target.value); setSelectedId(null); }}
            className="h-9 px-2 rounded-lg text-sm"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="moderation-state-filter"
          >
            {STATE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={loadList}
            className="inline-flex items-center gap-2 h-9 px-3 rounded-lg text-sm font-semibold"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid="moderation-refresh"
          >
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Left: list */}
        <aside
          className="md:col-span-1 rounded-xl overflow-hidden"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="moderation-list"
        >
          <div
            className="text-xs font-semibold px-3 py-2 flex items-center justify-between"
            style={{ color: colors.muted, borderBottom: `1px solid ${colors.border}` }}
          >
            <span>{total} row{total === 1 ? "" : "s"}</span>
            <span>{state.replace("_", " ")}</span>
          </div>
          {state === "pending_review" && items.length > 0 ? (
            <div
              className="flex items-center gap-2 px-3 py-2"
              style={{ borderBottom: `1px solid ${colors.border}`, backgroundColor: colors.surfaceSecondary }}
            >
              <input
                type="checkbox"
                onChange={toggleAllVisible}
                checked={items.length > 0 && items.every((it) => bulkSelected.has(it.id))}
                data-testid="moderation-select-all"
                aria-label="Select all visible"
              />
              <span className="text-xs font-semibold" style={{ color: colors.muted }}>
                {bulkSelected.size > 0 ? `${bulkSelected.size} selected` : "Select all visible"}
              </span>
              {bulkSelected.size > 0 ? (
                <div className="ml-auto flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => { setBulkMode("approve"); setBulkNotes(""); }}
                    className="h-7 px-2 rounded text-xs font-semibold text-white"
                    style={{ backgroundColor: "#10B981", border: 0 }}
                    data-testid="moderation-bulk-approve"
                  >
                    <Check size={12} className="inline" /> Bulk approve
                  </button>
                  <button
                    type="button"
                    onClick={() => { setBulkMode("reject"); setBulkNotes(""); }}
                    className="h-7 px-2 rounded text-xs font-semibold text-white"
                    style={{ backgroundColor: "#DC2626", border: 0 }}
                    data-testid="moderation-bulk-reject"
                  >
                    <X size={12} className="inline" /> Bulk reject
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
          {loading ? (
            <div className="p-4 text-sm text-center" style={{ color: colors.muted }}
                  data-testid="moderation-loading">
              Loading…
            </div>
          ) : items.length === 0 ? (
            <div className="p-4 text-sm text-center" style={{ color: colors.muted }}
                  data-testid="moderation-empty">
              Nothing here.
            </div>
          ) : (
            <ul>
              {items.map((it) => {
                const p = _pill(it.state);
                const active = it.id === selectedId;
                return (
                  <li key={it.id}>
                    <div className="flex items-stretch"
                          style={{ borderBottom: `1px solid ${colors.border}`,
                                    backgroundColor: active ? "#EEF2FF" : "transparent" }}>
                      {state === "pending_review" ? (
                        <label className="flex items-center px-2"
                               style={{ borderRight: `1px solid ${colors.border}` }}
                               onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={bulkSelected.has(it.id)}
                            onChange={() => toggleRow(it.id)}
                            data-testid={`moderation-select-${it.id}`}
                            aria-label={`Select ${it.service_name || it.id}`}
                          />
                        </label>
                      ) : null}
                      <button
                        type="button"
                        onClick={() => setSelectedId(it.id)}
                        className="w-full text-left px-3 py-2"
                        style={{ color: colors.onSurface, backgroundColor: "transparent" }}
                        data-testid={`moderation-item-${it.id}`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm font-semibold truncate">
                            {it.service_name || "Untitled service"}
                          </div>
                          <span
                            className="text-[10px] px-1.5 py-0.5 rounded"
                            style={{ backgroundColor: p.bg, color: p.fg }}
                          >
                            {p.label}
                          </span>
                        </div>
                        <div className="text-[11px] mt-0.5" style={{ color: colors.muted }}>
                          {(it.submitted_at || "").slice(0, 16).replace("T", " ")} · {(it.photos || []).length} photo{(it.photos || []).length === 1 ? "" : "s"}
                        </div>
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </aside>

        {/* Right: detail */}
        <section className="md:col-span-2" data-testid="moderation-detail-panel">
          {!selected ? (
            <div
              className="rounded-xl p-8 text-center text-sm"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
                color: colors.muted,
              }}
              data-testid="moderation-nothing-selected"
            >
              Select a row on the left to review.
            </div>
          ) : (
            <div
              className="rounded-xl p-4 space-y-4"
              style={{
                backgroundColor: colors.surface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={`moderation-detail-${selected.id}`}
            >
              <StateBanner row={selected} />

              {/* Photos */}
              {(selected.photos || []).length > 0 ? (
                <div className="grid grid-cols-3 sm:grid-cols-4 gap-2"
                      data-testid="moderation-photo-grid">
                  {(selected.photos || []).map((p, idx) => (
                    <a key={p.id || idx}
                        href={p.url}
                        target="_blank"
                        rel="noreferrer"
                        className="block aspect-square rounded overflow-hidden"
                        style={{ backgroundColor: colors.surfaceSecondary,
                                  border: `1px solid ${colors.border}` }}
                        data-testid={`moderation-photo-${idx}`}>
                      <img src={p.url} alt={p.alt || `Attachment ${idx + 1}`}
                            style={{ width: "100%", height: "100%",
                                      objectFit: "cover" }} />
                    </a>
                  ))}
                </div>
              ) : (
                <div className="text-xs italic" style={{ color: colors.muted }}>
                  No photos attached.
                </div>
              )}

              {/* Editable fields */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <LabelledInput
                  label="Service name"
                  value={draft?.service_name || ""}
                  onChange={(v) => setDraft({ ...(draft || {}), service_name: v })}
                  disabled={!canEdit}
                  testId="moderation-field-service-name"
                />
                <LabelledInput
                  label="Category"
                  value={draft?.service_category || ""}
                  onChange={(v) => setDraft({ ...(draft || {}), service_category: v })}
                  disabled={!canEdit}
                  testId="moderation-field-service-category"
                />
              </div>
              <LabelledTextareaWithAI
                label="Description"
                value={draft?.description || ""}
                onChange={(v) => setDraft({ ...(draft || {}), description: v })}
                disabled={!canEdit}
                testId="moderation-field-description"
                canRewrite={canEdit}
                selected={selected}
              />
              <LabelledInput
                label="Tags (comma-separated)"
                value={draft?.tags || ""}
                onChange={(v) => setDraft({ ...(draft || {}), tags: v })}
                disabled={!canEdit}
                testId="moderation-field-tags"
              />

              {/* Address preview */}
              <div
                className="rounded-lg p-3 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs"
                style={{ backgroundColor: colors.surfaceSecondary,
                         border: `1px solid ${colors.border}` }}
              >
                <div>
                  <div className="font-semibold mb-1" style={{ color: colors.muted }}>
                    <MapPin size={12} className="inline" /> Raw address (internal)
                  </div>
                  <div style={{ color: colors.onSurface }}
                        data-testid="moderation-raw-address">
                    {(selected.raw_address?.street || "—")}, {(selected.raw_address?.city || "—")}, {(selected.raw_address?.state || "—")} {(selected.raw_address?.zip || "")}
                  </div>
                </div>
                <div>
                  <div className="font-semibold mb-1" style={{ color: colors.muted }}>
                    <ShieldCheck size={12} className="inline" /> Public masked
                  </div>
                  <div style={{ color: colors.onSurface }}
                        data-testid="moderation-masked-address">
                    {selected.masked_address
                      ? `${selected.masked_address.street_name}, ${selected.masked_address.city}, ${selected.masked_address.state}`
                      : `${_previewMask(selected.raw_address?.street || "")}, ${selected.raw_address?.city || ""}, ${selected.raw_address?.state || ""}`}
                  </div>
                </div>
              </div>

              {/* Reviewer notes / rejection */}
              {isPending ? (
                <LabelledTextarea
                  label="Reviewer notes (required to reject)"
                  value={rejectNotes}
                  onChange={setRejectNotes}
                  disabled={busy}
                  testId="moderation-reject-notes"
                />
              ) : null}

              {/* Actions */}
              <div className="flex items-center gap-2 flex-wrap">
                {dirty && canEdit ? (
                  <button
                    type="button"
                    onClick={saveEdits}
                    disabled={busy}
                    className="h-9 px-3 rounded-lg text-sm font-semibold text-white inline-flex items-center gap-1.5"
                    style={{ backgroundColor: "#2563EB", border: 0 }}
                    data-testid="moderation-btn-save"
                  >
                    Save Edits
                  </button>
                ) : null}
                {isPending ? (
                  <>
                    <button
                      type="button"
                      onClick={doApprove}
                      disabled={busy}
                      className="h-9 px-3 rounded-lg text-sm font-semibold text-white inline-flex items-center gap-1.5"
                      style={{ backgroundColor: "#10B981", border: 0 }}
                      data-testid="moderation-btn-approve"
                    >
                      <Check size={14} /> Approve & Publish
                    </button>
                    <button
                      type="button"
                      onClick={doReject}
                      disabled={busy || !rejectNotes.trim()}
                      className="h-9 px-3 rounded-lg text-sm font-semibold text-white inline-flex items-center gap-1.5"
                      style={{ backgroundColor: "#DC2626", border: 0,
                               opacity: rejectNotes.trim() ? 1 : 0.6 }}
                      data-testid="moderation-btn-reject"
                    >
                      <X size={14} /> Reject
                    </button>
                  </>
                ) : null}
                {isApproved ? (
                  <button
                    type="button"
                    onClick={doUnpublish}
                    disabled={busy}
                    className="h-9 px-3 rounded-lg text-sm font-semibold inline-flex items-center gap-1.5"
                    style={{
                      backgroundColor: colors.surface,
                      color: colors.onSurface,
                      border: `1px solid ${colors.border}`,
                    }}
                    data-testid="moderation-btn-unpublish"
                  >
                    <Ban size={14} /> Unpublish
                  </button>
                ) : null}
              </div>
            </div>
          )}
        </section>
      </div>
      {/* MR-QoL · Feb-2026 — Bulk confirm modal. */}
      {bulkMode ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ backgroundColor: "rgba(15,23,42,0.5)" }}
          role="dialog" aria-modal="true"
          data-testid="moderation-bulk-modal"
        >
          <div className="w-full max-w-md rounded-2xl p-5"
                style={{ backgroundColor: colors.surface,
                          border: `1px solid ${colors.border}` }}>
            <div className="flex items-center justify-between mb-3">
              <div className="text-base font-semibold" style={{ color: colors.onSurface }}>
                {bulkMode === "approve"
                  ? `Bulk approve ${bulkSelected.size} row${bulkSelected.size === 1 ? "" : "s"}`
                  : `Bulk reject ${bulkSelected.size} row${bulkSelected.size === 1 ? "" : "s"}`}
              </div>
              <button type="button" onClick={closeBulkModal}
                       aria-label="Close" data-testid="moderation-bulk-close">
                <X size={16} />
              </button>
            </div>
            <p className="text-xs mb-2" style={{ color: colors.muted }}>
              {bulkMode === "approve"
                ? "Optional reviewer notes will be stamped on every row."
                : "Reviewer notes are required and will appear on the rejected row."}
            </p>
            <textarea
              value={bulkNotes}
              onChange={(e) => setBulkNotes(e.target.value)}
              rows={3}
              placeholder={bulkMode === "reject" ? "Required: reason for rejection" : "Optional notes"}
              data-testid="moderation-bulk-notes"
              className="w-full p-2 rounded-lg text-sm"
              style={{ backgroundColor: colors.surface,
                        color: colors.onSurface,
                        border: `1px solid ${colors.border}` }}
            />
            <div className="mt-4 flex items-center justify-end gap-2">
              <button type="button" onClick={closeBulkModal}
                       className="h-9 px-3 rounded-lg text-sm font-semibold"
                       style={{ backgroundColor: colors.surface,
                                 color: colors.onSurface,
                                 border: `1px solid ${colors.border}` }}
                       data-testid="moderation-bulk-cancel">
                Cancel
              </button>
              <button
                type="button"
                onClick={runBulk}
                disabled={busy || (bulkMode === "reject" && !bulkNotes.trim())}
                className="h-9 px-3 rounded-lg text-sm font-semibold text-white"
                style={{
                  backgroundColor: bulkMode === "approve" ? "#10B981" : "#DC2626",
                  border: 0,
                  opacity: (bulkMode === "reject" && !bulkNotes.trim()) ? 0.6 : 1,
                  cursor: (bulkMode === "reject" && !bulkNotes.trim()) ? "not-allowed" : "pointer",
                }}
                data-testid="moderation-bulk-submit"
              >
                {busy ? "Working…" : (bulkMode === "approve" ? "Approve all" : "Reject all")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </SafeScrollContainer>
  );
}


function _previewMask(street) {
  const m = String(street || "").match(/^\d[\dA-Za-z\-/]*\s+/);
  return m ? String(street).slice(m[0].length).trim() : String(street || "");
}


function StateBanner({ row }) {
  const p = _pill(row.state);
  if (row.state === "approved") {
    return (
      <div className="rounded-lg px-3 py-2 text-sm flex items-center gap-2"
            style={{ backgroundColor: p.bg, color: p.fg }}
            data-testid="moderation-banner-approved">
        <ShieldCheck size={14} /> Published on {(row.approved_at || "").slice(0, 16).replace("T", " ")}
      </div>
    );
  }
  if (row.state === "rejected") {
    return (
      <div className="rounded-lg px-3 py-2 text-sm flex flex-col gap-1"
            style={{ backgroundColor: p.bg, color: p.fg }}
            data-testid="moderation-banner-rejected">
        <div className="flex items-center gap-2 font-semibold">
          <ShieldAlert size={14} /> Rejected
        </div>
        <div className="text-xs">{row.reviewer_notes || "(no notes)"}</div>
      </div>
    );
  }
  if (row.state === "unpublished") {
    return (
      <div className="rounded-lg px-3 py-2 text-sm flex items-center gap-2"
            style={{ backgroundColor: p.bg, color: p.fg }}
            data-testid="moderation-banner-unpublished">
        <Ban size={14} /> Unpublished on {(row.unpublished_at || "").slice(0, 16).replace("T", " ")}
      </div>
    );
  }
  return (
    <div className="text-xs" style={{ color: colors.muted }}
          data-testid="moderation-banner-pending">
      Submitted {(row.submitted_at || "").slice(0, 16).replace("T", " ")}
      {row.photos?.length ? ` · ${row.photos.length} photo${row.photos.length === 1 ? "" : "s"}` : ""}
    </div>
  );
}


function LabelledInput({ label, value, onChange, disabled, testId }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: colors.muted }}>
      {label}
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        data-testid={testId}
        className="h-9 px-2 rounded-lg text-sm"
        style={{
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
      />
    </label>
  );
}


// MR-QoL · Feb-2026 — Description textarea + inline AI Rewrite button.
function LabelledTextareaWithAI({ label, value, onChange, disabled,
                                    testId, canRewrite, selected }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: colors.muted }}>
      <div className="flex items-center justify-between">
        <span>{label}</span>
        {canRewrite ? (
          <AIDescriptionRewriteButton
            draft={value}
            onRewritten={(text) => { onChange(text); }}
            context={{ service_category: selected?.service_category || undefined }}
            size="xs"
            testid="moderation-field-description-ai"
          />
        ) : null}
      </div>
      <textarea
        rows={4}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        data-testid={testId}
        className="p-2 rounded-lg text-sm"
        style={{
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
      />
    </label>
  );
}





function LabelledTextarea({ label, value, onChange, disabled, testId }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-semibold" style={{ color: colors.muted }}>
      {label}
      <textarea
        rows={3}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        data-testid={testId}
        className="p-2 rounded-lg text-sm"
        style={{
          backgroundColor: colors.surface,
          color: colors.onSurface,
          border: `1px solid ${colors.border}`,
        }}
      />
    </label>
  );
}

