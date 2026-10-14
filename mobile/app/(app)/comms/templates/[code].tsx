/**
 * Comms Template Detail — Phase 4 · Mobile Parity.
 *
 * Read-only view of a single email or SMS template.
 * Shows metadata + preview (calls /preview endpoint).
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  Platform,
} from "react-native";
import { useLocalSearchParams , useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { mapApiError, errorKindIcon } from "@/src/utils/mapApiError";
import {
  getEmailTemplate,
  getSmsTemplate,
  previewEmailTemplate,
  previewSmsTemplate,
} from "@/src/api/comms";
import CommsAdminGate from "@/src/components/comms/CommsAdminGate";
import EmailPreviewWebView from "@/src/components/comms/EmailPreviewWebView";

// P2 #11 — admin + super_admin only (backend `_require_admin`).
export default function CommsTemplateDetailScreen() {
  return (
    <CommsAdminGate title="Template">
      <CommsTemplateDetailBody />
    </CommsAdminGate>
  );
}

function CommsTemplateDetailBody() {
  const { code, channel } = useLocalSearchParams<{
    code: string;
    channel: string;
  }>();
  const insets = useSafeAreaInsets();
  const isEmail = channel === "email";

  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [previewData, setPreviewData] = useState<any>(null);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<unknown>(null);

  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      setError("");
      const fetcher = isEmail
        ? getEmailTemplate(code!)
        : getSmsTemplate(code!);
      fetcher
        .then((d) => setData(d))
        .catch((e: any) => setError(e))
        .finally(() => setLoading(false));
    }, [code, isEmail])
  );

  // Modal opens immediately with its own loading / error state — a
  // preview failure no longer replaces the whole screen.
  const onPreview = async () => {
    setPreviewVisible(true);
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewData(null);
    try {
      const d = isEmail
        ? await previewEmailTemplate(code!)
        : await previewSmsTemplate(code!);
      setPreviewData(d);
    } catch (e: any) {
      setPreviewError(e);
    } finally {
      setPreviewLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="Template" back />
        <ActivityIndicator
          testID="comms-template-detail-loader"
          style={{ marginTop: 40 }}
          color={colors.brand}
        />
      </View>
    );
  }

  if (error || !data) {
    const mapped = error ? mapApiError(error) : null;
    return (
      <View style={styles.root}>
        <Header title="Template" back />
        <View style={styles.errorWrap}>
          <Ionicons name={(mapped ? errorKindIcon(mapped.kind) : "alert-circle-outline") as any} size={28} color={colors.error} />
          <Text style={styles.errorText}>{mapped?.message || "Template not found"}</Text>
        </View>
      </View>
    );
  }

  return (
    <View testID="comms-template-detail" style={styles.root}>
      <Header
        title={data.name || data.code}
        subtitle={isEmail ? "Email template" : "SMS template"}
        back
        right={
          <TouchableOpacity
            testID="comms-template-preview-btn"
            style={styles.previewBtn}
            onPress={onPreview}
            disabled={previewLoading}
          >
            {previewLoading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="eye-outline" size={16} color="#fff" />
                <Text style={styles.previewBtnLabel}>Preview</Text>
              </>
            )}
          </TouchableOpacity>
        }
      />

      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingBottom: insets.bottom + 24 },
        ]}
        showsVerticalScrollIndicator={false}
      >
        {/* Meta */}
        <View style={styles.metaCard}>
          <MetaRow label="Code" value={data.code} mono />
          <MetaRow label="Name" value={data.name} />
          <MetaRow
            label="Type"
            value={data.is_system ? "System" : "Custom"}
          />
          <MetaRow
            label="Updated"
            value={(data.updated_at || data.created_at || "").slice(0, 10)}
          />
          {isEmail && <MetaRow label="Subject" value={data.subject} />}
        </View>

        {/* SMS body */}
        {!isEmail && data.body ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Body</Text>
            <View style={styles.bodyBox}>
              <Text style={styles.bodyText}>{data.body}</Text>
            </View>
          </View>
        ) : null}

        {/* Email blocks summary */}
        {isEmail && Array.isArray(data.blocks_json) && data.blocks_json.length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>
              Blocks ({data.blocks_json.length})
            </Text>
            {data.blocks_json.map((b: any, i: number) => (
              <View key={i} style={styles.blockRow}>
                <Ionicons
                  name="cube-outline"
                  size={14}
                  color={colors.muted}
                />
                <Text style={styles.blockType}>{b.type}</Text>
                {b.text ? (
                  <Text style={styles.blockHint} numberOfLines={1}>
                    {b.text}
                  </Text>
                ) : null}
              </View>
            ))}
          </View>
        ) : null}
      </ScrollView>

      {/* Preview modal */}
      <Modal
        visible={previewVisible}
        animationType="slide"
        transparent
        onRequestClose={() => setPreviewVisible(false)}
      >
        <View style={styles.modalOverlay}>
          <View
            style={[
              styles.modalContent,
              isEmail && styles.modalContentEmail,
              { paddingBottom: insets.bottom + 16 },
            ]}
            testID="comms-preview-modal"
          >
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Preview</Text>
              <TouchableOpacity
                testID="comms-preview-close"
                onPress={() => setPreviewVisible(false)}
              >
                <Ionicons name="close" size={22} color={colors.muted} />
              </TouchableOpacity>
            </View>
            {previewLoading ? (
              <ActivityIndicator
                testID="comms-preview-loader"
                style={{ marginVertical: 40 }}
                color={colors.brand}
              />
            ) : previewError ? (
              <View style={styles.errorWrap} testID="comms-preview-error">
                <Ionicons
                  name={errorKindIcon(mapApiError(previewError).kind) as any}
                  size={28}
                  color={colors.error}
                />
                <Text style={styles.errorText}>{mapApiError(previewError).message}</Text>
                <TouchableOpacity
                  testID="comms-preview-retry"
                  style={styles.previewBtn}
                  onPress={onPreview}
                >
                  <Text style={styles.previewBtnLabel}>Retry</Text>
                </TouchableOpacity>
              </View>
            ) : isEmail ? (
              <View style={styles.emailPreviewWrap}>
                <Text style={styles.previewSubjectLabel}>Subject</Text>
                <Text style={styles.previewSubject} testID="comms-preview-subject">
                  {previewData?.subject ||
                    previewData?.resolved_subject ||
                    "(no subject)"}
                </Text>
                <View style={styles.previewHtmlBox}>
                  <EmailPreviewWebView
                    html={previewData?.body_html || previewData?.html || "<p>(no body)</p>"}
                  />
                </View>
              </View>
            ) : (
            <ScrollView style={styles.modalBody}>
                <>
                  <Text style={styles.previewBodyLabel}>Body</Text>
                  <View style={styles.previewSmsBox}>
                    <Text style={styles.previewSmsText}>
                      {previewData?.body ||
                        previewData?.resolved_body ||
                        "(no body)"}
                    </Text>
                  </View>
                </>
            </ScrollView>
            )}
          </View>
        </View>
      </Modal>
    </View>
  );
}

