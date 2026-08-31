/**
 * CrewFilterBar — single-select "All crews" dropdown for the Schedule screen.
 * When a crew is selected, shows member names as compact chips.
 */
import React, { useState } from "react";
import {
  View, Text, Pressable, Modal, ScrollView, StyleSheet,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type Crew = {
  id: string;
  name: string;
  tech_ids?: string[];
  members?: { id: string; name: string }[];
  color?: string;
};

type Props = {
  crews: Crew[];
  selectedCrewId: string;
  onSelect: (crewId: string) => void;
  memberNames: string[];
};

export default function CrewFilterBar({
  crews, selectedCrewId, onSelect, memberNames,
}: Props) {
  const [open, setOpen] = useState(false);
  const selectedCrew = crews.find((c) => c.id === selectedCrewId);
  const label = selectedCrew ? selectedCrew.name : "All crews";

  return (
    <View testID="crew-filter-bar">
      <Pressable
        onPress={() => setOpen(true)}
        style={[s.dropdown, selectedCrewId ? s.dropdownActive : null]}
        testID="crew-filter-trigger"
        accessibilityRole="button"
        accessibilityLabel={`Crew filter: ${label}`}
      >
        <Ionicons
          name="people-outline"
          size={14}
          color={selectedCrewId ? "#fff" : colors.onSurface}
        />
        <Text
          style={[s.dropdownText, selectedCrewId && s.dropdownTextActive]}
          numberOfLines={1}
        >
          {label}
        </Text>
        <Ionicons
          name="chevron-down"
          size={12}
          color={selectedCrewId ? "#fff" : colors.muted}
        />
      </Pressable>

      {/* Member chips */}
      {selectedCrewId && memberNames.length > 0 ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          style={s.memberRow}
          testID="crew-member-chips"
        >
          {memberNames.map((name, i) => (
            <View key={`${name}-${i}`} style={s.memberChip}>
              <Ionicons name="person" size={10} color="#059669" />
              <Text style={s.memberChipText}>{name}</Text>
            </View>
          ))}
        </ScrollView>
      ) : null}

      {/* Crew picker modal */}
      <Modal
        visible={open}
        transparent
        animationType="fade"
        onRequestClose={() => setOpen(false)}
      >
        <Pressable style={s.backdrop} onPress={() => setOpen(false)}>
          <View style={s.sheet} testID="crew-filter-picker">
            <Text style={s.sheetTitle}>Select crew</Text>
            <ScrollView style={{ maxHeight: 350 }}>
              {/* "All crews" option */}
              <Pressable
                onPress={() => { onSelect(""); setOpen(false); }}
                style={[s.option, !selectedCrewId && s.optionActive]}
                testID="crew-filter-all"
              >
                <Ionicons name="globe-outline" size={16} color={colors.muted} />
                <Text
                  style={[s.optionText, !selectedCrewId && s.optionTextActive]}
                >
                  All crews
                </Text>
                {!selectedCrewId ? (
                  <Ionicons name="checkmark" size={16} color={colors.brand} />
                ) : null}
              </Pressable>
              {crews.map((c) => (
                <Pressable
                  key={c.id}
                  onPress={() => { onSelect(c.id); setOpen(false); }}
                  style={[s.option, selectedCrewId === c.id && s.optionActive]}
                  testID={`crew-filter-${c.id}`}
                >
                  {c.color ? (
                    <View style={[s.colorDot, { backgroundColor: c.color }]} />
                  ) : (
                    <Ionicons name="people" size={16} color={colors.brand} />
                  )}
                  <Text
                    style={[
                      s.optionText,
                      selectedCrewId === c.id && s.optionTextActive,
                    ]}
                  >
                    {c.name}
                  </Text>
                  {selectedCrewId === c.id ? (
                    <Ionicons name="checkmark" size={16} color={colors.brand} />
                  ) : null}
                </Pressable>
              ))}
              {crews.length === 0 ? (
                <Text style={s.emptyText} testID="crew-filter-empty">
                  No crews configured
                </Text>
              ) : null}
            </ScrollView>
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  dropdown: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.md,
    height: 34,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    maxWidth: 180,
  },
  dropdownActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  dropdownText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    flexShrink: 1,
  },
  dropdownTextActive: { color: "#fff" },
  memberRow: { marginTop: spacing.xs, flexDirection: "row" },
  memberChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
    backgroundColor: "#ECFDF5",
    marginRight: spacing.xs,
  },
  memberChipText: { fontFamily: font.medium, fontSize: 10, color: "#065F46" },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
  },
  sheet: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    maxHeight: "60%",
  },
  sheetTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  option: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.md,
    marginBottom: 2,
  },
  optionActive: { backgroundColor: colors.brandTertiary },
  optionText: {
    flex: 1,
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  optionTextActive: { color: colors.brand },
  colorDot: { width: 10, height: 10, borderRadius: 5 },
  emptyText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: spacing.lg,
  },
});
