/**
 * Phase v · WaterBodyManager — manages the water_bodies[] array.
 *
 * Renders a list of WaterBodyPanel cards + an "Add body of water"
 * button with a fixed-type picker sheet. Auto-seeds one pool body
 * for the common single-pool case (zero extra taps).
 */
import React, { useState, useCallback } from "react";
import {
  View, Text, Pressable, StyleSheet, Modal,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  WaterBody, BodyType, WATER_BODY_TYPES, BODY_TYPE_TINTS,
  MAX_BODIES, makeEmptyBody,
} from "@/src/lib/waterBodies";
import WaterBodyPanel from "./WaterBodyPanel";

interface Props {
  bodies: WaterBody[];
  locked: boolean;
  highlightBodies?: Record<number, string[]>;
  onChange: (next: WaterBody[]) => void;
}

export default function WaterBodyManager({ bodies, locked, highlightBodies, onChange }: Props) {
  const [pickerOpen, setPickerOpen] = useState(false);

  const addBody = useCallback((type: BodyType) => {
    if (bodies.length >= MAX_BODIES) return;
    const next = [...bodies, makeEmptyBody(type, bodies.length)];
    onChange(next);
    setPickerOpen(false);
  }, [bodies, onChange]);

  const updateBody = useCallback((index: number, updated: WaterBody) => {
    const next = [...bodies];
    next[index] = updated;
    onChange(next);
  }, [bodies, onChange]);

  const removeBody = useCallback((index: number) => {
    if (bodies.length <= 1) return;
    const next = bodies.filter((_: any, i: number) => i !== index);
    next.forEach((b, i) => { b.sequence = i; });
    onChange(next);
  }, [bodies, onChange]);

  return (
    <View testID="water-body-manager">
      {bodies.map((body, idx) => (
        <WaterBodyPanel
          key={body.id}
          body={body}
          index={idx}
          locked={locked}
          canRemove={bodies.length > 1}
          isPrimary={idx === 0}
          highlightMissing={highlightBodies?.[idx]}
          onChange={(updated) => updateBody(idx, updated)}
          onRemove={() => removeBody(idx)}
        />
      ))}

      {!locked && bodies.length < MAX_BODIES ? (
        <Pressable
          style={s.addBtn}
          onPress={() => setPickerOpen(true)}
          testID="add-water-body-btn"
        >
          <Ionicons name="add-circle-outline" size={18} color={colors.brand} />
          <Text style={s.addBtnText}>Add body of water</Text>
        </Pressable>
      ) : null}

      {/* Type picker modal */}
      <Modal
        visible={pickerOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setPickerOpen(false)}
      >
        <Pressable style={s.backdrop} onPress={() => setPickerOpen(false)}>
          <View style={s.pickerSheet}>
            <Text style={s.pickerTitle}>Select body type</Text>
            {WATER_BODY_TYPES.map((bt) => {
              const tint = BODY_TYPE_TINTS[bt.value] || BODY_TYPE_TINTS.pool;
              return (
                <Pressable
                  key={bt.value}
                  style={s.pickerRow}
                  onPress={() => addBody(bt.value)}
                  testID={`add-body-type-${bt.value}`}
                >
                  <View style={[s.pickerDot, { backgroundColor: tint.fg }]} />
                  <Text style={s.pickerLabel}>{bt.label}</Text>
                </Pressable>
              );
            })}
          </View>
        </Pressable>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 14,
    borderWidth: 1.5,
    borderStyle: "dashed",
    borderColor: colors.brand,
    borderRadius: radius.lg,
    marginBottom: spacing.md,
  },
  addBtnText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.35)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.xl,
  },
  pickerSheet: {
    width: "100%",
    maxWidth: 320,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  pickerTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    marginBottom: spacing.sm,
  },
  pickerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: 14,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  pickerDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  pickerLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
});
