/**
 * Phase S2 · Autopilot Schedules tab — global kill switch + 8-platform grid + recent actions.
 * Mirrors frontend/src/pages/soshie/AutopilotSchedulesTab.jsx
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Switch, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { Card } from "@/src/components/ui";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ── Skeleton ─────────────────────────────────────────────────── */
function Skeleton({ height = 60 }: { height?: number }) {
  return <View style={[s.skeleton, { height }]} />;
}

/* ── Chip ─────────────────────────────────────────────────────── */
function Chip({
  label, tone = "neutral", testID,
}: {
  label: string; tone?: "success" | "warning" | "danger" | "neutral"; testID?: string;
}) {
  const cfg = {
    success: { bg: "#DCFCE7", fg: "#166534" },
    warning: { bg: "#FEF3C7", fg: "#854D0E" },
    danger: { bg: "#FEE2E2", fg: "#991B1B" },
    neutral: { bg: colors.surfaceTertiary, fg: colors.muted },
  }[tone];
  return (
    <View style={[s.chip, { backgroundColor: cfg.bg }]} testID={testID}>
      <Text style={[s.chipText, { color: cfg.fg }]}>{label}</Text>
    </View>
  );
}

/* ── Platform grid moved to src/components/settings/PlatformGrid.tsx ── */

/* ── Global Kill Switch ──────────────────────────────────────── */
function GlobalKillSwitch({ disabled }: { disabled?: boolean }) {
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/soshie/autopilot/global")
      .then((r: any) => { setEnabled(!!r?.enabled); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const toggle = async () => {
    if (disabled) return;
    const next = !enabled;
    setEnabled(next); // optimistic
    try {
      await api.patch("/soshie/autopilot/global", { enabled: next });
      Alert.alert(
        "Updated",
        next ? "Autopilot enabled tenant-wide" : "Autopilot paused tenant-wide",
      );
    } catch (e: any) {
      setEnabled(!next); // revert
      Alert.alert("Failed", e?.message || "Could not update autopilot state");
    }
  };

  if (loading) return <Skeleton height={80} />;

  return (
    <Card style={s.card}>
      <View style={s.killRow} testID="global-kill-switch">
        <View style={{ flex: 1 }}>
          <View style={s.killTitleRow}>
            <Text style={s.killTitle}>Autopilot</Text>
            <Chip
              label={enabled ? "On" : "Paused"}
              tone={enabled ? "success" : "danger"}
              testID={enabled ? "global-status-on" : "global-status-off"}
            />
          </View>
          <Text style={s.killSub}>
            Tenant-wide kill switch. When off, all platforms are paused.
          </Text>
        </View>
        <Switch
          value={enabled}
          onValueChange={toggle}
          disabled={disabled}
          trackColor={{ false: "#94a3b8", true: colors.brand }}
          testID="global-kill-switch-toggle"
          accessibilityRole="switch"
          accessibilityLabel="Toggle autopilot"
          accessibilityState={{ checked: enabled }}
        />
      </View>
    </Card>
  );
}

/* ── Platform grid moved to src/components/settings/PlatformGrid.tsx ── */

/* ── Recent Actions Feed ─────────────────────────────────────── */
function RecentActionsFeed() {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/soshie/autopilot/recent-actions?limit=20")
      .then((r: any) => { setRows(r?.items || []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading) return <Skeleton height={100} />;

  return (
    <Card style={s.card}>
      <Text style={s.feedTitle}>Recent autopilot activity</Text>
      {!rows.length ? (
        <Text style={s.feedEmpty} testID="autopilot-recent-empty">
          Nothing yet. Once autopilot fires, the last 20 dispatches appear here.
        </Text>
      ) : (
        <View testID="autopilot-recent-list">
          {rows.map((r: any) => {
            const kind = r.result?.kind || r.status;
            const iconName =
              kind === "soshie_autopilot_published" ? "checkmark-circle" :
              kind === "soshie_autopilot_failed" ? "close-circle" : "time-outline";
            const iconColor =
              kind === "soshie_autopilot_published" ? colors.success :
              kind === "soshie_autopilot_failed" ? colors.error : colors.muted;
            return (
              <View key={r.id} style={s.feedRow} testID={`autopilot-action-${r.id}`}>
                <Ionicons name={iconName as any} size={14} color={iconColor} />
                <View style={{ flex: 1 }}>
                  <Text style={s.feedAction}>
                    <Text style={s.feedActionBold}>{r.action}</Text>
                    {" — "}
                    <Text style={{ color: colors.muted }}>{kind}</Text>
                  </Text>
                  <Text style={s.feedTime}>
                    {r.updated_at ? new Date(r.updated_at).toLocaleString() : ""}
                  </Text>
                </View>
              </View>
            );
          })}
        </View>
      )}
    </Card>
  );
}

/* ── Main tab ─────────────────────────────────────────────────── */
export default function AutopilotTab({ disabled }: { disabled?: boolean }) {
  return (
    <View testID="autopilot-schedules">
      <GlobalKillSwitch disabled={disabled} />

      {/* Platform grid now lives at /settings/social (PlatformGrid.tsx).
          A link nudges admins to the consolidated surface. */}
      <Card style={[s.card, { marginTop: spacing.md }]}>
        <View style={s.platformHeader}>
          <View>
            <Text style={s.platformHeaderTitle}>Platform cadences</Text>
            <Text style={s.platformHeaderSub}>
              Manage connections + cadence on the Settings → Social tab.
            </Text>
          </View>
          <Ionicons name="open-outline" size={16} color={colors.muted} />
        </View>
      </Card>

      <View style={{ marginTop: spacing.md }}>
        <RecentActionsFeed />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  card: { marginBottom: 0 },
  skeleton: {
    backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.md,
    marginBottom: spacing.sm,
  },
  skeletonWrap: { gap: spacing.sm },
  chip: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
    alignSelf: "flex-start",
  },
  chipText: {
    fontFamily: font.semibold,
    fontSize: 11,
  },
  killRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  killTitleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  killTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  killSub: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
    marginTop: 3,
  },
  platformHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.md,
  },
  platformHeaderTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  platformHeaderSub: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
    marginTop: 2,
  },
  feedTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  feedEmpty: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  feedRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  feedAction: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  feedActionBold: { fontFamily: font.medium },
  feedTime: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 1,
  },
});
