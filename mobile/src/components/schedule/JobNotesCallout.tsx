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
import NoteBlock from "./NoteBlock";

/* M2 hotfix — white fill with amber left-accent (was amber fill). */
const AMBER_BG = "#FFFFFF";
const AMBER_ACCENT = "#F59E0B";
const AMBER_BORDER = "#E5E7EB";
const AMBER_ICON = "#B45309";
const TEXT_DARK = "#111827";

function _mayOverflow(s?: string | null): boolean {
  if (!s) return false;
  return s.length > 100 || s.indexOf("\n") >= 0;
}

export interface JobNotesCalloutProps {
  jobId: string;
  note?: string | null;
  customerNote?: string | null;
  poolNote?: string | null;
  landscapeNote?: string | null;
  truncated?: boolean;
}

export default function JobNotesCallout({
  jobId, note, customerNote, poolNote, landscapeNote, truncated = false,
}: JobNotesCalloutProps) {
  // Rules of Hooks — keep ``useState`` above any early return so the
  // hook order stays stable across renders. Matches the web sibling.
  const [expanded, setExpanded] = useState(false);
  const jobNote = (note && String(note).trim()) ? String(note) : "";
  const custNote = (customerNote && String(customerNote).trim()) ? String(customerNote).trim() : "";
  const pool = (poolNote && String(poolNote).trim()) ? String(poolNote).trim() : "";
  const landscape = (landscapeNote && String(landscapeNote).trim()) ? String(landscapeNote).trim() : "";
  // Legacy toggle governs the job free-text note only; customer / pool /
  // landscape each own their toggle inside <NoteBlock> (web parity).
  const showMoreEligible = _mayOverflow(jobNote);
  const clampLines = expanded ? undefined : 2;
  if (!jobNote && !custNote && !pool && !landscape) return null;

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
        {/* Phase 3 · Feb-2026 — Customer → Pool → Landscape, each via
            the shared <NoteBlock> (120 chars OR 3 lines, own toggle). */}
        <NoteBlock label="Customer note" text={custNote} testID={`job-notes-preview-${jobId}`} />
        <NoteBlock label="Pool note" text={pool} testID={`job-notes-pool-${jobId}`} />
        <NoteBlock label="Landscape note" text={landscape} testID={`job-notes-landscape-${jobId}`} />
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
  toggle: { fontSize: 12, fontWeight: "700", color: AMBER_ICON, marginTop: 4 },
});
