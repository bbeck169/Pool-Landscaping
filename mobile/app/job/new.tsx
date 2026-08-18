import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { PrimaryButton, Sheet } from "@/src/components/ui";
import { Field } from "@/app/customer/new";

const SERVICE_TYPES = ["Pool Cleaning", "Repair", "Landscaping", "Inspection", "Installation"];

export default function JobForm() {
  const router = useRouter();
  // Feb-2026 · JobDetail "+ New Scheduled Job" hook — the parent
  // screen pushes /job/new with pre-fill params derived from the
  // current job (customer/technician/service/date). We hydrate the
  // form state below once the /customers + /technicians lists have
  // loaded so the picker labels resolve.
  const prefill = useLocalSearchParams<{
    customer_id?: string;
    technician_id?: string;
    service_type?: string;
    scheduled_date?: string;
  }>();
  const [customers, setCustomers] = useState<any[]>([]);
  const [techs, setTechs] = useState<any[]>([]);
  const [customer, setCustomer] = useState<any>(null);
  const [tech, setTech] = useState<any>(null);
  const [title, setTitle] = useState("");
  const [serviceType, setServiceType] = useState(prefill?.service_type || "Pool Cleaning");
  const [date, setDate] = useState(
    prefill?.scheduled_date || new Date().toISOString().slice(0, 10),
  );
  const [price, setPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [sheet, setSheet] = useState<null | "customer" | "tech" | "service">(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.get("/customers").then((rows) => {
      setCustomers(rows);
      // Feb-2026 · Pre-fill selection when the parent (JobDetail
      // "+ New Scheduled Job" flow) passes an explicit customer_id.
      if (prefill?.customer_id) {
        const c = (rows || []).find((r: any) => r.id === prefill.customer_id);
        if (c) setCustomer(c);
      }
    });
    api.get("/technicians").then((rows) => {
      setTechs(rows);
      if (prefill?.technician_id) {
        const t = (rows || []).find((r: any) => r.id === prefill.technician_id);
        if (t) setTech(t);
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    if (!title.trim() || !customer) {
      setError("Title and customer are required");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.post("/jobs", {
        title,
        customer_id: customer.id,
        technician_id: tech?.id || null,
        service_type: serviceType,
        scheduled_date: date,
        price: parseFloat(price) || 0,
        notes,
      });
      router.back();
    } catch (e: any) {
      setError(e.message || "Failed to create job");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <Header title="New Job" back />
      <KeyboardAwareScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }} bottomOffset={24} keyboardShouldPersistTaps="handled">
        <Field label="Job Title *" value={title} onChangeText={setTitle} placeholder="e.g. Weekly Pool Cleaning" testID="job-title-input" />

        <Selector label="Customer *" value={customer?.name} placeholder="Select customer" onPress={() => setSheet("customer")} testID="select-customer" />
        <Selector label="Technician" value={tech?.name} placeholder="Unassigned" onPress={() => setSheet("tech")} testID="select-technician" />
        <Selector label="Service Type" value={serviceType} onPress={() => setSheet("service")} testID="select-service" />

        <Field label="Scheduled Date" value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" testID="job-date-input" />
        <Field label="Price ($)" value={price} onChangeText={setPrice} placeholder="0.00" keyboardType="decimal-pad" testID="job-price-input" />
        <Field label="Notes" value={notes} onChangeText={setNotes} placeholder="Instructions…" multiline testID="job-notes-input" />

        {error ? <Text style={styles.error} testID="job-form-error">{error}</Text> : null}
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title="Create Job" onPress={save} loading={busy} testID="save-job-button" />
      </KeyboardAwareScrollView>

      <Sheet visible={sheet === "customer"} onClose={() => setSheet(null)} title="Select Customer" testID="customer-sheet">
        {customers.map((c) => (
          <Pressable key={c.id} style={styles.opt} onPress={() => { setCustomer(c); setSheet(null); }} testID={`pick-customer-${c.id}`}>
            <Text style={styles.optText}>{c.name}</Text>
            {customer?.id === c.id ? <Ionicons name="checkmark" size={20} color={colors.brand} /> : null}
          </Pressable>
        ))}
      </Sheet>
      <Sheet visible={sheet === "tech"} onClose={() => setSheet(null)} title="Select Technician" testID="technician-sheet">
        <Pressable style={styles.opt} onPress={() => { setTech(null); setSheet(null); }}>
          <Text style={styles.optText}>Unassigned</Text>
        </Pressable>
        {techs.map((t) => (
          <Pressable key={t.id} style={styles.opt} onPress={() => { setTech(t); setSheet(null); }} testID={`pick-tech-${t.id}`}>
            <Text style={styles.optText}>{t.name}</Text>
            {tech?.id === t.id ? <Ionicons name="checkmark" size={20} color={colors.brand} /> : null}
          </Pressable>
        ))}
      </Sheet>
      <Sheet visible={sheet === "service"} onClose={() => setSheet(null)} title="Service Type" testID="service-sheet">
        {SERVICE_TYPES.map((s) => (
          <Pressable key={s} style={styles.opt} onPress={() => { setServiceType(s); setSheet(null); }} testID={`pick-service-${s}`}>
            <Text style={styles.optText}>{s}</Text>
            {serviceType === s ? <Ionicons name="checkmark" size={20} color={colors.brand} /> : null}
          </Pressable>
        ))}
      </Sheet>
    </View>
  );
}

export function Selector({ label, value, placeholder, onPress, testID }: any) {
  return (
    <View style={{ marginBottom: spacing.md }}>
      <Text style={styles.label}>{label}</Text>
      <Pressable style={styles.selector} onPress={onPress} testID={testID}>
        <Text style={[styles.selectorText, !value && { color: colors.muted }]}>{value || placeholder}</Text>
        <Ionicons name="chevron-down" size={18} color={colors.muted} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  label: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  selector: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, height: 52,
  },
  selectorText: { fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface },
  opt: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider },
  optText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.onSurface },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
});
