/**
 * Templates Library — Phase 3 · Mobile UI
 *
 * Two tabs: Library (browse template definitions) and My Templates
 * (drafts + finalized instances).
 */
import React, { useCallback, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  ActivityIndicator,
  RefreshControl,
  Alert,
  Linking,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api, api_base } from "@/src/api";
import { useAuth } from "@/src/auth";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import TemplateCard from "@/src/components/templates/TemplateCard";
import TemplateStatusPill from "@/src/components/templates/TemplateStatusPill";

const CATEGORIES = [
  { key: "all", label: "All" },
  { key: "pricing_money", label: "Pricing & Money" },
  { key: "operations_checklists", label: "Ops & Checklists" },
  { key: "chemicals_chemistry", label: "Chemistry" },
  { key: "documents", label: "Documents" },
];

const CATEGORY_LABEL: Record<string, string> = {
  pricing_money: "Pricing & Money",
  operations_checklists: "Ops & Checklists",
  chemicals_chemistry: "Chemistry",
  documents: "Documents",
};

export default function TemplatesLibraryScreen() {
  const router = useRouter();
  useAuth();
  const [tab, setTab] = useState<"library" | "mine">("library");
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");
  const [defs, setDefs] = useState<any[]>([]);
  const [instances, setInstances] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const reload = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError("");
    try {
      const [d, i] = await Promise.all([
        api.get("/templates/definitions"),
        api.get("/templates/instances?mine=true"),
      ]);
      setDefs(d?.rows || []);
      setInstances(i?.rows || []);
    } catch (e: any) {
      setError(e.message || "Failed to load templates.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      reload();
    }, [reload])
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return defs.filter((d: any) => {
      if (category !== "all" && d.category !== category) return false;
      if (!q) return true;
      return (
        (d.title || "").toLowerCase().includes(q) ||
        (d.description || "").toLowerCase().includes(q) ||
        (d.code || "").toLowerCase().includes(q)
      );
    });
  }, [defs, category, query]);

  const drafts = useMemo(() => instances.filter((i: any) => i.status === "draft"), [instances]);
  const finalized = useMemo(
    () => instances.filter((i: any) => i.status === "finalized"),
    [instances]
  );

  const definitionsByCode = useMemo(() => {
    const m: Record<string, any> = {};
    for (const d of defs) m[d.code] = d;
    return m;
  }, [defs]);

  const handleCreate = async (code: string) => {
    setBusy(true);
    try {
      const inst = await api.post("/templates/instances", { template_code: code });
      router.push(`/(app)/templates/${inst.id}` as any);
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not create draft.");
    } finally {
      setBusy(false);
    }
  };

  const handleDuplicate = async (inst: any) => {
    try {
      const dup = await api.post(`/templates/instances/${inst.id}/duplicate`);
      router.push(`/(app)/templates/${dup.id}` as any);
    } catch (e: any) {
      Alert.alert("Error", e.message || "Could not duplicate.");
    }
  };

  const handleDelete = (inst: any) => {
    Alert.alert(
      "Delete Template",
      `Delete "${inst.title || "this instance"}"? This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            try {
              await api.del(`/templates/instances/${inst.id}`);
              reload(true);
            } catch (e: any) {
              Alert.alert("Error", e.message || "Could not delete.");
            }
          },
        },
      ]
    );
  };

  const handleDownloadPdf = async (inst: any) => {
    const url = `${api_base()}/templates/instances/${inst.id}/pdf`;
    Alert.alert(
      "Download PDF",
      "PDF will open in your browser.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Open",
          onPress: () => Linking.openURL(url),
        },
      ]
    );
  };

  return (
    <View style={styles.root} testID="templates-library-page">
      <Header
        title="Templates"
        subtitle="Fill-in-the-blank templates for your business"
        back
      />

      {/* Tabs */}
      <View style={styles.tabRow} testID="templates-library-tabs">
        {([
          { key: "library", label: "Library" },
          {
            key: "mine",
            label: `My Templates${instances.length ? ` (${instances.length})` : ""}`,
          },
        ] as const).map((t) => (
          <TouchableOpacity
            key={t.key}
            onPress={() => setTab(t.key)}
            style={[styles.tab, tab === t.key && styles.tabActive]}
            testID={`templates-tab-${t.key}`}
            activeOpacity={0.7}
          >
            <Text style={[styles.tabText, tab === t.key && styles.tabTextActive]}>
              {t.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {error ? (
        <View style={styles.errorBox} testID="templates-error">
          <Text style={styles.errorText}>{error}</Text>
        </View>
      ) : null}

      {loading && !refreshing ? (
        <View style={styles.loadingBox} testID="templates-loading">
          <ActivityIndicator size="large" color={colors.brand} />
          <Text style={styles.loadingText}>Loading templates…</Text>
        </View>
      ) : tab === "library" ? (
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                reload(true);
              }}
            />
          }
        >
          {/* Category chips */}
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.catScroll}
            contentContainerStyle={styles.catRow}
            testID="templates-category-bar"
          >
            {CATEGORIES.map((c) => (
              <TouchableOpacity
                key={c.key}
                onPress={() => setCategory(c.key)}
                style={[styles.catChip, category === c.key && styles.catChipActive]}
                activeOpacity={0.7}
                testID={`templates-category-${c.key}`}
              >
                <Text
                  style={[
                    styles.catChipText,
                    category === c.key && styles.catChipTextActive,
                  ]}
                >
                  {c.label}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {/* Search */}
          <View style={styles.searchRow}>
            <Ionicons name="search-outline" size={16} color={colors.muted} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search templates…"
              placeholderTextColor={colors.muted}
              style={styles.searchInput}
              testID="templates-search-input"
            />
          </View>

          {filtered.length === 0 ? (
            <View style={styles.emptyState} testID="templates-library-empty">
              <Ionicons name="library-outline" size={32} color={colors.brand} />
              <Text style={styles.emptyTitle}>No templates match your filters</Text>
              <Text style={styles.emptyBody}>
                Try clearing the search box or picking a different category.
              </Text>
            </View>
          ) : (
            filtered.map((defn: any) => (
              <TemplateCard
                key={defn.code}
                definition={defn}
                onCreate={handleCreate}
                busy={busy}
              />
            ))
          )}
        </ScrollView>
      ) : (
        /* My Templates tab */
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => {
                setRefreshing(true);
                reload(true);
              }}
            />
          }
        >
          {instances.length === 0 ? (
            <View style={styles.emptyState} testID="templates-mine-empty">
              <Ionicons name="document-text-outline" size={32} color={colors.brand} />
              <Text style={styles.emptyTitle}>No templates yet</Text>
              <Text style={styles.emptyBody}>
                Head to the Library tab and pick a template to get started.
              </Text>
            </View>
          ) : (
            <>
              <InstanceGroup
                title="Drafts"
                instances={drafts}
                definitionsByCode={definitionsByCode}
                onOpen={(inst) =>
                  router.push(`/(app)/templates/${inst.id}` as any)
                }
                onDuplicate={handleDuplicate}
                onDelete={handleDelete}
                onDownload={undefined}
              />
              <InstanceGroup
                title="Finalized"
                instances={finalized}
                definitionsByCode={definitionsByCode}
                onOpen={(inst) =>
                  router.push(`/(app)/templates/${inst.id}` as any)
                }
                onDuplicate={handleDuplicate}
                onDelete={handleDelete}
                onDownload={handleDownloadPdf}
              />
            </>
          )}
        </ScrollView>
      )}
    </View>
  );
}

/* ── Instance Group ────────────────────────────────────────────── */
function InstanceGroup({
  title,
  instances,
  definitionsByCode,
  onOpen,
  onDuplicate,
  onDelete,
  onDownload,
}: {
  title: string;
  instances: any[];
  definitionsByCode: Record<string, any>;
  onOpen: (inst: any) => void;
  onDuplicate: (inst: any) => void;
  onDelete: (inst: any) => void;
  onDownload?: (inst: any) => void;
}) {
  if (!instances || instances.length === 0) return null;
  return (
    <View
      style={styles.groupContainer}
      testID={`template-instance-group-${title.toLowerCase()}`}
    >
      <Text style={styles.groupTitle}>
        {title}{" "}
        <Text style={styles.groupCount}>({instances.length})</Text>
      </Text>
      {instances.map((inst) => {
        const defn = definitionsByCode?.[inst.template_code];
        return (
          <TouchableOpacity
            key={inst.id}
            style={styles.instRow}
            onPress={() => onOpen(inst)}
            activeOpacity={0.7}
            testID={`template-instance-row-${inst.id}`}
          >
            <View style={styles.instInfo}>
              <Ionicons
                name="document-text-outline"
                size={18}
                color={colors.muted}
              />
              <View style={{ flex: 1 }}>
                <Text style={styles.instTitle} numberOfLines={1}>
                  {inst.title || "(untitled)"}
                </Text>
                <View style={styles.instMeta}>
                  <Text style={styles.instTemplate} numberOfLines={1}>
                    {defn?.title || inst.template_code}
                  </Text>
                  {defn?.category ? (
                    <View style={styles.instCatBadge}>
                      <Text style={styles.instCatText}>
                        {CATEGORY_LABEL[defn.category] || defn.category}
                      </Text>
                    </View>
                  ) : null}
                </View>
                <View style={styles.instBottom}>
                  <TemplateStatusPill status={inst.status} />
                  <Text style={styles.instDate}>
                    {inst.updated_at
                      ? new Date(inst.updated_at).toLocaleDateString()
                      : "—"}
                  </Text>
                </View>
              </View>
            </View>
            <View style={styles.instActions}>
              {inst.status === "finalized" && onDownload ? (
                <TouchableOpacity
                  onPress={(e) => {
                    e.stopPropagation?.();
                    onDownload(inst);
                  }}
                  hitSlop={8}
                  testID={`template-instance-download-${inst.id}`}
                >
                  <Ionicons name="download-outline" size={18} color={colors.brand} />
                </TouchableOpacity>
              ) : null}
              <TouchableOpacity
                onPress={(e) => {
                  e.stopPropagation?.();
                  onDuplicate(inst);
                }}
                hitSlop={8}
                testID={`template-instance-duplicate-${inst.id}`}
              >
                <Ionicons name="copy-outline" size={18} color={colors.onSurfaceSecondary} />
              </TouchableOpacity>
              <TouchableOpacity
                onPress={(e) => {
                  e.stopPropagation?.();
                  onDelete(inst);
                }}
                hitSlop={8}
                testID={`template-instance-delete-${inst.id}`}
              >
                <Ionicons name="trash-outline" size={18} color={colors.error} />
              </TouchableOpacity>
            </View>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

/* ── Styles ────────────────────────────────────────────────────── */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  tabRow: {
    flexDirection: "row",
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    paddingBottom: spacing.sm,
    gap: 8,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  tab: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  tabActive: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  tabText: {
    fontSize: fontSize.sm,
    fontFamily: font.bold,
    color: colors.onSurface,
  },
  tabTextActive: {
    color: "#fff",
  },
  errorBox: {
    marginHorizontal: spacing.lg,
    marginTop: spacing.sm,
    backgroundColor: "#FEE2E2",
    borderRadius: radius.sm,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  errorText: {
    fontSize: fontSize.sm,
    fontFamily: font.regular,
    color: colors.error,
  },
  loadingBox: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 40,
    gap: 12,
  },
  loadingText: {
    fontSize: fontSize.sm,
    fontFamily: font.regular,
    color: colors.muted,
  },
  scroll: { flex: 1 },
  scrollContent: { padding: spacing.lg, paddingBottom: 40 },
  catScroll: { marginBottom: spacing.md },
  catRow: { gap: 6 },
  catChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  catChipActive: {
    borderColor: colors.brand,
    backgroundColor: colors.brand,
  },
  catChipText: {
    fontSize: 12,
    fontFamily: font.bold,
    color: colors.onSurface,
  },
  catChipTextActive: {
    color: "#fff",
  },
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    marginBottom: spacing.lg,
  },
  searchInput: {
    flex: 1,
    fontSize: fontSize.base,
    fontFamily: font.regular,
    color: colors.onSurface,
    padding: 0,
  },
  emptyState: {
    alignItems: "center",
    padding: 32,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    backgroundColor: colors.surface,
  },
  emptyTitle: {
    fontSize: fontSize.lg,
    fontFamily: font.bold,
    color: colors.onSurface,
    marginTop: 12,
  },
  emptyBody: {
    fontSize: fontSize.sm,
    fontFamily: font.regular,
    color: colors.onSurfaceSecondary,
    marginTop: 4,
    textAlign: "center",
  },
  // Instance group styles
  groupContainer: { marginBottom: spacing.xl },
  groupTitle: {
    fontSize: 12,
    fontFamily: font.bold,
    color: colors.onSurfaceSecondary,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 8,
  },
  groupCount: {
    fontFamily: font.regular,
    color: colors.muted,
  },
  instRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 14,
    paddingVertical: 12,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: 8,
  },
  instInfo: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
    flex: 1,
  },
  instTitle: {
    fontSize: fontSize.base,
    fontFamily: font.semibold,
    color: colors.onSurface,
    marginBottom: 2,
  },
  instMeta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 4,
    flexWrap: "wrap",
  },
  instTemplate: {
    fontSize: 12,
    fontFamily: font.regular,
    color: colors.onSurfaceSecondary,
  },
  instCatBadge: {
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 999,
  },
  instCatText: {
    fontSize: 9,
    fontFamily: font.bold,
    color: colors.onBrandTertiary,
    textTransform: "uppercase",
  },
  instBottom: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  instDate: {
    fontSize: 11,
    fontFamily: font.regular,
    color: colors.muted,
  },
  instActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginLeft: 8,
  },
});