function MetaRow({
  label,
  value,
  mono,
}: {
  label: string;
  value?: string;
  mono?: boolean;
}) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text
        style={[styles.metaValue, mono && { fontFamily: font.regular }]}
        numberOfLines={2}
      >
        {value || "—"}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  content: { padding: spacing.lg },
  errorWrap: { alignItems: "center", paddingTop: 60, gap: 8 },
  errorText: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.error,
    textAlign: "center",
  },
  previewBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brand,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.sm,
  },
  previewBtnLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  metaCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: colors.border,
    gap: 10,
    marginBottom: spacing.lg,
  },
  metaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
  },
  metaLabel: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    width: 80,
  },
  metaValue: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    flex: 1,
    textAlign: "right",
  },
  section: { marginBottom: spacing.lg },
  sectionTitle: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  bodyBox: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  bodyText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    lineHeight: 20,
  },
  blockRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  blockType: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  blockHint: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
    flex: 1,
  },
  /* Modal */
  modalOverlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  modalContent: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    maxHeight: "85%",
    paddingTop: spacing.lg,
  },
  modalHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.md,
  },
  modalTitle: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: colors.onSurface,
  },
  modalBody: { paddingHorizontal: spacing.lg },
  previewSubjectLabel: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  previewSubject: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginBottom: spacing.md,
  },
  previewBodyLabel: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  previewHtmlBox: {
    flex: 1,
    backgroundColor: "#fff",
    borderRadius: radius.sm,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.border,
  },
  modalContentEmail: { height: "85%" },
  emailPreviewWrap: { flex: 1, paddingHorizontal: spacing.lg },
  previewHtmlText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    lineHeight: 20,
  },
  previewSmsBox: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  previewSmsText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    lineHeight: 20,
  },
});
