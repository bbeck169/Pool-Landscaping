import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useLocalSearchParams, useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { StatusChip } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { JobBeforeAfterPhotos } from "@/src/components/files";

function Skeleton() {
  return (
    <View style={s.skeletonWrap} testID="portal-svc-detail-skeleton">
      <View style={[s.skeletonBar, { width: "100%", height: 110 }]} />
      <View style={[s.skeletonBar, { width: "60%", height: 14, marginTop: 16 }]} />
      <View style={[s.skeletonBar, { width: "40%", height: 12, marginTop: 8 }]} />
    </View>
  );
}

export default function PortalServiceDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const [job, setJob] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.get(`/jobs/${id}`);
      setJob(data);
    } catch {
      setJob(null);
    } finally {
      setRefreshing(false);
    }
  }, [id]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!job) {
    return (
      <View style={s.root}>
        <Header title="Service Detail" back />
        <Skeleton />
      </View>
    );
  }

  const checklist = Array.isArray(job.checklist) ? job.checklist : [];
  const readings = job.chemical_readings && typeof job.chemical_readings === "object"
    ? Object.entries(job.chemical_readings)
    : [];
  const photos = Array.isArray(job.photos) ? job.photos : [];

  return (
    <View style={s.root}>
      <Header title="Service Detail" back />
      <ScrollView
        testID="portal-svc-detail"
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />
        }
      >
        {/* Header card */}
        <View style={s.card}>
          <StatusChip status={job.status} />
          <Text style={s.title}>{job.title}</Text>
          <Text style={s.meta}>
            {job.scheduled_date || "Unscheduled"} {job.technician_name ? `\u00b7 ${job.technician_name}` : ""}
          </Text>
          {job.address ? (
            <View style={s.metaRow}>
              <Ionicons name="location-outline" size={13} color={colors.muted} />
              <Text style={s.metaText}>{job.address}</Text>
            </View>
          ) : null}
        </View>

        {/* Checklist */}
        {checklist.length > 0 ? (
          <View style={s.card}>
            <Text style={s.sectionTitle}>Service Checklist</Text>
            {checklist.map((c: any, i: number) => (
              <View key={c.id || i} style={s.checkItem}>
                <Ionicons
                  name={c.done ? "checkmark-circle" : "ellipse-outline"}
                  size={18}
                  color={c.done ? colors.success : colors.muted}
                />
                <Text
                  style={[
                    s.checkLabel,
                    c.done && { color: colors.muted, textDecorationLine: "line-through" },
                  ]}
                >
                  {c.label}
                </Text>
              </View>
            ))}
          </View>
        ) : null}

        {/* Water readings */}
        {readings.length > 0 ? (
          <View style={s.card}>
            <Text style={s.sectionTitle}>Water Readings</Text>
            <View style={s.readingsWrap}>
              {readings.map(([key, val]: [string, any]) => (
                <View key={key} style={s.readingChip}>
                  <Text style={s.readingChipText}>
                    {key.toUpperCase()} \u00b7 {String(val)}
                  </Text>
                </View>
              ))}
            </View>
          </View>
        ) : null}

        {/* Photos (legacy base64) */}
        {photos.length > 0 ? (
          <View style={s.card}>
            <Text style={s.sectionTitle}>Photos</Text>
            <View style={s.photoGrid}>
              {photos.map((p: any, i: number) => {
                const src = typeof p === "string" ? p : p.url || p.data_url || p;
                return (
                  <Image
                    key={i}
                    source={{ uri: src }}
                    style={s.photo}
                    testID={`portal-svc-photo-${i}`}
                  />
                );
              })}
            </View>
          </View>
        ) : null}

        {/* F2c.2 — Before/After photos (F0 pipeline, read-only for customers) */}
        <JobBeforeAfterPhotos jobId={id!} readOnly />

        {/* Notes */}
        {job.notes ? (
          <View style={s.card}>
            <Text style={s.sectionTitle}>Notes</Text>
            <Text style={s.notesText}>{job.notes}</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize["2xl"],
    color: colors.onSurface,
    marginTop: spacing.sm,
  },
  meta: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    marginTop: 4,
  },
  metaRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  metaText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  sectionTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  checkItem: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: 4 },
  checkLabel: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, flex: 1 },
  readingsWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  readingChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.pill,
    backgroundColor: colors.brandTertiary,
  },
  readingChipText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.onBrandTertiary },
  photoGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  photo: {
    width: "31%",
    aspectRatio: 1,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  notesText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, lineHeight: 22 },
  skeletonWrap: { padding: spacing.lg },
  skeletonBar: { borderRadius: radius.sm, backgroundColor: colors.surfaceTertiary },
});
