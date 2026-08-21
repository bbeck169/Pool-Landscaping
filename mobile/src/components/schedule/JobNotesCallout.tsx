/**
 * Feb-2026 · Schedule polish — Job Notes visibility bump (mobile).
 *
 * Amber-accented callout that renders ``job.notes`` (and optional
 * ``customer_notes`` / ``account_notes`` with a "Customer note:" prefix).
 * Replaces the previous blue-tinted Pressable + Alert.alert flow in
 * ``mobile/app/(app)/schedule/calendar.tsx`` so the mobile card matches
 * the same amber chip the web schedule now uses.
 *
 * Behaviour:
 *   • 2-line clamp on both notes lines when collapsed.
 *   • "Show more" / "Show less" toggle rendered only when either note
 *     plausibly overflows (>100 chars or contains a newline).
 *   • Empty on both notes ⇒ returns null (no placeholder chip).
 *   • Text size 13 px (web analogue uses 14 px per spec).
 */
import React, { useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

const AMBER_BG = "#FEF3C7";
const AMBER_ACCENT = "#F59E0B";
const AMBER_BORDER = "#FDE68A";
const AMBER_ICON = "#B45309";
const TEXT_DARK = "#111827";
const TEXT_MUTED = "#4B5563";

function _mayOverflow(s?: string | null): boolean {
  if (!s) return false;
  return s.length > 100 || s.indexOf("\n") >= 0;
}

export interface JobNotesCalloutProps {
  jobId: string;
  note?: string | null;
  customerNote?: string | null;
  truncated?: boolean;
}

export default function JobNotesCallout({
  jobId, note, customerNote, truncated = false,
}: JobNotesCalloutProps) {
  const jobNote = (note && String(note).trim()) ? String(note) : "";
  const custNote = (customerNote && String(customerNote).trim()) ? String(customerNote).trim() : "";
  if (!jobNote && !custNote) return null;

  const [expanded, setExpanded] = useState(false);
  const showMoreEligible = _mayOverflow(jobNote) || _mayOverflow(custNote);
  const clampLines = expanded ? undefined : 2;

  return (
    <View style={s.wrap} testID={`job-notes-callout-${jobId}`}>
      <Ionicons
        // ``document-text-outline`` was the prior icon here. Kept for
        // visual parity with other mobile notes affordances; ``pencil``
        // + ``document-text`` composited would be closer to the web's
        // ``NotebookPen`` but not worth a bundle addition.
        name="document-text-outline"
        size={13}
        color={AMBER_ICON}
        style={{ marginTop: 2 }}
        testID={`job-notes-icon-${jobId}`}
      />
      <View style={{ flex: 1, minWidth: 0 }}>
        {jobNote ? (
          <Text
            style={s.jobNote}
            numberOfLines={clampLines}
            ellipsizeMode="tail"
            testID={`job-${jobId}-notes`}
          >
            {jobNote}{truncated ? "…" : ""}
          </Text>
        ) : null}
        {custNote ? (
          <Text
            style={[s.custNote, { marginTop: jobNote ? 4 : 0 }]}
            numberOfLines={clampLines}
            ellipsizeMode="tail"
            testID={`job-notes-preview-${jobId}`}
          >
            <Text style={s.custNotePrefix}>Customer note: </Text>
            {custNote}
          </Text>
        ) : null}
        {showMoreEligible ? (
          <Pressable
            onPress={() => setExpanded((x) => !x)}
            hitSlop={6}
            testID={`job-notes-toggle-${jobId}`}
            accessibilityRole="button"
            accessibilityLabel={expanded ? "Show less" : "Show more"}
          >
            <Text style={s.toggle}>{expanded ? "Show less" : "Show more"}</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: {
    flexDirection: "row", alignItems: "flex-start", gap: 6,
    backgroundColor: AMBER_BG,
    borderColor: AMBER_BORDER, borderWidth: 1,
    borderLeftColor: AMBER_ACCENT, borderLeftWidth: 3,
    paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: 6, marginTop: 6,
  },
  jobNote: { fontSize: 13, lineHeight: 18, color: TEXT_DARK, fontWeight: "500" },
  custNote: { fontSize: 13, lineHeight: 18, color: TEXT_DARK },
  custNotePrefix: { fontWeight: "700", color: TEXT_MUTED },
  toggle: { fontSize: 12, fontWeight: "700", color: AMBER_ICON, marginTop: 4 },
});
