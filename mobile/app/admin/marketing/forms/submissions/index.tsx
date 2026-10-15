/**
 * Form submissions inbox (read-only) — mobile parity for web
 * MarketingFormsPage submissions view. No cross-form endpoint exists,
 * so "All forms" fans out (bounded) to forms with submission_count > 0.
 * Filters: form chips + date range (All / 7d / 30d, client-side).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, Pressable, ScrollView, RefreshControl, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";

import { Header } from "@/src/components/widgets";
import CommsAdminGate, { MARKETING_FORMS_ROLES } from "@/src/components/comms/CommsAdminGate";
import { listForms, listFormSubmissions, type FormSubmission, type MarketingForm } from "@/src/api/marketingForms";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";
import { ALL_FORMS_FANOUT_CAP, inRange, summaryLine, destinationLabel, type Range } from "@/src/utils/formSubmissions";

export default function FormSubmissionsScreen() {
  return (
    <CommsAdminGate title="Form Submissions" roles={MARKETING_FORMS_ROLES}>
      <InboxBody />
    </CommsAdminGate>
  );
}

function Chip({ label, on, onPress, testID }: { label: string; on: boolean; onPress: () => void; testID: string }) {
  return (
    <Pressable onPress={onPress} style={[s.chip, on && s.chipOn]} testID={testID}>
      <Text style={[s.chipText, on && s.chipTextOn]} numberOfLines={1}>{label}</Text>
    </Pressable>
  );
}

function InboxBody() {
  const params = useLocalSearchParams<{ fid?: string }>();
  const router = useRouter();
  const [forms, setForms] = useState<MarketingForm[] | null>(null);
  const [fid, setFid] = useState<string | null>(params.fid ? String(params.fid) : null);
  const [range, setRange] = useState<Range>("all");
  const [rows, setRows] = useState<FormSubmission[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => { listForms().then(setForms).catch(() => setForms([])); }, []);

  // Per-form fetch must not re-fire when the forms list arrives.
  const formsKey = fid ? null : forms;
  const load = useCallback(async () => {
    setErr(null);
    try {
      if (fid) {
        setRows(await listFormSubmissions(fid));
        return;
      }
      const targets = (formsKey || []).filter((f) => (f.submission_count || 0) > 0).slice(0, ALL_FORMS_FANOUT_CAP);
      const lists = await Promise.all(targets.map((f) => listFormSubmissions(f.id, 50).catch(() => [])));
      setRows(lists.flat().sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))));
    } catch (e: any) {
      setErr(e?.message || "Couldn't load submissions.");
      setRows([]);
    }
  }, [fid, formsKey]);
  useEffect(() => { if (fid || formsKey !== null) load(); }, [fid, formsKey, load]);

  const visible = useMemo(() => (rows || []).filter((r) => inRange(r.created_at, range)), [rows, range]);
  const formChips = (forms || []).filter((f) => (f.submission_count || 0) > 0 || f.id === fid);

  return (
    <View style={s.root} testID="form-submissions-screen">
      <Header title="Form Submissions" subtitle="Read-only inbox" back />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chipRow} style={{ flexGrow: 0 }}>
        <Chip label="All forms" on={!fid} onPress={() => { setRows(null); setFid(null); }} testID="form-subs-filter-all" />
        {formChips.map((f) => (
          <Chip key={f.id} label={f.name} on={fid === f.id} onPress={() => { setRows(null); setFid(f.id); }} testID={`form-subs-filter-${f.id}`} />
        ))}
      </ScrollView>
      <View style={s.chipRow}>
        {(["all", "7d", "30d"] as Range[]).map((r) => (
          <Chip key={r} label={r === "all" ? "Any date" : r === "7d" ? "Last 7 days" : "Last 30 days"} on={range === r} onPress={() => setRange(r)} testID={`form-subs-range-${r}`} />
        ))}
      </View>
      {rows === null ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} testID="form-subs-loader" />
      ) : (
        <FlatList
          data={visible}
          keyExtractor={(r) => r.id}
          contentContainerStyle={{ padding: spacing.lg, gap: spacing.sm }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
          ListHeaderComponent={err ? <Text style={s.err} testID="form-subs-error">{err}</Text> : null}
          ListEmptyComponent={!err ? <Text style={s.empty} testID="form-subs-empty">No submissions match these filters.</Text> : null}
          renderItem={({ item }) => {
            const dest = destinationLabel(item);
            return (
              <Pressable
                style={s.row}
                testID={`form-sub-row-${item.id}`}
                onPress={() => router.push({ pathname: "/admin/marketing/forms/submissions/[sid]", params: { sid: item.id, fid: item.form_id } } as any)}
              >
                <View style={s.rowTop}>
                  <Text style={s.formName} numberOfLines={1}>{item.form_name || "Form"}</Text>
                  <Text style={s.when}>{item.created_at ? new Date(item.created_at).toLocaleString() : ""}</Text>
                </View>
                <Text style={s.summary} numberOfLines={1}>{summaryLine(item)}</Text>
                {dest ? <Text style={s.dest} testID={`form-sub-dest-${item.id}`}>→ {dest}</Text> : null}
              </Pressable>
            );
          }}
        />
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  chipRow: { flexDirection: "row", gap: 6, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  chip: { minHeight: 34, maxWidth: 200, justifyContent: "center", paddingHorizontal: 12, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.medium, fontSize: 12, color: colors.onSurface },
  chipTextOn: { color: "#fff" },
  row: { padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary },
  rowTop: { flexDirection: "row", justifyContent: "space-between", gap: spacing.sm },
  formName: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  when: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  summary: { fontFamily: font.regular, fontSize: 13, color: colors.onSurface, marginTop: 4 },
  dest: { fontFamily: font.semibold, fontSize: 11, color: "#065F46", marginTop: 4 },
  err: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error },
  empty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center", marginTop: 40 },
});
