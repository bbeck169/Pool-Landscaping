/**
 * Service Log Detail — admin-only view for a completed job.
 * GET /api/jobs/{jid}/service-log
 *
 * Sections:
 *  1. Log Details (customer, property, checklist, previous service, email door hanger)
 *  2. Water Test Results (pool only)
 *  3. Chemicals Used (pool only) OR Service Notes (landscape)
 *  4. Service Images carousel
 */
import React, { useCallback, useEffect, useState, useRef } from "react";
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity,
  ActivityIndicator, Alert, FlatList, Dimensions, Platform,
} from "react-native";
import { Image } from "expo-image";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useLocalSearchParams, useRouter } from "expo-router";

import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/ToastProvider";
import { getServiceLog, emailDoorHanger, type ServiceLogData } from "@/src/api/serviceLog";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { formatCompletedAt } from "@/src/lib/dateTimeFormat";

const { width: SCREEN_W } = Dimensions.get("window");
const SLIDE_W = SCREEN_W - spacing.lg * 2;

function fmtAddr(prop: ServiceLogData["property"]): string {
  if (!prop?.address) return prop?.label || "—";
  const a = prop.address;
  return [a.line1, a.line2, [a.city, a.state].filter(Boolean).join(", "), a.postal_code].filter(Boolean).join(", ");
}

// Phase K22 — fmtDate replaced by formatCompletedAt from @/src/lib/dateTimeFormat.

