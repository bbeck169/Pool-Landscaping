import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  Image,
  Pressable,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { StatusChip } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { BODY_TYPE_LABELS, BODY_TYPE_TINTS, READING_LABELS } from "@/src/lib/waterBodies";
import { expandChemistryLabel } from "@/src/lib/expandChemistryLabel";
import { formatCompletedAt } from "@/src/lib/dateTimeFormat";
import { ClickableAddress } from "@/src/components/interactive";
import { portalJobPhotoRaw, resolvePortalMediaUri, usePortalAuthToken } from "@/src/lib/portalMediaUri";
import PortalPageShell, { PORTAL_PAGE_BG } from "@/src/components/portal/PortalPageShell";
import { resolveServiceType } from "@/src/lib/portalServiceType";

/* ── helpers ──────────────────────────────── */

// Phase K22 — fmtDate replaced by formatCompletedAt from @/src/lib/dateTimeFormat.

// TD-69 — shared landscape-priority resolver (web b86ecb289).
const reportKind = resolveServiceType;

const KIND_META = {
  pool: { label: "Pool service", bg: "#E0F2FE", fg: "#0369A1", icon: "water-outline" as const },
  landscape: { label: "Landscape service", bg: "#DCFCE7", fg: "#166534", icon: "leaf-outline" as const },
  generic: { label: "Service", bg: colors.surfaceTertiary, fg: colors.onSurfaceSecondary, icon: "clipboard-outline" as const },
};

const CHEM_BAND: Record<string, { bg: string; fg: string; label: string }> = {
  below: { bg: "#DBEAFE", fg: "#1E3A8A", label: "Below" },
  average: { bg: "#DCFCE7", fg: "#166534", label: "Average" },
  above: { bg: "#FEF3C7", fg: "#92400E", label: "Above Avg" },
  elevated: { bg: "#FEE2E2", fg: "#991B1B", label: "Elevated" },
};

function algaeLine(sr: any) {
  const level = String(sr?.observations?.visible_algae || "").toLowerCase();
  if (level === "heavy") return "Visible algae observed and treated during this visit.";
  if (level === "light") return "Light algae was observed and treated during this visit.";
  return null;
}

/* ── skeleton ─────────────────────────────── */

function Skeleton() {
  return (
    <View style={s.skeletonWrap} testID="service-report-detail-skeleton">
      <View style={[s.skeletonBar, { width: "100%", height: 120 }]} />
      <View style={[s.skeletonBar, { width: "70%", height: 16, marginTop: 16 }]} />
      <View style={[s.skeletonBar, { width: "50%", height: 14, marginTop: 8 }]} />
    </View>
  );
}

/* ── Section wrapper ──────────────────────── */

function Section({
  icon,
  title,
  testID,
  children,
}: {
  icon: any;
  title: string;
  testID: string;
  children: React.ReactNode;
}) {
  return (
    <View style={s.section} testID={testID}>
      <View style={s.sectionHeader}>
        <Ionicons name={icon} size={16} color={colors.brand} />
        <Text style={s.sectionTitle}>{title}</Text>
      </View>
      {children}
    </View>
  );
}

/* ── main component ───────────────────────── */

