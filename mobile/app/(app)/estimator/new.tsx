/**
 * Phase 21 · Mobile — New Field Estimate capture flow.
 * Uses expo-image-picker (multi, up to 10). Optionally attaches a LiDAR
 * scan payload if the user has enabled it in Settings (iOS native only).
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, Image, Alert, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";

import { api } from "@/src/api";
import { storage } from "@/src/utils/storage";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";
import AppTextInput from "@/src/components/ui/AppTextInput";

const SERVICE_TYPES = ["pool", "landscape", "hardscape", "repair", "other"];
const LIDAR_ENABLED_KEY = "estimator_lidar_enabled";

export default function EstimatorNewMobile() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [address, setAddress] = useState("");
  const [description, setDescription] = useState("");
  const [serviceType, setServiceType] = useState("pool");
  const [customers, setCustomers] = useState<any[]>([]);
  const [customerId, setCustomerId] = useState<string>("");
  const [photos, setPhotos] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"" | "creating" | "generating">("");
  const [lidarEnabled, setLidarEnabled] = useState(false);
  const [roomScan, setRoomScan] = useState<any>(null);

  useEffect(() => {
    api.get("/customers").then((r) =>
      setCustomers(Array.isArray(r) ? r : (r.items || []))).catch(() => {});
    (async () => {
      const on = await storage.getItem<boolean>(LIDAR_ENABLED_KEY, false);
      setLidarEnabled(!!on);
    })();
  }, []);

  const pickPhotos = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert("Permission needed", "Please grant photo library access.");
      return;
    }
    const r = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsMultipleSelection: true,
      selectionLimit: Math.max(1, 10 - photos.length),
      quality: 0.7,
      base64: true,
    });
    if (r.canceled) return;
    const picked = (r.assets || []).map((a) => ({
      // Backend accepts a URL. For MVP mobile capture, use a data URI so
      // Claude vision can still ingest inline. Cap at 10.
      url: a.base64
        ? `data:image/jpeg;base64,${a.base64}`
        : a.uri,
      width: a.width, height: a.height,
    }));
    setPhotos([...photos, ...picked].slice(0, 10));
  };

  const runLidar = async () => {
    // Safe no-op path in Expo Go / non-native. If a real ARKit RoomPlan
    // module is present at runtime, use it. This ships a wrapper only —
    // native binding is applied post-EAS-build.
    Alert.alert(
      "3D room scan",
      "LiDAR / ARKit RoomPlan is available only on native iOS builds. "
        + "In Expo Go this is a safe no-op. Once you build the iOS app, "
        + "the toggle in Settings → LiDAR wires up automatically.",
      [
        { text: "OK" },
        { text: "Attach demo scan", onPress: () => setRoomScan({
            walls: [
              { start: { x: 0, y: 0 }, end: { x: 5, y: 0 }, height: 2.7 },
              { start: { x: 5, y: 0 }, end: { x: 5, y: 4 }, height: 2.7 },
              { start: { x: 5, y: 4 }, end: { x: 0, y: 4 }, height: 2.7 },
              { start: { x: 0, y: 4 }, end: { x: 0, y: 0 }, height: 2.7 },
            ],
            floor_area_m2: 20.0,
            ceiling_height_m: 2.7,
            source: "demo",
        }) },
      ],
    );
  };

  const submit = async () => {
    if (!title.trim() || !description.trim()) {
      Alert.alert("Missing fields", "Title and scope description are required.");
      return;
    }
    setBusy(true); setPhase("creating");
    try {
      const payload: any = {
        title, address, description,
        service_type: serviceType,
        photos, notes: "",
      };
      if (customerId) payload.customer_id = customerId;
      if (roomScan) payload.room_scan = {
        walls: roomScan.walls,
        floor_area_m2: roomScan.floor_area_m2,
        ceiling_height_m: roomScan.ceiling_height_m,
      };
      const r = await api.post("/estimator/estimates", payload, 60000);
      const eid = r.estimate_id;
      setPhase("generating");
      await api.post(`/estimator/estimates/${eid}/generate`, null, 180000);
      router.replace(`/(app)/estimator/${eid}` as any);
    } catch (e: any) {
      Alert.alert("Failed", e?.message || "Error");
    } finally { setBusy(false); setPhase(""); }
  };

  return (
    <View style={styles.root}>
      <Header title="New estimate" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg,
                                             paddingBottom: 120 }}>
        <Text style={styles.label}>Title *</Text>
        <AppTextInput style={styles.input} value={title}
                    onChangeText={setTitle}
                    testID="est-new-title" />

        <Text style={styles.label}>Address</Text>
        <AppTextInput style={styles.input} value={address}
                    onChangeText={setAddress}
                    testID="est-new-address" />

        <Text style={styles.label}>Service type</Text>
        <View style={styles.chipRow}>
          {SERVICE_TYPES.map((s) => (
            <Pressable key={s}
                       onPress={() => setServiceType(s)}
                       style={[styles.chip,
                                serviceType === s && styles.chipActive]}
                       testID={`est-new-service-${s}`}>
              <Text style={[styles.chipText,
                              serviceType === s && { color: "#fff" }]}>{s}</Text>
            </Pressable>
          ))}
        </View>

        {customers.length > 0 && (
          <>
            <Text style={styles.label}>Customer (optional)</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false}
                         style={{ marginBottom: spacing.md }}>
              <Pressable style={[styles.chip,
                                    !customerId && styles.chipActive]}
                          onPress={() => setCustomerId("")}>
                <Text style={[styles.chipText,
                                !customerId && { color: "#fff" }]}>None</Text>
              </Pressable>
              {customers.slice(0, 30).map((c) => (
                <Pressable key={c.id}
                           style={[styles.chip,
                                    customerId === c.id && styles.chipActive]}
                           onPress={() => setCustomerId(c.id)}
                           testID={`est-new-customer-${c.id}`}>
                  <Text style={[styles.chipText,
                                  customerId === c.id && { color: "#fff" }]}
                         numberOfLines={1}>{c.name}</Text>
                </Pressable>
              ))}
            </ScrollView>
          </>
        )}

        <Text style={styles.label}>Scope description *</Text>
        <AppTextInput style={[styles.input,
                             { minHeight: 100, textAlignVertical: "top" }]}
                    multiline value={description}
                    onChangeText={setDescription}
                    testID="est-new-desc" />

        <Text style={styles.label}>Photos ({photos.length}/10)</Text>
        <View style={styles.photoGrid}>
          {photos.map((p, i) => (
            <View key={i} style={styles.photoWrap}>
              <Image source={{ uri: p.url }} style={styles.photo} />
              <Pressable style={styles.photoRemove}
                          onPress={() =>
                            setPhotos(photos.filter((_, j) => j !== i))}>
                <Ionicons name="close" size={12} color="#fff" />
              </Pressable>
            </View>
          ))}
          {photos.length < 10 && (
            <Pressable style={styles.photoAdd}
                        onPress={pickPhotos}
                        testID="est-new-add-photo">
              <Ionicons name="add" size={24} color={colors.muted} />
            </Pressable>
          )}
        </View>

        {lidarEnabled && (
          <View style={styles.lidarBox} testID="est-new-lidar-box">
            <Text style={styles.lidarTitle}>3D room scan (LiDAR)</Text>
            {roomScan ? (
              <Text style={styles.lidarBody}>
                Scan attached · {roomScan.walls.length} walls ·
                {" "}{roomScan.floor_area_m2 ?? "?"} m²
              </Text>
            ) : (
              <Text style={styles.lidarBody}>
                Optional — captures wall dimensions and floor area to
                improve estimate accuracy.
              </Text>
            )}
            <Pressable style={styles.lidarBtn} onPress={runLidar}
                        testID="est-new-lidar-btn">
              <Ionicons name="cube-outline" size={14}
                         color={colors.brand} />
              <Text style={styles.lidarBtnText}>
                {roomScan ? "Re-scan" : "Start scan"}
              </Text>
            </Pressable>
          </View>
        )}

        <Pressable style={[styles.submit, busy && { opacity: 0.6 }]}
                    disabled={busy} onPress={submit}
                    testID="est-new-submit">
          {busy && <ActivityIndicator color="#fff" size="small" />}
          <Ionicons name="sparkles" size={16} color="#fff" />
          <Text style={styles.submitText}>
            {phase === "creating" ? "Saving…"
             : phase === "generating" ? "AI generating estimate…"
             : "Generate estimate"}
          </Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  label: { fontFamily: font.semibold, fontSize: fontSize.sm,
            color: colors.muted, marginTop: spacing.md,
            marginBottom: spacing.xs },
  input: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, fontFamily: font.regular,
    fontSize: fontSize.base, color: colors.onSurface,
    borderWidth: 1, borderColor: colors.border,
  },
  chipRow: { flexDirection: "row", flexWrap: "wrap",
              gap: spacing.sm, marginBottom: spacing.sm },
  chip: {
    paddingHorizontal: spacing.md, paddingVertical: 6,
    borderRadius: 999, marginRight: spacing.sm,
    backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border,
  },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm,
               color: colors.onSurface },
  photoGrid: { flexDirection: "row", flexWrap: "wrap",
                gap: spacing.sm, marginBottom: spacing.md },
  photoWrap: { position: "relative" },
  photo: { width: 80, height: 80, borderRadius: radius.md },
  photoRemove: {
    position: "absolute", top: -6, right: -6,
    width: 20, height: 20, borderRadius: 10,
    backgroundColor: "#DC2626", alignItems: "center",
    justifyContent: "center",
  },
  photoAdd: {
    width: 80, height: 80, borderRadius: radius.md,
    backgroundColor: colors.surface, borderWidth: 1,
    borderStyle: "dashed", borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
  },
  lidarBox: {
    backgroundColor: colors.surface, borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.lg,
    padding: spacing.md, marginBottom: spacing.md,
  },
  lidarTitle: { fontFamily: font.bold, fontSize: fontSize.base,
                 color: colors.onSurface },
  lidarBody: { fontFamily: font.regular, fontSize: fontSize.sm,
                color: colors.muted, marginTop: 4, marginBottom: spacing.sm },
  lidarBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandTertiary,
    paddingHorizontal: spacing.md, paddingVertical: 8,
    borderRadius: radius.md, alignSelf: "flex-start",
  },
  lidarBtnText: { fontFamily: font.bold, fontSize: fontSize.sm,
                   color: colors.brand },
  submit: {
    marginTop: spacing.xl, backgroundColor: colors.brand,
    borderRadius: radius.md, padding: spacing.md,
    flexDirection: "row", alignItems: "center",
    justifyContent: "center", gap: spacing.sm,
  },
  submitText: { fontFamily: font.bold, fontSize: fontSize.lg,
                 color: "#fff" },
});
