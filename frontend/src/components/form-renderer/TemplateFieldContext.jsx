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


/**
 * Phase 14A · Feb-2026 — Template-ordered section renderer.
 *
 * Wraps a list of React children whose top-level props carry a
 * ``templateFieldId``. Reorders them per the active
 * ``useFormTemplateOrder()`` lookup.
 *
 * Zero-regression contract:
 *   * No active provider (or empty template) → children render in
 *     their original source order (byte-for-byte legacy layout).
 *   * Children without a ``templateFieldId`` prop are passed
 *     through at their source position (header blocks, bottom
 *     submit buttons, etc. — any mix of ordered + unordered
 *     children is handled).
 *   * Template field_ids with no matching child are silently
 *     skipped (template references a field the current page
 *     doesn't render — e.g. ``signature`` on a landscape report
 *     that doesn't ship one yet).
 *   * Children present in the page but absent from the template
 *     are appended at the end of the ordered run so no renderable
 *     section vanishes silently.
 */
export function TemplateOrderedSections({ children }) {
  const order = useFormTemplateOrder();
  const flat = React.Children.toArray(children)
    .filter((c) => c !== false && c != null && c !== "");
  if (!order || order.length === 0) {
    return <>{flat}</>;
  }
  // Partition into (ordered, passthrough). Passthroughs render at
  // their original index; ordered children get repositioned.
  const byFieldId = new Map();
  const passthroughPositions = [];
  flat.forEach((child, idx) => {
    const fid = child?.props?.templateFieldId;
    if (fid && !byFieldId.has(fid)) {
      byFieldId.set(fid, child);
    } else {
      passthroughPositions.push({ child, idx });
    }
  });
  const output = [];
  for (const fid of order) {
    const c = byFieldId.get(fid);
    if (c) {
      output.push(c);
      byFieldId.delete(fid);
    }
  }
  // Append any renderable sections the template didn't mention so
  // the page never silently loses content.
  for (const [, c] of byFieldId.entries()) {
    output.push(c);
  }
  // Re-insert passthroughs in approximately their source position.
  // Simple strategy: anything originally before the first ordered
  // child stays at the top; everything else goes at the bottom.
  const firstOrderedIdx = flat.findIndex(
    (c) => c?.props?.templateFieldId,
  );
  const before = [];
  const after = [];
  for (const { child, idx } of passthroughPositions) {
    if (firstOrderedIdx === -1 || idx < firstOrderedIdx) {
      before.push(child);
    } else {
      after.push(child);
    }
  }
  return <>{before}{output}{after}</>;
}


export default TemplateFieldProvider;
