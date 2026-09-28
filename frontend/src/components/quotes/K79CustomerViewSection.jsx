/**
 * Phase K79 · Feb-2026 — Customer-facing grouped view controls.
 *
 * Renders on the estimate/quote editor. Two concerns:
 *   1. A checkbox toggling ``customer_group_display`` — writes back
 *      via PUT /quotes/{id} on change.
 *   2. Per-service-category description inputs, one row per unique
 *      ``service_category_id`` in ``doc.line_items``. Cap 250 chars.
 *   3. A "Preview customer view" button that opens the preview modal
 *      (rendered by <K79CustomerViewPreview> — see sibling file).
 *
 * Admin-only surface. Not shown on portal / customer views.
 *
 * The rendering itself is deliberately lightweight (no form library).
 * State strategy: local edits stage optimistically; Save button (per
 * row) commits via PUT with the full ``customer_group_descriptions``
 * dict so the server merge is a straight replace.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Eye, Save as SaveIcon } from "lucide-react";
import { toast } from "sonner";
import { colors } from "@/theme";
import { api } from "@/api";
import { Switch } from "@/components/ui/switch";
import K79CustomerViewPreview from "./K79CustomerViewPreview";

const MAX_GROUP_DESC = 250;


function _uniqueServiceCategories(lines, allCats) {
  const seen = new Set();
  const out = [];
  for (const li of lines || []) {
    const cid = li?.service_category_id;
    if (!cid || seen.has(cid)) continue;
    seen.add(cid);
    const cat = (allCats || []).find((c) => c.id === cid);
    out.push({
      id: cid,
      name: cat?.name || cid,
    });
  }
  return out;
}


export default function K79CustomerViewSection({ doc, onDocRefresh }) {
  // Phase K79-TOGGLE · Feb-2026 — re-enable the grouped-layout
  // toggle for customer surfaces. Default = ON when the field is
  // missing (legacy quotes keep today's grouped rendering).
  // Backend + portal + PDF all branch on ``customer_group_display``
  // with the same "None → true" compat rule so a legacy quote
  // renders grouped everywhere.
  const initialGrouped = (
    doc?.customer_group_display === undefined
    || doc?.customer_group_display === null
      ? true
      : Boolean(doc.customer_group_display)
  );
  const [grouped, setGrouped] = useState(initialGrouped);
  const [groupedSaving, setGroupedSaving] = useState(false);
  const [descriptions, setDescriptions] = useState(
    doc.customer_group_descriptions || {},
  );
  const [savingKey, setSavingKey] = useState(null);
  const [error, setError] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [serviceCats, setServiceCats] = useState([]);

  // Sync local state when parent reloads doc after a save.
  useEffect(() => {
    setDescriptions(doc.customer_group_descriptions || {});
  }, [doc.customer_group_descriptions]);

  // K79-TOGGLE · Feb-2026 — keep the local toggle in sync when the
  // parent refreshes ``doc`` (e.g., after another user edited the
  // quote). Uses the same None → true compat rule as initial mount.
  useEffect(() => {
    setGrouped(
      doc?.customer_group_display === undefined
      || doc?.customer_group_display === null
        ? true
        : Boolean(doc.customer_group_display),
    );
  }, [doc?.customer_group_display]);

  useEffect(() => {
    let alive = true;
    api.get("/service-categories").then((res) => {
      if (!alive) return;
      setServiceCats(res?.items || []);
    }).catch(() => { if (alive) setServiceCats([]); });
    return () => { alive = false; };
  }, []);

  const groups = useMemo(
    () => _uniqueServiceCategories(doc.line_items, serviceCats),
    [doc.line_items, serviceCats],
  );

  // K79-TOGGLE · Feb-2026 — optimistic flip + revert-on-error.
  const persistGrouped = async (nextValue) => {
    const priorValue = grouped;
    setGrouped(nextValue);          // optimistic
    setGroupedSaving(true);
    try {
      await api.put(`/quotes/${doc.id}`, {
        customer_group_display: nextValue,
      });
      onDocRefresh?.();
    } catch (e) {
      // Revert UI + surface a toast — the sibling code lane
      // convention (see settings/PaymentProvidersCard.jsx).
      setGrouped(priorValue);
      toast.error(e?.message || "Failed to save grouped-layout toggle");
    } finally {
      setGroupedSaving(false);
    }
  };

  const persistDescription = async (catId) => {
    setSavingKey(catId);
    setError("");
    const nextDescriptions = { ...descriptions };
    const val = (nextDescriptions[catId] || "").slice(0, MAX_GROUP_DESC);
    nextDescriptions[catId] = val;
    try {
      await api.put(`/quotes/${doc.id}`, {
        customer_group_descriptions: nextDescriptions,
      });
      setDescriptions(nextDescriptions);
      onDocRefresh?.();
    } catch (e) {
      setError(e?.message || "Failed to save");
    } finally {
      setSavingKey(null);
    }
  };

  return (
    <div
      className="rounded-2xl p-6 mb-4"
      style={{ backgroundColor: colors.surface,
                border: `1px solid ${colors.border}` }}
      data-testid="k79-customer-view-section"
    >
      <div className="flex items-start justify-between mb-3 gap-3">
        <div>
          <h2 className="text-lg font-bold"
              style={{ color: colors.onSurface }}>
            Customer view
          </h2>
          <p className="text-xs mt-0.5" style={{ color: colors.muted }}>
            Choose how the customer sees this estimate. Admin view stays
            fully itemized.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setPreviewOpen(true)}
          className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-semibold"
          style={{ background: colors.surfaceSecondary,
                    border: `1px solid ${colors.border}`,
                    color: colors.brand }}
          data-testid="k79-preview-btn"
        >
          <Eye size={13} /> Preview customer view
        </button>
      </div>

      <label
        className="flex items-center gap-2 mb-3 text-sm"
        style={{ color: colors.onSurface }}
        data-testid="k79-grouped-toggle-row"
        htmlFor="k79-grouped-toggle"
      >
        {/* K79-TOGGLE · Feb-2026 — real Switch bound to
            ``customer_group_display``. Optimistic flip with a
            revert-on-error path (see ``persistGrouped``). Legacy
            quotes with the field absent default to ON, matching
            the prior lock-on behaviour so nothing regresses on
            historicals. */}
        <Switch
          id="k79-grouped-toggle"
          checked={grouped}
          disabled={groupedSaving}
          onCheckedChange={(next) => persistGrouped(Boolean(next))}
          data-testid="k79-grouped-toggle"
          aria-label="Grouped layout for customer-facing surfaces"
        />
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold"
          style={{
            background: colors.surfaceSecondary,
            border: `1px solid ${colors.border}`,
            color: grouped ? colors.brand : colors.muted,
          }}
          data-testid="k79-grouped-toggle-pill"
        >
          {`GROUPED LAYOUT (${grouped ? "ON" : "OFF"})`}
        </span>
        <span style={{ color: colors.muted }}>
          {grouped
            ? "Customer views show rolled-up service groups."
            : "Customer views show a fully itemized list."}
        </span>
      </label>

      {/* Group descriptions editor — always rendered since grouped
          layout is now locked on for customer surfaces. */}
      <div
          className="rounded-xl p-3 mt-2"
          style={{ background: colors.surfaceSecondary,
                    border: `1px solid ${colors.divider}` }}
          data-testid="k79-descriptions-editor"
        >
          <div className="text-xs uppercase font-bold mb-2"
                style={{ color: colors.muted }}>
            Group descriptions (optional)
          </div>
          {groups.length === 0 ? (
            <div className="text-sm" style={{ color: colors.muted }}
                  data-testid="k79-empty-hint">
              Categorize line items to see group description editors.
            </div>
          ) : (
            <div className="space-y-3">
              {groups.map((g) => {
                const val = descriptions[g.id] || "";
                const len = val.length;
                return (
                  <div key={g.id} data-testid={`k79-desc-row-${g.id}`}>
                    <div className="text-xs font-semibold mb-1"
                          style={{ color: colors.onSurface }}>
                      {g.name}
                      <span className="ml-2 font-normal"
                              style={{ color: colors.muted }}>
                        {len}/{MAX_GROUP_DESC}
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <textarea
                        rows={2}
                        maxLength={MAX_GROUP_DESC}
                        value={val}
                        onChange={(e) => setDescriptions((prev) => ({
                          ...prev,
                          [g.id]: e.target.value,
                        }))}
                        placeholder={`Optional summary for the "${g.name}" group…`}
                        className="flex-1 px-2 py-1 text-sm rounded"
                        style={{ background: colors.surface,
                                  border: `1px solid ${colors.border}`,
                                  resize: "vertical" }}
                        data-testid={`k79-desc-input-${g.id}`}
                      />
                      <button
                        type="button"
                        onClick={() => persistDescription(g.id)}
                        disabled={savingKey === g.id}
                        className="px-2 py-1 text-xs rounded font-semibold disabled:opacity-50"
                        style={{ background: colors.brand,
                                  color: colors.onBrand || "#fff" }}
                        data-testid={`k79-desc-save-${g.id}`}
                      >
                        <SaveIcon size={12} className="inline" /> Save
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

      {error ? (
        <div className="mt-3 text-xs" style={{ color: "#B91C1C" }}
              data-testid="k79-error">
          {error}
        </div>
      ) : null}

      {previewOpen ? (
        <K79CustomerViewPreview
          doc={doc}
          serviceCategories={serviceCats}
          descriptions={descriptions}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}
    </div>
  );
}
