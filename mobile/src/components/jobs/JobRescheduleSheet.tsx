/**
 * TD-82 · Bulk "Reschedule to date…" sheet (absolute mode only — the
 * relative ±days/weeks shift is TD-82-relative-shift). Web uses sheet +
 * a second confirm modal; mobile folds the confirmation into Apply with a
 * summary line (operator T3). Date input mirrors RevenueDateRangeFilter:
 * text YYYY-MM-DD on web, native DateTimePicker elsewhere.
 */
import React, { useEffect, useState } from "react";
import { View, Text, Pressable, StyleSheet, Platform, ActivityIndicator } from "react-native";
import DateTimePicker from "@react-native-community/datetimepicker";
import { Sheet } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { isValidIsoDate, isoDate } from "@/src/lib/revenueRange";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/** "Tue, Nov 4, 2026" — noon anchor avoids TZ day-shift. */
export function friendlyDate(iso: string): string {
  if (!isValidIsoDate(iso)) return iso;
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

type Props = { visible: boolean; count: number; busy?: boolean; onApply: (isoDate: string) => void; onClose: () => void };

export default function JobRescheduleSheet({ visible, count, busy, onApply, onClose }: Props) {
  const [date, setDate] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  useEffect(() => { if (visible) { setDate(""); setPickerOpen(false); } }, [visible]);

  const valid = isValidIsoDate(date);
  const canApply = valid && count > 0 && !busy;
  const noun = `${count} job${count === 1 ? "" : "s"}`;

  return (
    <Sheet visible={visible} onClose={onClose} title="Reschedule to date" testID="bulk-reschedule-sheet">
      <View style={s.body}>
        <Text style={s.label}>New scheduled date</Text>
        {Platform.OS === "web" ? (
          <AppTextInput value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" style={s.input} testID="bulk-reschedule-datepicker" />
        ) : (
          <>
            <Pressable style={s.input} onPress={() => setPickerOpen((v) => !v)} testID="bulk-reschedule-datepicker">
              <Text style={[s.inputText, !date && { color: colors.muted }]}>{date || "Pick a date"}</Text>
            </Pressable>
            {pickerOpen ? (
              <DateTimePicker
                value={valid ? new Date(`${date}T12:00:00`) : new Date()} mode="date"
                display={Platform.OS === "ios" ? "inline" : "default"}
                onChange={(e: any, d?: Date) => {
                  if (Platform.OS !== "ios") setPickerOpen(false);
                  if (e?.type !== "dismissed" && d) setDate(isoDate(d));
                }}
              />
            ) : null}
          </>
        )}
        {date && !valid ? <Text style={s.err} testID="bulk-reschedule-invalid">Enter a valid date (YYYY-MM-DD).</Text> : null}
        <Text style={s.summary} testID="bulk-reschedule-summary">
          {valid ? `Move ${noun} to ${friendlyDate(date)}` : `Pick a date to move ${noun}.`}
        </Text>
        <Text style={s.hint}>Locked jobs (active timers or completed with an invoice) will be skipped.</Text>
        <View style={s.btns}>
          <Pressable style={s.cancel} onPress={onClose} testID="bulk-reschedule-cancel">
            <Text style={s.cancelText}>Cancel</Text>
          </Pressable>
          <Pressable
            style={[s.apply, !canApply && { opacity: 0.5 }]} disabled={!canApply} onPress={() => onApply(date)}
            accessibilityState={{ disabled: !canApply }} testID="bulk-reschedule-apply"
          >
            {busy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={s.applyText}>{`Reschedule ${count}`}</Text>}
          </Pressable>
        </View>
      </View>
    </Sheet>
  );
}

const s = StyleSheet.create({
  body: { paddingHorizontal: spacing.lg, paddingBottom: spacing.lg },
  label: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: 4 },
  input: { minHeight: 44, justifyContent: "center", borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, backgroundColor: colors.surface },
  inputText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  err: { marginTop: 4, fontFamily: font.medium, fontSize: 12, color: colors.error },
  summary: { marginTop: spacing.md, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  hint: { marginTop: 4, fontFamily: font.regular, fontSize: 12, color: colors.muted },
  btns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.lg },
  cancel: { minHeight: 44, paddingHorizontal: 16, justifyContent: "center", borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  cancelText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  apply: { minHeight: 44, minWidth: 120, paddingHorizontal: 16, alignItems: "center", justifyContent: "center", borderRadius: radius.md, backgroundColor: colors.brand },
  applyText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
