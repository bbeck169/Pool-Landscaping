import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, TextInput, RefreshControl, Pressable, Platform, Alert, Modal } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { writeCache, readCache } from "@/src/services/readCache";
// Phase K40 · Feb-2026 — ``@/src/utils/storage`` no longer needed;
// K40 removed the AsyncStorage persistence for status + portal filters.
// (Import stripped by K40.)
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { ImportExport } from "@/src/components/ImportExport";
import { useBulkSelect, BulkCheckbox, BulkActionBar } from "@/src/components/bulk-select/BulkSelectToolkit";
import RestoreCustomerButton from "@/src/components/customers/RestoreCustomerButton";
import { formatCustomerName } from "@/src/utils/formatCustomerName";

export default function Customers() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  // Feb-2026 · Bulk-mark-inactive — manager is included per the dispatch
  // spec (super_admin / admin / manager permitted; tech / customer blocked).
  const isAdminOrManager = isAdmin || user?.role === "manager";
  // Ship 2 · Soft-deleted filter — admin+ can toggle
  const canManageDeleted = isAdmin || user?.role === "owner";
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  // Feb-2026 · P35 — mobile infinite-scroll pagination. Initial load
  // fetches page 1 (100 rows); ``onEndReached`` on the FlatList pulls
  // the next page and appends. Total pages is read from the response
  // envelope so we can short-circuit at the tail.
  const _PAGE_SIZE = 100;
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loadingMore, setLoadingMore] = useState(false);
  // Bulk-inactive confirm modal state (mobile mirror of the web modal).
  const [inactiveModalOpen, setInactiveModalOpen] = useState(false);
  const [inactiveBusy, setInactiveBusy] = useState(false);

  // Phase F6b — Active/Inactive/All segmented control.
  // Phase J2 / H4 — Waitlist 4th segment.
  //
  // Phase K40 · Feb-2026 — site-wide "no persistence across page
  // loads" rule. Customers is the ONE explicit exception to the
  // "default to All" policy: statusFilter still defaults to
  // ``"active"`` on every mount. The previous AsyncStorage read
  // (F6b / H4) has been REMOVED so a fresh open of the tab always
  // lands the operator on the Active cohort. Web parity: same
  // behaviour landed simultaneously in CustomersList.jsx.
  const [statusFilter, setStatusFilter] = useState<"active" | "inactive" | "all" | "waitlist">("active");

  // Phase G4b — Portal activation filter. K40 — no persistence.
  const [portalFilter, setPortalFilter] = useState<"all" | "activated" | "not_activated">("all");

  const visibleIds = useMemo(() => items.map((i) => i.id), [items]);
  const bulk = useBulkSelect(visibleIds);

  const load = useCallback(async (s: string, targetPage: number = 1, showDeleted: boolean = false) => {
    try {
      const qp = new URLSearchParams();
      if (s) qp.set("search", s);
      qp.set("page", String(targetPage));
      qp.set("page_size", String(_PAGE_SIZE));
      if (showDeleted && canManageDeleted) qp.set("include_deleted", "true");
      // Phase F6b — Active/Inactive/All filter + H4 Waitlist.
      if (statusFilter === "waitlist") {
        qp.set("waitlisted", "true");
      } else if (statusFilter !== "all") {
        qp.set("is_active", String(statusFilter === "active"));
      }
      // Phase G4b — Portal activation filter.
      if (portalFilter !== "all") qp.set("portal_status", portalFilter);
      const res: any = await api.get(`/customers?${qp.toString()}`);
      const rows = Array.isArray(res) ? res : (res?.items || []);
      const tp = Number.isFinite(res?.total_pages)
        ? res.total_pages
        : (rows.length ? 1 : 0);
      setTotalPages(tp);
      setPage(targetPage);
      setItems((prev) => targetPage <= 1 ? rows : [...prev, ...rows]);
      // Phase O5 · Cache first page for offline access.
      if (targetPage <= 1 && rows.length) {
        writeCache("customers:page1", rows).catch(() => {});
      }
    } catch {
      // Phase O5 · Offline fallback: read from SQLite cache.
      if (targetPage <= 1) {
        const cached = await readCache<any[]>("customers:page1");
        if (cached) { setItems(cached); setTotalPages(1); setPage(1); }
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
      setLoadingMore(false);
    }
  }, [statusFilter, portalFilter]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadMore = useCallback(() => {
    if (loadingMore) return;
    if (page >= totalPages) return;
    setLoadingMore(true);
    load(search, page + 1, includeDeleted);
  }, [loadingMore, page, totalPages, search, load, includeDeleted]);

  useFocusEffect(useCallback(() => { load(search, 1, includeDeleted); }, [load, search, includeDeleted]));

  const exitSelectMode = () => { setSelectMode(false); bulk.clear(); };

  const bulkDelete = async () => {
    Alert.alert(`Delete ${bulk.count} customer${bulk.count !== 1 ? "s" : ""}?`, "This action cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete", style: "destructive", onPress: async () => {
          try {
            await api.post("/customers/bulk-delete", { ids: [...bulk.selected] });
            Alert.alert("Deleted", `${bulk.count} customer${bulk.count !== 1 ? "s" : ""} removed.`);
            exitSelectMode();
            load(search, 1, includeDeleted);
          } catch (e: any) { Alert.alert("Error", e?.message || "Delete failed"); }
        },
      },
    ]);
  };

  // Feb-2026 · Bulk mark-inactive. Plain Confirm / Cancel modal per
  // user feedback — no typed-word gate.
  const openInactiveModal = () => {
    setInactiveModalOpen(true);
  };

  const doBulkInactive = async () => {
    const ids = [...bulk.selected];
    if (!ids.length) return;
    // Snapshot for rollback.
    const pre = new Map(items
      .filter((i) => bulk.selected.has(i.id))
      .map((i) => [i.id, { is_active: i.is_active, status: i.status }]));
    setInactiveBusy(true);
    // Optimistic — drop from current list (mobile shows a flat list).
    setItems((prev) => prev.map((r) => bulk.selected.has(r.id)
        ? { ...r, is_active: false, status: "inactive" }
        : r));
    try {
      const res = await api.patch("/customers/bulk-status", {
        customer_ids: ids, target_status: "inactive",
      });
      const n = res?.modified ?? res?.matched ?? 0;
      Alert.alert(
        "Marked inactive",
        `${n} customer${n === 1 ? "" : "s"} marked inactive.`,
      );
      setInactiveModalOpen(false);
      exitSelectMode();
      load(search, 1, includeDeleted);
    } catch (e: any) {
      // Rollback: restore pre-flip state, notify.
      setItems((prev) => prev.map((r) =>
        pre.has(r.id) ? { ...r, ...(pre.get(r.id) as object) } : r,
      ));
      Alert.alert("Error", e?.message || "Bulk mark inactive failed");
    } finally {
      setInactiveBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <Header
        title={selectMode ? `${bulk.count} selected` : "Customers"}
        right={
          selectMode ? (
            <Pressable onPress={exitSelectMode} testID="bulk-exit-select">
              <Text style={{ fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand }}>Cancel</Text>
            </Pressable>
          ) : (
            <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs }}>
              {isAdmin ? <ImportExport entity="customers" label="customers" exportPath="/export/customers" importPath="/import/customers" onDone={() => load(search, 1, includeDeleted)} /> : null}
              <IconButton icon="add" onPress={() => router.push("/customer/new")} testID="add-customer-button" />
            </View>
          )
        }
      />
      {/* Phase F6b — Active / Inactive / All + H4 Waitlist segmented control */}
      <View style={cs.segmentRow} testID="customer-status-filter">
        {(["active", "inactive", "waitlist", "all"] as const).map((seg) => (
          <Pressable
            key={seg}
            onPress={() => {
              setStatusFilter(seg);
              // Phase K40 — no persistence; page resets on filter change.
              setPage(1);
            }}
            style={[cs.segment, statusFilter === seg && cs.segmentActive]}
            testID={`customer-status-${seg}`}
            accessibilityRole="button"
          >
            <Text style={[cs.segmentText, statusFilter === seg && cs.segmentTextActive]}>
              {seg === "active" ? "Active" : seg === "inactive" ? "Inactive" : seg === "waitlist" ? "Waitlist" : "All"}
            </Text>
          </Pressable>
        ))}
      </View>
      {/* Phase G4b — Portal activation filter chips */}
      <View style={cs.portalRow} testID="customer-portal-filter">
        <Ionicons name="key-outline" size={13} color={colors.muted} style={{ marginRight: 4 }} />
        {(["all", "activated", "not_activated"] as const).map((opt) => (
          <Pressable
            key={opt}
            onPress={() => {
              setPortalFilter(opt);
              // Phase K40 — no persistence; page resets on filter change.
              setPage(1);
            }}
            style={[cs.portalChip, portalFilter === opt && cs.portalChipActive]}
            testID={`customer-portal-${opt}`}
            accessibilityRole="button"
          >
            <Text style={[cs.portalChipText, portalFilter === opt && cs.portalChipTextActive]}>
              {opt === "all" ? "All" : opt === "activated" ? "Activated" : "Not activated"}
            </Text>
          </Pressable>
        ))}
      </View>
      <View style={styles.searchWrap}>
        <View style={styles.searchBox}>
          {selectMode ? (
            <BulkCheckbox
              checked={bulk.allSelected}
              indeterminate={bulk.indeterminate}
              onPress={bulk.toggleAll}
              testID="bulk-select-all-customers"
            />
          ) : (
            <Ionicons name="search" size={18} color={colors.muted} />
          )}
          <TextInput
            testID="customer-search-input"
            style={styles.searchInput}
            placeholder="Search customers"
            placeholderTextColor={colors.muted}
            value={search}
            onChangeText={(t) => { setSearch(t); load(t); }}
            autoCapitalize="none"
          />
        </View>
        {/* Ship 2 · "Show deleted" toggle chip — admin+ only */}
        {canManageDeleted ? (
          <Pressable
            style={[cs.deletedChip, includeDeleted && cs.deletedChipActive]}
            onPress={() => setIncludeDeleted((v) => !v)}
            testID="customers-filter-include-deleted"
          >
            <View style={[cs.deletedDot, includeDeleted && cs.deletedDotActive]} />
            <Text style={[cs.deletedChipText, includeDeleted && cs.deletedChipTextActive]}>
              Show deleted
            </Text>
          </Pressable>
        ) : null}
      </View>
      {loading ? (
        <Loading testID="customers-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="people-outline" title="No customers found" subtitle="Add your first customer to get started." testID="customers-empty" />
      ) : (
        <FlatList
          testID="customers-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: selectMode ? 100 : spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(search, 1, includeDeleted); }} />}
          onEndReached={loadMore}
          onEndReachedThreshold={0.4}
          renderItem={({ item }) => (
            <Pressable
              style={[styles.row, bulk.selected.has(item.id) && styles.rowSelected, item.deleted_at && cs.rowDeleted]}
              onPress={() => selectMode ? bulk.toggleOne(item.id) : router.push(`/customer/${item.id}`)}
              onLongPress={() => { if (!selectMode) { setSelectMode(true); bulk.toggleOne(item.id); } }}
              testID={`customer-row-${item.id}`}
            >
              {selectMode ? (
                <BulkCheckbox checked={bulk.selected.has(item.id)} onPress={() => bulk.toggleOne(item.id)} testID={`bulk-check-${item.id}`} />
              ) : null}
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{item.name?.charAt(0)?.toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <Text style={[styles.name, item.deleted_at && cs.nameDeleted]} numberOfLines={1}>{item.name}</Text>
                  {item.deleted_at && canManageDeleted ? (
                    <RestoreCustomerButton
                      customer={item}
                      onRestored={(res) => {
                        Alert.alert("Restored", res?.was_anonymized ? "Customer restored (PII stays scrubbed)" : "Customer restored");
                        load(search, 1, includeDeleted);
                      }}
                      onError={(msg) => Alert.alert("Restore failed", msg)}
                    />
                  ) : null}
                </View>
                <Text style={styles.sub} numberOfLines={1}>{item.address || item.phone || item.email || "—"}</Text>
              </View>
              {!selectMode ? <Ionicons name="chevron-forward" size={18} color={colors.muted} /> : null}
            </Pressable>
          )}
        />
      )}
      <BulkActionBar
        count={bulk.count}
        onClear={exitSelectMode}
        actions={[
          ...(isAdminOrManager ? [{
            key: "bulk-mark-inactive-customers",
            label: "Mark inactive",
            icon: "person-remove-outline" as const,
            onPress: openInactiveModal,
          }] : []),
          { key: "bulk-delete-customers", label: "Delete", icon: "trash-outline", tone: "danger", onPress: bulkDelete },
        ]}
      />

      {/* Feb-2026 · Bulk-mark-inactive hard-confirm modal (mobile). */}
      <Modal
        visible={inactiveModalOpen}
        animationType="fade"
        transparent
        onRequestClose={() => setInactiveModalOpen(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard} testID="bulk-mark-inactive-modal">
            <Text style={styles.modalTitle}>
              Mark {bulk.count} customer{bulk.count === 1 ? "" : "s"} inactive?
            </Text>
            <Text style={styles.modalSub}>
              These customers will move to the Inactive tab and their
              scheduled jobs may be cancelled.
            </Text>

            {/* First 5 preview */}
            <View style={{ marginTop: spacing.sm }}
                  testID="bulk-mark-inactive-preview-list">
              {items
                .filter((i) => bulk.selected.has(i.id))
                .slice(0, 5)
                .map((i) => (
                  <Text key={i.id} style={styles.modalListRow}
                        numberOfLines={1}>
                    · {i.name || i.email || i.id}
                  </Text>
                ))}
              {bulk.count > 5 ? (
                <Text style={styles.modalListMore}>
                  … and {bulk.count - 5} more
                </Text>
              ) : null}
            </View>

            <View style={styles.modalActions}>
              <Pressable
                testID="bulk-mark-inactive-cancel"
                onPress={() => setInactiveModalOpen(false)}
                style={[styles.modalBtn, styles.modalBtnGhost]}
              >
                <Text style={styles.modalBtnGhostText}>Cancel</Text>
              </Pressable>
              <Pressable
                testID="bulk-mark-inactive-confirm"
                disabled={inactiveBusy}
                onPress={doBulkInactive}
                style={[
                  styles.modalBtn,
                  styles.modalBtnDanger,
                  inactiveBusy && { opacity: 0.4 },
                ]}
              >
                <Text style={styles.modalBtnDangerText}>
                  {inactiveBusy ? "Marking…" : `Mark ${bulk.count} inactive`}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  searchWrap: { paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48,
  },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.lg, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  rowSelected: { borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.brand },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  // Feb-2026 · Bulk-mark-inactive modal.
  modalBackdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center", justifyContent: "center", padding: spacing.lg,
  },
  modalCard: {
    width: "100%", maxWidth: 480,
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.lg,
  },
  modalTitle: {
    fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface,
  },
  modalSub: {
    fontFamily: font.regular, fontSize: fontSize.sm,
    color: colors.muted, marginTop: spacing.xs,
  },
  modalListRow: {
    fontFamily: font.regular, fontSize: fontSize.sm,
    color: colors.onSurface, marginTop: 2,
  },
  modalListMore: {
    fontFamily: font.regular, fontSize: fontSize.xs,
    color: colors.muted, fontStyle: "italic", marginTop: 4,
  },
  modalLabel: {
    fontFamily: font.semibold, fontSize: fontSize.xs,
    color: colors.onSurface, marginTop: spacing.md,
  },
  modalInput: {
    marginTop: spacing.xs,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    fontFamily: font.regular, fontSize: fontSize.base,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  modalActions: {
    flexDirection: "row", justifyContent: "flex-end",
    gap: spacing.sm, marginTop: spacing.lg,
  },
  modalBtn: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: radius.md,
  },
  modalBtnGhost: {
    backgroundColor: colors.surfaceSecondary,
  },
  modalBtnGhostText: {
    fontFamily: font.semibold, fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  modalBtnDanger: { backgroundColor: "#B45309" },
  modalBtnDangerText: {
    fontFamily: font.bold, fontSize: fontSize.sm, color: "#FFFFFF",
  },
});