export default function PortalServiceReportDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const [sr, setSr] = useState<any>(null);
  const [err, setErr] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const token = usePortalAuthToken();

  const load = useCallback(async () => {
    try {
      setSr(null);
      setErr("");
      const data = await api.get(`/customers/me/service-reports/${id}`);
      setSr(data);
    } catch (e: any) {
      setErr(e?.message || "This service report is not available.");
    } finally {
      setRefreshing(false);
    }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (err) {
    return (
      <View style={s.root}>
        <Header title="Service Report" back />
        <View style={s.errorCard} testID="portal-service-report-error">
          <Text style={s.errorText}>{err}</Text>
        </View>
      </View>
    );
  }

  if (!sr) {
    return (
      <View style={s.root}>
        <Header title="Service Report" back />
        <Skeleton />
      </View>
    );
  }

  const kind = reportKind(sr);
  const km = KIND_META[kind];
  const readings = Array.isArray(sr.chemical_readings)
    ? sr.chemical_readings.filter(
        (r: any) => r && (r.label || (r.value !== null && r.value !== undefined && r.value !== ""))
      )
    : [];
  const chemicalsAdded = Array.isArray(sr.chemicals_added)
    ? sr.chemicals_added.filter((c: any) => c && (c.name || c.chemical))
    : [];
  const checklistItems = Array.isArray(sr.checklist_items) ? sr.checklist_items : [];
  const photos = Array.isArray(sr.photos) ? sr.photos : [];
  const jobPhotos = Array.isArray(sr.job_photos) ? sr.job_photos : [];
  const algae = algaeLine(sr);

  return (
    <View style={s.root}>
      <Header title="Service Report" back />
      <ScrollView
        testID="portal-service-report-detail"
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />
        }
      >
        {/* TD-68 — web PortalPageShell: white card on navy page */}
        <PortalPageShell>
        {/* Header Card */}
        <View style={s.headerCard}>
          <View style={s.headerRow}>
            <View style={[s.kindIcon, { backgroundColor: km.bg }]}>
              <Ionicons name={km.icon} size={22} color={km.fg} />
            </View>
            <View style={{ flex: 1 }}>
              <View style={s.chipRow}>
                <View style={[s.kindChip, { backgroundColor: km.bg }]}>
                  <Text style={[s.kindChipText, { color: km.fg }]}>{km.label}</Text>
                </View>
                <StatusChip status="completed" />
              </View>
              <Text style={s.detailTitle} testID="portal-service-report-title">
                {sr?.job?.title || "Service visit"}
              </Text>
              <View style={s.metaWrap}>
                <View style={s.metaItem} testID="portal-service-report-visit-date">
                  <Ionicons name="calendar-outline" size={12} color={colors.muted} />
                  <Text style={s.metaText}>
                    {formatCompletedAt(sr.submitted_at || sr?.job?.scheduled_start)}
                  </Text>
                </View>
                {sr.tech_name ? (
                  <View style={s.metaItem} testID="portal-service-report-tech">
                    <Ionicons name="person-outline" size={12} color={colors.muted} />
                    <Text style={s.metaText}>{sr.tech_name}</Text>
                  </View>
                ) : null}
                {sr?.job?.address ? (
                  <View style={s.metaItem} testID="portal-service-report-address">
                    <Ionicons name="location-outline" size={12} color={colors.muted} />
                    <ClickableAddress address={sr.job.address} style={s.metaText} testID="portal-service-report-address-link" />
                  </View>
                ) : null}
              </View>
            </View>
          </View>
        </View>

        {/* Algae observation (pool only) */}
        {kind === "pool" && algae ? (
          <View style={s.algaeBanner} testID="portal-service-report-algae">
            <Ionicons name="alert-circle-outline" size={16} color="#854D0E" />
            <Text style={s.algaeText}>{algae}</Text>
          </View>
        ) : null}

        {/* Water chemistry readings */}
        {/* Phase v · Multi-body display when water_bodies[] present */}
        {/* TD-69 — chemistry (incl. multi-body) only for pool reports. */}
        {kind === "pool" && Array.isArray(sr.water_bodies) && sr.water_bodies.length > 1 ? (
          <Section icon="layers-outline" title={`Water Bodies (${sr.water_bodies.length})`} testID="portal-water-bodies-section">
            {sr.water_bodies.map((wb: any, wbi: number) => {
              const tint = BODY_TYPE_TINTS[wb.type] || BODY_TYPE_TINTS.pool;
              const wbReadings = (wb.readings || []).filter(
                (r: any) => r && r.value !== null && r.value !== undefined && r.value !== "",
              );
              return (
                <View key={wb.id || wbi} style={[s.wbCard, { borderColor: tint.border }]} testID={`portal-water-body-${wbi}`}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 }}>
                    <View style={[s.wbBadge, { backgroundColor: tint.bg }]}>
                      <Text style={[s.wbBadgeText, { color: tint.fg }]}>{BODY_TYPE_LABELS[wb.type] || wb.type}</Text>
                    </View>
                    {wb.label ? <Text style={s.wbLabel}>{wb.label}</Text> : null}
                  </View>
                  {wbReadings.length > 0 ? (
                    <View style={s.readingsGrid}>
                      {wbReadings.map((r: any, ri: number) => {
                        const meta = READING_LABELS[r.key] || {};
                        const band = r.label || "average";
                        const bs = CHEM_BAND[band] || CHEM_BAND.average;
                        return (
                          <View key={r.key || ri} style={s.readingCard}>
                            <View style={{ flex: 1 }}>
                              <Text style={s.readingLabel}>{expandChemistryLabel((meta as any).name || r.name || r.key)}</Text>
                            </View>
                            <View style={[s.bandChip, { backgroundColor: bs.bg }]}>
                              <Text style={[s.bandChipText, { color: bs.fg }]}>{bs.label}</Text>
                            </View>
                          </View>
                        );
                      })}
                    </View>
                  ) : <Text style={s.emptyText}>No readings recorded</Text>}
                  {wb.notes ? <Text style={s.wbNotes}>{wb.notes}</Text> : null}
                </View>
              );
            })}
          </Section>
        ) : null}
        {/* Legacy single-body readings */}
        {kind === "pool" && readings.length > 0 && !(Array.isArray(sr.water_bodies) && sr.water_bodies.length > 1) ? (
          <Section icon="water-outline" title="Water Chemistry" testID="portal-service-report-readings">
            <View style={s.readingsGrid} testID="portal-service-report-readings-list">
              {readings.map((r: any, i: number) => {
                const band = r.label || sr?.readings_label?.[r.key] || "average";
                const bs = CHEM_BAND[band] || CHEM_BAND.average;
                return (
                  <View
                    key={r.key || r.name || i}
                    style={s.readingCard}
                    testID={`portal-service-report-reading-${r.key || i}`}
                  >
                    <View style={{ flex: 1 }}>
                      <Text style={s.readingLabel}>{expandChemistryLabel(r.name || r.key)}</Text>
                      {r.unit ? <Text style={s.readingUnit}>{r.unit}</Text> : null}
                    </View>
                    <View style={[s.bandChip, { backgroundColor: bs.bg }]}>
                      <Text style={[s.bandChipText, { color: bs.fg }]}>{bs.label}</Text>
                    </View>
                  </View>
                );
              })}
            </View>
          </Section>
        ) : null}

        {/* Chemicals added */}
        {kind === "pool" && chemicalsAdded.length > 0 ? (
          <Section icon="flask-outline" title="Chemicals Added" testID="portal-service-report-chemicals">
            {chemicalsAdded.map((c: any, i: number) => {
              const name = c.name || c.chemical || "Chemical";
              const amount = c.amount ?? c.qty ?? c.quantity ?? "";
              const unit = c.unit || c.default_unit || "";
              return (
                <View key={i} style={s.chemRow} testID={`portal-service-report-chemical-${i}`}>
                  <Text style={s.chemName}>{name}</Text>
                  <Text style={s.chemAmount}>
                    {amount} {unit}
                  </Text>
                </View>
              );
            })}
          </Section>
        ) : null}

        {/* Checklist */}
        {checklistItems.length > 0 ? (
          <Section
            icon="checkbox-outline"
            title={kind === "landscape" ? "Landscape Checklist" : "Service Checklist"}
            testID="portal-service-report-checklist"
          >
            {checklistItems.map((it: any, i: number) => {
              const checked = !!it.checked;
              return (
                <View
                  key={it.id || i}
                  style={s.checkItem}
                  testID={`portal-service-report-checklist-item-${i}`}
                >
                  <View
                    style={[
                      s.checkBox,
                      {
                        backgroundColor: checked ? colors.success + "22" : colors.surfaceTertiary,
                        borderColor: checked ? colors.success : colors.border,
                      },
                    ]}
                  >
                    {checked ? <Ionicons name="checkmark" size={13} color={colors.success} /> : null}
                  </View>
                  <Text
                    style={[
                      s.checkLabel,
                      { color: checked ? colors.onSurface : colors.muted },
                    ]}
                  >
                    {it.label}
                  </Text>
                </View>
              );
            })}
          </Section>
        ) : null}

        {/* Customer notes */}
        {(sr.customer_notes || "").trim() ? (
          <Section icon="document-text-outline" title="Notes from Your Tech" testID="portal-service-report-customer-notes">
            <Text style={s.notesText}>{sr.customer_notes}</Text>
          </Section>
        ) : null}

        {/* TD-67 / TD-76 Phase A — tech-attached job photos (web
            "Job Photos" section). Canonical thumb_url / full_url
            from BE; `?auth=` stamped for the customer streaming route. */}
        {jobPhotos.length > 0 ? (
          <Section icon="camera-outline" title="Job Photos" testID="portal-service-report-job-photos">
            <View style={s.photoGrid}>
              {jobPhotos.map((p: any, i: number) => {
                const src = resolvePortalMediaUri(portalJobPhotoRaw(p), token);
                if (!src) return null;
                return (
                  <Image
                    key={p.id || i}
                    source={{ uri: src }}
                    style={s.photo}
                    testID={`portal-service-report-job-photo-${i}`}
                  />
                );
              })}
            </View>
          </Section>
        ) : null}

        {/* Visit photos */}
        {photos.length > 0 ? (
          <Section icon="images-outline" title="Visit Photos" testID="portal-service-report-photos">
            <View style={s.photoGrid}>
              {photos.map((p: any, i: number) => {
                const raw =
                  typeof p === "string"
                    ? p
                    : p.url || p.data_url || p.data || p.thumb_url || "";
                // TD-67 — BE emits relative /api/public/... paths here;
                // RN <Image> needs an absolute URI.
                const src = resolvePortalMediaUri(raw, token);
                if (!src) return null;
                return (
                  <Image
                    key={p.id || i}
                    source={{ uri: src }}
                    style={s.photo}
                    testID={`portal-service-report-photo-${i}`}
                  />
                );
              })}
            </View>
          </Section>
        ) : null}
        </PortalPageShell>
      </ScrollView>
    </View>
  );
}

