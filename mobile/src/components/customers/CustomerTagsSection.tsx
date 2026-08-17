/**
 * Task 1 · Feb-2026 — Mobile mirror of the web ``CustomerTagsCard``.
 *
 * Chip render of attached tags + tap-to-add bottom sheet with
 * search, existing-tag selection, and an inline "Create new: <query>"
 * affordance. Reuses the same backend surface as the web:
 *
 *   * GET  /customer-tags                            — global list
 *   * POST /customer-tags/{id}/attach {customer_id}  — attach
 *   * POST /customer-tags/{id}/detach {customer_id}  — detach
 *   * POST /customer-tags        {name, color}       — create new
 *
 * The web picker also exposes a bulk PATCH but that's out of scope
 * for the mobile customer detail (single-customer view only).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, Pressable, StyleSheet, Modal, TextInput, FlatList,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Tag = {
  id: string;
  name: string;
  color: string;
  is_system?: boolean;
};

type Props = {
  customerId: string;
  value?: Tag[];
  onChange?: (nextTags: Tag[]) => void;
};

export default function CustomerTagsSection({
  customerId, value, onChange,
}: Props) {
  const attached: Tag[] = useMemo(() =>
    (Array.isArray(value) ? value : []) as Tag[], [value]);
  const [sheetOpen, setSheetOpen] = useState(false);

  const detach = async (tag: Tag) => {
    try {
      await api.post(`/customer-tags/${tag.id}/detach`, { customer_id: customerId });
      const next = attached.filter((t) => t.id !== tag.id);
      onChange?.(next);
    } catch { /* silent */ }
  };

  return (
    <View style={ss.card} testID="customer-tags-section">
      <View style={ss.header}>
        <Ionicons name="pricetag-outline" size={14} color={colors.onSurface} />
        <Text style={ss.title}>Tags</Text>
        <View style={ss.countPill} testID="customer-tags-section-count">
          <Text style={ss.countText}>{attached.length}</Text>
        </View>
      </View>

      {attached.length === 0 ? (
        <Text style={ss.empty} testID="customer-tags-section-empty">
          No tags yet. Tap "+ Tag" below to attach one.
        </Text>
      ) : (
        <View style={ss.chipRow}>
          {attached.map((t) => (
            <View
              key={t.id}
              style={[ss.chip, { backgroundColor: t.color || "#DBEAFE" }]}
              testID={`customer-tag-chip-${t.id}`}
            >
              <Text style={ss.chipText}>{t.name}</Text>
              <Pressable onPress={() => detach(t)}
                            testID={`customer-tag-chip-remove-${t.id}`}>
                <Ionicons name="close" size={12} color="#0F172A" />
              </Pressable>
            </View>
          ))}
        </View>
      )}

      <Pressable
        onPress={() => setSheetOpen(true)}
        style={ss.addBtn}
        testID="customer-tags-open-picker"
      >
        <Ionicons name="add" size={14} color={colors.brandPrimary} />
        <Text style={ss.addBtnText}>Tag</Text>
      </Pressable>

      <TagPickerSheet
        visible={sheetOpen}
        customerId={customerId}
        attached={attached}
        onClose={() => setSheetOpen(false)}
        onAttached={(t) => {
          const next = [...attached, t];
          onChange?.(next);
        }}
      />
    </View>
  );
}

