/**
 * Phase A5 · Smart Brief Card — tech-facing job intelligence pane.
 *
 * Fetches ``GET /api/jobs/{job_id}/smart-brief`` on mount and renders:
 *   1. Customer header (name + phone link + address link)
 *   2. Special access chips (gate code, key, dog, other notes)
 *   3. Last 3 visits (accordion: date/tech/service → chemistry + notes)
 *   4. Open intelligence alerts (top 3, severity dot + title + body)
 *
 * Sections collapse gracefully when data is empty. Loading skeleton
 * shown while fetching; error banner with retry on failure. 403/404
 * silently hides the card.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, Pressable,
  StyleSheet, Clipboard,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { PhoneLink, AddressLink } from "@/src/components/customer";

/* ── Types ──────────────────────────────────────────────────────────── */

interface ChemistrySnapshot {
  salt: number | null;
  ph: number | null;
  alkalinity: number | null;
  chlorine: number | null;
  cyanuric_acid: number | null;
  hardness: number | null;
}

interface VisitNote {
  author_display_name: string;
  body: string;
  created_at: string;
}

interface Visit {
  visit_id: string;
  completed_at: string;
  tech_display_name: string;
  service_type: string;
  duration_minutes: number | null;
  chemistry_snapshot: ChemistrySnapshot;
  notes: VisitNote[];
}

interface Alert {
  alert_id: string;
  category: string;
  severity: string;
  title: string;
  body: string;
  created_at: string;
}

interface SmartBrief {
  job_id: string;
  customer_id: string;
  customer: {
    id: string;
    display_name: string;
    phone: string | null;
    address_line: string | null;
    coordinates: { lat: number; lng: number } | null;
  };
  special_access: {
    gate_code: string | null;
    key_location: string | null;
    dog_on_property: boolean;
    dog_notes: string | null;
    other_notes: string | null;
  };
  last_visits: Visit[];
  open_intelligence_alerts: Alert[];
}

/* ── Helpers ────────────────────────────────────────────────────────── */

const CHEM_LABELS: { key: keyof ChemistrySnapshot; label: string }[] = [
  { key: "ph", label: "pH" },
  { key: "chlorine", label: "Cl" },
  { key: "alkalinity", label: "Alk" },
  { key: "cyanuric_acid", label: "CYA" },
  { key: "salt", label: "Salt" },
  { key: "hardness", label: "Hard" },
];

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch { return iso; }
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: "#DC2626",
  high: "#EA580C",
  medium: "#CA8A04",
  low: "#6B7280",
};

/* ── Component ──────────────────────────────────────────────────────── */

interface Props {
  jobId: string;
  testID?: string;
}

