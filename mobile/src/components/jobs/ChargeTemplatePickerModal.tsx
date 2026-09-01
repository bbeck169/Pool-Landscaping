/**
 * ChargeTemplatePickerModal — Phase H8 · F2 parity.
 *
 * Searchable bottom-sheet modal listing active charge templates.
 * Selecting one calls POST /api/charge-templates/{id}/apply-to-job/{jobId}
 * and fires onApplied() so the parent can refresh line items.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Modal,
  Pressable,
  TextInput,
  ActivityIndicator,
  Alert,
  ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  getChargeTemplates,
  applyChargeTemplate,
  type ChargeTemplate,
} from "@/src/api/chargeTemplates";

type Props = {
  visible: boolean;
  jobId: string;
  onClose: () => void;
  onApplied: () => void;
};

export default function ChargeTemplatePickerModal({
  visible,
  jobId,
  onClose,
  onApplied,
}: Props) {
  const [templates, setTemplates] = useState<ChargeTemplate[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [applyingId, setApplyingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getChargeTemplates();
      setTemplates(res?.templates || []);
    } catch (e: any) {
      setError(e?.message || "Failed to load templates");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (visible && templates.length === 0 && !loading && !error) {
      load();
    }
  }, [visible, templates.length, loading, error, load]);

  // Reset search on close
  useEffect(() => {
    if (!visible) setSearch("");
  }, [visible]);

  const filtered = useMemo(() => {
    const needle = (search || "").trim().toLowerCase();
    if (!needle) return templates;
    return templates.filter(
      (t) =>
        (t.name || "").toLowerCase().includes(needle) ||
        (t.category || "").toLowerCase().includes(needle),
    );
  }, [templates, search]);

  const apply = async (tpl: ChargeTemplate) => {
    setApplyingId(tpl.id);
    try {
      const res = await applyChargeTemplate(tpl.id, jobId);
      const count = res?.added_count ?? (tpl.line_items || []).length;
      Alert.alert(
        "Template applied",
        `"${tpl.name}" — ${count} item${count === 1 ? "" : "s"} added`,
      );
      onClose();
      onApplied();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Apply failed");
    } finally {
      setApplyingId(null);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
    >
      <View style={s.bg}>
        <View style={s.card} testID="charge-template-picker-modal">
          <View style={s.handle} />
          <Text style={s.title}>Add from template</Text>

          {/* Search bar */}
          <View style={s.searchRow}>
            <Ionicons name="search-outline" size={16} color={colors.muted} />
            <TextInput
              style={s.searchInput}
              value={search}
              onChangeText={setSearch}
              placeholder="Search templates…"
              placeholderTextColor={colors.muted}
              testID="charge-template-search"
            />
          </View>

          {/* Content */}
          <ScrollView
            style={s.list}
            keyboardShouldPersistTaps="handled"
            testID="charge-template-list"
          >
            {loading ? (
              <View style={s.center} testID="charge-template-loading">
                <ActivityIndicator size="small" color={colors.brand} />
                <Text style={s.centerText}>Loading…</Text>
              </View>
            ) : error ? (
              <View style={s.center} testID="charge-template-error">
                <Ionicons
                  name="alert-circle-outline"
                  size={20}
                  color={colors.error}
                />
                <Text style={[s.centerText, { color: colors.error }]}>
                  {error}
                </Text>
                <Pressable style={s.retryBtn} onPress={load}>
                  <Text style={s.retryText}>Retry</Text>
                </Pressable>
              </View>
            ) : filtered.length === 0 ? (
              <View style={s.center} testID="charge-template-empty">
                <Ionicons
                  name="document-outline"
                  size={24}
                  color={colors.muted}
                />
                <Text style={s.centerText}>
                  {templates.length === 0
                    ? "No charge templates yet."
                    : "No matches."}
                </Text>
              </View>
            ) : (
              filtered.map((tpl) => (
                <Pressable
                  key={tpl.id}
                  style={[
                    s.row,
                    applyingId === tpl.id && s.rowApplying,
                  ]}
                  onPress={() => apply(tpl)}
                  disabled={applyingId != null}
                  testID={`charge-template-option-${tpl.id}`}
                >
                  <Ionicons
                    name="layers-outline"
                    size={18}
                    color={colors.brand}
                  />
                  <View style={s.rowContent}>
                    <Text style={s.rowName}>{tpl.name}</Text>
                    <Text style={s.rowMeta}>
                      {tpl.category || "custom"} ·{" "}
                      {(tpl.line_items || []).length} item
                      {(tpl.line_items || []).length === 1 ? "" : "s"}
                      {applyingId === tpl.id ? " · Applying…" : ""}
                    </Text>
                  </View>
                  <Ionicons
                    name="add-circle-outline"
                    size={20}
                    color={
                      applyingId === tpl.id ? colors.muted : colors.brand
                    }
                  />
                </Pressable>
              ))
            )}
          </ScrollView>

          {/* Footer */}
          <View style={s.footer}>
            <Pressable
              style={s.cancelBtn}
              onPress={onClose}
              testID="charge-template-cancel"
            >
              <Text style={s.cancelText}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  bg: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  card: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingTop: spacing.sm,
    maxHeight: "80%",
  },
  handle: {
    width: 36,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.surfaceTertiary,
    alignSelf: "center",
    marginBottom: spacing.sm,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.md,
  },
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
  },
  searchInput: {
    flex: 1,
    height: 40,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  list: {
    paddingHorizontal: spacing.lg,
  },
  center: {
    alignItems: "center",
    paddingVertical: spacing.xl,
    gap: spacing.sm,
  },
  centerText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
  },
  retryBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: 6,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  retryText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  rowApplying: {
    backgroundColor: colors.surfaceSecondary,
    opacity: 0.7,
  },
  rowContent: {
    flex: 1,
  },
  rowName: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  rowMeta: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  footer: {
    flexDirection: "row",
    justifyContent: "flex-end",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  cancelBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
});
