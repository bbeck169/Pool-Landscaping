import React, { useState } from "react";
import { View, Text, Pressable, TextInput, Platform, ScrollView , StyleSheet } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { styles as jobStyles } from "./styles";


const CONDITIONS: Record<string, string[]> = {
  filter: ["Clean", "Light debris", "Heavy debris", "Needs replacement"],
  salt_cell: ["Clean", "Light scale", "Heavy scale", "Needs replacement"],
};

export default function MaintenanceLog({
  job,
  mtype,
  readOnly,
  online,
  onSaved,
}: {
  job: any;
  mtype: "filter" | "salt_cell";
  readOnly: boolean;
  online: boolean;
  onSaved: (j: any) => void;
}) {
  const existing = job.maintenance || {};
  const [psi, setPsi] = useState<string>(existing.psi != null ? String(existing.psi) : "");
  const [saltPpm, setSaltPpm] = useState<string>(existing.salt_ppm != null ? String(existing.salt_ppm) : "");
  const [condition, setCondition] = useState<string>(
    mtype === "filter" ? existing.filter_condition || "" : existing.cell_condition || ""
  );
  const [notes, setNotes] = useState<string>(existing.notes || "");
  const [photos, setPhotos] = useState<any[]>(existing.photos || []);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(existing.logged_at || null);

  const isFilter = mtype === "filter";
  const title = isFilter ? "Filter Cleaning Log" : "Salt Cell Cleaning Log";

  const addPhoto = async (label: string) => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({ base64: true, quality: 0.4, allowsEditing: true });
    if (res.canceled || !res.assets?.[0]?.base64) return;
    setPhotos((p) => [...p, { label, data: `data:image/jpeg;base64,${res.assets[0].base64}` }]);
  };

  const removePhoto = (idx: number) => setPhotos((p) => p.filter((_, i) => i !== idx));

  const save = async () => {
    setSaving(true);
    try {
      const body: any = { notes };
      if (isFilter) {
        body.psi = psi ? parseFloat(psi) : null;
        body.filter_condition = condition || null;
      } else {
        body.salt_ppm = saltPpm ? parseFloat(saltPpm) : null;
        body.cell_condition = condition || null;
      }
      body.photos = photos.map((p) => ({ label: p.label, data: p.data }));
      const { data: updated, queued } = await offlineWrite({
        op_type: "maintenance_log.create",
        entity_id: job.id,
        endpoint: `/jobs/${job.id}/maintenance-log`,
        method: "POST",
        payload: body,
        onlineFn: () => api.post(`/jobs/${job.id}/maintenance-log`, body),
      });
      if (updated) onSaved(updated);
      setSavedAt(new Date().toISOString());
    } catch {}
    finally { setSaving(false); }
  };

  // Read-only summary for the customer view.
  if (readOnly) {
    if (!existing.logged_at && !(existing.photos || []).length) return null;
    return (
      <>
        <View style={jobStyles.reportHeader}>
          <Ionicons name={isFilter ? "filter" : "flash"} size={18} color={colors.brand} />
          <Text style={jobStyles.reportTitle}>{isFilter ? "Filter Cleaning" : "Salt Cell Cleaning"}</Text>
        </View>
        <View style={jobStyles.reportCard}>
          {isFilter && existing.psi != null ? <Row label="Filter pressure" value={`${existing.psi} PSI`} /> : null}
          {!isFilter && existing.salt_ppm != null ? <Row label="Salt level" value={`${existing.salt_ppm} ppm`} /> : null}
          {existing.filter_condition ? <Row label="Condition" value={existing.filter_condition} /> : null}
          {existing.cell_condition ? <Row label="Cell condition" value={existing.cell_condition} /> : null}
          {existing.notes ? <Text style={ml.notes}>{existing.notes}</Text> : null}
          <PhotoStrip photos={existing.photos || []} />
        </View>
      </>
    );
  }

  return (
    <>
      <View style={jobStyles.reportHeader}>
        <Ionicons name={isFilter ? "filter" : "flash"} size={18} color={colors.brand} />
        <Text style={jobStyles.reportTitle}>{title}</Text>
        {savedAt ? (
          <>
            <View style={{ flex: 1 }} />
            <View style={ml.savedChip}>
              <Ionicons name="checkmark-circle" size={13} color={colors.success} />
              <Text style={ml.savedChipText}>Logged</Text>
            </View>
          </>
        ) : null}
      </View>
      <View style={jobStyles.reportCard}>
        {isFilter ? (
          <View style={ml.fieldRow}>
            <Text style={ml.fieldLabel}>Filter pressure</Text>
            <View style={ml.psiWrap}>
              <TextInput
                style={ml.psiInput}
                value={psi}
                onChangeText={setPsi}
                keyboardType="decimal-pad"
                placeholder="—"
                placeholderTextColor={colors.muted}
                testID="maint-psi-input"
              />
              <Text style={ml.psiUnit}>PSI</Text>
            </View>
          </View>
        ) : (
          <View style={ml.fieldRow}>
            <Text style={ml.fieldLabel}>Salt level</Text>
            <View style={ml.psiWrap}>
              <TextInput
                style={ml.psiInput}
                value={saltPpm}
                onChangeText={setSaltPpm}
                keyboardType="decimal-pad"
                placeholder="—"
                placeholderTextColor={colors.muted}
                testID="maint-salt-input"
              />
              <Text style={ml.psiUnit}>ppm</Text>
            </View>
          </View>
        )}

        <Text style={[ml.fieldLabel, { marginTop: spacing.sm, marginBottom: spacing.xs }]}>Condition</Text>
        <View style={ml.chipRow}>
          {CONDITIONS[mtype].map((c) => (
            <Pressable
              key={c}
              style={[ml.chip, condition === c && ml.chipOn]}
              onPress={() => setCondition(c)}
              testID={`maint-cond-${c}`}
            >
              <Text style={[ml.chipText, condition === c && ml.chipTextOn]}>{c}</Text>
            </Pressable>
          ))}
        </View>

        <Text style={[ml.fieldLabel, { marginTop: spacing.md, marginBottom: spacing.xs }]}>Before / after photos</Text>
        <View style={ml.photoBtnRow}>
          <Pressable style={ml.photoBtn} onPress={() => addPhoto("Before")} testID="maint-add-before">
            <Ionicons name="camera-outline" size={16} color={colors.brand} />
            <Text style={ml.photoBtnText}>Before</Text>
          </Pressable>
          <Pressable style={ml.photoBtn} onPress={() => addPhoto("After")} testID="maint-add-after">
            <Ionicons name="camera-outline" size={16} color={colors.brand} />
            <Text style={ml.photoBtnText}>After</Text>
          </Pressable>
        </View>
        {photos.length ? (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm, marginTop: spacing.sm }}>
            {photos.map((p, i) => (
              <View key={i} style={ml.thumb} testID={`maint-photo-${i}`}>
                <Image source={{ uri: p.data }} style={ml.thumbImg} contentFit="cover" />
                <View style={ml.thumbLabel}><Text style={ml.thumbLabelText}>{p.label}</Text></View>
                <Pressable style={ml.thumbDel} onPress={() => removePhoto(i)} hitSlop={6}>
                  <Ionicons name="close" size={12} color="#fff" />
                </Pressable>
              </View>
            ))}
          </ScrollView>
        ) : null}

        <TextInput
          style={ml.notesInput}
          value={notes}
          onChangeText={setNotes}
          placeholder="Notes (e.g. replaced O-ring, cell scaled)…"
          placeholderTextColor={colors.muted}
          multiline
          testID="maint-notes-input"
        />

        <Pressable style={ml.saveBtn} onPress={save} disabled={saving} testID="maint-save">
          <Ionicons name={saving ? "hourglass-outline" : "save-outline"} size={16} color="#fff" />
          <Text style={ml.saveText}>{saving ? "Saving…" : savedAt ? "Update Log" : "Save Log"}</Text>
        </Pressable>
        {!online ? <Text style={jobStyles.offlineHint}>You&apos;re offline — reconnect to save this log.</Text> : null}
      </View>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={ml.roRow}>
      <Text style={ml.roLabel}>{label}</Text>
      <Text style={ml.roValue}>{value}</Text>
    </View>
  );
}