export default function SmartBriefCard({ jobId, testID = "smart-brief" }: Props) {
  const router = useRouter();
  const [brief, setBrief] = useState<SmartBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [expandedVisit, setExpandedVisit] = useState<string | null>(null);

  const fetchBrief = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const data: SmartBrief = await api.get(`/jobs/${jobId}/smart-brief`);
      setBrief(data);
    } catch (e: any) {
      const status = e?.status ?? e?.response?.status;
      if (status === 403 || status === 404) {
        // eslint-disable-next-line no-console
        console.log(`[SmartBrief] ${status} — hiding card`, e?.message);
        setHidden(true);
      } else {
        setError(true);
      }
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => { fetchBrief(); }, [fetchBrief]);

  if (hidden) return null;

  /* ── Loading skeleton ──────────────────────────────────────────── */
  if (loading) {
    return (
      <View style={s.card} testID={`${testID}-loading`}>
        <View style={s.skeletonRow}>
          <View style={s.skeletonCircle} />
          <View style={{ flex: 1, gap: 6 }}>
            <View style={[s.skeletonBar, { width: "60%" }]} />
            <View style={[s.skeletonBar, { width: "40%" }]} />
          </View>
        </View>
      </View>
    );
  }

  /* ── Error banner ──────────────────────────────────────────────── */
  if (error || !brief) {
    return (
      <View style={s.errorCard} testID={`${testID}-error`}>
        <Ionicons name="alert-circle-outline" size={18} color={colors.error} />
        <Text style={s.errorText}>{"Couldn't load Smart Brief"}</Text>
        <Pressable onPress={fetchBrief} hitSlop={8} testID={`${testID}-retry`}>
          <Ionicons name="refresh" size={18} color={colors.brand} />
        </Pressable>
      </View>
    );
  }

  const { customer, special_access: sa, last_visits, open_intelligence_alerts } = brief;

  const hasAccess = !!(sa.gate_code || sa.key_location || sa.dog_on_property || sa.other_notes);
  const alerts = open_intelligence_alerts.slice(0, 3);

  return (
    <View style={s.card} testID={testID}>
      {/* ── Customer header ──────────────────────────────────────── */}
      <View style={s.section} testID={`${testID}-customer`}>
        <View style={s.customerRow}>
          <View style={s.customerAvatar}>
            <Ionicons name="person" size={18} color={colors.brand} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={s.customerName} numberOfLines={1}>{customer.display_name}</Text>
            {customer.phone ? (
              <PhoneLink phone={customer.phone} style={s.subText} testID={`${testID}-phone`} />
            ) : null}
            {customer.address_line ? (
              <AddressLink address={customer.address_line} style={s.subText} testID={`${testID}-address`} />
            ) : null}
          </View>
        </View>
      </View>

      {/* ── Special access ───────────────────────────────────────── */}
      {hasAccess ? (
        <View style={s.section} testID={`${testID}-access`}>
          <Text style={s.sectionLabel}>Access Notes</Text>
          <View style={s.chipRow}>
            {sa.gate_code ? (
              <View style={s.chip} testID={`${testID}-gate`}>
                <Ionicons name="key-outline" size={13} color="#4338CA" />
                <Text style={s.chipText}>Gate: {sa.gate_code}</Text>
              </View>
            ) : null}
            {sa.key_location ? (
              <View style={s.chip} testID={`${testID}-key`}>
                <Ionicons name="lock-closed-outline" size={13} color="#4338CA" />
                <Text style={s.chipText}>{sa.key_location}</Text>
              </View>
            ) : null}
            {sa.dog_on_property ? (
              <View style={[s.chip, s.dogChip]} testID={`${testID}-dog`}>
                <Text style={{ fontSize: 13 }}>🐕</Text>
                <Text style={s.dogChipText}>Dog{sa.dog_notes ? `: ${sa.dog_notes}` : ""}</Text>
              </View>
            ) : null}
            {sa.other_notes ? (
              <View style={s.chip} testID={`${testID}-other-notes`}>
                <Ionicons name="document-text-outline" size={13} color="#4338CA" />
                <Text style={s.chipText} numberOfLines={2}>{sa.other_notes}</Text>
              </View>
            ) : null}
          </View>
        </View>
      ) : null}

      {/* ── Last visits ──────────────────────────────────────────── */}
      <View style={s.section} testID={`${testID}-visits`}>
        <Text style={s.sectionLabel}>Recent Visits</Text>
        {last_visits.length === 0 ? (
          <Text style={s.placeholder} testID={`${testID}-no-visits`}>No prior visits</Text>
        ) : (
          last_visits.map((v) => {
            const isExpanded = expandedVisit === v.visit_id;
            const chemEntries = CHEM_LABELS.filter(
              (c) => v.chemistry_snapshot[c.key] != null,
            );
            return (
              <View key={v.visit_id} testID={`${testID}-visit-${v.visit_id}`}>
                <Pressable
                  style={s.visitHeader}
                  onPress={() => setExpandedVisit(isExpanded ? null : v.visit_id)}
                  testID={`${testID}-visit-toggle-${v.visit_id}`}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={s.visitDate}>
                      {formatDate(v.completed_at)} · {v.tech_display_name}
                    </Text>
                    <Text style={s.visitService}>{v.service_type}</Text>
                  </View>
                  <Ionicons
                    name={isExpanded ? "chevron-up" : "chevron-down"}
                    size={16}
                    color={colors.muted}
                  />
                </Pressable>
                {isExpanded ? (
                  <View style={s.visitBody}>
                    {chemEntries.length > 0 ? (
                      <View style={s.chemRow} testID={`${testID}-chem-${v.visit_id}`}>
                        {chemEntries.map((c) => (
                          <View key={c.key} style={s.chemPill}>
                            <Text style={s.chemLabel}>{c.label}</Text>
                            <Text style={s.chemValue}>{v.chemistry_snapshot[c.key]}</Text>
                          </View>
                        ))}
                      </View>
                    ) : null}
                    {v.notes.map((n, i) => (
                      <View key={i} style={s.noteRow}>
                        <Text style={s.noteAuthor}>{n.author_display_name}</Text>
                        <Text style={s.noteBody}>{n.body}</Text>
                      </View>
                    ))}
                    {v.notes.length === 0 && chemEntries.length === 0 ? (
                      <Text style={s.placeholder}>No details recorded</Text>
                    ) : null}
                  </View>
                ) : null}
              </View>
            );
          })
        )}
      </View>

      {/* ── Intelligence alerts ──────────────────────────────────── */}
      {alerts.length > 0 ? (
        <View style={s.section} testID={`${testID}-alerts`}>
          <Text style={s.sectionLabel}>Alerts</Text>
          {alerts.map((a) => (
            <Pressable
              key={a.alert_id}
              style={s.alertRow}
              onPress={() => {
                if (brief.customer_id) {
                  router.push(`/customer/${brief.customer_id}`);
                } else {
                  Clipboard.setString(a.title);
                }
              }}
              testID={`${testID}-alert-${a.alert_id}`}
            >
              <View
                style={[s.severityDot, { backgroundColor: SEVERITY_COLOR[a.severity] || "#6B7280" }]}
              />
              <View style={{ flex: 1 }}>
                <Text style={s.alertTitle} numberOfLines={1}>{a.title}</Text>
                <Text style={s.alertBody} numberOfLines={1}>{a.body}</Text>
              </View>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

/* ── Styles ──────────────────────────────────────────────────────────── */

const s = StyleSheet.create({
  card: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  section: {
    padding: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  sectionLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.xs,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  /* Customer header */
  customerRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  customerAvatar: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  customerName: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  subText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 1,
  },
  /* Special access chips */
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#EEF2FF",
    paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: radius.pill,
  },
  chipText: {
    fontFamily: font.medium, fontSize: fontSize.xs, color: "#4338CA",
  },
  dogChip: { backgroundColor: "#FEE2E2" },
  dogChipText: { fontFamily: font.medium, fontSize: fontSize.xs, color: "#B91C1C" },
  /* Visits */
  visitHeader: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  visitDate: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface,
  },
  visitService: {
    fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted,
  },
  visitBody: {
    paddingVertical: spacing.sm,
    paddingLeft: spacing.sm,
    gap: spacing.xs,
  },
  chemRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chemPill: {
    flexDirection: "row", alignItems: "center", gap: 3,
    backgroundColor: colors.surfaceSecondary,
    paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: radius.sm,
  },
  chemLabel: { fontFamily: font.semibold, fontSize: 11, color: colors.muted },
  chemValue: { fontFamily: font.bold, fontSize: 11, color: colors.onSurface },
  noteRow: { marginTop: 4 },
  noteAuthor: { fontFamily: font.semibold, fontSize: fontSize.xs, color: colors.onSurface },
  noteBody: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 1 },
  /* Alerts */
  alertRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: spacing.xs,
  },
  severityDot: { width: 8, height: 8, borderRadius: 4 },
  alertTitle: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurface },
  alertBody: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  /* Placeholder */
  placeholder: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    fontStyle: "italic",
  },
  /* Loading */
  skeletonRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, padding: spacing.md },
  skeletonCircle: {
    width: 36, height: 36, borderRadius: 18, backgroundColor: colors.surfaceSecondary,
  },
  skeletonBar: {
    height: 12, borderRadius: 4, backgroundColor: colors.surfaceSecondary,
  },
  /* Error */
  errorCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    marginHorizontal: spacing.md, marginBottom: spacing.md,
    padding: spacing.md, borderRadius: radius.lg,
    backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FCA5A5",
  },
  errorText: {
    flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: "#B91C1C",
  },
});
