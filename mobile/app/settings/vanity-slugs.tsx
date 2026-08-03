import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, RefreshControl,
  TouchableOpacity, ActivityIndicator, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { showConfirm } from "@/src/components/ConfirmModal";

const ALIAS_REGEX = /^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$/;

export default function VanitySlugsPage() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const [state, setState] = useState<any>(null);
  const [adding, setAdding] = useState("");
  const [addError, setAddError] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/tenants/current/slug-aliases");
      setState(r);
    } catch {
      setState({ canonical_slug: "", aliases: [] });
    } finally {
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { if (isSuperAdmin) load(); }, [isSuperAdmin, load]));

  const addAlias = async () => {
    const slug = adding.trim().toLowerCase();
    if (!slug) return;
    if (!ALIAS_REGEX.test(slug)) {
      setAddError("3-32 chars, lowercase a-z, 0-9, hyphens only.");
      return;
    }
    setBusy(true);
    setAddError("");
    try {
      await api.post("/tenants/current/slug-aliases", { slug });
      setAdding("");
      await load();
    } catch (e: any) {
      setAddError(e?.message || "Failed to add");
    } finally {
      setBusy(false);
    }
  };

  const deleteAlias = (slug: string) => {
    showConfirm({
      title: "Delete alias?",
      message: `Remove "${slug}"?`,
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: async () => {
        setBusy(true);
        try {
          await api.del(`/tenants/current/slug-aliases/${slug}`);
          await load();
        } catch (e: any) {
          Alert.alert("Error", e?.message || "Delete failed");
        } finally { setBusy(false); }
      },
    });
  };

  if (!isSuperAdmin) {
    return (
      <View style={s.root}>
        <Header title="Vanity Slugs" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Super admin only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root}>
      <Header title="Vanity Slugs" subtitle="URL alias management" back />
      {!state ? (
        <View style={s.center}><ActivityIndicator size="large" color={colors.brand} /></View>
      ) : (
        <ScrollView
          testID="vanity-slugs-page"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          {/* Canonical slug */}
          <View style={s.canonCard} testID="vanity-slug-canonical">
            <Ionicons name="lock-closed" size={14} color={colors.muted} />
            <Text style={s.canonLabel}>Canonical:</Text>
            <Text style={s.canonSlug}>{state.canonical_slug || "\u2014"}</Text>
          </View>

          {/* Aliases */}
          <Text style={s.sectionTitle}>Aliases</Text>
          {(state.aliases || []).length === 0 ? (
            <Text style={s.emptyText}>No aliases yet.</Text>
          ) : (
            (state.aliases || []).map((a: any) => (
              <View key={a.slug || a} style={s.aliasRow} testID={`vanity-slug-alias-${a.slug || a}`}>
                <Ionicons name="link-outline" size={16} color={colors.brand} />
                <Text style={s.aliasText}>{a.slug || a}</Text>
                <TouchableOpacity onPress={() => deleteAlias(a.slug || a)} testID={`vanity-slug-delete-${a.slug || a}`}>
                  <Ionicons name="trash-outline" size={18} color={colors.error} />
                </TouchableOpacity>
              </View>
            ))
          )}

          {/* Add form */}
          <View style={s.addRow}>
            <TextInput
              style={s.addInput}
              value={adding}
              onChangeText={(v) => { setAdding(v.toLowerCase()); setAddError(""); }}
              placeholder="new-slug"
              placeholderTextColor={colors.muted}
              autoCapitalize="none"
              autoCorrect={false}
              testID="vanity-slug-add-input"
            />
            <TouchableOpacity
              style={[s.addBtn, (busy || !adding.trim()) && { opacity: 0.5 }]}
              onPress={addAlias}
              disabled={busy || !adding.trim()}
              testID="vanity-slug-add-btn"
            >
              <Ionicons name="add" size={20} color="#fff" />
            </TouchableOpacity>
          </View>
          {addError ? <Text style={s.addError}>{addError}</Text> : null}
          <Text style={s.hint}>3-32 chars, lowercase letters, numbers, hyphens.</Text>
        </ScrollView>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },
  canonCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surfaceTertiary, borderRadius: radius.md,
    padding: spacing.md, marginBottom: spacing.lg,
  },
  canonLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  canonSlug: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.sm, textTransform: "uppercase",
    letterSpacing: 0.8, color: colors.muted, marginBottom: spacing.sm,
  },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginBottom: spacing.md },
  aliasRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  aliasText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  addRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.lg },
  addInput: {
    flex: 1, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
  },
  addBtn: {
    width: 48, height: 48, borderRadius: radius.md, backgroundColor: colors.brand,
    alignItems: "center", justifyContent: "center",
  },
  addError: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error, marginTop: spacing.xs },
  hint: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: spacing.xs },
});
