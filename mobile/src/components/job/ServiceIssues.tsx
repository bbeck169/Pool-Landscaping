import React, { useState } from "react";
import { View, Text, ScrollView, Pressable, TextInput } from "react-native";
import { Image } from "expo-image";
import * as ImagePicker from "expo-image-picker";
import { Ionicons } from "@expo/vector-icons";
import { colors, spacing, money } from "@/src/theme";
import { api } from "@/src/api";
import { offlineWrite } from "@/src/services/offlineWrite";
import { Sheet, PrimaryButton } from "@/src/components/ui";
import { styles } from "./styles";

export default function ServiceIssues({ job, canManage, isCustomer, onSaved }: { job: any; canManage: boolean; isCustomer: boolean; onSaved: (j: any) => void }) {
  const issues = job.service_issues || [];
  const [sheet, setSheet] = useState(false);
  const [desc, setDesc] = useState("");
  const [cost, setCost] = useState("");
  const [photo, setPhoto] = useState("");
  const [busy, setBusy] = useState(false);
  const [approving, setApproving] = useState<string | null>(null);

  if (!canManage && issues.length === 0) return null;

  const pick = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) return;
    const res = await ImagePicker.launchImageLibraryAsync({ base64: true, quality: 0.5, allowsEditing: true });
    if (res.canceled || !res.assets?.[0]?.base64) return;
    setPhoto(`data:image/jpeg;base64,${res.assets[0].base64}`);
  };

  const submit = async () => {
    if (!desc.trim() || busy) return;
    setBusy(true);
    try {
      const body: any = { description: desc.trim() };
      const c = parseFloat(cost);
      if (!isNaN(c) && c > 0) body.cost = c;
      if (photo) body.photo = photo;
      const { data: updated, queued } = await offlineWrite({
        op_type: "issue.create",
        entity_id: job.id,
        endpoint: `/jobs/${job.id}/issues`,
        method: "POST",
        payload: body,
        onlineFn: () => api.post(`/jobs/${job.id}/issues`, body),
      });
      if (updated) onSaved(updated);
      setDesc(""); setCost(""); setPhoto(""); setSheet(false);
    } catch {}
    finally { setBusy(false); }
  };

  const approve = async (iid: string) => {
    setApproving(iid);
    try {
      const { data } = await offlineWrite({
        op_type: "issue.approve",
        entity_id: job.id,
        endpoint: `/jobs/${job.id}/issues/${iid}/approve`,
        method: "POST",
        payload: {},
        onlineFn: () => api.post(`/jobs/${job.id}/issues/${iid}/approve`),
      });
      if (data) onSaved(data);
    } catch {}
    finally { setApproving(null); }
  };

  const remove = async (iid: string) => {
    try { onSaved(await api.del(`/jobs/${job.id}/issues/${iid}`)); } catch {}
  };

  return (
    <View style={{ marginTop: spacing.xl }}>
      <View style={styles.photosHeader}>
        <Text style={styles.photosTitle}>Service Issues ({issues.length})</Text>
        {canManage ? (
          <Pressable style={styles.addPhotoBtn} onPress={() => setSheet(true)} testID="add-issue-button">
            <Ionicons name="warning-outline" size={16} color={colors.brand} />
            <Text style={styles.addPhotoText}>Report</Text>
          </Pressable>
        ) : null}
      </View>

      {issues.length === 0 ? (
        <Text style={styles.noPhotos}>No issues reported for this service.</Text>
      ) : (
        issues.map((it: any) => (
          <View key={it.id} style={styles.issueCard} testID={`issue-${it.id}`}>
            {it.photo ? <Image source={{ uri: it.photo }} style={styles.issueImg} contentFit="cover" /> : null}
            <View style={styles.issueBody}>
              <View style={styles.issueTop}>
                <View style={[styles.issueBadge, it.status === "approved" ? styles.issueBadgeOk : styles.issueBadgeOpen]}>
                  <Ionicons name={it.status === "approved" ? "checkmark-circle" : "alert-circle"} size={12} color="#fff" />
                  <Text style={styles.issueBadgeText}>{it.status === "approved" ? "Fix Approved" : "Open"}</Text>
                </View>
                {canManage ? (
                  <Pressable onPress={() => remove(it.id)} hitSlop={8} testID={`delete-issue-${it.id}`}>
                    <Ionicons name="trash-outline" size={16} color={colors.muted} />
                  </Pressable>
                ) : null}
              </View>
              <Text style={styles.issueDesc}>{it.description}</Text>
              {it.cost ? <Text style={styles.issueCost}>Estimated repair: {money(it.cost)}</Text> : null}
              <Text style={styles.issueMeta}>Reported by {it.reported_by}</Text>
              {isCustomer && it.status !== "approved" ? (
                <Pressable style={styles.approveBtn} onPress={() => approve(it.id)} disabled={!!approving} testID={`approve-issue-${it.id}`}>
                  <Ionicons name="checkmark" size={16} color="#fff" />
                  <Text style={styles.approveText}>{approving === it.id ? "Approving…" : "Approve Fix"}</Text>
                </Pressable>
              ) : null}
              {it.status === "approved" && canManage ? (
                <Text style={styles.issueApprovedNote}>✓ Customer approved the repair</Text>
              ) : null}
            </View>
          </View>
        ))
      )}

      <Sheet visible={sheet} onClose={() => setSheet(false)} title="Report Service Issue" testID="issue-sheet">
        <ScrollView keyboardShouldPersistTaps="handled" style={{ maxHeight: 420 }}>
          <TextInput
            style={styles.issueInput}
            value={desc}
            onChangeText={setDesc}
            placeholder="Describe the issue (e.g. Pump motor is failing)"
            placeholderTextColor={colors.muted}
            multiline
            testID="issue-desc-input"
          />
          <TextInput
            style={[styles.issueInput, { minHeight: 44 }]}
            value={cost}
            onChangeText={setCost}
            placeholder="Estimated repair cost (optional)"
            placeholderTextColor={colors.muted}
            keyboardType="decimal-pad"
            testID="issue-cost-input"
          />
          <Pressable style={styles.photoOpt} onPress={pick} testID="issue-photo">
            <Ionicons name={photo ? "checkmark-circle" : "image-outline"} size={22} color={colors.brand} />
            <Text style={styles.photoOptText}>{photo ? "Photo attached" : "Attach a photo (optional)"}</Text>
          </Pressable>
          <View style={{ height: spacing.sm }} />
          <PrimaryButton title="Report Issue" icon="warning" onPress={submit} loading={busy} testID="issue-submit" />
        </ScrollView>
      </Sheet>
    </View>
  );
}