// ═════════════════════════════════════════════════════════════════
// Bottom sheet picker.
// ═════════════════════════════════════════════════════════════════
function TagPickerSheet({
  visible, customerId, attached, onClose, onAttached,
}: {
  visible: boolean;
  customerId: string;
  attached: Tag[];
  onClose: () => void;
  onAttached: (tag: Tag) => void;
}) {
  const [all, setAll] = useState<Tag[] | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setAll(null);
    try {
      const r = await api.get("/customer-tags");
      const items = Array.isArray(r) ? r : (r?.items || r?.tags || []);
      setAll(items);
    } catch { setAll([]); }
  }, []);

  useEffect(() => {
    if (visible) { setQuery(""); load(); }
  }, [visible, load]);

  const attachedIds = useMemo(() => new Set(attached.map((t) => t.id)),
                                   [attached]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const src = (all || []).filter((t) => !attachedIds.has(t.id));
    if (!q) return src;
    return src.filter((t) => (t.name || "").toLowerCase().includes(q));
  }, [all, query, attachedIds]);

  const exactMatch = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return false;
    return (all || []).some((t) => (t.name || "").toLowerCase() === q);
  }, [all, query]);

  const attach = async (tag: Tag) => {
    setBusy(tag.id);
    try {
      await api.post(`/customer-tags/${tag.id}/attach`,
                        { customer_id: customerId });
      onAttached(tag);
      onClose();
    } catch { /* silent */ }
    finally { setBusy(null); }
  };
  const createAndAttach = async () => {
    const name = query.trim();
    if (!name) return;
    setBusy("__create__");
    try {
      const t = await api.post("/customer-tags", { name });
      await api.post(`/customer-tags/${t.id}/attach`,
                        { customer_id: customerId });
      onAttached(t);
      onClose();
    } catch { /* silent */ }
    finally { setBusy(null); }
  };

  return (
    <Modal visible={visible} transparent animationType="slide"
             onRequestClose={onClose}>
      <View style={ss.sheetScrim}>
        <View style={ss.sheet} testID="customer-tags-picker-sheet">
          <View style={ss.sheetHeader}>
            <Text style={ss.sheetTitle}>Attach a tag</Text>
            <Pressable onPress={onClose} testID="customer-tags-picker-close">
              <Ionicons name="close" size={22} color={colors.muted} />
            </Pressable>
          </View>
          <View style={ss.searchWrap}>
            <Ionicons name="search" size={14} color={colors.muted}
                        style={{ marginRight: 6 }} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search or create new…"
              style={ss.searchInput}
              autoFocus
              testID="customer-tags-picker-search"
            />
          </View>
          {all === null ? (
            <ActivityIndicator style={{ marginVertical: spacing.lg }} />
          ) : (
            <FlatList
              data={filtered}
              keyExtractor={(t) => t.id}
              ListHeaderComponent={
                query.trim() && !exactMatch ? (
                  <Pressable
                    onPress={createAndAttach}
                    style={ss.createRow}
                    testID="customer-tags-picker-create"
                  >
                    <Ionicons name="add-circle-outline" size={16}
                                color={colors.brandPrimary} />
                    <Text style={ss.createText}>
                      Create new: <Text style={ss.createBold}>{query.trim()}</Text>
                    </Text>
                  </Pressable>
                ) : null
              }
              renderItem={({ item }) => (
                <Pressable
                  onPress={() => attach(item)}
                  disabled={busy === item.id}
                  style={ss.itemRow}
                  testID={`customer-tags-picker-item-${item.id}`}
                >
                  <View style={[ss.itemSwatch,
                                    { backgroundColor: item.color || "#94A3B8" }]} />
                  <Text style={ss.itemName}>{item.name}</Text>
                  {item.is_system ? (
                    <View style={ss.systemBadge}>
                      <Text style={ss.systemBadgeText}>System</Text>
                    </View>
                  ) : null}
                </Pressable>
              )}
              ListEmptyComponent={
                <Text style={ss.empty}>No matches.</Text>
              }
            />
          )}
        </View>
      </View>
    </Modal>
  );
}

const ss = StyleSheet.create({
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.lg, padding: spacing.md,
    marginHorizontal: spacing.lg, marginBottom: spacing.md,
  },
  header: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.sm },
  title: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface, flex: 1 },
  countPill: {
    backgroundColor: colors.surfaceTertiary,
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999,
  },
  countText: { fontFamily: font.semibold, fontSize: 10, color: colors.onSurfaceSecondary },
  empty: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginBottom: 6 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 6 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
  },
  chipText: { fontFamily: font.semibold, fontSize: 11, color: "#0F172A" },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    alignSelf: "flex-start",
    paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: 999, borderWidth: 1, borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  addBtnText: { fontFamily: font.semibold, fontSize: 11, color: colors.brandPrimary },
  sheetScrim: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: spacing.lg, maxHeight: "80%",
  },
  sheetHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  sheetTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  searchWrap: {
    flexDirection: "row", alignItems: "center",
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md,
    backgroundColor: colors.surface, marginBottom: spacing.md,
  },
  searchInput: { flex: 1, paddingVertical: 8, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  createRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 10, paddingHorizontal: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  createText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  createBold: { fontFamily: font.bold, color: colors.brandPrimary },
  itemRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, paddingHorizontal: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  itemSwatch: { width: 16, height: 16, borderRadius: 8, borderWidth: 1, borderColor: colors.border },
  itemName: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  systemBadge: { backgroundColor: colors.surfaceTertiary, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  systemBadgeText: { fontFamily: font.bold, fontSize: 9, color: colors.onSurfaceSecondary, textTransform: "uppercase" },
});
