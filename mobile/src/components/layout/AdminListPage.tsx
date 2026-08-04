// Phase 41.2 · Feb 2026 — Mobile admin-list-page primitive.
//
// Extract the repeated `RoleGate + Header + ScrollView(RefreshControl) +
// [Loading | EmptyState | rows] + optional Sheet` scaffold that every
// admin list page from Phase 35 / 36 / 37 (recurring jobs, vendor bills,
// scorecards, roles, SOPs, leanboards, sprints, price-increase, anomalies,
// payroll, ap-aging, master-invoices list, autobilling runs, …) hand-wired
// verbatim.
//
// Callers still own:
//   • row layout — passed in as `children`
//   • data-fetch state — `loading`, `isEmpty`, `refreshing`, `onRefresh`
//   • the create-sheet body (if any) — passed as `sheet`
//
// This primitive intentionally does NOT own:
//   • the row renderer (bespoke per surface — pill vs status color vs
//     inline switch, etc.)
//   • the data-fetch effect (`useFocusEffect(load)` — kept in the caller
//     so a page can trigger extra side effects on focus)
//   • filter chips or bulk-action bars — passed as `headerExtra` /
//     `bulkBar` so autobilling-runs-style pages keep their bespoke rows
//     without special-casing this primitive.
//
// Testing contract:
//   • Every refactored page keeps its existing `data-testid` values
//     (`{page}-page`, `{page}-empty`, `{page}-create`, `{page}-sheet`, …)
//     because they're passed straight through the props below. Downstream
//     source-inspection tests from Phase 35 / 36 / 37 stay green.
import React from "react";
import { View, StyleSheet, ScrollView, RefreshControl } from "react-native";

import { colors, spacing } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header, IconButton } from "@/src/components/widgets";
import { RoleGate, type GateLevel } from "@/src/components/RoleGate";

export type AdminListPageProps = {
  /** Page title rendered inside the shared `<Header>`. */
  title: string;
  /** `testID` for the outer `<View>` — final id is `${testID}` verbatim
   *  so callers can pass `"recurring-jobs-page"` to keep parity. */
  testID: string;
  /** Access gate. Defaults to `"strict_admin"` — the level every current
   *  finance/OS/CFO list page uses. */
  roleLevel?: GateLevel;
  /** Whether the data fetch is in-flight — renders `<Loading />` when true. */
  loading: boolean;
  /** Empty-state predicate — `true` renders `<EmptyState />` after loading. */
  isEmpty: boolean;
  /** Pull-to-refresh handler. Callers own the refreshing boolean so they
   *  can flip it around their own async load. */
  refreshing: boolean;
  onRefresh: () => void | Promise<void>;
  /** Empty-state props — passed through to `<EmptyState>`. */
  emptyIcon: any;
  emptyTitle: string;
  emptySubtitle?: string;
  emptyTestID?: string;
  /** Optional create button in the Header's right slot. Present ⇒ `<IconButton icon="add"/>`. */
  onCreate?: () => void;
  createTestID?: string;
  /** Rendered ABOVE the list body (e.g. autobilling-runs filter chips). */
  headerExtra?: React.ReactNode;
  /** Rendered between `headerExtra` and the list (e.g. bulk-cancel bar). */
  bulkBar?: React.ReactNode;
  /** The row list — caller owns render. */
  children: React.ReactNode;
  /** Optional `<Sheet>` (or any node) mounted alongside the list — the
   *  Phase 35 / 37 create sheets pass through here unchanged. */
  sheet?: React.ReactNode;
};

export function AdminListPage({
  title,
  testID,
  roleLevel = "strict_admin",
  loading,
  isEmpty,
  refreshing,
  onRefresh,
  emptyIcon,
  emptyTitle,
  emptySubtitle,
  emptyTestID,
  onCreate,
  createTestID,
  headerExtra,
  bulkBar,
  children,
  sheet,
}: AdminListPageProps) {
  return (
    <RoleGate level={roleLevel}>
      <View style={styles.container} testID={testID}>
        <Header
          title={title}
          right={
            onCreate ? (
              <IconButton icon="add" onPress={onCreate} testID={createTestID} />
            ) : undefined
          }
        />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
          }
        >
          {headerExtra}
          {bulkBar}
          {loading ? (
            <Loading />
          ) : isEmpty ? (
            <EmptyState
              icon={emptyIcon}
              title={emptyTitle}
              subtitle={emptySubtitle}
              testID={emptyTestID}
            />
          ) : (
            children
          )}
        </ScrollView>
        {sheet}
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing["3xl"] },
});
