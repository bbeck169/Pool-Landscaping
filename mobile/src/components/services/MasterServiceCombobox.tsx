/**
 * Phase P19 · MasterServiceCombobox — mobile port of web P16.
 *
 * TextInput + dropdown modal that fetches active master services from
 * `GET /api/master-services` and provides typeahead filtering.
 *
 * On pick: fires `onPick({ name, default_price, category })`.
 * Inline "+ Add to Master Service List?" affordance for manager/admin
 * roles (hidden for technicians).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View, Text, TextInput, Pressable, Modal, FlatList, StyleSheet,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type MasterService = {
  id: string;
  name: string;
  default_price: number;
  category: string;
  is_active?: boolean;
};

type PickResult = {
  name: string;
  default_price: number | null;
  category: string | null;
};

export type MasterServiceComboboxProps = {
  value: string;
  onChangeText: (v: string) => void;
  onPick: (result: PickResult) => void;
  defaultPriceHint?: number | null;
  placeholder?: string;
  testID?: string;
};

// ─── In-memory cache (60s TTL) ───────────────────────────────────
let _cache: { items: MasterService[]; expires: number } | null = null;
const _CACHE_TTL_MS = 60_000;

async function fetchActiveServices(force = false): Promise<MasterService[]> {
  if (!force && _cache && _cache.expires > Date.now()) return _cache.items;
  const res: any = await api.get("/master-services");
  const items: MasterService[] = Array.isArray(res?.items) ? res.items : [];
  _cache = { items, expires: Date.now() + _CACHE_TTL_MS };
  return items;
}

export function invalidateMasterServicesCache() {
  _cache = null;
}

// ─── Add Modal ───────────────────────────────────────────────────
function AddMasterServiceModal({
  initialName,
  initialDefaultPrice,
  onCancel,
  onCreated,
}: {
  initialName: string;
  initialDefaultPrice: number | null;
  onCancel: () => void;
  onCreated: (item: MasterService) => void;
}) {
  const [name, setName] = useState(initialName || "");
  const [defaultPrice, setDefaultPrice] = useState(
    Number.isFinite(initialDefaultPrice) && (initialDefaultPrice ?? 0) > 0
      ? String(initialDefaultPrice)
      : "",
  );
  const [category, setCategory] = useState("");
  const [categories, setCategories] = useState<string[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [catPickerOpen, setCatPickerOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.get("/master-services/categories").then((res: any) => {
      if (cancelled) return;
      setCategories(Array.isArray(res?.items) ? res.items : []);
    }).catch(() => {
      if (!cancelled) setCategories([]);
    });
    return () => { cancelled = true; };
  }, []);

  const save = useCallback(async () => {
    setErr("");
    const trimmed = (name || "").trim();
    if (!trimmed) { setErr("Name is required."); return; }
    if (!category) { setErr("Category is required."); return; }
    const priceN = Number(defaultPrice);
    if (defaultPrice !== "" && (!Number.isFinite(priceN) || priceN < 0)) {
      setErr("Default price must be a non-negative number.");
      return;
    }
    setBusy(true);
    try {
      const created: any = await api.post("/master-services", {
        name: trimmed,
        default_price: defaultPrice === "" ? 0 : priceN,
        category,
      });
      invalidateMasterServicesCache();
      onCreated?.(created);
    } catch (e: any) {
      const code = e?.data?.detail?.error || e?.data?.error;
      if (code === "duplicate_name") {
        setErr("A master service with that name already exists.");
      } else if (code === "category_invalid") {
        setErr("Category is not valid for this tenant.");
      } else {
        setErr(e?.message || "Save failed.");
      }
    } finally { setBusy(false); }
  }, [name, defaultPrice, category, onCreated]);

  return (
    <Modal transparent animationType="fade" onRequestClose={onCancel}>
      <Pressable style={ms.backdrop} onPress={onCancel}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={ms.center}
        >
          <Pressable style={ms.card} onPress={() => {}}>
            <View style={ms.header}>
              <Text style={ms.headerTitle}>Add to Master Service List</Text>
              <Pressable onPress={onCancel} hitSlop={8} testID="master-service-add-modal-close">
                <Ionicons name="close" size={20} color={colors.muted} />
              </Pressable>
            </View>

            <View style={ms.body}>
              <Text style={ms.label}>Name *</Text>
              <AppTextInput
                value={name}
                onChangeText={setName}
                style={ms.input}
                autoFocus
                testID="master-service-add-modal-name"
              />

              <Text style={ms.label}>Default Price</Text>
              <AppTextInput
                value={defaultPrice}
                onChangeText={setDefaultPrice}
                keyboardType="decimal-pad"
                placeholder="0.00"
                style={ms.input}
                testID="master-service-add-modal-price"
              />

              <Text style={ms.label}>Category *</Text>
              <Pressable
                style={ms.input}
                onPress={() => setCatPickerOpen(true)}
                testID="master-service-add-modal-category"
              >
                <Text style={category ? ms.inputText : ms.inputPlaceholder}>
                  {category || "Select a category…"}
                </Text>
              </Pressable>

              {catPickerOpen && (
                <View style={ms.catList}>
                  {categories.map((c) => (
                    <Pressable
                      key={c}
                      style={[ms.catItem, category === c && ms.catItemActive]}
                      onPress={() => { setCategory(c); setCatPickerOpen(false); }}
                      testID={`master-service-add-modal-cat-${c}`}
                    >
                      <Text style={[ms.catItemText, category === c && ms.catItemTextActive]}>{c}</Text>
                    </Pressable>
                  ))}
                  {categories.length === 0 && (
                    <Text style={ms.catEmpty}>No categories found</Text>
                  )}
                </View>
              )}

              {err ? <Text style={ms.err} testID="master-service-add-modal-error">{err}</Text> : null}
            </View>

            <View style={ms.footer}>
              <Pressable style={ms.cancelBtn} onPress={onCancel}>
                <Text style={ms.cancelBtnText}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[ms.saveBtn, busy && { opacity: 0.6 }]}
                onPress={save}
                disabled={busy}
                testID="master-service-add-modal-save"
              >
                {busy ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={ms.saveBtnText}>Add service</Text>
                )}
              </Pressable>
            </View>
          </Pressable>
        </KeyboardAvoidingView>
      </Pressable>
    </Modal>
  );
}

// ─── Main Combobox ───────────────────────────────────────────────
export default function MasterServiceCombobox({
  value,
  onChangeText,
  onPick,
  defaultPriceHint,
  placeholder = "e.g. Pool Cleaning",
  testID = "master-service-combobox",
}: MasterServiceComboboxProps) {
  const { user } = useAuth();
  const role = String((user as any)?.role || "");
  const canAdd = role === "admin" || role === "super_admin" || role === "manager";

  const [services, setServices] = useState<MasterService[]>([]);
  const [open, setOpen] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    fetchActiveServices().then(setServices).catch(() => {});
  }, []);

  const filtered = useMemo(() => {
    const q = (value || "").trim().toLowerCase();
    if (!q) return services;
    return services.filter((s) => s.name.toLowerCase().includes(q));
  }, [value, services]);

  const exactMatch = useMemo(() => {
    const q = (value || "").trim().toLowerCase();
    return q ? services.some((s) => s.name.toLowerCase() === q) : true;
  }, [value, services]);

  const handlePick = useCallback((item: MasterService) => {
    onChangeText(item.name);
    onPick({
      name: item.name,
      default_price: item.default_price,
      category: item.category,
    });
    setOpen(false);
  }, [onChangeText, onPick]);

  const handleAddCreated = useCallback((item: MasterService) => {
    setAddModalOpen(false);
    setServices((prev) => [item, ...prev]);
    onChangeText(item.name);
    onPick({
      name: item.name,
      default_price: item.default_price,
      category: item.category,
    });
    setOpen(false);
  }, [onChangeText, onPick]);

  return (
    <View testID={testID}>
      <AppTextInput
        ref={inputRef}
        value={value}
        onChangeText={(t) => { onChangeText(t); if (!open) setOpen(true); }}
        onFocus={() => setOpen(true)}
        placeholder={placeholder}
        style={cs.input}
        testID={`${testID}-input`}
      />

      {open && (value || "").trim().length > 0 && (
        <View style={cs.dropdown} testID={`${testID}-dropdown`}>
          {filtered.length > 0 ? (
            <FlatList
              data={filtered.slice(0, 8)}
              keyExtractor={(item) => item.id}
              keyboardShouldPersistTaps="handled"
              style={{ maxHeight: 200 }}
              renderItem={({ item }) => (
                <Pressable
                  style={cs.dropdownItem}
                  onPress={() => handlePick(item)}
                  testID={`${testID}-item-${item.id}`}
                >
                  <Text style={cs.itemName} numberOfLines={1}>{item.name}</Text>
                  {item.default_price > 0 && (
                    <Text style={cs.itemPrice}>${(item.default_price / 100).toFixed(2)}</Text>
                  )}
                </Pressable>
              )}
            />
          ) : (
            <Text style={cs.noResults}>No matches</Text>
          )}

          {/* "+ Add" affordance — manager/admin only, not exact match */}
          {canAdd && !exactMatch && (value || "").trim().length > 0 && (
            <Pressable
              style={cs.addRow}
              onPress={() => setAddModalOpen(true)}
              testID={`${testID}-add-btn`}
            >
              <Ionicons name="add-circle-outline" size={16} color={colors.brand} />
              <Text style={cs.addRowText}>Add "{(value || "").trim()}" to Master Service List</Text>
            </Pressable>
          )}

          <Pressable style={cs.dismissRow} onPress={() => setOpen(false)}>
            <Text style={cs.dismissText}>Close</Text>
          </Pressable>
        </View>
      )}

      {addModalOpen && (
        <AddMasterServiceModal
          initialName={(value || "").trim()}
          initialDefaultPrice={defaultPriceHint ?? null}
          onCancel={() => setAddModalOpen(false)}
          onCreated={handleAddCreated}
        />
      )}
    </View>
  );
}

