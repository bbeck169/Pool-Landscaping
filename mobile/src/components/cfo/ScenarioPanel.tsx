/**
 * Phase 34c · Mobile Scenario Planner panel.
 *
 * Mirror of `/app/frontend/src/components/cfo/ScenarioPanel.jsx`.
 * Structured params (hire techs / hourly rate / price-change % /
 * customer churn) + optional free-text prompt → POST /api/cfo/scenario.
 *
 * Renders the returned 12-month delta as a compact 4-column grid
 * (Month · ΔRev · ΔExp · ΔNet) since recharts is desktop-only in this
 * repo. Annual KPI tiles, confidence badge, caveats bullets, and
 * favorite-toggle mirror the web behaviour. When `result.mocked===true`
 * we still render the zero-filled grid so the layout stays honest.
 * History drawer reads `GET /api/cfo/scenario/history?limit=20` and
 * pins favorites to the top.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, Pressable, ScrollView, ActivityIndicator, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Customer = { customer_id?: string; customer_name?: string; total?: number };
type ScenarioResult = {
  assumptions?: string[];
  monthly_delta?: {
    month: number;
    revenue_delta?: number;
    expense_delta?: number;
    net_delta?: number;
  }[];
  annual?: {
    revenue_delta?: number;
    expense_delta?: number;
    net_delta?: number;
    margin_delta_pct?: number;
  };
  confidence?: "high" | "medium" | "low" | string;
  caveats?: string[];
  mocked?: boolean;
  reason?: string;
};
type Current = {
  id?: string;
  result: ScenarioResult;
  tokens_used: number;
  favorite?: boolean;
  prompt: string;
  structured?: any;
  created_at: string;
  readonly?: boolean;
};

const fmtUSD = (n?: number) => {
  if (typeof n !== "number") return "—";
  try {
    return n.toLocaleString(undefined, {
      style: "currency", currency: "USD", maximumFractionDigits: 0,
    });
  } catch { return `$${Math.round(n)}`; }
};
const relTime = (iso?: string | null) => {
  if (!iso) return "";
  const s = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`;
  return new Date(iso).toLocaleDateString();
};
const _synthesizePrompt = (s: any) => {
  const parts: string[] = [];
  if (s.hire_techs) parts.push(`hire ${s.hire_techs} techs at $${s.avg_hourly_rate}/hr`);
  if (s.price_change_pct) parts.push(`change prices by ${s.price_change_pct}%`);
  if ((s.customer_churn || []).length) parts.push(`lose ${s.customer_churn.length} customers`);
  return parts.length ? `Scenario: ${parts.join("; ")}.` : "";
};
const CONF_COLOR: Record<string, string> = {
  high: "#059669", medium: "#B45309", low: "#B91C1C",
};

export type ScenarioPanelProps = {
  topCustomers?: Customer[];
  onUsageChange?: () => void;
};

export default function ScenarioPanel({
  topCustomers = [], onUsageChange,
}: ScenarioPanelProps) {
  const [prompt, setPrompt] = useState("");
  const [hireTechs, setHireTechs] = useState(0);
  const [hourlyRate, setHourlyRate] = useState(20);
  const [priceChangePct, setPriceChangePct] = useState(0);
  const [churn, setChurn] = useState<string[]>([]);
  const [current, setCurrent] = useState<Current | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [quotaHit, setQuotaHit] = useState<any>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const rows: any = await api.get(`/cfo/scenario/history?limit=20`);
      const arr = Array.isArray(rows) ? rows : rows?.items || [];
      arr.sort((a: any, b: any) => {
        if (!!b.favorite !== !!a.favorite) return (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0);
        return (new Date(b.created_at).getTime() || 0) - (new Date(a.created_at).getTime() || 0);
      });
      setHistory(arr);
    } catch (_) { /* silent */ }
    finally { setHistoryLoading(false); }
  }, []);
  useEffect(() => { if (historyOpen) loadHistory(); }, [historyOpen, loadHistory]);

  const toggleChurn = (id: string) => {
    setChurn((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };
  const bumpPrice = (delta: number) => {
    setPriceChangePct((p) => Math.max(-20, Math.min(50, p + delta)));
  };

  const submit = async (force = false) => {
    if (busy) return;
    const structured = {
      hire_techs: Number(hireTechs) || 0,
      avg_hourly_rate: Number(hourlyRate) || 0,
      price_change_pct: Number(priceChangePct) || 0,
      customer_churn: churn,
    };
    const body: any = {
      prompt: prompt.trim() || _synthesizePrompt(structured),
      structured,
    };
    if (!body.prompt) { setErr("Give a prompt or move a slider off zero."); return; }
    setBusy(true); setErr(""); setQuotaHit(null); setCurrent(null);
    try {
      const path = `/cfo/scenario${force ? "?force=true" : ""}`;
      const r: any = await api.post(path, body);
      if (r?.error === "quota_exceeded") { setQuotaHit(r.usage || {}); return; }
      setCurrent({
        id: r.history_id, result: r.result, tokens_used: r.tokens_used || 0,
        favorite: false, prompt: body.prompt, structured,
        created_at: new Date().toISOString(),
      });
      onUsageChange?.();
      if (historyOpen) loadHistory();
    } catch (e: any) {
      setErr(e?.message || "Scenario request failed.");
    } finally { setBusy(false); }
  };

  const toggleFavorite = async () => {
    if (!current?.id) return;
    const next = !current.favorite;
    try {
      await api.post(`/cfo/scenario/${current.id}/save-as-favorite?favorite=${next}`);
      setCurrent({ ...current, favorite: next });
      if (historyOpen) loadHistory();
    } catch (_) { /* silent */ }
  };

  const loadFromHistory = (row: any) => {
    setCurrent({
      id: row.id, result: row.result, tokens_used: row.tokens_used || 0,
      favorite: !!row.favorite, prompt: row.prompt, structured: row.structured || {},
      created_at: row.created_at, readonly: true,
    });
    setPrompt(row.prompt || "");
    const s = row.structured || {};
    setHireTechs(s.hire_techs ?? 0);
    setHourlyRate(s.avg_hourly_rate ?? 20);
    setPriceChangePct(s.price_change_pct ?? 0);
    setChurn(s.customer_churn || []);
  };

  // Always render 12 months so a `mocked:true` result still shows a
  // zero-filled grid.
  const monthlyRaw = current?.result?.monthly_delta || [];
  const monthly = Array.from({ length: 12 }, (_, i) => {
    const m = monthlyRaw[i] || { month: i + 1 };
    return {
      month: m.month ?? i + 1,
      revenue_delta: (m as any).revenue_delta ?? 0,
      expense_delta: (m as any).expense_delta ?? 0,
      net_delta: (m as any).net_delta ?? 0,
    };
  });

  return (
    <View style={styles.card} testID="cfo-scenario-panel">
      <View style={styles.headerRow}>
        <Ionicons name="trending-up-outline" size={16} color={colors.brand} />
        <Text style={styles.headerTitle}>Scenario Planner</Text>
        <View style={{ flex: 1 }} />
        <Pressable
          onPress={() => setHistoryOpen((x) => !x)}
          testID="cfo-scenario-history-toggle"
          style={styles.historyBtn}
          hitSlop={6}
        >
          <Ionicons name={historyOpen ? "chevron-up" : "chevron-down"} size={12} color={colors.muted} />
          <Text style={styles.historyBtnText}>History</Text>
        </Pressable>
      </View>

      {/* Structured inputs */}
      <View style={styles.inputGrid}>
        <View style={styles.inputCol}>
          <Text style={styles.label}>Hire techs</Text>
          <AppTextInput
            editable={!busy}
            keyboardType="number-pad"
            value={String(hireTechs)}
            onChangeText={(v) => setHireTechs(Math.max(0, Math.min(10, Number(v.replace(/[^0-9]/g, "")) || 0)))}
            style={styles.numInput}
            testID="cfo-scenario-hire-techs"
          />
        </View>
        <View style={styles.inputCol}>
          <Text style={styles.label}>Hourly rate ($)</Text>
          <AppTextInput
            editable={!busy}
            keyboardType="decimal-pad"
            value={String(hourlyRate)}
            onChangeText={(v) => setHourlyRate(parseFloat(v) || 0)}
            style={styles.numInput}
            testID="cfo-scenario-hourly-rate"
          />
        </View>
      </View>

      <View style={styles.inputColFull}>
        <Text style={styles.label}>
          Price change % ({priceChangePct >= 0 ? "+" : ""}{priceChangePct}%)
        </Text>
        <View style={styles.priceRow} testID="cfo-scenario-price-change">
          <Pressable onPress={() => bumpPrice(-5)} disabled={busy} style={styles.priceBtn}>
            <Ionicons name="remove" size={16} color={colors.onSurface} />
          </Pressable>
          <AppTextInput
            editable={!busy}
            keyboardType="numbers-and-punctuation"
            value={String(priceChangePct)}
            onChangeText={(v) => {
              const n = parseInt(v.replace(/[^-0-9]/g, ""), 10);
              if (!Number.isFinite(n)) return;
              setPriceChangePct(Math.max(-20, Math.min(50, n)));
            }}
            style={[styles.numInput, { flex: 1, textAlign: "center" }]}
            testID="cfo-scenario-price-change-input"
          />
          <Pressable onPress={() => bumpPrice(5)} disabled={busy} style={styles.priceBtn}>
            <Ionicons name="add" size={16} color={colors.onSurface} />
          </Pressable>
        </View>
      </View>

      <View style={styles.inputColFull}>
        <Text style={styles.label}>Customers to churn</Text>
        {topCustomers.length === 0 ? (
          <Text style={styles.emptyNote} testID="cfo-scenario-churn-empty">
            No top customers loaded yet.
          </Text>
        ) : (
          <View style={styles.churnGrid} testID="cfo-scenario-churn">
            {topCustomers.slice(0, 10).map((cust) => {
              const id = cust.customer_id || cust.customer_name || "";
              const active = churn.includes(id);
              return (
                <Pressable
                  key={id}
                  onPress={() => toggleChurn(id)}
                  disabled={busy}
                  style={[styles.churnChip, active && styles.churnChipActive]}
                  testID={`cfo-scenario-churn-chip-${id}`}
                >
                  <Text style={[styles.churnChipText, active && styles.churnChipTextActive]} numberOfLines={1}>
                    {cust.customer_name}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        )}
      </View>

      <AppTextInput
        multiline
        numberOfLines={3}
        editable={!busy}
        value={prompt}
        onChangeText={setPrompt}
        placeholder="Optional free-text prompt (e.g. 'What if we win the HOA contract worth $8K/month?')"
        placeholderTextColor={colors.muted}
        style={styles.input}
        testID="cfo-scenario-prompt"
      />

      <View style={styles.actionRow}>
        <Text style={styles.hint}>Claude will project 12 months.</Text>
        <View style={{ flex: 1 }} />
        <Pressable
          onPress={() => submit(false)}
          disabled={busy}
          style={[styles.submitBtn, busy && styles.submitBtnDisabled]}
          testID="cfo-scenario-submit"
        >
          {busy
            ? <ActivityIndicator size="small" color="#fff" />
            : <Ionicons name="send" size={12} color="#fff" />}
          <Text style={styles.submitText}>Run</Text>
        </Pressable>
      </View>

      {err ? (
        <View style={styles.errBox} testID="cfo-scenario-error">
          <Text style={styles.errText}>{err}</Text>
        </View>
      ) : null}

      {quotaHit ? (
        <View style={styles.quotaBox} testID="cfo-scenario-quota-banner">
          <Text style={styles.quotaText}>
            Daily quota reached ({quotaHit.request_count}/{quotaHit.quota}).
          </Text>
          <Pressable onPress={() => submit(true)} style={styles.forceBtn} testID="cfo-scenario-force-submit">
            <Ionicons name="refresh" size={11} color="#fff" />
            <Text style={styles.forceText}>Force submit</Text>
          </Pressable>
        </View>
      ) : null}

      {busy ? (
        <View style={styles.loadingBox} testID="cfo-scenario-loading">
          <ActivityIndicator size="small" color={colors.brand} />
          <Text style={styles.loadingText}>Projecting 12 months…</Text>
        </View>
      ) : current?.result ? (
        <View style={styles.resultBox} testID="cfo-scenario-result">
          {current.result.mocked ? (
            <View style={styles.mockedBanner} testID="cfo-scenario-mocked-reason">
              <Ionicons name="warning-outline" size={12} color="#B45309" />
              <Text style={styles.mockedBannerText}>
                LLM unavailable — {current.result.reason || "no reason"}. Grid below is zero-filled.
              </Text>
            </View>
          ) : null}

          {/* Assumptions + prompt + favorite */}
          <View style={styles.section} testID="cfo-scenario-assumptions">
            <View style={styles.assumptionsHeader}>
              <Text style={styles.assumptionsTitle} numberOfLines={2}>
                Assumptions · <Text style={styles.assumptionsPrompt}>{current.prompt}</Text>
              </Text>
              <Pressable
                onPress={toggleFavorite}
                style={styles.favBtn}
                testID="cfo-scenario-favorite"
                hitSlop={6}
              >
                <Ionicons
                  name={current.favorite ? "star" : "star-outline"}
                  size={14}
                  color={current.favorite ? "#B45309" : colors.muted}
                />
                <Text style={[styles.favText, current.favorite && { color: "#B45309" }]}>
                  {current.favorite ? "Favorited" : "Save"}
                </Text>
              </Pressable>
            </View>
            {(current.result.assumptions || []).length === 0 ? (
              <Text style={styles.emptyNote}>No assumptions returned.</Text>
            ) : (
              (current.result.assumptions || []).map((a, i) => (
                <Text key={i} style={styles.bullet}>• {a}</Text>
              ))
            )}
          </View>

          {/* Monthly delta grid */}
          <View style={styles.section} testID="cfo-scenario-monthly">
            <Text style={styles.sectionTitle}>Monthly Δ (12 months)</Text>
            <View style={styles.tableHeader}>
              <Text style={[styles.tableHead, { flex: 1 }]}>MO</Text>
              <Text style={[styles.tableHead, { flex: 2, textAlign: "right" }]}>ΔREV</Text>
              <Text style={[styles.tableHead, { flex: 2, textAlign: "right" }]}>ΔEXP</Text>
              <Text style={[styles.tableHead, { flex: 2, textAlign: "right" }]}>ΔNET</Text>
            </View>
            {monthly.map((m) => {
              const net = Number(m.net_delta) || 0;
              return (
                <View key={m.month} style={styles.tableRow}>
                  <Text style={[styles.tableCell, { flex: 1 }]}>M{m.month}</Text>
                  <Text style={[styles.tableCell, { flex: 2, textAlign: "right", color: "#059669" }]}>
                    {fmtUSD(m.revenue_delta)}
                  </Text>
                  <Text style={[styles.tableCell, { flex: 2, textAlign: "right", color: "#B91C1C" }]}>
                    {fmtUSD(m.expense_delta)}
                  </Text>
                  <Text
                    style={[
                      styles.tableCell, { flex: 2, textAlign: "right", fontFamily: font.bold },
                      { color: net >= 0 ? "#059669" : "#B91C1C" },
                    ]}
                  >
                    {fmtUSD(m.net_delta)}
                  </Text>
                </View>
              );
            })}
          </View>

          {/* Annual tiles */}
          <View style={styles.tiles}>
            <View style={styles.tile} testID="cfo-scenario-annual-revenue">
              <Text style={styles.tileLabel}>Annual Δ Revenue</Text>
              <Text style={styles.tileValue}>{fmtUSD(current.result.annual?.revenue_delta)}</Text>
            </View>
            <View style={styles.tile} testID="cfo-scenario-annual-expense">
              <Text style={styles.tileLabel}>Annual Δ Expense</Text>
              <Text style={styles.tileValue}>{fmtUSD(current.result.annual?.expense_delta)}</Text>
            </View>
            <View style={styles.tile} testID="cfo-scenario-annual-net">
              <Text style={styles.tileLabel}>Annual Δ Net</Text>
              <Text style={[
                styles.tileValue,
                { color: (current.result.annual?.net_delta ?? 0) >= 0 ? "#059669" : "#B91C1C" },
              ]}>
                {fmtUSD(current.result.annual?.net_delta)}
              </Text>
            </View>
            <View style={styles.tile} testID="cfo-scenario-annual-margin">
              <Text style={styles.tileLabel}>Δ Margin %</Text>
              <Text style={styles.tileValue}>
                {typeof current.result.annual?.margin_delta_pct === "number"
                  ? `${current.result.annual.margin_delta_pct.toFixed(2)}%`
                  : "—"}
              </Text>
            </View>
          </View>

          {/* Confidence badge */}
          <View style={styles.confRow}>
            <View
              style={[
                styles.confBadge,
                { backgroundColor: CONF_COLOR[String(current.result.confidence || "").toLowerCase()] || colors.muted },
              ]}
              testID="cfo-scenario-confidence"
            >
              <Text style={styles.confText}>
                Confidence: {String(current.result.confidence || "unknown")}
              </Text>
            </View>
            <Text style={styles.confMeta}>
              {relTime(current.created_at)} · Tokens: {current.tokens_used}
              {current.readonly ? " · from history" : ""}
            </Text>
          </View>

          {(current.result.caveats || []).length > 0 ? (
            <View style={styles.caveats} testID="cfo-scenario-caveats">
              <Text style={styles.caveatsTitle}>Caveats</Text>
              {(current.result.caveats || []).map((cv, i) => (
                <Text key={i} style={styles.caveatItem}>• {cv}</Text>
              ))}
            </View>
          ) : null}
        </View>
      ) : null}

      {historyOpen ? (
        <View style={styles.historyList} testID="cfo-scenario-history-list">
          <Text style={styles.historyTitle}>History (latest 20 · favorites first)</Text>
          {historyLoading ? (
            <View style={styles.historyLoading}>
              <ActivityIndicator size="small" color={colors.brand} />
              <Text style={styles.historyLoadingText}>Loading…</Text>
            </View>
          ) : history.length === 0 ? (
            <Text style={styles.historyEmpty} testID="cfo-scenario-history-empty">
              No scenarios run yet.
            </Text>
          ) : (
            <ScrollView style={{ maxHeight: 260 }}>
              {history.map((row) => (
                <Pressable
                  key={row.id}
                  onPress={() => loadFromHistory(row)}
                  style={styles.historyItem}
                  testID="cfo-scenario-history-item"
                >
                  <Ionicons
                    name={row.favorite ? "star" : "trending-down-outline"}
                    size={12}
                    color={row.favorite ? "#B45309" : colors.muted}
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.historyItemQ} numberOfLines={2}>{row.prompt}</Text>
                    <Text style={styles.historyItemMeta}>
                      {relTime(row.created_at)} · Δnet {fmtUSD(row.result?.annual?.net_delta)}
                      {" "}· {row.tokens_used || 0} tokens
                      {row.result?.mocked ? " · mocked" : ""}
                    </Text>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
          )}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    backgroundColor: colors.surface, padding: spacing.md, marginTop: spacing.md,
  },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: spacing.sm },
  headerTitle: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  historyBtn: { flexDirection: "row", alignItems: "center", gap: 4 },
  historyBtnText: { fontFamily: font.semibold, fontSize: 11, color: colors.muted },
  inputGrid: { flexDirection: "row", gap: 8, marginBottom: 8 },
  inputCol: { flex: 1 },
  inputColFull: { marginBottom: 8 },
  label: {
    fontFamily: font.bold, fontSize: 10, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 4,
  },
  numInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 6,
    fontFamily: font.regular, fontSize: 13, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  priceRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  priceBtn: {
    width: 32, height: 32, alignItems: "center", justifyContent: "center",
    borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  emptyNote: { fontFamily: font.regular, fontSize: 11, color: colors.muted, fontStyle: "italic" },
  churnGrid: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  churnChip: {
    paddingHorizontal: 8, paddingVertical: 5, borderRadius: 999,
    backgroundColor: "#F1F5F9", maxWidth: "48%",
  },
  churnChipActive: { backgroundColor: colors.brand },
  churnChipText: { fontFamily: font.semibold, fontSize: 11, color: colors.onSurface },
  churnChipTextActive: { color: "#fff" },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: spacing.sm,
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
    textAlignVertical: "top", minHeight: 72, marginBottom: 8,
    backgroundColor: colors.surface,
  },
  actionRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  hint: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  submitBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brand, borderRadius: radius.sm,
    paddingHorizontal: spacing.md, paddingVertical: 8,
  },
  submitBtnDisabled: { opacity: 0.5 },
  submitText: { fontFamily: font.bold, fontSize: 12, color: "#fff" },
  errBox: {
    backgroundColor: "#FEE2E2", borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 6, marginTop: 8,
  },
  errText: { fontFamily: font.semibold, fontSize: 11, color: "#B91C1C" },
  quotaBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FEF3C7", borderRadius: radius.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 8, marginTop: 8,
  },
  quotaText: { flex: 1, fontFamily: font.regular, fontSize: 11, color: "#B45309" },
  forceBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#B45309", borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 4,
  },
  forceText: { fontFamily: font.bold, fontSize: 10, color: "#fff" },
  loadingBox: {
    marginTop: 12, borderRadius: radius.sm, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, borderStyle: "dashed",
    backgroundColor: colors.surfaceSecondary || "#F8FAFC",
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  loadingText: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  resultBox: { marginTop: 12, gap: 10 },
  mockedBanner: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#FEF3C7", borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 6,
  },
  mockedBannerText: { flex: 1, fontFamily: font.regular, fontSize: 11, color: "#B45309" },
  section: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    padding: spacing.sm, backgroundColor: colors.surfaceSecondary || "#F8FAFC",
  },
  sectionTitle: {
    fontFamily: font.bold, fontSize: 10, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6,
  },
  assumptionsHeader: {
    flexDirection: "row", alignItems: "flex-start", gap: 6, marginBottom: 6,
  },
  assumptionsTitle: {
    flex: 1, fontFamily: font.bold, fontSize: 10, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.6,
  },
  assumptionsPrompt: {
    fontFamily: font.regular, fontSize: 11, color: colors.onSurface,
    textTransform: "none", letterSpacing: 0,
  },
  favBtn: { flexDirection: "row", alignItems: "center", gap: 4 },
  favText: { fontFamily: font.bold, fontSize: 11, color: colors.muted },
  bullet: { fontFamily: font.regular, fontSize: 12, color: colors.onSurface, marginTop: 2 },
  tableHeader: {
    flexDirection: "row", paddingBottom: 4, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  tableHead: {
    fontFamily: font.bold, fontSize: 10, color: colors.muted,
    letterSpacing: 0.6,
  },
  tableRow: {
    flexDirection: "row", paddingVertical: 4, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  tableCell: {
    fontFamily: font.regular, fontSize: 11, color: colors.onSurface,
  },
  tiles: {
    flexDirection: "row", flexWrap: "wrap", gap: 6,
  },
  tile: {
    width: "48%", padding: spacing.sm, borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  tileLabel: {
    fontFamily: font.bold, fontSize: 9, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.6,
  },
  tileValue: {
    fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2,
  },
  confRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  confBadge: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.sm,
  },
  confText: {
    fontFamily: font.bold, fontSize: 10, color: "#fff",
    textTransform: "uppercase", letterSpacing: 0.4,
  },
  confMeta: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
  caveats: {
    borderWidth: 1, borderColor: "#B45309", borderRadius: radius.sm,
    padding: spacing.sm, backgroundColor: "#FEF3C7",
  },
  caveatsTitle: {
    fontFamily: font.bold, fontSize: 10, color: "#B45309",
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 4,
  },
  caveatItem: { fontFamily: font.regular, fontSize: 11, color: "#B45309", marginTop: 2 },
  historyList: {
    marginTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.border,
    paddingTop: spacing.sm,
  },
  historyTitle: {
    fontFamily: font.bold, fontSize: 10, color: colors.muted,
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6,
  },
  historyLoading: { flexDirection: "row", alignItems: "center", gap: 6 },
  historyLoadingText: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  historyEmpty: { fontFamily: font.regular, fontSize: 11, color: colors.muted },
  historyItem: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  historyItemQ: { fontFamily: font.semibold, fontSize: 12, color: colors.onSurface },
  historyItemMeta: { fontFamily: font.regular, fontSize: 10, color: colors.muted, marginTop: 2 },
});
