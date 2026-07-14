/** Phase 17A · Mobile — Audit detail with score rings + tabbed issues/pages/otto. */
import React, { useEffect, useState, useMemo } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import {
  AdminOnlyGate, ScoreChip, SeverityDot, BrandPill, CenterLoader,
} from "../_shared";

type Tab = "issues" | "pages" | "otto";

export default function AuditDetailMobile() {
  return (
    <AdminOnlyGate title="Audit">
      <Inner />
    </AdminOnlyGate>
  );
}

function Inner() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [audit, setAudit] = useState<any>(null);
  const [pages, setPages] = useState<any[]>([]);
  const [otto, setOtto] = useState<{ fixes: any[]; totals: any } | null>(null);
  const [tab, setTab] = useState<Tab>("issues");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const a = await api.get(`/seo/audits/${id}`);
    setAudit(a);
    const p = await api.get(`/seo/audits/${id}/pages?limit=200`);
    setPages(p.items || p.rows || []);
    try {
      const o = await api.get(`/seo/otto/fixes/${id}`);
      setOtto(o);
    } catch { /* audit may not exist yet for OTTO */ }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [id]);
  useEffect(() => {
    if (!audit || ["done", "failed", "cancelled"].includes(audit.status)) return;
    const t = setInterval(load, 3500);
    return () => clearInterval(t);
  }, [audit?.status]);

  const allIssues = useMemo(() => {
    const out: any[] = [];
    pages.forEach((p) => {
      (p.issues || []).forEach((i: any) => out.push({ ...i, url: p.url }));
    });
    return out;
  }, [pages]);

  const generateOtto = async () => {
    setBusy(true);
    try {
      await api.post("/seo/otto/generate-fixes",
                     { audit_id: id, max_fixes: 40 });
      await load();
      setTab("otto");
    } finally { setBusy(false); }
  };

  if (!audit) return (
    <View style={styles.root}>
      <Header title="Audit" />
      <CenterLoader />
    </View>
  );

  const scores = audit.summary?.scores || {};

  return (
    <View style={styles.root}>
      <Header title="Audit" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 40 }}>
        <Text style={styles.url} numberOfLines={1}>{audit.url}</Text>
        <View style={styles.metaRow}>
          <BrandPill text={audit.status}
                      tone={audit.status === "done" ? "green" :
                             audit.status === "failed" ? "red" :
                             audit.status === "running" ? "brand" : "amber"} />
          <Text style={styles.metaText}>
            {audit.summary?.pages_crawled ?? "—"} pages ·{" "}
            {audit.summary?.issues_total ?? "—"} issues
          </Text>
        </View>

        {/* Score ring row */}
        <View style={styles.ringRow}>
          {[
            ["Overall", scores.overall],
            ["Technical", scores.technical],
            ["On-page", scores.on_page],
            ["UX", scores.ux],
          ].map(([label, v]) => (
            <View key={label as string} style={styles.ringCard}>
              <Text style={styles.ringLabel}>{label}</Text>
              <ScoreChip value={v as number} size="lg" />
            </View>
          ))}
        </View>

        {/* Tabs */}
        <View style={styles.tabRow}>
          {(["issues", "pages", "otto"] as Tab[]).map((t) => (
            <Pressable key={t}
                       style={[styles.tab, tab === t && styles.tabActive]}
                       testID={`audit-tab-${t}`}
                       onPress={() => setTab(t)}>
              <Text style={[styles.tabText,
                             tab === t && styles.tabTextActive]}>
                {t === "otto" ? `Auto-Fix (${otto?.fixes?.length ?? 0})`
                                : t === "issues" ? `Issues (${allIssues.length})`
                                : `Pages (${pages.length})`}
              </Text>
            </Pressable>
          ))}
        </View>

        {tab === "issues" && (
          allIssues.length === 0 ? (
            <Text style={styles.empty}>
              {audit.status === "done"
                ? "No issues detected."
                : "Crawling — check back shortly."}
            </Text>
          ) : (
            allIssues.slice(0, 200).map((i, idx) => (
              <View key={idx} style={styles.rowItem}>
                <SeverityDot severity={i.severity} />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text style={styles.rowCode}>{i.code}</Text>
                  <Text style={styles.rowHint} numberOfLines={2}>
                    {i.hint}
                  </Text>
                  <Text style={styles.rowUrl} numberOfLines={1}>
                    {i.url}
                  </Text>
                </View>
              </View>
            ))
          )
        )}

        {tab === "pages" && pages.map((p, idx) => (
          <View key={p.url + idx} style={styles.rowItem}>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={styles.rowUrl} numberOfLines={1}>{p.url}</Text>
              <Text style={styles.rowMeta}>
                {p.status_code} · {(p.issues || []).length} issues
              </Text>
            </View>
          </View>
        ))}

        {tab === "otto" && (
          <>
            <Pressable style={[styles.generateBtn,
                                busy && { opacity: 0.6 }]}
                       disabled={busy}
                       onPress={generateOtto}
                       testID="audit-otto-generate">
              <Ionicons name="sparkles" size={16} color="#fff" />
              <Text style={styles.generateBtnText}>
                {busy ? "Generating…" : "Generate fixes"}
              </Text>
            </Pressable>
            {(otto?.fixes || []).length === 0 ? (
              <Text style={styles.empty}>
                No fixes yet. Tap Generate to produce concrete patches.
              </Text>
            ) : (
              (otto?.fixes || []).slice(0, 100).map((f: any) => (
                <Pressable key={f.id}
                          style={styles.rowItem}
                          onPress={() => router.push(
                            `/admin/seo/otto/${f.id}` as any)}>
                  <SeverityDot severity={f.severity} />
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text style={styles.rowCode}>{f.issue_code}</Text>
                    <Text style={styles.rowUrl} numberOfLines={1}>
                      {f.page_url}
                    </Text>
                  </View>
                  <BrandPill text={f.status}
                              tone={f.status === "applied" ? "green" :
                                     f.status === "dismissed" ? "grey" : "amber"} />
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
  url: { fontFamily: font.bold, fontSize: fontSize.lg,
          color: colors.onSurface },
  metaRow: { flexDirection: "row", gap: spacing.sm, alignItems: "center",
              marginTop: 6, marginBottom: spacing.lg },
  metaText: { fontFamily: font.regular, fontSize: fontSize.sm,
               color: colors.muted },
  ringRow: { flexDirection: "row", flexWrap: "wrap",
              gap: spacing.sm, marginBottom: spacing.lg },
  ringCard: {
    flex: 1, minWidth: 130,
    backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.lg,
    padding: spacing.md, alignItems: "center",
  },
  ringLabel: { fontFamily: font.semibold, fontSize: 10,
                color: colors.muted, marginBottom: 4,
                textTransform: "uppercase" },
  tabRow: {
    flexDirection: "row", gap: spacing.sm,
    marginBottom: spacing.md,
  },
  tab: {
    flex: 1, paddingVertical: 10, borderRadius: radius.md,
    backgroundColor: colors.surface, alignItems: "center",
    borderWidth: 1, borderColor: colors.border,
  },
  tabActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  tabText: { fontFamily: font.semibold, fontSize: fontSize.sm,
              color: colors.onSurface },
  tabTextActive: { color: "#fff" },
  rowItem: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: spacing.md, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  rowCode: { fontFamily: font.bold, fontSize: fontSize.sm,
              color: colors.onSurface },
  rowHint: { fontFamily: font.regular, fontSize: fontSize.sm,
              color: colors.muted },
  rowUrl: { fontFamily: font.regular, fontSize: 11,
             color: colors.brand, marginTop: 2 },
  rowMeta: { fontFamily: font.regular, fontSize: fontSize.sm,
              color: colors.muted, marginTop: 2 },
  empty: { fontFamily: font.regular, fontSize: fontSize.base,
            color: colors.muted, textAlign: "center",
            padding: spacing.xl },
  generateBtn: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    justifyContent: "center", backgroundColor: colors.brand,
    borderRadius: radius.md, padding: spacing.md,
    marginBottom: spacing.md,
  },
  generateBtnText: { fontFamily: font.bold, fontSize: fontSize.base,
                      color: "#fff" },
});
