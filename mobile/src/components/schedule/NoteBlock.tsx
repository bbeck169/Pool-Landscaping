/**
 * Phase 3 · Feb-2026 — shared truncation primitive for the three
 * customer-sourced note types on the schedule card (customer / pool /
 * landscape). Mobile mirror of web `NoteBlock` in
 * `frontend/src/components/schedule/JobNotesCallout.jsx`.
 *
 *  • Hidden entirely when `text` is empty / whitespace / null.
 *  • Collapsed: 3-line clamp. "Show more" toggle appears when the text
 *    is > 120 chars OR contains a newline (wrapped text also hits the
 *    3-line ceiling via `numberOfLines`).
 *  • Each instance owns its own `expanded` state.
 */
import React, { useState } from "react";
import { View, Text, Pressable, StyleSheet } from "react-native";

export const NOTE_CHAR_LIMIT = 120;
export const NOTE_LINE_LIMIT = 3;

const TEXT_DARK = "#111827";
const TEXT_MUTED = "#4B5563";
const TOGGLE_FG = "#B45309";

export function noteOverflows(text: string): boolean {
  return text.length > NOTE_CHAR_LIMIT || text.indexOf("\n") >= 0;
}

export default function NoteBlock({ label, text, testID }: {
  label: string;
  text?: string | null;
  testID: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const safe = text && String(text).trim() ? String(text).trim() : "";
  if (!safe) return null;
  const overflow = noteOverflows(safe);
  return (
    <View style={s.wrap} testID={testID}>
      <Text
        style={s.body}
        numberOfLines={expanded ? undefined : NOTE_LINE_LIMIT}
        ellipsizeMode="tail"
        testID={`${testID}-text`}
      >
        <Text style={s.label}>{label}: </Text>
        {safe}
      </Text>
      {overflow ? (
        <Pressable
          onPress={() => setExpanded((x) => !x)}
          hitSlop={8}
          testID={`${testID}-toggle`}
          accessibilityRole="button"
          accessibilityState={{ expanded }}
          accessibilityLabel={expanded ? "Show less" : "Show more"}
        >
          <Text style={s.toggle}>{expanded ? "Show less" : "Show more"}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { marginTop: 4 },
  body: { fontSize: 13, lineHeight: 18, color: TEXT_DARK },
  label: { fontWeight: "700", color: TEXT_MUTED },
  toggle: { fontSize: 12, fontWeight: "700", color: TOGGLE_FG, marginTop: 2 },
});
