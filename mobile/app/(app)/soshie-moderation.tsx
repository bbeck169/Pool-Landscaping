/**
 * SoshieModerationQueueScreen — Phase H8 · F3 + H5.5 parity.
 *
 * Admin+ screen for reviewing flagged/blocked social posts.
 * Tab-based: Awaiting Review / Blocked / Rejected.
 * Actions: Approve, Reject, Copy to clipboard (expo-clipboard), Mark as posted.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  Alert,
  RefreshControl,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import {
  getModerationQueue,
  approveModerationPost,
  rejectModerationPost,
  markModerationPosted,
  type ModerationPost,
} from "@/src/api/soshieModeration";

/* ═══════════ Status Tabs ═══════════ */

const STATUS_TABS = [
  { value: "awaiting_review", label: "Awaiting review" },
  { value: "blocked", label: "Blocked" },
  { value: "rejected", label: "Rejected" },
] as const;

/* ═══════════ Sub-components ═══════════ */

function DecisionPill({ decision }: { decision?: string }) {
  const isBlock = decision === "block";
  const bg = isBlock ? "#FEE2E2" : "#FEF3C7";
  const fg = isBlock ? colors.error : "#78350F";
  const border = isBlock ? "#FCA5A5" : "#FDE68A";
  return (
    <View
      style={[pill.wrap, { backgroundColor: bg, borderColor: border }]}
      testID={`moderation-decision-${decision || "unknown"}`}
    >
      <Text style={[pill.text, { color: fg }]}>
        {(decision || "flag").toUpperCase()}
      </Text>
    </View>
  );
}

const pill = StyleSheet.create({
  wrap: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
    borderWidth: 1,
  },
  text: {
    fontFamily: font.bold,
    fontSize: 10,
    letterSpacing: 0.5,
  },
});

function ReasonPills({ reasons }: { reasons?: string[] }) {
  if (!reasons || reasons.length === 0) return null;
  return (
    <View style={s.reasonRow}>
      {reasons.map((r, i) => (
        <View
          key={`${r}-${i}`}
          style={s.reasonPill}
          testID={`moderation-reason-${i}`}
        >
          <Text style={s.reasonText}>{r}</Text>
        </View>
      ))}
    </View>
  );
}

/* ═══════════ Row ═══════════ */

