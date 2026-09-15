/**
 * Task 1 · Feb-2026 — Mobile mirror of the web ``/admin/tags`` CRUD
 * page (Queue Item 2 web equivalent).
 *
 * Feature parity:
 *   • Tenant tag registry list with usage-count column.
 *   • "New Tag" affordance — modal with name + color-swatch picker.
 *   • Edit tag inline (opens the same modal in edit mode).
 *   • Delete tag with hard-confirm showing live usage count.
 *   • System tags (is_system:true) locked with icon + disabled
 *     Edit / Delete + tooltip copy.
 *   • Search input auto-appears once the tag count > 10.
 *
 * Preserves the existing backend contract — same endpoints
 * (`/customer-tags`, `/customer-tags/:id`) as the web page.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, Pressable, FlatList, StyleSheet, Modal, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

const PALETTE = [
  "#DBEAFE", "#FEE2E2", "#DCFCE7", "#FEF3C7", "#EDE9FE",
  "#CFFAFE", "#FCE7F3", "#FEDCBB", "#E0E7FF", "#D1FAE5",
  "#22C55E", "#94A3B8",
];
const SEARCH_VISIBILITY_THRESHOLD = 10;
const SYSTEM_LOCK_TOOLTIP = "System tags cannot be modified";

type Tag = {
  id: string;
  name: string;
  color: string;
  is_system?: boolean;
  is_archived?: boolean;
  usage_count?: number;
};

function normalizeRows(payload: any): Tag[] {
  if (Array.isArray(payload)) return payload;
  return payload?.items || payload?.tags || [];
}

// ═════════════════════════════════════════════════════════════════
// Editor modal (create + edit share the same UI).
// ═════════════════════════════════════════════════════════════════
function TagEditorModal({
  visible, mode, initial, onClose, onSubmit, busy,
}: {
  visible: boolean;
  mode: "create" | "edit";
  initial?: Tag | null;
  onClose: () => void;
  onSubmit: (payload: { name?: string; color?: string }) => void;
  busy: boolean;
}) {
  const [name, setName] = useState("");
  const [color, setColor] = useState(PALETTE[0]);
  useEffect(() => {
    if (!visible) return;
    setName(initial?.name || "");
    setColor(initial?.color || PALETTE[0]);
  }, [visible, initial]);

  const isEdit = mode === "edit";
  const trimmed = (name || "").trim();
  const canSubmit = trimmed.length > 0 && trimmed.length <= 40 && !busy && (
    !isEdit || trimmed !== (initial?.name || "") || color !== (initial?.color || "")
  );
  const submit = () => {
    if (!canSubmit) return;
    const payload: { name?: string; color?: string } = {};
    if (!isEdit || trimmed !== (initial?.name || "")) payload.name = trimmed;
    if (!isEdit || color !== (initial?.color || "")) payload.color = color;
    onSubmit(payload);
  };

  return (
    <Modal visible={visible} transparent animationType="slide"
             onRequestClose={onClose}>
      <View style={ss.modalScrim}>
        <View style={ss.modalCard} testID="tag-editor-modal">
          <View style={ss.modalHeader}>
            <Text style={ss.modalTitle}>{isEdit ? "Edit tag" : "New tag"}</Text>
            <Pressable onPress={onClose} testID="tag-editor-close">
              <Ionicons name="close" size={22} color={colors.muted} />
            </Pressable>
          </View>
          <Text style={ss.label}>Name</Text>
          <AppTextInput
            value={name}
            onChangeText={setName}
            placeholder="e.g. VIP"
            maxLength={40}
            style={ss.input}
            autoFocus
            testID="tag-editor-name-input"
          />
          <Text style={ss.hint}>1–40 characters, no leading/trailing whitespace.</Text>

          <Text style={ss.label}>Color</Text>
          <View style={ss.paletteRow} testID="tag-editor-palette">
            {PALETTE.map((c) => (
              <Pressable
                key={c}
                onPress={() => setColor(c)}
                style={[
                  ss.swatch, { backgroundColor: c },
                  c.toLowerCase() === color.toLowerCase() ? ss.swatchActive : null,
                ]}
                testID={`tag-editor-palette-swatch-${c.replace("#", "").toLowerCase()}`}
              />
            ))}
          </View>

          <View style={ss.modalActions}>
            <Pressable onPress={onClose} style={ss.btnSecondary}
                          testID="tag-editor-cancel">
              <Text style={ss.btnSecondaryText}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={submit}
              disabled={!canSubmit}
              style={[ss.btnPrimary, !canSubmit ? { opacity: 0.5 } : null]}
              testID="tag-editor-submit"
            >
              <Text style={ss.btnPrimaryText}>
                {busy ? "Saving…" : (isEdit ? "Save changes" : "Create tag")}
              </Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// ═════════════════════════════════════════════════════════════════
// Delete confirm modal.
// ═════════════════════════════════════════════════════════════════
function DeleteConfirmModal({
  visible, tag, onClose, onConfirm, busy,
}: {
  visible: boolean;
  tag: Tag | null;
  onClose: () => void;
  onConfirm: () => void;
  busy: boolean;
}) {
  if (!tag) return null;
  const usage = Number(tag.usage_count || 0);
  return (
    <Modal visible={visible} transparent animationType="fade"
             onRequestClose={onClose}>
      <View style={ss.modalScrim}>
        <View style={ss.modalCard} testID="admin-tag-delete-modal">
          <View style={ss.modalHeader}>
            <Text style={ss.modalTitle}>Delete tag “{tag.name}”?</Text>
            <Pressable onPress={onClose} testID="admin-tag-delete-close">
              <Ionicons name="close" size={22} color={colors.muted} />
            </Pressable>
          </View>
          <Text style={[ss.hint, { marginBottom: spacing.md }]}>
            {usage > 0
              ? `This tag is applied to ${usage} customer${usage === 1 ? "" : "s"}. Deleting will remove it from all of them. This action cannot be undone.`
              : "This tag is not applied to any customer. Deleting is safe."}
          </Text>
          <View style={ss.modalActions}>
            <Pressable onPress={onClose} style={ss.btnSecondary}
                          testID="admin-tag-delete-cancel">
              <Text style={ss.btnSecondaryText}>Cancel</Text>
            </Pressable>
            <Pressable onPress={onConfirm} disabled={busy}
                          style={[ss.btnDanger, busy ? { opacity: 0.5 } : null]}
                          testID="admin-tag-delete-confirm">
              <Text style={ss.btnPrimaryText}>{busy ? "Deleting…" : "Delete tag"}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

// ═════════════════════════════════════════════════════════════════
// Main page.
// ═════════════════════════════════════════════════════════════════
export default function AdminTagsPage() {
  const [rows, setRows] = useState<Tag[] | null>(null);
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<{ open: boolean; mode: "create" | "edit"; tag: Tag | null }>({
    open: false, mode: "create", tag: null,
  });
  const [editorBusy, setEditorBusy] = useState(false);
  const [delModal, setDelModal] = useState<{ open: boolean; tag: Tag | null }>({
    open: false, tag: null,
  });
  const [delBusy, setDelBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/customer-tags");
      setRows(normalizeRows(r));
    } catch { setRows([]); }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const filtered = useMemo(() => {
    const q = (query || "").trim().toLowerCase();
    const all = rows || [];
    if (!q) return all;
    return all.filter((r) => (r.name || "").toLowerCase().includes(q));
  }, [rows, query]);
  const totalCount = (rows || []).length;
  const showSearch = totalCount > SEARCH_VISIBILITY_THRESHOLD;

  const openCreate = () => setEditor({ open: true, mode: "create", tag: null });
  const openEdit = (tag: Tag) => setEditor({ open: true, mode: "edit", tag });
  const closeEditor = () => { if (!editorBusy) setEditor({ open: false, mode: "create", tag: null }); };

  const submitEditor = async (payload: { name?: string; color?: string }) => {
    setEditorBusy(true);
    try {
      if (editor.mode === "create") {
        await api.post("/customer-tags", payload);
      } else if (editor.tag) {
        await api.patch(`/customer-tags/${editor.tag.id}`, payload);
      }
      setEditor({ open: false, mode: "create", tag: null });
      load();
    } catch { /* silent — the web toast pattern isn't wired here yet */ }
    finally { setEditorBusy(false); }
  };
  const openDelete = (tag: Tag) => setDelModal({ open: true, tag });
  const closeDelete = () => { if (!delBusy) setDelModal({ open: false, tag: null }); };
  const submitDelete = async () => {
    if (!delModal.tag) return;
    setDelBusy(true);
    try {
      await api.del(`/customer-tags/${delModal.tag.id}`);
      setDelModal({ open: false, tag: null });
      load();
    } catch { /* silent */ }
    finally { setDelBusy(false); }
  };

  return (
    <View style={ss.page} testID="admin-tags-page">
      <Header title="Customer Tags" />

      <View style={ss.topRow}>
        <Text style={ss.subtitle}>
          Manage the tenant tag registry. {totalCount} tag{totalCount === 1 ? "" : "s"}.
        </Text>
        <Pressable
          onPress={openCreate}
          style={ss.btnPrimarySmall}
          testID="admin-tags-new-btn"
        >
          <Ionicons name="add" size={14} color="#fff" />
          <Text style={ss.btnPrimaryText}> New tag</Text>
        </Pressable>
      </View>

      {showSearch ? (
        <View style={ss.searchWrap}>
          <Ionicons name="search" size={14} color={colors.muted} style={ss.searchIcon} />
          <AppTextInput
            value={query}
            onChangeText={setQuery}
            placeholder={`Search ${totalCount} tags…`}
            style={ss.searchInput}
            testID="admin-tags-search-input"
          />
        </View>
      ) : null}

      {rows === null ? (
        <ActivityIndicator style={{ marginTop: spacing.xl }} />
      ) : (
        <FlatList
          data={filtered}
          keyExtractor={(t) => t.id}
          ListEmptyComponent={
            <Text style={ss.empty} testID="admin-tags-empty">
              {totalCount === 0 ? "No tags yet." : "No tags match your search."}
            </Text>
          }
          renderItem={({ item }) => (
            <TagRow tag={item} onEdit={openEdit} onDelete={openDelete} />
          )}
        />
      )}

      <TagEditorModal
        visible={editor.open}
        mode={editor.mode}
        initial={editor.tag}
        onClose={closeEditor}
        onSubmit={submitEditor}
        busy={editorBusy}
      />
      <DeleteConfirmModal
        visible={delModal.open}
        tag={delModal.tag}
        onClose={closeDelete}
        onConfirm={submitDelete}
        busy={delBusy}
      />
    </View>
  );
}

