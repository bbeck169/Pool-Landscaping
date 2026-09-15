/**
 * Phase 29A · Mobile Wave A parity — Weather Reschedule.
 *
 * Mobile port of `/admin/dispatch/weather`. Runs the daily weather scan,
 * lists proposed weather-reschedule events, lets admin accept (with optional
 * override date) or reject each one.
 *
 * Endpoints (all Phase 26 Wave A, pre-existing):
 *   GET  /api/dispatch/weather-events            → { items: [...] }
 *   GET  /api/dispatch/settings                  → weather thresholds + mode
 *   POST /api/dispatch/weather-scan {}           → { scanned, affected, mode }
 *   POST /api/dispatch/weather-events/{id}/accept { override_date? }
 *   POST /api/dispatch/weather-events/{id}/reject
 *   PUT  /api/dispatch/settings { weather_reschedule_mode | rain_threshold_pct | wind_threshold_mph }
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

type WeatherEvent = {
  id: string;
  job_id: string;
  original_date: string;
  proposed_date: string;
  actual_date: string | null;
  rain_prob_pct: number;
  wind_mph: number;
  mode: string;
  status: "proposed" | "accepted" | "rejected" | "auto_moved" | string;
  decided_by?: string | null;
  decided_at?: string | null;
};

type DispatchSettings = {
  weather_reschedule_mode: "manual" | "auto";
  rain_threshold_pct: number;
  wind_threshold_mph: number;
};

const STATUS_META: Record<string, { color: string; bg: string; label: string }> = {
  proposed:   { color: "#A16207", bg: "#FEF9C3", label: "Proposed" },
  accepted:   { color: "#059669", bg: "#DCFCE7", label: "Accepted" },
  auto_moved: { color: "#059669", bg: "#DCFCE7", label: "Auto-moved" },
  rejected:   { color: "#6B7280", bg: "#F3F4F6", label: "Rejected" },
};

export default function WeatherRescheduleMobile() {
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";

  const [events, setEvents] = useState<WeatherEvent[]>([]);
  const [settings, setSettings] = useState<DispatchSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [busyEvent, setBusyEvent] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ text: string; kind: "info" | "err" } | null>(null);
  const [overrideOpen, setOverrideOpen] = useState<string | null>(null);
  const [overrideDate, setOverrideDate] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [e, s] = await Promise.all([
        api.get("/dispatch/weather-events"),
        api.get("/dispatch/settings"),
      ]);
      setEvents(e.items || []);
      setSettings(s);
    } catch (e: any) {
      setMsg({ text: e.message || "Failed to load", kind: "err" });
    } finally { setLoading(false); }
  }, []);

  useFocusEffect(useCallback(() => {
    if (isAdmin) load();
  }, [isAdmin, load]));

  const scan = async () => {
    setScanning(true); setMsg(null);
    try {
      const r = await api.post("/dispatch/weather-scan", {});
      setMsg({
        text: `Scanned ${r.scanned ?? "?"} outdoor jobs · ${r.affected ?? 0} affected in ${r.mode || "manual"} mode`,
        kind: "info",
      });
      await load();
    } catch (e: any) {
      setMsg({ text: e.message || "Scan failed", kind: "err" });
    } finally { setScanning(false); }
  };

  const decide = async (id: string, action: "accept" | "reject", override?: string) => {
    setBusyEvent(id); setMsg(null);
    try {
      await api.post(
        `/dispatch/weather-events/${id}/${action}`,
        override ? { override_date: override } : {},
      );
      setMsg({
        text: action === "accept" ? "Reschedule accepted" : "Proposal rejected",
        kind: "info",
      });
      setOverrideOpen(null); setOverrideDate("");
      await load();
    } catch (e: any) {
      setMsg({ text: e.message || "Action failed", kind: "err" });
    } finally { setBusyEvent(null); }
  };

  const setMode = async (mode: "manual" | "auto") => {
    if (!settings) return;
    try {
      const r = await api.put("/dispatch/settings", { weather_reschedule_mode: mode });
      setSettings(r);
    } catch (e: any) {
      setMsg({ text: e.message || "Failed", kind: "err" });
    }
  };

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <Header title="Weather reschedule" />
        <View style={styles.forbid}>
          <Ionicons name="lock-closed-outline" size={28} color={colors.muted} />
          <Text style={styles.forbidTitle}>Admins only</Text>
        </View>
      </View>
    );
  }

  const proposed = events.filter((e) => e.status === "proposed");
  const decided = events.filter((e) => e.status !== "proposed");

  return (
    <View style={styles.root}>
      <Header title="Weather reschedule" subtitle="Move outdoor jobs when rain or wind spikes" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        {settings ? (
          <View style={styles.settingsCard} testID="weather-settings-card">
            <Text style={styles.settingsTitle}>Mode</Text>
            <View style={styles.modeRow}>
              {(["manual", "auto"] as const).map((m) => {
                const active = settings.weather_reschedule_mode === m;
                return (
                  <Pressable
                    key={m}
                    onPress={() => setMode(m)}
                    style={[styles.mode, active && styles.modeActive]}
                    testID={`weather-mode-${m}`}
                  >
                    <Text style={[styles.modeText, active && { color: "#fff" }]}>
                      {m === "manual" ? "Manual (propose)" : "Auto (move now)"}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
            <Text style={styles.settingsMeta}>
              Triggers when rain ≥ <Text style={styles.b}>{settings.rain_threshold_pct}%</Text>
              {" or wind ≥ "}<Text style={styles.b}>{settings.wind_threshold_mph} mph</Text>.
              {"\n"}Change thresholds on desktop → /admin/dispatch/weather.
            </Text>
          </View>
        ) : null}

        <Pressable
          onPress={scan}
          disabled={scanning}
          style={[styles.scanBtn, scanning && { opacity: 0.6 }]}
          testID="weather-scan-btn"
        >
          {scanning
            ? <ActivityIndicator color="#fff" size="small" />
            : <Ionicons name="cloud-outline" size={16} color="#fff" />}
          <Text style={styles.scanBtnText}>
            {scanning ? "Scanning today + tomorrow…" : "Run weather scan"}
          </Text>
        </Pressable>

        {msg ? (
          <View
            style={[styles.msg, msg.kind === "err" ? styles.msgErr : styles.msgInfo]}
            testID="weather-msg"
          >
            <Ionicons
              name={msg.kind === "err" ? "warning-outline" : "checkmark-circle-outline"}
              size={14}
              color={msg.kind === "err" ? colors.error : "#059669"}
            />
            <Text style={[styles.msgText, msg.kind === "err" ? { color: colors.error } : { color: "#166534" }]}>
              {msg.text}
            </Text>
          </View>
        ) : null}

        {loading ? (
          <View style={styles.center}><ActivityIndicator color={colors.brand} /></View>
        ) : (
          <>
            <Text style={styles.sectionTitle}>
              <Ionicons name="alert-circle-outline" size={13} color={colors.muted} />{"  "}
              Proposed · {proposed.length}
            </Text>
            {proposed.length === 0 ? (
              <View style={styles.emptyCard} testID="weather-no-proposed">
                <Text style={styles.emptyText}>No pending weather proposals.</Text>
                <Text style={styles.emptySub}>Tap &quot;Run weather scan&quot; to check today + tomorrow&apos;s outdoor jobs.</Text>
              </View>
            ) : proposed.map((ev) => (
              <EventCard
                key={ev.id}
                ev={ev}
                busy={busyEvent === ev.id}
                overrideOpen={overrideOpen === ev.id}
                overrideDate={overrideDate}
                onOverrideOpen={(open) => { setOverrideOpen(open ? ev.id : null); setOverrideDate(""); }}
                onOverrideDate={setOverrideDate}
                onAccept={(override) => decide(ev.id, "accept", override)}
                onReject={() => decide(ev.id, "reject")}
              />
            ))}

            {decided.length > 0 ? (
              <>
                <Text style={[styles.sectionTitle, { marginTop: spacing.lg }]}>Decided · {decided.length}</Text>
                {decided.slice(0, 20).map((ev) => (
                  <EventCard key={ev.id} ev={ev} readOnly />
                ))}
              </>
            ) : null}
          </>
        )}
      </ScrollView>
    </View>
  );
}

function EventCard({
  ev, busy, overrideOpen, overrideDate,
  onOverrideOpen, onOverrideDate, onAccept, onReject, readOnly,
}: {
  ev: WeatherEvent;
  busy?: boolean;
  overrideOpen?: boolean;
  overrideDate?: string;
  onOverrideOpen?: (open: boolean) => void;
  onOverrideDate?: (v: string) => void;
  onAccept?: (override?: string) => void;
  onReject?: () => void;
  readOnly?: boolean;
}) {
  const meta = STATUS_META[ev.status] || { color: colors.muted, bg: "#F3F4F6", label: ev.status };
  return (
    <View style={cardStyles.card} testID={`weather-event-${ev.id}`}>
      <View style={cardStyles.head}>
        <View style={[cardStyles.statusPill, { backgroundColor: meta.bg }]}>
          <Text style={[cardStyles.statusText, { color: meta.color }]}>{meta.label}</Text>
        </View>
        <Text style={cardStyles.jobId}>Job {ev.job_id.slice(0, 8)}…</Text>
      </View>
      <View style={cardStyles.datesRow}>
        <View style={cardStyles.dateCol}>
          <Text style={cardStyles.dateLabel}>ORIGINAL</Text>
          <Text style={cardStyles.dateVal}>{ev.original_date}</Text>
        </View>
        <Ionicons name="arrow-forward" size={16} color={colors.muted} />
        <View style={cardStyles.dateCol}>
          <Text style={cardStyles.dateLabel}>{ev.actual_date ? "MOVED TO" : "PROPOSED"}</Text>
          <Text style={cardStyles.dateVal}>{ev.actual_date || ev.proposed_date}</Text>
        </View>
      </View>
      <Text style={cardStyles.reason}>
        Rain <Text style={cardStyles.b}>{ev.rain_prob_pct}%</Text>
        {" · "}Wind <Text style={cardStyles.b}>{ev.wind_mph} mph</Text>
        {" · "}mode <Text style={cardStyles.b}>{ev.mode}</Text>
      </Text>

      {!readOnly && onAccept && onReject ? (
        <>
          {overrideOpen ? (
            <View style={cardStyles.overrideBox}>
              <Text style={cardStyles.overrideLabel}>Override date (YYYY-MM-DD)</Text>
              <AppTextInput
                testID={`weather-override-input-${ev.id}`}
                value={overrideDate}
                onChangeText={onOverrideDate}
                placeholder={ev.proposed_date}
                placeholderTextColor={colors.muted}
                autoCapitalize="none"
                autoCorrect={false}
                style={cardStyles.overrideInput}
              />
              <View style={cardStyles.overrideRow}>
                <Pressable
                  onPress={() => onOverrideOpen?.(false)}
                  style={[cardStyles.btn, cardStyles.btnGhost]}
                  testID={`weather-override-cancel-${ev.id}`}
                >
                  <Text style={cardStyles.btnGhostText}>Cancel</Text>
                </Pressable>
                <Pressable
                  onPress={() => onAccept(overrideDate || undefined)}
                  disabled={busy}
                  style={[cardStyles.btn, cardStyles.btnAccept, busy && { opacity: 0.5 }]}
                  testID={`weather-accept-override-${ev.id}`}
                >
                  <Text style={cardStyles.btnAcceptText}>Accept with override</Text>
                </Pressable>
              </View>
            </View>
          ) : (
            <View style={cardStyles.actions}>
              <Pressable
                onPress={onReject}
                disabled={busy}
                style={[cardStyles.btn, cardStyles.btnReject, busy && { opacity: 0.5 }]}
                testID={`weather-reject-${ev.id}`}
              >
                <Ionicons name="close-circle-outline" size={14} color={colors.error} />
                <Text style={cardStyles.btnRejectText}>Reject</Text>
              </Pressable>
              <Pressable
                onPress={() => onOverrideOpen?.(true)}
                disabled={busy}
                style={[cardStyles.btn, cardStyles.btnGhost]}
                testID={`weather-override-open-${ev.id}`}
              >
                <Ionicons name="calendar-outline" size={14} color={colors.brand} />
                <Text style={cardStyles.btnGhostText}>Override…</Text>
              </Pressable>
              <Pressable
                onPress={() => onAccept()}
                disabled={busy}
                style={[cardStyles.btn, cardStyles.btnAccept, busy && { opacity: 0.5 }]}
                testID={`weather-accept-${ev.id}`}
              >
                {busy ? <ActivityIndicator color="#fff" size="small" />
                      : <Ionicons name="checkmark-circle" size={14} color="#fff" />}
                <Text style={cardStyles.btnAcceptText}>Accept</Text>
              </Pressable>
            </View>
          )}
        </>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { padding: spacing.xl, alignItems: "center" },
  forbid: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.xl, gap: spacing.sm },
  forbidTitle: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.muted },
  settingsCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
    gap: spacing.sm,
  },
  settingsTitle: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: colors.muted,
  },
  settingsMeta: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, lineHeight: 16 },
  b: { fontFamily: font.semibold, color: colors.onSurface },
  modeRow: { flexDirection: "row", gap: spacing.sm },
  mode: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
  },
  modeActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  modeText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  scanBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: spacing.xs,
    backgroundColor: colors.brand,
    height: 48,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  scanBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff" },
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
  sectionTitle: {
    fontFamily: font.semibold,
    fontSize: 11,
    letterSpacing: 1,
    textTransform: "uppercase",
    color: colors.muted,
    marginBottom: spacing.sm,
  },
  emptyCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    padding: spacing.xl,
    alignItems: "center",
    gap: spacing.xs,
  },
  emptyText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  emptySub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textAlign: "center" },
});

const cardStyles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
    gap: spacing.sm,
  },
  head: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  statusPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  statusText: { fontFamily: font.bold, fontSize: 10, letterSpacing: 0.5 },
  jobId: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginLeft: "auto" },
  datesRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  dateCol: { alignItems: "flex-start", gap: 2 },
  dateLabel: { fontFamily: font.semibold, fontSize: 10, letterSpacing: 0.5, color: colors.muted },
  dateVal: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  reason: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  b: { fontFamily: font.semibold, color: colors.onSurface },
  actions: { flexDirection: "row", gap: spacing.xs, marginTop: spacing.xs },
  btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.md,
    minHeight: 34,
  },
  btnAccept: { backgroundColor: colors.brand, flex: 1, justifyContent: "center" },
  btnAcceptText: { fontFamily: font.bold, fontSize: fontSize.xs, color: "#fff" },
  btnReject: { backgroundColor: "#fff", borderWidth: 1, borderColor: "#FCA5A5" },
  btnRejectText: { fontFamily: font.bold, fontSize: fontSize.xs, color: colors.error },
  btnGhost: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  btnGhostText: { fontFamily: font.semibold, fontSize: fontSize.xs, color: colors.brand },
  overrideBox: { gap: spacing.xs },
  overrideLabel: {
    fontFamily: font.semibold, fontSize: 10, letterSpacing: 0.5,
    color: colors.muted, textTransform: "uppercase",
  },
  overrideInput: {
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
  overrideRow: { flexDirection: "row", gap: spacing.xs },
});