export default function ServiceLogScreen() {
  const { showToast } = useToast();
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { user } = useAuth();

  const [data, setData] = useState<ServiceLogData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [doorBusy, setDoorBusy] = useState(false);
  const [slideIdx, setSlideIdx] = useState(0);
  const flatRef = useRef<FlatList>(null);

  // Role gate — admin + super_admin only
  const role = (user as any)?.role || "";
  const allowed = role === "admin" || role === "super_admin";

  const load = useCallback(async () => {
    if (!id || !allowed) return;
    setLoading(true);
    setError("");
    try {
      setData(await getServiceLog(id));
    } catch (e: any) {
      setError(e?.message || "Failed to load service log");
    } finally {
      setLoading(false);
    }
  }, [id, allowed]);

  useEffect(() => { load(); }, [load]);

  const onEmailDoor = async () => {
    if (!id) return;
    setDoorBusy(true);
    try {
      await emailDoorHanger(id);
      showToast(`Door hanger emailed to ${data?.log_details?.customer_email || "customer"}.`);
    } catch (e: any) {
      const status = e?.response?.status || e?.status;
      if (status === 429) {
        showToast("Just sent — try again in a moment.", "error");
      } else {
        showToast(e?.message || "Failed to send door hanger.", "error");
      }
    } finally {
      setDoorBusy(false);
    }
  };

  const scrollSlide = (dir: -1 | 1) => {
    const next = Math.max(0, Math.min(slideIdx + dir, (data?.service_images?.length || 1) - 1));
    flatRef.current?.scrollToIndex({ index: next, animated: true });
    setSlideIdx(next);
  };

  // Role gate UI
  if (!allowed) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]} testID="service-log-role-gate">
        <Ionicons name="lock-closed" size={36} color={colors.muted} />
        <Text style={s.gateText}>Not authorized</Text>
        <Text style={s.gateSubtext}>Workstream is available to admins only.</Text>
        <TouchableOpacity onPress={() => router.replace("/(app)")} style={s.gateBtn} testID="service-log-go-home">
          <Text style={s.gateBtnText}>Go Home</Text>
        </TouchableOpacity>
      </View>
    );
  }

  if (loading) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]}>
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  if (error || !data) {
    return (
      <View style={[s.center, { paddingTop: insets.top + 60 }]}>
        <Ionicons name="alert-circle" size={32} color={colors.error} />
        <Text style={s.errorText}>{error || "Service log not found"}</Text>
        <TouchableOpacity onPress={() => router.back()} style={s.gateBtn}>
          <Text style={s.gateBtnText}>Go Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const isPool = data.service_line === "pool";
  const images = data.service_images || [];

  return (
    <View style={[s.root, { paddingTop: insets.top }]}>
      {/* Nav bar */}
      <View style={s.navBar}>
        <TouchableOpacity onPress={() => router.back()} hitSlop={12} testID="service-log-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </TouchableOpacity>
        <Text style={s.navTitle}>Service Log</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={s.scroll} showsVerticalScrollIndicator={false}>
        {/* ─── Section 1: Log Details ─── */}
        <View style={s.card} testID="service-log-details-card">
          <Text style={s.sectionLabel}>LOG DETAILS</Text>

          {/* Customer → Property */}
          <View style={s.detailRow}>
            <Ionicons name="person" size={16} color={colors.brand} />
            <Text style={s.detailValue}>{formatCustomerName(data.log_details)}</Text>
          </View>
          <View style={[s.detailRow, { marginLeft: 16 }]}>
            <Ionicons name="arrow-forward" size={12} color={colors.muted} />
            <Text style={s.detailMuted}>{fmtAddr(data.property) || data.log_details.property_address}</Text>
          </View>

          {/* Service date/time */}
          <View style={s.detailRow}>
            <Ionicons name="calendar" size={16} color={colors.brand} />
            <Text style={s.detailValue}>{formatCompletedAt(data.log_details.service_at)}</Text>
          </View>

          {/* Time spent */}
          {data.log_details.time_spent_minutes != null && (
            <View style={s.detailRow}>
              <Ionicons name="time" size={16} color={colors.brand} />
              <Text style={s.detailValue}>Time spent: {data.log_details.time_spent_minutes} min</Text>
            </View>
          )}

          {/* Employee */}
          <View style={s.employeeRow}>
            <View style={s.empAvatar}>
              <Text style={s.empInit}>{(data.employee.name || "?")[0]?.toUpperCase()}</Text>
            </View>
            <View>
              <Text style={s.empName}>{data.employee.name}</Text>
              {data.employee.department ? <Text style={s.empDept}>{data.employee.department}</Text> : null}
            </View>
          </View>

          {/* Checklist */}
          <View style={s.checklistWrap} testID="service-log-checklist">
            <Text style={s.subLabel}>Checklist</Text>
            {data.checklist_state.items.map((it) => (
              <View key={it.key} style={s.checkRow} testID={`sl-check-${it.key}`}>
                <Ionicons
                  name={it.completed ? "checkmark-circle" : "ellipse-outline"}
                  size={18}
                  color={it.completed ? colors.brand : colors.muted}
                />
                <Text style={[s.checkLabel, it.completed && s.checkLabelDone]}>{it.label}</Text>
              </View>
            ))}
          </View>

          {/* Previous service */}
          {data.previous_service.length > 0 && (
            <View style={s.prevWrap} testID="service-log-previous">
              <Text style={s.subLabel}>Previous Service</Text>
              {data.previous_service.map((ps) => (
                <View key={ps.job_id} style={s.prevRow}>
                  <Text style={s.prevDate}>{formatCompletedAt(ps.completed_at)}</Text>
                  <TouchableOpacity
                    style={s.viewPill}
                    onPress={() => router.push(`/workstream/${ps.job_id}`)}
                    testID={`sl-prev-${ps.job_id}`}
                  >
                    <Text style={s.viewPillText}>VIEW</Text>
                  </TouchableOpacity>
                </View>
              ))}
            </View>
          )}

          {/* Email door hanger button */}
          <TouchableOpacity
            style={s.doorBtn}
            onPress={onEmailDoor}
            disabled={doorBusy}
            testID="service-log-email-door-hanger"
          >
            {doorBusy ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="mail" size={18} color="#fff" />
                <Text style={s.doorBtnText}>EMAIL DOOR HANGER</Text>
              </>
            )}
          </TouchableOpacity>
        </View>

        {/* ─── Section 2: Water Test (pool only) ─── */}
        {isPool && (
          <View style={s.card} testID="service-log-water-test">
            <Text style={s.sectionLabel}>WATER TEST RESULTS</Text>
            {(data.water_test || []).length === 0 ? (
              <Text style={s.emptyHint}>No water test recorded</Text>
            ) : (
              data.water_test.map((wt, i) => (
                <View key={i} style={s.wtRow}>
                  <Text style={s.wtLabel}>{wt.label}</Text>
                  <Text style={s.wtValue}>{wt.value ?? "—"}{wt.unit ? ` ${wt.unit}` : ""}</Text>
                </View>
              ))
            )}
          </View>
        )}

        {/* ─── Section 3: Chemicals (pool) or Service Notes (landscape) ─── */}
        {isPool ? (
          <View style={s.card} testID="service-log-chemicals">
            <View style={s.chemHeader}>
              <Text style={s.sectionLabel}>CHEMICALS USED</Text>
              {data.chemical_cost_usd > 0 && (
                <View style={s.costPill} testID="service-log-chem-cost">
                  <Text style={s.costPillText}>Chemical Cost ${data.chemical_cost_usd.toFixed(2)}</Text>
                </View>
              )}
            </View>
            {(data.chemicals_used || []).length === 0 ? (
              <Text style={s.emptyHint}>No chemicals recorded</Text>
            ) : (
              data.chemicals_used.map((ch, i) => (
                <View key={i} style={s.chemRow}>
                  <Text style={s.chemName}>{ch.name}</Text>
                  <Text style={s.chemAmt}>{ch.amount}{ch.unit ? ` ${ch.unit}` : ""}</Text>
                </View>
              ))
            )}
          </View>
        ) : (
          <View style={s.card} testID="service-log-landscape-notes">
            <Text style={s.sectionLabel}>SERVICE NOTES</Text>
            <Text style={s.notesText}>{data.service_notes || "No notes recorded."}</Text>
            {(data.materials_used || []).length > 0 && (
              <>
                <Text style={[s.subLabel, { marginTop: spacing.md }]}>Materials Used</Text>
                {data.materials_used!.map((m, i) => (
                  <View key={i} style={s.chemRow}>
                    <Text style={s.chemName}>{m.name}</Text>
                    <Text style={s.chemAmt}>{m.quantity || ""}{m.unit ? ` ${m.unit}` : ""}</Text>
                  </View>
                ))}
              </>
            )}
          </View>
        )}

        {/* ─── Section 4: Service Images carousel ─── */}
        <View style={s.card} testID="service-log-images">
          <Text style={s.sectionLabel}>SERVICE IMAGES</Text>
          {images.length === 0 ? (
            <View style={s.emptyImageWrap}>
              <Ionicons name="images-outline" size={28} color={colors.muted} />
              <Text style={s.emptyHint}>No service images uploaded</Text>
            </View>
          ) : (
            <>
              <View style={s.carouselWrap}>
                {/* Left chevron */}
                {slideIdx > 0 && (
                  <TouchableOpacity style={[s.chevron, s.chevronL]} onPress={() => scrollSlide(-1)} testID="sl-img-prev">
                    <Ionicons name="chevron-back" size={22} color="#fff" />
                  </TouchableOpacity>
                )}
                <FlatList
                  ref={flatRef}
                  data={images}
                  horizontal
                  pagingEnabled
                  showsHorizontalScrollIndicator={false}
                  keyExtractor={(_, i) => String(i)}
                  onMomentumScrollEnd={(e) => {
                    const idx = Math.round(e.nativeEvent.contentOffset.x / SLIDE_W);
                    setSlideIdx(idx);
                  }}
                  renderItem={({ item }) => (
                    <View style={[s.slide, { width: SLIDE_W }]}>
                      {item.kind === "video" ? (
                        <View style={s.videoThumb}>
                          <Ionicons name="play-circle" size={48} color="rgba(255,255,255,0.9)" />
                          <Text style={s.videoLabel}>Video</Text>
                        </View>
                      ) : (
                        <Image source={{ uri: item.url }} style={s.slideImg} contentFit="cover" />
                      )}
                      {item.kind === "video" && (
                        <View style={s.playBadge}>
                          <Ionicons name="videocam" size={12} color="#fff" />
                        </View>
                      )}
                    </View>
                  )}
                />
                {/* Right chevron */}
                {slideIdx < images.length - 1 && (
                  <TouchableOpacity style={[s.chevron, s.chevronR]} onPress={() => scrollSlide(1)} testID="sl-img-next">
                    <Ionicons name="chevron-forward" size={22} color="#fff" />
                  </TouchableOpacity>
                )}
              </View>
              {/* Dots */}
              <View style={s.dots}>
                {images.map((_, i) => (
                  <View key={i} style={[s.dot, i === slideIdx && s.dotActive]} />
                ))}
              </View>
            </>
          )}
        </View>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F8FAFC" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: colors.surface, padding: 24 },
  gateText: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: 12 },
  gateSubtext: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 4, textAlign: "center" },
  gateBtn: { marginTop: 20, paddingHorizontal: 24, paddingVertical: 12, borderRadius: radius.md, backgroundColor: colors.brand },
  gateBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  errorText: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.error, marginTop: 8, textAlign: "center" },
  navBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.surface },
  navTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.border },
  sectionLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, textTransform: "uppercase", letterSpacing: 1, marginBottom: spacing.sm },
  subLabel: { fontFamily: font.semibold, fontSize: 11, color: colors.onSurfaceSecondary, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: spacing.xs, marginTop: spacing.md },
  detailRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 6 },
  detailValue: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  detailMuted: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, flex: 1 },
  employeeRow: { flexDirection: "row", alignItems: "center", gap: 10, marginTop: spacing.sm, marginBottom: spacing.sm, paddingVertical: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  empAvatar: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  empInit: { fontFamily: font.bold, fontSize: 14, color: colors.brand },
  empName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  empDept: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  checklistWrap: { marginTop: spacing.sm },
  checkRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5 },
  checkLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  checkLabelDone: { color: colors.brand },
  prevWrap: { marginTop: spacing.sm, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  prevRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 6 },
  prevDate: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  viewPill: { paddingHorizontal: 12, paddingVertical: 4, borderRadius: 999, backgroundColor: colors.brand },
  viewPillText: { fontFamily: font.bold, fontSize: 10, color: "#fff", letterSpacing: 0.5 },
  doorBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.brand, paddingVertical: 14, borderRadius: radius.md, marginTop: spacing.lg },
  doorBtnText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#fff", letterSpacing: 0.5 },
  wtRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  wtLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  wtValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  chemHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  costPill: { backgroundColor: "#FEE2E2", paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999 },
  costPillText: { fontFamily: font.bold, fontSize: 11, color: "#B91C1C" },
  chemRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border },
  chemName: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  chemAmt: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  notesText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  emptyHint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 4 },
  emptyImageWrap: { alignItems: "center", paddingVertical: spacing.xl },
  carouselWrap: { position: "relative", borderRadius: radius.sm, overflow: "hidden" },
  slide: { height: 220, borderRadius: radius.sm, overflow: "hidden", backgroundColor: colors.surfaceTertiary },
  slideImg: { width: "100%", height: "100%" },
  videoThumb: { flex: 1, alignItems: "center", justifyContent: "center", backgroundColor: "#1E293B" },
  videoLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: "rgba(255,255,255,0.7)", marginTop: 4 },
  playBadge: { position: "absolute", top: 8, right: 8, backgroundColor: "rgba(0,0,0,0.6)", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4 },
  chevron: { position: "absolute", top: "50%", marginTop: -18, zIndex: 10, width: 36, height: 36, borderRadius: 18, backgroundColor: "rgba(0,0,0,0.4)", alignItems: "center", justifyContent: "center" },
  chevronL: { left: 8 },
  chevronR: { right: 8 },
  dots: { flexDirection: "row", justifyContent: "center", marginTop: spacing.sm, gap: 6 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.border },
  dotActive: { backgroundColor: colors.brand, width: 18 },
});
