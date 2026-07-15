/**
 * Phase 29A · Mobile Wave A parity — Batch checks + Payroll CSV.
 *
 * Two flows in one screen (toggle at top):
 *   1. Batch checks — pick bank + payees + amounts → POST /checks/batch →
 *      open the generated 3-up PDF in the device browser via Linking.
 *   2. Payroll CSV — pick a bank, pick a .csv (expo-document-picker), POST
 *      /checks/payroll/import-csv (preview) → shows validation rows →
 *      execute → open the resulting batch PDF.
 *
 * Endpoints (Phase 26.3 batch + payroll — pre-existing, admin-only):
 *   GET  /api/checks/bank-accounts
 *   GET  /api/checks/payees
 *   POST /api/checks/batch { bank_account_id, checks: [...] }
 *   POST /api/checks/batch/{bid}/print       → PDF stream (open via URL)
 *   GET  /api/checks/payroll/template.csv    → download starter CSV
 *   POST /api/checks/payroll/import-csv?bank_account_id=...&execute=false|true
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Platform, Linking,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import * as DocumentPicker from "expo-document-picker";

import { api, api_base, getAuthToken } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

type Bank = { id: string; nickname: string; bank_name?: string; account_number_last4?: string; current_balance?: number };
type Payee = { id: string; name: string; kind?: string };
type Line = { id: string; payee_id: string; amount: string; date: string; memo: string };

const todayISO = () => new Date().toISOString().slice(0, 10);

export default function PayrollBatchMobile() {
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";

  const [tab, setTab] = useState<"batch" | "csv">("batch");
  const [banks, setBanks] = useState<Bank[]>([]);
  const [payees, setPayees] = useState<Payee[]>([]);
  const [bankId, setBankId] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, p] = await Promise.all([
        api.get("/checks/bank-accounts"),
        api.get("/checks/payees"),
      ]);
      const bItems: Bank[] = b.items || [];
      setBanks(bItems);
      setPayees(p.items || []);
      if (bItems.length && !bankId) setBankId(bItems[0].id);
    } catch {
      /* silent — page shows empty state */
    } finally { setLoading(false); }
  }, [bankId]);

  useFocusEffect(useCallback(() => {
    if (isAdmin) load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]));

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <Header title="Batch checks + Payroll" />
        <View style={styles.forbid}>
          <Ionicons name="lock-closed-outline" size={28} color={colors.muted} />
          <Text style={styles.forbidTitle}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <Header title="Batch checks + Payroll" subtitle="Write many checks at once" />

      <View style={styles.tabs} testID="payroll-tabs">
        {(["batch", "csv"] as const).map((t) => {
          const active = tab === t;
          return (
            <Pressable
              key={t}
              onPress={() => setTab(t)}
              style={[styles.tab, active && styles.tabActive]}
              testID={`payroll-tab-${t}`}
            >
              <Ionicons
                name={t === "batch" ? "list-outline" : "cloud-upload-outline"}
                size={14}
                color={active ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text style={[styles.tabText, active && { color: "#fff" }]}>
                {t === "batch" ? "Manual batch" : "Payroll CSV"}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {loading && banks.length === 0 ? (
        <View style={styles.center}><ActivityIndicator color={colors.brand} /></View>
      ) : banks.length === 0 ? (
        <View style={styles.emptyCard} testID="payroll-no-bank">
          <Ionicons name="wallet-outline" size={28} color={colors.muted} />
          <Text style={styles.emptyText}>No bank accounts yet</Text>
          <Text style={styles.emptySub}>Add a bank account on desktop first: /admin/checks/bank-accounts.</Text>
        </View>
      ) : (
        <BankPicker banks={banks} value={bankId} onChange={setBankId} />
      )}

      {banks.length > 0 && tab === "batch" ? (
        <BatchTab bankId={bankId} payees={payees} onDone={load} />
      ) : null}
      {banks.length > 0 && tab === "csv" ? (
        <CsvTab bankId={bankId} onDone={load} />
      ) : null}
    </View>
  );
}

/* ─── Bank picker (chip row) ────────────────────────────────────────── */
function BankPicker({ banks, value, onChange }: { banks: Bank[]; value: string; onChange: (v: string) => void }) {
  return (
    <View style={styles.bankPicker}>
      <Text style={styles.bankLabel}>PAY FROM</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.xs }}>
        {banks.map((b) => {
          const active = value === b.id;
          return (
            <Pressable
              key={b.id}
              onPress={() => onChange(b.id)}
              style={[styles.bankChip, active && styles.bankChipActive]}
              testID={`payroll-bank-${b.id}`}
            >
              <Text style={[styles.bankChipText, active && { color: "#fff" }]} numberOfLines={1}>
                {b.nickname}
              </Text>
              {b.account_number_last4 ? (
                <Text style={[styles.bankChipMeta, active && { color: "#DBEAFE" }]}>••{b.account_number_last4}</Text>
              ) : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

/* ─── Manual batch tab ──────────────────────────────────────────────── */
function BatchTab({ bankId, payees, onDone }: { bankId: string; payees: Payee[]; onDone: () => void }) {
  const [lines, setLines] = useState<Line[]>([]);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ text: string; kind: "info" | "err" } | null>(null);
  const [created, setCreated] = useState<any | null>(null);

  const total = useMemo(
    () => lines.reduce((s, l) => s + (Number(l.amount) || 0), 0),
    [lines],
  );

  const addLine = () => setLines((cur) => [...cur, {
    id: Math.random().toString(36).slice(2, 9),
    payee_id: payees[0]?.id || "",
    amount: "",
    date: todayISO(),
    memo: "",
  }]);
  const updateLine = (id: string, patch: Partial<Line>) =>
    setLines((cur) => cur.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  const removeLine = (id: string) =>
    setLines((cur) => cur.filter((l) => l.id !== id));

  const submit = async () => {
    if (!bankId) { setMsg({ text: "Pick a bank first.", kind: "err" }); return; }
    if (lines.length === 0) { setMsg({ text: "Add at least one check.", kind: "err" }); return; }
    if (lines.some((l) => !l.payee_id || Number(l.amount) <= 0)) {
      setMsg({ text: "Every line needs a payee and a positive amount.", kind: "err" });
      return;
    }
    setSaving(true); setMsg(null); setCreated(null);
    try {
      const r = await api.post("/checks/batch", {
        bank_account_id: bankId,
        checks: lines.map((l) => ({
          payee_id: l.payee_id,
          amount: Number(l.amount),
          date: l.date,
          memo: l.memo,
        })),
      });
      setCreated(r);
      setLines([]);
      setMsg({ text: `Batch created · ${r.checks?.length || 0} checks`, kind: "info" });
      onDone();
    } catch (e: any) {
      setMsg({ text: e.message || "Batch failed", kind: "err" });
    } finally { setSaving(false); }
  };

  const openBatchPdf = async () => {
    if (!created?.id) return;
    // POST endpoint returns a PDF stream on server. On mobile we open the
    // URL directly in the device browser; the JWT is attached via a query
    // param convention some backends use — but our server accepts bearer,
    // so we fall back to Linking + copy URL alert if the platform can't
    // include an Authorization header on a plain-URL Linking.
    const url = `${api_base()}/checks/batch/${created.id}/print`;
    try { await Linking.openURL(url); }
    catch {
      setMsg({ text: "Couldn't open PDF; copy this URL on desktop: " + url, kind: "err" });
    }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
      {msg ? (
        <View
          style={[batchStyles.msg, msg.kind === "err" ? batchStyles.msgErr : batchStyles.msgInfo]}
          testID="payroll-msg"
        >
          <Ionicons
            name={msg.kind === "err" ? "warning-outline" : "checkmark-circle-outline"}
            size={14}
            color={msg.kind === "err" ? colors.error : "#059669"}
          />
          <Text style={[batchStyles.msgText, msg.kind === "err" ? { color: colors.error } : { color: "#166534" }]}>
            {msg.text}
          </Text>
        </View>
      ) : null}

      {created ? (
        <View style={batchStyles.createdCard} testID="payroll-created">
          <Text style={batchStyles.createdTitle}>Batch #{created.id?.slice(0, 8)}… ready</Text>
          <Text style={batchStyles.createdMeta}>
            {created.checks?.length || 0} checks · total ${Number(created.total || 0).toFixed(2)}
          </Text>
          <Pressable onPress={openBatchPdf} style={batchStyles.pdfBtn} testID="payroll-print">
            <Ionicons name="print-outline" size={14} color="#fff" />
            <Text style={batchStyles.pdfBtnText}>Open PDF in browser</Text>
          </Pressable>
        </View>
      ) : null}

      {payees.length === 0 ? (
        <View style={batchStyles.warn}>
          <Text style={batchStyles.warnText}>
            No payees exist yet. Add payees on desktop first: /admin/checks/payees.
          </Text>
        </View>
      ) : (
        <>
          {lines.map((l) => (
            <View key={l.id} style={batchStyles.lineCard} testID={`payroll-line-${l.id}`}>
              <View style={batchStyles.lineHead}>
                <Text style={batchStyles.lineIdx}>#{lines.findIndex((x) => x.id === l.id) + 1}</Text>
                <Pressable onPress={() => removeLine(l.id)} testID={`payroll-line-remove-${l.id}`} hitSlop={10}>
                  <Ionicons name="trash-outline" size={16} color={colors.error} />
                </Pressable>
              </View>
              <Text style={batchStyles.fieldLabel}>PAYEE</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.xs }}>
                {payees.map((p) => {
                  const active = l.payee_id === p.id;
                  return (
                    <Pressable
                      key={p.id}
                      onPress={() => updateLine(l.id, { payee_id: p.id })}
                      style={[batchStyles.payeeChip, active && batchStyles.payeeChipActive]}
                      testID={`payroll-payee-${l.id}-${p.id}`}
                    >
                      <Text style={[batchStyles.payeeChipText, active && { color: "#fff" }]}>
                        {p.name}
                      </Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
              <View style={batchStyles.fieldRow}>
                <View style={{ flex: 1 }}>
                  <Text style={batchStyles.fieldLabel}>AMOUNT</Text>
                  <TextInput
                    value={l.amount}
                    onChangeText={(v) => updateLine(l.id, { amount: v })}
                    keyboardType="decimal-pad"
                    placeholder="0.00"
                    placeholderTextColor={colors.muted}
                    style={batchStyles.input}
                    testID={`payroll-amount-${l.id}`}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={batchStyles.fieldLabel}>DATE</Text>
                  <TextInput
                    value={l.date}
                    onChangeText={(v) => updateLine(l.id, { date: v })}
                    placeholder="YYYY-MM-DD"
                    placeholderTextColor={colors.muted}
                    autoCapitalize="none"
                    autoCorrect={false}
                    style={batchStyles.input}
                    testID={`payroll-date-${l.id}`}
                  />
                </View>
              </View>
              <Text style={batchStyles.fieldLabel}>MEMO (OPTIONAL)</Text>
              <TextInput
                value={l.memo}
                onChangeText={(v) => updateLine(l.id, { memo: v })}
                placeholder="e.g. May payroll"
                placeholderTextColor={colors.muted}
                style={batchStyles.input}
                testID={`payroll-memo-${l.id}`}
              />
            </View>
          ))}

          <Pressable onPress={addLine} style={batchStyles.addBtn} testID="payroll-add-line">
            <Ionicons name="add-circle-outline" size={16} color={colors.brand} />
            <Text style={batchStyles.addBtnText}>Add another check</Text>
          </Pressable>

          {lines.length > 0 ? (
            <>
              <View style={batchStyles.totalRow}>
                <Text style={batchStyles.totalLabel}>Batch total</Text>
                <Text style={batchStyles.totalVal} testID="payroll-total">${total.toFixed(2)}</Text>
              </View>
              <Pressable
                onPress={submit}
                disabled={saving}
                style={[batchStyles.submitBtn, saving && { opacity: 0.5 }]}
                testID="payroll-submit"
              >
                {saving
                  ? <ActivityIndicator color="#fff" />
                  : <Ionicons name="checkmark-circle" size={16} color="#fff" />}
                <Text style={batchStyles.submitBtnText}>
                  {saving ? "Creating…" : `Generate ${lines.length} check${lines.length === 1 ? "" : "s"}`}
                </Text>
              </Pressable>
            </>
          ) : null}
        </>
      )}
    </ScrollView>
  );
}

/* ─── CSV import tab ───────────────────────────────────────────────── */
function CsvTab({ bankId, onDone }: { bankId: string; onDone: () => void }) {
  const [file, setFile] = useState<{ uri: string; name: string; mimeType?: string } | null>(null);
  const [preview, setPreview] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; kind: "info" | "err" } | null>(null);
  const [created, setCreated] = useState<any | null>(null);

  const pick = async () => {
    setMsg(null);
    const res = await DocumentPicker.getDocumentAsync({
      type: ["text/csv", "text/comma-separated-values", "text/plain", "application/vnd.ms-excel", "*/*"],
      multiple: false,
      copyToCacheDirectory: true,
    });
    if (res.canceled) return;
    const a = res.assets?.[0];
    if (!a) return;
    setFile({ uri: a.uri, name: a.name || "payroll.csv", mimeType: a.mimeType });
    setPreview(null); setCreated(null);
  };

  const uploadTemplateUrl = `${api_base()}/checks/payroll/template.csv`;

  const send = async (execute: boolean) => {
    if (!bankId) { setMsg({ text: "Pick a bank first.", kind: "err" }); return; }
    if (!file) { setMsg({ text: "Pick a CSV file first.", kind: "err" }); return; }
    setBusy(true); setMsg(null);
    try {
      // Build multipart body via fetch (RN FormData handles the blob for us).
      const form = new FormData();
      // @ts-ignore — RN FormData accepts this shape
      form.append("csv_file", {
        uri: file.uri,
        name: file.name,
        type: file.mimeType || "text/csv",
      });
      const token = await getAuthToken();
      const url = `${api_base()}/checks/payroll/import-csv?bank_account_id=${encodeURIComponent(bankId)}${execute ? "&execute=true" : ""}`;
      const res = await fetch(url, {
        method: "POST",
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          // NOTE: do NOT set Content-Type; RN fills the multipart boundary.
        },
        body: form as any,
      });
      const text = await res.text();
      const json = text ? JSON.parse(text) : {};
      if (!res.ok) {
        const detail = json.detail || `HTTP ${res.status}`;
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }
      if (execute) {
        setCreated(json);
        setPreview(null);
        setMsg({ text: `Executed · ${json.checks?.length || json.total_checks || 0} checks`, kind: "info" });
        onDone();
      } else {
        setPreview(json);
        setMsg({ text: `Previewed ${json.rows?.length || 0} rows. Review then Execute.`, kind: "info" });
      }
    } catch (e: any) {
      setMsg({ text: e.message || "CSV upload failed", kind: "err" });
    } finally { setBusy(false); }
  };

  const openBatchPdf = async () => {
    if (!created?.batch?.id && !created?.id) return;
    const bid = created.batch?.id || created.id;
    const url = `${api_base()}/checks/batch/${bid}/print`;
    try { await Linking.openURL(url); }
    catch { setMsg({ text: "Couldn't open PDF: " + url, kind: "err" }); }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
      <View style={csvStyles.templateCard} testID="payroll-template-card">
        <Ionicons name="document-text-outline" size={22} color={colors.brand} />
        <View style={{ flex: 1 }}>
          <Text style={csvStyles.templateTitle}>Need a starter?</Text>
          <Text style={csvStyles.templateSub}>
            Grab the CSV template on desktop, fill it in, then upload here.
          </Text>
        </View>
        <Pressable
          onPress={() => Linking.openURL(uploadTemplateUrl)}
          style={csvStyles.templateBtn}
          testID="payroll-template-btn"
        >
          <Text style={csvStyles.templateBtnText}>Template</Text>
        </Pressable>
      </View>

      <Pressable onPress={pick} style={csvStyles.pickBtn} testID="payroll-file-pick">
        <Ionicons name="folder-open-outline" size={16} color={colors.brand} />
        <Text style={csvStyles.pickBtnText}>{file ? "Change file" : "Pick a .csv file"}</Text>
      </Pressable>
      {file ? (
        <Text style={csvStyles.fileName} testID="payroll-file-name">
          <Ionicons name="document-outline" size={12} color={colors.muted} />{" "}
          {file.name}
        </Text>
      ) : null}

      {msg ? (
        <View
          style={[batchStyles.msg, msg.kind === "err" ? batchStyles.msgErr : batchStyles.msgInfo]}
          testID="payroll-msg"
        >
          <Ionicons
            name={msg.kind === "err" ? "warning-outline" : "checkmark-circle-outline"}
            size={14}
            color={msg.kind === "err" ? colors.error : "#059669"}
          />
          <Text style={[batchStyles.msgText, msg.kind === "err" ? { color: colors.error } : { color: "#166534" }]}>
            {msg.text}
          </Text>
        </View>
      ) : null}

      <View style={csvStyles.actionRow}>
        <Pressable
          onPress={() => send(false)}
          disabled={busy || !file || !bankId}
          style={[csvStyles.previewBtn, (busy || !file || !bankId) && { opacity: 0.4 }]}
          testID="payroll-preview-btn"
        >
          {busy ? <ActivityIndicator color={colors.brand} size="small" />
                : <Ionicons name="eye-outline" size={14} color={colors.brand} />}
          <Text style={csvStyles.previewBtnText}>Preview</Text>
        </Pressable>
        <Pressable
          onPress={() => send(true)}
          disabled={busy || !file || !bankId || !preview}
          style={[csvStyles.execBtn, (busy || !file || !bankId || !preview) && { opacity: 0.4 }]}
          testID="payroll-execute-btn"
        >
          {busy ? <ActivityIndicator color="#fff" size="small" />
                : <Ionicons name="rocket-outline" size={14} color="#fff" />}
          <Text style={csvStyles.execBtnText}>Execute</Text>
        </Pressable>
      </View>

      {preview?.rows?.length ? (
        <View style={csvStyles.previewCard} testID="payroll-preview">
          <Text style={csvStyles.previewTitle}>{preview.rows.length} rows</Text>
          {preview.warnings?.length ? (
            <Text style={csvStyles.previewWarn}>
              ⚠ {preview.warnings.length} row-level warning{preview.warnings.length === 1 ? "" : "s"} — desktop shows full detail.
            </Text>
          ) : null}
          {preview.rows.slice(0, 20).map((r: any, i: number) => (
            <View key={i} style={csvStyles.previewRow} testID={`payroll-row-${i}`}>
              <View style={{ flex: 1 }}>
                <Text style={csvStyles.previewRowName}>{r.payee_name || r.name || "?"}</Text>
                <Text style={csvStyles.previewRowMeta}>
                  ${Number(r.amount || 0).toFixed(2)}
                  {r.date ? ` · ${r.date}` : ""}
                  {r.memo ? ` · ${r.memo}` : ""}
                </Text>
              </View>
              {r.status || r.error ? (
                <View style={[csvStyles.statusPill, {
                  backgroundColor: r.error ? "#FEE2E2" : "#DCFCE7",
                }]}>
                  <Text style={{
                    fontFamily: font.bold, fontSize: 10,
                    color: r.error ? colors.error : "#059669",
                  }}>{r.error ? "ERR" : (r.status || "OK")}</Text>
                </View>
              ) : null}
            </View>
          ))}
          {preview.rows.length > 20 ? (
            <Text style={csvStyles.previewMore}>+{preview.rows.length - 20} more rows on execute.</Text>
          ) : null}
        </View>
      ) : null}

      {created ? (
        <View style={batchStyles.createdCard} testID="payroll-executed">
          <Text style={batchStyles.createdTitle}>
            Batch created · {created.batch?.checks?.length ?? created.checks?.length ?? 0} checks
          </Text>
          <Pressable onPress={openBatchPdf} style={batchStyles.pdfBtn} testID="payroll-print-executed">
            <Ionicons name="print-outline" size={14} color="#fff" />
            <Text style={batchStyles.pdfBtnText}>Open PDF in browser</Text>
          </Pressable>
        </View>
      ) : null}
    </ScrollView>
  );
}

/* ─── Styles ───────────────────────────────────────────────────────── */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { padding: spacing.xl, alignItems: "center" },
  forbid: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.sm },
  forbidTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.muted },
  tabs: {
    flexDirection: "row",
    gap: spacing.xs,
    paddingHorizontal: spacing.lg,
    marginTop: spacing.md,
  },
  tab: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tabActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  tabText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  bankPicker: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    gap: spacing.xs,
  },
  bankLabel: {
    fontFamily: font.semibold,
    fontSize: 10,
    letterSpacing: 1,
    color: colors.muted,
  },
  bankChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    minWidth: 130,
    gap: 2,
  },
  bankChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  bankChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  bankChipMeta: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
  emptyCard: {
    margin: spacing.lg,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    padding: spacing.xl,
    alignItems: "center",
    gap: spacing.xs,
  },
  emptyText: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  emptySub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
});

const batchStyles = StyleSheet.create({
  msg: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    padding: spacing.sm,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  msgInfo: { backgroundColor: "#F0FDF4", borderWidth: 1, borderColor: "#86EFAC" },
  msgErr: { backgroundColor: "#FEE2E2", borderWidth: 1, borderColor: "#FCA5A5" },
  msgText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm },
  warn: {
    padding: spacing.md,
    backgroundColor: "#FEF9C3",
    borderWidth: 1,
    borderColor: "#FDE68A",
    borderRadius: radius.md,
  },
  warnText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#92400E" },
  lineCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
    gap: spacing.xs,
  },
  lineHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  lineIdx: {
    fontFamily: font.bold,
    fontSize: fontSize.xs,
    color: colors.muted,
    letterSpacing: 0.5,
  },
  fieldLabel: {
    fontFamily: font.semibold,
    fontSize: 10,
    letterSpacing: 0.8,
    color: colors.muted,
    marginTop: spacing.xs,
  },
  fieldRow: { flexDirection: "row", gap: spacing.sm },
  input: {
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 44,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  payeeChip: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  payeeChipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  payeeChipText: { fontFamily: font.semibold, fontSize: fontSize.xs, color: colors.onSurface },
  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1.5,
    borderColor: colors.brand,
    borderStyle: "dashed",
    borderRadius: radius.md,
    marginTop: spacing.xs,
  },
  addBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.brand },
  totalRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    marginTop: spacing.md,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
  },
  totalLabel: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: colors.onBrandTertiary,
  },
  totalVal: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.onBrandTertiary },
  submitBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    height: 52,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
    marginTop: spacing.sm,
  },
  submitBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
  createdCard: {
    padding: spacing.md,
    backgroundColor: "#F0FDF4",
    borderWidth: 1,
    borderColor: "#86EFAC",
    borderRadius: radius.md,
    marginBottom: spacing.md,
    gap: spacing.xs,
  },
  createdTitle: { fontFamily: font.bold, fontSize: fontSize.base, color: "#166534" },
  createdMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#166534" },
  pdfBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    backgroundColor: "#059669",
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    marginTop: spacing.xs,
  },
  pdfBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});

