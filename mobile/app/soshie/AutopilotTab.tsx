/**
 * Phase S2 · Autopilot Schedules tab — global kill switch + 8-platform grid + recent actions.
 * Mirrors frontend/src/pages/soshie/AutopilotSchedulesTab.jsx
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, Switch, Alert,
  TextInput,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { Card } from "@/src/components/ui";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

const PLATFORM_LABELS: Record<string, string> = {
  gbp: "Google Business Profile",
  wordpress: "WordPress",
  facebook: "Facebook",
  instagram: "Instagram",
  linkedin: "LinkedIn",
  youtube: "YouTube",
  tiktok: "TikTok",
  reddit: "Reddit",
};

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

/* ── Status badge ─────────────────────────────────────────────── */
function StatusBadge({ status, isReddit }: { status: any; isReddit: boolean }) {
  if (isReddit) {
    return <Chip label="Manual Only" tone="warning" testID="platform-badge-manual" />;
  }
  if (status?.ok) {
    return <Chip label="Connected" tone="success" testID="platform-badge-connected" />;
  }
  const detail = status?.detail || "";
  if (detail.includes("Pending operator setup") || detail.includes("Coming Soon")) {
    return <Chip label="Coming Soon" tone="neutral" testID="platform-badge-coming-soon" />;
  }
  return <Chip label="Not Connected" tone="neutral" testID="platform-badge-not-connected" />;
}

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

/* ── Platform Row ─────────────────────────────────────────────── */
function PlatformRow({
  cfg, status, onPatch, disabled,
}: {
  cfg: any; status: any; onPatch: (next: any) => void; disabled?: boolean;
}) {
  const platform: string = cfg.platform;
  const isReddit = platform === "reddit";
  const isDaily = platform === "gbp";
  const [busy, setBusy] = useState(false);

  const cadenceKey = isDaily ? "posts_per_day" : "posts_per_week";
  const cadenceVal = cfg[cadenceKey] ?? 0;

  const patch = async (delta: any, revertKey: string, revertVal: any) => {
    setBusy(true);
    try {
      const next = await api.patch(`/soshie/autopilot/config/${platform}`, delta);
      onPatch(next);
    } catch (e: any) {
      onPatch({ ...cfg, [revertKey]: revertVal }); // revert
      Alert.alert("Failed", e?.message || `Could not update ${platform}`);
    } finally {
      setBusy(false);
    }
  };

  const toggleEnabled = () => {
    if (isReddit || disabled) return; // hard-blocked
    const prev = cfg.enabled;
    onPatch({ ...cfg, enabled: !prev }); // optimistic
    patch({ enabled: !prev }, "enabled", prev);
  };

  const onCadenceChange = (text: string) => {
    const n = text === "" ? 0 : Math.max(0, Math.min(10, parseInt(text, 10) || 0));
    const prev = cadenceVal;
    onPatch({ ...cfg, [cadenceKey]: n }); // optimistic
    patch({ [cadenceKey]: n }, cadenceKey, prev);
  };

  return (
    <View style={s.platformRow} testID={`platform-row-${platform}`}>
      <View style={s.platformLeft}>
        <View style={s.platformNameRow}>
          <Text style={s.platformName} testID={`platform-name-${platform}`}>
            {PLATFORM_LABELS[platform] || platform}
          </Text>
          <StatusBadge status={status} isReddit={isReddit} />
        </View>
        <Text style={s.platformTz} testID={`platform-timezone-${platform}`}>
          {cfg.timezone || "America/Phoenix"}
        </Text>
      </View>

      <View style={s.platformRight}>
        <View style={s.cadenceWrap}>
          <Text style={s.cadenceLabel}>{isDaily ? "per day" : "per week"}</Text>
          <TextInput
            style={[s.cadenceInput, (isReddit || disabled) && s.inputDisabled]}
            keyboardType="number-pad"
            value={String(cadenceVal)}
            onEndEditing={(e) => onCadenceChange(e.nativeEvent.text)}
            editable={!isReddit && !disabled && !busy}
            testID={`platform-cadence-${platform}`}
            accessibilityLabel="Cadence"
          />
        </View>
        <Switch
          value={!!cfg.enabled}
          onValueChange={toggleEnabled}
          disabled={isReddit || disabled || busy}
          trackColor={{ false: "#94a3b8", true: colors.brand }}
          style={isReddit ? { opacity: 0.5 } : undefined}
          testID={`platform-toggle-${platform}`}
          accessibilityRole="switch"
          accessibilityLabel={`Toggle ${platform} autopilot`}
          accessibilityState={{ disabled: isReddit || disabled }}
        />
      </View>
    </View>
  );
}

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
  const [configs, setConfigs] = useState<any[]>([]);
  const [platforms, setPlatforms] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [cfg, plat] = await Promise.all([
        api.get("/soshie/autopilot/config"),
        api.get("/soshie/platforms"),
      ]);
      setConfigs((cfg as any)?.items || []);
      const byName: Record<string, any> = {};
      for (const p of ((plat as any)?.platforms || [])) {
        byName[p.platform] = p;
      }
      setPlatforms(byName);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Couldn't load autopilot schedules");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!disabled) load();
  }, [load, disabled]);

  const patchRow = (next: any) => {
    setConfigs((rows) =>
      rows.map((r) => (r.platform === next.platform ? { ...r, ...next } : r)),
    );
  };

  return (
    <View testID="autopilot-schedules">
      <GlobalKillSwitch disabled={disabled} />

      <Card style={[s.card, { marginTop: spacing.md }]}>
        <View style={s.platformHeader}>
          <View>
            <Text style={s.platformHeaderTitle}>Platforms</Text>
            <Text style={s.platformHeaderSub}>
              Per-platform cadence + connection status.
            </Text>
          </View>
          <Ionicons name="information-circle-outline" size={16} color={colors.muted} />
        </View>
        {loading ? (
          <View style={s.skeletonWrap} testID="autopilot-loading">
            <Skeleton />
            <Skeleton />
            <Skeleton />
          </View>
        ) : configs.length ? (
          <View style={s.platformList}>
            {configs.map((cfg) => (
              <PlatformRow
                key={cfg.platform}
                cfg={cfg}
                status={platforms[cfg.platform]}
                onPatch={patchRow}
                disabled={disabled}
              />
            ))}
          </View>
        ) : (
          <Text style={s.feedEmpty} testID="autopilot-empty">
            {"No autopilot config yet — refreshing…"}
          </Text>
        )}
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
  platformList: { gap: spacing.sm },
  platformRow: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.md,
  },
  platformLeft: { flex: 1 },
  platformNameRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  platformName: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  platformTz: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    marginTop: 2,
  },
  platformRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  cadenceWrap: {
    alignItems: "center",
    gap: 2,
  },
  cadenceLabel: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
  },
  cadenceInput: {
    width: 48,
    height: 32,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    textAlign: "center",
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    paddingHorizontal: 4,
  },
  inputDisabled: { opacity: 0.4 },
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