/* ── styles ───────────────────────────────── */

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: PORTAL_PAGE_BG },

  /* Header card */
  headerCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  headerRow: { flexDirection: "row", alignItems: "flex-start", gap: spacing.md },
  kindIcon: {
    width: 48,
    height: 48,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  chipRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" },
  kindChip: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill },
  kindChipText: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase" },
  detailTitle: {
    fontFamily: font.bold,
    fontSize: fontSize["2xl"],
    color: colors.onSurface,
    marginTop: spacing.sm,
  },
  metaWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: spacing.xs },
  metaItem: { flexDirection: "row", alignItems: "center", gap: 4 },
  metaText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },

  /* Algae banner */
  algaeBanner: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.sm,
    padding: spacing.md,
    borderRadius: radius.lg,
    backgroundColor: "#FEF9C3",
    borderWidth: 1,
    borderColor: "#FDE68A",
    marginBottom: spacing.md,
  },
  algaeText: { fontFamily: font.medium, fontSize: fontSize.sm, color: "#854D0E", flex: 1 },

  /* Sections */
  section: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  sectionHeader: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.md },
  sectionTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },

  /* Readings */
  readingsGrid: { gap: spacing.sm },
  readingCard: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  readingLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  readingUnit: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  bandChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  bandChipText: { fontFamily: font.bold, fontSize: fontSize.sm },

  /* Chemicals */
  chemRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  chemName: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  chemAmount: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },

  /* Checklist */
  checkItem: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 6 },
  checkBox: {
    width: 22,
    height: 22,
    borderRadius: 6,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
  },
  checkLabel: { fontFamily: font.regular, fontSize: fontSize.base, flex: 1 },

  /* Notes */
  notesText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },

  /* Photos */
  photoGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  photo: {
    width: "48%",
    aspectRatio: 1,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },

  /* Skeleton */
  skeletonWrap: { padding: spacing.lg },
  skeletonBar: { borderRadius: radius.sm, backgroundColor: colors.surfaceTertiary },

  /* Error */
  errorCard: {
    margin: spacing.lg,
    padding: spacing.xl,
    borderRadius: radius.lg,
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  errorText: { fontFamily: font.medium, fontSize: fontSize.base, color: "#991B1B" },

  /* Phase v · Multi-body water bodies */
  wbCard: {
    borderWidth: 1.5,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
    backgroundColor: colors.surface,
  },
  wbBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.sm,
  },
  wbBadgeText: {
    fontFamily: font.bold,
    fontSize: 10,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  wbLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  wbNotes: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: spacing.xs,
    fontStyle: "italic",
  },
  emptyText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
});
