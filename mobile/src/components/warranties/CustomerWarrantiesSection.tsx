/**
 * CustomerWarrantiesSection — v1.5 CRUD warranties list
 * for the admin/tech customer detail screen.
 *
 * Read list:   GET /api/customers/{customer_id}/warranties
 * Create:      POST /api/warranties/contracts
 * Update:      PATCH /api/warranties/contracts/{cid}
 * Delete:      DELETE /api/warranties/contracts/{cid}  (soft)
 * Link opts:   GET /api/customers/{customer_id}/warranties/link-options?type=install|equipment
 *
 * Portal stays read-only (v1 posture) — this CRUD is admin/tech only.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal,
  ActivityIndicator, ScrollView, KeyboardAvoidingView, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import WarrantyCard, { WarrantyContract } from "./WarrantyCard";
import AppTextInput from "@/src/components/ui/AppTextInput";

// ── Form types ─────────────────────────────────────────────────────
type FormData = {
  contract_name: string;
  provider: string;
  coverage_start: string;
  coverage_end: string;
  linked_type: "none" | "install" | "equipment";
  linked_id: string;
  notes: string;
};

const EMPTY_FORM: FormData = {
  contract_name: "",
  provider: "",
  coverage_start: "",
  coverage_end: "",
  linked_type: "none",
  linked_id: "",
  notes: "",
};

const LINKED_TYPES: { value: FormData["linked_type"]; label: string }[] = [
  { value: "none", label: "None" },
  { value: "install", label: "Install Job" },
  { value: "equipment", label: "Equipment" },
];

type LinkOption = { id: string; label: string };

// ── Component ──────────────────────────────────────────────────────
export default function CustomerWarrantiesSection({
  customerId,
}: {
  customerId: string;
}) {
  const { showToast } = useToast();
  const [items, setItems] = useState<WarrantyContract[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Form state
  const [formVisible, setFormVisible] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormData>(EMPTY_FORM);
  const [formErr, setFormErr] = useState("");
  const [saving, setSaving] = useState(false);

  // Link options
  const [linkOptions, setLinkOptions] = useState<LinkOption[]>([]);
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkTypePicker, setLinkTypePicker] = useState(false);
  const [linkIdPicker, setLinkIdPicker] = useState(false);

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState<WarrantyContract | null>(null);
  const [deleting, setDeleting] = useState(false);

  // ── Load list ────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setError("");
    try {
      const res = await api.get(`/customers/${customerId}/warranties`);
      const list = res?.items || (Array.isArray(res) ? res : []);
      setItems(list);
    } catch (e: any) {
      setError(e?.message || "Failed to load warranties");
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  // ── Link options loader ──────────────────────────────────────────
  const loadLinkOptions = useCallback(async (type: string) => {
    if (type === "none") { setLinkOptions([]); return; }
    setLinkLoading(true);
    try {
      const opts = await api.get(
        `/customers/${customerId}/warranties/link-options?type=${type}`,
      );
      const arr = Array.isArray(opts) ? opts : [];
      setLinkOptions(
        arr.map((o: any) => ({
          id: o.id,
          label:
            type === "install"
              ? `${o.service_type || "Install"} · ${o.service_date || "N/A"}`
              : `${o.equipment_type || "Equipment"} · ${[o.brand, o.model].filter(Boolean).join(" ")}`,
        })),
      );
    } catch {
      setLinkOptions([]);
    } finally {
      setLinkLoading(false);
    }
  }, [customerId]);

  // ── Form helpers ─────────────────────────────────────────────────
  const openAdd = () => {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setLinkOptions([]);
    setFormErr("");
    setFormVisible(true);
  };

  const openEdit = (w: WarrantyContract) => {
    const lt = (w.linked_type === "install" || w.linked_type === "equipment") ? w.linked_type : "none";
    setEditingId(w.id);
    setForm({
      contract_name: w.contract_name || "",
      provider: w.provider || "",
      coverage_start: w.coverage_start ? w.coverage_start.slice(0, 10) : "",
      coverage_end: w.coverage_end ? w.coverage_end.slice(0, 10) : "",
      linked_type: lt,
      linked_id: w.linked_id || "",
      notes: w.notes || "",
    });
    setFormErr("");
    setFormVisible(true);
    if (lt !== "none") loadLinkOptions(lt);
  };

  const patchForm = (key: keyof FormData, val: string) =>
    setForm((f) => ({ ...f, [key]: val }));

  const handleLinkedTypeChange = (val: FormData["linked_type"]) => {
    patchForm("linked_type", val);
    patchForm("linked_id", "");
    setLinkTypePicker(false);
    if (val !== "none") loadLinkOptions(val);
    else setLinkOptions([]);
  };

  const handleLinkIdSelect = (id: string) => {
    patchForm("linked_id", id);
    setLinkIdPicker(false);
  };

  // ── Save ─────────────────────────────────────────────────────────
  const handleSave = async () => {
    if (!form.contract_name.trim()) {
      setFormErr("Contract name is required");
      return;
    }
    setSaving(true);
    setFormErr("");
    try {
      const payload: any = {
        contract_name: form.contract_name.trim(),
        provider: form.provider.trim() || undefined,
        coverage_start: form.coverage_start || undefined,
        coverage_end: form.coverage_end || undefined,
        linked_type: form.linked_type,
        linked_id: form.linked_type === "none" ? null : (form.linked_id || null),
        notes: form.notes.trim() || undefined,
      };

      if (editingId) {
        await api.patch(`/warranties/contracts/${editingId}`, payload);
        showToast("Warranty updated");
      } else {
        payload.customer_id = customerId;
        await api.post("/warranties/contracts", payload);
        showToast("Warranty added");
      }
      setFormVisible(false);
      await load();
    } catch (e: any) {
      setFormErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  // ── Delete ───────────────────────────────────────────────────────
  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del(`/warranties/contracts/${deleteTarget.id}`);
      setDeleteTarget(null);
      showToast("Warranty deleted");
      await load();
    } catch (e: any) {
      showToast(e?.message || "Delete failed", "error");
    } finally {
      setDeleting(false);
    }
  };

  // ── Selected link option label ───────────────────────────────────
  const selectedLinkLabel = linkOptions.find((o) => o.id === form.linked_id)?.label;

  // ── Render ───────────────────────────────────────────────────────
  if (loading) {
    return (
      <ActivityIndicator
        color={colors.brand}
        style={{ marginVertical: spacing.md }}
        testID="warranty-loading"
      />
    );
  }

  if (error) {
    return (
      <Text style={s.errorText} testID="warranty-error">{error}</Text>
    );
  }

  return (
    <View testID="customer-warranties-section">
      {/* Add button */}
      <Pressable style={s.addBtn} onPress={openAdd} testID="warranty-add-btn">
        <Ionicons name="add-circle" size={18} color={colors.brand} />
        <Text style={s.addBtnText}>Add Warranty</Text>
      </Pressable>

      {items.length === 0 ? (
        <Text style={s.empty} testID="warranty-empty">
          No warranty contracts on file.
        </Text>
      ) : (
        <View testID="warranty-list">
          {items.map((w, i) => (
            <WarrantyCard
              key={w.id}
              warranty={w}
              index={i}
              testIdPrefix="warranty"
              onEdit={openEdit}
              onDelete={setDeleteTarget}
            />
          ))}
        </View>
      )}

      {/* ── Add/Edit modal ──────────────────────────────────────── */}
      <Modal
        visible={formVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setFormVisible(false)}
        testID="warranty-modal"
      >
        <KeyboardAvoidingView
          style={s.modalBg}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          <View style={s.modalCard}>
            <View style={s.modalHeader}>
              <Text style={s.modalTitle}>
                {editingId ? "Edit Warranty" : "Add Warranty"}
              </Text>
              <Pressable onPress={() => setFormVisible(false)} testID="warranty-modal-cancel-btn">
                <Ionicons name="close" size={24} color={colors.onSurface} />
              </Pressable>
            </View>
            <ScrollView
              contentContainerStyle={s.modalBody}
              keyboardShouldPersistTaps="handled"
            >
              {/* Contract name */}
              <Text style={s.label}>Contract Name *</Text>
              <AppTextInput
                style={s.input}
                value={form.contract_name}
                onChangeText={(v) => patchForm("contract_name", v.slice(0, 200))}
                placeholder="e.g. Pentair 3-Year Plan"
                placeholderTextColor={colors.muted}
                testID="warranty-contract-name-input"
              />

              {/* Provider */}
              <Text style={s.label}>Provider</Text>
              <AppTextInput
                style={s.input}
                value={form.provider}
                onChangeText={(v) => patchForm("provider", v.slice(0, 200))}
                placeholder="e.g. Pentair Inc."
                placeholderTextColor={colors.muted}
                testID="warranty-provider-input"
              />

              {/* Coverage start */}
              <Text style={s.label}>Coverage Start</Text>
              <AppTextInput
                style={s.input}
                value={form.coverage_start}
                onChangeText={(v) => patchForm("coverage_start", v)}
                placeholder="YYYY-MM-DD"
                placeholderTextColor={colors.muted}
                testID="warranty-coverage-start-input"
              />

              {/* Coverage end */}
              <Text style={s.label}>Coverage End</Text>
              <AppTextInput
                style={s.input}
                value={form.coverage_end}
                onChangeText={(v) => patchForm("coverage_end", v)}
                placeholder="YYYY-MM-DD"
                placeholderTextColor={colors.muted}
                testID="warranty-coverage-end-input"
              />

              {/* Linked type picker */}
              <Text style={s.label}>Linked Entity Type</Text>
              <Pressable
                style={s.selectBtn}
                onPress={() => setLinkTypePicker(true)}
                testID="warranty-linked-type-select"
              >
                <Text style={form.linked_type !== "none" ? s.selectText : s.selectPlaceholder}>
                  {LINKED_TYPES.find((t) => t.value === form.linked_type)?.label || "None"}
                </Text>
                <Ionicons name="chevron-down" size={16} color={colors.muted} />
              </Pressable>

              {/* Linked id picker — only when linked_type != none */}
              {form.linked_type !== "none" ? (
                <>
                  <Text style={s.label}>
                    Linked {form.linked_type === "install" ? "Install Job" : "Equipment"}
                  </Text>
                  {linkLoading ? (
                    <ActivityIndicator size="small" color={colors.brand} style={{ marginVertical: 8 }} />
                  ) : (
                    <Pressable
                      style={s.selectBtn}
                      onPress={() => setLinkIdPicker(true)}
                      testID="warranty-linked-id-select"
                    >
                      <Text
                        style={selectedLinkLabel ? s.selectText : s.selectPlaceholder}
                        numberOfLines={1}
                      >
                        {selectedLinkLabel || "Select…"}
                      </Text>
                      <Ionicons name="chevron-down" size={16} color={colors.muted} />
                    </Pressable>
                  )}
                </>
              ) : null}

              {/* Notes */}
              <Text style={s.label}>Notes</Text>
              <AppTextInput
                style={[s.input, { minHeight: 80 }]}
                value={form.notes}
                onChangeText={(v) => patchForm("notes", v.slice(0, 2000))}
                placeholder="Optional notes…"
                placeholderTextColor={colors.muted}
                multiline
                textAlignVertical="top"
                testID="warranty-notes-input"
              />

              {formErr ? (
                <Text style={s.formError} testID="warranty-form-error">{formErr}</Text>
              ) : null}

              <View style={s.formBtns}>
                <Pressable
                  style={s.cancelBtn}
                  onPress={() => setFormVisible(false)}
                  testID="warranty-modal-cancel-btn"
                >
                  <Text style={s.cancelBtnText}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={[s.saveBtn, saving && { opacity: 0.6 }]}
                  onPress={handleSave}
                  disabled={saving}
                  testID="warranty-modal-save-btn"
                >
                  <Text style={s.saveBtnText}>
                    {saving ? "Saving…" : "Save"}
                  </Text>
                </Pressable>
              </View>
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* ── Linked-type picker modal ────────────────────────────── */}
      <Modal
        visible={linkTypePicker}
        transparent
        animationType="fade"
        onRequestClose={() => setLinkTypePicker(false)}
      >
        <Pressable style={s.pickerBg} onPress={() => setLinkTypePicker(false)}>
          <View />
        </Pressable>
        <View style={s.pickerContainer}>
          <View style={s.pickerCard}>
            <Text style={s.pickerTitle}>Linked Entity Type</Text>
            {LINKED_TYPES.map((t) => (
              <Pressable
                key={t.value}
                style={[s.pickerRow, form.linked_type === t.value && s.pickerRowActive]}
                onPress={() => handleLinkedTypeChange(t.value)}
                testID={`warranty-linked-type-option-${t.value}`}
              >
                <Text style={[s.pickerRowText, form.linked_type === t.value && { color: colors.brand }]}>
                  {t.label}
                </Text>
                {form.linked_type === t.value ? (
                  <Ionicons name="checkmark" size={18} color={colors.brand} />
                ) : null}
              </Pressable>
            ))}
          </View>
        </View>
      </Modal>

      {/* ── Linked-id picker modal ──────────────────────────────── */}
      <Modal
        visible={linkIdPicker}
        transparent
        animationType="fade"
        onRequestClose={() => setLinkIdPicker(false)}
      >
        <Pressable style={s.pickerBg} onPress={() => setLinkIdPicker(false)}>
          <View />
        </Pressable>
        <View style={s.pickerContainer}>
          <View style={s.pickerCard}>
            <Text style={s.pickerTitle}>
              Select {form.linked_type === "install" ? "Install Job" : "Equipment"}
            </Text>
            <ScrollView style={{ maxHeight: 360 }}>
              {linkOptions.length === 0 ? (
                <Text style={s.pickerEmpty}>No options available.</Text>
              ) : (
                linkOptions.map((opt) => (
                  <Pressable
                    key={opt.id}
                    style={[s.pickerRow, form.linked_id === opt.id && s.pickerRowActive]}
                    onPress={() => handleLinkIdSelect(opt.id)}
                    testID={`warranty-linked-id-option-${opt.id}`}
                  >
                    <Text
                      style={[s.pickerRowText, form.linked_id === opt.id && { color: colors.brand }]}
                      numberOfLines={1}
                    >
                      {opt.label}
                    </Text>
                    {form.linked_id === opt.id ? (
                      <Ionicons name="checkmark" size={18} color={colors.brand} />
                    ) : null}
                  </Pressable>
                ))
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* ── Delete confirm modal ────────────────────────────────── */}
      <Modal
        visible={!!deleteTarget}
        transparent
        animationType="fade"
        onRequestClose={() => setDeleteTarget(null)}
        testID="warranty-delete-confirm-modal"
      >
        <Pressable style={s.pickerBg} onPress={() => setDeleteTarget(null)}>
          <View />
        </Pressable>
        <View style={s.pickerContainer}>
          <View style={s.deleteCard}>
            <Text style={s.deleteTitle}>Delete warranty?</Text>
            <Text style={s.deleteBody}>
              This will remove {`"${deleteTarget?.contract_name || "Unnamed"}"`} from this
              customer{"'"}s warranty contracts.
            </Text>
            <View style={s.deleteBtns}>
              <Pressable
                style={s.cancelBtn}
                onPress={() => setDeleteTarget(null)}
                testID="warranty-delete-cancel-btn"
              >
                <Text style={s.cancelBtnText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[s.deleteConfirmBtn, deleting && { opacity: 0.6 }]}
                onPress={handleDelete}
                disabled={deleting}
                testID="warranty-delete-confirm-btn"
              >
                <Text style={s.deleteConfirmText}>
                  {deleting ? "Deleting…" : "Delete"}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

// ── Styles ─────────────────────────────────────────────────────────
const s = StyleSheet.create({
  addBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, backgroundColor: colors.brandTertiary, borderRadius: radius.md,
    paddingVertical: 12, marginBottom: spacing.md,
  },
  addBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  empty: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    marginBottom: spacing.md,
  },
  errorText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#B91C1C",
    marginBottom: spacing.md,
  },
  // Modal
  modalBg: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)", justifyContent: "flex-end" },
  modalCard: {
    backgroundColor: colors.surface, borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg, maxHeight: "90%", overflow: "hidden",
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
  // Pickers
  pickerBg: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)" },
  pickerContainer: {
    position: "absolute", left: 0, right: 0, bottom: 0, top: 0,
    justifyContent: "center", alignItems: "center", paddingHorizontal: spacing.lg,
  },
  pickerCard: {
    width: "100%", maxWidth: 360, backgroundColor: colors.surface,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, overflow: "hidden",
  },
  pickerTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  pickerRow: {
    paddingHorizontal: spacing.md, paddingVertical: 12, flexDirection: "row",
    justifyContent: "space-between", alignItems: "center",
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  pickerRowActive: { backgroundColor: colors.brandTertiary },
  pickerRowText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  pickerEmpty: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, padding: spacing.md },
  // Delete
  deleteCard: {
    width: "100%", maxWidth: 360, backgroundColor: colors.surface,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.md,
  },
  deleteTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: "#B91C1C", marginBottom: spacing.sm },
  deleteBody: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface, marginBottom: spacing.md },
  deleteBtns: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm },
  deleteConfirmBtn: {
    minHeight: 44, paddingHorizontal: spacing.md, alignItems: "center", justifyContent: "center",
    borderRadius: radius.sm, backgroundColor: "#B91C1C",
  },
  deleteConfirmText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
