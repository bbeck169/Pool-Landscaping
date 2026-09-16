// Phase MI1 · Feb 2026 — Multi-industry checklist renderer.
// Phase MI1.1 · Feb 2026 — prop signature aligned with the
// ``ChecklistModal`` call site so this drops in as a direct
// replacement for the historic ``<GenericChecklistForm>`` for the
// five new industries (hvac / pest_control / cleaning / solar /
// handyman).
//
// Dispatches by ``industry``:
//   * ``pool``  → the historical ``PoolChecklistForm`` (untouched).
//   * anything else → a lightweight generic renderer that lists the
//     resolved template items with a checkbox each, required items
//     flagged with a red asterisk. A free-form Notes textarea sits
//     below the list — matches the ``GenericChecklistForm`` UX so
//     techs don't lose the ability to leave a comment on a
//     non-Pool visit.
//
// Design intent: Pool tenants get byte-identical UX vs pre-MI1.
// Non-pool industries get a fit-for-purpose checkbox list right now;
// heavier per-industry surfaces (chemistry-style panels for solar
// output, HVAC pressure readings, etc.) land in Phase D.
//
// The old ``PoolChecklistForm`` file stays authoritative for the
// pool experience — the file rename in the brief was deliberately
// skipped to avoid touching the 1000+ line component (and its
// 20+ source-scanning tests). This wrapper satisfies the same
// "one component, industry prop" contract without the risky
// rename.
import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/api";
import { colors } from "@/theme";
import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";

export const INDUSTRY_LABELS = {
  pool: "Pool",
  landscaping: "Landscaping",
  hvac: "HVAC",
  pest_control: "Pest Control",
  cleaning: "Cleaning",
  solar: "Solar",
  handyman: "Handyman",
};


// Fold the tenant-agnostic template items with the report's
// persisted ``checklist_items`` so:
//   * order + labels come from the template (admin-controlled)
//   * ``checked`` + ``id`` + ``notes`` come from the report when
//     already present (preserves in-flight state on re-render)
function mergeTemplateAndReport(templateItems, reportItems) {
  const byKey = new Map();
  (reportItems || []).forEach((r) => {
    const k = String(r.key || r.label || "").toLowerCase();
    if (k) byKey.set(k, r);
  });
  return (templateItems || []).map((t, idx) => {
    const k = String(t.key || t.label || "").toLowerCase();
    const prev = byKey.get(k) || byKey.get(String(t.label || "").toLowerCase());
    return {
      id: prev?.id || t.key || `item-${idx}`,
      key: t.key,
      label: t.label,
      required: !!t.required,
      checked: !!prev?.checked,
      notes: prev?.notes || "",
      // Phase D4 · Feb 2026 — carry the locale metadata forward
      // so the row-level "translation pending" badge can render.
      label_en: t.label_en,
      label_i18n_available: t.label_i18n_available,
    };
  });
}


