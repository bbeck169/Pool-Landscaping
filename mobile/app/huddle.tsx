/**
 * Phase 16B · Technician daily huddle entry.
 * yesterday / today / blockers → posts to /api/huddles + huddles/{id}/action-items
 */
import React, { useState, useEffect } from "react";
import { View, Text, StyleSheet, Pressable, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { todayKeyInTenantTz } from "@/src/utils/tenantTime";
// Phase 38 · Feb-2026 · Phase 30.4 completeness — replaced legacy
// `Alert.alert` (silently fails on user's Android/Expo Go build) with
// an inline status banner (no new dep).

export default function HuddleScreen() {
  const { user } = useAuth();
  const today = todayKeyInTenantTz();
  const [yesterday, setYesterday] = useState("");
  const [todayText, setTodayText] = useState("");
  const [blockers, setBlockers] = useState("");
  const [huddle, setHuddle] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [recentSops, setRecentSops] = useState<any[]>([]);
  const [statusMsg, setStatusMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    // Best-effort: check if today's huddle already exists.
    // ``today`` is derived from ``new Date()`` at render time. Running
    // this effect once on mount is intentional — we don't want to
    // refetch mid-session if the render clock happens to tick over.
    (async () => {
      try {
        const rows = await api.get("/huddles");
        const found = (rows || []).find((h: any) => h.date === today);
        if (found) setHuddle(found);
        const s = await api.get("/sops");
        setRecentSops((s || []).slice(0, 5));
      } catch { /* ignore */ }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async () => {
    setBusy(true);
    try {
      let h = huddle;
      if (!h) {
        h = await api.post("/huddles", { date: today, title: "Daily Huddle" });
        setHuddle(h);
      }
      // Post each non-empty line as an action-item — creates a task.
      const lines = [
        ...(yesterday.split("\n").map((s) => s.trim()).filter(Boolean)
          .map((t) => `[Yesterday] ${t}`)),
        ...(todayText.split("\n").map((s) => s.trim()).filter(Boolean)
          .map((t) => `[Today] ${t}`)),
        ...(blockers.split("\n").map((s) => s.trim()).filter(Boolean)
          .map((t) => `[Blocker] ${t}`)),
      ];
      for (const text of lines) {
        await api.post(`/huddles/${h.id}/action-items`, {
          huddle_id: h.id, text, owner_user_id: user?.id,
        });
      }
      setStatusMsg({ kind: "ok", text: `Submitted · ${lines.length} note(s) posted for ${today}.` });
      setYesterday(""); setTodayText(""); setBlockers("");
    } catch (e: any) {
      setStatusMsg({ kind: "err", text: e?.message || "Submit failed — try again." });
    } finally { setBusy(false); }
  };

  return (
    <ScrollView style={styles.root} contentContainerStyle={{ padding: spacing.lg, paddingBottom: 120 }}
                testID="huddle-screen">
      <Text style={styles.h1}>Daily Huddle</Text>
      <Text style={styles.hint}>{today} · your notes flow to the admin&apos;s Business OS.</Text>
      {statusMsg && (
        <View
          style={[styles.banner, statusMsg.kind === "ok" ? styles.bannerOk : styles.bannerErr]}
          testID="huddle-status-banner"
        >
          <Text style={styles.bannerText}>{statusMsg.text}</Text>
        </View>
      )}

      <View style={styles.card}>
        <Text style={styles.label}>What did you finish yesterday?</Text>
        <AppTextInput value={yesterday} onChangeText={setYesterday} multiline placeholder="One per line"
                   style={styles.input} testID="huddle-yesterday"/>
      </View>
      <View style={styles.card}>
        <Text style={styles.label}>What are you doing today?</Text>
        <AppTextInput value={todayText} onChangeText={setTodayText} multiline placeholder="One per line"
                   style={styles.input} testID="huddle-today"/>
      </View>
      <View style={styles.card}>
        <Text style={styles.label}>Any blockers?</Text>
        <AppTextInput value={blockers} onChangeText={setBlockers} multiline placeholder="One per line"
                   style={styles.input} testID="huddle-blockers"/>
      </View>

      <Pressable onPress={submit} disabled={busy} style={styles.submitBtn} testID="huddle-submit">
        <Ionicons name="paper-plane-outline" size={18} color="#fff"/>
        <Text style={styles.submitLbl}>{busy ? "Submitting…" : "Submit huddle"}</Text>
      </Pressable>

      {recentSops.length > 0 && (
        <View style={{ marginTop: spacing.xl }}>
          <Text style={styles.h2}>Reference SOPs</Text>
          {recentSops.map((s) => (
            <View key={s.id} style={styles.sopRow} testID={`huddle-sop-${s.slug}`}>
              <Ionicons name="document-text-outline" size={14} color={colors.brand}/>
              <Text style={styles.sopTitle}>{s.title}</Text>
              <Text style={styles.sopCat}>{s.category}</Text>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  h1: { fontFamily: font.bold, fontSize: 26, color: colors.onSurface },
  h2: { fontFamily: font.semiBold, fontSize: 16, color: colors.onSurface, marginBottom: spacing.sm },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
          marginBottom: spacing.lg },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
          borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  label: { fontFamily: font.semiBold, fontSize: 13, color: colors.onSurface, marginBottom: spacing.sm },
  input: { minHeight: 90, fontFamily: font.regular, fontSize: 14, color: colors.onSurface,
           textAlignVertical: "top" },
  submitBtn: { backgroundColor: colors.brand, borderRadius: radius.md, padding: spacing.md,
               flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm },
  submitLbl: { color: "#fff", fontFamily: font.bold, fontSize: 15 },
  sopRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm,
            paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border },
  sopTitle: { flex: 1, fontFamily: font.semiBold, fontSize: 13, color: colors.onSurface },
  sopCat: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  banner: {
    padding: spacing.sm, borderRadius: radius.sm,
    marginBottom: spacing.md, borderWidth: 1,
  },
  bannerOk: { backgroundColor: "#DCFCE7", borderColor: "#22C55E" },
  bannerErr: { backgroundColor: "#FEE2E2", borderColor: "#EF4444" },
  bannerText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
});
