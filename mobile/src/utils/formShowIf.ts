/**
 * Form Builder conditional-logic evaluator — 1:1 PORT of web
 * `frontend/src/lib/formShowIf.js` (Phase 2, e8ccd0d36), which itself
 * mirrors backend `routers/marketing_forms.py::_is_field_visible`.
 * Same algorithm, same branches, same fail-open semantics — only TS
 * types added. Keep in lock-step with the web file.
 *
 *   - no `show_if` / non-object       → visible
 *   - parent field missing            → visible (fail-open)
 *   - lookup by parent.name, then by field_id
 *   - eq / neq on trimmed-string ("" → null) comparison
 *   - contains: array membership, or substring for strings; else false
 *   - unknown operator                → visible
 */
export type ShowIfRule = { field_id: string; operator: "eq" | "neq" | "contains" | string; value?: any };
export type FormField = { id?: string; name?: string; show_if?: ShowIfRule | null; [k: string]: any };

export function coerceForCompare(v: any): any {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") {
    const s = v.trim();
    return s === "" ? null : s;
  }
  return v;
}

export function isFieldVisible(
  field: FormField | null | undefined,
  answers: Record<string, any> | null | undefined,
  fieldsById: Record<string, FormField> | null | undefined,
): boolean {
  if (!field) return true;
  const rule = field.show_if;
  if (!rule || typeof rule !== "object") return true;
  const parent = fieldsById && fieldsById[rule.field_id];
  if (!parent) {
    return true;
  }
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
  return true;
}

export function stripHiddenAnswers(fields: FormField[], answers: Record<string, any>): Record<string, any> {
  if (!Array.isArray(fields) || !fields.length) return { ...(answers || {}) };
  const fieldsById: Record<string, FormField> = {};
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
