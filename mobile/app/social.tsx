/**
 * Phase 18A — Mobile Social Composer (lightweight)
 * Admin / marketing only. Techs never see this screen (guarded here + in `more.tsx`).
 * Creates draft or scheduled posts against POST /api/social/posts.
 * OAuth + publishing lands in Phase 18B.
 */
import React, { useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  Alert, Platform, ActivityIndicator,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import DateTimePicker from "@react-native-community/datetimepicker";

import { useAuth } from "@/src/auth";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Header } from "@/src/components/widgets";

type NetKey =
  | "facebook" | "instagram" | "twitter" | "linkedin"
  | "tiktok" | "youtube" | "gbp" | "pinterest" | "threads";

const NETWORKS: { key: NetKey; label: string; icon: any; limit: number }[] = [
  { key: "facebook",  label: "Facebook",  icon: "logo-facebook",  limit: 5000 },
  { key: "instagram", label: "Instagram", icon: "logo-instagram", limit: 2200 },
  { key: "twitter",   label: "X",         icon: "logo-twitter",   limit: 280 },
  { key: "linkedin",  label: "LinkedIn",  icon: "logo-linkedin",  limit: 3000 },
  { key: "tiktok",    label: "TikTok",    icon: "logo-tiktok",    limit: 2200 },
  { key: "youtube",   label: "YouTube",   icon: "logo-youtube",   limit: 5000 },
  { key: "gbp",       label: "GBP",       icon: "location-outline", limit: 1500 },
  { key: "pinterest", label: "Pinterest", icon: "logo-pinterest", limit: 500 },
  { key: "threads",   label: "Threads",   icon: "at-outline",     limit: 500 },
];