function PhotoStrip({ photos }: { photos: any[] }) {
  if (!photos.length) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: spacing.sm, marginTop: spacing.sm }}>
      {photos.map((p, i) => (
        <View key={i} style={ml.thumb}>
          <Image source={{ uri: p.data }} style={ml.thumbImg} contentFit="cover" />
          <View style={ml.thumbLabel}><Text style={ml.thumbLabelText}>{p.label}</Text></View>
        </View>
      ))}
    </ScrollView>
  );
}
const ml = StyleSheet.create({
  fieldRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  fieldLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  psiWrap: { flexDirection: "row", alignItems: "center", gap: 6 },
  psiInput: { width: 72, height: 44, textAlign: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  psiUnit: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.muted, width: 34 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  chip: { paddingHorizontal: spacing.md, height: 34, borderRadius: radius.pill, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  chipOn: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  chipTextOn: { color: "#fff" },
  photoBtnRow: { flexDirection: "row", gap: spacing.sm },
  photoBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, height: 42, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  photoBtnText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.brand },
  thumb: { width: 92, height: 92, borderRadius: radius.md, overflow: "hidden", backgroundColor: colors.surfaceTertiary },
  thumbImg: { width: "100%", height: "100%" },
  thumbLabel: { position: "absolute", bottom: 4, left: 4, backgroundColor: "rgba(0,0,0,0.6)", paddingHorizontal: 6, paddingVertical: 1, borderRadius: radius.pill },
  thumbLabelText: { color: "#fff", fontFamily: font.semibold, fontSize: 10 },
  thumbDel: { position: "absolute", top: 4, right: 4, width: 20, height: 20, borderRadius: 10, backgroundColor: "rgba(0,0,0,0.6)", alignItems: "center", justifyContent: "center" },
  notesInput: { minHeight: 60, marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, padding: spacing.md, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, textAlignVertical: "top", ...(Platform.OS === "web" ? { outlineStyle: "none" as any } : {}) },
  saveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, marginTop: spacing.md, height: 46, borderRadius: radius.md, backgroundColor: colors.brand },
  saveText: { fontFamily: font.semibold, fontSize: fontSize.base, color: "#fff" },
  savedChip: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill, backgroundColor: "#DCFCE7" },
  savedChipText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.success },
  roRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  roLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.muted },
  roValue: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  notes: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurfaceSecondary, lineHeight: 20, marginTop: spacing.xs },
});
