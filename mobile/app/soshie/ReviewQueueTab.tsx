/**
 * Phase S2 · Review Queue tab — pending / flagged / deferred action list.
 * Mirrors frontend/src/pages/soshie/ReviewQueueTab.jsx
 */
import React, { useEffect, useState, useCallback } from "react";
import {
  View, Text, StyleSheet, Alert, ActivityIndicator,
  Pressable, TextInput, Image, RefreshControl, FlatList,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { Card, PrimaryButton, Sheet, EmptyState } from "@/src/components/ui";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

/* ── Chip ─────────────────────────────────────────────────────── */
function Chip({
  label, tone = "neutral", testID,
}: {
  label: string; tone?: "success" | "warning" | "danger" | "neutral"; testID?: string;
}) {
  const cfg = {
    success: { bg: "#DCFCE7", fg: "#166534" },
    warning: { bg: "#FEF3C7", fg: "#854D0E" },
    danger: { bg: "#FEE2E2", fg: "#991B1B" },
    neutral: { bg: colors.surfaceTertiary, fg: colors.muted },
  }[tone];
  return (
    <View style={[s.chip, { backgroundColor: cfg.bg }]} testID={testID}>
      <Text style={[s.chipText, { color: cfg.fg }]}>{label}</Text>
    </View>
  );
}

/* ── Skeleton ─────────────────────────────────────────────────── */
function Skeleton({ height = 100 }: { height?: number }) {
  return <View style={[s.skeleton, { height }]} />;
}

/* ── Edit Modal ──────────────────────────────────────────────── */
function EditModal({
  visible, onClose, action, onDone,
}: {
  visible: boolean; onClose: () => void; action: any; onDone: (a: any) => void;
}) {
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (action) {
      setText(action.draft?.text || "");
      setTitle(action.draft?.title || action.title || "");
    }
  }, [action]);

  const submit = async () => {
    if (!text.trim()) {
      Alert.alert("Error", "Draft text cannot be empty.");
      return;
    }
    setBusy(true);
    try {
      const next = await api.patch(
        `/ai-employees/actions/${action.id}/draft`,
        { text, title },
      );
      const flags = ((next as any)?.moderation_flags || []).length;
      Alert.alert(
        "Saved",
        flags
          ? `Draft saved · ${flags} moderation flag(s) still present`
          : "Draft saved — moderation clean",
      );
      onDone(next);
      onClose();
    } catch (e: any) {
      Alert.alert("Edit failed", e?.message || "Try again.");
    } finally {
      setBusy(false);
    }
  };

  if (!action) return null;

  return (
    <Sheet
      visible={visible}
      onClose={onClose}
      title="Edit draft"
      testID="review-queue-edit-modal"
    >
      <View style={s.modalBody}>
        <Text style={s.label}>Title</Text>
        <TextInput
          style={s.input}
          value={title}
          onChangeText={setTitle}
          testID="edit-title-input"
          accessibilityLabel="Title"
        />

        <Text style={[s.label, { marginTop: spacing.md }]}>Draft body</Text>
        <TextInput
          style={[s.input, { minHeight: 160, textAlignVertical: "top" }]}
          multiline
          value={text}
          onChangeText={setText}
          testID="edit-text-input"
          accessibilityLabel="Draft body"
        />

        <View style={s.modalActions}>
          <Pressable
            style={s.cancelBtn}
            onPress={onClose}
            disabled={busy}
            testID="edit-cancel"
            accessibilityRole="button"
            accessibilityLabel="Cancel"
          >
            <Text style={s.cancelText}>Cancel</Text>
          </Pressable>
          <PrimaryButton
            title={busy ? "Saving…" : "Save + re-moderate"}
            onPress={submit}
            loading={busy}
            disabled={busy}
            testID="edit-submit"
          />
        </View>
      </View>
    </Sheet>
  );
}