const csvStyles = StyleSheet.create({
  templateCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    padding: spacing.md,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  templateTitle: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onBrandTertiary },
  templateSub: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.onBrandTertiary, marginTop: 2 },
  templateBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
  },
  templateBtnText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
  pickBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: colors.brand,
    backgroundColor: colors.surface,
    marginBottom: spacing.xs,
  },
  pickBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.brand },
  fileName: {
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    marginBottom: spacing.md,
  },
  actionRow: { flexDirection: "row", gap: spacing.xs },
  previewBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    paddingVertical: spacing.sm + 2,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.brand,
  },
  previewBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.brand },
  execBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    paddingVertical: spacing.sm + 2,
    borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  execBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
  previewCard: {
    marginTop: spacing.md,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
  },
  previewTitle: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: colors.muted,
    marginBottom: spacing.xs,
  },
  previewWarn: {
    fontFamily: font.medium,
    fontSize: fontSize.xs,
    color: "#A16207",
    marginBottom: spacing.xs,
  },
  previewRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.xs,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: spacing.xs,
  },
  previewRowName: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  previewRowMeta: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 1 },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
  },
  previewMore: {
    marginTop: spacing.xs,
    fontFamily: font.regular,
    fontSize: fontSize.xs,
    color: colors.muted,
    textAlign: "center",
  },
});