function TagRow({
  tag, onEdit, onDelete,
}: {
  tag: Tag;
  onEdit: (t: Tag) => void;
  onDelete: (t: Tag) => void;
}) {
  const isSystem = !!tag.is_system;
  const usage = Number(tag.usage_count || 0);
  return (
    <View style={ss.row} testID={`admin-tag-row-${tag.id}`}>
      <View style={[ss.swatchSmall, { backgroundColor: tag.color || "#94A3B8" }]} />
      <View style={{ flex: 1 }}>
        <View style={ss.rowTitleLine}>
          {isSystem ? (
            <View testID={`admin-tag-system-lock-${tag.id}`}
                     style={{ marginRight: 4 }}>
              <Ionicons name="lock-closed" size={12} color={colors.muted} />
            </View>
          ) : null}
          <Text style={ss.rowName}>{tag.name}</Text>
          {isSystem ? (
            <View style={ss.systemBadge}>
              <Text style={ss.systemBadgeText}>System</Text>
            </View>
          ) : null}
        </View>
        <Text style={ss.rowMeta} testID={`admin-tag-usage-${tag.id}`}>
          {usage} customer{usage === 1 ? "" : "s"}
        </Text>
      </View>
      <Pressable
        onPress={() => !isSystem && onEdit(tag)}
        disabled={isSystem}
        style={[ss.iconBtn, isSystem ? { opacity: 0.35 } : null]}
        testID={`admin-tag-edit-btn-${tag.id}`}
        accessibilityLabel={isSystem ? SYSTEM_LOCK_TOOLTIP : "Edit tag"}
      >
        <Ionicons name="create-outline" size={16} color={colors.onSurfaceSecondary} />
      </Pressable>
      <Pressable
        onPress={() => !isSystem && onDelete(tag)}
        disabled={isSystem}
        style={[ss.iconBtnDanger, isSystem ? { opacity: 0.35 } : null]}
        testID={`admin-tag-delete-btn-${tag.id}`}
        accessibilityLabel={isSystem ? SYSTEM_LOCK_TOOLTIP : "Delete tag"}
      >
        <Ionicons name="trash-outline" size={16} color={colors.error} />
      </Pressable>
    </View>
  );
}

