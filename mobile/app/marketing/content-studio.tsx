/**
 * Marketing Content Studio — AI image generation.
 * Route: /marketing/content-studio  (admin+)
 *
 * Port of frontend/src/pages/marketing/ContentStudioPage.jsx (MVP)
 *
 * - Prompt input + aspect ratio selector + Generate button
 * - Result image preview
 * - Recent generations library grid
 * - Feature-flagged on Supercool connected (shows banner if not)
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  Image, Alert, RefreshControl, Dimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api, api_base } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Card, PrimaryButton, Loading } from "@/src/components/ui";

const ASPECT_OPTIONS = [
  { v: "1:1", label: "Square" },
  { v: "16:9", label: "Wide" },
  { v: "4:5", label: "Portrait" },
  { v: "9:16", label: "Story" },
  { v: "4:3", label: "Landscape" },
];

function absoluteMediaUrl(u: string): string {
  if (!u) return "";
  if (u.startsWith("http") || u.startsWith("data:")) return u;
  const base = api_base().replace(/\/api\/?$/, "");
  return base + u;
}

const W = Dimensions.get("window").width;

export default function ContentStudio() {
  const [prompt, setPrompt] = useState("");
  const [aspect, setAspect] = useState("1:1");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [supercoolConnected, setSupercoolConnected] = useState<boolean | null>(null);
  const [library, setLibrary] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.get("/integrations/supercool/status");
      setSupercoolConnected(!!s?.connected);
    } catch {
      setSupercoolConnected(false);
    }
  }, []);

  const loadLibrary = useCallback(async () => {
    try {
      const r = await api.get("/media/library?limit=20");
      setLibrary(r?.items || r || []);
    } catch {
      setLibrary([]);
    }
  }, []);

  useEffect(() => {
    Promise.all([loadStatus(), loadLibrary()]).finally(() => setLoading(false));
  }, [loadStatus, loadLibrary]);

  const generate = async () => {
    if (!prompt.trim()) {
      Alert.alert("Prompt required", "Describe the image you want to create.");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/media/image/generate", {
        prompt: prompt.trim(),
        aspect_ratio: aspect,
      });
      setResult(r);
      loadLibrary();
    } catch (e: any) {
      Alert.alert("Generation failed", e.message || "Unknown error");
    } finally {
      setBusy(false);
    }
  };

  const deleteItem = async (id: string) => {
    Alert.alert("Delete image?", "This cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Delete", style: "destructive", onPress: async () => {
          try {
            await api.del(`/media/library/${id}`);
            setLibrary((l) => l.filter((x: any) => x.id !== id));
          } catch (e: any) {
            Alert.alert("Delete failed", e.message);
          }
        },
      },
    ]);
  };

  if (loading) {
    return (
      <View style={s.root}>
        <Header title="Content Studio" back />
        <Loading testID="content-studio-loading" />
      </View>
    );
  }

  return (
    <View style={s.root}>
      <Header title="Content Studio" back subtitle="AI image generation" />
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, paddingBottom: 80 }}
        refreshControl={
          <RefreshControl refreshing={false} onRefresh={() => { loadStatus(); loadLibrary(); }} />
        }
        keyboardShouldPersistTaps="handled"
      >
        {/* Supercool banner */}
        {supercoolConnected === false && (
          <Card style={s.banner} testID="content-studio-supercool-banner">
            <Ionicons name="information-circle-outline" size={18} color="#D97706" />
            <Text style={s.bannerText}>
              Supercool not connected. Image generation uses fallback mode.
            </Text>
          </Card>
        )}

        {/* Prompt */}
        <Text style={s.label}>PROMPT</Text>
        <TextInput
          style={[s.input, s.textArea]}
          value={prompt}
          onChangeText={setPrompt}
          multiline
          placeholder="Describe the image you want to create..."
          placeholderTextColor={colors.muted}
          testID="content-studio-prompt"
        />

        {/* Aspect ratio selector */}
        <Text style={s.label}>ASPECT RATIO</Text>
        <View style={s.aspectRow} testID="content-studio-aspect-row">
          {ASPECT_OPTIONS.map((o) => {
            const active = aspect === o.v;
            return (
              <Pressable
                key={o.v}
                style={[s.aspectBtn, active && s.aspectBtnActive]}
                onPress={() => setAspect(o.v)}
                testID={`content-studio-aspect-${o.v}`}
              >
                <Text style={[s.aspectText, active && s.aspectTextActive]}>{o.label}</Text>
              </Pressable>
            );
          })}
        </View>

        {/* Generate button */}
        <PrimaryButton
          title={busy ? "Generating..." : "Generate Image"}
          icon="sparkles-outline"
          loading={busy}
          onPress={generate}
          disabled={busy || !prompt.trim()}
          testID="content-studio-generate-btn"
        />

        {/* Result */}
        {result?.url && (
          <Card style={{ marginTop: spacing.lg }} testID="content-studio-result">
            <Text style={s.resultLabel}>Generated Image</Text>
            <Image
              source={{ uri: absoluteMediaUrl(result.url) }}
              style={s.resultImage}
              resizeMode="contain"
            />
          </Card>
        )}

        {/* Library */}
        {library.length > 0 && (
          <View style={{ marginTop: spacing.xl }}>
            <Text style={s.sectionTitle}>Recent Generations</Text>
            <View style={s.grid} testID="content-studio-library">
              {library.map((item: any) => (
                <Pressable
                  key={item.id}
                  style={s.gridItem}
                  onLongPress={() => deleteItem(item.id)}
                  testID={`content-studio-lib-${item.id}`}
                >
                  <Image
                    source={{ uri: absoluteMediaUrl(item.url || item.image_url) }}
                    style={s.gridImage}
                    resizeMode="cover"
                  />
                  {item.prompt && (
                    <Text style={s.gridCaption} numberOfLines={2}>{item.prompt}</Text>
                  )}
                </Pressable>
              ))}
            </View>
          </View>
        )}
      </ScrollView>
    </View>
  );
}

const GRID_GAP = spacing.sm;
const GRID_COLS = 2;
const GRID_ITEM_W = (W - spacing.lg * 2 - GRID_GAP) / GRID_COLS;

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  banner: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: "#FFFBEB", borderColor: "#FDE68A", marginBottom: spacing.md,
  },
  bannerText: { flex: 1, fontFamily: font.medium, fontSize: fontSize.sm, color: "#92400E" },
  label: {
    fontFamily: font.semibold, fontSize: 11, letterSpacing: 1,
    color: colors.onSurfaceSecondary, marginBottom: spacing.xs, marginTop: spacing.md,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, paddingVertical: 12,
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
    backgroundColor: colors.surface, marginBottom: spacing.md,
  },
  textArea: { minHeight: 100, textAlignVertical: "top" },
  aspectRow: {
    flexDirection: "row", flexWrap: "wrap", gap: spacing.xs, marginBottom: spacing.lg,
  },
  aspectBtn: {
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  aspectBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  aspectText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  aspectTextActive: { color: "#FFFFFF" },
  resultLabel: {
    fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface, marginBottom: spacing.sm,
  },
  resultImage: { width: "100%", height: 300, borderRadius: radius.md },
  sectionTitle: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.sm,
  },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: GRID_GAP },
  gridItem: {
    width: GRID_ITEM_W, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, overflow: "hidden",
  },
  gridImage: { width: "100%", height: GRID_ITEM_W, backgroundColor: colors.surfaceSecondary },
  gridCaption: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    padding: spacing.xs, lineHeight: 16,
  },
});