// Ship 2 · extra styles for soft-deleted UX
const cs = StyleSheet.create({
  deletedChip: {
    flexDirection: "row",
    alignItems: "center",
    alignSelf: "flex-start",
    gap: 6,
    marginTop: spacing.sm,
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  deletedChipActive: {
    backgroundColor: "#FEE2E2",
    borderColor: "#FCA5A5",
  },
  deletedDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#94A3B8",
  },
  deletedDotActive: {
    backgroundColor: "#B91C1C",
  },
  deletedChipText: {
    fontFamily: font.semibold,
    fontSize: fontSize.xs,
    color: colors.onSurfaceSecondary,
  },
  deletedChipTextActive: {
    color: "#991B1B",
  },
  rowDeleted: {
    opacity: 0.6,
  },
  nameDeleted: {
    textDecorationLine: "line-through",
  },
  segmentRow: {
    flexDirection: "row",
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
    padding: 3,
  },
  segment: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 7,
    borderRadius: radius.md - 2,
  },
  segmentActive: {
    backgroundColor: colors.surface,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.08,
    shadowRadius: 2,
    elevation: 2,
  },
  segmentText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  segmentTextActive: {
    color: colors.onSurface,
  },
  portalRow: {
    flexDirection: "row",
    alignItems: "center",
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    gap: 4,
  },
  portalChip: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceTertiary,
  },
  portalChipActive: {
    backgroundColor: "#0D9488",
  },
  portalChipText: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
  },
  portalChipTextActive: {
    color: "#fff",
  },
});
