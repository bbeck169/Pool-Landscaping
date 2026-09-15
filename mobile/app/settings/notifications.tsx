/**
 * Phase 41.5c · Feb-2026 — Mobile Notification Preferences.
 *
 * Native parity for the web ``/settings/notifications`` page
 * (``frontend/src/pages/settings/NotificationPrefs.jsx``). Per-user,
 * any authenticated caller — the web route has NO role guard beyond
 * the auth-required app shell. Endpoints reused verbatim:
 *   • GET /api/settings/notifications
 *       → { kinds: [{key,label}], channels: {[kind]: {bell,push,email,sms}},
 *           quiet_hours: {enabled, start_time, end_time, timezone} }
 *   • PUT /api/settings/notifications
 *       body { channels, quiet_hours? } → same shape as GET.
 *
 * Non-optimistic save (matches web): local edits stay in a dirty
 * draft until the user taps Save; the whole payload is PUT in one
 * request. No push-token registration here (out of scope).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable,
  Switch, TouchableOpacity, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import CommsWhitelistBanner from "@/src/components/comms/CommsWhitelistBanner";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Channel = "bell" | "push" | "email" | "sms";
type ChannelMap = Partial<Record<Channel, boolean>>;
type Kind = { key: string; label: string };
type QuietHours = {
  enabled: boolean;
  start_time: string;
  end_time: string;
  timezone: string;
};

const CHANNELS: { key: Channel; label: string; icon: any }[] = [
  { key: "bell",  label: "Bell",  icon: "notifications-outline" },
  { key: "push",  label: "Push",  icon: "phone-portrait-outline" },
  { key: "email", label: "Email", icon: "mail-outline" },
  { key: "sms",   label: "SMS",   icon: "chatbubble-outline" },
];

const TIMEZONES = [
  "UTC",
  "America/Phoenix",
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
];

const DEFAULT_QUIET: QuietHours = {
  enabled: false, start_time: "22:00", end_time: "07:00", timezone: "UTC",
};

function clone<T>(v: T): T { return JSON.parse(JSON.stringify(v)); }

export default function NotificationPrefsScreen() {
  const { user } = useAuth();
  const authed = !!user?.id;

  const [kinds, setKinds] = useState<Kind[]>([]);
  const [channels, setChannels] = useState<Record<string, ChannelMap>>({});
  const [initial, setInitial] = useState<Record<string, ChannelMap>>({});
  const [quiet, setQuiet] = useState<QuietHours>(DEFAULT_QUIET);
  const [initialQuiet, setInitialQuiet] = useState<QuietHours>(DEFAULT_QUIET);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    if (!authed) { setLoading(false); return; }
    try {
      const r = await api.get("/settings/notifications");
      setKinds(r?.kinds || []);
      const ch = r?.channels || {};
      setChannels(ch);
      setInitial(clone(ch));
      const qh = r?.quiet_hours || DEFAULT_QUIET;
      setQuiet(qh);
      setInitialQuiet(clone(qh));
    } catch {
      /* silent — matches web */
    } finally {
      setLoading(false);
    }
  }, [authed]);

  useEffect(() => { load(); }, [load]);

  const dirty =
    JSON.stringify(channels) !== JSON.stringify(initial) ||
    JSON.stringify(quiet) !== JSON.stringify(initialQuiet);

  const flip = (kindKey: string, chan: Channel) => {
    setChannels((prev) => ({
      ...prev,
      [kindKey]: { ...(prev[kindKey] || {}), [chan]: !prev?.[kindKey]?.[chan] },
    }));
  };

  const setAll = (chan: Channel, value: boolean) => {
    setChannels((prev) => {
      const next: Record<string, ChannelMap> = { ...prev };
      for (const k of kinds) {
        next[k.key] = { ...(next[k.key] || {}), [chan]: value };
      }
      return next;
    });
  };

  const reset = () => {
    setChannels(clone(initial));
    setQuiet(clone(initialQuiet));
  };

  const showToast = (ok: boolean, text: string) => {
    setToast({ ok, text });
    setTimeout(() => setToast(null), ok ? 2000 : 3000);
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = { channels, quiet_hours: quiet };
      const { data: r, queued } = await offlineWrite({
        op_type: "notification_settings.update",
        entity_id: "self",
        endpoint: "/settings/notifications",
        method: "PUT",
        payload,
        onlineFn: () => api.put("/settings/notifications", payload),
      });
      if (r) {
        const nextCh = r?.channels || channels;
        const nextQh = r?.quiet_hours || quiet;
        setChannels(nextCh);
        setInitial(clone(nextCh));
        setQuiet(nextQh);
        setInitialQuiet(clone(nextQh));
      }
      showToast(true, queued ? "Saved offline — will sync later" : "Preferences saved");
    } catch (e: any) {
      showToast(false, e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (!authed) {
    return (
      <View style={s.root} testID="notif-prefs-unauth">
        <Header title="Notification Preferences" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Sign in to manage notifications.</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root} testID="notif-prefs-screen">
      <Header title="Notification Preferences"
              subtitle="Choose how you get each alert"
              back />

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator size="large" color={colors.brand}
                             testID="notif-prefs-loading" />
        </View>
      ) : (
        <ScrollView
          testID="notif-prefs-scroll"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        >
          {/* Task 1 · Feb-2026 — Outbound comms whitelist banner. */}
          <CommsWhitelistBanner />
          {toast ? (
            <View style={[s.toast,
                          { backgroundColor: toast.ok ? "#DCFCE7" : "#FEE2E2" }]}
                  testID="notif-prefs-toast">
              <Text style={[s.toastText,
                            { color: toast.ok ? "#166534" : "#991B1B" }]}>
                {toast.text}
              </Text>
            </View>
          ) : null}

          {/* Channel column header + "all on / all off" per column */}
          <View style={s.headerRow}>
            <Text style={[s.headerLabel, { flex: 1 }]}>Kind</Text>
            {CHANNELS.map((c) => (
              <View key={c.key} style={s.channelHeaderCell}>
                <Ionicons name={c.icon} size={12} color={colors.onSurface} />
                <Text style={s.channelHeaderLabel}>{c.label}</Text>
                <View style={s.allBtnRow}>
                  <Pressable
                    onPress={() => setAll(c.key, true)}
                    testID={`notif-prefs-all-on-${c.key}`}
                    style={s.allBtn}
                  >
                    <Text style={[s.allBtnText, { color: colors.brand }]}>on</Text>
                  </Pressable>
                  <Text style={s.allBtnDivider}>·</Text>
                  <Pressable
                    onPress={() => setAll(c.key, false)}
                    testID={`notif-prefs-all-off-${c.key}`}
                    style={s.allBtn}
                  >
                    <Text style={[s.allBtnText, { color: colors.muted }]}>off</Text>
                  </Pressable>
                </View>
              </View>
            ))}
          </View>

          {kinds.map((k) => {
            const row: ChannelMap = channels[k.key] || {};
            return (
              <View key={k.key} style={s.kindRow}
                    testID={`notif-prefs-row-${k.key}`}>
                <Text style={s.kindLabel} numberOfLines={2}>{k.label}</Text>
                {CHANNELS.map((c) => (
                  <View key={c.key} style={s.toggleCell}>
                    <Switch
                      value={!!row[c.key]}
                      onValueChange={() => flip(k.key, c.key)}
                      testID={`notif-prefs-toggle-${k.key}-${c.key}`}
                    />
                  </View>
                ))}
              </View>
            );
          })}

          {kinds.length === 0 ? (
            <View style={s.emptyCard} testID="notif-prefs-empty">
              <Text style={s.emptyText}>
                No notification kinds available yet.
              </Text>
            </View>
          ) : null}

          {/* Quiet hours */}
          <View style={s.quietCard} testID="notif-quiet-hours-card">
            <View style={s.quietHeader}>
              <View style={{ flex: 1 }}>
                <Text style={s.quietTitle}>Quiet hours</Text>
                <Text style={s.quietHint}>
                  Push is silenced during this window. In-app bell still records.
                </Text>
              </View>
              <Switch
                value={!!quiet.enabled}
                onValueChange={(v) => setQuiet((q) => ({ ...q, enabled: v }))}
                testID="notif-quiet-hours-toggle"
              />
            </View>
            <View style={s.timeRow}>
              <View style={{ flex: 1 }}>
                <Text style={s.timeLabel}>Start</Text>
                <AppTextInput
                  testID="notif-quiet-hours-start"
                  style={[s.timeInput, !quiet.enabled && { opacity: 0.5 }]}
                  editable={!!quiet.enabled}
                  value={quiet.start_time || "22:00"}
                  onChangeText={(v) => setQuiet((q) => ({ ...q, start_time: v }))}
                  placeholder="HH:MM"
                  placeholderTextColor={colors.muted}
                  autoCapitalize="none"
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={s.timeLabel}>End</Text>
                <AppTextInput
                  testID="notif-quiet-hours-end"
                  style={[s.timeInput, !quiet.enabled && { opacity: 0.5 }]}
                  editable={!!quiet.enabled}
                  value={quiet.end_time || "07:00"}
                  onChangeText={(v) => setQuiet((q) => ({ ...q, end_time: v }))}
                  placeholder="HH:MM"
                  placeholderTextColor={colors.muted}
                  autoCapitalize="none"
                />
              </View>
            </View>
            <Text style={s.timeLabel}>Timezone</Text>
            <ScrollView
              horizontal showsHorizontalScrollIndicator={false}
              contentContainerStyle={s.tzRow}
              testID="notif-quiet-hours-tz-strip"
            >
              {TIMEZONES.map((tz) => {
                const active = quiet.timezone === tz;
                return (
                  <Pressable
                    key={tz}
                    onPress={() => setQuiet((q) => ({ ...q, timezone: tz }))}
                    disabled={!quiet.enabled}
                    style={[s.tzChip,
                            active && s.tzChipActive,
                            !quiet.enabled && { opacity: 0.5 }]}
                    testID={`notif-quiet-hours-tz-${tz}`}
                  >
                    <Text style={[s.tzChipText,
                                  active && s.tzChipTextActive]}>
                      {tz}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </View>

          {/* Action row */}
          <View style={s.actionRow}>
            <TouchableOpacity
              onPress={reset}
              disabled={!dirty}
              style={[s.btnGhost, !dirty && { opacity: 0.5 }]}
              testID="notif-prefs-reset"
            >
              <Ionicons name="arrow-undo" size={14} color={colors.onSurface} />
              <Text style={s.btnGhostText}>Undo</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={save}
              disabled={!dirty || saving}
              style={[s.btnPrimary, (!dirty || saving) && { opacity: 0.5 }]}
              testID="notif-prefs-save"
            >
              <Ionicons name="save" size={14} color="#fff" />
              <Text style={s.btnPrimaryText}>
                {saving ? "Saving\u2026" : "Save changes"}
              </Text>
            </TouchableOpacity>
          </View>
        </ScrollView>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },

  toast: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: radius.md, marginBottom: spacing.md,
    alignSelf: "flex-start",
  },
  toastText: { fontFamily: font.bold, fontSize: fontSize.sm },

  headerRow: {
    flexDirection: "row", alignItems: "flex-end",
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.md, borderTopRightRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
  },
  headerLabel: {
    fontFamily: font.bold, fontSize: 10, textTransform: "uppercase",
    letterSpacing: 0.8, color: colors.muted,
  },
  channelHeaderCell: {
    width: 62, alignItems: "center", gap: 2,
  },
  channelHeaderLabel: {
    fontFamily: font.bold, fontSize: 10, color: colors.onSurface,
  },
  allBtnRow: {
    flexDirection: "row", alignItems: "center", gap: 2, marginTop: 2,
  },
  allBtn: { paddingHorizontal: 4 },
  allBtnText: { fontFamily: font.bold, fontSize: 9, textTransform: "uppercase" },
  allBtnDivider: { color: colors.muted, fontSize: 9 },

  kindRow: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.surface,
    borderLeftWidth: 1, borderRightWidth: 1, borderBottomWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md, paddingVertical: spacing.md,
  },
  kindLabel: {
    flex: 1, fontFamily: font.medium, fontSize: fontSize.sm,
    color: colors.onSurface, paddingRight: spacing.sm,
  },
  toggleCell: { width: 62, alignItems: "center" },

  emptyCard: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.lg, alignItems: "center", marginTop: spacing.md,
  },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },

  quietCard: {
    marginTop: spacing.lg,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
  },
  quietHeader: { flexDirection: "row", alignItems: "center",
                  gap: spacing.sm, marginBottom: spacing.sm },
  quietTitle: { fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface },
  quietHint:  { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted,
                  marginTop: 2 },
  timeRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  timeLabel: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase",
                letterSpacing: 0.8, color: colors.muted, marginBottom: 4,
                marginTop: spacing.sm },
  timeInput: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
  },
  tzRow: { gap: 6, paddingVertical: 4 },
  tzChip: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  tzChipActive: {
    backgroundColor: colors.brand, borderColor: colors.brand,
  },
  tzChipText: { fontFamily: font.regular, fontSize: 11, color: colors.onSurface },
  tzChipTextActive: { color: "#fff", fontFamily: font.bold },

  actionRow: {
    flexDirection: "row", gap: spacing.sm, marginTop: spacing.lg,
    justifyContent: "flex-end",
  },
  btnGhost: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: 10, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  btnGhostText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onSurface },
  btnPrimary: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: 10, borderRadius: radius.md,
    backgroundColor: colors.brand,
  },
  btnPrimaryText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