/* ── Action Row ──────────────────────────────────────────────── */
function ActionRow({
  action, onDone, disabled,
}: {
  action: any; onDone: () => void; disabled?: boolean;
}) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const flags: any[] = action.moderation_flags || [];
  const humanReq = !!action.requires_human_approval;
  const created = action.created_at ? new Date(action.created_at) : null;
  const ageHours = created
    ? Math.max(0, Math.floor((Date.now() - created.getTime()) / 3_600_000))
    : null;

  const publishNow = async () => {
    if (disabled) return;
    setBusy("publish");
    try {
      const r: any = await api.post(
        `/ai-employees/actions/${action.id}/approve?confirm_flags=1`,
      );
      if (r?.status === "published") {
        showToast("Action published successfully.");
      } else if (r?.status === "failed") {
        Alert.alert("Failed", r?.result?.error || "Publisher returned failure.");
      } else {
        showToast(`Approved — Status: ${r?.status}`);
      }
      onDone();
    } catch (e: any) {
      Alert.alert("Publish failed", e?.message || "Try again.");
    } finally {
      setBusy(null);
    }
  };

  const reject = async () => {
    if (disabled) return;
    setBusy("reject");
    try {
      await api.post(
        `/ai-employees/actions/${action.id}/reject`,
        { note: "Rejected from review queue" },
      );
      Alert.alert("Rejected", "Action rejected.");
      onDone();
    } catch (e: any) {
      Alert.alert("Reject failed", e?.message || "Try again.");
    } finally {
      setBusy(null);
    }
  };

  const platform =
    action.params?.platform ||
    action.draft?.platform ||
    (action.action?.startsWith("soshie.publish_blog") ? "wordpress" : "—");
  const previewText = (action.draft?.text || action.summary || "").slice(0, 200);

  return (
    <Card style={s.rowCard}>
      <View style={s.rowTop} testID={`review-row-${action.id}`}>
        <View style={{ flex: 1 }}>
          {/* Meta chips */}
          <View style={s.chipRow}>
            <Text style={s.rowPlatform} testID={`review-platform-${action.id}`}>
              {platform}
            </Text>
            <Text style={s.rowAction}>· {action.action}</Text>
            {ageHours != null ? (
              <Chip label={`${ageHours}h`} tone="neutral" testID={`review-age-${action.id}`} />
            ) : null}
            {flags.length ? (
              <Chip
                label={`${flags.length} flag(s)`}
                tone="warning"
                testID={`review-flag-chip-${action.id}`}
              />
            ) : null}
            {humanReq ? (
              <Chip
                label="Needs human review"
                tone="danger"
                testID={`review-human-chip-${action.id}`}
              />
            ) : null}
            {action.status === "deferred_no_credits" ? (
              <Chip
                label="No credits"
                tone="warning"
                testID={`review-nocred-${action.id}`}
              />
            ) : null}
          </View>

          {/* Preview */}
          <Text style={s.previewText} testID={`review-preview-${action.id}`}>
            {previewText}
            {previewText.length >= 200 ? "…" : ""}
          </Text>

          {/* Flag detail */}
          {flags.length ? (
            <View style={s.flagDetail} testID={`review-flags-detail-${action.id}`}>
              <Ionicons name="warning-outline" size={12} color={colors.warning} />
              <Text style={s.flagText}>
                {flags.map((f: any) => f.match || f.type).join(", ")}
              </Text>
            </View>
          ) : null}
        </View>

        {/* Media thumbnail */}
        {action.media_url ? (
          <View style={s.mediaSide}>
            <Image
              source={{ uri: action.media_url }}
              style={s.mediaThumb}
              testID={`review-media-${action.id}`}
            />
            <View style={s.mediaSource}>
              <Ionicons
                name={action.media_source === "ai_generated" ? "sparkles" : "camera-outline"}
                size={11}
                color={colors.muted}
              />
              <Text style={s.mediaSourceText} testID={`review-media-source-${action.id}`}>
                {action.media_source === "ai_generated"
                  ? `AI · ${(action.brand_score ?? 0).toFixed(2)}`
                  : "Real photo"}
              </Text>
            </View>
          </View>
        ) : null}
      </View>

      {/* Action buttons */}
      <View style={s.actions}>
        <Pressable
          style={[s.actionBtn, s.publishBtn]}
          onPress={publishNow}
          disabled={busy != null || disabled}
          testID={`review-publish-${action.id}`}
          accessibilityRole="button"
          accessibilityLabel="Publish now"
        >
          {busy === "publish" ? (
            <ActivityIndicator size={14} color="#fff" />
          ) : (
            <Ionicons name="checkmark" size={14} color="#fff" />
          )}
          <Text style={s.publishText}>
            {busy === "publish" ? "Publishing…" : "Publish now"}
          </Text>
        </Pressable>

        <Pressable
          style={[s.actionBtn, s.editBtn]}
          onPress={() => setEditOpen(true)}
          disabled={busy != null || disabled}
          testID={`review-edit-${action.id}`}
          accessibilityRole="button"
          accessibilityLabel="Edit"
        >
          <Ionicons name="create-outline" size={14} color={colors.brand} />
          <Text style={s.editText}>Edit</Text>
        </Pressable>

        <Pressable
          style={[s.actionBtn, s.rejectBtn]}
          onPress={reject}
          disabled={busy != null || disabled}
          testID={`review-reject-${action.id}`}
          accessibilityRole="button"
          accessibilityLabel="Reject"
        >
          {busy === "reject" ? (
            <ActivityIndicator size={14} color="#991B1B" />
          ) : (
            <Ionicons name="trash-outline" size={14} color="#991B1B" />
          )}
          <Text style={s.rejectText}>
            {busy === "reject" ? "Rejecting…" : "Reject"}
          </Text>
        </Pressable>
      </View>

      <EditModal
        visible={editOpen}
        action={action}
        onClose={() => setEditOpen(false)}
        onDone={() => onDone()}
      />
    </Card>
  );
}

