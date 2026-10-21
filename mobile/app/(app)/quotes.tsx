import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl, Pressable,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/ToastProvider";
import { writeCache, readCache } from "@/src/services/readCache";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Loading, EmptyState, StatusChip } from "@/src/components/ui";
import { Header, FilterRow, IconButton, NotificationBell } from "@/src/components/widgets";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import {
  canUserDeclineOrReopenQuote,
  shouldShowDeclineButton,
  shouldShowReopenButton,
} from "@/src/utils/quoteLifecycle";
import QuotesBulkToolbar, { bulkOutcomeMessage } from "@/src/components/quotes/QuotesBulkToolbar";

// ── Phase 3 lifecycle view filter (mirrors web QuotesList.jsx) ────
const VIEW_FILTERS = [
  { key: "open",      label: "Open" },
  { key: "converted", label: "Converted" },
  { key: "declined",  label: "Declined" },
  { key: "all",       label: "All" },
];

// Legacy doc-type filter for non-admin (unchanged)
const DOC_TYPE_FILTERS = [
  { key: "all", label: "All" },
  { key: "quote", label: "Quotes" },
  { key: "invoice", label: "Invoices" },
];

export default function Quotes() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const roleCanLifecycle = canUserDeclineOrReopenQuote(user?.role);
  const router = useRouter();
  const { showToast } = useToast();
  const [items, setItems] = useState<any[]>([]);
  // Phase 3: default to "open" view for lifecycle filter
  const [view, setView] = useState("open");
  // Legacy doc_type filter for non-admin users
  const [docTypeFilter, setDocTypeFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const lifecycleBusyRef = useRef<string | null>(null);

  // ── TD-96-g1-mobile · `?lead=<lid>` filter (web QuotesList 00888d0af) ──
  // `lead` → `lead_id` on both role branches (BE scopes; D4). `view` param
  // seeds the lifecycle view (LeadLinkedQuotesPanel sends view:"all", D1).
  // Badge name via GET /leads/{lid}, short-id fallback (D2). Filtered
  // fetches never touch the offline cache (keyed by view / doc_type only).
  const params = useLocalSearchParams<{ lead?: string; view?: string }>();
  const leadFilter = typeof params?.lead === "string" && params.lead ? params.lead : null;
  const viewParam = typeof params?.view === "string" ? params.view : "";
  useEffect(() => {
    if (VIEW_FILTERS.some((f) => f.key === viewParam)) setView(viewParam);
  }, [viewParam]);
  const [leadName, setLeadName] = useState<string | null>(null);
  useEffect(() => {
    setLeadName(null);
    if (!leadFilter) return;
    let alive = true;
    api.get(`/leads/${encodeURIComponent(leadFilter)}`)
      .then((r: any) => { if (alive) setLeadName(r?.name || null); })
      .catch(() => {});
    return () => { alive = false; };
  }, [leadFilter]);

  // ── Phase 4b · Bulk selection (web parity f61449679) ─────────────
  // Same role set as web ``canUserLifecycle`` / server
  // ``require_admin_or_manager``. Techs never see checkboxes/toolbar.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  useEffect(() => {
    // Drop selections for rows no longer in the list (filter change / refetch).
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev;
      const visible = new Set(items.map((r) => r.id));
      const next = new Set([...prev].filter((id) => visible.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [items]);
  const toggleRowSelect = (id: string) =>
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  const clearSelection = () => setSelectedIds(new Set());

  const load = useCallback(async (v: string, dtf: string) => {
    try {
      let q: string;
      if (isAdmin) {
        // Phase 3: admin uses lifecycle view filter
        q = `?view=${v}`;
      } else {
        // Non-admin: legacy doc_type filter
        q = dtf === "all" ? "" : `?doc_type=${dtf}`;
      }
      if (leadFilter) q += `${q ? "&" : "?"}lead_id=${encodeURIComponent(leadFilter)}`;
      const data = await api.get(`/quotes${q}`);
      setItems(Array.isArray(data) ? data : []);
      if (!leadFilter) writeCache(`quotes:${isAdmin ? v : dtf}`, data).catch(() => {});
    } catch {
      if (leadFilter) { setItems([]); return; }
      const cached = await readCache<any[]>(`quotes:${isAdmin ? v : dtf}`);
      if (cached) setItems(cached);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isAdmin, leadFilter]);

  useFocusEffect(
    useCallback(() => {
      load(view, docTypeFilter);
    }, [view, docTypeFilter, load])
  );

  const refresh = () => {
    setRefreshing(true);
    load(view, docTypeFilter);
  };

  const runBulk = async (route: string, verb: string) => {
    const ids = Array.from(selectedIds);
    if (!ids.length || bulkBusy) return;
    setBulkBusy(true);
    try {
      const res = await api.post(`/quotes/${route}`, { quote_ids: ids });
      const { message, tone } = bulkOutcomeMessage(verb, res?.succeeded, res?.skipped);
      showToast(message, tone);
      // Clear only succeeded ids so skipped rows stay selected for retry.
      setSelectedIds((prev) => {
        const next = new Set(prev);
        for (const id of res?.succeeded || []) next.delete(id);
        return next;
      });
    } catch (e: any) {
      showToast(e?.message || `Bulk ${verb} failed.`, "error");
    } finally {
      setBulkBusy(false);
      load(view, docTypeFilter);
    }
  };

  // ── Phase 3 Decline handler ─────────────────────────────────────
  const handleRowDecline = (item: any) => {
    if (lifecycleBusyRef.current) return;
    Alert.alert(
      "Decline Quote",
      "Decline this quote? You can reopen it later.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Decline",
          style: "destructive",
          onPress: async () => {
            lifecycleBusyRef.current = item.id;
            try {
              await api.post(`/quotes/${item.id}/decline`, {});
              showToast("Quote declined", "success");
            } catch (e: any) {
              const code = e?.detail?.code;
              if (code === "already_converted") {
                const invId = e?.detail?.invoice_id;
                showToast(
                  `Already converted to invoice${invId ? ` ${invId}` : ""}`,
                  "info",
                );
              } else if (code === "already_declined") {
                showToast("Already declined", "info");
              } else {
                showToast(e?.message || "Decline failed", "error");
              }
            } finally {
              lifecycleBusyRef.current = null;
              refresh();
            }
          },
        },
      ],
    );
  };

  // ── Phase 3 Reopen handler ──────────────────────────────────────
  const handleRowReopen = (item: any) => {
    if (lifecycleBusyRef.current) return;
    Alert.alert(
      "Reopen Quote",
      "Reopen this quote?",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Reopen",
          onPress: async () => {
            lifecycleBusyRef.current = item.id;
            try {
              await api.post(`/quotes/${item.id}/reopen`, {});
              showToast("Quote reopened", "success");
            } catch (e: any) {
              const code = e?.detail?.code;
              if (code === "not_declined") {
                showToast("Not currently declined", "info");
              } else {
                showToast(e?.message || "Reopen failed", "error");
              }
            } finally {
              lifecycleBusyRef.current = null;
              refresh();
            }
          },
        },
      ],
    );
  };

  // Row-level visibility helpers
  const canDeclineRow = (item: any) =>
    shouldShowDeclineButton({
      isInvoice: item.doc_type === "invoice",
      docStatus: item.status,
      convertedInvoiceId: item.converted_invoice_id,
      canDecline: roleCanLifecycle,
    });
  const canReopenRow = (item: any) =>
    shouldShowReopenButton({
      isInvoice: item.doc_type === "invoice",
      docStatus: item.status,
      canReopen: roleCanLifecycle,
    });

  return (
    <View style={styles.root}>
      <Header
        title={isAdmin ? "Quotes & Invoices" : "My Invoices"}
        right={
          isAdmin ? (
            <IconButton icon="add" onPress={() => router.push("/quote/new")} testID="add-quote-button" />
          ) : (
            <NotificationBell />
          )
        }
      />
      {/* Phase 3: admin sees lifecycle view filter; non-admin sees doc_type filter */}
      {isAdmin ? (
        <FilterRow
          options={VIEW_FILTERS}
          value={view}
          onChange={setView}
          testID="quotes-list-filter"
        />
      ) : (
        <FilterRow
          options={DOC_TYPE_FILTERS}
          value={docTypeFilter}
          onChange={setDocTypeFilter}
          testID="quotes-filter"
        />
      )}
      {leadFilter ? (
        <View style={styles.leadBar} testID="quotes-filter-lead-bar">
          <Text style={styles.leadBarLabel}>Lead</Text>
          <View style={styles.leadBadge}>
            <Text style={styles.leadBadgeText} numberOfLines={1} testID="quotes-filter-lead-badge">
              {leadName || `Lead ${leadFilter.slice(0, 8)}`}
            </Text>
          </View>
          <Pressable
            onPress={() => router.setParams({ lead: undefined } as any)} hitSlop={8}
            style={styles.leadClear} testID="quotes-filter-lead-clear"
            accessibilityRole="button" accessibilityLabel="Clear lead filter"
          >
            <Text style={styles.leadClearText}>Clear</Text>
            <Ionicons name="close" size={12} color="#374151" />
          </Pressable>
        </View>
      ) : null}
      {loading ? (
        <Loading testID="quotes-loading" />
      ) : items.length === 0 ? (
        <EmptyState
          icon="document-text-outline"
          title={isAdmin ? "No documents yet" : "No invoices yet"}
          subtitle={isAdmin ? "Create a quote or invoice to get started." : "Your invoices will appear here."}
          testID="quotes-empty"
        />
      ) : (
        <FlatList
          testID="quotes-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: selectedIds.size ? 160 : spacing["3xl"] }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
          renderItem={({ item }) => (
            <Pressable
              style={styles.card}
              onPress={() => router.push(`/quote/${item.id}`)}
              testID={`quote-card-${item.id}`}
            >
              <View style={styles.topRow}>
                {roleCanLifecycle ? (
                  <Pressable
                    onPress={() => toggleRowSelect(item.id)}
                    hitSlop={10}
                    style={[styles.checkbox, selectedIds.has(item.id) && styles.checkboxOn]}
                    testID={`quote-row-select-${item.id}`}
                    accessibilityRole="checkbox"
                    accessibilityState={{ checked: selectedIds.has(item.id) }}
                    accessibilityLabel={`Select ${item.title || "quote"}`}
                  >
                    {selectedIds.has(item.id) ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                  </Pressable>
                ) : null}
                <View style={[styles.typeBadge, { flex: 1 }]}>
                  <Ionicons
                    name={item.doc_type === "invoice" ? "receipt-outline" : "document-text-outline"}
                    size={16}
                    color={colors.brand}
                  />
                  <Text style={styles.typeText}>
                    {item.doc_type === "invoice" ? "Invoice" : "Quote"}
                  </Text>
                </View>
                <StatusChip status={item.payment_status === "paid" ? "paid" : item.status} />
              </View>
              <Text style={styles.title} numberOfLines={1}>{item.title}</Text>
              <Text style={styles.customer}>{formatCustomerName(item)}</Text>
              <View style={styles.footer}>
                <Text style={styles.total}>{money(item.total)}</Text>
                <View style={styles.rowActions}>
                  {/* Phase 3: inline Decline button */}
                  {canDeclineRow(item) ? (
                    <Pressable
                      testID={`quote-row-decline-${item.id}`}
                      style={styles.declineBtn}
                      onPress={() => handleRowDecline(item)}
                      hitSlop={8}
                    >
                      <Ionicons name="close-circle-outline" size={16} color="#B91C1C" />
                      <Text style={styles.declineBtnText}>Decline</Text>
                    </Pressable>
                  ) : null}
                  {/* Phase 3: inline Reopen button */}
                  {canReopenRow(item) ? (
                    <Pressable
                      testID={`quote-row-reopen-${item.id}`}
                      style={styles.reopenBtn}
                      onPress={() => handleRowReopen(item)}
                      hitSlop={8}
                    >
                      <Ionicons name="refresh-outline" size={16} color={colors.brand} />
                      <Text style={styles.reopenBtnText}>Reopen</Text>
                    </Pressable>
                  ) : null}
                  <Ionicons name="chevron-forward" size={18} color={colors.muted} />
                </View>
              </View>
            </Pressable>
          )}
        />
      )}
      {roleCanLifecycle ? (
        <QuotesBulkToolbar
          selectedCount={selectedIds.size}
          busy={bulkBusy}
          onAccept={() => runBulk("bulk-accept", "accepted")}
          onDecline={() => runBulk("bulk-decline", "declined")}
          onDelete={() => runBulk("bulk-delete", "deleted")}
          onClear={clearSelection}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  leadBar: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  leadBarLabel: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  leadBadge: { maxWidth: "60%", paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: radius.pill, backgroundColor: "#DBEAFE", borderWidth: 1, borderColor: "#93C5FD" },
  leadBadgeText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#1E40AF" },
  leadClear: { flexDirection: "row", alignItems: "center", gap: 4, minHeight: 32, paddingHorizontal: spacing.sm, borderRadius: radius.pill, backgroundColor: "#F3F4F6", borderWidth: 1, borderColor: "#D1D5DB" },
  leadClearText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#374151" },
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.md,
    gap: 4,
  },
  topRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 4,
  },
  typeBadge: { flexDirection: "row", alignItems: "center", gap: 5 },
  checkbox: {
    width: 22, height: 22, borderRadius: 5, borderWidth: 2, borderColor: colors.border,
    alignItems: "center", justifyContent: "center", marginRight: 10, backgroundColor: colors.surface,
  },
  checkboxOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  typeText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.brand },
  title: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  customer: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted },
  footer: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: spacing.sm,
  },
  total: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  rowActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  declineBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.sm,
    backgroundColor: "#FEE2E2",
    minHeight: 32,
  },
  declineBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.xs,
    color: "#B91C1C",
  },
  reopenBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    minHeight: 32,
  },
  reopenBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.xs,
    color: colors.brand,
  },
});
