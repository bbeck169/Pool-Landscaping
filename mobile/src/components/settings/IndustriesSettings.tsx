/**
 * IndustriesSettings — read/write multi-select for tenant industries.
 *
 * 25 toggles, auto-save on tap via PATCH /api/tenants/mine/settings.
 * Invalidates the useIndustries() cache after each successful save.
 *
 * Mounted on the Settings Hub General tab.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { INDUSTRIES, INDUSTRY_LABELS } from "@/src/config/industries";
import { invalidateIndustries } from "@/src/hooks/useIndustries";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

export default function IndustriesSettings() {
  const { showToast } = useToast();
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);

  // Load current industries on mount.
  useEffect(() => {
    api.get("/tenants/mine/settings")
      .then((res: any) => {
        setSelected(Array.isArray(res?.industries) ? res.industries : []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const toggle = useCallback(async (slug: string) => {
    const prev = selected;
    // Optimistic toggle.
    const next = prev.includes(slug)
      ? prev.filter((s) => s !== slug)
      : [...prev, slug];
    setSelected(next);
    setSaving(slug);

    try {
      await api.patch("/tenants/mine/settings", { industries: next });
      invalidateIndustries();
      showToast("Saved");
    } catch {
      // Rollback on error.
      setSelected(prev);
      showToast("Failed to save industries. Please refresh and try again.");
    } finally {
      setSaving(null);
    }
  }, [selected, showToast]);

  if (loading) {
    return (
      <View style={s.loadingWrap} testID="settings-industries-loading">
        <ActivityIndicator size="small" color={colors.brand} />
      </View>
    );
  }

  return (
    <View testID="settings-industries-section">
      <Text style={s.title} testID="settings-industries-title">Industries</Text>
      <Text style={s.subtitle}>
        Select all industries your business serves.
      </Text>
      <View style={s.grid}>
        {INDUSTRIES.map((slug) => {
          const active = selected.includes(slug);
          const isSaving = saving === slug;
          return (
            <Pressable
              key={slug}
              style={[s.row, active && s.rowActive]}
              onPress={() => toggle(slug)}
              disabled={saving !== null}
              testID={`settings-industry-checkbox-${slug}`}
            >
              <View style={[s.check, active && s.checkActive]}>
                {active && (
                  <Ionicons name="checkmark" size={14} color="#fff" />
                )}
              </View>
              <Text style={[s.label, active && s.labelActive]} numberOfLines={1}>
                {INDUSTRY_LABELS[slug] || slug}
              </Text>
              {isSaving && (
                <ActivityIndicator size="small" color={colors.brand} style={{ marginLeft: 4 }} />
              )}
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  loadingWrap: {
    paddingVertical: spacing.xl,
    alignItems: "center",
  },
  title: {
    fontFamily: font.semibold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
    marginBottom: 2,
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginBottom: spacing.md,
  },
  grid: { gap: spacing.sm },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  rowActive: {
    backgroundColor: "#E0F2FE",
    borderColor: "rgba(2,132,199,0.35)",
  },
  check: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
  },
  checkActive: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  label: {
    flex: 1,
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  labelActive: {
    fontFamily: font.semibold,
    color: colors.brand,
  },
});
