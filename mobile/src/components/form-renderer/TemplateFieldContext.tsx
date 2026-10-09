/**
 * Phase 7D · Form Template Runtime (mobile) — field context.
 * Port of web `frontend/src/components/form-renderer/TemplateFieldContext.jsx`.
 *
 *   <TemplateFieldProvider fieldsById={tpl.fieldsById}> … </TemplateFieldProvider>
 *   const { style, order, isLocked, hasTemplate } = useTemplateField("notes");
 *
 * `style` is the RN-mapped style (styleToRNStyle) or null when the field
 * is absent — consumers keep their hardcoded style when it is null.
 */
import React, { createContext, useContext, useMemo } from "react";
import { styleToRNStyle, RNFieldStyle } from "@/src/lib/formStyle";
import type { TemplateField } from "@/src/hooks/useFormTemplateRuntime";

const EMPTY_FIELDS: Record<string, TemplateField> = Object.freeze({}) as Record<string, TemplateField>;
const Ctx = createContext<Record<string, TemplateField>>(EMPTY_FIELDS);

export function TemplateFieldProvider({ fieldsById, children }: {
  fieldsById?: Record<string, TemplateField> | null;
  children: React.ReactNode;
}) {
  const value = useMemo(() => fieldsById || EMPTY_FIELDS, [fieldsById]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export type TemplateFieldInfo = {
  style: RNFieldStyle | null;
  order: number | null;
  isLocked: boolean;
  hasTemplate: boolean;
};

export function useTemplateField(fieldId?: string | null): TemplateFieldInfo {
  const map = useContext(Ctx);
  const field = fieldId ? map[fieldId] : undefined;
  return useMemo(() => ({
    style: field ? styleToRNStyle(field.style) : null,
    order: field && typeof field.order === "number" ? field.order : null,
    isLocked: !!field?.locked_reorder,
    hasTemplate: !!field,
  }), [field]);
}

/** Ordered field_ids, or null without a template (web `useFormTemplateOrder`). */
export function useFormTemplateOrder(): string[] | null {
  const map = useContext(Ctx);
  return useMemo(() => {
    const list = Object.values(map || {});
    if (list.length === 0) return null;
    return list.slice().sort((a, b) => (Number(a?.order) || 0) - (Number(b?.order) || 0)).map((f) => f.field_id);
  }, [map]);
}

/**
 * Phase 19 · Template-ordered section renderer (mobile parity with web
 * Phase 14A · d60c85630 ``TemplateOrderedSections``).
 *
 * Children carrying a ``templateFieldId`` prop are re-sequenced per the
 * active template order (``fieldsOrdered`` → ``useFormTemplateOrder``).
 * React.Children + prop inspection is renderer-agnostic, so the web
 * pattern ports to RN as-is.
 *
 * Zero-regression contract (same as web):
 *   * no provider / empty template (``isEmpty``) → source order, untouched
 *   * template field_id with no matching child → skipped
 *   * ordered child the template doesn't mention → appended after the
 *     ordered run
 *   * passthroughs (no ``templateFieldId``) before the first ordered
 *     child stay at the top; after the last ordered child → bottom
 * Mobile divergence: a passthrough BETWEEN two ordered children is
 * anchored to the ordered child that precedes it (e.g. the pool-only
 * "Visible Algae" card follows "Chemical Readings" wherever it moves).
 * Web's ServiceReport group has no mid-run passthroughs, so the
 * observable behavior is identical there.
 */
type Unit = { fid: string; nodes: React.ReactNode[] };

export function TemplateOrderedSections({ children }: { children: React.ReactNode }) {
  const order = useFormTemplateOrder();
  const flat = React.Children.toArray(children);
  if (!order || order.length === 0) return <>{flat}</>;

  const fidOf = (c: any): string | null => {
    const f = c?.props?.templateFieldId;
    return typeof f === "string" && f ? f : null;
  };
  const lastOrderedIdx = flat.reduce<number>((acc, c, i) => (fidOf(c) ? i : acc), -1);
  const head: React.ReactNode[] = [];
  const tail: React.ReactNode[] = [];
  const units: Unit[] = [];
  const seen = new Set<string>();
  flat.forEach((child, idx) => {
    const fid = fidOf(child);
    if (fid && !seen.has(fid)) {
      seen.add(fid);
      units.push({ fid, nodes: [child] });
    } else if (units.length === 0) {
      head.push(child);
    } else if (idx > lastOrderedIdx) {
      tail.push(child);
    } else {
      units[units.length - 1].nodes.push(child);
    }
  });
  const byFid = new Map(units.map((u) => [u.fid, u]));
  const out: React.ReactNode[] = [];
  for (const fid of order) {
    const u = byFid.get(fid);
    if (u) { out.push(...u.nodes); byFid.delete(fid); }
  }
  for (const u of units) if (byFid.has(u.fid)) out.push(...u.nodes);
  return <>{head}{out}{tail}</>;
}

export default TemplateFieldProvider;
