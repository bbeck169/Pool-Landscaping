import React, { useCallback, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  Platform,
  Alert,
  Linking,
  ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import * as Sharing from "expo-sharing";
import * as FileSystem from "expo-file-system/legacy";
import { useFocusEffect } from "expo-router";

import { AdminOnly } from "@/src/components/AdminOnly";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import { Sheet, PrimaryButton } from "@/src/components/ui";

const STYLES = [
  "Modern",
  "Desert / Xeriscape",
  "Tropical",
  "Mediterranean",
  "Traditional",
  "Minimalist",
  "Cottage Garden",
];

const ELEMENTS = [
  "Paver patio",
  "Artificial turf",
  "Natural grass lawn",
  "Flower beds",
  "Shade trees",
  "Water feature",
  "Fire pit",
  "Outdoor lighting",
  "Retaining wall",
  "Gravel / rock",
  "Palm trees",
  "Pool deck",
];

type AttachMode = "none" | "customer" | "lead";

const asUri = (b64: string) => (b64.startsWith("data:") ? b64 : `data:image/png;base64,${b64}`);

export default function LandscapeAI() {
  return (
    <AdminOnly>
      <LandscapeAIScreen />
    </AdminOnly>
  );
}

function LandscapeAIScreen() {
  const [inputB64, setInputB64] = useState<string | null>(null); // data uri
  const [style, setStyle] = useState<string>("");
  const [elements, setElements] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [output, setOutput] = useState<string | null>(null); // raw base64 or data uri
  const [generating, setGenerating] = useState(false);

  const [attachMode, setAttachMode] = useState<AttachMode>("none");
  const [attachId, setAttachId] = useState<string | null>(null);
  const [attachLabel, setAttachLabel] = useState<string>("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [customers, setCustomers] = useState<any[]>([]);
  const [leads, setLeads] = useState<any[]>([]);

  const [sourceSheet, setSourceSheet] = useState(false);
  const [renders, setRenders] = useState<any[]>([]);
  const [viewer, setViewer] = useState<any | null>(null);

  const loadRenders = useCallback(async () => {
    try {
      setRenders(await api.get("/landscape/renders"));
    } catch {}
  }, []);

  const loadDirectory = useCallback(async () => {
    try {
      const [c, l] = await Promise.all([api.get("/customers"), api.get("/leads")]);
      setCustomers(c || []);
      setLeads(l || []);
    } catch {}
  }, []);

  useFocusEffect(
    useCallback(() => {
      loadRenders();
      loadDirectory();
    }, [loadRenders, loadDirectory])
  );

  const pickPhoto = async (source: "camera" | "library") => {
    setSourceSheet(false);
    try {
      const perm =
        source === "camera"
          ? await ImagePicker.requestCameraPermissionsAsync()
          : await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) {
          Alert.alert(
            source === "camera" ? "Camera access needed" : "Photo access needed",
            "Enable access in Settings to add a yard photo.",
            [
              { text: "Cancel", style: "cancel" },
              { text: "Open Settings", onPress: () => Linking.openSettings() },
            ]
          );
        }
        return;
      }
      const opts: ImagePicker.ImagePickerOptions = { base64: true, quality: 0.6, allowsEditing: false };
      const res =
        source === "camera"
          ? await ImagePicker.launchCameraAsync(opts)
          : await ImagePicker.launchImageLibraryAsync({ ...opts, mediaTypes: ["images"] });
      if (res.canceled || !res.assets?.[0]?.base64) return;
      setInputB64(`data:image/jpeg;base64,${res.assets[0].base64}`);
      setOutput(null);
    } catch (e: any) {
      Alert.alert("Could not add photo", e?.message || "Please try again.");
    }
  };

  const toggleElement = (el: string) =>
    setElements((prev) => (prev.includes(el) ? prev.filter((x) => x !== el) : [...prev, el]));

  const openPicker = (mode: Exclude<AttachMode, "none">) => {
    setAttachMode(mode);
    setPickerOpen(true);
  };

  const chooseAttach = (mode: Exclude<AttachMode, "none">, id: string, label: string) => {
    setAttachMode(mode);
    setAttachId(id);
    setAttachLabel(label);
    setPickerOpen(false);
  };

  const clearAttach = () => {
    setAttachMode("none");
    setAttachId(null);
    setAttachLabel("");
  };

  const generate = async () => {
    if (!inputB64) {
      Alert.alert("Add a photo", "Snap or upload a yard photo first.");
      return;
    }
    setGenerating(true);
    setOutput(null);
    try {
      const body: any = {
        image_base64: inputB64,
        style,
        elements,
        prompt,
      };
      if (attachMode === "customer" && attachId) body.customer_id = attachId;
      if (attachMode === "lead" && attachId) body.lead_id = attachId;
      const res = await api.post("/landscape/render", body, 120000);
      setOutput(res.output_image);
      loadRenders();
    } catch (e: any) {
      Alert.alert("Rendering failed", e?.message || "Please try a clearer photo or different options.");
    } finally {
      setGenerating(false);
    }
  };

  const saveImage = async (b64: string) => {
    const uri = asUri(b64);
    try {
      if (Platform.OS === "web") {
        if (typeof document !== "undefined") {
          const a = document.createElement("a");
          a.href = uri;
          a.download = `landscape-${Date.now()}.png`;
          a.click();
        }
        return;
      }
      if (!(await Sharing.isAvailableAsync())) {
        Alert.alert("Sharing unavailable", "Sharing is not available on this device.");
        return;
      }
      const path = `${FileSystem.cacheDirectory}landscape-${Date.now()}.png`;
      const raw = uri.split(",", 2)[1] || "";
      await FileSystem.writeAsStringAsync(path, raw, { encoding: FileSystem.EncodingType.Base64 });
      await Sharing.shareAsync(path, { mimeType: "image/png", dialogTitle: "Save or share design" });
    } catch (e: any) {
      Alert.alert("Could not share", e?.message || "Please try again.");
    }
  };

  const deleteRender = (rid: string) => {
    const doDelete = async () => {
      try {
        await api.del(`/landscape/renders/${rid}`);
        setViewer(null);
        loadRenders();
      } catch (e: any) {
        Alert.alert("Delete failed", e?.message || "Please try again.");
      }
    };
    if (Platform.OS === "web") {
      doDelete();
      return;
    }
    Alert.alert("Delete design?", "This cannot be undone.", [
      { text: "Cancel", style: "cancel" },
      { text: "Delete", style: "destructive", onPress: doDelete },
    ]);
  };

  const startNew = () => {
    setInputB64(null);
    setOutput(null);
    setStyle("");
    setElements([]);
    setPrompt("");
    clearAttach();
  };

  const pickerList = attachMode === "customer" ? customers : leads;

  const attachSummary = useMemo(() => {
    if (attachMode === "none" || !attachId) return null;
    return `${attachMode === "customer" ? "Customer" : "Lead"}: ${attachLabel}`;
  }, [attachMode, attachId, attachLabel]);

  return (
    <View style={styles.root}>
      <Header title="Landscape AI" subtitle="Photorealistic yard redesigns" back />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }} keyboardShouldPersistTaps="handled">
        {/* Photo */}
        <Text style={styles.sectionLabel}>YARD PHOTO</Text>
        {inputB64 ? (
          <View style={styles.photoWrap}>
            <Image source={{ uri: inputB64 }} style={styles.photo} contentFit="cover" />
            <Pressable style={styles.photoChange} onPress={() => setSourceSheet(true)} testID="landscape-change-photo">
              <Ionicons name="camera-reverse-outline" size={16} color="#fff" />
              <Text style={styles.photoChangeText}>Change</Text>
            </Pressable>
          </View>
        ) : (
          <Pressable style={styles.dropzone} onPress={() => setSourceSheet(true)} testID="landscape-add-photo">
            <View style={styles.dropIcon}>
              <Ionicons name="image-outline" size={28} color={colors.brand} />
            </View>
            <Text style={styles.dropTitle}>Add a yard photo</Text>
            <Text style={styles.dropSub}>Snap or upload the space you want to redesign</Text>
          </Pressable>
        )}

        {/* Style */}
        <Text style={[styles.sectionLabel, { marginTop: spacing.xl }]}>DESIGN STYLE</Text>
        <View style={styles.chipWrap}>
          {STYLES.map((s) => {
            const on = style === s;
            return (
              <Pressable key={s} onPress={() => setStyle(on ? "" : s)} style={[styles.chip, on && styles.chipOn]} testID={`landscape-style-${s}`}>
                <Text style={[styles.chipText, on && styles.chipTextOn]}>{s}</Text>
              </Pressable>
            );
          })}
        </View>

        {/* Elements */}
        <Text style={[styles.sectionLabel, { marginTop: spacing.xl }]}>ADD FEATURES</Text>
        <View style={styles.chipWrap}>
          {ELEMENTS.map((el) => {
            const on = elements.includes(el);
            return (
              <Pressable key={el} onPress={() => toggleElement(el)} style={[styles.chip, on && styles.chipOn]} testID={`landscape-el-${el}`}>
                {on ? <Ionicons name="checkmark" size={14} color="#fff" style={{ marginRight: 4 }} /> : null}
                <Text style={[styles.chipText, on && styles.chipTextOn]}>{el}</Text>
              </Pressable>
            );
          })}
        </View>

        {/* Prompt */}
        <Text style={[styles.sectionLabel, { marginTop: spacing.xl }]}>EXTRA NOTES (OPTIONAL)</Text>
        <TextInput
          style={styles.textarea}
          value={prompt}
          onChangeText={setPrompt}
          placeholder="e.g. low-maintenance, drought-tolerant plants, warm evening lighting"
          placeholderTextColor={colors.muted}
          multiline
          testID="landscape-prompt"
        />

        {/* Attach */}
        <Text style={[styles.sectionLabel, { marginTop: spacing.xl }]}>ATTACH TO (OPTIONAL)</Text>
        {attachSummary ? (
          <View style={styles.attachRow}>
            <Ionicons name={attachMode === "customer" ? "person-outline" : "magnet-outline"} size={16} color={colors.brand} />
            <Text style={styles.attachText}>{attachSummary}</Text>
            <Pressable onPress={clearAttach} hitSlop={8} testID="landscape-attach-clear">
              <Ionicons name="close-circle" size={18} color={colors.muted} />
            </Pressable>
          </View>
        ) : (
          <View style={styles.attachBtns}>
            <Pressable style={styles.attachBtn} onPress={() => openPicker("customer")} testID="landscape-attach-customer">
              <Ionicons name="person-outline" size={16} color={colors.brand} />
              <Text style={styles.attachBtnText}>Customer</Text>
            </Pressable>
            <Pressable style={styles.attachBtn} onPress={() => openPicker("lead")} testID="landscape-attach-lead">
              <Ionicons name="magnet-outline" size={16} color={colors.brand} />
              <Text style={styles.attachBtnText}>Lead</Text>
            </Pressable>
          </View>
        )}

        <View style={{ height: spacing.lg }} />
        <PrimaryButton
          title={generating ? "Designing your yard…" : "Generate Design"}
          icon="sparkles-outline"
          loading={generating}
          disabled={!inputB64}
          onPress={generate}
          testID="landscape-generate"
        />

        {generating ? (
          <View style={styles.genHint}>
            <ActivityIndicator color={colors.brand} />
            <Text style={styles.genHintText}>This can take 15–40 seconds. Keep the screen open.</Text>
          </View>
        ) : null}

        {/* Result */}
        {output ? (
          <View style={styles.resultCard} testID="landscape-result">
            <Text style={styles.resultTitle}>Redesigned Yard</Text>
            <View style={styles.beforeAfter}>
              <View style={styles.baItem}>
                <Text style={styles.baLabel}>BEFORE</Text>
                {inputB64 ? <Image source={{ uri: inputB64 }} style={styles.baImg} contentFit="cover" /> : null}
              </View>
              <View style={styles.baItem}>
                <Text style={styles.baLabel}>AFTER</Text>
                <Image source={{ uri: asUri(output) }} style={styles.baImg} contentFit="cover" />
              </View>
            </View>
            <View style={styles.resultActions}>
              <PrimaryButton title="Save / Share" icon="share-outline" variant="outline" onPress={() => saveImage(output)} testID="landscape-save" />
              <View style={{ height: spacing.sm }} />
              <PrimaryButton title="New Design" icon="add-outline" variant="success" onPress={startNew} testID="landscape-new" />
            </View>
          </View>
        ) : null}

        {/* Gallery */}
        {renders.length > 0 ? (
          <>
            <Text style={[styles.sectionLabel, { marginTop: spacing["2xl"] }]}>PAST DESIGNS</Text>
            <View style={styles.gallery}>
              {renders.map((r) => (
                <Pressable key={r.id} style={styles.galleryItem} onPress={() => setViewer(r)} testID={`landscape-render-${r.id}`}>
                  <Image source={{ uri: asUri(r.output_image) }} style={styles.galleryImg} contentFit="cover" />
                </Pressable>
              ))}
            </View>
          </>
        ) : null}
      </ScrollView>

      {/* Photo source sheet */}
      <Sheet visible={sourceSheet} onClose={() => setSourceSheet(false)} title="Add yard photo" testID="landscape-source-sheet">
        <Pressable style={styles.sourceRow} onPress={() => pickPhoto("camera")} testID="landscape-source-camera">
          <Ionicons name="camera-outline" size={22} color={colors.brand} />
          <Text style={styles.sourceText}>Take a photo</Text>
        </Pressable>
        <Pressable style={styles.sourceRow} onPress={() => pickPhoto("library")} testID="landscape-source-library">
          <Ionicons name="images-outline" size={22} color={colors.brand} />
          <Text style={styles.sourceText}>Choose from library</Text>
        </Pressable>
      </Sheet>

      {/* Attach picker sheet */}
      <Sheet
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title={attachMode === "customer" ? "Attach to customer" : "Attach to lead"}
        testID="landscape-picker-sheet"
      >
        {pickerList.length === 0 ? (
          <Text style={styles.emptyText}>Nothing found.</Text>
        ) : (
          pickerList.map((it) => (
            <Pressable
              key={it.id}
              style={styles.pickerRow}
              onPress={() => chooseAttach(attachMode as any, it.id, it.name)}
              testID={`landscape-pick-${it.id}`}
            >
              <Text style={styles.pickerName}>{it.name}</Text>
              {it.address ? <Text style={styles.pickerSub}>{it.address}</Text> : null}
            </Pressable>
          ))
        )}
      </Sheet>

      {/* Viewer sheet */}
      <Sheet visible={!!viewer} onClose={() => setViewer(null)} title="Design" testID="landscape-viewer-sheet">
        {viewer ? (
          <View>
            <View style={styles.beforeAfter}>
              <View style={styles.baItem}>
                <Text style={styles.baLabel}>BEFORE</Text>
                <Image source={{ uri: asUri(viewer.input_image) }} style={styles.baImg} contentFit="cover" />
              </View>
              <View style={styles.baItem}>
                <Text style={styles.baLabel}>AFTER</Text>
                <Image source={{ uri: asUri(viewer.output_image) }} style={styles.baImg} contentFit="cover" />
              </View>
            </View>
            {viewer.style ? <Text style={styles.viewerMeta}>Style: {viewer.style}</Text> : null}
            {viewer.elements?.length ? <Text style={styles.viewerMeta}>Features: {viewer.elements.join(", ")}</Text> : null}
            <View style={{ height: spacing.md }} />
            <PrimaryButton title="Save / Share" icon="share-outline" variant="outline" onPress={() => saveImage(viewer.output_image)} testID="landscape-viewer-save" />
            <View style={{ height: spacing.sm }} />
            <Pressable style={styles.deleteBtn} onPress={() => deleteRender(viewer.id)} testID="landscape-viewer-delete">
              <Ionicons name="trash-outline" size={18} color={colors.error} />
              <Text style={styles.deleteText}>Delete design</Text>
            </Pressable>
          </View>
        ) : null}
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  sectionLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.sm },
  dropzone: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderStyle: "dashed",
    padding: spacing["2xl"],
    alignItems: "center",
  },
  dropIcon: { width: 56, height: 56, borderRadius: 28, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center", marginBottom: spacing.md },
  dropTitle: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  dropSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2, textAlign: "center" },
  photoWrap: { borderRadius: radius.lg, overflow: "hidden", borderWidth: 1, borderColor: colors.border },
  photo: { width: "100%", height: 220 },
  photoChange: {
    position: "absolute",
    bottom: spacing.sm,
    right: spacing.sm,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "rgba(10,25,40,0.7)",
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: radius.pill,
  },
  photoChangeText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: "#fff" },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    height: 38,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  chipTextOn: { color: "#fff" },
  textarea: {
    backgroundColor: colors.surface,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    minHeight: 80,
    textAlignVertical: "top",
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}),
  },
  attachBtns: { flexDirection: "row", gap: spacing.sm },
  attachBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    height: 46,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  attachBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  attachRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    height: 46,
  },
  attachText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onBrandTertiary },
  genHint: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, marginTop: spacing.md },
  genHintText: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  resultCard: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border, padding: spacing.lg, marginTop: spacing.xl },
  resultTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.md },
  beforeAfter: { flexDirection: "row", gap: spacing.sm },
  baItem: { flex: 1 },
  baLabel: { fontFamily: font.semibold, fontSize: 10, letterSpacing: 0.8, color: colors.muted, marginBottom: 4 },
  baImg: { width: "100%", height: 130, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary },
  resultActions: { marginTop: spacing.lg },
  gallery: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  galleryItem: { width: "31.5%", aspectRatio: 1, borderRadius: radius.md, overflow: "hidden", borderWidth: 1, borderColor: colors.border },
  galleryImg: { width: "100%", height: "100%" },
  sourceRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md },
  sourceText: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  pickerRow: { paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  pickerName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  pickerSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
  emptyText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, textAlign: "center", paddingVertical: spacing.lg },
  viewerMeta: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginTop: spacing.sm },
  deleteBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 46 },
  deleteText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.error },
});
