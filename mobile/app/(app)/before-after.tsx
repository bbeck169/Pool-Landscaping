/**
 * QuoteIQ Phase Q3 · Mobile — Before/After Studio (tech + admin).
 *
 * Pick two photos, choose a style, generate a branded composite card
 * via ``/api/before-after/generate`` (5 credits). Native share sheet
 * for the public share URL. Techs can enter this screen already
 * scoped to a job or customer via query params, and the loaded gallery
 * is filtered accordingly.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Image, Share,
  ActivityIndicator, Alert,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { colors, spacing, radius, fontSize, font } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";
import { absolutizeUrl } from "@/src/lib/absolutizeUrl";

const STYLES = [
  { v: "side_by_side", label: "Side by side" },
  { v: "stacked", label: "Stacked" },
  { v: "slider", label: "Slider" },
] as const;

const CREDIT_COST = 5;

async function pickPhoto(): Promise<string | null> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (perm.status !== "granted") {
    Alert.alert("Photos permission is needed to select an image.");
    return null;
  }
  const res = await ImagePicker.launchImageLibraryAsync({
    base64: true, quality: 0.5, allowsEditing: false,
  });
  if (res.canceled || !res.assets?.[0]?.base64) return null;
  return `data:image/jpeg;base64,${res.assets[0].base64}`;
}

function ShareUrl({ token }: { token?: string }) {
  if (!token) return null;
  const backend = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/$/, "");
  const url = `${backend}/api/before-after/public/${token}`;
  return (
    <Pressable
      onPress={() => Share.share({ url, message: `Take a look: ${url}` })}
      style={styles.shareBtn}
      testID="ba-share-btn">
      <Ionicons name="share-outline" size={16} color="#fff" />
      <Text style={styles.shareTxt}>Share</Text>
    </Pressable>
  );
}

export default function BeforeAfterMobile() {
  const router = useRouter();
  const params = useLocalSearchParams<{ job_id?: string; customer_id?: string }>();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || (user?.role as any) === "super_admin";

  const [before, setBefore] = useState<string | null>(null);
  const [after, setAfter] = useState<string | null>(null);
  const [style, setStyle] = useState<string>("side_by_side");
  const [caption, setCaption] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [pair, setPair] = useState<any | null>(null);
  const [gallery, setGallery] = useState<any[]>([]);
  const [balance, setBalance] = useState<any>(null);

  const load = useCallback(async () => {
    // Techs can only list scoped by job or customer; admins get full list.
    const q: string[] = [];
    if (params.job_id) q.push(`job_id=${params.job_id}`);
    if (params.customer_id) q.push(`customer_id=${params.customer_id}`);
    if (!isAdmin && q.length === 0) {
      setGallery([]);
    } else {
      try {
        const r = await api.get(
          `/before-after/pairs${q.length ? "?" + q.join("&") : "?limit=20"}`,
        );
        setGallery(r.pairs || []);
      } catch {
        setGallery([]);
      }
    }
    if (isAdmin) {
      try {
        setBalance(await api.get("/ai-credits/balance"));
      } catch {}
    }
  }, [params.job_id, params.customer_id, isAdmin]);
  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    if (!before || !after) {
      Alert.alert("Pick both photos first");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/before-after/generate", {
        before_photo_url: before, after_photo_url: after,
        style, caption, service_type: "pool_cleaning",
        include_branding: true,
        job_id: params.job_id || null,
        customer_id: params.customer_id || null,
      });
      setPair(r.pair);
      Alert.alert("Card generated");
      load();
    } catch (e: any) {
      Alert.alert("Generate failed", e?.message || "");
    } finally { setBusy(false); }
  };

  const canGenerate = isAdmin;  // Backend enforces admin on POST; hide the CTA for techs.

  return (
    <View style={styles.root}>
      <Header title="Before / After" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 120 }}>
        {balance && (
          <View style={styles.balanceRow}>
            <Ionicons name="sparkles" size={14} color={colors.brand} />
            <Text style={styles.balanceTxt}>
              AI credits: <Text style={{ fontWeight: "700" }}>{balance.balance}</Text>
            </Text>
          </View>
        )}

        {canGenerate ? (
          <View style={styles.card}>
            <View style={styles.pickerRow}>
              <Pressable style={styles.pickerBox}
                          onPress={async () => setBefore(await pickPhoto())}
                          testID="ba-mobile-pick-before">
                {before ? (
                  <Image source={{ uri: before }} style={styles.thumb} />
                ) : (
                  <>
                    <Ionicons name="image-outline" size={22}
                                color={colors.muted} />
                    <Text style={styles.pickerLabel}>Before</Text>
                  </>
                )}
              </Pressable>
              <Pressable style={styles.pickerBox}
                          onPress={async () => setAfter(await pickPhoto())}
                          testID="ba-mobile-pick-after">
                {after ? (
                  <Image source={{ uri: after }} style={styles.thumb} />
                ) : (
                  <>
                    <Ionicons name="image-outline" size={22}
                                color={colors.muted} />
                    <Text style={styles.pickerLabel}>After</Text>
                  </>
                )}
              </Pressable>
            </View>

            <View style={styles.stylesRow}>
              {STYLES.map((s) => (
                <Pressable key={s.v}
                            onPress={() => setStyle(s.v)}
                            style={[styles.styleChip,
                              style === s.v && styles.styleChipActive]}
                            testID={`ba-mobile-style-${s.v}`}>
                  <Text style={[styles.styleChipTxt,
                    style === s.v && styles.styleChipTxtActive]}>
                    {s.label}
                  </Text>
                </Pressable>
              ))}
            </View>

            <View style={styles.footer}>
              <Text style={styles.footerHint}>
                {CREDIT_COST} credits per generation
              </Text>
              <Pressable style={[styles.genBtn, busy && { opacity: 0.7 }]}
                          disabled={busy}
                          onPress={generate}
                          testID="ba-mobile-generate">
                {busy
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={styles.genBtnTxt}>Generate</Text>}
              </Pressable>
            </View>
          </View>
        ) : (
          <View style={styles.techNotice}>
            <Ionicons name="information-circle-outline" size={20}
                        color={colors.muted} />
            <Text style={styles.techNoticeTxt}>
              Before/After cards are generated by an admin. You can view
              recent cards for your assigned jobs below.
            </Text>
          </View>
        )}

        {pair && (
          <View style={styles.card} testID="ba-mobile-result">
            <View style={styles.resultHeader}>
              <Text style={styles.resultTitle}>
                Generated · {pair.status}
              </Text>
              <ShareUrl token={pair.share_token} />
            </View>
            {pair.generated_card_url && (
              <Image source={{ uri: absolutizeUrl(pair.generated_card_url) }}
                     style={styles.resultImg}
                     resizeMode="contain" />
            )}
          </View>
        )}

        <Text style={styles.sectionTitle}>
          Recent cards{params.job_id ? " · job" : params.customer_id ? " · customer" : ""}
        </Text>
        <View style={styles.gallery}>
          {gallery.length === 0 && (
            <Text style={styles.emptyTxt}>
              {isAdmin
                ? "No cards yet."
                : "No cards for this job/customer yet."}
            </Text>
          )}
          {gallery.map((p) => (
            <Pressable key={p.id} onPress={() => setPair(p)}
                        style={styles.galleryItem}
                        testID={`ba-mobile-gallery-${p.id}`}>
              {p.generated_card_url ? (
                <Image source={{ uri: absolutizeUrl(p.generated_card_url) }}
                        style={styles.galleryImg}
                        resizeMode="cover" />
              ) : (
                <View style={styles.galleryFallback}>
                  <Text style={styles.emptyTxt}>{p.status || "pending"}</Text>
                </View>
              )}
              <Text style={styles.galleryCaption} numberOfLines={1}>
                {p.caption || p.service_type || p.style}
              </Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  balanceRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    marginBottom: spacing.md,
  },
  balanceTxt: { color: colors.muted, fontSize: fontSize.sm,
                 fontFamily: font.regular },
  card: {
    backgroundColor: colors.surface, borderColor: colors.border,
    borderWidth: 1, borderRadius: radius.lg, padding: spacing.lg,
    marginBottom: spacing.lg,
  },
  pickerRow: { flexDirection: "row", gap: spacing.md },
  pickerBox: {
    flex: 1, aspectRatio: 1, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary, alignItems: "center",
    justifyContent: "center", gap: 4, overflow: "hidden",
  },
  thumb: { width: "100%", height: "100%" },
  pickerLabel: { color: colors.muted, fontSize: fontSize.sm,
                    fontFamily: font.regular },
  stylesRow: { flexDirection: "row", gap: 6, marginTop: spacing.md,
                flexWrap: "wrap" },
  styleChip: {
    borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999,
  },
  styleChipActive: { backgroundColor: colors.brand,
                      borderColor: colors.brand },
  styleChipTxt: { color: colors.onSurface, fontSize: fontSize.sm,
                    fontFamily: font.regular },
  styleChipTxtActive: { color: "#fff" },
  footer: {
    marginTop: spacing.md, flexDirection: "row",
    alignItems: "center", justifyContent: "space-between",
  },
  footerHint: { color: colors.muted, fontSize: fontSize.sm,
                  fontFamily: font.regular },
  genBtn: {
    backgroundColor: colors.brand, paddingHorizontal: spacing.lg,
    paddingVertical: 10, borderRadius: 8,
  },
  genBtnTxt: { color: "#fff", fontWeight: "700",
                fontFamily: font.bold },
  techNotice: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    padding: spacing.md, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, marginBottom: spacing.lg,
  },
  techNoticeTxt: {
    flex: 1, color: colors.muted, fontSize: fontSize.sm,
    fontFamily: font.regular,
  },
  resultHeader: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between", marginBottom: spacing.sm,
  },
  resultTitle: {
    color: colors.onSurface, fontFamily: font.bold,
    fontWeight: "700",
  },
  resultImg: { width: "100%", height: 220, borderRadius: radius.md },
  shareBtn: {
    backgroundColor: colors.brand, paddingHorizontal: 10,
    paddingVertical: 6, borderRadius: 8,
    flexDirection: "row", alignItems: "center", gap: 4,
  },
  shareTxt: { color: "#fff", fontWeight: "700",
                fontFamily: font.bold, fontSize: fontSize.sm },
  sectionTitle: {
    color: colors.onSurface, fontWeight: "700",
    fontFamily: font.bold, marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  gallery: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  galleryItem: { width: "48%" },
  galleryImg: { width: "100%", height: 96, borderRadius: 8 },
  galleryFallback: {
    width: "100%", height: 96, borderRadius: 8,
    backgroundColor: colors.surfaceSecondary,
    alignItems: "center", justifyContent: "center",
  },
  galleryCaption: {
    color: colors.muted, fontSize: fontSize.sm,
    fontFamily: font.regular, marginTop: 4,
  },
  emptyTxt: { color: colors.muted, fontSize: fontSize.sm,
                fontFamily: font.regular },
});