function GenericIndustryChecklistBody({
  industry, template, checklistItems, notes, locked, onChange,
}) {
  // Phase D3 · Feb 2026 — pull namespaces for the shell strings +
  // industry display name. Row labels remain from the template
  // (Phase D4 will translate those).
  const { t, i18n } = useTranslation(["checklist", "industries", "common"]);
  const items = template?.items || [];
  const merged = useMemo(
    () => mergeTemplateAndReport(items, checklistItems),
    [items, checklistItems],
  );

  const toggle = (idx) => {
    if (locked) return;
    const next = merged.map(
      (row, i) => (i === idx ? { ...row, checked: !row.checked } : row),
    );
    onChange && onChange({ checklist_items: next });
  };

  const setNote = (idx, note) => {
    if (locked) return;
    const next = merged.map(
      (row, i) => (i === idx ? { ...row, notes: note } : row),
    );
    onChange && onChange({ checklist_items: next });
  };

  if (!items.length) {
    return (
      <div className="text-sm p-4 rounded-lg"
           style={{ color: colors.muted, background: colors.surfaceSecondary }}
           data-testid="industry-checklist-empty">
        {t("checklist:no_template_found")}
      </div>
    );
  }

  const industryLabel = t(`industries:${industry}`, {
    defaultValue: INDUSTRY_LABELS[industry] || t("common:checklist"),
  });

  return (
    <div data-testid={`industry-checklist-${industry}`} className="space-y-4">
      <div>
        <div className="text-sm font-bold mb-2"
              style={{ color: colors.onSurface }}
              data-testid={`industry-checklist-title-${industry}`}>
          {industryLabel}
        </div>
        <div className="space-y-2">
          {merged.map((row, idx) => (
            <div
              key={row.id}
              className="p-2 rounded-md"
              style={{
                border: `1px solid ${row.checked ? "#059669" : colors.border}`,
                background: row.checked ? "#D1FAE5" : colors.surface,
              }}
              data-testid={`industry-check-${row.key}`}
            >
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  disabled={!!locked}
                  checked={!!row.checked}
                  onChange={() => toggle(idx)}
                  data-testid={`industry-check-toggle-${row.key}`}
                />
                <span className="text-sm" style={{ color: colors.onSurface }}>
                  {row.label}
                  {row.required ? (
                    <span className="ml-1" style={{ color: "#DC2626" }}
                          aria-label={t("checklist:required_asterisk_tooltip")}
                          title={t("checklist:required_asterisk_tooltip")}>*</span>
                  ) : null}
                  {/* Phase D4 · translation-pending indicator. Server
                      returns ``label_i18n_available`` per row — when
                      the active locale isn't in that list, show a
                      subtle badge with the English source in the
                      tooltip so techs can cross-check. */}
                  {row.label_i18n_available
                    && !row.label_i18n_available.includes(
                      (i18n.language || "en").slice(0, 2),
                    ) ? (
                    <span
                      className="ml-1 inline-flex items-center justify-center rounded-full text-[9px] font-bold"
                      style={{
                        color: "#B45309", background: "#FEF3C7",
                        padding: "0px 5px", verticalAlign: "middle",
                      }}
                      title={
                        t("checklist:translation_pending_tooltip")
                        + (row.label_en ? ` · EN: ${row.label_en}` : "")
                      }
                      aria-label={t("checklist:translation_pending_tooltip")}
                      data-testid={`industry-check-translation-pending-${row.key}`}
                    >
                      {t("checklist:translation_pending")}
                    </span>
                  ) : null}
                </span>
              </label>
              {row.checked && !locked ? (
                <input
                  value={row.notes || ""}
                  placeholder={t("common:optional")}
                  onChange={(e) => setNote(idx, e.target.value)}
                  className="w-full mt-2 px-2 py-1 rounded text-xs"
                  style={{ border: `1px solid ${colors.border}` }}
                  data-testid={`industry-check-note-${row.key}`}
                />
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div>
        <div className="text-sm font-bold mb-2"
              style={{ color: colors.onSurface }}>
          {t("common:notes")}
        </div>
        <textarea
          rows={3}
          disabled={!!locked}
          value={notes || ""}
          onChange={(e) => onChange && onChange({ notes: e.target.value })}
          placeholder={t("checklist:notes_placeholder")}
          className="w-full px-2 py-1.5 rounded-md text-sm"
          style={{
            border: `1px solid ${colors.border}`,
            background: locked ? colors.surfaceSecondary : colors.surface,
            color: colors.onSurface,
            resize: "vertical",
          }}
          data-testid={`industry-checklist-notes-${industry}`}
        />
      </div>
    </div>
  );
}


export default function IndustryChecklistForm({
  industry = "pool",
  tenantId,
  // ChecklistModal-style props ---------------------------------
  locked,
  checklistItems,
  notes,
  onChange,
  // Legacy MI1 props (kept for callers that render outside the
  // report flow) ---------------------------------------------------
  value,
  poolProps,
}) {
  // Hooks must run unconditionally per React rules. We fetch the
  // template even on the pool branch (the request short-circuits
  // in the effect below) so the hook order stays stable across
  // industry switches.
  const [template, setTemplate] = useState(null);
  const [error, setError] = useState("");
  const { i18n } = useTranslation();
  useEffect(() => {
    if (industry === "pool") { setTemplate(null); setError(""); return; }
    let cancelled = false;
    setError(""); setTemplate(null);
    // Phase D4 · Feb 2026 — pass the active locale explicitly so a
    // tech who toggled the D3 language selector sees translated
    // rows immediately without re-logging in. Belt-and-suspenders
    // with the ``user.locale`` fallback the backend also honours.
    const loc = (i18n.language || "en").slice(0, 2);
    const qs = loc ? `?locale=${encodeURIComponent(loc)}` : "";
    api.get(`/checklists/industry/${industry}${qs}`)
      .then((body) => { if (!cancelled) setTemplate(body); })
      .catch((e) => { if (!cancelled) setError(e?.message || "Failed to load"); });
    return () => { cancelled = true; };
  }, [industry, tenantId, i18n.language]);

  // Pool → delegate to the untouched historical component so
  // pool tenants keep the full chemistry UX.
  if (industry === "pool") {
    return <PoolChecklistForm {...(poolProps || {})} />;
  }

  if (error) {
    return (
      <div className="text-sm p-3 rounded-lg"
           style={{ color: "#991B1B", background: "#FEE2E2" }}
           data-testid="industry-checklist-error">
        {error}
      </div>
    );
  }
  if (!template) {
    return (
      <div className="text-sm p-3" style={{ color: colors.muted }}
           data-testid="industry-checklist-loading">Loading…</div>
    );
  }

  // Legacy caller shape → array of items via ``value``, patch-based
  // ``onChange`` returning the array. Wrap so the generic renderer
  // still works.
  const effectiveItems =
    checklistItems !== undefined ? checklistItems : (value || []);
  const effectiveOnChange = (patch) => {
    if (!onChange) return;
    // Modal-style callers get the patch object verbatim; legacy
    // callers get the checklist_items array unwrapped so their
    // existing ``value`` state slot stays a bare array.
    if (checklistItems !== undefined) onChange(patch);
    else onChange(patch?.checklist_items ?? []);
  };

  return (
    <GenericIndustryChecklistBody
      industry={industry}
      template={template}
      checklistItems={effectiveItems}
      notes={notes}
      locked={locked}
      onChange={effectiveOnChange}
    />
  );
}