export default function SocialComposerMobile() {
  const { user } = useAuth();
  const router = useRouter();

  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin" || role === "marketing";

  const [caption, setCaption] = useState("");
  const [selected, setSelected] = useState<NetKey[]>(["instagram", "facebook"]);
  const [scheduledAt, setScheduledAt] = useState<Date | null>(null);
  const [pickerMode, setPickerMode] = useState<"none" | "date" | "time">("none");
  const [firstComment, setFirstComment] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [variants, setVariants] = useState<string[]>([]);

  const tightestLimit = useMemo(() => {
    if (selected.length === 0) return null;
    return Math.min(...selected.map((k) => NETWORKS.find((n) => n.key === k)!.limit));
  }, [selected]);

  if (!allowed) {
    return (
      <View style={styles.root}>
        <Header title="Social" />
        <View style={{ padding: spacing.lg }}>
          <Text style={styles.forbid}>
            Social Suite is available to Admins and Marketing users.
          </Text>
        </View>
      </View>
    );
  }

  const toggleNet = (k: NetKey) => {
    setSelected((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));
  };

  const runAi = async () => {
    if (!caption.trim() && selected.length === 0) {
      Alert.alert("Add a topic", "Type a topic or brief in the caption box first.");
      return;
    }
    setAiBusy(true);
    try {
      const res = await api.post("/social/ai/caption", {
        topic: caption || "General social update",
        networks: selected.length ? selected : ["instagram", "facebook"],
        brand_voice: "friendly",
      });
      setVariants(res.captions || []);
      if (res.mocked) {
        Alert.alert("AI in mock mode", "EMERGENT_LLM_KEY not set — variants are placeholders.");
      }
    } catch (e: any) {
      Alert.alert("AI error", e?.message || "Could not generate caption.");
    } finally {
      setAiBusy(false);
    }
  };

  const savePost = async (status: "draft" | "scheduled") => {
    if (selected.length === 0) {
      Alert.alert("Pick a network", "Select at least one target network.");
      return;
    }
    if (!caption.trim()) {
      Alert.alert("Caption required", "Write a caption before saving.");
      return;
    }
    if (status === "scheduled" && !scheduledAt) {
      Alert.alert("Pick a schedule time", "Tap the Schedule row to pick a date & time.");
      return;
    }
    setSaving(true);
    try {
      await api.post("/social/posts", {
        networks: selected,
        caption,
        first_comment: firstComment || undefined,
        scheduled_at: status === "scheduled" && scheduledAt ? scheduledAt.toISOString() : null,
        status,
      });
      Alert.alert(
        status === "scheduled" ? "Scheduled" : "Draft saved",
        status === "scheduled"
          ? "Post queued. Publishing wires up in Phase 18B."
          : "Draft saved. Publishing wires up in Phase 18B.",
        [{ text: "OK", onPress: () => router.back() }],
      );
    } catch (e: any) {
      Alert.alert("Save failed", e?.message || "Could not save the post.");
    } finally {
      setSaving(false);
    }
  };

  const submitForApproval = async () => {
    if (selected.length === 0) {
      Alert.alert("Pick a network", "Select at least one target network.");
      return;
    }
    if (!caption.trim()) {
      Alert.alert("Caption required", "Write a caption before submitting.");
      return;
    }
    setSaving(true);
    try {
      const post = await api.post("/social/posts", {
        networks: selected,
        caption,
        first_comment: firstComment || undefined,
        scheduled_at: scheduledAt ? scheduledAt.toISOString() : null,
        status: "draft",
      });
      await api.post(`/social/posts/${post.id}/submit-for-approval`, {});
      Alert.alert(
        "Submitted for approval",
        "An admin will review this post before it schedules.",
        [{ text: "OK", onPress: () => router.back() }],
      );
    } catch (e: any) {
      Alert.alert("Submit failed", e?.message || "Could not submit the post.");
    } finally {
      setSaving(false);
    }
  };

  const overLimit = tightestLimit != null && caption.length > tightestLimit;

  return (
    <View style={styles.root}>
      <Header title="Social Composer" />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: spacing["3xl"] }}>
        <Text style={styles.sectionTitle}>Caption</Text>
        <TextInput
          testID="social-caption-input"
          style={styles.textarea}
          multiline
          numberOfLines={6}
          value={caption}
          onChangeText={setCaption}
          placeholder="Write your post caption..."
          placeholderTextColor={colors.muted}
        />
        <View style={styles.metaRow}>
          {tightestLimit != null && (
            <Text style={[styles.counter, overLimit && { color: colors.error }]}>
              {caption.length} / {tightestLimit}
            </Text>
          )}
          <Pressable style={styles.aiBtn} onPress={runAi} disabled={aiBusy} testID="social-ai-suggest">
            {aiBusy ? (
              <ActivityIndicator color={colors.brand} size="small" />
            ) : (
              <Ionicons name="sparkles-outline" size={18} color={colors.brand} />
            )}
            <Text style={styles.aiBtnText}>AI Suggest</Text>
          </Pressable>
        </View>

        {variants.length > 0 && (
          <View style={styles.variantWrap}>
            <Text style={styles.sectionTitle}>AI variants</Text>
            {variants.map((v, i) => (
              <Pressable
                key={i}
                style={styles.variant}
                onPress={() => setCaption(v)}
                testID={`social-variant-${i}`}
              >
                <Text style={styles.variantText}>{v}</Text>
                <Text style={styles.variantHint}>Tap to use</Text>
              </Pressable>
            ))}
          </View>
        )}

        <Text style={[styles.sectionTitle, { marginTop: spacing.xl }]}>Networks</Text>
        <View style={styles.netGrid}>
          {NETWORKS.map((n) => {
            const active = selected.includes(n.key);
            return (
              <Pressable
                key={n.key}
                onPress={() => toggleNet(n.key)}
                style={[styles.netChip, active && styles.netChipActive]}
                testID={`social-net-${n.key}`}
              >
                <Ionicons
                  name={n.icon as any}
                  size={18}
                  color={active ? colors.brand : colors.muted}
                />
                <Text style={[styles.netLabel, active && { color: colors.brand }]}>{n.label}</Text>
                <Text style={styles.notConnected}>🔌 not connected</Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={[styles.sectionTitle, { marginTop: spacing.xl }]}>First comment (optional)</Text>
        <TextInput
          style={styles.input}
          value={firstComment}
          onChangeText={setFirstComment}
          placeholder="Auto-post as first comment (Instagram/LinkedIn)"
          placeholderTextColor={colors.muted}
          testID="social-first-comment"
        />

        <Text style={[styles.sectionTitle, { marginTop: spacing.xl }]}>Schedule</Text>
        <Pressable
          style={styles.scheduleRow}
          onPress={() => setPickerMode("date")}
          testID="social-schedule-row"
        >
          <Ionicons name="calendar-outline" size={20} color={colors.brand} />
          <Text style={styles.scheduleText}>
            {scheduledAt ? scheduledAt.toLocaleString() : "Save as draft (tap to schedule)"}
          </Text>
          {scheduledAt && (
            <Pressable onPress={() => setScheduledAt(null)} testID="social-clear-schedule">
              <Ionicons name="close-circle" size={20} color={colors.muted} />
            </Pressable>
          )}
        </Pressable>

        {pickerMode !== "none" && (
          <DateTimePicker
            value={scheduledAt || new Date(Date.now() + 60 * 60 * 1000)}
            mode={pickerMode}
            onChange={(_, d) => {
              if (Platform.OS === "android") setPickerMode("none");
              if (!d) return;
              if (pickerMode === "date") {
                const next = scheduledAt ? new Date(scheduledAt) : new Date();
                next.setFullYear(d.getFullYear(), d.getMonth(), d.getDate());
                setScheduledAt(next);
                if (Platform.OS === "android") setTimeout(() => setPickerMode("time"), 100);
              } else {
                const next = scheduledAt ? new Date(scheduledAt) : new Date();
                next.setHours(d.getHours(), d.getMinutes(), 0, 0);
                setScheduledAt(next);
                if (Platform.OS === "android") setPickerMode("none");
              }
            }}
          />
        )}

        <View style={styles.actionRow}>
          <Pressable
            style={[styles.btn, styles.btnGhost]}
            onPress={() => savePost("draft")}
            disabled={saving || overLimit}
            testID="social-save-draft"
          >
            <Ionicons name="save-outline" size={18} color={colors.brand} />
            <Text style={styles.btnGhostText}>Save Draft</Text>
          </Pressable>
          <Pressable
            style={[styles.btn, styles.btnPrimary, (!scheduledAt || overLimit) && { opacity: 0.5 }]}
            onPress={() => savePost("scheduled")}
            disabled={saving || !scheduledAt || overLimit}
            testID="social-schedule-post"
          >
            <Ionicons name="time-outline" size={18} color="#fff" />
            <Text style={styles.btnPrimaryText}>Schedule</Text>
          </Pressable>
        </View>

        <Pressable
          style={[styles.btn, styles.btnGhost, { marginTop: spacing.md }]}
          onPress={submitForApproval}
          disabled={saving || overLimit || !caption.trim()}
          testID="social-submit-approval"
        >
          <Ionicons name="shield-checkmark-outline" size={18} color={colors.brand} />
          <Text style={styles.btnGhostText}>Submit for Approval</Text>
        </Pressable>

        <View style={styles.publishNote} testID="social-publish-note">
          <Ionicons name="lock-closed-outline" size={16} color={colors.muted} />
          <Text style={styles.publishNoteText}>
            Publish Now is available in Phase 18B once networks are connected.
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  forbid: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.muted, textAlign: "center", marginTop: spacing.xl },
  sectionTitle: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface, marginBottom: spacing.sm },
  textarea: {
    minHeight: 140,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
    textAlignVertical: "top",
  },
  input: {
    height: 48,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    fontFamily: font.regular,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.sm,
  },
  counter: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.muted },
  aiBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
  },
  aiBtnText: { fontFamily: font.bold, fontSize: fontSize.sm, color: colors.brand },
  variantWrap: { marginTop: spacing.md },
  variant: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  variantText: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface },
  variantHint: { fontFamily: font.semibold, fontSize: fontSize.xs, color: colors.brand, marginTop: 4 },
  netGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  netChip: {
    flexBasis: "48%",
    flexDirection: "column",
    alignItems: "flex-start",
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: 4,
  },
  netChipActive: { borderColor: colors.brand, backgroundColor: colors.brandTertiary },
  netLabel: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  notConnected: { fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted },
  scheduleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  scheduleText: { flex: 1, fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurface },
  actionRow: { flexDirection: "row", gap: spacing.md, marginTop: spacing.xl },
  btn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    height: 48,
    borderRadius: radius.md,
  },
  btnPrimary: { backgroundColor: colors.brand },
  btnPrimaryText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.base },
  btnGhost: { borderWidth: 1.5, borderColor: colors.brand },
  btnGhostText: { color: colors.brand, fontFamily: font.bold, fontSize: fontSize.base },
  publishNote: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginTop: spacing.xl,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  publishNoteText: { flex: 1, fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
});
