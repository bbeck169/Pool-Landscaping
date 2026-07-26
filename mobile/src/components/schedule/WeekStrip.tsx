/**
 * WeekStrip — compact 7-day (Mon–Sun) toggle strip.
 *
 * Port of `/frontend/src/components/schedule/WeekStrip.jsx`.
 *
 * Props:
 *   selectedDate  — ISO yyyy-mm-dd string (controlled)
 *   onSelectDate  — callback fired with ISO string when a day is tapped
 *
 * Rendering rules:
 *   • Selected day → filled circle with white text
 *   • Today        → small dot below the number (visible even on other weeks)
 *   • Chevrons     → shift visible week ±7 days
 *   • Auto-selects today on mount when selectedDate is not provided
 */
import React, { useEffect, useMemo, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

const DAY_LABELS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function isoToDate(iso?: string | null): Date {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return new Date();
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

function dateToIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function startOfWeekMonday(d: Date): Date {
  const day = d.getDay(); // 0=Sun, 1=Mon ... 6=Sat
  const diff = day === 0 ? -6 : 1 - day;
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + diff);
}

type Props = {
  selectedDate?: string;
  onSelectDate?: (iso: string) => void;
  /** Map of ISO date → job count for the visible week. */
  counts?: Record<string, number>;
};

export default function WeekStrip({ selectedDate, onSelectDate, counts }: Props) {
  const [anchor, setAnchor] = useState(() =>
    startOfWeekMonday(isoToDate(selectedDate || todayIso()))
  );

  // Keep anchor in sync when parent shifts to a different week.
  useEffect(() => {
    if (!selectedDate) return;
    const monday = startOfWeekMonday(isoToDate(selectedDate));
    setAnchor((prev) => {
      if (dateToIso(prev) === dateToIso(monday)) return prev;
      return monday;
    });
  }, [selectedDate]);

  // Auto-select today on mount when parent didn't seed a date.
  useEffect(() => {
    if (selectedDate) return;
    onSelectDate?.(todayIso());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const today = todayIso();
  const selIso = selectedDate || today;

  const days = useMemo(() => {
    return Array.from({ length: 7 }).map((_, i) => {
      const d = new Date(anchor.getFullYear(), anchor.getMonth(), anchor.getDate() + i);
      return {
        iso: dateToIso(d),
        label: DAY_LABELS[i],
        num: d.getDate(),
      };
    });
  }, [anchor]);

  const shiftWeek = (dir: -1 | 1) => {
    setAnchor((prev) =>
      new Date(prev.getFullYear(), prev.getMonth(), prev.getDate() + dir * 7)
    );
  };

  return (
    <View style={s.container} testID="schedule-week-strip">
      <TouchableOpacity
        onPress={() => shiftWeek(-1)}
        style={s.chevron}
        activeOpacity={0.6}
        testID="week-strip-prev"
      >
        <Ionicons name="chevron-back" size={16} color={colors.onSurface} />
      </TouchableOpacity>

      <View style={s.daysRow} testID="week-strip-days">
        {days.map((d) => {
          const isSelected = d.iso === selIso;
          const isToday = d.iso === today;
          return (
            <TouchableOpacity
              key={d.iso}
              onPress={() => onSelectDate?.(d.iso)}
              style={s.dayBtn}
              activeOpacity={0.6}
              testID={`week-strip-day-${d.iso}`}
            >
              <Text
                style={[
                  s.dayLabel,
                  isSelected && s.dayLabelSelected,
                  isToday && !isSelected && s.dayLabelToday,
                ]}
              >
                {d.label}
              </Text>
              <View style={[s.dayCircle, isSelected && s.dayCircleSelected]}>
                <Text
                  style={[s.dayNum, isSelected && s.dayNumSelected]}
                >
                  {d.num}
                </Text>
              </View>
              <View
                style={[
                  s.todayDot,
                  isToday && !isSelected && s.todayDotVisible,
                ]}
                testID={isToday ? `week-strip-today-dot-${d.iso}` : undefined}
              />
            </TouchableOpacity>
          );
        })}
      </View>

      <TouchableOpacity
        onPress={() => shiftWeek(1)}
        style={s.chevron}
        activeOpacity={0.6}
        testID="week-strip-next"
      >
        <Ionicons name="chevron-forward" size={16} color={colors.onSurface} />
      </TouchableOpacity>
    </View>
  );
}

const s = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    gap: 2,
    marginHorizontal: spacing.md,
    marginBottom: spacing.xs,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.xs,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chevron: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
  },
  daysRow: {
    flex: 1,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  dayBtn: {
    flex: 1,
    alignItems: "center",
    paddingVertical: 2,
    minWidth: 36,
  },
  dayLabel: {
    fontFamily: font.bold,
    fontSize: 9,
    letterSpacing: 0.8,
    color: colors.muted,
    marginBottom: 2,
  },
  dayLabelSelected: {
    color: colors.brand,
  },
  dayLabelToday: {
    color: colors.onSurface,
  },
  dayCircle: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "transparent",
  },
  dayCircleSelected: {
    backgroundColor: colors.brand,
    shadowColor: colors.brand,
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 6,
    elevation: 3,
  },
  dayNum: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  dayNumSelected: {
    color: "#FFFFFF",
  },
  todayDot: {
    width: 4,
    height: 4,
    borderRadius: 2,
    marginTop: 2,
    backgroundColor: "transparent",
  },
  todayDotVisible: {
    backgroundColor: colors.brand,
  },
  countBadge: {
    fontFamily: font.bold,
    fontSize: 9,
    color: colors.muted,
    marginTop: 1,
    textAlign: "center",
  },
  countBadgeSelected: {
    color: colors.brand,
  },
});
