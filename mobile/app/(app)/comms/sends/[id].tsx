/**
 * Comms Send Detail — Phase 4 · Mobile Parity.
 *
 * Full detail view for a single send record: recipient, status,
 * rendered body, error info, provider ID.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { useLocalSearchParams, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { getSend } from "@/src/api/comms";
import SendStatusPill from "@/src/components/comms/SendStatusPill";
import ChannelIcon from "@/src/components/comms/ChannelIcon";

export default function CommsSendDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();

  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      setError("");
      getSend(id!)
        .then((d) => setData(d))
        .catch((e: any) => setError(e.message || "Failed to load"))
        .finally(() => setLoading(false));
    }, [id])
  );

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="Send Detail" back />
        <ActivityIndicator
          testID="comms-send-detail-loader"
          style={{ marginTop: 40 }}
          color={colors.brand}
        />
      </View>
    );
  }

  if (error || !data) {
    return (
      <View style={styles.root}>
        <Header title="Send Detail" back />
        <View style={styles.errorWrap}>
          <Ionicons name="alert-circle-outline" size={28} color={colors.error} />
          <Text style={styles.errorText}>{error || "Send not found"}</Text>
        </View>
      </View>
    );
  }

  const isEmail = data.kind === "email";

  return (
    <View testID="comms-send-detail" style={styles.root}>
      <Header title="Send Detail" subtitle={data.template_code} back />

      <ScrollView
        contentContainerStyle={[
          styles.content,
          { paddingBottom: insets.bottom + 24 },
        ]}
        showsVerticalScrollIndicator={false}
      >
        {/* Status badges */}
        <View style={styles.badges}>
          <ChannelIcon channel={data.kind} />
          <SendStatusPill status={data.status} />
        </View>

        {/* Meta card */}
        <View style={styles.metaCard}>
          <MetaRow label="ID" value={data.id} />
          <MetaRow label="Template" value={data.template_code} />
          <MetaRow
            label="Recipient"
            value={data.recipient_address || data.recipient_id}
          />
          {data.automation_code ? (
            <MetaRow label="Automation" value={data.automation_code} />
          ) : null}
          <MetaRow
            label="Sent at"
            value={(data.sent_at || data.queued_at || "")
              .slice(0, 19)
              .replace("T", " ")}
          />
          {data.provider_message_id ? (
            <MetaRow label="Provider ID" value={data.provider_message_id} />
          ) : null}
        </View>

        {/* Error box */}
        {data.error ? (
          <View style={styles.errorBox}>
            <Ionicons name="warning-outline" size={16} color="#991B1B" />
            <Text style={styles.errorBoxText}>{data.error}</Text>
          </View>
        ) : null}

        {/* Body */}
        {isEmail ? (
          <View style={styles.section}>
            {data.subject ? (
              <>
                <Text style={styles.sectionTitle}>Subject</Text>
                <Text style={styles.subjectText}>{data.subject}</Text>
              </>
            ) : null}
            <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>
              Body
            </Text>
            <View style={styles.bodyBox}>
              <Text style={styles.bodyText}>
                {(
                  data.body_html ||
                  data.rendered_body ||
                  "(body not stored)"
                )
                  .replace(/<[^>]*>/g, " ")
                  .trim()}
              </Text>
            </View>
          </View>
        ) : (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Body</Text>
            <View style={styles.smsBox}>
              <Text style={styles.smsText}>
                {data.body_text ||
                  data.rendered_body ||
                  "(body not stored)"}
              </Text>
            </View>
          </View>
        )}

        {/* Resolved tokens */}
        {data.tokens_resolved &&
        Object.keys(data.tokens_resolved).length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Resolved Tokens</Text>
            <View style={styles.codeBox}>
              <Text style={styles.codeText}>
                {JSON.stringify(data.tokens_resolved, null, 2)}
              </Text>
            </View>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

function MetaRow({ label, value }: { label: string; value?: string }) {
  return (
    <View style={styles.metaRowFlex}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue} numberOfLines={2}>
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
  badges: {
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.lg,
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
  metaRowFlex: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  metaLabel: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    width: 90,
  },
  metaValue: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    flex: 1,
    textAlign: "right",
  },
  errorBox: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    backgroundColor: "#FEE2E2",
    borderRadius: radius.sm,
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  errorBoxText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: "#991B1B",
    flex: 1,
    lineHeight: 18,
  },
  section: { marginBottom: spacing.lg },
  sectionTitle: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  subjectText: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
    marginBottom: spacing.sm,
  },
  bodyBox: {
    backgroundColor: "#FFFFFF",
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
  smsBox: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  smsText: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.onSurface,
    lineHeight: 20,
  },
  codeBox: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  codeText: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.onSurface,
    lineHeight: 18,
  },
});