function ModerationRow({
  post,
  tab,
  onAction,
}: {
  post: ModerationPost;
  tab: string;
  onAction: () => void;
}) {
  const [busyAction, setBusyAction] = useState<string | null>(null);

  const handleApprove = async () => {
    setBusyAction("approve");
    try {
      await approveModerationPost(post.id);
      Alert.alert("Done", `Approved · queued for publish (${post.platform || "unknown"})`);
      onAction();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Approve failed");
    } finally {
      setBusyAction(null);
    }
  };

  const handleReject = () => {
    Alert.alert("Reject post?", "This will remove it from the publish queue.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "Reject",
        style: "destructive",
        onPress: async () => {
          setBusyAction("reject");
          try {
            await rejectModerationPost(post.id);
            Alert.alert("Done", "Post rejected");
            onAction();
          } catch (e: any) {
            Alert.alert("Error", e?.message || "Reject failed");
          } finally {
            setBusyAction(null);
          }
        },
      },
    ]);
  };

  const handleCopy = async () => {
    setBusyAction("copy");
    try {
      const text =
        post.draft?.text || post.draft_text || post.preview || post.summary || "";
      const mediaUrl = post.media_url || post.draft?.media_url || "";
      const payload = mediaUrl ? `${text}\n\n${mediaUrl}` : text;
      await Clipboard.setStringAsync(payload);
      Alert.alert("Copied", "Post content copied to clipboard");
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Copy failed");
    } finally {
      setBusyAction(null);
    }
  };

  const handleMarkPosted = async () => {
    setBusyAction("posted");
    try {
      await markModerationPosted(post.id);
      Alert.alert("Done", "Marked as posted");
      onAction();
    } catch (e: any) {
      Alert.alert("Error", e?.message || "Mark posted failed");
    } finally {
      setBusyAction(null);
    }
  };

  const alreadyPosted =
    post.status === "published_manual" || !!post.manual_posted_at;

  return (
    <View style={s.rowCard} testID={`soshie-moderation-row-${post.id}`}>
      {/* Header info */}
      <View style={s.rowHeader}>
        {/* Placeholder if no media */}
        <View style={s.rowThumb}>
          <Ionicons name="shield-outline" size={22} color={colors.muted} />
        </View>
        <View style={s.rowInfo}>
          <View style={s.rowChips}>
            <Text style={s.rowPlatform} testID={`moderation-platform-${post.id}`}>
              {(post.platform || "unknown").toUpperCase()}
            </Text>
            <View style={s.rowTime}>
              <Ionicons name="time-outline" size={12} color={colors.muted} />
              <Text style={s.rowTimeText}>
                {post.scheduled_at
                  ? new Date(post.scheduled_at).toLocaleString()
                  : "—"}
              </Text>
            </View>
            <DecisionPill decision={post.moderation_decision} />
          </View>
          <Text
            style={s.rowPreview}
            numberOfLines={4}
            testID={`soshie-moderation-preview-${post.id}`}
          >
            {post.preview || "(no preview)"}
          </Text>
          <ReasonPills reasons={post.moderation_reasons} />
        </View>
      </View>

      {/* Action buttons */}
      {tab !== "rejected" ? (
        <View style={s.rowActions}>
          <Pressable
            style={[s.actionBtn, s.approveBtn]}
            onPress={handleApprove}
            disabled={busyAction != null}
            testID={`soshie-moderation-approve-${post.id}`}
          >
            <Ionicons name="checkmark-circle-outline" size={14} color="#fff" />
            <Text style={s.approveBtnText}>
              {busyAction === "approve" ? "Approving…" : "Approve"}
            </Text>
          </Pressable>

          <Pressable
            style={[s.actionBtn, s.copyBtn]}
            onPress={handleCopy}
            disabled={busyAction != null}
            testID={`soshie-moderation-copy-${post.id}`}
          >
            <Ionicons name="clipboard-outline" size={14} color={colors.brand} />
            <Text style={s.copyBtnText}>
              {busyAction === "copy" ? "Copying…" : "Copy"}
            </Text>
          </Pressable>

          <Pressable
            style={[
              s.actionBtn,
              s.postedBtn,
              alreadyPosted && s.postedBtnDone,
            ]}
            onPress={handleMarkPosted}
            disabled={busyAction != null || alreadyPosted}
            testID={`soshie-moderation-mark-posted-${post.id}`}
          >
            <Ionicons
              name={alreadyPosted ? "checkmark-done-outline" : "send-outline"}
              size={14}
              color={alreadyPosted ? colors.muted : colors.onSurface}
            />
            <Text
              style={[
                s.postedBtnText,
                alreadyPosted && { color: colors.muted },
              ]}
            >
              {busyAction === "posted"
                ? "Marking…"
                : alreadyPosted
                  ? "Posted"
                  : "Mark posted"}
            </Text>
          </Pressable>

          <Pressable
            style={[s.actionBtn, s.rejectBtn]}
            onPress={handleReject}
            disabled={busyAction != null}
            testID={`soshie-moderation-reject-${post.id}`}
          >
            <Ionicons name="close-circle-outline" size={14} color={colors.error} />
            <Text style={s.rejectBtnText}>
              {busyAction === "reject" ? "Rejecting…" : "Reject"}
            </Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

/* ═══════════ Main Screen ═══════════ */

export default function SoshieModerationQueueScreen() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const role = (user?.role as string) || "";
  const isAdmin = role === "admin" || role === "super_admin";

  const [tab, setTab] = useState<string>("awaiting_review");
  const [posts, setPosts] = useState<ModerationPost[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getModerationQueue(tab);
      setPosts(res?.posts || []);
    } catch (e: any) {
      setError(e?.message || "Failed to load moderation queue");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [tab]);

  useEffect(() => {
    if (isAdmin) load();
  }, [load, isAdmin]);

  const onRefresh = () => {
    setRefreshing(true);
    load();
  };

  // Role gate
  if (!isAdmin) {
    return (
      <View
        style={[s.container, { paddingTop: insets.top + spacing.xl }]}
        testID="soshie-moderation-forbidden"
      >
        <Ionicons name="lock-closed-outline" size={32} color={colors.muted} />
        <Text style={s.forbiddenText}>Not authorized</Text>
        <Text style={s.forbiddenSub}>
          Only admins can access the moderation queue.
        </Text>
      </View>
    );
  }

  return (
    <View
      style={[s.screenWrap, { paddingTop: insets.top }]}
      testID="soshie-moderation-page"
    >
      {/* Header */}
      <View style={s.header}>
        <View style={{ flex: 1 }}>
          <Text style={s.headerTitle}>Soshie Moderation</Text>
          <Text style={s.headerSub}>
            Review flagged or blocked social posts before they publish.
          </Text>
        </View>
        <Pressable
          style={s.refreshBtn}
          onPress={load}
          testID="soshie-moderation-refresh"
        >
          <Ionicons name="refresh-outline" size={18} color={colors.onSurface} />
        </Pressable>
      </View>

      {/* Tabs */}
      <View style={s.tabRow} testID="soshie-moderation-tabs">
        {STATUS_TABS.map((t) => (
          <Pressable
            key={t.value}
            style={[s.tabBtn, tab === t.value && s.tabBtnActive]}
            onPress={() => setTab(t.value)}
            testID={`soshie-moderation-tab-${t.value}`}
          >
            <Text
              style={[s.tabText, tab === t.value && s.tabTextActive]}
            >
              {t.label}
              {tab === t.value ? ` · ${posts.length}` : ""}
            </Text>
          </Pressable>
        ))}
      </View>

      {/* Error */}
      {error ? (
        <View style={s.errorBanner} testID="soshie-moderation-error">
          <Ionicons name="alert-circle-outline" size={16} color={colors.error} />
          <Text style={s.errorText}>{error}</Text>
        </View>
      ) : null}

      {/* List */}
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.scrollContent}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
        testID="soshie-moderation-list"
      >
        {loading && posts.length === 0 ? (
          <View style={s.emptyWrap} testID="soshie-moderation-loading">
            <ActivityIndicator size="small" color={colors.brand} />
            <Text style={s.emptyText}>Loading…</Text>
          </View>
        ) : posts.length === 0 ? (
          <View style={s.emptyWrap} testID="soshie-moderation-empty">
            <Ionicons
              name="shield-checkmark-outline"
              size={28}
              color={colors.muted}
            />
            <Text style={s.emptyTitle}>Nothing here</Text>
            <Text style={s.emptyText}>
              Nothing in the {tab.replace(/_/g, " ")} queue.
            </Text>
          </View>
        ) : (
          posts.map((p) => (
            <ModerationRow
              key={p.id}
              post={p}
              tab={tab}
              onAction={load}
            />
          ))
        )}
      </ScrollView>
    </View>
  );
}

/* ═══════════ Styles ═══════════ */

const s = StyleSheet.create({
  screenWrap: {
    flex: 1,
    backgroundColor: colors.surface,
  },
  container: {
    flex: 1,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.xl,
    gap: spacing.sm,
  },
  forbiddenText: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  forbiddenSub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
  },
  /* header */
  header: {
    flexDirection: "row",
    alignItems: "flex-start",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    paddingTop: spacing.xl + 8,
    gap: spacing.md,
  },
  headerTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.xl,
    color: colors.onSurface,
  },
  headerSub: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginTop: 2,
  },
  refreshBtn: {
    width: 36,
    height: 36,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  /* tabs */
  tabRow: {
    flexDirection: "row",
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 3,
    gap: 3,
  },
  tabBtn: {
    flex: 1,
    paddingVertical: 6,
    borderRadius: radius.sm,
    alignItems: "center",
  },
  tabBtnActive: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tabText: {
    fontFamily: font.semibold,
    fontSize: 11,
    color: colors.muted,
  },
  tabTextActive: {
    color: colors.onSurface,
  },
  /* error */
  errorBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
    padding: spacing.md,
    borderRadius: radius.md,
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  errorText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.error,
    flex: 1,
  },
  /* list */
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xl,
    gap: spacing.md,
  },
  emptyWrap: {
    alignItems: "center",
    paddingVertical: spacing.xl * 2,
    gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
  },
  emptyTitle: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  emptyText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
  /* row card */
  rowCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: spacing.md,
  },
  rowHeader: {
    flexDirection: "row",
    gap: spacing.md,
  },
  rowThumb: {
    width: 48,
    height: 48,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  rowInfo: {
    flex: 1,
  },
  rowChips: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginBottom: 4,
  },
  rowPlatform: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.onSurface,
    letterSpacing: 0.5,
  },
  rowTime: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
  },
  rowTimeText: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
  },
  rowPreview: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    lineHeight: 18,
  },
  reasonRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 4,
    marginTop: spacing.sm,
  },
  reasonPill: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: radius.sm,
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  reasonText: {
    fontFamily: font.semibold,
    fontSize: 10,
    color: colors.error,
  },
  /* actions */
  rowActions: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  actionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    borderRadius: radius.md,
    borderWidth: 1,
    minHeight: 36,
  },
  approveBtn: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  approveBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  copyBtn: {
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
  },
  copyBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
  postedBtn: {
    backgroundColor: colors.surfaceSecondary,
    borderColor: colors.border,
  },
  postedBtnDone: {
    opacity: 0.6,
  },
  postedBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  rejectBtn: {
    backgroundColor: "#FEF2F2",
    borderColor: colors.error,
  },
  rejectBtnText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.error,
  },
});
