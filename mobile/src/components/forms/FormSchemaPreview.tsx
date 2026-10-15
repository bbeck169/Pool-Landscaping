/**
 * Read-only Form Builder schema preview (mobile parity, web Phase 1+2).
 *
 * Renders `fields[]` in `order`, applying the PORTED show_if evaluator
 * live: tapping a choice / typing sample data updates LOCAL answers only
 * so admins can see conditional fields appear / disappear. Nothing is
 * ever submitted or saved from here (edit-on-mobile deferred, TD-48).
 */
import React, { useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";

import AppTextInput from "@/src/components/ui/AppTextInput";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";
import { isFieldVisible, type FormField } from "@/src/utils/formShowIf";

const optLabel = (o: any) => (typeof o === "string" ? o : o?.label ?? o?.value ?? "");
const optValue = (o: any) => (typeof o === "string" ? o : o?.value ?? o?.label ?? "");
const keyOf = (f: FormField) => f.name || f.id || "";

export function orderedFields(fields: FormField[] = []): FormField[] {
  return fields
    .map((f, i) => ({ f, i }))
    .sort((a, b) => (a.f.order ?? a.i) - (b.f.order ?? b.i) || a.i - b.i)
    .map((x) => x.f);
}

function Chips({ field, value, multi, onChange }: { field: FormField; value: any; multi: boolean; onChange: (v: any) => void }) {
  const sel: any[] = multi ? (Array.isArray(value) ? value : []) : [value];
  return (
    <View style={s.chips}>
      {(field.options || []).map((o: any) => {
        const v = optValue(o);
        const on = sel.includes(v);
        const next = multi ? (on ? sel.filter((x) => x !== v) : [...sel, v]) : on ? undefined : v;
        return (
          <Pressable key={v} onPress={() => onChange(next)} style={[s.chip, on && s.chipOn]} testID={`form-preview-opt-${keyOf(field)}-${v}`}>
            <Text style={[s.chipText, on && s.chipTextOn]}>{optLabel(o)}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function FieldControl({ field, value, onChange }: { field: FormField; value: any; onChange: (v: any) => void }) {
  const t = field.type;
  if (t === "dropdown" || t === "radio") return <Chips field={field} value={value} multi={false} onChange={onChange} />;
  if (t === "multiselect" || (t === "checkbox" && (field.options || []).length)) return <Chips field={field} value={value} multi onChange={onChange} />;
  if (t === "checkbox") {
    return (
      <Pressable onPress={() => onChange(!value)} style={[s.chip, value && s.chipOn, { alignSelf: "flex-start" }]} testID={`form-preview-toggle-${keyOf(field)}`}>
        <Text style={[s.chipText, value && s.chipTextOn]}>{value ? "Checked" : "Unchecked"}</Text>
      </Pressable>
    );
  }
  if (t === "file") return <Text style={s.muted}>File upload (not available in preview)</Text>;
  return (
    <AppTextInput
      testID={`form-preview-input-${keyOf(field)}`}
      style={[s.input, t === "textarea" && { minHeight: 72, textAlignVertical: "top" }]}
      value={value ?? ""}
      onChangeText={onChange}
      placeholder={field.placeholder || ""}
      placeholderTextColor={colors.muted}
      multiline={t === "textarea"}
      keyboardType={t === "number" ? "decimal-pad" : t === "email" ? "email-address" : t === "phone" ? "phone-pad" : "default"}
      autoCapitalize={t === "email" || t === "url" ? "none" : "sentences"}
    />
  );
}

export default function FormSchemaPreview({ fields, submitLabel }: { fields: FormField[]; submitLabel?: string }) {
  const [answers, setAnswers] = useState<Record<string, any>>({});
  const ordered = useMemo(() => orderedFields(fields), [fields]);
  const byId = useMemo(() => Object.fromEntries(ordered.filter((f) => f.id).map((f) => [f.id as string, f])), [ordered]);
  const visible = ordered.filter((f) => isFieldVisible(f, answers, byId));
  const hidden = ordered.length - visible.length;

  if (!ordered.length) return <Text style={s.muted} testID="form-preview-empty">This form has no fields yet.</Text>;
  return (
    <View testID="form-preview">
      <Text style={s.banner}>Preview only — sample answers stay on this device and are never submitted.</Text>
      {visible.map((f) => (
        <View key={f.id || f.name} style={s.field} testID={`form-preview-field-${keyOf(f)}`}>
          <View style={s.labelRow}>
            <Text style={s.label}>{f.label || f.name}{f.required ? " *" : ""}</Text>
            {f.show_if ? <Text style={s.cond} testID={`form-preview-conditional-${keyOf(f)}`}>Conditional</Text> : null}
          </View>
          <FieldControl field={f} value={answers[keyOf(f)]} onChange={(v) => setAnswers((a) => ({ ...a, [keyOf(f)]: v }))} />
        </View>
      ))}
      {hidden > 0 ? (
        <Text style={s.muted} testID="form-preview-hidden-count">
          {hidden} field{hidden === 1 ? "" : "s"} hidden by conditional logic
        </Text>
      ) : null}
      <View style={s.submit}><Text style={s.submitText}>{submitLabel || "Submit"}</Text></View>
    </View>
  );
}

const s = StyleSheet.create({
  banner: { fontFamily: font.medium, fontSize: 12, color: "#92400E", backgroundColor: "#FEF3C7", borderRadius: radius.sm, padding: spacing.sm, marginBottom: spacing.md },
  field: { marginBottom: spacing.md },
  labelRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 4 },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  cond: { fontFamily: font.bold, fontSize: 9, color: "#6D28D9", backgroundColor: "#EDE9FE", paddingHorizontal: 6, paddingVertical: 1, borderRadius: 4, letterSpacing: 0.4 },
  input: { minHeight: 44, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, paddingHorizontal: spacing.md, backgroundColor: colors.surface, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: { minHeight: 36, justifyContent: "center", paddingHorizontal: 12, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.medium, fontSize: 13, color: colors.onSurface },
  chipTextOn: { color: "#fff" },
  muted: { fontFamily: font.regular, fontSize: 12, color: colors.muted, marginBottom: spacing.sm },
  submit: { minHeight: 44, borderRadius: radius.sm, backgroundColor: colors.border, alignItems: "center", justifyContent: "center", marginTop: spacing.sm },
  submitText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
});
