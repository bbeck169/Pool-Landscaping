/**
 * CustomerWarrantiesSection — inline read-only warranties list
 * for the admin/tech customer detail screen.
 *
 * Endpoint: GET /api/customers/{customer_id}/warranties (paginated envelope).
 * Read-only in v1 — no add/edit modals on mobile.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ActivityIndicator } from "react-native";

import { api } from "@/src/api";
import { colors, spacing, font, fontSize } from "@/src/theme";
import WarrantyCard, { WarrantyContract } from "./WarrantyCard";

export default function CustomerWarrantiesSection({
  customerId,
}: {
  customerId: string;
}) {
  const [items, setItems] = useState<WarrantyContract[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const res = await api.get(`/customers/${customerId}/warranties`);
      const list = res?.items || (Array.isArray(res) ? res : []);
      setItems(list);
    } catch (e: any) {
      setError(e?.message || "Failed to load warranties");
    } finally {
      setLoading(false);
    }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <ActivityIndicator
        color={colors.brand}
        style={{ marginVertical: spacing.md }}
        testID="warranty-loading"
      />
    );
  }

  if (error) {
    return (
      <Text style={s.errorText} testID="warranty-error">{error}</Text>
    );
  }

  return (
    <View testID="customer-warranties-section">
      {items.length === 0 ? (
        <Text style={s.empty} testID="warranty-empty">
          No warranty contracts on file.
        </Text>
      ) : (
        <View testID="warranty-list">
          {items.map((w, i) => (
            <WarrantyCard
              key={w.id}
              warranty={w}
              index={i}
              testIdPrefix="warranty"
            />
          ))}
        </View>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  empty: {
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.muted,
    marginBottom: spacing.md,
  },
  errorText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: "#B91C1C",
    marginBottom: spacing.md,
  },
});
