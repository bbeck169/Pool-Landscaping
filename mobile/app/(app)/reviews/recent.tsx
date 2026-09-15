/** Recent reviews list — Phase 3 mobile. */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, FlatList, ActivityIndicator, RefreshControl, Modal, TouchableOpacity, Switch, Alert, ScrollView } from "react-native";
import { useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { listReviews, updateReview } from "@/src/api/reviews";
import { ReviewCardNative } from "@/src/components/reviews/ReviewCardNative";
import AppTextInput from "@/src/components/ui/AppTextInput";

export default function ReviewsRecentScreen() {
  const insets = useSafeAreaInsets();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<any>(null);
  const [response, setResponse] = useState("");
  const [visible, setVisible] = useState(true);
  const [saving, setSaving] = useState(false);
  const [minStar, setMinStar] = useState(0);

  const reload = useCallback((silent = false) => {
    if (!silent) setLoading(true);
    listReviews({ limit: "100", min_star: minStar ? String(minStar) : undefined })
      .then((d) => setRows(d))
      .catch(() => setRows([]))
      .finally(() => { setLoading(false); setRefreshing(false); });
  }, [minStar]);

  useFocusEffect(useCallback(() => { reload(); }, [reload]));

  const openDetail = (r: any) => {
    setSelected(r);
    setResponse(r.admin_response || "");
    setVisible(r.visible_on_widget !== false);
  };

  const onSave = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      await updateReview(selected.id, { admin_response: response, visible_on_widget: visible });
      showToast("Review updated");
      setSelected(null);
      reload();
    } catch (e: any) { Alert.alert("Error", e.message); }
    finally { setSaving(false); }
  };

  return (
    <View style={styles.root} testID="reviews-recent">
      <Header title="Recent Reviews" subtitle={`${rows.length} reviews`} back />
      <View style={styles.filterRow}>
        {[0, 3, 4, 5].map((n) => (
          <TouchableOpacity
            key={n}
            testID={`reviews-min-${n}`}
            style={[styles.filterChip, minStar === n && styles.filterChipActive]}
            onPress={() => setMinStar(n)}
          >
            <Text style={[styles.filterChipText, minStar === n && styles.filterChipTextActive]}>
              {n === 0 ? "All" : `${n}★+`}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
      {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} /> : (
        <FlatList
          data={rows}
          keyExtractor={(item) => item.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); reload(true); }} />}
          contentContainerStyle={{ padding: spacing.lg }}
          renderItem={({ item }) => (
            <TouchableOpacity activeOpacity={0.7} onPress={() => openDetail(item)} testID={`reviews-recent-row-${item.id}`}>
              <ReviewCardNative review={item} />
            </TouchableOpacity>
          )}
          ListEmptyComponent={<View style={styles.empty}><Ionicons name="chatbox-outline" size={30} color={colors.muted} /><Text style={styles.emptyText}>No reviews</Text></View>}
        />
      )}

      {/* Detail modal */}
      <Modal visible={!!selected} animationType="slide" transparent onRequestClose={() => setSelected(null)}>
        <View style={styles.modalOverlay}>
          <View style={[styles.modalSheet, { paddingBottom: insets.bottom + 16 }]}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Review</Text>
              <TouchableOpacity testID="reviews-modal-close" onPress={() => setSelected(null)}>
                <Ionicons name="close" size={22} color={colors.muted} />
              </TouchableOpacity>
            </View>
            <ScrollView contentContainerStyle={{ padding: spacing.lg }}>
              {selected ? <ReviewCardNative review={selected} /> : null}
              <Text style={styles.label}>Admin response</Text>
              <AppTextInput
                multiline value={response} onChangeText={setResponse}
                placeholder="Say thanks, address concerns…"
                placeholderTextColor={colors.muted}
                testID="reviews-admin-response"
                style={styles.textArea}
              />
              <View style={styles.switchRow}>
                <Text style={{ fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface }}>Visible on public widget</Text>
                <Switch value={visible} onValueChange={setVisible} testID="reviews-visible-toggle"
                          trackColor={{ false: colors.border, true: colors.brand + "80" }}
                          thumbColor={visible ? colors.brand : colors.muted} />
              </View>
              <TouchableOpacity testID="reviews-save" style={styles.saveBtn} onPress={onSave} disabled={saving}>
                {saving ? <ActivityIndicator color="#fff" /> : <Text style={styles.saveBtnLabel}>Save changes</Text>}
              </TouchableOpacity>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  filterRow: { flexDirection: "row", gap: 6, padding: spacing.lg, paddingBottom: 0 },
  filterChip: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12, paddingVertical: 4, borderRadius: 999 },
  filterChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  filterChipText: { fontFamily: font.medium, fontSize: 11, color: colors.onSurface },
  filterChipTextActive: { color: "#fff" },
  empty: { alignItems: "center", paddingTop: 60, gap: 6 },
  emptyText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  modalOverlay: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, maxHeight: "88%" },
  modalHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  label: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.5, textTransform: "uppercase", marginTop: spacing.md, marginBottom: 4 },
  textArea: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, padding: spacing.md, minHeight: 80, textAlignVertical: "top", fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  switchRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: spacing.md },
  saveBtn: { backgroundColor: colors.brand, padding: 12, borderRadius: radius.sm, alignItems: "center", marginTop: spacing.lg },
  saveBtnLabel: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
});
