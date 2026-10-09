// Phase 7C · Feb-2026 — Template field context.
//
// A tiny React Context + custom hook that lets any descendant of a
// ``<TemplateFieldProvider>`` look up the template style for a
// given ``field_id`` without threading the fields map through every
// component.
//
// Design keeps the ServiceReport / Estimate / Invoice edits small:
// the real pages wrap themselves in the provider at the top of the
// render, pass a ``templateFieldId`` prop down to each section-
// wrapper, and the wrapper reads the style from context + applies
// it via ``styleToCss``.  Any sub-tree WITHOUT a provider gets the
// empty sentinel and falls back to the legacy hardcoded layout.
import React, {
  createContext, useContext, useMemo,
} from "react";
import { styleToCss } from "@/lib/formStyle";


const _EMPTY_FIELDS = Object.freeze({});

const TemplateFieldContext = createContext(_EMPTY_FIELDS);


/**
 * Wraps a form render surface.  Provide ``fieldsById`` (keyed map
 * from the Phase 7A payload) and every descendant can call
 * ``useFieldStyle(fieldId)`` to read the template style.
 *
 * When ``fieldsById`` is empty (no template saved, 404, 5xx) the
 * provider is effectively a no-op — ``useFieldStyle`` returns null
 * so consumers fall through to their hardcoded style.
 */
export function TemplateFieldProvider({ fieldsById, children }) {
  const value = useMemo(() => fieldsById || _EMPTY_FIELDS, [fieldsById]);
  return (
    <TemplateFieldContext.Provider value={value}>
      {children}
    </TemplateFieldContext.Provider>
  );
}


/**
 * Returns the raw field dict for ``fieldId`` or ``null`` if the
 * current provider has no template loaded (or the field_id is
 * missing from the template — e.g. a renderer calls for a field
 * that doesn't exist on this form_type's seed).
 */
export function useFormTemplateField(fieldId) {
  const map = useContext(TemplateFieldContext);
  return map?.[fieldId] || null;
}


/**
 * Returns a CSS object spreadable into an inline ``style`` prop,
 * or ``null`` if no template style exists for this field_id.
 * ``null`` is the signal to fall back to the component's hardcoded
 * style.
 */
export function useFieldStyle(fieldId) {
  const field = useFormTemplateField(fieldId);
  return useMemo(() => {
    if (!field) return null;
    return styleToCss(field.style);
  }, [field]);
}


/**
 * Convenience hook for Phase 7C's ordered-section rendering:
 * returns the current provider's ordered field list for cases
 * where a caller wants to render fields in template order.
 * ``null`` when no provider is wrapping (ie. render legacy order).
 */
export function useFormTemplateOrder() {
  const map = useContext(TemplateFieldContext);
  return useMemo(() => {
    if (!map || map === _EMPTY_FIELDS) return null;
    const list = Object.values(map);
    if (list.length === 0) return null;
    return list
      .slice()
      .sort((a, b) => (Number(a?.order) || 0) - (Number(b?.order) || 0))
      .map((f) => f.field_id);
  }, [map]);
}


export default TemplateFieldProvider;
