import React, { useCallback, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
  Alert,
  Linking,
  ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import * as Location from "expo-location";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { AdminOnly } from "@/src/components/AdminOnly";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { useToast } from "@/src/components/ToastProvider";
import { Sheet, PrimaryButton } from "@/src/components/ui";
// Resolved by Metro via .native.tsx / .web.tsx platform extensions.
// eslint-disable-next-line import/no-unresolved
import MeasureMap from "@/src/components/measure/MeasureMap";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Coord = { latitude: number; longitude: number };
type Mode = "distance" | "area";

const DEFAULT_REGION = { latitude: 33.7405, longitude: -112.3373, latitudeDelta: 0.01, longitudeDelta: 0.01 };

const toRad = (d: number) => (d * Math.PI) / 180;

function segMeters(a: Coord, b: Coord) {
  const R = 6371000;
  const dLat = toRad(b.latitude - a.latitude);
  const dLng = toRad(b.longitude - a.longitude);
  const la1 = toRad(a.latitude);
  const la2 = toRad(b.latitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function pathMeters(pts: Coord[]) {
  let d = 0;
  for (let i = 1; i < pts.length; i++) d += segMeters(pts[i - 1], pts[i]);
  return d;
}
function polygonAreaM2(pts: Coord[]) {
  if (pts.length < 3) return 0;
  const R = 6378137;
  let area = 0;
  for (let i = 0; i < pts.length; i++) {
    const p1 = pts[i];
    const p2 = pts[(i + 1) % pts.length];
    area += toRad(p2.longitude - p1.longitude) * (2 + Math.sin(toRad(p1.latitude)) + Math.sin(toRad(p2.latitude)));
  }
  return Math.abs((area * R * R) / 2);
}
function polygonPerimeterM(pts: Coord[]) {
  if (pts.length < 2) return 0;
  const closed = [...pts, pts[0]];
  return pathMeters(closed);
}

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: n < 100 ? 1 : 0 });

export default function Measure() {
  return (
    <AdminOnly>
      <MeasureScreen />
    </AdminOnly>
  );
}

function MeasureScreen() {
  const insets = useSafeAreaInsets();
  const { showToast } = useToast();
  const router = useRouter();
  const mapRef = useRef<any>(null);

  const [mode, setMode] = useState<Mode>("distance");
  const [points, setPoints] = useState<Coord[]>([]);
  const [region, setRegion] = useState<any>(DEFAULT_REGION);
  const [search, setSearch] = useState("");
  const [locating, setLocating] = useState(false);
  const [searching, setSearching] = useState(false);

  const { user } = useAuth();
  const isAdmin = user?.role === "admin" || user?.role === "super_admin";
  const [saveOpen, setSaveOpen] = useState(false);
  const [mName, setMName] = useState("");
  const [attachId, setAttachId] = useState<string | null>(null);
  const [attachKind, setAttachKind] = useState<"customer" | "lead" | null>(null);
  const [attachLabel, setAttachLabel] = useState("");
  const [pickerMode, setPickerMode] = useState<"customer" | "lead" | null>(null);
  const [customers, setCustomers] = useState<any[]>([]);
  const [leads, setLeads] = useState<any[]>([]);
  const [saving, setSaving] = useState(false);

  const addPoint = useCallback((c: Coord) => setPoints((p) => [...p, c]), []);
  const undo = () => setPoints((p) => p.slice(0, -1));
  const clear = () => setPoints([]);

  const goTo = (lat: number, lng: number) => {
    const r = { latitude: lat, longitude: lng, latitudeDelta: 0.004, longitudeDelta: 0.004 };
    setRegion(r);
    if (mapRef.current?.animateToRegion) mapRef.current.animateToRegion(r, 600);
  };

  const myLocation = async () => {
    setLocating(true);
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (!perm.granted) {
        if (!perm.canAskAgain) {
          Alert.alert("Location needed", "Enable location to center the map on you.", [
            { text: "Cancel", style: "cancel" },
            { text: "Open Settings", onPress: () => Linking.openSettings() },
          ]);
        }
        return;
      }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      goTo(pos.coords.latitude, pos.coords.longitude);
    } catch {
      Alert.alert("Location error", "Could not get your current location.");
    } finally {
      setLocating(false);
    }
  };

  const doSearch = async () => {
    if (!search.trim()) return;
    setSearching(true);
    try {
      const res = await Location.geocodeAsync(search.trim());
      if (res?.[0]) goTo(res[0].latitude, res[0].longitude);
      else Alert.alert("Not found", "No location matched that address.");
    } catch {
      Alert.alert("Search failed", "Could not look up that address.");
    } finally {
      setSearching(false);
    }
  };

  const openSave = async () => {
    if ((mode === "distance" && points.length < 2) || (mode === "area" && points.length < 3)) {
      Alert.alert("Nothing to save", mode === "area" ? "Tap at least 3 points to enclose an area." : "Tap at least 2 points to measure a distance.");
      return;
    }
    setSaveOpen(true);
    if (customers.length === 0 && leads.length === 0) {
      try {
        const [c, l] = await Promise.all([api.get("/customers"), api.get("/leads")]);
        setCustomers(c || []);
        setLeads(l || []);
      } catch {}
    }
  };

  const chooseAttach = (kind: "customer" | "lead", cid: string, label: string) => {
    setAttachKind(kind);
    setAttachId(cid);
    setAttachLabel(`${kind === "customer" ? "Customer" : "Lead"}: ${label}`);
    setPickerMode(null);
  };

  const computePayloadMetrics = () => {
    const distM = mode === "distance" ? pathMeters(points) : polygonPerimeterM(points);
    const areaM2 = polygonAreaM2(points);
    return {
      distance_ft: mode === "distance" ? distM * 3.28084 : 0,
      perimeter_ft: mode === "area" ? distM * 3.28084 : 0,
      area_sqft: mode === "area" ? areaM2 * 10.7639 : 0,
      acres: mode === "area" ? areaM2 / 4046.8564 : 0,
    };
  };

  const doSave = async () => {
    setSaving(true);
    try {
      await api.post("/measurements", {
        name: mName || (mode === "area" ? "Area measurement" : "Distance measurement"),
        mode,
        points,
        customer_id: attachKind === "customer" ? attachId : null,
        lead_id: attachKind === "lead" ? attachId : null,
        ...computePayloadMetrics(),
      });
      setSaveOpen(false);
      showToast(attachLabel ? `Measurement saved to ${attachLabel.replace(/^.*?: /, "")}.` : "Measurement saved.");
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const useInEstimate = () => {
    if (mode !== "area" || points.length < 3) {
      Alert.alert("Measure an area first", "Enclose the lawn/pool area (tap 3+ points) so it can be priced.");
      return;
    }
    const areaFtNum = Math.round(polygonAreaM2(points) * 10.7639);
    const p: any = {
      id: "new",
      title: mName || `Area estimate — ${areaFtNum.toLocaleString()} sq ft`,
      lineDesc: `${mName || "Measured area"} (${areaFtNum.toLocaleString()} sq ft)`,
      lineQty: String(areaFtNum),
      lineCost: "0",
      category: "Material",
    };
    if (attachKind === "customer" && attachId) {
      p.customerId = attachId;
      p.customerName = attachLabel.replace(/^Customer: /, "");
    }
    router.push({ pathname: "/estimator/[id]", params: p });
  };

  // measurements
  const distM = mode === "distance" ? pathMeters(points) : polygonPerimeterM(points);
  const distFt = distM * 3.28084;
  const distMi = distM / 1609.344;
  const areaM2 = polygonAreaM2(points);
  const areaFt = areaM2 * 10.7639;
  const areaAc = areaM2 / 4046.8564;

  return (
    <View style={styles.root}>
      <MeasureMap mode={mode} points={points} region={region} onRegionChange={setRegion} onPress={addPoint} mapRef={mapRef} />

      {/* Top controls */}
      <View style={[styles.top, { paddingTop: insets.top + spacing.sm }]}>
        <View style={styles.searchRow}>
          <Pressable style={styles.circleBtn} onPress={() => router.back()} hitSlop={8} testID="measure-back">
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={styles.searchBox}>
            <Ionicons name="search" size={16} color={colors.muted} />
            <AppTextInput
              style={styles.searchInput}
              value={search}
              onChangeText={setSearch}
              placeholder="Search address or place"
              placeholderTextColor={colors.muted}
              returnKeyType="search"
              onSubmitEditing={doSearch}
              testID="measure-search"
            />
            {searching ? <ActivityIndicator size="small" color={colors.brand} /> : null}
          </View>
        </View>

        <View style={styles.modeRow}>
          {(["distance", "area"] as Mode[]).map((m) => (
            <Pressable key={m} style={[styles.modeBtn, mode === m && styles.modeBtnOn]} onPress={() => setMode(m)} testID={`measure-mode-${m}`}>
              <Ionicons name={m === "distance" ? "resize-outline" : "scan-outline"} size={16} color={mode === m ? "#fff" : colors.onSurface} />
              <Text style={[styles.modeText, mode === m && { color: "#fff" }]}>{m === "distance" ? "Distance" : "Area"}</Text>
            </Pressable>
          ))}
        </View>
      </View>

      {/* My location */}
      <Pressable style={[styles.locBtn, { bottom: 190 + insets.bottom }]} onPress={myLocation} testID="measure-locate">
        {locating ? <ActivityIndicator size="small" color={colors.brand} /> : <Ionicons name="locate" size={22} color={colors.brand} />}
      </Pressable>

      {/* Result panel */}
      <View style={[styles.panel, { paddingBottom: insets.bottom + spacing.md }]}>
        <View style={styles.resultRow}>
          <View style={{ flex: 1 }}>
            {mode === "distance" ? (
              <>
                <Text style={styles.resultLabel}>TOTAL DISTANCE</Text>
                <Text style={styles.resultValue}>{points.length > 1 ? `${fmt(distFt)} ft` : "—"}</Text>
                {points.length > 1 ? <Text style={styles.resultSub}>{distMi < 0.19 ? `${fmt(distM)} m` : `${distMi.toFixed(2)} mi`} · {points.length} points</Text> : <Text style={styles.resultSub}>Tap the map to drop points</Text>}
              </>
            ) : (
              <>
                <Text style={styles.resultLabel}>AREA</Text>
                <Text style={styles.resultValue}>{points.length > 2 ? `${fmt(areaFt)} sq ft` : "—"}</Text>
                {points.length > 2 ? (
                  <Text style={styles.resultSub}>{areaAc.toFixed(areaAc < 1 ? 3 : 2)} acres · {fmt(distFt)} ft perimeter</Text>
                ) : (
                  <Text style={styles.resultSub}>Tap 3+ points to enclose an area</Text>
                )}
              </>
            )}
          </View>
        </View>
        <View style={styles.actions}>
          <Pressable style={styles.primaryAct} onPress={openSave} testID="measure-save-open">
            <Ionicons name="bookmark-outline" size={18} color="#fff" />
            <Text style={styles.primaryActText}>Save</Text>
          </Pressable>
          {isAdmin ? (
            <Pressable style={styles.secondaryAct} onPress={useInEstimate} testID="measure-use-estimate">
              <Ionicons name="calculator-outline" size={18} color={colors.brand} />
              <Text style={styles.secondaryActText}>Use in Estimate</Text>
            </Pressable>
          ) : null}
        </View>
        <View style={styles.actions}>
          <Pressable style={[styles.actBtn, points.length === 0 && styles.actDisabled]} onPress={undo} disabled={points.length === 0} testID="measure-undo">
            <Ionicons name="arrow-undo-outline" size={18} color={colors.onSurface} />
            <Text style={styles.actText}>Undo</Text>
          </Pressable>
          <Pressable style={[styles.actBtn, points.length === 0 && styles.actDisabled]} onPress={clear} disabled={points.length === 0} testID="measure-clear">
            <Ionicons name="trash-outline" size={18} color={colors.error} />
            <Text style={[styles.actText, { color: colors.error }]}>Clear</Text>
          </Pressable>
        </View>
      </View>

      {/* Save sheet */}
      <Sheet visible={saveOpen} onClose={() => setSaveOpen(false)} title="Save measurement" testID="measure-save-sheet">
        <Text style={styles.inputLabel}>NAME</Text>
        <AppTextInput style={styles.sheetInput} value={mName} onChangeText={setMName} placeholder={mode === "area" ? "Backyard lawn" : "Fence run"} placeholderTextColor={colors.muted} testID="measure-name" />
        <Text style={[styles.inputLabel, { marginTop: spacing.md }]}>ATTACH TO (OPTIONAL)</Text>
        {attachLabel ? (
          <View style={styles.attachRow}>
            <Text style={styles.attachText}>{attachLabel}</Text>
            <Pressable onPress={() => { setAttachKind(null); setAttachId(null); setAttachLabel(""); }} hitSlop={8} testID="measure-attach-clear">
              <Ionicons name="close-circle" size={18} color={colors.muted} />
            </Pressable>
          </View>
        ) : (
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <Pressable style={styles.attachBtn} onPress={() => setPickerMode("customer")} testID="measure-attach-customer">
              <Ionicons name="person-outline" size={16} color={colors.brand} />
              <Text style={styles.attachBtnText}>Customer</Text>
            </Pressable>
            <Pressable style={styles.attachBtn} onPress={() => setPickerMode("lead")} testID="measure-attach-lead">
              <Ionicons name="magnet-outline" size={16} color={colors.brand} />
              <Text style={styles.attachBtnText}>Lead</Text>
            </Pressable>
          </View>
        )}
        <View style={{ height: spacing.lg }} />
        <PrimaryButton title={saving ? "Saving…" : "Save measurement"} icon="bookmark-outline" loading={saving} onPress={doSave} testID="measure-save-confirm" />
      </Sheet>

      {/* Attach picker */}
      <Sheet visible={!!pickerMode} onClose={() => setPickerMode(null)} title={pickerMode === "customer" ? "Attach to customer" : "Attach to lead"} testID="measure-picker-sheet">
        {(pickerMode === "customer" ? customers : leads).length === 0 ? (
          <Text style={styles.resultSub}>Nothing found.</Text>
        ) : (
          (pickerMode === "customer" ? customers : leads).map((it: any) => (
            <Pressable key={it.id} style={styles.pickerRow} onPress={() => chooseAttach(pickerMode as any, it.id, it.name)} testID={`measure-pick-${it.id}`}>
              <Text style={styles.pickerName}>{it.name}</Text>
              {it.address ? <Text style={styles.pickerSub}>{it.address}</Text> : null}
            </Pressable>
          ))
        )}
      </Sheet>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#0B1220" },
  top: { position: "absolute", top: 0, left: 0, right: 0, paddingHorizontal: spacing.md, gap: spacing.sm },
  searchRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  circleBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center", shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  searchBox: { flex: 1, flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.surface, borderRadius: radius.pill, paddingHorizontal: spacing.md, height: 44, shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  searchInput: { flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  modeRow: { flexDirection: "row", gap: spacing.sm, alignSelf: "center", backgroundColor: colors.surface, borderRadius: radius.pill, padding: 4, shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 3 },
  modeBtn: { flexDirection: "row", alignItems: "center", gap: 5, paddingHorizontal: spacing.lg, height: 36, borderRadius: radius.pill },
  modeBtnOn: { backgroundColor: colors.brand },
  modeText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  locBtn: { position: "absolute", right: spacing.lg, width: 48, height: 48, borderRadius: 24, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center", shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 6, shadowOffset: { width: 0, height: 2 }, elevation: 4 },
  panel: { position: "absolute", left: 0, right: 0, bottom: 0, backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, paddingHorizontal: spacing.lg, paddingTop: spacing.lg, gap: spacing.md },
  resultRow: { flexDirection: "row", alignItems: "center" },
  resultLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary },
  resultValue: { fontFamily: font.bold, fontSize: fontSize["3xl"], color: colors.brand, marginTop: 2 },
  resultSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 2 },
  actions: { flexDirection: "row", gap: spacing.md },
  actBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 48, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.border },
  actDisabled: { opacity: 0.4 },
  actText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  primaryAct: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 48, borderRadius: radius.md, backgroundColor: colors.brand },
  primaryActText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  secondaryAct: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 48, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.brand },
  secondaryActText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  inputLabel: { fontFamily: font.semibold, fontSize: 11, letterSpacing: 0.8, color: colors.onSurfaceSecondary, marginBottom: spacing.xs },
  sheetInput: { backgroundColor: colors.surfaceSecondary, borderWidth: 1.5, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 48, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  attachBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 46, borderRadius: radius.md, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  attachBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  attachRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, backgroundColor: colors.brandTertiary, borderRadius: radius.md, paddingHorizontal: spacing.md, height: 46 },
  attachText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onBrandTertiary },
  pickerRow: { paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  pickerName: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  pickerSub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: 1 },
});