const ss = StyleSheet.create({
  page: { flex: 1, backgroundColor: colors.surface },
  topRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  subtitle: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  btnPrimarySmall: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderRadius: radius.md,
  },
  searchWrap: {
    marginHorizontal: spacing.lg, marginBottom: spacing.sm,
    flexDirection: "row", alignItems: "center",
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md,
    backgroundColor: colors.surface,
  },
  searchIcon: { marginRight: 6 },
  searchInput: { flex: 1, paddingVertical: 8, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  empty: { textAlign: "center", marginTop: spacing.xl, fontFamily: font.regular, color: colors.muted, fontSize: fontSize.sm },
  row: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: spacing.md, paddingHorizontal: spacing.lg,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
    gap: spacing.sm,
  },
  swatchSmall: { width: 20, height: 20, borderRadius: 10, borderWidth: 1, borderColor: colors.border },
  rowTitleLine: { flexDirection: "row", alignItems: "center", gap: 6 },
  rowName: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  rowMeta: { fontFamily: font.regular, fontSize: 11, color: colors.muted, marginTop: 2 },
  systemBadge: { marginLeft: 6, backgroundColor: colors.surfaceTertiary, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  systemBadgeText: { fontFamily: font.bold, fontSize: 9, color: colors.onSurfaceSecondary, textTransform: "uppercase" },
  iconBtn: {
    padding: 8, borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  iconBtnDanger: {
    padding: 8, borderRadius: radius.sm,
    borderWidth: 1, borderColor: "#FECACA",
    backgroundColor: "#FEF2F2",
  },
  modalScrim: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
    justifyContent: "center", alignItems: "center", paddingHorizontal: spacing.lg,
  },
  modalCard: {
    width: "100%", maxWidth: 400,
    backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: spacing.lg,
  },
  modalHeader: {
    flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, flex: 1 },
  label: { fontFamily: font.bold, fontSize: 11, color: colors.onSurfaceSecondary, marginBottom: 4, marginTop: spacing.sm },
  input: {
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, paddingVertical: 10,
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  hint: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 4 },
  paletteRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 },
  swatch: { width: 32, height: 32, borderRadius: 16, borderWidth: 1, borderColor: colors.border },
  swatchActive: { borderWidth: 2, borderColor: colors.brandPrimary },
  modalActions: {
    flexDirection: "row", justifyContent: "flex-end", gap: 8, marginTop: spacing.lg,
  },
  btnSecondary: {
    paddingHorizontal: spacing.md, paddingVertical: 10,
    borderRadius: radius.md, backgroundColor: colors.surfaceSecondary,
  },
  btnSecondaryText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  btnPrimary: {
    paddingHorizontal: spacing.md, paddingVertical: 10,
    borderRadius: radius.md, backgroundColor: colors.brandPrimary,
  },
  btnDanger: {
    paddingHorizontal: spacing.md, paddingVertical: 10,
    borderRadius: radius.md, backgroundColor: colors.error,
  },
  btnPrimaryText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
