import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useRouter, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton } from "@/src/components/ui";
import { Field } from "@/app/customer/new";
import AppTextInput from "@/src/components/ui/AppTextInput";
import QuoteRecipientPicker, {
  type RecipientValue,
} from "@/src/components/quotes/QuoteRecipientPicker";

type LI = { description: string; quantity: string; unit_price: string; category: string };

export default function QuoteForm() {
  const router = useRouter();
  // Phase 2 B2 — accept URL params for pre-fill
  const params = useLocalSearchParams<{
    customer_id?: string;
    recipient_type?: string;
    recipient_id?: string;
  }>();

  // Phase 2 B2 — hybrid recipient state (Customer OR Lead)
  const _initialRecipient = (() => {
    if (params.recipient_type && params.recipient_id) {
      return {
        type: (params.recipient_type.toLowerCase() === "lead" ? "lead" : "customer") as "customer" | "lead",
        id: params.recipient_id,
        name: "",
      };
    }
    if (params.customer_id) {
      return { type: "customer" as const, id: params.customer_id, name: "" };
    }
    return null;
  })();
  const [recipient, setRecipient] = useState<RecipientValue>(_initialRecipient);

  const [docType, setDocType] = useState<"quote" | "invoice">("quote");
  const [title, setTitle] = useState("");
  const [taxRate, setTaxRate] = useState("8");
  const [categories, setCategories] = useState<string[]>(["Pool", "Landscaping", "Labor"]);
  const [items, setItems] = useState<LI[]>([{ description: "", quantity: "1", unit_price: "", category: "Pool" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    // Hydrate recipient display name if legacy customer_id URL param
    if (_initialRecipient?.type === "customer" && _initialRecipient.id && !_initialRecipient.name) {
      api.get("/customers").then((custs: any[]) => {
        const hit = (custs || []).find((c: any) => c.id === _initialRecipient.id);
        if (hit) setRecipient((prev) => prev ? { ...prev, name: hit.name || "" } : prev);
      }).catch(() => {});
    }
    // TD-96-mobile D3 — hydrate lead name (web QuoteInvoiceNew parity) so the
    // picker shows the lead's name instead of its raw id.
    if (_initialRecipient?.type === "lead" && _initialRecipient.id && !_initialRecipient.name) {
      const lid = _initialRecipient.id;
      api.get(`/leads/${encodeURIComponent(lid)}`).then((l: any) => {
        if (l?.name) setRecipient((prev) => (prev && prev.type === "lead" && prev.id === lid ? { ...prev, name: l.name } : prev));
      }).catch(() => {});
    }
    api.get("/income-categories").then((r) => {
      const cats = r.categories || [];
      if (cats.length) {
        setCategories(cats);
        setItems((arr) => arr.map((li) => (li.category ? li : { ...li, category: cats[0] })));
      }
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const totals = useMemo(() => {
    const subtotal = items.reduce((s, li) => s + (parseFloat(li.quantity) || 0) * (parseFloat(li.unit_price) || 0), 0);
    const tax = subtotal * ((parseFloat(taxRate) || 0) / 100);
    return { subtotal, tax, total: subtotal + tax };
  }, [items, taxRate]);

  const updateItem = (i: number, k: keyof LI, v: string) =>
    setItems((arr) => arr.map((li, idx) => (idx === i ? { ...li, [k]: v } : li)));
  const addItem = () => setItems((a) => [...a, { description: "", quantity: "1", unit_price: "", category: categories[0] || "Pool" }]);
  const removeItem = (i: number) => setItems((a) => a.filter((_, idx) => idx !== i));

  const save = async () => {
    if (!title.trim() || !recipient?.id) {
      setError("Title and recipient are required");
      return;
    }
    const filled = items.filter((li) => li.description.trim());
    if (filled.length === 0) {
      setError("Add at least one line item");
      return;
    }
    if (filled.some((li) => !li.category)) {
      setError("Assign a category to every line item");
      return;
    }
    const line_items = filled.map((li) => ({ description: li.description, quantity: parseFloat(li.quantity) || 0, unit_price: parseFloat(li.unit_price) || 0, category: li.category }));
    setBusy(true);
    setError("");
    try {
      // Phase 2 B2 — hybrid payload: Customer → include customer_id;
      // Lead → omit customer_id entirely.
      const isLeadRecipient = recipient.type === "lead";
      const payload: any = {
        ...(isLeadRecipient ? {} : { customer_id: recipient.id }),
        recipient_type: recipient.type,
        recipient_id: recipient.id,
        title,
        doc_type: docType,
        tax_rate: parseFloat(taxRate) || 0,
        line_items,
      };
      await api.post("/quotes", payload);
      router.back();
    } catch (e: any) {
      setError(e.message || "Failed to create");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <Header title="New Document" back />
      <KeyboardAwareScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }} bottomOffset={24} keyboardShouldPersistTaps="handled">
        <View style={styles.toggle}>
          {(["quote", "invoice"] as const).map((t) => (
            <Pressable key={t} style={[styles.toggleBtn, docType === t && styles.toggleActive]} onPress={() => setDocType(t)} testID={`doctype-${t}`}>
              <Text style={[styles.toggleText, docType === t && { color: "#fff" }]}>{t === "quote" ? "Quote" : "Invoice"}</Text>
            </Pressable>
          ))}
        </View>

        <Field label="Title *" value={title} onChangeText={setTitle} placeholder="e.g. Filter System Upgrade" testID="quote-title-input" />
        <QuoteRecipientPicker value={recipient} onChange={setRecipient} />

        <Text style={styles.sectionLabel}>Line Items</Text>
        {items.map((li, i) => (
          <View key={i} style={styles.itemCard} testID={`line-item-${i}`}>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Text style={styles.itemNum}>Item {i + 1}</Text>
              {items.length > 1 ? (
                <Pressable onPress={() => removeItem(i)} hitSlop={8} testID={`remove-item-${i}`}>
                  <Ionicons name="trash-outline" size={18} color={colors.error} />
                </Pressable>
              ) : null}
            </View>
            <AppTextInput
              testID={`item-desc-${i}`}
              style={styles.itemInput}
              placeholder="Description"
              placeholderTextColor={colors.muted}
              value={li.description}
              onChangeText={(v) => updateItem(i, "description", v)}
            />
            <View style={{ flexDirection: "row", gap: spacing.sm }}>
              <AppTextInput
                testID={`item-qty-${i}`}
                style={[styles.itemInput, { flex: 1 }]}
                placeholder="Qty"
                placeholderTextColor={colors.muted}
                keyboardType="decimal-pad"
                value={li.quantity}
                onChangeText={(v) => updateItem(i, "quantity", v)}
              />
              <AppTextInput
                testID={`item-price-${i}`}
                style={[styles.itemInput, { flex: 2 }]}
                placeholder="Unit price"
                placeholderTextColor={colors.muted}
                keyboardType="decimal-pad"
                value={li.unit_price}
                onChangeText={(v) => updateItem(i, "unit_price", v)}
              />
            </View>
            <View style={styles.catRow}>
              {categories.map((cat) => (
                <Pressable
                  key={cat}
                  style={[styles.catChip, li.category === cat && styles.catChipActive]}
                  onPress={() => updateItem(i, "category", cat)}
                  testID={`item-cat-${i}-${cat}`}
                >
                  <Text style={[styles.catChipText, li.category === cat && { color: "#fff" }]}>{cat}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        ))}
        <Pressable style={styles.addItem} onPress={addItem} testID="add-line-item">
          <Ionicons name="add-circle-outline" size={20} color={colors.brand} />
          <Text style={styles.addItemText}>Add line item</Text>
        </Pressable>

        <Field label="Tax Rate (%)" value={taxRate} onChangeText={setTaxRate} placeholder="8" keyboardType="decimal-pad" testID="quote-tax-input" />

        <View style={styles.totalsCard}>
          <TotalRow label="Subtotal" value={money(totals.subtotal)} />
          <TotalRow label="Tax" value={money(totals.tax)} />
          <TotalRow label="Total" value={money(totals.total)} bold />
        </View>

        {error ? <Text style={styles.error} testID="quote-form-error">{error}</Text> : null}
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title={`Create ${docType === "quote" ? "Quote" : "Invoice"}`} onPress={save} loading={busy} testID="save-quote-button" />
      </KeyboardAwareScrollView>

    </View>
  );
}

function TotalRow({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <View style={styles.totalRow}>
      <Text style={[styles.totalLabel, bold && { fontFamily: font.bold, color: colors.onSurface }]}>{label}</Text>
      <Text style={[styles.totalValue, bold && { fontFamily: font.bold, fontSize: fontSize.xl }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  toggle: { flexDirection: "row", backgroundColor: colors.surfaceTertiary, borderRadius: radius.md, padding: 4, marginBottom: spacing.lg },
  toggleBtn: { flex: 1, height: 40, alignItems: "center", justifyContent: "center", borderRadius: radius.sm },
  toggleActive: { backgroundColor: colors.brand },
  toggleText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurfaceSecondary },
  sectionLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm },
  itemCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm, gap: spacing.sm },
  itemNum: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  catRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  catChip: { paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  catChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  catChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  itemInput: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, height: 46, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  addItem: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, paddingVertical: spacing.md, marginBottom: spacing.md },
  addItemText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  totalsCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, gap: spacing.xs },
  totalRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  totalLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  totalValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
});
