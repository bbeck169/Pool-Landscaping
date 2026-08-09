/** Phase 17C · Mobile — OTTO fix detail with stacked before/after diff. */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import {
  AdminOnlyGate, BrandPill, SeverityDot, CenterLoader,
} from "../_shared";

const STATUS_TONE: Record<string, "brand" | "green" | "amber" | "red" | "grey"> = {
  pending: "amber", applied: "green", dismissed: "grey",
};

export default function OttoDetailMobile() {
  return (
    <AdminOnlyGate title="Fix Detail">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [fix, setFix] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    // Detail endpoint doesn't exist standalone; walk audits to locate.
    const auds = await api.get("/seo/audits");
    const auditList = Array.isArray(auds) ? auds : (auds.items || []);
    for (const a of auditList) {
      const r = await api.get(`/seo/otto/fixes/${a.id}`);
      const found = (r.fixes || []).find((f: any) => f.id === id);
      if (found) { setFix({ ...found, audit_id: a.id }); return; }
    }
    setFix({ __not_found: true });
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const copy = async () => {
    if (!fix?.patch_snippet) return;
    await Clipboard.setStringAsync(fix.patch_snippet);
    Alert.alert("Copied", "Patch snippet copied to clipboard.");
  };

  const action = async (verb: "mark-applied" | "dismiss") => {
    setBusy(true);
    try {
      await api.post(`/seo/otto/fixes/${id}/${verb}`);
      await load();
    } finally { setBusy(false); }
  };

  if (!fix) return (
    <View style={styles.root}>
      <Header title="Fix Detail" />
      <CenterLoader />
    </View>
  );
  if (fix.__not_found) return (
    <View style={styles.root}>
      <Header title="Fix Detail" />
      <View style={{ padding: spacing.xl, alignItems: "center" }}>
        <Ionicons name="alert-circle-outline" size={28}
                   color={colors.muted} />
        <Text style={{ fontFamily: font.regular, color: colors.muted,
                        marginTop: spacing.sm }}>
          Fix not found.
        </Text>
      </View>
    </View>
  );

  return (
    <View style={styles.root}>
      <Header title="Fix Detail" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 60 }}>
        <View style={styles.headerCard}>
          <View style={{ flexDirection: "row", alignItems: "center",
                          gap: spacing.sm }}>
            <SeverityDot severity={fix.severity} />
            <Text style={styles.code}>{fix.issue_code}</Text>
            <BrandPill text={fix.patch_type} tone="brand" />
            <BrandPill text={fix.status}
                        tone={STATUS_TONE[fix.status] || "grey"} />
          </View>
          <Text style={styles.pageUrl} numberOfLines={2}>
            {fix.page_url}
          </Text>
          {fix.rationale ? (
            <Text style={styles.rationale}>{fix.rationale}</Text>
          ) : null}
        </View>

        <Text style={styles.sectionLabel}>Before</Text>
        <View style={styles.beforeBox}>
          <Text style={styles.diffText}>
            {fix.current_value || "(empty / missing)"}
          </Text>
        </View>

        <Text style={styles.sectionLabel}>After</Text>
        <View style={styles.afterBox}>
          <Text style={styles.diffText}>
            {fix.suggested_value || fix.patch_snippet || "(no suggestion)"}
          </Text>
        </View>

        <Text style={styles.sectionLabel}>Patch snippet</Text>
        <View style={styles.snippetBox}>
          <Text style={styles.snippetText}>
            {fix.patch_snippet || "(no snippet)"}
          </Text>
        </View>

        <View style={{ flexDirection: "row", gap: spacing.sm,
                        marginTop: spacing.md, flexWrap: "wrap" }}>
          <Pressable style={styles.actionBtn}
                      onPress={copy}
                      testID="otto-copy">
            <Ionicons name="copy-outline" size={16} color="#fff" />
            <Text style={styles.actionBtnText}>Copy patch</Text>
          </Pressable>
          {fix.status === "pending" && (
            <>
              <Pressable style={[styles.actionBtnGreen,
                                    busy && { opacity: 0.6 }]}
                          disabled={busy}
                          onPress={() => action("mark-applied")}
                          testID="otto-applied">
                <Ionicons name="checkmark" size={16} color="#fff" />
                <Text style={styles.actionBtnText}>Mark applied</Text>
              </Pressable>
              <Pressable style={[styles.actionBtnGrey,
                                    busy && { opacity: 0.6 }]}
                          disabled={busy}
                          onPress={() => action("dismiss")}
                          testID="otto-dismiss">
                <Ionicons name="close" size={16} color={colors.onSurface} />
                <Text style={[styles.actionBtnText,
                                { color: colors.onSurface }]}>Dismiss</Text>
              </Pressable>
            </>
          )}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  headerCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, marginBottom: spacing.md, gap: 6,
  },
  code: { flex: 1, fontFamily: font.bold, fontSize: fontSize.base,
           color: colors.onSurface },
  pageUrl: { fontFamily: font.regular, fontSize: fontSize.sm,
              color: colors.brand, marginTop: 4 },
  rationale: { fontFamily: font.regular, fontSize: fontSize.sm,
                color: colors.muted, marginTop: 6, lineHeight: 18 },
  sectionLabel: { fontFamily: font.bold, fontSize: 10,
                   textTransform: "uppercase", color: colors.muted,
                   marginTop: spacing.md, marginBottom: 6 },
  beforeBox: {
    backgroundColor: "#FEE2E2", borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: "#FCA5A5",
  },
  afterBox: {
    backgroundColor: "#DCFCE7", borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: "#86EFAC",
  },
  diffText: { fontFamily: "Courier", fontSize: 12,
               color: colors.onSurface, lineHeight: 18 },
  snippetBox: {
    backgroundColor: "#0F172A", borderRadius: radius.md,
    padding: spacing.md,
  },
  snippetText: { fontFamily: "Courier", fontSize: 11,
                  color: "#E2E8F0", lineHeight: 16 },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 10,
  },
  actionBtnGreen: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#059669", borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 10,
  },
  actionBtnGrey: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.surface, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 10,
    borderWidth: 1, borderColor: colors.border,
  },
  actionBtnText: { fontFamily: font.bold, fontSize: fontSize.sm,
                    color: "#fff" },
});