const ms = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "center", alignItems: "center" },
  center: { width: "100%", alignItems: "center" },
  card: { width: "90%", maxWidth: 400, backgroundColor: colors.surface, borderRadius: radius.lg, overflow: "hidden" },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  body: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  label: { fontFamily: font.semibold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4, marginTop: spacing.sm },
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  inputText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  inputPlaceholder: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  catList: { marginTop: 4, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, backgroundColor: colors.surface },
  catItem: { paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  catItemActive: { backgroundColor: colors.brandTertiary },
  catItemText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  catItemTextActive: { color: colors.brand },
  catEmpty: { padding: 12, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  err: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error, marginTop: spacing.sm },
  footer: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  cancelBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border },
  cancelBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  saveBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.sm, backgroundColor: colors.brand },
  saveBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});

const cs = StyleSheet.create({
  input: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 10, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  dropdown: { marginTop: 4, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm, backgroundColor: colors.surface, zIndex: 10, elevation: 10 },
  dropdownItem: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 12, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  itemName: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  itemPrice: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted, marginLeft: 8 },
  noResults: { paddingHorizontal: 12, paddingVertical: 10, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
  addRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 10, borderTopWidth: 1, borderTopColor: colors.border },
  addRowText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand, flex: 1 },
  dismissRow: { paddingHorizontal: 12, paddingVertical: 8, alignItems: "center", borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  dismissText: { fontFamily: font.medium, fontSize: 11, color: colors.muted },
});
