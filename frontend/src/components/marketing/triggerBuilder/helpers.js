/**
 * Feb 2026 · Phase 2 Custom Trigger Builder · helpers.
 *
 * Two pure functions consumed by ``TriggerBuilder`` and its child
 * components. Kept plain-JS (no JSX) so vitest can import them
 * without the JSDOM harness.
 */

// ─── Canonical entity ordering ─────────────────────────────────────
// Mirrors the ordering the backend uses in
// ``GET /marketing/sequences/event-catalog`` so the UI never fights
// the API's grouping.
export const ENTITY_ORDER = [
  "lead", "estimate", "job", "invoice", "payment", "customer",
];

export const ENTITY_LABELS = {
  lead: "Lead",
  estimate: "Estimate",
  job: "Job",
  invoice: "Invoice",
  payment: "Payment",
  customer: "Customer",
};


// ─── Empty-filter stripper ─────────────────────────────────────────
// The Phase-1 evaluator treats missing filter keys as "don't care"
// but treats explicitly-empty ones (``[]`` / ``""`` / ``null``) as
// "match nothing". We strip empty values from every condition before
// PATCHing so the saved sequence doesn't accidentally fail-closed
// on every match.
export function stripEmptyFilters(filters) {
  if (!filters || typeof filters !== "object") return {};
  const out = {};
  for (const [k, v] of Object.entries(filters)) {
    if (v === null || v === undefined) continue;
    if (Array.isArray(v)) {
      const cleaned = v.filter((x) => x !== null && x !== undefined && String(x).trim() !== "");
      if (cleaned.length > 0) out[k] = cleaned;
      continue;
    }
    if (typeof v === "string") {
      if (v.trim() !== "") out[k] = v.trim();
      continue;
    }
    // Numbers / booleans / nested objects (custom_fields specs).
    if (typeof v === "number" && !Number.isFinite(v)) continue;
    out[k] = v;
  }
  return out;
}


// ─── Trigger validator ─────────────────────────────────────────────
// Client-side gate for the Save button on the parent editor. Returns
// ``{ ok: true }`` when the trigger is coherent, ``{ ok: false, errors: [...] }``
// otherwise. Backend re-validates the same rules — this is a UX layer.
export function validateTrigger(trigger, eventCatalog = []) {
  const errors = [];
  if (!trigger || typeof trigger !== "object") {
    return { ok: false, errors: ["trigger missing"] };
  }
  const conds = trigger.conditions || [];
  if (!Array.isArray(conds) || conds.length === 0) {
    errors.push("Add at least one condition.");
  }
  const catalogById = new Map((eventCatalog || []).map((e) => [e.id, e]));
  for (let i = 0; i < conds.length; i += 1) {
    const c = conds[i] || {};
    if (!c.event) {
      errors.push(`Condition #${i + 1}: pick an event.`);
      continue;
    }
    const meta = catalogById.get(c.event);
    if (!meta && eventCatalog.length > 0) {
      errors.push(`Condition #${i + 1}: event "${c.event}" is not in the catalog.`);
    }
    const d = c.delay || { mode: "immediate" };
    if (d.mode === "after" || d.mode === "before") {
      const v = Number(d.value);
      if (!Number.isInteger(v) || v < 0) {
        errors.push(`Condition #${i + 1}: delay value must be a non-negative integer.`);
      }
      if (d.mode === "before" && meta && !meta.allow_negative_offset) {
        errors.push(
          `Condition #${i + 1}: event "${c.event}" does not support "before" delays.`,
        );
      }
    }
    if (d.mode === "on_weekday") {
      const wd = Number(d.weekday);
      if (!Number.isInteger(wd) || wd < 0 || wd > 6) {
        errors.push(`Condition #${i + 1}: weekday must be 0-6.`);
      }
      if (typeof d.time_local !== "string" || !/^\d{1,2}:\d{2}$/.test(d.time_local)) {
        errors.push(`Condition #${i + 1}: time_local must be HH:MM.`);
      }
    }
  }
  return errors.length > 0 ? { ok: false, errors } : { ok: true };
}


// ─── Save-shape builder ────────────────────────────────────────────
// Turn the UI's in-memory ``trigger`` state into the payload that
// PATCHes cleanly to /api/marketing/sequences/{sid}. Strips empty
// filters per-condition and normalises delay shapes.
export function buildTriggerPayload(trigger) {
  if (!trigger || typeof trigger !== "object") {
    return { logic: "AND", conditions: [] };
  }
  const logic = (trigger.logic || "AND").toUpperCase();
  const conditions = (trigger.conditions || []).map((c) => ({
    event: c.event || "",
    delay: normaliseDelay(c.delay),
    filters: stripEmptyFilters(c.filters || {}),
  }));
  return {
    logic: logic === "OR" ? "OR" : "AND",
    conditions,
  };
}


export function normaliseDelay(delay) {
  const d = delay || { mode: "immediate" };
  const mode = d.mode || "immediate";
  if (mode === "immediate") return { mode: "immediate" };
  if (mode === "after") {
    return {
      mode: "after",
      value: Number.isFinite(Number(d.value)) ? Number(d.value) : 0,
      unit: d.unit || "day",
    };
  }
  if (mode === "before") {
    return {
      mode: "before",
      value: Number.isFinite(Number(d.value)) ? Number(d.value) : 0,
    };
  }
  if (mode === "on_weekday") {
    return {
      mode: "on_weekday",
      weekday: Number.isFinite(Number(d.weekday)) ? Number(d.weekday) : 0,
      time_local: d.time_local || "09:00",
    };
  }
  return { mode: "immediate" };
}


// ─── LocalStorage draft persistence ────────────────────────────────
export const DRAFT_KEY = (sequenceId) => `sequence.${sequenceId || "new"}.draftTrigger`;

export function loadDraft(sequenceId) {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY(sequenceId));
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveDraft(sequenceId, trigger) {
  try {
    window.localStorage.setItem(
      DRAFT_KEY(sequenceId), JSON.stringify(trigger || {}),
    );
  } catch {
    /* quota / private-mode — silent */
  }
}

export function clearDraft(sequenceId) {
  try {
    window.localStorage.removeItem(DRAFT_KEY(sequenceId));
  } catch { /* noop */ }
}
