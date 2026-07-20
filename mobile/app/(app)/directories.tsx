/**
 * Directories · Mobile feed + assignment inbox (D2 · Feb 2026).
 *
 * Read-only for techs. Admin can Mark Verified + Assign-to-self.
 * Full NAP profile editor stays on web — mobile is meant for
 * status triage + external URL taps.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  Linking, RefreshControl, Alert,
} from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, fontSize, font } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";

const STATUS_COLOURS: Record<string, string> = {
  not_started:  colors.muted,
  in_progress:  colors.brand,
  submitted:    "#f59e0b",
  verified:     "#10b981",
  needs_update: "#f97316",
  rejected:     "#ef4444",
  paid_wall:    "#8b5cf6",
};
const STATUS_LABELS: Record<string, string> = {
  not_started:  "Not started",
  in_progress:  "In progress",
  submitted:    "Submitted",
  verified:     "Verified",
  needs_update: "Needs update",
  rejected:     "Rejected",
  paid_wall:    "Paid wall",
};

export default function DirectoriesMobile() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || (user?.role as any) === "super_admin";

  const [subs, setSubs] = useState<any[]>([]);
  const [defs, setDefs] = useState<Record<string, any>>({});
  const [selected, setSelected] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [subsResp, defsResp] = await Promise.all([
        api.get("/directories/submissions?limit=200"),
        api.get("/directories/definitions"),
      ]);
      setSubs(subsResp.submissions || []);
      const byslug: Record<string, any> = {};
      for (const d of defsResp.definitions || []) byslug[d.slug] = d;
      setDefs(byslug);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Failed to load directories");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const grouped = useMemo(() => {
    const g: Record<string, any[]> = {};
    for (const s of subs) {
      const k = s.status || "not_started";
      (g[k] = g[k] || []).push(s);
    }
    return g;
  }, [subs]);

  const verify = async (sid: string) => {
    setBusy(true);
    try {
      const r = await api.post(`/directories/submissions/${sid}/mark-verified`, {});
      setSubs((cur) => cur.map((x) => (x.id === sid ? r : x)));
      setSelected(r);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Verify failed");
    }
    setBusy(false);
  };

  const assignMe = async (sid: string) => {
    if (!user?.id) return;
    setBusy(true);
    try {
      const r = await api.post(`/directories/submissions/${sid}/assign`,
                                 { assigned_user_id: user.id });
      setSubs((cur) => cur.map((x) => (x.id === sid ? r : x)));
      setSelected(r);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Assign failed");
    }
    setBusy(false);
  };

  const openUrl = (url?: string) => {
    if (!url) return;
    Linking.openURL(url).catch(() =>
      Alert.alert("Cannot open", "This URL cannot be opened on this device."));
  };

  if (loading) {
    return (
      <View style={styles.center} testID="directories-loading">
        <ActivityIndicator color={colors.brand} />
        <Text style={styles.muted}>Loading directories…</Text>
      </View>
    );
  }

  // ── Detail view ────────────────────────────────────────────────
  if (selected) {
    const d = defs[selected.directory_slug] || {};
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg }}>
        <Header
          title={d.name || selected.directory_slug}
          onBack={() => setSelected(null)}
        />
        <ScrollView contentContainerStyle={styles.detail}
                     testID="directory-detail">
          <View style={styles.card}>
            <Text style={styles.h2}>{d.name || selected.directory_slug}</Text>
            <Text style={styles.muted}>
              {d.category?.replace(/_/g, " ")} · Priority {d.priority || "?"}
            </Text>
            <View style={styles.chipRow}>
              <View style={[styles.chip, { backgroundColor: STATUS_COLOURS[selected.status] }]}>
                <Text style={styles.chipText}>{STATUS_LABELS[selected.status] || selected.status}</Text>
              </View>
              {selected.nap_match_score != null && (
                <View style={[styles.chip, { backgroundColor: "#0f172a" }]}>
                  <Text style={styles.chipText}>NAP {selected.nap_match_score}%</Text>
                </View>
              )}
              {selected.assigned_user_id && (
                <View style={[styles.chip, { backgroundColor: colors.brand }]}>
                  <Text style={styles.chipText}>Assigned</Text>
                </View>
              )}
            </View>
          </View>

          {d.homepage_url ? (
            <Pressable style={styles.linkBtn} onPress={() => openUrl(d.homepage_url)}
                        testID="detail-homepage">
              <Ionicons name="open-outline" size={16} color={colors.brand} />
              <Text style={styles.linkText}>Open directory homepage</Text>
            </Pressable>
          ) : null}
          {d.submission_url ? (
            <Pressable style={styles.linkBtn} onPress={() => openUrl(d.submission_url)}
                        testID="detail-submit-url">
              <Ionicons name="paper-plane-outline" size={16} color={colors.brand} />
              <Text style={styles.linkText}>Open submission form</Text>
            </Pressable>
          ) : null}
          {selected.external_listing_url ? (
            <Pressable style={styles.linkBtn} onPress={() => openUrl(selected.external_listing_url)}>
              <Ionicons name="link-outline" size={16} color={colors.brand} />
              <Text style={styles.linkText}>Open live listing</Text>
            </Pressable>
          ) : null}

          {(selected.discrepancies || []).length > 0 && (
            <View style={styles.card}>
              <Text style={styles.h3}>NAP diff</Text>
              {selected.discrepancies.map((diff: any, i: number) => (
                <Text key={i} style={styles.diffLine}>
                  · <Text style={{ fontWeight: "700" }}>{diff.field}</Text> —
                  expected <Text style={{ color: "#10b981" }}>{String(diff.expected)}</Text>,
                  found <Text style={{ color: "#ef4444" }}>{String(diff.found)}</Text>
                </Text>
              ))}
            </View>
          )}

          {selected.notes ? (
            <View style={styles.card}>
              <Text style={styles.h3}>Notes</Text>
              <Text style={styles.muted}>{selected.notes}</Text>
            </View>
          ) : null}

          {isAdmin && (
            <View style={styles.actionRow}>
              <Pressable style={styles.primaryBtn}
                          onPress={() => verify(selected.id)}
                          disabled={busy}
                          testID="detail-verify-btn">
                <Ionicons name="checkmark-circle" size={16} color="#fff" />
                <Text style={styles.primaryBtnText}>Mark Verified</Text>
              </Pressable>
              {!selected.assigned_user_id && (
                <Pressable style={styles.secondaryBtn}
                            onPress={() => assignMe(selected.id)}
                            disabled={busy}
                            testID="detail-assign-btn">
                  <Ionicons name="person-add" size={16} color={colors.brand} />
                  <Text style={styles.secondaryBtnText}>Assign to me</Text>
                </Pressable>
              )}
            </View>
          )}
        </ScrollView>
      </View>
    );
  }

  // ── List view ──────────────────────────────────────────────────
  const orderedStatuses = [
    "needs_update", "in_progress", "submitted", "not_started",
    "verified", "rejected", "paid_wall",
  ];
  const myAssigned = subs.filter((s) => s.assigned_user_id === user?.id);

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <Header title="Directories" onBack={() => router.back()} />
      <ScrollView contentContainerStyle={styles.list}
                    refreshControl={
                      <RefreshControl refreshing={refreshing}
                                        onRefresh={() => { setRefreshing(true); load(); }} />
                    }
                    testID="directories-list">
        {myAssigned.length > 0 && (
          <View style={styles.section}>
            <Text style={styles.sectionTitle} testID="section-my-assignments">
              Assigned to me · {myAssigned.length}
            </Text>
            {myAssigned.map((s) => (
              <SubmissionRow key={s.id} s={s} defn={defs[s.directory_slug]}
                              onPress={() => setSelected(s)} />
            ))}
          </View>
        )}
        {orderedStatuses.map((st) => {
          const list = grouped[st] || [];
          if (list.length === 0) return null;
          return (
            <View key={st} style={styles.section}>
              <Text style={[styles.sectionTitle, { color: STATUS_COLOURS[st] }]}
                     testID={`section-${st}`}>
                {STATUS_LABELS[st]} · {list.length}
              </Text>
              {list.map((s) => (
                <SubmissionRow key={s.id} s={s} defn={defs[s.directory_slug]}
                                onPress={() => setSelected(s)} />
              ))}
            </View>
          );
        })}
        {subs.length === 0 && (
          <Text style={styles.muted}>
            No submissions yet — head to the web app to create your first one.
          </Text>
        )}
      </ScrollView>
    </View>
  );
}

function SubmissionRow({ s, defn, onPress }: {
  s: any; defn?: any; onPress: () => void;
}) {
  return (
    <Pressable style={styles.row} onPress={onPress}
                 testID={`row-${s.directory_slug}`}>
      <View style={{ flex: 1 }}>
        <Text style={styles.rowTitle}>{defn?.name || s.directory_slug}</Text>
        <Text style={styles.muted}>
          {defn?.category?.replace(/_/g, " ") || "?"} · P{defn?.priority || "?"}
        </Text>
      </View>
      {s.nap_match_score != null && (
        <View style={styles.scoreChip}>
          <Text style={styles.scoreText}>{s.nap_match_score}%</Text>
        </View>
      )}
      <Ionicons name="chevron-forward" size={16} color={colors.muted} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center",
             backgroundColor: colors.bg },
  list:   { padding: spacing.md, paddingBottom: spacing.xl * 2 },
  detail: { padding: spacing.md, paddingBottom: spacing.xl * 2 },
  section: { marginBottom: spacing.lg },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.md,
                    color: colors.onSurface, marginBottom: spacing.sm },
  row: { flexDirection: "row", alignItems: "center", padding: spacing.md,
          backgroundColor: colors.surface, borderRadius: radius.md,
          marginBottom: spacing.xs, borderWidth: 1, borderColor: colors.border },
  rowTitle: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface },
  muted: { color: colors.muted, fontSize: fontSize.sm, fontFamily: font.regular },
  scoreChip: { backgroundColor: "#0f172a", paddingHorizontal: 8, paddingVertical: 3,
                 borderRadius: 999, marginRight: spacing.sm },
  scoreText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.xs },
  card: { padding: spacing.md, backgroundColor: colors.surface,
           borderRadius: radius.md, marginBottom: spacing.md,
           borderWidth: 1, borderColor: colors.border },
  h2: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  h3: { fontFamily: font.bold, fontSize: fontSize.md, color: colors.onSurface,
         marginBottom: spacing.xs },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.sm },
  chip: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  chipText: { color: "#fff", fontSize: fontSize.xs, fontFamily: font.bold },
  linkBtn: { flexDirection: "row", alignItems: "center", padding: spacing.md,
              backgroundColor: colors.surface, borderRadius: radius.md,
              marginBottom: spacing.sm, borderWidth: 1, borderColor: colors.border,
              gap: spacing.sm },
  linkText: { color: colors.brand, fontFamily: font.bold, fontSize: fontSize.md },
  diffLine: { color: colors.onSurface, fontSize: fontSize.sm,
                fontFamily: font.regular, marginBottom: 2 },
  actionRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  primaryBtn: { flex: 1, flexDirection: "row", alignItems: "center",
                  justifyContent: "center", padding: spacing.md,
                  backgroundColor: colors.brand, borderRadius: radius.md,
                  gap: spacing.xs },
  primaryBtnText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.md },
  secondaryBtn: { flex: 1, flexDirection: "row", alignItems: "center",
                    justifyContent: "center", padding: spacing.md,
                    backgroundColor: colors.surface, borderRadius: radius.md,
                    borderWidth: 1, borderColor: colors.brand, gap: spacing.xs },
  secondaryBtnText: { color: colors.brand, fontFamily: font.bold, fontSize: fontSize.md },
});
