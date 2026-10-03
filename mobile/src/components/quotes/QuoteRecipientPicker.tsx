/**
 * QuoteRecipientPicker — Phase 2 B2 mobile parity
 *
 * Unified picker that searches both Customers and Leads via
 * GET /api/quote-recipients/search. Renders a trigger button
 * that opens a Sheet with a debounced search + FlatList of results.
 *
 * Props:
 *   value      {type:"customer"|"lead", id:string, name:string} | null
 *   onChange   fn({type,id,name}) — fired on pick
 *   disabled   boolean
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  FlatList,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Sheet } from "@/src/components/ui";
import AppTextInput from "@/src/components/ui/AppTextInput";

// ── Badge constants (match web exactly) ──────────────────────────
const BADGE_COPY = { customer: "Customer", lead: "Lead" } as const;
const BADGE_BG = { customer: "#DBEAFE", lead: "#FEF3C7" } as const;
const BADGE_FG = { customer: "#1E40AF", lead: "#92400E" } as const;

export type RecipientValue = {
  type: "customer" | "lead";
  id: string;
  name: string;
} | null;

interface SearchResult {
  id: string;
  kind: "customer" | "lead";
  display_name?: string;
  email?: string;
  phone?: string;
}

// ── RecipientTypeBadge (exported for reuse on detail page) ───────
export function RecipientTypeBadge({
  type,
  testID,
}: {
  type: "customer" | "lead" | string;
  testID?: string;
}) {
  const kind = type === "lead" ? "lead" : "customer";
  return (
    <View
      testID={testID}
      style={[
        styles.badge,
        { backgroundColor: BADGE_BG[kind] },
      ]}
    >
      <Text style={[styles.badgeText, { color: BADGE_FG[kind] }]}>
        {BADGE_COPY[kind]}
      </Text>
    </View>
  );
}

// ── Main Picker ──────────────────────────────────────────────────
interface PickerProps {
  value: RecipientValue;
  onChange: (v: RecipientValue) => void;
  disabled?: boolean;
}

export default function QuoteRecipientPicker({
  value,
  onChange,
  disabled = false,
}: PickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced search
  const search = useCallback(async (q: string) => {
    setLoading(true);
    try {
      const rows = await api.get(
        `/quote-recipients/search?q=${encodeURIComponent(q || "")}&limit=20`,
      );
      setResults(Array.isArray(rows) ? rows : []);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => search(query), 300);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [open, query, search]);

  const handleSelect = (item: SearchResult) => {
    const kind = item.kind === "lead" ? "lead" : "customer";
    onChange({
      type: kind,
      id: item.id,
      name: item.display_name || "",
    });
    setOpen(false);
    setQuery("");
  };

  const selectedLabel = value?.id
    ? value.name || value.id
    : "Choose a customer or lead…";

  return (
    <>
      <View style={{ marginBottom: spacing.md }}>
        <Text style={styles.label}>RECIPIENT *</Text>
        <Pressable
          testID="quote-recipient-picker"
          style={[styles.trigger, disabled && styles.triggerDisabled]}
          onPress={() => !disabled && setOpen(true)}
          disabled={disabled}
        >
          <View style={styles.triggerInner}>
            {value?.id ? (
              <RecipientTypeBadge
                type={value.type}
                testID="quote-recipient-picker-selected-badge"
              />
            ) : null}
            <Text
              style={[
                styles.triggerText,
                !value?.id && { color: colors.muted },
              ]}
              numberOfLines={1}
            >
              {selectedLabel}
            </Text>
          </View>
          <Ionicons name="chevron-down" size={18} color={colors.muted} />
        </Pressable>
      </View>

      <Sheet
        visible={open}
        onClose={() => { setOpen(false); setQuery(""); }}
        title="Select Recipient"
        testID="quote-recipient-sheet"
      >
        <AppTextInput
          testID="quote-recipient-picker-search"
          style={styles.searchInput}
          value={query}
          onChangeText={setQuery}
          placeholder="Search customers or leads…"
          placeholderTextColor={colors.muted}
          autoFocus
        />

        {loading ? (
          <ActivityIndicator
            size="small"
            color={colors.brand}
            style={{ marginTop: spacing.lg }}
            testID="quote-recipient-picker-loading"
          />
        ) : null}

        <FlatList
          data={results}
          keyExtractor={(item) => `${item.kind}-${item.id}`}
          keyboardShouldPersistTaps="handled"
          style={{ maxHeight: 400 }}
          ListEmptyComponent={
            !loading ? (
              <Text
                style={styles.empty}
                testID="quote-recipient-picker-empty"
              >
                No matches.
              </Text>
            ) : null
          }
          renderItem={({ item }) => {
            const kind = item.kind === "lead" ? "lead" : "customer";
            const aux = [item.email, item.phone].filter(Boolean).join(" · ");
            const selected = value?.id === item.id && value?.type === kind;

            return (
              <Pressable
                testID={`quote-recipient-picker-item-${kind}-${item.id}`}
                style={styles.resultRow}
                onPress={() => handleSelect(item)}
              >
                <View style={styles.resultLeft}>
                  <View style={styles.resultNameRow}>
                    <RecipientTypeBadge
                      type={kind}
                      testID={`quote-recipient-picker-item-${kind}-${item.id}-badge`}
                    />
                    <Text style={styles.resultName} numberOfLines={1}>
                      {item.display_name || "(unnamed)"}
                    </Text>
                  </View>
                  {aux ? (
                    <Text style={styles.resultAux} numberOfLines={1}>
                      {aux}
                    </Text>
                  ) : null}
                </View>
                {selected ? (
                  <Ionicons name="checkmark" size={18} color={colors.brand} />
                ) : null}
              </Pressable>
            );
          }}
        />
      </Sheet>
    </>
  );
}

const styles = StyleSheet.create({
  label: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurfaceSecondary,
    marginBottom: spacing.xs,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  trigger: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.surface,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 52,
  },
  triggerDisabled: { opacity: 0.6 },
  triggerInner: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginRight: spacing.sm,
  },
  triggerText: {
    fontFamily: font.regular,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    flexShrink: 1,
  },
  searchInput: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 44,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  empty: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.lg,
  },
  resultRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    minHeight: 52,
  },
  resultLeft: { flex: 1, marginRight: spacing.sm },
  resultNameRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  resultName: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
    flexShrink: 1,
  },
  resultAux: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
    marginLeft: 2,
  },
  // Badge
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
    alignSelf: "flex-start",
  },
  badgeText: {
    fontFamily: font.bold,
    fontSize: 10,
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
});
