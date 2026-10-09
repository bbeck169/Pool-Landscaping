// Phase 14B · Feb-2026 — Checklist item ordering helper.
//
// Follow-up 4 from the Phase 7 form-editor rollout. Reorders a
// service report's ``checklist_items`` array to match the order
// specified by the active form_template for
// ``job_checklist_pool`` / ``job_checklist_landscape`` /
// ``job_checklist_generic``.
//
// Phase 17 · Feb-2026 — Cross-collection field_id convention.
// Checklist items in ``industry_checklist_templates`` and
// ``tenant_checklist_overrides`` are now stamped with a stable
// ``field_id`` by the Phase 17 migration + write-path upsert.
// This helper now matches on ``field_id`` FIRST and falls back
// to label-match for backwards compatibility with:
//
//   * Pre-migration tenants (field_id absent)
//   * Items coming from the Phase 7A form_templates seed whose
//     field_ids are hand-curated keywords (e.g. ``chk_skim_
//     surface``) rather than mechanical slugs; the migrated
//     service_report side carries a mechanical slug which won't
//     id-match the curated seed id. Label-match bridges the gap.
//
// Public API unchanged per the Phase 14 commitment — signature +
// return shape identical.
//
// Zero-regression contract:
//   * No template fields → return items unchanged (same reference
//     when possible to avoid React key churn).
//   * No match (id or label) for a service-report item → appended
//     at end of the ordered run.
//   * Template field with no matching item → silently skipped.


function _labelKey(s) {
  return String(s || "").trim().toLowerCase();
}


/**
 * Reorder ``items`` (service-report checklist_items) using the
 * template-provided order.
 *
 * @param {Array} items          service-report checklist items.
 *                               Each item has {label, checked, id?,
 *                               field_id?}.
 * @param {Array} templateFields fieldsOrdered from
 *                               useFormTemplateRuntime(form_type).
 *                               Each has {field_id, label, order}.
 * @returns {Array}              reordered items (new array when
 *                               reordering happened, same ref when
 *                               no reorder was needed).
 */
export function orderChecklistByTemplate(items, templateFields) {
  if (!Array.isArray(items) || items.length === 0) return items;
  if (!Array.isArray(templateFields) || templateFields.length === 0) {
    return items;
  }
  // Only consider checklist (``chk_*``) template fields — the
  // form_template may also carry non-checklist fields (``notes``,
  // ``signature``) that must NOT reorder item list entries.
  const checklistFields = templateFields.filter(
    (f) => typeof f?.field_id === "string"
      && f.field_id.startsWith("chk_"),
  );
  if (checklistFields.length === 0) return items;

  // Phase 17 · build BOTH id→item and label→item maps so the
  // match pass can try id first, then fall back to label.
  const byFieldId = new Map();
  const byLabel = new Map();
  for (const item of items) {
    const fid = typeof item?.field_id === "string"
      ? item.field_id : "";
    if (fid) {
      if (!byFieldId.has(fid)) byFieldId.set(fid, []);
      byFieldId.get(fid).push(item);
    }
    const key = _labelKey(item?.label);
    if (key) {
      if (!byLabel.has(key)) byLabel.set(key, []);
      byLabel.get(key).push(item);
    }
  }

  const consumed = new Set();
  const ordered = [];
  for (const f of checklistFields) {
    // Prefer id-match.
    let bucket = byFieldId.get(f?.field_id);
    let next = null;
    while (bucket && bucket.length) {
      const cand = bucket.shift();
      if (!consumed.has(cand)) { next = cand; break; }
    }
    // Fall back to label-match for pre-migration items / seed
    // id-mismatches.
    if (!next) {
      const lbucket = byLabel.get(_labelKey(f?.label));
      while (lbucket && lbucket.length) {
        const cand = lbucket.shift();
        if (!consumed.has(cand)) { next = cand; break; }
      }
    }
    if (next) {
      ordered.push(next);
      consumed.add(next);
    }
  }
  // Append any items the template didn't mention, preserving
  // their original relative order.
  for (const item of items) {
    if (!consumed.has(item)) ordered.push(item);
  }
  // Short-circuit when no actual reorder happened (saves React a
  // re-render through downstream memo boundaries).
  let same = ordered.length === items.length;
  if (same) {
    for (let i = 0; i < items.length; i += 1) {
      if (ordered[i] !== items[i]) { same = false; break; }
    }
  }
  return same ? items : ordered;
}


/**
 * Resolve the matching ``form_type`` from a service-report
 * ``kind`` (``pool`` / ``landscape`` / ``generic``). Mirrors the
 * backend seed naming.
 */
export function checklistFormTypeFor(kind) {
  if (kind === "landscape") return "job_checklist_landscape";
  if (kind === "generic") return "job_checklist_generic";
  return "job_checklist_pool";
}
