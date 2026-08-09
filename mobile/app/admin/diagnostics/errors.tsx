/**
 * Phase 41.5c · Feb-2026 — Mobile Client-side Errors diagnostics.
 *
 * Native parity for the web ``/admin/diagnostics/errors`` page
 * (``frontend/src/pages/admin/AdminDiagnosticsErrorsPage.jsx``).
 * Read-only newest-100 list of frontend-captured errors.
 *
 * Endpoint reused verbatim:
 *   • GET /api/admin/client-errors?component=…&limit=…
 *     → { errors: [{id, created_at, component, message, url,
 *                    user_email, user_agent, stack, extra, ...}],
 *          count }
 *
 * Role gate: admin / super_admin (mirrors the web ``<AdminOnly>`` +
 * the backend ``if role not in ("admin","super_admin")`` check).
 *
 * Extras beyond the web page (leveraging fields already returned by
 * the endpoint — no backend changes):
 *   • Tap-to-expand detail modal showing full stack + user agent +
 *     url + extra JSON.
 *   • Copy-to-clipboard for the stack trace (expo-clipboard).
 *   • Pull-to-refresh.
 * The web page does not surface the stack trace; this ticket asked
 * for a detail view and the field is present in the payload.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, RefreshControl,
  TouchableOpacity, ActivityIndicator, Modal, Pressable, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

type ClientErrorRow = {
  id: string;
  created_at?: string;
  ts?: string;
  component?: string | null;
  message: string;
  url?: string | null;
  user_email?: string | null;
  user_agent?: string | null;
  stack?: string | null;
  extra?: any;
};

function fmtWhen(iso?: string | null) {
  if (!iso) return "—";
  return String(iso).slice(0, 19).replace("T", " ");
}

export default function ClientErrorsDiagnosticsScreen() {
  const { user } = useAuth();
  // Mirror the web ``<AdminOnly>`` route guard + backend 403.
  const isAdmin = user?.role === "admin" || (user?.role as any) === "super_admin";

  const [rows, setRows] = useState<ClientErrorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [componentFilter, setComponentFilter] = useState("");
  const [selected, setSelected] = useState<ClientErrorRow | null>(null);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (componentFilter) qs.set("component", componentFilter);
      const q = qs.toString() ? `?${qs.toString()}` : "";
      const r = await api.get(`/admin/client-errors${q}`);
      setRows(r?.errors || []);
    } catch (e: any) {
      setError(e?.message || "Failed to load");
      setRows([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isAdmin, componentFilter]);

  useEffect(() => { load(); }, [load]);

  const copyStack = async () => {
    if (!selected?.stack) return;
    try {
      await Clipboard.setStringAsync(selected.stack);
      Alert.alert("Copied", "Stack trace copied to clipboard.");
    } catch {
      Alert.alert("Error", "Copy failed.");
    }
  };

  if (!isAdmin) {
    return (
      <View style={s.root} testID="client-errors-role-gate">
        <Header title="Client Errors" back />
        <View style={s.center}>
          <Ionicons name="lock-closed" size={32} color={colors.muted} />
          <Text style={s.centerText}>Admin only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={s.root} testID="client-errors-screen">
      <Header title="Client Errors"
              subtitle="Frontend Error Boundary reports · newest 100"
              back />

      <View style={s.toolbar}>
        <TextInput
          testID="client-errors-filter"
          style={s.search}
          value={componentFilter}
          onChangeText={setComponentFilter}
          onSubmitEditing={load}
          placeholder="Filter by component (e.g. DispatchBoard)"
          placeholderTextColor={colors.muted}
          autoCapitalize="none"
          autoCorrect={false}
          returnKeyType="search"
        />
        <TouchableOpacity onPress={load} style={s.refreshBtn}
                          testID="client-errors-refresh">
          <Ionicons name="refresh" size={16} color={colors.onSurface} />
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={s.center}>
          <ActivityIndicator size="large" color={colors.brand}
                             testID="client-errors-loading" />
        </View>
      ) : (
        <ScrollView
          testID="client-errors-list"
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing}
                              onRefresh={() => { setRefreshing(true); load(); }} />}
        >
          {error ? (
            <View style={s.errorBanner} testID="client-errors-error">
              <Ionicons name="warning" size={16} color="#7F1D1D" />
              <Text style={s.errorText}>{error}</Text>
            </View>
          ) : null}

          {!error && rows.length === 0 ? (
            <View style={s.emptyCard} testID="client-errors-empty">
              <Text style={s.emptyText}>No client-side errors recorded.</Text>
            </View>
          ) : null}

          {rows.map((r) => (
            <TouchableOpacity
              key={r.id}
              activeOpacity={0.7}
              style={s.card}
              onPress={() => setSelected(r)}
              testID={`client-errors-row-${r.id}`}
            >
              <View style={s.cardHeader}>
                <Text style={s.cardWhen}
                      testID={`client-errors-when-${r.id}`}>
                  {fmtWhen(r.created_at || r.ts)}
                </Text>
                {r.component ? (
                  <View style={s.componentPill}>
                    <Text style={s.componentPillText}>{r.component}</Text>
                  </View>
                ) : null}
              </View>
              <Text style={s.messageText}
                    testID={`client-errors-message-${r.id}`}
                    numberOfLines={3}>
                {r.message}
              </Text>
              {r.url ? (
                <Text style={s.urlText} numberOfLines={1}>{r.url}</Text>
              ) : null}
              <Text style={s.userText}>
                {r.user_email || "anonymous"}
              </Text>
            </TouchableOpacity>
          ))}
        </ScrollView>
      )}

      <Modal
        visible={selected !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setSelected(null)}
      >
        <View style={s.modalBackdrop}>
          <View style={s.modalCard} testID="client-errors-detail-modal">
            <View style={s.modalTopRow}>
              <Text style={s.modalTitle}>Error detail</Text>
              <Pressable onPress={() => setSelected(null)}
                          testID="client-errors-close-detail"
                          style={s.modalClose}>
                <Ionicons name="close" size={20} color={colors.onSurface} />
              </Pressable>
            </View>
            <ScrollView contentContainerStyle={{ paddingBottom: spacing.md }}>
              <Text style={s.detailLabel}>When</Text>
              <Text style={s.detailValue}>
                {fmtWhen(selected?.created_at || selected?.ts)}
              </Text>
              <Text style={s.detailLabel}>Component</Text>
              <Text style={s.detailValue}>{selected?.component || "—"}</Text>
              <Text style={s.detailLabel}>Message</Text>
              <Text style={s.detailValueMono}
                    testID="client-errors-detail-message">
                {selected?.message}
              </Text>
              <Text style={s.detailLabel}>URL</Text>
              <Text style={s.detailValue}
                    testID="client-errors-detail-url"
                    selectable>
                {selected?.url || "—"}
              </Text>
              <Text style={s.detailLabel}>User</Text>
              <Text style={s.detailValue}>
                {selected?.user_email || "anonymous"}
              </Text>
              <Text style={s.detailLabel}>User agent</Text>
              <Text style={s.detailValueMono}
                    testID="client-errors-detail-ua"
                    selectable>
                {selected?.user_agent || "—"}
              </Text>
              <Text style={s.detailLabel}>Stack</Text>
              <View style={s.stackBox}>
                <Text style={s.stackText}
                      testID="client-errors-detail-stack"
                      selectable>
                  {selected?.stack || "(no stack trace captured)"}
                </Text>
              </View>
              {selected?.extra ? (
                <>
                  <Text style={s.detailLabel}>Extra</Text>
                  <View style={s.stackBox}>
                    <Text style={s.stackText} selectable>
                      {typeof selected.extra === "string"
                        ? selected.extra
                        : JSON.stringify(selected.extra, null, 2)}
                    </Text>
                  </View>
                </>
              ) : null}
            </ScrollView>
            <View style={s.modalFooter}>
              <TouchableOpacity
                onPress={copyStack}
                disabled={!selected?.stack}
                style={[s.copyBtn, !selected?.stack && { opacity: 0.5 }]}
                testID="client-errors-copy-stack"
              >
                <Ionicons name="copy" size={14} color="#fff" />
                <Text style={s.copyBtnText}>Copy stack</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: spacing.md },
  centerText: { fontFamily: font.medium, fontSize: fontSize.lg, color: colors.muted },

  toolbar: { flexDirection: "row", gap: spacing.sm,
              paddingHorizontal: spacing.lg, paddingTop: spacing.md,
              alignItems: "center" },
  search: { flex: 1, backgroundColor: colors.surface,
              borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
              paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
              fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  refreshBtn: { padding: 10, backgroundColor: colors.surface,
                 borderWidth: 1, borderColor: colors.border, borderRadius: radius.md },

  errorBanner: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#FEE2E2", borderColor: "#FCA5A5", borderWidth: 1,
    borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md,
  },
  errorText: { fontFamily: font.regular, fontSize: fontSize.sm, color: "#7F1D1D" },

  emptyCard: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.lg, alignItems: "center",
  },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },

  card: { backgroundColor: colors.surface, borderRadius: radius.md,
           borderWidth: 1, borderColor: colors.border,
           padding: spacing.md, marginBottom: spacing.md },
  cardHeader: { flexDirection: "row", justifyContent: "space-between",
                 alignItems: "center", marginBottom: spacing.xs },
  cardWhen: { fontFamily: font.bold, fontSize: fontSize.xs,
               color: colors.onSurface },
  componentPill: { backgroundColor: colors.surfaceTertiary,
                    borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  componentPillText: { fontFamily: font.bold, fontSize: 10,
                        color: colors.onSurfaceSecondary,
                        textTransform: "uppercase", letterSpacing: 0.5 },
  messageText: { fontFamily: font.regular, fontSize: fontSize.sm,
                  color: colors.onSurface, marginTop: 2 },
  urlText: { fontFamily: font.regular, fontSize: fontSize.xs,
              color: colors.muted, marginTop: 4 },
  userText: { fontFamily: font.regular, fontSize: fontSize.xs,
               color: colors.muted, marginTop: 4 },

  modalBackdrop: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
                    alignItems: "center", justifyContent: "center", padding: spacing.md },
  modalCard: { width: "100%", maxWidth: 520, maxHeight: "85%",
                backgroundColor: colors.surface, borderRadius: radius.lg,
                padding: spacing.lg },
  modalTopRow: { flexDirection: "row", justifyContent: "space-between",
                  alignItems: "center", marginBottom: spacing.md },
  modalTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface },
  modalClose: { padding: 4 },
  detailLabel: { fontFamily: font.bold, fontSize: 10, textTransform: "uppercase",
                  letterSpacing: 0.8, color: colors.muted,
                  marginTop: spacing.sm, marginBottom: 2 },
  detailValue: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface },
  detailValueMono: { fontFamily: "Courier", fontSize: fontSize.xs, color: colors.onSurface },
  stackBox: { backgroundColor: colors.surfaceSecondary,
               borderRadius: radius.sm, padding: spacing.sm,
               borderWidth: 1, borderColor: colors.border, marginTop: 2 },
  stackText: { fontFamily: "Courier", fontSize: fontSize.xs, color: colors.onSurface },
  modalFooter: { flexDirection: "row", justifyContent: "flex-end", marginTop: spacing.md },
  copyBtn: { flexDirection: "row", alignItems: "center", gap: 6,
              backgroundColor: colors.brand,
              paddingHorizontal: spacing.md, paddingVertical: 10,
              borderRadius: radius.md },
  copyBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: "#fff" },
});
