/**
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53) ·
 * ``show_if`` conditional-logic client-side evaluator.
 *
 * This is the browser-side mirror of the backend's
 * ``routers/marketing_forms.py::_is_field_visible`` helper. Keeping
 * them in two places with the same semantics means authors see the
 * SAME visibility decision on the admin preview surface, the public
 * widget, AND the server-side validation — no late surprises.
 *
 * Rule shape (matches the backend's Pydantic contract):
 *
 *   {
 *     field_id: "<id of another field on the same form>",
 *     operator: "eq" | "neq" | "contains",
 *     value:    <string | boolean | number | array>
 *   }
 *
 * Operator semantics (ALL coerced via ``coerceForCompare``):
 *   * eq       — parent answer == rule.value   (strings stripped;
 *                empty-after-strip collapses to null so empty-answer
 *                compares equal to never-answered-at-all)
 *   * neq      — parent answer != rule.value
 *   * contains — list/array parent: value is a member;
 *                string parent: value is a substring;
 *                anything else: false (defensive — malformed data
 *                does NOT fire the rule).
 *
 * Legacy forms (no ``show_if`` on any field) short-circuit to
 * ``true`` so pre-Phase-2 forms render byte-identical.
 */

/** @param {*} v */
export function coerceForCompare(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") {
    const s = v.trim();
    return s === "" ? null : s;
  }
  return v;
}

/**
 * Evaluate a field's ``show_if`` rule against the current answers.
 *
 * @param {Object} field       The field descriptor (must carry
 *                             ``show_if``, ``name``, ``id``).
 * @param {Object} answers     The current form answers keyed by
 *                             field ``name`` (widget-canonical).
 * @param {Object} fieldsById  Map of field_id -> field descriptor
 *                             for parent resolution.
 * @returns {boolean}          True if the field should render; false
 *                             if the rule evaluates false.
 */
export function isFieldVisible(field, answers, fieldsById) {
  if (!field) return true;
  const rule = field.show_if;
  if (!rule || typeof rule !== "object") return true;

  const parent = fieldsById && fieldsById[rule.field_id];
  if (!parent) {
    // Dangling at runtime (save-time validator should prevent this,
    // but defend pre-Phase-2 forms + manual DB edits).
    return true;
  }

  // Read the parent's current answer under its ``name`` first, then
  // fall back to ``id`` (widget may post either).
  let parentVal = parent.name && answers ? answers[parent.name] : undefined;
  if (parentVal === undefined) {
    parentVal = answers ? answers[rule.field_id] : undefined;
  }

  const op = rule.operator;
  const target = rule.value;
  const lhs = coerceForCompare(parentVal);
  const rhs = coerceForCompare(target);

  if (op === "eq") return lhs === rhs;
  if (op === "neq") return lhs !== rhs;
  if (op === "contains") {
    if (Array.isArray(parentVal)) {
      return parentVal.indexOf(target) !== -1;
    }
    if (typeof parentVal === "string" && typeof target === "string") {
      return parentVal.indexOf(target) !== -1;
    }
    return false;
  }
  // Unknown operator — save-time validator rejects these, so this
  // branch only fires on manually-crafted / corrupted docs.
  return true;
}

/**
 * Convenience helper for the submit path. Given the full field list
 * + the current answers, returns the ``answers`` object with hidden
 * fields' entries removed (both under ``name`` and ``id`` keys for
 * total parity with the backend's strip-before-persist behavior).
 *
 * @param {Array<Object>} fields  Form fields.
 * @param {Object} answers        Current answers (not mutated).
 * @returns {Object}              A shallow copy with hidden entries
 *                                removed.
 */
export function stripHiddenAnswers(fields, answers) {
  if (!Array.isArray(fields) || !fields.length) return { ...(answers || {}) };
  const fieldsById = {};
  fields.forEach((f) => { if (f && f.id) fieldsById[f.id] = f; });
  const out = { ...(answers || {}) };
  fields.forEach((f) => {
    if (!isFieldVisible(f, out, fieldsById)) {
      if (f.name) delete out[f.name];
      if (f.id) delete out[f.id];
    }
  });
  return out;
}
