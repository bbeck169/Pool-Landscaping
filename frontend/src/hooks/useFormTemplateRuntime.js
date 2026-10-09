// Phase 7C · Feb-2026 — Runtime form-template loader hook.
//
// Fetches ``GET /api/form-templates/{form_type}`` once per
// ``form_type`` per browser session and surfaces the fields in two
// shapes:
//
//   * ``fieldsById[field_id]`` → the raw field dict
//   * ``fieldsOrdered``        → fields sorted by ``.order``
//
// FALLBACK CONTRACT (zero-regression):
//   Any failure (null form_type, fetch rejection, 4xx/5xx, non-dict
//   response, missing ``fields`` array) returns the EMPTY sentinel:
//
//       { fieldsById: {}, fieldsOrdered: [], isLoading: false,
//         error: <truthy if the fetch failed>, isEmpty: true }
//
//   Consumers MUST interpret ``isEmpty: true`` as "no template is
//   configured — render the hardcoded legacy layout untouched".
//   This guarantees every tenant without a saved template sees
//   zero behavior change relative to pre-Phase-7C.
//
// Caching: module-scope promise + resolved-value map, same pattern
// as ``hooks/useTenantBrand`` — one GET per form_type for the life
// of the page.  ``invalidateFormTemplateRuntime(form_type?)`` is
// exported for the Phase 7B editor to call after a Save / Revert
// so a tech viewing the live form in another tab picks up the new
// template on next mount (we can't push into other tabs without a
// websocket; a reload grabs the fresh copy).
import { useEffect, useState } from "react";
import { api } from "@/api";


const _cache    = new Map();   // form_type → resolved template
const _inflight = new Map();   // form_type → promise (dedupe parallel mounts)


const _EMPTY = Object.freeze({
  fieldsById: Object.freeze({}),
  fieldsOrdered: Object.freeze([]),
  isLoading: false,
  error: null,
  isEmpty: true,
  version: null,
});


function _normalize(body) {
  if (!body || typeof body !== "object") return null;
  const fields = Array.isArray(body.fields) ? body.fields : null;
  if (!fields || fields.length === 0) return null;
  const byId = {};
  for (const f of fields) {
    if (f && typeof f === "object" && typeof f.field_id === "string") {
      byId[f.field_id] = f;
    }
  }
  const ordered = [...fields].sort((a, b) => (
    (Number(a?.order) || 0) - (Number(b?.order) || 0)
  ));
  return {
    fieldsById: byId,
    fieldsOrdered: ordered,
    version: typeof body.version === "number" ? body.version : null,
    isLoading: false,
    error: null,
    isEmpty: false,
  };
}


function _fetchOnce(formType) {
  if (_cache.has(formType)) {
    return Promise.resolve(_cache.get(formType));
  }
  if (_inflight.has(formType)) {
    return _inflight.get(formType);
  }
  const p = Promise.resolve()
    .then(() => {
      try { return api.get(`/form-templates/${formType}`); }
      catch { return null; }
    })
    .then((body) => {
      const norm = _normalize(body);
      // Store the normalised shape OR the empty sentinel keyed by
      // form_type so a 404 doesn't trigger a retry storm on every
      // mount — a tenant without a saved template is a stable
      // state until they open the Phase 7B editor.
      const stored = norm || { ..._EMPTY, error: null };
      _cache.set(formType, stored);
      _inflight.delete(formType);
      return stored;
    })
    .catch(() => {
      const stored = { ..._EMPTY, error: "fetch_failed" };
      _cache.set(formType, stored);
      _inflight.delete(formType);
      return stored;
    });
  _inflight.set(formType, p);
  return p;
}


export function invalidateFormTemplateRuntime(formType) {
  if (!formType) {
    _cache.clear();
    _inflight.clear();
    return;
  }
  _cache.delete(formType);
  _inflight.delete(formType);
}


export function useFormTemplateRuntime(formType) {
  const [state, setState] = useState(() => {
    if (!formType) return _EMPTY;
    if (_cache.has(formType)) return _cache.get(formType);
    return { ..._EMPTY, isLoading: true };
  });

  useEffect(() => {
    if (!formType) {
      setState(_EMPTY);
      return undefined;
    }
    if (_cache.has(formType)) {
      setState(_cache.get(formType));
      return undefined;
    }
    let alive = true;
    setState({ ..._EMPTY, isLoading: true });
    _fetchOnce(formType).then((body) => {
      if (!alive) return;
      setState(body);
    });
    return () => { alive = false; };
  }, [formType]);

  return state;
}


// Phase 7D will mirror this module in ``/app/mobile/src/hooks/``
// using the same cache / sentinel semantics so the mobile forms
// pick up the admin's edits without a second round-trip model.
