// Phase 14B · Feb-2026 — Checklist item ordering helper.
//
// Follow-up 4 from the Phase 7 form-editor rollout. Reorders a
// service report's ``checklist_items`` array to match the order
// specified by the active form_template for
// ``job_checklist_pool`` / ``job_checklist_landscape`` /
// ``job_checklist_generic``.
//
// Mapping convention — CROSS-COLLECTION ID MISMATCH
// -------------------------------------------------
// Service report checklist items are stored as a flat list of
// labels (``POOL_CHECKLIST_DEFAULT`` at
// ``backend/routers/service_reports.py``) with no stable
// ``field_id``.  Form_template field_ids are of the shape
// ``chk_<slug>`` (manually assigned during the Phase 7A seed).
// Because the two collections don't share a stable identifier,
// Option A (template-order lookup) matches items by LABEL
// (case-insensitive, trimmed, exact string compare).
//
// Future-proofing: a cross-collection seed migration that stamps
// a stable ``field_id`` onto each checklist item is noted as a
// follow-up in /app/memory/known_issues.md; once shipped, this
// helper can swap the label-match for an id-match without
// changing its public API.
//
// Zero-regression contract:
//   * No template fields → return items unchanged (same reference
//     when possible to avoid React key churn).
//   * No label match for a service-report item → appended at end
//     of the ordered run (never silently dropped).
//   * Template field with no matching item → silently skipped.


function _labelKey(s) {
  return String(s || "").trim().toLowerCase();
}


/**
 * Reorder ``items`` (service-report checklist_items) using the
 * template-provided order.
 *
 * @param {Array} items          service-report checklist items.
 *                               Each item has {label, checked, id?}.
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

  const byLabel = new Map();
  for (const item of items) {
    const key = _labelKey(item?.label);
    if (!key) continue;
    if (!byLabel.has(key)) byLabel.set(key, []);
    byLabel.get(key).push(item);
  }

  const consumed = new Set();
  const ordered = [];
  for (const f of checklistFields) {
    const key = _labelKey(f?.label);
    const bucket = byLabel.get(key);
    if (!bucket || bucket.length === 0) continue;
    const next = bucket.shift();
    ordered.push(next);
    consumed.add(next);
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
