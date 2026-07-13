import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Loading, Sheet, PrimaryButton, EmptyState } from "@/src/components/ui";
import { computeEstimate, CATEGORIES, CATEGORY_META, EstimateLine } from "@/src/utils/estimate";
import { exportEstimatePdf } from "@/src/utils/exportEstimatePdf";

const emptyLine = (): EstimateLine => ({ category: "Material", description: "", quantity: 1, unit_cost: 0 });

export default function EstimateBuilder() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    id: string; customerId?: string; customerName?: string; title?: string;
    lineDesc?: string; lineQty?: string; lineCost?: string; category?: string;
  }>();
  const { id } = params;
  const isNew = id === "new";

  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [title, setTitle] = useState("");
  const [customer, setCustomer] = useState<{ id: string; name: string } | null>(null);
  const [lines, setLines] = useState<EstimateLine[]>([]);
  const [overhead, setOverhead] = useState("15");
  const [margin, setMargin] = useState("30");
  const [notes, setNotes] = useState("");
  const [status, setStatus] = useState("draft");
  const [convertedId, setConvertedId] = useState<string | null>(null);

  const [customers, setCustomers] = useState<any[]>([]);
  const [custSheet, setCustSheet] = useState(false);
  const [lineSheet, setLineSheet] = useState(false);
  const [lineDraft, setLineDraft] = useState<EstimateLine>(emptyLine());
  const [lineIdx, setLineIdx] = useState<number | null>(null);
  const [pbSheet, setPbSheet] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [tplSheet, setTplSheet] = useState(false);
  const [templates, setTemplates] = useState<any[]>([]);
  const [saveTplSheet, setSaveTplSheet] = useState(false);
  const [tplName, setTplName] = useState("");

  const load = useCallback(async () => {
    try {
      const [custs, its] = await Promise.all([api.get("/customers"), api.get("/items")]);
      setCustomers(custs);
      setItems(its);
      if (isNew) {
        try {
          const s = await api.get("/estimates/settings");
          setOverhead(String(s.overhead_pct ?? 15));
          setMargin(String(s.margin_pct ?? 30));
        } catch {}
        // Prefill from a saved measurement / "Use in Estimate" deep link.
        if (params.customerId && params.customerName) setCustomer({ id: params.customerId, name: params.customerName });
        if (params.title) setTitle(params.title);
        if (params.lineDesc) {
          setLines([{
            category: (params.category as any) || "Material",
            description: params.lineDesc,
            quantity: Number(params.lineQty) || 1,
            unit_cost: Number(params.lineCost) || 0,
          }]);
        }
        setLoading(false);
      } else {
        const e = await api.get(`/estimates/${id}`);
        setTitle(e.title || "");
        setCustomer({ id: e.customer_id, name: e.customer_name });
        setLines(e.line_items || []);
        setOverhead(String(e.overhead_pct ?? 15));
        setMargin(String(e.margin_pct ?? 30));
        setNotes(e.notes || "");
        setStatus(e.status || "draft");
        setConvertedId(e.converted_quote_id || null);
        setLoading(false);
      }
    } catch {
      setLoading(false);
    }
  }, [id, isNew, params.customerId, params.customerName, params.title, params.lineDesc, params.lineQty, params.lineCost, params.category]);

  useEffect(() => { load(); }, [load]);

  const calc = useMemo(() => computeEstimate(lines, parseFloat(overhead) || 0, parseFloat(margin) || 0), [lines, overhead, margin]);
  const readOnly = status === "converted";

  const openAddLine = () => { setLineDraft(emptyLine()); setLineIdx(null); setLineSheet(true); };
  const openEditLine = (i: number) => { setLineDraft({ ...lines[i] }); setLineIdx(i); setLineSheet(true); };
  const saveLine = () => {
    if (!lineDraft.description.trim()) { Alert.alert("Description required", "Enter what this line covers."); return; }
    const clean = { ...lineDraft, quantity: Number(lineDraft.quantity) || 0, unit_cost: Number(lineDraft.unit_cost) || 0 };
    setLines((prev) => (lineIdx === null ? [...prev, clean] : prev.map((l, i) => (i === lineIdx ? clean : l))));
    setLineSheet(false);
  };
  const removeLine = (i: number) => setLines((prev) => prev.filter((_, idx) => idx !== i));

  const pickItem = (it: any) => {
    setLineDraft((d) => ({
      ...d,
      description: it.name,
      unit_cost: Number(it.unit_price) || 0,
      category: it.category === "Part" || it.category === "Chemical" ? "Material" : d.category,
      item_id: it.id,
    }));
    setPbSheet(false);
  };

  const openTemplates = async () => {
    try { setTemplates(await api.get("/estimate-templates")); } catch { setTemplates([]); }
    setTplSheet(true);
  };
  const applyTemplate = (t: any) => {
    setLines((prev) => [...prev, ...(t.line_items || [])]);
    setOverhead(String(t.overhead_pct ?? overhead));
    setMargin(String(t.margin_pct ?? margin));
    if (!title.trim()) setTitle(t.name);
    setTplSheet(false);
  };
  const saveAsTemplate = async () => {
    if (!tplName.trim()) return;
    try {
      await api.post("/estimate-templates", { name: tplName.trim(), line_items: lines, overhead_pct: parseFloat(overhead) || 0, margin_pct: parseFloat(margin) || 0 });
      setSaveTplSheet(false); setTplName("");
      Alert.alert("Saved", "Template saved for reuse.");
    } catch (e: any) { Alert.alert("Error", e.message || "Could not save template."); }
  };

  const buildBody = () => ({
    customer_id: customer?.id, title: title.trim(), line_items: lines,
    overhead_pct: parseFloat(overhead) || 0, margin_pct: parseFloat(margin) || 0, notes,
  });

  const exportPdf = async () => {
    if (lines.length === 0) { Alert.alert("Nothing to export", "Add line items first."); return; }
    try {
      await exportEstimatePdf({
        title, customerName: customer?.name || "",
        lines, overheadPct: parseFloat(overhead) || 0, marginPct: parseFloat(margin) || 0,
      });
    } catch (e: any) { Alert.alert("Export failed", e.message || "Could not generate the PDF."); }
  };

  const save = async () => {
    if (!customer) { Alert.alert("Customer required", "Pick a customer first."); return; }
    if (!title.trim()) { Alert.alert("Title required", "Give this estimate a name."); return; }
    setSaving(true);
    try {
      if (isNew) { const e = await api.post("/estimates", buildBody()); router.replace(`/estimator/${e.id}`); }
      else { await api.put(`/estimates/${id}`, buildBody()); Alert.alert("Saved", "Estimate updated."); }
    } catch (e: any) { Alert.alert("Error", e.message || "Could not save."); }
    finally { setSaving(false); }
  };

  const convert = async () => {
    if (isNew) { Alert.alert("Save first", "Save the estimate before converting."); return; }
    Alert.alert("Convert to Quote", `Create a customer quote for ${money(calc.sellPrice)}? Your cost breakdown stays private.`, [
      { text: "Cancel", style: "cancel" },
      { text: "Convert", onPress: async () => {
        try {
          const q = await api.post(`/estimates/${id}/convert`, {});
          setStatus("converted"); setConvertedId(q.id);
          Alert.alert("Quote created 🎉", "The estimate is now a quote you can send.");
        } catch (e: any) { Alert.alert("Error", e.message || "Could not convert."); }
      } },
    ]);
  };

  if (loading) return <Loading testID="estimate-builder-loading" />;

  return (
    <View style={styles.root}>
      <Header title={isNew ? "New Estimate" : "Estimate"} back subtitle={readOnly ? "Converted (read-only)" : "Cost + overhead + margin"} />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }} keyboardShouldPersistTaps="handled">
        <Text style={styles.label}>Customer</Text>
        <Pressable style={styles.selector} onPress={() => !readOnly && setCustSheet(true)} testID="estimate-pick-customer">
          <Ionicons name="person-outline" size={18} color={colors.muted} />
          <Text style={[styles.selectorText, !customer && { color: colors.muted }]} numberOfLines={1}>{customer?.name || "Select a customer"}</Text>
          {!readOnly ? <Ionicons name="chevron-down" size={18} color={colors.muted} /> : null}
        </Pressable>

        <Text style={styles.label}>Title</Text>
        <TextInput style={styles.input} value={title} onChangeText={setTitle} editable={!readOnly} placeholder="e.g. Equipment upgrade" placeholderTextColor={colors.muted} testID="estimate-title" />

        <View style={styles.sectionHead}>
          <Text style={styles.sectionTitle}>Cost line items</Text>
          {!readOnly ? (
            <Pressable onPress={openTemplates} testID="estimate-load-template" hitSlop={8}>
              <Text style={styles.linkText}>Load template</Text>
            </Pressable>
          ) : null}
        </View>

        {lines.length === 0 ? (
          <EmptyState icon="list-outline" title="No line items" subtitle="Add materials, labor, subs and equipment costs." testID="estimate-lines-empty" />
        ) : (
          lines.map((l, i) => {
            const meta = CATEGORY_META[l.category] || CATEGORY_META.Other;
            return (
              <Pressable key={i} style={styles.lineRow} onPress={() => !readOnly && openEditLine(i)} testID={`estimate-line-${i}`}>
                <View style={[styles.lineDot, { backgroundColor: meta.color }]}>
                  <Ionicons name={meta.icon as any} size={15} color="#fff" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.lineTitle} numberOfLines={1}>{l.description || l.category}</Text>
                  <Text style={styles.lineMeta}>{l.category} · {l.quantity} × {money(l.unit_cost)}</Text>
                </View>
                <Text style={styles.lineAmt}>{money((Number(l.quantity) || 0) * (Number(l.unit_cost) || 0))}</Text>
                {!readOnly ? (
                  <Pressable hitSlop={10} onPress={() => removeLine(i)} testID={`estimate-line-remove-${i}`}>
                    <Ionicons name="close-circle" size={20} color={colors.muted} />
                  </Pressable>
                ) : null}
              </Pressable>
            );
          })
        )}

        {!readOnly ? (
          <Pressable style={styles.addLineBtn} onPress={openAddLine} testID="estimate-add-line">
            <Ionicons name="add" size={18} color={colors.brand} />
            <Text style={styles.addLineText}>Add line item</Text>
          </Pressable>
        ) : null}

        <View style={styles.pctRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Overhead %</Text>
            <TextInput style={styles.input} value={overhead} onChangeText={(v) => setOverhead(v.replace(/[^0-9.]/g, ""))} editable={!readOnly} keyboardType="decimal-pad" testID="estimate-overhead" />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.label}>Profit margin %</Text>
            <TextInput style={styles.input} value={margin} onChangeText={(v) => setMargin(v.replace(/[^0-9.]/g, ""))} editable={!readOnly} keyboardType="decimal-pad" testID="estimate-margin" />
          </View>
        </View>

        <View style={styles.summary} testID="estimate-summary">
          <SummaryRow label="Direct cost" value={money(calc.directCost)} />
          <SummaryRow label={`Overhead (${overhead || 0}%)`} value={money(calc.overheadAmount)} />
          <SummaryRow label="Burdened cost" value={money(calc.totalCost)} muted />
          <SummaryRow label="Profit" value={money(calc.profitAmount)} accent="#16A34A" />
          <View style={styles.sellRow}>
            <Text style={styles.sellLabel}>Sell price</Text>
            <Text style={styles.sellValue} testID="estimate-sell-price">{money(calc.sellPrice)}</Text>
          </View>
          <Text style={styles.gmText}>Gross margin {calc.grossMarginPct}%</Text>
        </View>

        <Pressable style={styles.pdfBtn} onPress={exportPdf} testID="estimate-export-pdf">
          <Ionicons name="document-attach-outline" size={16} color={colors.onSurface} />
          <Text style={styles.pdfBtnText}>Internal cost breakdown PDF</Text>
        </Pressable>

        {!readOnly ? (
          <>
            <View style={{ height: spacing.md }} />
            <PrimaryButton title={isNew ? "Save Estimate" : "Save Changes"} icon="checkmark" loading={saving} onPress={save} testID="estimate-save" />
            {!isNew ? (
              <>
                <Pressable style={styles.convertBtn} onPress={convert} testID="estimate-convert">
                  <Ionicons name="document-text" size={16} color="#fff" />
                  <Text style={styles.convertText}>Convert to Quote</Text>
                </Pressable>
                <Pressable style={styles.tplBtn} onPress={() => setSaveTplSheet(true)} testID="estimate-save-template">
                  <Ionicons name="albums-outline" size={16} color={colors.brand} />
                  <Text style={styles.tplBtnText}>Save as template</Text>
                </Pressable>
              </>
            ) : null}
          </>
        ) : convertedId ? (
          <Pressable style={styles.convertBtn} onPress={() => router.push(`/quote/${convertedId}`)} testID="estimate-view-quote">
            <Ionicons name="open-outline" size={16} color="#fff" />
            <Text style={styles.convertText}>View created quote</Text>
          </Pressable>
        ) : null}
      </ScrollView>

      {/* Customer picker */}
      <Sheet visible={custSheet} onClose={() => setCustSheet(false)} title="Select Customer" testID="estimate-customer-sheet">
        <ScrollView style={{ maxHeight: 420 }} keyboardShouldPersistTaps="handled">
          {customers.map((c) => (
            <Pressable key={c.id} style={styles.pickRow} onPress={() => { setCustomer({ id: c.id, name: c.name }); setCustSheet(false); }} testID={`estimate-customer-${c.id}`}>
              <Text style={styles.pickName}>{c.name}</Text>
              {c.address ? <Text style={styles.pickMeta} numberOfLines={1}>{c.address}</Text> : null}
            </Pressable>
          ))}
        </ScrollView>
      </Sheet>

      {/* Line editor */}
      <Sheet visible={lineSheet} onClose={() => setLineSheet(false)} title={lineIdx === null ? "Add Line Item" : "Edit Line Item"} testID="estimate-line-sheet">
        <ScrollView style={{ maxHeight: 460 }} keyboardShouldPersistTaps="handled">
          <Text style={styles.label}>Category</Text>
          <View style={styles.chipRow}>
            {CATEGORIES.map((c) => {
              const meta = CATEGORY_META[c];
              const active = lineDraft.category === c;
              return (
                <Pressable key={c} style={[styles.chip, active && { backgroundColor: meta.color, borderColor: meta.color }]} onPress={() => setLineDraft((d) => ({ ...d, category: c }))} testID={`estimate-cat-${c}`}>
                  <Text style={[styles.chipText, active && { color: "#fff" }]}>{c}</Text>
                </Pressable>
              );
            })}
          </View>
          <Pressable style={styles.pbBtn} onPress={() => setPbSheet(true)} testID="estimate-from-pricebook">
            <Ionicons name="pricetags-outline" size={15} color={colors.brand} />
            <Text style={styles.pbBtnText}>Fill from Price Book</Text>
          </Pressable>
          <Text style={styles.label}>Description</Text>
          <TextInput style={styles.input} value={lineDraft.description} onChangeText={(v) => setLineDraft((d) => ({ ...d, description: v }))} placeholder="What this covers" placeholderTextColor={colors.muted} testID="estimate-line-desc" />
          <View style={styles.pctRow}>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Quantity</Text>
              <TextInput style={styles.input} value={String(lineDraft.quantity)} onChangeText={(v) => setLineDraft((d) => ({ ...d, quantity: v.replace(/[^0-9.]/g, "") as any }))} keyboardType="decimal-pad" testID="estimate-line-qty" />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.label}>Unit cost ($)</Text>
              <TextInput style={styles.input} value={String(lineDraft.unit_cost)} onChangeText={(v) => setLineDraft((d) => ({ ...d, unit_cost: v.replace(/[^0-9.]/g, "") as any }))} keyboardType="decimal-pad" testID="estimate-line-cost" />
            </View>
          </View>
          <View style={{ height: spacing.md }} />
          <PrimaryButton title={lineIdx === null ? "Add" : "Update"} icon="checkmark" onPress={saveLine} testID="estimate-line-save" />
        </ScrollView>
      </Sheet>

      {/* Price book picker */}
      <Sheet visible={pbSheet} onClose={() => setPbSheet(false)} title="Price Book" testID="estimate-pb-sheet">
        <ScrollView style={{ maxHeight: 420 }} keyboardShouldPersistTaps="handled">
          {items.length === 0 ? (
            <Text style={styles.pickMeta}>No price book items yet.</Text>
          ) : items.map((it) => (
            <Pressable key={it.id} style={styles.pickRow} onPress={() => pickItem(it)} testID={`estimate-pb-${it.id}`}>
              <Text style={styles.pickName}>{it.name}</Text>
              <Text style={styles.pickMeta}>{it.category} · {money(it.unit_price)}/{it.unit}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </Sheet>

      {/* Template picker */}
      <Sheet visible={tplSheet} onClose={() => setTplSheet(false)} title="Templates" testID="estimate-tpl-sheet">
        <ScrollView style={{ maxHeight: 420 }} keyboardShouldPersistTaps="handled">
          {templates.map((t) => (
            <Pressable key={t.id} style={styles.pickRow} onPress={() => applyTemplate(t)} testID={`estimate-tpl-${t.id}`}>
              <Text style={styles.pickName}>{t.name}</Text>
              <Text style={styles.pickMeta}>{(t.line_items || []).length} items · OH {t.overhead_pct}% · Margin {t.margin_pct}%</Text>
            </Pressable>
          ))}
        </ScrollView>
      </Sheet>

      {/* Save as template */}
      <Sheet visible={saveTplSheet} onClose={() => setSaveTplSheet(false)} title="Save as Template" testID="estimate-savetpl-sheet">
        <Text style={styles.label}>Template name</Text>
        <TextInput style={styles.input} value={tplName} onChangeText={setTplName} placeholder="e.g. Standard equipment install" placeholderTextColor={colors.muted} testID="estimate-tpl-name" />
        <View style={{ height: spacing.md }} />
        <PrimaryButton title="Save Template" icon="albums" onPress={saveAsTemplate} testID="estimate-tpl-save" />
      </Sheet>
    </View>
  );
}

function SummaryRow({ label, value, muted, accent }: { label: string; value: string; muted?: boolean; accent?: string }) {
  return (
    <View style={styles.sumRow}>
      <Text style={[styles.sumLabel, muted && { color: colors.muted }]}>{label}</Text>
      <Text style={[styles.sumValue, accent ? { color: accent } : null]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.md },
  input: { backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  selector: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48 },
  selectorText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  sectionHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginTop: spacing.lg, marginBottom: spacing.xs },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  linkText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  lineRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  lineDot: { width: 32, height: 32, borderRadius: 16, alignItems: "center", justifyContent: "center" },
  lineTitle: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  lineMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  lineAmt: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  addLineBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 46, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.brand, borderStyle: "dashed", marginTop: spacing.xs },
  addLineText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  pctRow: { flexDirection: "row", gap: spacing.md },
  summary: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginTop: spacing.lg },
  sumRow: { flexDirection: "row", justifyContent: "space-between", marginBottom: spacing.sm },
  sumLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary },
  sumValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  sellRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", borderTopWidth: 1, borderTopColor: colors.border, paddingTop: spacing.sm, marginTop: spacing.xs },
  sellLabel: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  sellValue: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.brand },
  gmText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#16A34A", textAlign: "right", marginTop: 2 },
  convertBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.sm, height: 48, borderRadius: radius.md, backgroundColor: "#7C3AED" },
  convertText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  tplBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.sm, height: 46, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.brand },
  tplBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  pdfBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.md, height: 46, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.border, backgroundColor: colors.surface },
  pdfBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  pickRow: { paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  pickName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  pickMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, height: 36, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  pbBtn: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: spacing.sm },
  pbBtnText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
});
