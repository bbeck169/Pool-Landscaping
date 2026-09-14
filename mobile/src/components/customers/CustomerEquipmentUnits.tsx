/**
 * Customer Equipment Units — structured equipment library (mobile).
 *
 * Uses the new /api/customer-equipment endpoints (brand/model/serial + S3 photos).
 * Separate from the legacy CustomerEquipmentLibrary (photo-only, base64).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, Modal,
  ActivityIndicator, ScrollView, KeyboardAvoidingView, Platform,
} from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { uploadFile, FileRecord } from "@/src/api/files";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const EQUIPMENT_TYPES = [
  "Filter Pump", "Cleaning Pump", "Waterfall Pump", "Filter",
  "Heater", "Salt Cell", "Cleaning System", "Automation",
  "Heater Plumbing", "Check Valves", "Jandy Valves",
];

type Photo = { id: string; filename: string; content_type: string; url: string };
type EquipmentUnit = {
  id: string;
  equipment_type: string;
  brand?: string;
  model?: string;
  serial_number?: string;
  install_date?: string;
  notes?: string;
  photos?: Photo[];
  created_at?: string;
};

type FormData = {
  equipment_type: string;
  brand: string;
  model: string;
  serial_number: string;
  install_date: string;
  notes: string;
};

const EMPTY_FORM: FormData = {
  equipment_type: "",
  brand: "",
  model: "",
  serial_number: "",
  install_date: "",
  notes: "",
};

type PhotoSlot = {
  localUri: string;
  fileId: string | null;
  uploading: boolean;
  error: string | null;
};

export default function CustomerEquipmentUnits({ customerId }: { customerId: string }) {
  const { showToast } = useToast();
  const [units, setUnits] = useState<EquipmentUnit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Form state
  const [formVisible, setFormVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [formErr, setFormErr] = useState("");
  const [saving, setSaving] = useState(false);
  const [photoSlots, setPhotoSlots] = useState<PhotoSlot[]>([]);
  const [typePicker, setTypePicker] = useState(false);

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<EquipmentUnit | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Lightbox
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.get(`/customer-equipment?customer_id=${customerId}`);
      const list = Array.isArray(data) ? data : data?.items || [];
      setUnits(list);
      setError("");
    } catch (e: any) {
      setError(e?.message || "Failed to load equipment");
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  // ── Form helpers ────────────────────────────────────────────────
  const openAdd = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setPhotoSlots([]);
    setFormErr("");
    setFormVisible(true);
  };

  const openEdit = (u: EquipmentUnit) => {
    setEditingId(u.id);
    setForm({
      equipment_type: u.equipment_type || "",
      brand: u.brand || "",
      model: u.model || "",
      serial_number: u.serial_number || "",
      install_date: u.install_date || "",
      notes: u.notes || "",
    });
    setPhotoSlots([]);
    setFormErr("");
    setFormVisible(true);
  };

  const patchForm = (key: keyof FormData, val: string) =>
    setForm((f) => ({ ...f, [key]: val }));

  const pickFormPhoto = async () => {
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) { showToast("Photo library permission required"); return; }
      const res = await ImagePicker.launchImageLibraryAsync({ quality: 0.7 });
      if (res.canceled || !res.assets?.[0]) return;
      const uri = res.assets[0].uri;
      setPhotoSlots((prev) => [...prev, { localUri: uri, fileId: null, uploading: true, error: null }]);
      const idx = photoSlots.length;
      try {
        const rec: FileRecord = await uploadFile({
          uri,
          name: `equip_${Date.now()}.jpg`,
          type: "image/jpeg",
          purpose: "customer_equipment",
        });
        setPhotoSlots((prev) => prev.map((p, i) =>
          i === idx ? { ...p, fileId: rec.id, uploading: false } : p));
      } catch (e: any) {
        setPhotoSlots((prev) => prev.map((p, i) =>
          i === idx ? { ...p, uploading: false, error: e?.message || "Upload failed" } : p));
      }
    } catch {}
  };

  const removeFormPhoto = (idx: number) =>
    setPhotoSlots((prev) => prev.filter((_, i) => i !== idx));

  const handleSave = async () => {
    if (!form.equipment_type) { setFormErr("Equipment type is required"); return; }
    setSaving(true);
    setFormErr("");
    try {
      const payload: any = { ...form, customer_id: customerId };
      let savedId = editingId;
      if (editingId) {
        await api.patch(`/customer-equipment/${editingId}`, payload);
      } else {
        const created: any = await api.post("/customer-equipment", payload);
        savedId = created?.id;
      }
      // Link any new photos
      if (savedId && photoSlots.length > 0) {
        for (const slot of photoSlots) {
          if (slot.fileId) {
            try {
              await api.patch(`/files/${slot.fileId}`, {
                linked_entity_type: "customer_equipment",
                linked_entity_id: savedId,
              });
            } catch {}
          }
        }
      }
      setFormVisible(false);
      showToast(editingId ? "Equipment updated" : "Equipment added");
      await load();
    } catch (e: any) {
      setFormErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del(`/customer-equipment/${deleteTarget.id}`);
      setDeleteTarget(null);
      showToast("Equipment deleted");
      await load();
    } catch (e: any) {
      showToast(e?.message || "Delete failed", "error");
    } finally {
      setDeleting(false);
    }
  };

  const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";

  // ── Render ──────────────────────────────────────────────────────
  if (loading) return <ActivityIndicator color={colors.brand} style={{ marginVertical: spacing.md }} testID="equipment-loading" />;
  if (error) return <Text style={s.errorText} testID="equipment-error">{error}</Text>;

  return (
    <View testID="customer-equipment-library">
      {/* Add button */}
      <Pressable style={s.addBtn} onPress={openAdd} testID="equipment-add-btn">
        <Ionicons name="add-circle" size={18} color={colors.brand} />
        <Text style={s.addBtnText}>Add Equipment</Text>
      </Pressable>

      {/* Cards list */}
      {units.length === 0 ? (
        <Text style={s.empty} testID="equipment-empty">No equipment recorded yet.</Text>
      ) : (
        units.map((u, idx) => (
          <View key={u.id} style={s.card} testID={`equipment-card-${idx}`}>
            <View style={s.cardHeader}>
              <View style={s.cardTypeBox}>
                <Ionicons name="hardware-chip-outline" size={16} color={colors.brand} />
                <Text style={s.cardType}>{u.equipment_type}</Text>
              </View>
              <View style={s.cardActions}>
                <Pressable onPress={() => openEdit(u)} hitSlop={8} testID={`equipment-edit-btn-${idx}`}>
                  <Ionicons name="create-outline" size={18} color={colors.brand} />
                </Pressable>
                <Pressable onPress={() => setDeleteTarget(u)} hitSlop={8} testID={`equipment-delete-btn-${idx}`}>
                  <Ionicons name="trash-outline" size={18} color="#B91C1C" />
                </Pressable>
              </View>
            </View>
            {u.brand || u.model ? (
              <Text style={s.cardField}>
                {[u.brand, u.model].filter(Boolean).join(" · ")}
              </Text>
            ) : null}
            {u.serial_number ? (
              <Text style={s.cardFieldMuted}>S/N: {u.serial_number}</Text>
            ) : null}
            {u.install_date ? (
              <Text style={s.cardFieldMuted}>Installed: {u.install_date}</Text>
            ) : null}
            {u.notes ? (
              <Text style={s.cardNotes} numberOfLines={2}>{u.notes}</Text>
            ) : null}
            {u.photos && u.photos.length > 0 ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={s.photoStrip}>
                {u.photos.map((p, pi) => (
                  <Pressable
                    key={p.id}
                    onPress={() => setLightboxUrl(`${BASE}${p.url}`)}
                    testID={`equipment-photo-thumb-${pi}`}
                  >
                    <Image
                      source={{ uri: `${BASE}${p.url}` }}
                      style={s.photoThumb}
                      contentFit="cover"
                    />
                  </Pressable>
                ))}
              </ScrollView>
            ) : null}
          </View>
        ))
      )}

      {/* ── Add/Edit form modal ──────────────────────────────────── */}
      <Modal visible={formVisible} transparent animationType="slide" onRequestClose={() => setFormVisible(false)} testID="equipment-form-modal">
        <KeyboardAvoidingView style={s.modalBg} behavior={Platform.OS === "ios" ? "padding" : "height"}>
          <View style={s.modalCard}>
            <View style={s.modalHeader}>
              <Text style={s.modalTitle}>{editingId ? "Edit Equipment" : "Add Equipment"}</Text>
              <Pressable onPress={() => setFormVisible(false)} testID="equipment-form-close">
                <Ionicons name="close" size={24} color={colors.onSurface} />
              </Pressable>
            </View>
            <ScrollView contentContainerStyle={s.modalBody} keyboardShouldPersistTaps="handled">
              {/* Type picker */}
              <Text style={s.label}>Type *</Text>
              <Pressable
                style={s.selectBtn}
                onPress={() => setTypePicker(true)}
                testID="equipment-type-picker"
              >
                <Text style={form.equipment_type ? s.selectText : s.selectPlaceholder}>
                  {form.equipment_type || "Select equipment type…"}
                </Text>
                <Ionicons name="chevron-down" size={16} color={colors.muted} />
              </Pressable>

              <Text style={s.label}>Brand</Text>
              <TextInput
                style={s.input}
                value={form.brand}
                onChangeText={(v) => patchForm("brand", v.slice(0, 200))}
                placeholder="e.g. Pentair"
                placeholderTextColor={colors.muted}
                testID="equipment-brand-input"
              />
              <Text style={s.label}>Model</Text>
              <TextInput
                style={s.input}
                value={form.model}
                onChangeText={(v) => patchForm("model", v.slice(0, 200))}
                placeholder="e.g. IntelliFlo VSF"
                placeholderTextColor={colors.muted}
                testID="equipment-model-input"
              />
              <Text style={s.label}>Serial Number</Text>
              <TextInput
                style={s.input}
                value={form.serial_number}
                onChangeText={(v) => patchForm("serial_number", v.slice(0, 200))}
                placeholder="e.g. SN-12345"
                placeholderTextColor={colors.muted}
                testID="equipment-serial-input"
              />
              <Text style={s.label}>Install Date</Text>
              <TextInput
                style={s.input}
                value={form.install_date}
                onChangeText={(v) => patchForm("install_date", v)}
                placeholder="YYYY-MM-DD"
                placeholderTextColor={colors.muted}
                testID="equipment-install-date-input"
              />
              <Text style={s.label}>Notes</Text>
              <TextInput
                style={[s.input, { minHeight: 80 }]}
                value={form.notes}
                onChangeText={(v) => patchForm("notes", v.slice(0, 2000))}
                placeholder="Additional notes…"
                placeholderTextColor={colors.muted}
                multiline
                textAlignVertical="top"
                testID="equipment-notes-input"
              />

              {/* Photo uploads */}
              <Text style={s.label}>Photos</Text>
              <View style={s.formPhotoRow} testID="equipment-photo-upload">
                {photoSlots.map((p, i) => (
                  <View key={`ps-${i}`} style={s.formThumbWrap} testID={`equipment-photo-thumb-${i}`}>
                    <Image source={{ uri: p.localUri }} style={s.formThumb} contentFit="cover" />
                    {p.uploading ? (
                      <View style={s.formThumbOverlay}>
                        <ActivityIndicator size="small" color="#fff" />
                      </View>
                    ) : p.error ? (
                      <View style={s.formThumbOverlayErr}>
                        <Ionicons name="alert-circle" size={16} color="#fff" />
                      </View>
                    ) : null}
                    <Pressable style={s.formThumbRemove} onPress={() => removeFormPhoto(i)} hitSlop={6}>
                      <Ionicons name="close-circle" size={20} color="#fff" />
                    </Pressable>
                  </View>
                ))}
                <Pressable style={s.formAddPhoto} onPress={pickFormPhoto} testID="equipment-photo-add-btn">
                  <Ionicons name="camera" size={20} color={colors.brand} />
                  <Text style={s.formAddPhotoText}>Add</Text>
                </Pressable>
              </View>

              {formErr ? <Text style={s.formError} testID="equipment-form-error">{formErr}</Text> : null}

              <View style={s.formBtns}>
                <Pressable style={s.cancelBtn} onPress={() => setFormVisible(false)} testID="equipment-form-cancel">
                  <Text style={s.cancelBtnText}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={[s.saveBtn, saving && { opacity: 0.6 }]}
                  onPress={handleSave}
                  disabled={saving}
                  testID="equipment-form-submit"
                >
                  <Text style={s.saveBtnText}>{saving ? "Saving…" : "Save"}</Text>
                </Pressable>
              </View>
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* ── Type picker modal ────────────────────────────────────── */}
      <Modal visible={typePicker} transparent animationType="fade" onRequestClose={() => setTypePicker(false)}>
        <Pressable style={s.typePickerBg} onPress={() => setTypePicker(false)}>
          <View />
        </Pressable>
        <View style={s.typePickerContainer}>
          <View style={s.typePickerCard}>
            <Text style={s.typePickerTitle}>Equipment Type</Text>
            <ScrollView style={{ maxHeight: 360 }}>
              {EQUIPMENT_TYPES.map((t) => (
                <Pressable
                  key={t}
                  style={[s.typePickerRow, form.equipment_type === t && s.typePickerRowActive]}
                  onPress={() => { patchForm("equipment_type", t); setTypePicker(false); }}
                  testID={`equipment-type-option-${t.replace(/\s+/g, "-").toLowerCase()}`}
                >
                  <Text style={[s.typePickerRowText, form.equipment_type === t && { color: colors.brand }]}>
                    {t}
                  </Text>
                  {form.equipment_type === t ? (
                    <Ionicons name="checkmark" size={18} color={colors.brand} />
                  ) : null}
                </Pressable>
              ))}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* ── Delete confirm modal ─────────────────────────────────── */}
      <Modal visible={!!deleteTarget} transparent animationType="fade" onRequestClose={() => setDeleteTarget(null)} testID="equipment-delete-confirm-modal">
        <Pressable style={s.typePickerBg} onPress={() => setDeleteTarget(null)}>
          <View />
        </Pressable>
        <View style={s.typePickerContainer}>
          <View style={s.deleteCard}>
            <Text style={s.deleteTitle}>Delete equipment?</Text>
            <Text style={s.deleteBody}>
              This will remove {`"${deleteTarget?.equipment_type}"`} ({deleteTarget?.brand || "—"} {deleteTarget?.model || "—"}) from this customer&apos;s equipment library.
            </Text>
            <View style={s.deleteBtns}>
              <Pressable style={s.cancelBtn} onPress={() => setDeleteTarget(null)} testID="equipment-delete-cancel-btn">
                <Text style={s.cancelBtnText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[s.deleteConfirmBtn, deleting && { opacity: 0.6 }]}
                onPress={handleDelete}
                disabled={deleting}
                testID="equipment-delete-confirm-btn"
              >
                <Text style={s.deleteConfirmText}>{deleting ? "Deleting…" : "Delete"}</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* ── Lightbox ─────────────────────────────────────────────── */}
      <Modal visible={!!lightboxUrl} transparent animationType="fade" onRequestClose={() => setLightboxUrl(null)}>
        <Pressable style={s.lightboxBg} onPress={() => setLightboxUrl(null)}>
          <View style={s.lightboxWrap}>
            {lightboxUrl ? (
              <Image source={{ uri: lightboxUrl }} style={s.lightboxImg} contentFit="contain" />
            ) : null}
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  addBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, backgroundColor: colors.brandTertiary, borderRadius: radius.md,
    paddingVertical: 12, marginBottom: spacing.md,
  },
  addBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  empty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginBottom: spacing.md },
  errorText: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#B91C1C", marginBottom: spacing.md },
  // Card
  card: {
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, padding: spacing.md, marginBottom: spacing.sm,
  },
  cardHeader: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6,
  },
  cardTypeBox: { flexDirection: "row", alignItems: "center", gap: 6, flex: 1 },
  cardType: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  cardActions: { flexDirection: "row", gap: spacing.md },
  cardField: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, marginTop: 2 },
  cardFieldMuted: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 2 },
  cardNotes: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 4, fontStyle: "italic" },
  photoStrip: { marginTop: spacing.sm },
  photoThumb: { width: 64, height: 64, borderRadius: radius.sm, marginRight: spacing.xs, backgroundColor: colors.surfaceMuted },
  // Modal
  modalBg: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)", justifyContent: "flex-end" },
  modalCard: {
    backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    maxHeight: "90%", overflow: "hidden",
  },
  modalHeader: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    paddingHorizontal: spacing.md, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  modalBody: { padding: spacing.md, gap: spacing.sm, paddingBottom: 60 },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 10,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.background,
  },
  selectBtn: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 12,
    backgroundColor: colors.background,
  },
  selectText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  selectPlaceholder: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  // Form photos
  formPhotoRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  formThumbWrap: { width: 64, height: 64, borderRadius: radius.sm, overflow: "hidden", backgroundColor: colors.surfaceMuted },
  formThumb: { width: "100%", height: "100%" },
  formThumbOverlay: {
    ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.5)",
    alignItems: "center", justifyContent: "center",
  },
  formThumbOverlayErr: {
    ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(185,28,28,0.6)",
    alignItems: "center", justifyContent: "center",
  },
  formThumbRemove: { position: "absolute", top: 2, right: 2 },
  formAddPhoto: {
    width: 64, height: 64, borderRadius: radius.sm, borderWidth: 1, borderStyle: "dashed",
    borderColor: colors.border, alignItems: "center", justifyContent: "center", gap: 2,
  },
  formAddPhotoText: { fontFamily: font.bold, fontSize: 10, color: colors.brand },
  formError: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#B91C1C" },
  formBtns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, marginTop: spacing.md },
  cancelBtn: {
    minHeight: 44, paddingHorizontal: spacing.md, alignItems: "center", justifyContent: "center",
    borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border,
  },
  cancelBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  saveBtn: {
    minHeight: 44, paddingHorizontal: spacing.lg, alignItems: "center", justifyContent: "center",
    borderRadius: radius.sm, backgroundColor: colors.brand,
  },
  saveBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  // Type picker
  typePickerBg: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)" },
  typePickerContainer: {
    position: "absolute", left: 0, right: 0, bottom: 0, top: 0,
    justifyContent: "center", alignItems: "center", paddingHorizontal: spacing.lg,
  },
  typePickerCard: {
    width: "100%", maxWidth: 360, backgroundColor: colors.surface,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, overflow: "hidden",
  },
  typePickerTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  typePickerRow: {
    paddingHorizontal: spacing.md, paddingVertical: 12, flexDirection: "row",
    justifyContent: "space-between", alignItems: "center",
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  typePickerRowActive: { backgroundColor: colors.brandTertiary },
  typePickerRowText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  // Delete
  deleteCard: { width: "100%", maxWidth: 360, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md },
  deleteTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#B91C1C", marginBottom: spacing.sm },
  deleteBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, marginBottom: spacing.md },
  deleteBtns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm },
  deleteConfirmBtn: { minHeight: 44, paddingHorizontal: spacing.md, alignItems: "center", justifyContent: "center", borderRadius: radius.sm, backgroundColor: "#B91C1C" },
  deleteConfirmText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  // Lightbox
  lightboxBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.9)", justifyContent: "center", alignItems: "center" },
  lightboxWrap: { width: "90%", aspectRatio: 1 },
  lightboxImg: { width: "100%", height: "100%" },
});
