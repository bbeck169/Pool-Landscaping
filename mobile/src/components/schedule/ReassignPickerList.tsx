/**
 * UU-mobile · bulk-reassign picker rows (web AssignTechDropdown parity): crews
 * first (sub-label literal "crew"), then techs (sub-label = role). Tech row markup
 * + testIDs are unchanged from calendar.tsx's original inline list.
 */
import React from "react";
import { View, Text, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors, font, fontSize, radius } from "@/src/theme";
import { reassignRoleLabel } from "@/src/lib/bulkReassign";

type Props = {
  crews: any[];
  techs: any[];
  pickedTechId: string;
  pickedCrewId: string;
  onPickTech: (id: string) => void;
  onPickCrew: (id: string) => void;
};

function Row({ picked, onPress, testID, title, sub }: { picked: boolean; onPress: () => void; testID: string; title: string; sub: string }) {
  return (
    <Pressable
      onPress={onPress}
      style={{
        flexDirection: "row", alignItems: "center", gap: 10,
        paddingVertical: 10, paddingHorizontal: 12, borderRadius: radius.md,
        backgroundColor: picked ? colors.brandTertiary : "transparent",
        marginBottom: 4,
      }}
      accessibilityState={{ selected: picked }}
      testID={testID}
    >
      <View style={{
        width: 20, height: 20, borderRadius: 10,
        borderWidth: 2, borderColor: picked ? colors.brand : colors.border,
        backgroundColor: picked ? colors.brand : "transparent",
        alignItems: "center", justifyContent: "center",
      }}>
        {picked ? <Ionicons name="checkmark" size={12} color="#fff" /> : null}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface }}>{title}</Text>
        {sub ? <Text style={{ fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, textTransform: "capitalize" }} testID={`${testID}-sublabel`}>{sub}</Text> : null}
      </View>
    </Pressable>
  );
}

export default function ReassignPickerList({ crews, techs, pickedTechId, pickedCrewId, onPickTech, onPickCrew }: Props) {
  const crewRows = Array.isArray(crews) ? crews.filter((c) => c?.id) : [];
  return (
    <>
      {crewRows.map((c) => (
        <Row key={`crew-${c.id}`} picked={pickedCrewId === c.id} onPress={() => onPickCrew(c.id)} testID={`reassign-crew-${c.id}`} title={c.name || "Unnamed crew"} sub="crew" />
      ))}
      {techs.map((t) => (
        <Row key={t.id} picked={pickedTechId === t.id} onPress={() => onPickTech(t.id)} testID={`reassign-tech-${t.id}`} title={t.name} sub={reassignRoleLabel(t.role)} />
      ))}
      {techs.length === 0 && crewRows.length === 0 ? (
        <Text style={{ fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", paddingVertical: 20 }} testID="reassign-empty">
          No technicians available
        </Text>
      ) : null}
    </>
  );
}
