import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Linking } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";

const ICONS: Record<string, any> = {
  agreement: "document-text-outline",
  invoice: "receipt-outline",
  photo: "image-outline",
  document: "document-outline",
};

export default function PortalDocuments() {
  const [docs, setDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      setDocs(await api.get("/me/documents"));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const open = (d: any) => {
    if (d.data) Linking.openURL(d.data).catch(() => {});
  };

  return (
    <View style={styles.root}>
      <Header title="Documents" subtitle="Files shared with you" back />
      {loading ? (
        <Loading testID="portal-documents-loading" />
      ) : (
        <FlatList
          testID="portal-documents-list"
          data={docs}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.md, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
          ListEmptyComponent={
            <EmptyState icon="folder-open-outline" title="No documents yet" subtitle="Agreements and files from our team will appear here." testID="portal-documents-empty" />
          }
          renderItem={({ item }) => (
            <Pressable style={styles.row} onPress={() => open(item)} testID={`portal-document-${item.id}`}>
              <View style={styles.rowIcon}>
                <Ionicons name={ICONS[item.type] || ICONS.document} size={20} color={colors.brand} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.rowTitle} numberOfLines={1}>{item.name}</Text>
                <Text style={styles.rowMeta}>{(item.created_at || "").slice(0, 10)} · {item.uploaded_by}</Text>
              </View>
              <Ionicons name="download-outline" size={20} color={colors.muted} />
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  rowIcon: { width: 40, height: 40, borderRadius: radius.md, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  rowTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  rowMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
});
