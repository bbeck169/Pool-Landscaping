import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, FlatList, TextInput, RefreshControl, Pressable, Platform, Alert, Modal, ScrollView } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { writeCache, readCache } from "@/src/services/readCache";
// Phase K40 · Feb-2026 — ``@/src/utils/storage`` no longer needed;
// K40 removed the AsyncStorage persistence for status + portal filters.
// (Import stripped by K40.)
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { ImportExport } from "@/src/components/ImportExport";
import { useBulkSelect, BulkCheckbox, BulkActionBar } from "@/src/components/bulk-select/BulkSelectToolkit";
import RestoreCustomerButton from "@/src/components/customers/RestoreCustomerButton";
import PortalOnboardingHealthTile from "@/src/components/customers/PortalOnboardingHealthTile";

export default function Customers() {
  const router = useRouter();
  const { showToast } = useToast();
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

  // P43c corrected — Portal status tri-state ("" = any, "activated" = Signed in, "not_activated" = Never signed in).
  const [portalFilter, setPortalFilter] = useState<"" | "activated" | "not_activated">("");
  const [portalActivatedCount, setPortalActivatedCount] = useState<number | null>(null);
  const [portalNotActivatedCount, setPortalNotActivatedCount] = useState<number | null>(null);

  // P43b — Missing address filter.
  const [missingAddressFilter, setMissingAddressFilter] = useState(false);
  const [missingAddressCount, setMissingAddressCount] = useState<number | null>(null);

  // P44 — No payment on file filter + row action.
  const [noPaymentFilter, setNoPaymentFilter] = useState(false);
  const [noPaymentCount, setNoPaymentCount] = useState<number | null>(null);
  const [sendingPaymentLink, setSendingPaymentLink] = useState<Set<string>>(new Set());

  // P45 — Additional consolidated filters.
  const [missingEmailFilter, setMissingEmailFilter] = useState(false);
  const [missingEmailCount, setMissingEmailCount] = useState<number | null>(null);
  const [missingPhoneFilter, setMissingPhoneFilter] = useState(false);
  const [missingPhoneCount, setMissingPhoneCount] = useState<number | null>(null);
  const [includeMerged, setIncludeMerged] = useState(false);
  const [pendingMergeCandidates, setPendingMergeCandidates] = useState(false);
  const [pendingMergeCount, setPendingMergeCount] = useState<number | null>(null);
  const [moreFiltersOpen, setMoreFiltersOpen] = useState(false);

  // Temp-password parity — "Never logged in" filter.
  const [neverLoggedInFilter, setNeverLoggedInFilter] = useState(false);
  const [neverLoggedInCount, setNeverLoggedInCount] = useState<number | null>(null);

  // Dispatch A — Portal Onboarding Tile: "portal_invited=any" filter for chase-invites.
  const [portalInvitedFilter, setPortalInvitedFilter] = useState(false);

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
      // P43c corrected — Portal status filter (portal_activated param).
      if (portalFilter === "activated") qp.set("portal_activated", "true");
      else if (portalFilter === "not_activated") qp.set("portal_activated", "false");
      // P43b — Missing address filter.
      if (missingAddressFilter) qp.set("missing_address", "true");
      // P44 — No payment on file filter.
      if (noPaymentFilter) qp.set("has_payment_method", "false");
      // P45 — Additional consolidated filters.
      if (missingEmailFilter) qp.set("missing_email", "true");
      if (missingPhoneFilter) qp.set("missing_phone", "true");
      if (includeMerged) qp.set("include_merged", "true");
      if (pendingMergeCandidates) qp.set("pending_merge_candidates", "true");
      // Temp-password parity — "Never logged in" filter.
      if (neverLoggedInFilter) qp.set("first_access", "never");
      // Dispatch A — Portal Onboarding Tile: chase-invite audience filter.
      if (portalInvitedFilter) qp.set("portal_invited", "any");
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
  }, [statusFilter, portalFilter, missingAddressFilter, noPaymentFilter, missingEmailFilter, missingPhoneFilter, includeMerged, pendingMergeCandidates, neverLoggedInFilter, portalInvitedFilter]); // eslint-disable-line react-hooks/exhaustive-deps

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
            showToast(`${bulk.count} customer${bulk.count !== 1 ? "s" : ""} removed.`);
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
      showToast(`${n} customer${n === 1 ? "" : "s"} marked inactive.`);
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

  // P43b + P43c + P44 + P45 — Fetch filter counts on mount (parallel, stable badges).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [addrRes, paRes, pnaRes, payRes, emailRes, phoneRes, mergeRes, neverLogRes] = await Promise.all([
        api.get("/customers?count_only=true&missing_address=true").catch(() => null),
        api.get("/customers?count_only=true&portal_activated=true").catch(() => null),
        api.get("/customers?count_only=true&portal_activated=false").catch(() => null),
        api.get("/customers?count_only=true&has_payment_method=false").catch(() => null),
        api.get("/customers?count_only=true&missing_email=true").catch(() => null),
        api.get("/customers?count_only=true&missing_phone=true").catch(() => null),
        api.get("/customers?count_only=true&pending_merge_candidates=true").catch(() => null),
        api.get("/customers?count_only=true&first_access=never").catch(() => null),
      ]);
      if (cancelled) return;
      setMissingAddressCount(addrRes?.count ?? null);
      setPortalActivatedCount(paRes?.count ?? null);
      setPortalNotActivatedCount(pnaRes?.count ?? null);
      setNoPaymentCount(payRes?.count ?? null);
      setMissingEmailCount(emailRes?.count ?? null);
      setMissingPhoneCount(phoneRes?.count ?? null);
      setPendingMergeCount(mergeRes?.count ?? null);
      setNeverLoggedInCount(neverLogRes?.count ?? null);
    })();
    return () => { cancelled = true; };
  }, []);

  // P44 — Send payment link row action.
  const handleSendPaymentLink = async (cust: any) => {
    if (!cust?.id) return;
    setSendingPaymentLink((s) => new Set(s).add(cust.id));
    try {
      const res: any = await api.post(`/customers/${cust.id}/send-card-add-link`, {});
      const to = [res?.email_recipient, res?.sms_recipient].filter(Boolean).join(" and ");
      showToast(to ? `Add-card link sent to ${to}` : "Add-card link sent");
    } catch (e: any) {
      const msg = e?.detail?.code === "RATE_LIMITED"
        ? "Please wait a few minutes before sending another link."
        : (e?.message || "Failed to send link");
      Alert.alert("Error", msg);
    } finally {
      setSendingPaymentLink((s) => { const n = new Set(s); n.delete(cust.id); return n; });
    }
  };

  // P45 — "More filters" trigger summary.
  const activeFilterLabels = useMemo(() => {
    const labels: string[] = [];
    if (missingEmailFilter) labels.push("No email");
    if (missingPhoneFilter) labels.push("No phone");
    if (missingAddressFilter) labels.push("Missing address");
    if (noPaymentFilter) labels.push("No payment");
    if (portalFilter === "activated") labels.push("Signed in");
    if (portalFilter === "not_activated") labels.push("Never signed in");
    if (includeDeleted) labels.push("Deleted");
    if (includeMerged) labels.push("Merged");
    if (pendingMergeCandidates) labels.push("Pending merge");
    if (neverLoggedInFilter) labels.push("Never logged in");
    if (portalInvitedFilter) labels.push("Invited (portal)");
    return labels;
  }, [missingEmailFilter, missingPhoneFilter, missingAddressFilter, noPaymentFilter, portalFilter, includeDeleted, includeMerged, pendingMergeCandidates, neverLoggedInFilter, portalInvitedFilter]);

  const moreFiltersSummary = activeFilterLabels.length === 0
    ? "All"
    : activeFilterLabels.length === 1
      ? activeFilterLabels[0]
      : `${activeFilterLabels[0]} +${activeFilterLabels.length - 1}`;

  const clearAllFilters = () => {
    setMissingEmailFilter(false);
    setMissingPhoneFilter(false);
    setMissingAddressFilter(false);
    setNoPaymentFilter(false);
    setPortalFilter("");
    setIncludeDeleted(false);
    setIncludeMerged(false);
    setPendingMergeCandidates(false);
    setNeverLoggedInFilter(false);
    setPortalInvitedFilter(false);
    setPage(1);
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
      {/* Dispatch A — Portal Onboarding Health Tile (admin-only) */}
      {isAdmin ? (
        <PortalOnboardingHealthTile
          onFilterInvited={() => { setPortalInvitedFilter(true); setPortalFilter(""); setNeverLoggedInFilter(false); }}
          onFilterActivated={() => { setPortalFilter("activated"); setPortalInvitedFilter(false); setNeverLoggedInFilter(false); }}
          onFilterSignedIn={() => { setPortalFilter("activated"); setPortalInvitedFilter(false); setNeverLoggedInFilter(false); }}
          onFilterNever={() => { setNeverLoggedInFilter(true); setPortalFilter("not_activated"); setPortalInvitedFilter(false); }}
        />
      ) : null}
      {/* P45 — Single "More filters" trigger replacing individual chip rows. */}
      <Pressable
        onPress={() => setMoreFiltersOpen(true)}
        style={cs.moreFiltersTrigger}
        testID="customers-more-filters-dropdown"
        accessibilityRole="button"
        accessibilityLabel={`More filters: ${moreFiltersSummary}`}
      >
        <Ionicons name="options-outline" size={16} color={activeFilterLabels.length > 0 ? colors.brand : colors.muted} />
        <Text style={[cs.moreFiltersTriggerText, activeFilterLabels.length > 0 && { color: colors.brand }]}>
          More filters: {moreFiltersSummary}
        </Text>
        {activeFilterLabels.length >= 2 ? (
          <View style={cs.moreFiltersBadge}>
            <Text style={cs.moreFiltersBadgeText}>{activeFilterLabels.length}</Text>
          </View>
        ) : null}
        <Ionicons name="chevron-down" size={14} color={colors.muted} />
      </Pressable>

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
                  {/* P44 — missing card dot (before name) */}
                  {!item.has_card_on_file ? (
                    <View style={cs.missingCardDot} testID={`row-${item.id}-missing-card-dot`} />
                  ) : null}
                  <Text style={[styles.name, item.deleted_at && cs.nameDeleted]} numberOfLines={1} testID={`customer-row-name-${item.id}`}>{item.name}</Text>
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
              {/* P45 — Add card pill in right actions cluster (navy/white) */}
              {isAdmin && !item.has_card_on_file ? (
                <Pressable
                  onPress={() => { handleSendPaymentLink(item); }}
                  disabled={sendingPaymentLink.has(item.id)}
                  style={[cs.addCardPill, sendingPaymentLink.has(item.id) && { opacity: 0.5 }]}
                  testID={`customer-row-add-card-btn-${item.id}`}
                  accessibilityRole="button"
                  accessibilityLabel={`Add card for ${item.name}`}
                  accessibilityHint="Email and SMS a secure link to add a card for auto-pay"
                >
                  <Ionicons name="card-outline" size={10} color="#FFFFFF" />
                  <Text style={cs.addCardPillText}>
                    {sendingPaymentLink.has(item.id) ? "Sending…" : "Add card"}
                  </Text>
                </Pressable>
              ) : null}
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

      {/* P45 — "More filters" sheet (modal) */}
      <Modal
        visible={moreFiltersOpen}
        animationType="slide"
        transparent
        onRequestClose={() => setMoreFiltersOpen(false)}
      >
        <Pressable style={mfStyles.backdrop} onPress={() => setMoreFiltersOpen(false)}>
          <Pressable style={mfStyles.sheet} onPress={(e) => e.stopPropagation()}>
            <View style={mfStyles.sheetHeader}>
              <Text style={mfStyles.sheetTitle}>More filters</Text>
              <View style={{ flexDirection: "row", gap: 12 }}>
                <Pressable
                  onPress={() => { clearAllFilters(); }}
                  testID="customers-more-filters-clear"
                  accessibilityRole="button"
                >
                  <Text style={mfStyles.clearText}>Clear all</Text>
                </Pressable>
                <Pressable onPress={() => setMoreFiltersOpen(false)} accessibilityLabel="Close filters">
                  <Ionicons name="close" size={22} color={colors.onSurface} />
                </Pressable>
              </View>
            </View>

            <ScrollView style={{ maxHeight: 480 }}>
              {/* Group 1: Contact info missing */}
              <Text style={mfStyles.groupLabel}>Contact info missing</Text>
              {/* No email */}
              <Pressable
                style={mfStyles.checkRow}
                onPress={() => { setMissingEmailFilter((v) => !v); setPage(1); }}
                testID="filter-chip-missing-email"
                accessibilityRole="checkbox"
                accessibilityState={{ checked: missingEmailFilter }}
              >
                <Ionicons name={missingEmailFilter ? "checkbox" : "square-outline"} size={20} color={missingEmailFilter ? colors.brand : colors.muted} />
                <Text style={mfStyles.checkLabel}>No email</Text>
                {missingEmailCount != null ? <Text style={mfStyles.countBadge}>({missingEmailCount})</Text> : null}
              </Pressable>
              {/* No phone */}
              <Pressable
                style={mfStyles.checkRow}
                onPress={() => { setMissingPhoneFilter((v) => !v); setPage(1); }}
                testID="filter-chip-missing-phone"
                accessibilityRole="checkbox"
                accessibilityState={{ checked: missingPhoneFilter }}
              >
                <Ionicons name={missingPhoneFilter ? "checkbox" : "square-outline"} size={20} color={missingPhoneFilter ? colors.brand : colors.muted} />
                <Text style={mfStyles.checkLabel}>No phone number</Text>
                {missingPhoneCount != null ? <Text style={mfStyles.countBadge}>({missingPhoneCount})</Text> : null}
              </Pressable>
              {/* Missing address */}
              <Pressable
                style={mfStyles.checkRow}
                onPress={() => { setMissingAddressFilter((v) => !v); setPage(1); }}
                testID="customers-missing-address-filter"
                accessibilityRole="checkbox"
                accessibilityState={{ checked: missingAddressFilter }}
              >
                <Ionicons name={missingAddressFilter ? "checkbox" : "square-outline"} size={20} color={missingAddressFilter ? colors.brand : colors.muted} />
                <Text style={mfStyles.checkLabel}>Missing address</Text>
                {missingAddressCount != null ? <Text style={mfStyles.countBadge} testID="customers-missing-address-count">({missingAddressCount})</Text> : null}
              </Pressable>

              {/* Group 2: Payment */}
              <Text style={mfStyles.groupLabel}>Payment</Text>
              <Pressable
                style={mfStyles.checkRow}
                onPress={() => { setNoPaymentFilter((v) => !v); setPage(1); }}
                testID="customers-no-payment-filter"
                accessibilityRole="checkbox"
                accessibilityState={{ checked: noPaymentFilter }}
              >
                <Ionicons name={noPaymentFilter ? "checkbox" : "square-outline"} size={20} color={noPaymentFilter ? colors.brand : colors.muted} />
                <Text style={mfStyles.checkLabel}>No payment on file</Text>
                {noPaymentCount != null ? <Text style={mfStyles.countBadge} testID="customers-no-payment-count">({noPaymentCount})</Text> : null}
              </Pressable>

              {/* Group 3: Portal status — radio group */}
              <Text style={mfStyles.groupLabel}>Portal status</Text>
              <View accessibilityRole="radiogroup" testID="customers-portal-status-filter">
                {([
                  { value: "" as const, label: "Any", count: null, testid: "customers-portal-status-any" },
                  { value: "activated" as const, label: "Signed in", count: portalActivatedCount, testid: "customers-portal-status-activated" },
                  { value: "not_activated" as const, label: "Never signed in", count: portalNotActivatedCount, testid: "customers-portal-status-not-activated" },
                ] as const).map((opt) => {
                  const sel = portalFilter === opt.value;
                  return (
                    <Pressable
                      key={opt.value || "any"}
                      style={mfStyles.checkRow}
                      onPress={() => { setPortalFilter(opt.value); setPage(1); }}
                      testID={opt.testid}
                      accessibilityRole="radio"
                      accessibilityState={{ selected: sel }}
                    >
                      <Ionicons name={sel ? "radio-button-on" : "radio-button-off"} size={20} color={sel ? colors.brand : colors.muted} />
                      <Text style={mfStyles.checkLabel}>{opt.label}</Text>
                      {opt.count != null ? <Text style={mfStyles.countBadge}>({opt.count})</Text> : null}
                    </Pressable>
                  );
                })}
              </View>

              {/* Group 4: Administrative — admin-only */}
              {isAdmin ? (
                <>
                  <Text style={mfStyles.groupLabel}>Administrative</Text>
                  <Pressable
                    style={mfStyles.checkRow}
                    onPress={() => { setIncludeDeleted((v) => !v); setPage(1); }}
                    testID="customers-filter-include-deleted"
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: includeDeleted }}
                  >
                    <Ionicons name={includeDeleted ? "checkbox" : "square-outline"} size={20} color={includeDeleted ? "#B91C1C" : colors.muted} />
                    <Text style={mfStyles.checkLabel}>Show deleted</Text>
                  </Pressable>
                  <Pressable
                    style={mfStyles.checkRow}
                    onPress={() => { setIncludeMerged((v) => !v); setPage(1); }}
                    testID="customers-filter-include-merged"
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: includeMerged }}
                  >
                    <Ionicons name={includeMerged ? "checkbox" : "square-outline"} size={20} color={includeMerged ? colors.brand : colors.muted} />
                    <Text style={mfStyles.checkLabel}>Show merged</Text>
                  </Pressable>
                  <Pressable
                    style={mfStyles.checkRow}
                    onPress={() => { setPendingMergeCandidates((v) => !v); setPage(1); }}
                    testID="customers-filter-pending-merge-candidates"
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: pendingMergeCandidates }}
                  >
                    <Ionicons name={pendingMergeCandidates ? "checkbox" : "square-outline"} size={20} color={pendingMergeCandidates ? colors.brand : colors.muted} />
                    <Text style={mfStyles.checkLabel}>Pending merge candidates</Text>
                    {pendingMergeCount != null ? <Text style={mfStyles.countBadge}>({pendingMergeCount})</Text> : null}
                  </Pressable>

                  {/* Temp-password parity — Never logged in filter */}
                  <Pressable
                    style={mfStyles.checkRow}
                    onPress={() => { setNeverLoggedInFilter((v) => !v); setPage(1); }}
                    testID="customers-filter-never-logged-in"
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: neverLoggedInFilter }}
                  >
                    <Ionicons name={neverLoggedInFilter ? "checkbox" : "square-outline"} size={20} color={neverLoggedInFilter ? colors.brand : colors.muted} />
                    <Text style={mfStyles.checkLabel}>Never logged in</Text>
                    {neverLoggedInCount != null ? <Text style={mfStyles.countBadge}>({neverLoggedInCount})</Text> : null}
                  </Pressable>
                </>
              ) : null}
            </ScrollView>
          </Pressable>
        </Pressable>
      </Modal>

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
  // P44 — Missing card dot.
  missingCardDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#F59E0B",
  },
  addCardPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.sm,
    backgroundColor: "#1E293B",
    borderWidth: 1,
    borderColor: "#0F172A",
  },
  addCardPillText: {
    fontFamily: font.semibold,
    fontSize: 10,
    color: "#FFFFFF",
  },
  // P45 — "More filters" trigger.
  moreFiltersTrigger: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  moreFiltersTriggerText: {
    flex: 1,
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
  moreFiltersBadge: {
    backgroundColor: colors.brand,
    borderRadius: 10,
    minWidth: 20,
    height: 20,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 5,
  },
  moreFiltersBadgeText: {
    fontFamily: font.bold,
    fontSize: 10,
    color: "#FFFFFF",
  },
});


// P45 — More Filters sheet styles.
const mfStyles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(15,23,42,0.45)",
    justifyContent: "flex-end",
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    paddingBottom: 34,
    borderWidth: 1,
    borderColor: colors.border,
    borderBottomWidth: 0,
    maxHeight: "80%",
  },
  sheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  sheetTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
  },
  clearText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
  groupLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.xs,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.8,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
    paddingBottom: spacing.xs,
  },
  checkRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: spacing.lg,
    paddingVertical: 10,
  },
  checkLabel: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  countBadge: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
});
