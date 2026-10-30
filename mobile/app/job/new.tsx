import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Pressable, Alert, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { Header } from "@/src/components/widgets";
import { PrimaryButton, Sheet } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { Field } from "@/app/customer/new";

/** Select Customer sheet search — case-insensitive text match on names +
 *  emails; digit-only match on phones when the query carries >= 3 digits. */
export function customerMatches(c: any, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const text = [
    c?.name, c?.display_name, c?.first_name, c?.last_name,
    [c?.first_name, c?.last_name].filter(Boolean).join(" "),
    c?.email, ...(Array.isArray(c?.emails) ? c.emails.map((e: any) => e?.address) : []),
  ];
  if (text.some((v) => typeof v === "string" && v.toLowerCase().includes(q))) return true;
  const qd = q.replace(/\D/g, "");
  if (qd.length < 3) return false;
  const phones = [c?.phone, ...(Array.isArray(c?.mobiles) ? c.mobiles.flatMap((m: any) => [m?.number_e164, m?.number]) : [])];
  return phones.some((p) => typeof p === "string" && p.replace(/\D/g, "").includes(qd));
}

const SERVICE_TYPES = ["Pool Cleaning", "Repair", "Landscaping", "Inspection", "Installation"];

export default function JobForm() {
  const router = useRouter();
  const { showToast } = useToast();
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
  // Feb-2026 · "+ New Scheduled Job" bug fix — respect an empty
  // ``service_type`` param from the JobDetail push (``??`` instead
  // of ``||`` so "" survives). Direct /job/new opens still land on
  // the "Pool Cleaning" default because the param is undefined
  // there.
  const [serviceType, setServiceType] = useState(
    prefill?.service_type ?? "Pool Cleaning",
  );
  const [date, setDate] = useState(
    prefill?.scheduled_date || new Date().toISOString().slice(0, 10),
  );
  const [price, setPrice] = useState("");
  const [notes, setNotes] = useState("");
  const [sheet, setSheet] = useState<null | "customer" | "tech" | "service">(null);
  const [custQuery, setCustQuery] = useState("");
  const filteredCustomers = useMemo(() => customers.filter((c) => customerMatches(c, custQuery)), [customers, custQuery]);
  const closeCustomerSheet = () => { setSheet(null); setCustQuery(""); };
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
      const body = {
        title,
        customer_id: customer.id,
        technician_id: tech?.id || null,
        service_type: serviceType,
        scheduled_date: date,
        price: parseFloat(price) || 0,
        notes,
      };
      const { queued } = await offlineWrite({
        op_type: "job.create",
        entity_id: customer.id,
        endpoint: "/jobs",
        method: "POST",
        payload: body,
        onlineFn: () => api.post("/jobs", body),
      });
      if (queued) {
        showToast("Job will be created when you're back online.", "info");
      }
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
        <Selector label="Service Type" value={serviceType} placeholder="Select service type" onPress={() => setSheet("service")} testID="select-service" />

        <Field label="Scheduled Date" value={date} onChangeText={setDate} placeholder="YYYY-MM-DD" testID="job-date-input" />
        <Field label="Price ($)" value={price} onChangeText={setPrice} placeholder="0.00" keyboardType="decimal-pad" testID="job-price-input" />
        <Field label="Notes" value={notes} onChangeText={setNotes} placeholder="Instructions…" multiline testID="job-notes-input" />

        {error ? <Text style={styles.error} testID="job-form-error">{error}</Text> : null}
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title="Create Job" onPress={save} loading={busy} testID="save-job-button" />
      </KeyboardAwareScrollView>

      <Sheet
        visible={sheet === "customer"} onClose={closeCustomerSheet} title="Select Customer" testID="customer-sheet"
        header={
          <View style={styles.searchBox}>
            <Ionicons name="search" size={18} color={colors.muted} />
            <AppTextInput
              style={styles.searchInput} value={custQuery} onChangeText={setCustQuery}
              placeholder="Search customers…" placeholderTextColor={colors.muted}
              autoCorrect={false} autoCapitalize="none" returnKeyType="search"
              testID="customer-sheet-search"
            />
            {custQuery ? (
              <Pressable onPress={() => setCustQuery("")} hitSlop={10} style={styles.searchClear} accessibilityLabel="Clear search" testID="customer-sheet-search-clear">
                <Ionicons name="close-circle" size={18} color={colors.muted} />
              </Pressable>
            ) : null}
          </View>
        }
      >
        {filteredCustomers.map((c) => (
          <Pressable key={c.id} style={styles.opt} onPress={() => { setCustomer(c); closeCustomerSheet(); }} testID={`pick-customer-${c.id}`}>
            <Text style={styles.optText}>{c.name}</Text>
            {customer?.id === c.id ? <Ionicons name="checkmark" size={20} color={colors.brand} /> : null}
          </Pressable>
        ))}
        {custQuery.trim() && filteredCustomers.length === 0 ? (
          <Text style={styles.searchEmpty} testID="customer-sheet-empty">{`No customers match '${custQuery.trim()}'`}</Text>
        ) : null}
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
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48,
  },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  searchClear: { minWidth: 32, minHeight: 44, alignItems: "center", justifyContent: "center" },
  searchEmpty: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", paddingVertical: spacing.xl },
  error: { color: colors.error, fontFamily: font.medium, fontSize: fontSize.base, marginTop: spacing.sm },
});
