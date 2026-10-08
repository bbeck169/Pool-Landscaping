/**
 * Templates Library — Phase 3 (Mobile) · browse screen.
 *
 * Segments: Library (definitions, RBAC-filtered server-side) | My Templates
 * (GET /instances?mine=true grouped Drafts / Finalized). Mirrors web
 * `TemplatesLibraryPage.jsx`. Falls back to the last cached list when
 * offline so techs can still reach their drafts in the field.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, FlatList, TouchableOpacity, ActivityIndicator, RefreshControl } from "react-native";
import { useRouter, useFocusEffect, useLocalSearchParams } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { ApiNetworkError } from "@/src/api";
import { useOnline } from "@/src/offline";
import { Header } from "@/src/components/widgets";
import { useToast } from "@/src/components/ToastProvider";
import { showConfirm } from "@/src/components/ConfirmModal";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import TemplateCard from "@/src/components/templates/TemplateCard";
import TemplateInstanceList from "@/src/components/templates/TemplateInstanceList";
import OfflineIndicator from "@/src/components/templates/OfflineIndicator";
import {
  TEMPLATE_CATEGORIES, listDefinitions, listInstances, createInstance,
  duplicateInstance, deleteInstance, downloadPdf,
} from "@/src/api/templates";
import {
  cacheTemplateList, readTemplateList, getPendingQueue, clearSnapshot,
  removePending, clearInstanceBundle,
} from "@/src/utils/offlineTemplateDrafts";

type Tab = "library" | "mine";
const openPath = (id: string) => `/(app)/templates/${id}` as any;

function Segments({ tab, setTab, mineCount }: { tab: Tab; setTab: (t: Tab) => void; mineCount: number }) {
  const items: { key: Tab; label: string }[] = [
    { key: "library", label: "Library" },
    { key: "mine", label: `My Templates${mineCount ? ` (${mineCount})` : ""}` },
  ];
  return (
    <View style={styles.segment} testID="templates-library-tabs">
      {items.map((t) => (
        <TouchableOpacity key={t.key} onPress={() => setTab(t.key)} style={[styles.segBtn, tab === t.key && styles.segBtnActive]} testID={`templates-tab-${t.key}`}>
          <Text style={[styles.segText, tab === t.key && styles.segTextActive]}>{t.label}</Text>
        </TouchableOpacity>
      ))}
    </View>
  );
}

function EmptyState({ icon, title, body, testID }: { icon: any; title: string; body: string; testID: string }) {
  return (
    <View style={styles.empty} testID={testID}>
      <Ionicons name={icon} size={30} color={colors.brand} />
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyBody}>{body}</Text>
    </View>
  );
}

function LibraryFilters({ category, setCategory, query, setQuery }: any) {
  return (
    <View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.catRow} style={styles.catScroll} testID="templates-category-bar">
        {TEMPLATE_CATEGORIES.map((c) => (
          <TouchableOpacity key={c.key} onPress={() => setCategory(c.key)} style={[styles.chip, category === c.key && styles.chipActive]} testID={`templates-category-${c.key}`}>
            <Text style={[styles.chipText, category === c.key && styles.chipTextActive]}>{c.label}</Text>
          </TouchableOpacity>
        ))}
      </ScrollView>
      <View style={styles.searchRow}>
        <Ionicons name="search-outline" size={16} color={colors.muted} />
        <AppTextInput value={query} onChangeText={setQuery} placeholder="Search templates…" style={styles.searchInput} testID="templates-search-input" />
        {query ? (
          <TouchableOpacity onPress={() => setQuery("")} hitSlop={10} testID="templates-search-clear">
            <Ionicons name="close-circle" size={16} color={colors.muted} />
          </TouchableOpacity>
        ) : null}
      </View>
    </View>
  );
}

export default function TemplatesLibraryScreen() {
  const router = useRouter();
  const online = useOnline();
  const { showToast } = useToast();
  const params = useLocalSearchParams<{ tab?: string }>();
  const [tab, setTab] = useState<Tab>(params.tab === "mine" ? "mine" : "library");
  // Tab screens stay mounted — honour `?tab=` on every navigation (e.g. after delete).
  useEffect(() => {
    if (params.tab === "mine" || params.tab === "library") setTab(params.tab);
  }, [params.tab]);
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");
  const [defs, setDefs] = useState<any[]>([]);
  const [instances, setInstances] = useState<any[]>([]);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [cachedAt, setCachedAt] = useState<string | null>(null);

  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError("");
    try {
      const [d, i] = await Promise.all([listDefinitions(), listInstances({ mine: true })]);
      setDefs(d?.rows || []);
      setInstances(i?.rows || []);
      setCachedAt(null);
      cacheTemplateList(d?.rows || [], i?.rows || []);
    } catch (e: any) {
      const cached = e instanceof ApiNetworkError ? await readTemplateList() : null;
      if (cached) {
        setDefs(cached.defs || []);
        setInstances(cached.instances || []);
        setCachedAt(cached.cached_at);
      } else {
        setError(e.message || "Failed to load templates.");
      }
    } finally {
      setPendingIds(new Set((await getPendingQueue()).map((p) => p.instance_id)));
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { reload(); }, [reload]));

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return defs.filter((d: any) => {
      if (category !== "all" && d.category !== category) return false;
      if (!q) return true;
      return [d.title, d.description, d.code].some((s) => (s || "").toLowerCase().includes(q));
    });
  }, [defs, category, query]);

  const drafts = useMemo(() => instances.filter((i: any) => i.status === "draft"), [instances]);
  const finalized = useMemo(() => instances.filter((i: any) => i.status === "finalized"), [instances]);
  const definitionsByCode = useMemo(() => Object.fromEntries(defs.map((d: any) => [d.code, d])), [defs]);

  const handleCreate = async (code: string) => {
    if (!online) return showToast("Creating a new template needs a connection. You can still edit existing drafts offline.", "info");
    setBusy(true);
    try {
      const inst = await createInstance({ template_code: code });
      router.push(openPath(inst.id));
    } catch (e: any) {
      showToast(e.message || "Could not create draft.", "error");
    } finally {
      setBusy(false);
    }
  };

  const handleDuplicate = async (inst: any) => {
    try {
      const dup = await duplicateInstance(inst.id);
      router.push(openPath(dup.id));
    } catch (e: any) {
      showToast(e.message || "Could not duplicate.", "error");
    }
  };

  const handleDelete = (inst: any) =>
    showConfirm({
      title: "Delete template?",
      message: `Delete "${inst.title || "this instance"}"? This cannot be undone.`,
      confirmLabel: "Delete",
      confirmStyle: "destructive",
      onConfirm: async () => {
        try {
          await deleteInstance(inst.id);
          await Promise.all([clearSnapshot(inst.id), removePending(inst.id), clearInstanceBundle(inst.id)]);
          reload(true);
        } catch (e: any) {
          showToast(e.message || "Could not delete.", "error");
        }
      },
    });

  const handleDownload = async (inst: any) => {
    setDownloadingId(inst.id);
    try {
      await downloadPdf(inst.id, inst.title || inst.template_code);
    } catch (e: any) {
      showToast(e.message || "Could not generate PDF.", "error");
    } finally {
      setDownloadingId(null);
    }
  };

  const refreshControl = <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); reload(true); }} />;
  const listHandlers = { definitionsByCode, pendingIds, downloadingId, onOpen: (i: any) => router.push(openPath(i.id)), onDuplicate: handleDuplicate, onDelete: handleDelete };

  return (
    <View style={styles.root} testID="templates-library-page">
      <Header title="Templates" subtitle="Fill-in-the-blank forms for pricing, ops, chemistry & docs" back />
      <Segments tab={tab} setTab={setTab} mineCount={instances.length} />
      {(!online || cachedAt) && (
        <View style={styles.offlineRow} testID="templates-offline-banner">
          <OfflineIndicator online={online} hasPending={pendingIds.size > 0} />
          {cachedAt ? <Text style={styles.offlineText}>Showing saved list from {new Date(cachedAt).toLocaleString()}</Text> : null}
        </View>
      )}
      {error ? <View style={styles.errorBox} testID="templates-error"><Text style={styles.errorText}>{error}</Text></View> : null}

      {loading && !refreshing ? (
        <View style={styles.loading} testID="templates-loading">
          <ActivityIndicator size="large" color={colors.brand} />
          <Text style={styles.loadingText}>Loading templates…</Text>
        </View>
      ) : tab === "library" ? (
        <FlatList
          data={filtered}
          keyExtractor={(d: any) => d.code}
          renderItem={({ item }) => <TemplateCard definition={item} onCreate={handleCreate} busy={busy} />}
          ListHeaderComponent={<LibraryFilters category={category} setCategory={setCategory} query={query} setQuery={setQuery} />}
          ListEmptyComponent={<EmptyState icon="library-outline" title="No templates match your filters" body="Try clearing the search box or picking a different category." testID="templates-library-empty" />}
          contentContainerStyle={styles.listContent}
          keyboardShouldPersistTaps="handled"
          refreshControl={refreshControl}
          testID="templates-cards-list"
        />
      ) : (
        <ScrollView contentContainerStyle={styles.listContent} refreshControl={refreshControl} testID="templates-mine-list">
          {instances.length === 0 ? (
            <EmptyState icon="document-text-outline" title="You haven't filled any templates yet" body="Head to the Library tab and pick a template to get started." testID="templates-mine-empty" />
          ) : (
            <>
              <TemplateInstanceList title="Drafts" instances={drafts} {...listHandlers} />
              <TemplateInstanceList title="Finalized" instances={finalized} {...listHandlers} onDownload={handleDownload} />
            </>
          )}
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  segment: {
    flexDirection: "row", margin: spacing.lg, marginBottom: spacing.sm, padding: 4, gap: 4,
    backgroundColor: colors.surfaceTertiary, borderRadius: radius.md,
  },
  segBtn: { flex: 1, minHeight: 40, alignItems: "center", justifyContent: "center", borderRadius: radius.sm },
  segBtnActive: { backgroundColor: colors.surface, shadowColor: "#000", shadowOpacity: 0.08, shadowRadius: 4, shadowOffset: { width: 0, height: 1 }, elevation: 2 },
  segText: { fontSize: fontSize.sm, fontFamily: font.semibold, color: colors.onSurfaceSecondary },
  segTextActive: { color: colors.brand, fontFamily: font.bold },
  offlineRow: { paddingHorizontal: spacing.lg, gap: 4, marginBottom: spacing.sm },
  offlineText: { fontSize: 11, fontFamily: font.regular, color: colors.muted },
  errorBox: { marginHorizontal: spacing.lg, backgroundColor: "#FEE2E2", borderRadius: radius.sm, paddingHorizontal: 12, paddingVertical: 8 },
  errorText: { fontSize: fontSize.sm, fontFamily: font.regular, color: colors.error },
  loading: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12 },
  loadingText: { fontSize: fontSize.sm, fontFamily: font.regular, color: colors.muted },
  listContent: { padding: spacing.lg, paddingTop: spacing.sm, paddingBottom: 48 },
  catScroll: { marginBottom: spacing.md, marginHorizontal: -spacing.lg },
  catRow: { gap: 6, paddingHorizontal: spacing.lg },
  chip: { minHeight: 36, justifyContent: "center", paddingHorizontal: 14, borderRadius: 999, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  chipActive: { borderColor: colors.brand, backgroundColor: colors.brand },
  chipText: { fontSize: 12, fontFamily: font.bold, color: colors.onSurface },
  chipTextActive: { color: "#fff" },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 12, minHeight: 44,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, marginBottom: spacing.lg,
  },
  searchInput: { flex: 1, fontSize: fontSize.base, fontFamily: font.regular, paddingVertical: 8 },
  empty: { alignItems: "center", padding: 32, borderRadius: radius.lg, borderWidth: 1, borderStyle: "dashed", borderColor: colors.border, backgroundColor: colors.surface },
  emptyTitle: { fontSize: fontSize.lg, fontFamily: font.bold, color: colors.onSurface, marginTop: 12, textAlign: "center" },
  emptyBody: { fontSize: fontSize.sm, fontFamily: font.regular, color: colors.onSurfaceSecondary, marginTop: 4, textAlign: "center" },
});
