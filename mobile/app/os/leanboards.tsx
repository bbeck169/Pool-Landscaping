// Phase 37 · Feb-2026 — Business OS Lean Boards (P1.3).
// Web: BusinessOS.jsx Lean Boards slice.
// Backend: GET /leanboards, GET /leanboards/{id}/cards, POST /leanboards/cards/{id}/move.
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { RoleGate } from "@/src/components/RoleGate";

const COLUMNS = ["backlog", "in_progress", "done"];

export default function OsLeanboards() {
  const [boards, setBoards] = useState<any[]>([]);
  const [selected, setSelected] = useState<any>(null);
  const [cards, setCards] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadBoards = useCallback(async () => {
    setLoading(true);
    try {
      const r: any = await api.get("/leanboards");
      const list = Array.isArray(r) ? r : r?.items || [];
      setBoards(list);
      if (list.length && !selected) setSelected(list[0]);
    } catch { setBoards([]); } finally { setLoading(false); }
  }, [selected]);

  const loadCards = useCallback(async (boardId: string) => {
    try {
      const r: any = await api.get(`/leanboards/${boardId}/cards`);
      setCards(Array.isArray(r) ? r : r?.items || []);
    } catch { setCards([]); }
  }, []);

  useFocusEffect(useCallback(() => { loadBoards(); }, [loadBoards]));

  const pickBoard = useCallback(async (b: any) => {
    setSelected(b);
    await loadCards(b.id);
  }, [loadCards]);

  const moveCard = useCallback(async (card: any, column: string) => {
    try {
      await api.post(`/leanboards/cards/${card.id}/move`, { column });
      if (selected) await loadCards(selected.id);
    } catch { /* ignore */ }
  }, [selected, loadCards]);

  return (
    <RoleGate level="strict_admin">
      <View style={styles.container} testID="os-leanboards-page">
        <Header title="Lean Boards" />
        <ScrollView
          contentContainerStyle={styles.body}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => {
            setRefreshing(true); await loadBoards(); if (selected) await loadCards(selected.id); setRefreshing(false);
          }} />}
        >
          {loading ? <Loading /> : boards.length === 0 ? (
            <EmptyState icon="grid-outline" title="No lean boards yet" subtitle="Create them on desktop." testID="os-leanboards-empty" />
          ) : (
            <>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.pills} testID="os-leanboards-picker">
                {boards.map((b) => (
                  <Pressable
                    key={b.id}
                    onPress={() => pickBoard(b)}
                    style={[styles.pill, selected?.id === b.id && styles.pillOn]}
                    testID={`os-leanboards-board-${b.id}`}
                  >
                    <Text style={[styles.pillText, selected?.id === b.id && styles.pillTextOn]}>{b.name || b.id.slice(0, 8)}</Text>
                  </Pressable>
                ))}
              </ScrollView>
              {selected && (
                <>
                  {COLUMNS.map((col) => {
                    const colCards = cards.filter((c) => (c.column || "backlog") === col);
                    return (
                      <View key={col} style={styles.column} testID={`os-leanboards-column-${col}`}>
                        <Text style={styles.columnHead}>{col.replace("_", " ").toUpperCase()} ({colCards.length})</Text>
                        {colCards.length === 0 ? (
                          <Text style={styles.emptyCol}>—</Text>
                        ) : colCards.map((c) => (
                          <View key={c.id} style={styles.card} testID={`os-leanboards-card-${c.id}`}>
                            <Text style={styles.cardTitle}>{c.title || "—"}</Text>
                            <View style={styles.cardActions}>
                              {COLUMNS.filter((k) => k !== col).map((target) => (
                                <Pressable
                                  key={target}
                                  onPress={() => moveCard(c, target)}
                                  style={styles.moveBtn}
                                  testID={`os-leanboards-move-${c.id}-${target}`}
                                >
                                  <Text style={styles.moveText}>→ {target.replace("_", " ")}</Text>
                                </Pressable>
                              ))}
                            </View>
                          </View>
                        ))}
                      </View>
                    );
                  })}
                </>
              )}
            </>
          )}
        </ScrollView>
      </View>
    </RoleGate>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.lg, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  pills: { flexDirection: "row", gap: spacing.xs },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  pillOn: { backgroundColor: colors.brandTertiary, borderColor: colors.brand },
  pillText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  pillTextOn: { color: colors.brand },
  column: { padding: spacing.md, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, gap: spacing.xs },
  columnHead: { fontFamily: font.bold, fontSize: 11, color: colors.muted, letterSpacing: 0.5 },
  emptyCol: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  card: { padding: spacing.sm, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary, gap: spacing.xs },
  cardTitle: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface },
  cardActions: { flexDirection: "row", gap: spacing.xs, flexWrap: "wrap" },
  moveBtn: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: radius.pill, backgroundColor: colors.brandTertiary },
  moveText: { fontFamily: font.medium, fontSize: 10, color: colors.brand },
});