/* ── Main tab ─────────────────────────────────────────────────── */
export default function ReviewQueueTab({ disabled }: { disabled?: boolean }) {
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const r: any = await api.get(
        "/ai-employees/actions?employee_key=soshie&status=pending&limit=100",
      );
      const all = r?.items || r || [];
      const filtered = all.filter((a: any) => {
        const ageMs = a.created_at
          ? Date.now() - new Date(a.created_at).getTime()
          : 0;
        const past24h = ageMs >= 24 * 3_600_000;
        const flagged = (a.moderation_flags || []).length > 0;
        const humanReq = !!a.requires_human_approval;
        return past24h || flagged || humanReq;
      });
      const r2: any = await api.get(
        "/ai-employees/actions?employee_key=soshie&status=deferred_no_credits&limit=100",
      );
      const deferred = r2?.items || r2 || [];
      const merged = [...filtered, ...deferred];
      merged.sort((a: any, b: any) =>
        (a.created_at || "").localeCompare(b.created_at || ""),
      );
      setRows(merged);
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Couldn't load review queue");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!disabled) load();
  }, [load, disabled]);

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  if (loading) {
    return (
      <View style={s.skeletonWrap} testID="review-queue-loading">
        <Skeleton />
        <Skeleton />
      </View>
    );
  }

  if (!rows.length) {
    return (
      <View testID="review-queue-empty">
        <EmptyState
          icon="checkmark-circle-outline"
          title="Nothing to review"
          subtitle={"You're all caught up — Soshie will let you know when the next draft needs attention."}
          testID="review-queue-empty-state"
        />
      </View>
    );
  }

  return (
    <View testID="review-queue-list">
      <FlatList
        data={rows}
        keyExtractor={(a: any) => a.id}
        scrollEnabled={false}
        renderItem={({ item }) => (
          <ActionRow action={item} onDone={load} disabled={disabled} />
        )}
        ItemSeparatorComponent={() => <View style={{ height: spacing.sm }} />}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
      />
    </View>
  );
}

const s = StyleSheet.create({
  skeletonWrap: { gap: spacing.sm },
  skeleton: {
    backgroundColor: colors.surfaceTertiary,
    borderRadius: radius.lg,
  },
  chip: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: radius.pill,
    alignSelf: "flex-start",
  },
  chipText: {
    fontFamily: font.semibold,
    fontSize: 11,
  },
  rowCard: { marginBottom: 0 },
  rowTop: {
    flexDirection: "row",
    gap: spacing.md,
  },
  chipRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 6,
    marginBottom: spacing.sm,
  },
  rowPlatform: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  rowAction: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.muted,
  },
  previewText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    lineHeight: 20,
  },
  flagDetail: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: spacing.sm,
  },
  flagText: {
    fontFamily: font.regular,
    fontSize: 12,
    color: colors.warning,
  },
  mediaSide: { alignItems: "center" },
  mediaThumb: {
    width: 64,
    height: 64,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  mediaSource: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    marginTop: 4,
  },
  mediaSourceText: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
  },
  actions: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.md,
    flexWrap: "wrap",
  },
  actionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: spacing.md,
    paddingVertical: 9,
    borderRadius: radius.sm,
    minHeight: 44,
  },
  publishBtn: { backgroundColor: colors.brand },
  publishText: { fontFamily: font.semibold, fontSize: 13, color: "#fff" },
  editBtn: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: colors.border,
  },
  editText: { fontFamily: font.semibold, fontSize: 13, color: colors.brand },
  rejectBtn: { backgroundColor: "#FEE2E2" },
  rejectText: { fontFamily: font.semibold, fontSize: 13, color: "#991B1B" },
  modalBody: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  label: {
    fontFamily: font.semibold,
    fontSize: 12,
    color: colors.muted,
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm + 2,
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.xl,
  },
  cancelBtn: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.sm,
  },
  cancelText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.muted,
  },
});
