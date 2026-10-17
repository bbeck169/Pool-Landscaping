/**
 * Optimize Route → reorder modal — mobile parity for web
 * `ReorderRouteModal.jsx` + CalendarSchedule `optimizeRoute()`
 * (2f14a7ea5 + e5d6fa01e).
 *
 *  - On open: POST /schedule/optimize-route {date, technician_id}
 *  - Header "Estimated ~Xh Ym · M.Mmi · {trivial|short|long}" — server
 *    totals while the list matches the server order; any drag / move /
 *    reverse switches to the client-side haversine recompute.
 *  - Dropped-job yellow banner (`dropped_job_ids`).
 *  - Reverse Order (secondary) immediately left of Save.
 *  - Save → POST /jobs/reorder {ordered_job_ids, tech_user_id?, date}
 *    (same endpoint + body as the calendar's Rearrange save).
 */
import React, { useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, Modal, Pressable, ActivityIndicator, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import DraggableFlatList, { ScaleDecorator, type RenderItemParams } from "react-native-draggable-flatlist";
import { useSafeAreaInsets, initialWindowMetrics } from "react-native-safe-area-context";

import { api } from "@/src/api";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";
import { formatRouteHeader, totalHaversineMeters } from "@/src/utils/routeHaversine";

type Job = { id: string; customer_name?: string; title?: string; address?: string; route_index?: number | null; [k: string]: any };
type Opt = { orderedIds: string[]; meters: number; seconds: number; dropped: string[] };

/** Rank by optimized ids; unknown ids sink to the bottom (web `_initialOrderedJobs`). */
export function seedOrder(jobs: Job[], orderedIds: string[]): Job[] {
  const rank = new Map(orderedIds.map((id, i) => [id, i]));
  return [...jobs].sort((a, b) => (rank.get(a.id) ?? 9999) - (rank.get(b.id) ?? 9999));
}

export function droppedBannerText(n: number): string | null {
  if (!n) return null;
  return `${n} job${n > 1 ? "s" : ""} skipped: no address coordinates. Visit Admin → Property Geocoding Health to fix.`;
}

export default function OptimizeRouteModal({ visible, jobs, date, technicianId, onClose, onSaved }: {
  visible: boolean; jobs: Job[]; date: string; technicianId?: string | null;
  onClose: () => void; onSaved?: () => void;
}) {
  const insets = useSafeAreaInsets();
  // The (app) shell hands tab screens top:0 (it owns the inset above the
  // fleet chip). A <Modal> is a new full-screen window, so fall back to
  // the device's real top inset to keep the title clear of the status bar.
  const modalTop = Math.max(insets.top, initialWindowMetrics?.insets.top ?? 0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [opt, setOpt] = useState<Opt | null>(null);
  const [ordered, setOrdered] = useState<Job[]>([]);
  const [matchesServer, setMatchesServer] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!visible) return;
    let alive = true;
    setLoading(true); setError(null); setOpt(null); setMatchesServer(true);
    api.post("/schedule/optimize-route", { date, technician_id: technicianId || null })
      .then((r: any) => {
        if (!alive) return;
        const o: Opt = {
          orderedIds: Array.isArray(r?.ordered_job_ids) ? r.ordered_job_ids : [],
          meters: Number(r?.total_distance_m || 0),
          seconds: Number(r?.total_duration_s || 0),
          dropped: Array.isArray(r?.dropped_job_ids) ? r.dropped_job_ids : [],
        };
        setOpt(o);
        setOrdered(seedOrder(jobs, o.orderedIds));
      })
      .catch((e: any) => alive && setError(e?.message || "Couldn't optimize the route."))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, date, technicianId]);

  const header = useMemo(() => {
    if (!opt || !ordered.length) return null;
    return matchesServer ? formatRouteHeader(opt.meters, opt.seconds) : formatRouteHeader(totalHaversineMeters(ordered));
  }, [opt, ordered, matchesServer]);

  const reorder = (next: Job[]) => { setOrdered(next); setMatchesServer(false); };
  const moveBy = (i: number, d: number) => {
    const t = i + d;
    if (t < 0 || t >= ordered.length) return;
    const next = [...ordered];
    const [m] = next.splice(i, 1);
    next.splice(t, 0, m);
    reorder(next);
  };
  const reverse = () => { if (ordered.length >= 2) reorder([...ordered].reverse()); };

  const save = async () => {
    if (!ordered.length) return;
    setSaving(true);
    try {
      const body: any = { ordered_job_ids: ordered.map((j) => j.id), date };
      if (technicianId) body.tech_user_id = technicianId;
      await api.post("/jobs/reorder", body);
      Alert.alert("Route reordered", `New order saved for ${ordered.length} jobs.`);
      onSaved?.();
      onClose();
    } catch (e: any) {
      Alert.alert("Reorder failed", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const renderItem = ({ item, drag, isActive, getIndex }: RenderItemParams<Job>) => {
    const i = getIndex() ?? 0;
    const label = item.customer_name || item.title || "Job";
    return (
      <ScaleDecorator>
        <View style={[s.row, isActive && s.rowActive]} testID={`optimize-route-row-${item.id}`}>
          <Pressable onLongPress={drag} delayLongPress={150} hitSlop={8} accessibilityLabel={`Drag ${label}`} testID={`optimize-route-handle-${item.id}`}>
            <Ionicons name="reorder-three-outline" size={22} color={colors.muted} />
          </Pressable>
          <View style={s.badge}><Text style={s.badgeText} testID={`optimize-route-badge-${item.id}`}>{i + 1}</Text></View>
          <View style={{ flex: 1 }}>
            <Text style={s.name} numberOfLines={1}>{label}</Text>
            {item.address ? <Text style={s.addr} numberOfLines={1}>{item.address}</Text> : null}
          </View>
          <Pressable onPress={() => moveBy(i, -1)} disabled={i === 0} style={[s.mv, i === 0 && s.off]} accessibilityLabel={`Move ${label} up`} testID={`optimize-route-up-${item.id}`}>
            <Ionicons name="chevron-up" size={16} color={colors.onSurface} />
          </Pressable>
          <Pressable onPress={() => moveBy(i, 1)} disabled={i === ordered.length - 1} style={[s.mv, i === ordered.length - 1 && s.off]} accessibilityLabel={`Move ${label} down`} testID={`optimize-route-down-${item.id}`}>
            <Ionicons name="chevron-down" size={16} color={colors.onSurface} />
          </Pressable>
        </View>
      </ScaleDecorator>
    );
  };

  const banner = droppedBannerText(opt?.dropped.length || 0);
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} presentationStyle="pageSheet">
      <View style={[s.root, { paddingTop: modalTop + spacing.sm, paddingBottom: insets.bottom + spacing.sm }]} testID="optimize-route-modal">
        <View style={s.top}>
          <Text style={s.title}>Optimize Route</Text>
          <Pressable onPress={onClose} hitSlop={10} testID="optimize-route-close"><Ionicons name="close" size={24} color={colors.onSurface} /></Pressable>
        </View>
        {header ? <Text style={s.header} testID="optimize-route-header">{header}</Text> : null}
        {banner ? (
          <View style={s.banner} testID="optimize-route-dropped-banner">
            <Ionicons name="warning-outline" size={16} color="#92400E" />
            <Text style={s.bannerText}>{banner}</Text>
          </View>
        ) : null}
        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} testID="optimize-route-loading" />
        ) : error ? (
          <Text style={s.err} testID="optimize-route-error">{error}</Text>
        ) : (
          <DraggableFlatList
            data={ordered}
            keyExtractor={(j) => j.id}
            onDragEnd={({ data }) => reorder(data)}
            renderItem={renderItem}
            containerStyle={{ flex: 1 }}
            testID="optimize-route-list"
          />
        )}
        <View style={s.footer}>
          <Pressable onPress={reverse} disabled={loading || ordered.length < 2} style={[s.secondary, (loading || ordered.length < 2) && s.off]} testID="optimize-route-reverse">
            <Ionicons name="swap-vertical" size={16} color={colors.onSurface} />
            <Text style={s.secondaryText}>Reverse Order</Text>
          </Pressable>
          <Pressable onPress={save} disabled={saving || loading || !ordered.length} style={[s.primary, (saving || loading || !ordered.length) && s.off]} testID="optimize-route-save">
            <Ionicons name="save-outline" size={16} color="#fff" />
            <Text style={s.primaryText}>{saving ? "Saving…" : "Save order"}</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface, paddingHorizontal: spacing.lg },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: spacing.sm },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  header: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface, marginBottom: spacing.sm },
  banner: { flexDirection: "row", gap: 6, alignItems: "flex-start", backgroundColor: "#FEF3C7", borderColor: "#FCD34D", borderWidth: 1, borderRadius: radius.sm, padding: spacing.sm, marginBottom: spacing.sm },
  bannerText: { flex: 1, fontFamily: font.medium, fontSize: 12, color: "#92400E" },
  err: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.error, marginTop: spacing.lg },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.sm, minHeight: 56, paddingHorizontal: spacing.sm, marginBottom: 6, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary },
  rowActive: { borderColor: "#059669" },
  badge: { minWidth: 26, height: 26, borderRadius: 13, backgroundColor: "#059669", alignItems: "center", justifyContent: "center", paddingHorizontal: 6 },
  badgeText: { fontFamily: font.bold, fontSize: 12, color: "#fff" },
  name: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  addr: { fontFamily: font.regular, fontSize: 12, color: colors.muted },
  mv: { width: 36, height: 36, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface },
  off: { opacity: 0.35 },
  footer: { flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm, paddingTop: spacing.sm },
  secondary: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: spacing.md, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  secondaryText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  primary: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 44, paddingHorizontal: spacing.lg, borderRadius: radius.sm, backgroundColor: "#059669" },
  primaryText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
});
