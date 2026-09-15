import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  Platform,
  Alert,
  Linking,
  ActivityIndicator,
  Dimensions } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { ZillowAccess } from "@/src/components/ZillowAccess";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Sheet, PrimaryButton } from "@/src/components/ui";
import { ZillowUsageChip, ZillowRateLimitedBanner } from "@/src/components/ZillowUsageChip";
import AppTextInput from "@/src/components/ui/AppTextInput";

const W = Dimensions.get("window").width;
const num = (n: any) => (n === null || n === undefined || n === "" ? "—" : Number(n).toLocaleString());

export default function VirtualBid() {
  return (
    <ZillowAccess>
      <VirtualBidScreen />
    </ZillowAccess>
  );
}

function VirtualBidScreen() {
  const { showToast } = useToast();
  const router = useRouter();
  const [address, setAddress] = useState("");
  const [loading, setLoading] = useState(false);
  const [prop, setProp] = useState<any>(null);
  const [error, setError] = useState("");
  const [photoIdx, setPhotoIdx] = useState(0);

  const [saveOpen, setSaveOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<"customer" | "lead" | null>(null);
  const [customers, setCustomers] = useState<any[]>([]);
  const [leads, setLeads] = useState<any[]>([]);
  const [saving, setSaving] = useState(false);
  const [usageBump, setUsageBump] = useState(0);

  const lookup = async () => {
    const a = address.trim();
    if (a.length < 5) { setError("Enter a full property address."); return; }
    setLoading(true);
    setError("");
    setProp(null);
    setPhotoIdx(0);
    try {
      const d = await api.get(`/property/lookup?address=${encodeURIComponent(a)}`);
      setProp(d);
      setUsageBump((n) => n + 1);
    } catch (e: any) {
      setError(e?.message || "Could not find that property.");
    } finally {
      setLoading(false);
    }
  };

  const loadDir = useCallback(async () => {
    if (customers.length || leads.length) return;
    try {
      const [c, l] = await Promise.all([api.get("/customers"), api.get("/leads")]);
      setCustomers(c || []);
      setLeads(l || []);
    } catch {}
  }, [customers.length, leads.length]);

  const savePayload = (extra: any) => ({
    address: prop.address,
    zpid: prop.zpid,
    detail_url: prop.detail_url,
    price: prop.price || 0,
    zestimate: prop.zestimate,
    beds: prop.beds,
    baths: prop.baths,
    sqft: prop.sqft,
    lot_size: prop.lot_size ? String(prop.lot_size) : null,
    year_built: prop.year_built,
    home_type: prop.home_type,
    lat: prop.lat,
    lng: prop.lng,
    photos: prop.photos || [],
    ...extra,
  });

  const saveAsLead = async () => {
    setSaving(true);
    try {
      const res = await api.post("/property/save", savePayload({ create_lead: true }));
      setSaveOpen(false);
      showToast("Saved as lead — " + `${prop.address} saved with photos.`);
      router.push("/leads");
      return res;
    } catch (e: any) {
      showToast(e?.message || "Save failed.", "error");
    } finally {
      setSaving(false);
    }
  };

  const attachTo = async (kind: "customer" | "lead", id: string, label: string) => {
    setPickerMode(null);
    setSaving(true);
    try {
      await api.post("/property/save", savePayload(kind === "customer" ? { customer_id: id } : { lead_id: id }));
      setSaveOpen(false);
      showToast(`Property & photos attached to ${label}.`);
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const createEstimate = () => {
    const sqft = Math.round(prop.sqft || 0);
    router.push({
      pathname: "/estimator/[id]",
      params: {
        id: "new",
        title: `Bid — ${prop.address}`,
        lineDesc: `${prop.address}${sqft ? ` (${sqft.toLocaleString()} sq ft)` : ""}`,
        lineQty: String(sqft || 1),
        lineCost: "0",
        category: "Material",
      },
    });
  };

  const facts: [string, string][] = prop
    ? [
        ["Beds", num(prop.beds)],
        ["Baths", num(prop.baths)],
        ["Living area", prop.sqft ? `${num(prop.sqft)} sq ft` : "—"],
        ["Lot size", prop.lot_size ? String(prop.lot_size) : "—"],
        ["Year built", prop.year_built ? String(prop.year_built) : "—"],
        ["Type", prop.home_type || "—"],
      ]
    : [];

  return (
    <View style={styles.root}>
      <Header title="Virtual Bid" subtitle="Size up a property from Zillow" back
              right={<ZillowUsageChip refreshKey={usageBump} testID="vbid-zillow-chip" />} />
      <ZillowRateLimitedBanner testID="vbid-zillow-banner" />

      <View style={styles.searchWrap}>
        <View style={styles.searchBox}>
          <Ionicons name="search" size={16} color={colors.muted} />
          <AppTextInput
            style={styles.searchInput}
            value={address}
            onChangeText={setAddress}
            placeholder="Enter property address"
            placeholderTextColor={colors.muted}
            returnKeyType="search"
            onSubmitEditing={lookup}
            autoCapitalize="words"
            testID="vbid-address"
          />
        </View>
        <Pressable style={styles.lookupBtn} onPress={lookup} disabled={loading} testID="vbid-lookup">
          {loading ? <ActivityIndicator color="#fff" size="small" /> : <Ionicons name="arrow-forward" size={20} color="#fff" />}
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingTop: 0, paddingBottom: spacing["3xl"] }}>
        {loading ? (
          <View style={styles.center}><ActivityIndicator color={colors.brand} /><Text style={styles.centerText}>Pulling the Zillow listing…</Text></View>
        ) : error ? (
          <View style={styles.center}><Ionicons name="alert-circle-outline" size={28} color={colors.error} /><Text style={styles.centerText}>{error}</Text></View>
        ) : !prop ? (
          <View style={styles.center}>
            <Ionicons name="home-outline" size={30} color={colors.muted} />
            <Text style={styles.centerText}>Enter an address to pull its listing photos and facts so you can bid without driving out.</Text>
          </View>
        ) : (
          <>
            {/* Photos */}
            {prop.photos?.length ? (
              <View style={styles.gallery}>
                <ScrollView
                  horizontal
                  pagingEnabled
                  showsHorizontalScrollIndicator={false}
                  onMomentumScrollEnd={(e) => setPhotoIdx(Math.round(e.nativeEvent.contentOffset.x / (W - spacing.lg * 2)))}
                  testID="vbid-gallery"
                >
                  {prop.photos.map((u: string, i: number) => (
                    <Image key={i} source={{ uri: u }} style={styles.photo} contentFit="cover" transition={150} />
                  ))}
                </ScrollView>
                <View style={styles.counter}><Text style={styles.counterText}>{photoIdx + 1}/{prop.photos.length}</Text></View>
              </View>
            ) : (
              <View style={[styles.photo, styles.noPhoto]}><Ionicons name="image-outline" size={30} color={colors.muted} /><Text style={styles.centerText}>No photos on this listing</Text></View>
            )}

            {/* Header row */}
            <Text style={styles.addr}>{prop.address}</Text>
            <Text style={styles.cityLine}>{[prop.city, prop.state, prop.zipcode].filter(Boolean).join(", ")}</Text>
            <View style={styles.priceRow}>
              {prop.price ? <Text style={styles.price}>{money(prop.price)}</Text> : null}
              {prop.zestimate ? <Text style={styles.zest}>Zestimate {money(prop.zestimate)}</Text> : null}
            </View>

            {/* Facts */}
            <View style={styles.factGrid}>
              {facts.map(([k, v]) => (
                <View key={k} style={styles.fact}>
                  <Text style={styles.factLabel}>{k.toUpperCase()}</Text>
                  <Text style={styles.factValue}>{v}</Text>
                </View>
              ))}
            </View>

            {prop.detail_url ? (
              <Pressable style={styles.zillowLink} onPress={() => Linking.openURL(prop.detail_url)} testID="vbid-zillow">
                <Ionicons name="open-outline" size={16} color={colors.brand} />
                <Text style={styles.zillowText}>Open on Zillow</Text>
              </Pressable>
            ) : null}

            {/* Actions */}
            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Create Estimate" icon="calculator-outline" onPress={createEstimate} testID="vbid-estimate" />
            <View style={{ height: spacing.sm }} />
            <PrimaryButton title="Save property" icon="bookmark-outline" variant="outline" onPress={() => { setSaveOpen(true); loadDir(); }} testID="vbid-save-open" />
          </>
        )}
      </ScrollView>

      {/* Save sheet */}
      <Sheet visible={saveOpen} onClose={() => setSaveOpen(false)} title="Save property" testID="vbid-save-sheet">
        <Text style={styles.hint}>Keep this listing (with photos) for later. Create a fresh lead or attach it to an existing customer/lead.</Text>
        <View style={{ height: spacing.md }} />
        <PrimaryButton title={saving ? "Saving…" : "Save as new Lead"} icon="magnet-outline" loading={saving} onPress={saveAsLead} testID="vbid-save-lead" />
        <View style={{ height: spacing.sm }} />
        <Pressable style={styles.optRow} onPress={() => setPickerMode("customer")} testID="vbid-attach-customer">
          <Ionicons name="person-outline" size={18} color={colors.brand} />
          <Text style={styles.optText}>Attach to a customer</Text>
          <Ionicons name="chevron-forward" size={16} color={colors.muted} />
        </Pressable>
        <Pressable style={styles.optRow} onPress={() => setPickerMode("lead")} testID="vbid-attach-lead">
          <Ionicons name="magnet-outline" size={18} color={colors.brand} />
          <Text style={styles.optText}>Attach to an existing lead</Text>
          <Ionicons name="chevron-forward" size={16} color={colors.muted} />
        </Pressable>
      </Sheet>

      {/* Attach picker */}
      <Sheet visible={!!pickerMode} onClose={() => setPickerMode(null)} title={pickerMode === "customer" ? "Attach to customer" : "Attach to lead"} testID="vbid-picker-sheet">
        {(pickerMode === "customer" ? customers : leads).length === 0 ? (
          <Text style={styles.hint}>Nothing found.</Text>
        ) : (
          (pickerMode === "customer" ? customers : leads).map((it: any) => (
            <Pressable key={it.id} style={styles.pickerRow} onPress={() => attachTo(pickerMode as any, it.id, it.name)} testID={`vbid-pick-${it.id}`}>
              <Text style={styles.pickerName}>{it.name}</Text>
              {it.address ? <Text style={styles.pickerSub}>{it.address}</Text> : null}
            </Pressable>
          ))
        )}
      </Sheet>
    </View>
  );
}

const IMG_W = W - spacing.lg * 2;
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  searchWrap: { flexDirection: "row", gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  searchBox: { flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48 },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  lookupBtn: { width: 48, height: 48, borderRadius: radius.md, backgroundColor: colors.brand, alignItems: "center", justifyContent: "center" },
  center: { alignItems: "center", justifyContent: "center", paddingVertical: spacing["3xl"], gap: spacing.md },
  centerText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", paddingHorizontal: spacing.lg, lineHeight: 20 },
  gallery: { borderRadius: radius.lg, overflow: "hidden" },
  photo: { width: IMG_W, height: 240, borderRadius: radius.lg, backgroundColor: colors.surfaceTertiary },
  noPhoto: { alignItems: "center", justifyContent: "center", gap: spacing.sm },
  counter: { position: "absolute", bottom: spacing.sm, right: spacing.sm, backgroundColor: "rgba(10,25,40,0.7)", paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  counterText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  addr: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface, marginTop: spacing.lg },
  cityLine: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 2 },
  priceRow: { flexDirection: "row", alignItems: "baseline", gap: spacing.md, marginTop: spacing.sm },
  price: { fontFamily: font.bold, fontSize: fontSize["2xl"], color: colors.brand },
  zest: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted },
  factGrid: { flexDirection: "row", flexWrap: "wrap", marginTop: spacing.lg, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, overflow: "hidden" },
  fact: { width: "33.33%", padding: spacing.md, borderWidth: 0.5, borderColor: colors.border },
  factLabel: { fontFamily: font.semibold, fontSize: 10, letterSpacing: 0.6, color: colors.muted },
  factValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginTop: 2 },
  zillowLink: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.md },
  zillowText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  hint: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, lineHeight: 20 },
  optRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  optText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  pickerRow: { paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  pickerName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  pickerSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
});
