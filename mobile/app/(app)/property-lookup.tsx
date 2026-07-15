/**
 * Phase 25 · Mobile — Property Lookup (tech + admin surface).
 * Search by address, GPS reverse-geocode, save notes, view history.
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, TextInput, Pressable,
  ActivityIndicator, Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";

import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

interface Comp {
  address?: string;
  price?: number;
  sold_date?: string;
  beds?: number;
  baths?: number;
  sqft?: number;
  photo?: string;
}

export default function PropertyLookup() {
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [noteText, setNoteText] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const [noteSaved, setNoteSaved] = useState(false);

  const runSearch = async (addr?: string) => {
    const q = (addr ?? address).trim();
    if (q.length < 5) { setError("Enter a full property address"); return; }
    setLoading(true); setError(null); setResult(null); setNoteSaved(false);
    try {
      const r = await api.get(
        `/property/search?address=${encodeURIComponent(q)}`);
      setResult(r);
    } catch (e: any) {
      setError(e.message || "Search failed");
    } finally { setLoading(false); }
  };

  const useMyLocation = async () => {
    setError(null);
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") {
      setError("Location permission denied");
      return;
    }
    setLoading(true);
    try {
      const loc = await Location.getCurrentPositionAsync({});
      const r = await api.get(
        `/property/search-by-coords?lat=${loc.coords.latitude}&lng=${loc.coords.longitude}`);
      setResult(r);
      setAddress(r?.property?.address || "");
    } catch (e: any) {
      setError(e.message || "GPS lookup failed");
    } finally { setLoading(false); }
  };

  const loadHistory = useCallback(async () => {
    try {
      const r = await api.get("/property/history");
      setHistory(r.items || []);
    } catch { /* ignore */ }
  }, []);

  const openHistory = async () => {
    await loadHistory();
    setShowHistory(true);
  };

  const saveNote = async () => {
    if (!noteText.trim() || !result?.property?.address) return;
    setSavingNote(true);
    try {
      await api.post("/property/save-note", {
        address: result.property.address, note: noteText,
      });
      setNoteText(""); setNoteSaved(true);
    } finally { setSavingNote(false); }
  };

  const p = result?.property;
  const isMocked = !!result?.mocked;
  const cachedAt = result?.cached_at;

  return (
    <View style={styles.root}>
      <Header title="Property lookup" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: spacing["3xl"] }}>
        <View style={styles.searchRow}>
          <TextInput
            value={address} onChangeText={setAddress}
            placeholder="123 Main St, Springfield, IL"
            placeholderTextColor={colors.muted}
            style={styles.search}
            onSubmitEditing={() => runSearch()}
            testID="prop-address-input" />
          <Pressable onPress={() => runSearch()} style={styles.searchBtn}
                     disabled={loading}
                     testID="prop-search-btn">
            <Ionicons name="search" size={16} color="#fff" />
          </Pressable>
        </View>

        <View style={styles.actionRow}>
          <Pressable onPress={useMyLocation} style={styles.actionChip}
                     testID="prop-gps-btn">
            <Ionicons name="location" size={14} color={colors.brand} />
            <Text style={styles.actionChipText}>Use my location</Text>
          </Pressable>
          <Pressable onPress={openHistory} style={styles.actionChip}
                     testID="prop-history-btn">
            <Ionicons name="time-outline" size={14} color={colors.brand} />
            <Text style={styles.actionChipText}>History</Text>
          </Pressable>
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: spacing.xl }}
                              color={colors.brand} />
        ) : null}

        {error ? (
          <View style={styles.errorBanner}>
            <Ionicons name="alert-circle" size={16} color="#DC2626" />
            <Text style={styles.errorText}>{error}</Text>
          </View>
        ) : null}

        {p ? (
          <>
            {isMocked ? (
              <View style={styles.mockBanner}
                     testID="prop-mock-banner">
                <Ionicons name="information-circle" size={14}
                            color="#92400E" />
                <Text style={styles.mockText}>
                  Live Zillow data unavailable — {result.reason || "provider offline"}.
                  Showing address only.
                </Text>
              </View>
            ) : null}

            {p.photos && p.photos.length > 0 ? (
              <Image source={{ uri: p.photos[0] }} style={styles.hero} />
            ) : null}

            <View style={styles.card}>
              <Text style={styles.address}
                     testID="prop-result-address">
                {p.address}
              </Text>
              {p.city || p.state ? (
                <Text style={styles.subAddress}>
                  {p.city}{p.state ? `, ${p.state}` : ""}
                  {p.zipcode ? ` ${p.zipcode}` : ""}
                </Text>
              ) : null}
              {p.zestimate ? (
                <View style={styles.zestimateBox}>
                  <Text style={styles.zestimateLabel}>ZESTIMATE</Text>
                  <Text style={styles.zestimateValue}>
                    ${Number(p.zestimate).toLocaleString()}
                  </Text>
                </View>
              ) : null}

              <View style={styles.factsGrid}>
                {[
                  ["Beds",       p.beds],
                  ["Baths",      p.baths],
                  ["Sqft",       p.sqft ? Number(p.sqft).toLocaleString() : null],
                  ["Year built", p.year_built],
                  ["Lot size",   p.lot_size],
                  ["Type",       p.property_type],
                ].filter(([_, v]) => v).map(([l, v], i) => (
                  <View key={i} style={styles.fact}>
                    <Text style={styles.factLabel}>{l as string}</Text>
                    <Text style={styles.factValue}>{String(v)}</Text>
                  </View>
                ))}
              </View>

              {p.owner_name || p.last_sale_price || p.tax_assessment ? (
                <View style={styles.section}>
                  <Text style={styles.sectionTitle}>Ownership & taxes</Text>
                  {p.owner_name ? (
                    <Text style={styles.sectionRow}>
                      <Text style={styles.rowLabel}>Owner: </Text>
                      {p.owner_name}
                    </Text>
                  ) : null}
                  {p.last_sale_price ? (
                    <Text style={styles.sectionRow}>
                      <Text style={styles.rowLabel}>Last sale: </Text>
                      ${Number(p.last_sale_price).toLocaleString()}
                      {p.last_sale_date ? ` (${p.last_sale_date})` : ""}
                    </Text>
                  ) : null}
                  {p.tax_assessment ? (
                    <Text style={styles.sectionRow}>
                      <Text style={styles.rowLabel}>Tax assessment: </Text>
                      ${Number(p.tax_assessment).toLocaleString()}
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </View>

            {p.neighborhood_comps && p.neighborhood_comps.length > 0 ? (
              <View style={styles.section}>
                <Text style={styles.sectionTitleHero}>
                  Neighborhood comps
                </Text>
                <ScrollView horizontal
                            showsHorizontalScrollIndicator={false}
                            contentContainerStyle={{ gap: spacing.sm }}>
                  {p.neighborhood_comps.map((c: Comp, i: number) => (
                    <View key={i} style={styles.compCard}
                            testID={`prop-comp-${i}`}>
                      {c.photo ? (
                        <Image source={{ uri: c.photo }}
                                 style={styles.compPhoto} />
                      ) : (
                        <View style={[styles.compPhoto,
                                        styles.compPhotoEmpty]}>
                          <Ionicons name="home-outline" size={24}
                                      color={colors.muted} />
                        </View>
                      )}
                      <View style={{ padding: spacing.sm }}>
                        <Text style={styles.compAddress}
                                 numberOfLines={2}>
                          {c.address || "—"}
                        </Text>
                        {c.price ? (
                          <Text style={styles.compPrice}>
                            ${Number(c.price).toLocaleString()}
                          </Text>
                        ) : null}
                        <Text style={styles.compMeta}>
                          {[c.beds && `${c.beds}bd`,
                              c.baths && `${c.baths}ba`,
                              c.sqft && `${Number(c.sqft).toLocaleString()} sqft`]
                              .filter(Boolean).join(" · ")}
                        </Text>
                      </View>
                    </View>
                  ))}
                </ScrollView>
              </View>
            ) : null}

            <View style={styles.card}>
              <Text style={styles.sectionTitle}>Save a note</Text>
              <TextInput
                value={noteText} onChangeText={setNoteText}
                placeholder='e.g., "Big yard, quarterly service"'
                placeholderTextColor={colors.muted}
                multiline
                style={styles.noteInput}
                testID="prop-note-input" />
              <Pressable onPress={saveNote}
                         disabled={savingNote || !noteText.trim()}
                         style={[styles.saveBtn,
                                  (!noteText.trim() || savingNote)
                                    && { opacity: 0.4 }]}
                         testID="prop-note-save">
                <Text style={styles.saveBtnText}>
                  {savingNote ? "Saving…"
                     : noteSaved ? "Saved ✓" : "Save note"}
                </Text>
              </Pressable>
            </View>

            <Text style={styles.footer}>
              Data via Zillow ·{" "}
              {cachedAt ? (result.cached
                            ? `cached ${cachedAt.slice(11, 16)}`
                            : "fresh") : ""}
              {isMocked ? " · MOCKED" : ""}
            </Text>
          </>
        ) : null}

        {showHistory ? (
          <View style={styles.historyModal}
                 testID="prop-history-modal">
            <View style={styles.historyHeader}>
              <Text style={styles.historyTitle}>Recent lookups</Text>
              <Pressable onPress={() => setShowHistory(false)}>
                <Ionicons name="close" size={20} color={colors.onSurface} />
              </Pressable>
            </View>
            {history.length === 0 ? (
              <Text style={styles.emptyText}>No lookups yet.</Text>
            ) : (
              history.map((h: any, i: number) => (
                <Pressable key={i} style={styles.historyRow}
                             onPress={() => {
                               setAddress(h.address);
                               setShowHistory(false);
                               runSearch(h.address);
                             }}
                             testID={`prop-history-row-${i}`}>
                  <Ionicons name="location-outline" size={14}
                              color={colors.brand} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.historyAddress}>
                      {h.address}
                    </Text>
                    <Text style={styles.historyTs}>
                      {(h.ts || "").slice(0, 16).replace("T", " ")}
                    </Text>
                  </View>
                  <Ionicons name="chevron-forward" size={14}
                              color={colors.muted} />
                </Pressable>
              ))
            )}
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  searchRow: { flexDirection: "row", gap: spacing.sm,
                marginBottom: spacing.sm },
  search: {
    flex: 1, backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface,
    fontFamily: font.regular, fontSize: fontSize.base,
  },
  searchBtn: {
    backgroundColor: colors.brand, borderRadius: radius.md,
    paddingHorizontal: spacing.lg, alignItems: "center",
    justifyContent: "center",
  },
  actionRow: { flexDirection: "row", gap: spacing.sm,
                marginBottom: spacing.md },
  actionChip: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderRadius: radius.pill,
    backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border,
  },
  actionChipText: { fontFamily: font.semibold, fontSize: fontSize.sm,
                      color: colors.brand },
  errorBanner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: "#FEE2E2", padding: spacing.md,
    borderRadius: radius.md, marginBottom: spacing.md,
  },
  errorText: { fontFamily: font.semibold, fontSize: fontSize.sm,
                color: "#991B1B", flex: 1 },
  mockBanner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: "#FEF3C7", padding: spacing.md,
    borderRadius: radius.md, marginBottom: spacing.sm,
  },
  mockText: { fontFamily: font.regular, fontSize: fontSize.xs,
               color: "#92400E", flex: 1 },
  hero: { width: "100%", height: 180, borderRadius: radius.md,
           marginBottom: spacing.sm },
  card: {
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.md,
    marginBottom: spacing.md,
  },
  address: { fontFamily: font.bold, fontSize: fontSize.xl,
               color: colors.onSurface },
  subAddress: { fontFamily: font.regular, fontSize: fontSize.sm,
                  color: colors.muted, marginTop: 2 },
  zestimateBox: {
    marginTop: spacing.md, padding: spacing.md,
    backgroundColor: `${colors.brand}10`,
    borderRadius: radius.md,
  },
  zestimateLabel: { fontFamily: font.semibold, fontSize: 10,
                      color: colors.brand, letterSpacing: 1 },
  zestimateValue: { fontFamily: font.bold, fontSize: 28,
                      color: colors.brand, marginTop: 2 },
  factsGrid: { flexDirection: "row", flexWrap: "wrap",
                 gap: spacing.sm, marginTop: spacing.md },
  fact: {
    minWidth: "30%", padding: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
  },
  factLabel: { fontFamily: font.regular, fontSize: 10,
                 color: colors.muted, textTransform: "uppercase" },
  factValue: { fontFamily: font.bold, fontSize: fontSize.base,
                 color: colors.onSurface, marginTop: 2 },
  section: {
    marginTop: spacing.md,
    paddingTop: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.base,
                    color: colors.onSurface, marginBottom: spacing.sm },
  sectionTitleHero: { fontFamily: font.bold, fontSize: fontSize.lg,
                        color: colors.onSurface, marginBottom: spacing.sm },
  sectionRow: { fontFamily: font.regular, fontSize: fontSize.sm,
                  color: colors.onSurface, marginTop: 4 },
  rowLabel: { fontFamily: font.semibold, color: colors.muted },
  compCard: {
    width: 200,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, overflow: "hidden",
  },
  compPhoto: { width: "100%", height: 120 },
  compPhotoEmpty: {
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
  },
  compAddress: { fontFamily: font.bold, fontSize: fontSize.sm,
                   color: colors.onSurface },
  compPrice: { fontFamily: font.bold, fontSize: fontSize.base,
                 color: colors.brand, marginTop: 2 },
  compMeta: { fontFamily: font.regular, fontSize: fontSize.xs,
                color: colors.muted, marginTop: 2 },
  noteInput: {
    minHeight: 80,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.md,
    color: colors.onSurface, fontFamily: font.regular,
    fontSize: fontSize.base, textAlignVertical: "top",
  },
  saveBtn: {
    marginTop: spacing.sm,
    backgroundColor: colors.brand,
    borderRadius: radius.md, padding: spacing.md,
    alignItems: "center",
  },
  saveBtnText: { fontFamily: font.bold, fontSize: fontSize.base,
                   color: "#fff" },
  footer: { textAlign: "center", marginTop: spacing.md,
              fontFamily: font.regular, fontSize: fontSize.xs,
              color: colors.muted },
  historyModal: {
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.md,
  },
  historyHeader: {
    flexDirection: "row", justifyContent: "space-between",
    alignItems: "center", marginBottom: spacing.sm,
  },
  historyTitle: { fontFamily: font.bold, fontSize: fontSize.lg,
                    color: colors.onSurface },
  historyRow: {
    flexDirection: "row", alignItems: "center",
    gap: spacing.sm, paddingVertical: spacing.sm,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  historyAddress: { fontFamily: font.semibold, fontSize: fontSize.sm,
                      color: colors.onSurface },
  historyTs: { fontFamily: font.regular, fontSize: fontSize.xs,
                 color: colors.muted, marginTop: 2 },
  emptyText: { textAlign: "center", padding: spacing.md,
                 color: colors.muted, fontFamily: font.regular,
                 fontSize: fontSize.sm },
});
