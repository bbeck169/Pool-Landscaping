// Phase 16 · Feb-2026 — Mention detail + draft reply launcher.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView } from "react-native";
import { router, useFocusEffect, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Card, Loading, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

type MentionDetail = {
  id: string;
  provider?: string;
  sentiment?: string;
  snippet?: string;
  full_text?: string;
  url?: string;
  captured_at?: string;
  domain?: string;
  is_own_domain?: boolean;
  is_competitor?: boolean;
};

export default function MentionDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [row, setRow] = useState<MentionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true); setErr("");
    try {
      const j: any = await api.get(`/aeo/mentions/list?id=${encodeURIComponent(id)}`);
      const hit = (j?.items || j?.mentions || []).find((m: any) => m.id === id) || null;
      setRow(hit);
    } catch (e: any) {
      setErr(String(e?.message || e));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  return (
    <RoleGate level="admin_plus">
      <View style={styles.container}>
        <Header title="Mention" />
        {loading ? (
          <Loading />
        ) : (
          <ScrollView contentContainerStyle={styles.body}>
            {err ? <Text style={styles.err}>{err}</Text> : null}
            {!row ? (
              <Card>
                <Text style={styles.hint}>Mention not found.</Text>
              </Card>
            ) : (
              <>
                <Card>
                  <Text style={styles.provider}>{row.provider || "unknown provider"}</Text>
                  <Text style={styles.meta}>
                    {row.captured_at ? new Date(row.captured_at).toLocaleString() : "—"}
                    {row.domain ? ` · ${row.domain}` : ""}
                  </Text>
                  <View style={{ height: spacing.sm }} />
                  <Text style={styles.body_text} testID="mention-detail-full-text">
                    {row.full_text || row.snippet || "(text missing)"}
                  </Text>
                  {row.url ? (
                    <Text style={styles.url} numberOfLines={2} testID="mention-detail-url">
                      {row.url}
                    </Text>
                  ) : null}
                </Card>
                <PrimaryButton
                  testID="mention-detail-draft-reply-btn"
                  title="Draft reply"
                  icon="create-outline"
                  onPress={() => router.push({
                    pathname: "/aeo/response-draft",
                    params: { mentionId: row.id },
                  })}
                />
              </>
            )}
          </ScrollView>
        )}
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
  provider: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface, textTransform: "capitalize" },
  meta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  body_text: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  url: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.brand, marginTop: spacing.sm },
  hint: { fontFamily: font.regular, color: colors.muted },
  err: { color: colors.error, fontFamily: font.medium },
});
