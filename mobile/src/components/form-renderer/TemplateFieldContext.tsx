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

export default TemplateFieldProvider;
