/** Phase 17C · Mobile — OTTO cross-audit fix list with filters. */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import {
  AdminOnlyGate, BrandPill, SeverityDot, CenterLoader,
} from "./_shared";

const STATUS_TONE: Record<string, "brand" | "green" | "amber" | "red" | "grey"> = {
  pending: "amber", applied: "green", dismissed: "grey",
};

export default function OttoListMobile() {
  return (
    <AdminOnlyGate title="OTTO Auto-Fix">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const router = useRouter();
  const [audits, setAudits] = useState<any[]>([]);
  const [fixes, setFixes] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [patchFilter, setPatchFilter] = useState<string>("");

  const load = async () => {
    setLoading(true);
    try {
      const auds = await api.get("/seo/audits");
      const auditList = Array.isArray(auds) ? auds : (auds.items || []);
      setAudits(auditList);
      // Aggregate fixes across all audits.
      const all: any[] = [];
      for (const a of auditList.slice(0, 20)) {
        try {
          const r = await api.get(`/seo/otto/fixes/${a.id}`);
          for (const f of (r.fixes || [])) {
            all.push({ ...f, audit_url: a.url });
          }
        } catch { /* ignore */ }
      }
      setFixes(all);
    } finally { setLoading(false); }
  };
  useFocusEffect(useCallback(() => { load(); }, []));

  const patchTypes = Array.from(new Set(fixes.map(
    (f) => f.patch_type).filter(Boolean)));
  const filtered = fixes.filter((f) => {
    if (statusFilter && f.status !== statusFilter) return false;
    if (patchFilter && f.patch_type !== patchFilter) return false;
    return true;
  });

  return (
    <View style={styles.root}>
      <Header title="OTTO Auto-Fix" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 60 }}>
        {loading ? <CenterLoader /> : (
          <>
            {/* Status filter chips */}
            <Text style={styles.chipHead}>Status</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}
                         style={{ marginBottom: spacing.sm }}>
              {[
                ["", "All"], ["pending", "Pending"],
                ["applied", "Applied"], ["dismissed", "Dismissed"],
              ].map(([v, l]) => (
                <Pressable key={v || "all"}
                            style={[styles.chip,
                                     statusFilter === v && styles.chipActive]}
                            onPress={() => setStatusFilter(v as string)}
                            testID={`otto-filter-status-${v || "all"}`}>
                  <Text style={[styles.chipText,
                                statusFilter === v && { color: "#fff" }]}>
                    {l}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>

            {patchTypes.length > 0 && (
              <>
                <Text style={styles.chipHead}>Patch type</Text>
                <ScrollView horizontal
                             showsHorizontalScrollIndicator={false}
                             style={{ marginBottom: spacing.md }}>
                  {[["", "All"], ...patchTypes.map((p) => [p, p])].map(
                    ([v, l]) => (
                      <Pressable key={v || "all-patch"}
                                  style={[styles.chip,
                                            patchFilter === v && styles.chipActive]}
                                  onPress={() => setPatchFilter(v as string)}
                                  testID={`otto-filter-patch-${v || "all"}`}>
                        <Text style={[styles.chipText,
                                        patchFilter === v && { color: "#fff" }]}>
                          {l}
                        </Text>
                      </Pressable>
                    )
                  )}
                </ScrollView>
              </>
            )}

            {filtered.length === 0 ? (
              <View style={styles.empty}>
                <Ionicons name="sparkles-outline" size={28}
                           color={colors.muted} />
                <Text style={styles.emptyTitle}>No fixes here yet</Text>
                <Text style={styles.emptyBody}>
                  Run an audit and use “Generate fixes” to create patches.
                </Text>
              </View>
            ) : (
              filtered.map((f) => (
                <Pressable key={f.id}
                            style={styles.fixCard}
                            onPress={() => router.push(
                              `/admin/seo/otto/${f.id}` as any)}
                            testID={`otto-list-${f.id}`}>
                  <SeverityDot severity={f.severity} />
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <View style={{ flexDirection: "row",
                                    alignItems: "center", gap: 6 }}>
                      <Text style={styles.fixCode}>{f.issue_code}</Text>
                      <BrandPill text={f.patch_type} tone="brand" />
                      <BrandPill text={f.status}
                                  tone={STATUS_TONE[f.status] || "grey"} />
                    </View>
                    <Text style={styles.fixUrl} numberOfLines={1}>
                      {f.page_url}
                    </Text>
                  </View>
                  <Ionicons name="chevron-forward" size={16}
                             color={colors.muted} />
                </Pressable>
              ))
            )}
          </>
        )}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  chipHead: { fontFamily: font.semibold, fontSize: 10,
               color: colors.muted, textTransform: "uppercase",
               marginTop: spacing.sm, marginBottom: spacing.xs },
  chip: {
    paddingHorizontal: spacing.md, paddingVertical: 6,
    borderRadius: 999, marginRight: spacing.sm,
    backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border,
  },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm,
               color: colors.onSurface },
  empty: {
    padding: spacing["2xl"], alignItems: "center", gap: spacing.sm,
  },
  emptyTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: colors.onSurface, marginTop: spacing.sm },
  emptyBody: { fontFamily: font.regular, fontSize: fontSize.base,
                color: colors.muted, textAlign: "center" },
  fixCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, marginBottom: spacing.sm,
  },
  fixCode: { fontFamily: font.bold, fontSize: fontSize.sm,
              color: colors.onSurface },
  fixUrl: { fontFamily: font.regular, fontSize: 11,
             color: colors.brand, marginTop: 4 },
});
