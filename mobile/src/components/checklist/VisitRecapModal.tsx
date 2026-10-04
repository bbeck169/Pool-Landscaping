/**
 * Phase 39 · Step 2 · Visit Recap modal (mobile).
 * Mirror of the web `VisitRecapModal.jsx` — see it for the canonical
 * behaviour spec. Test IDs are identical.
 */
import React, { useMemo, useState } from "react";
import {
  View, Text, Pressable, Modal, ActivityIndicator, StyleSheet, Switch,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

type RecapResult = {
  sent: boolean;
  channel: string;
  results: Record<string, { sent: boolean; mocked?: boolean; reason?: string }>;
  mocked_channels: string[];
  photo_count?: number;
};

export type VisitRecapModalProps = {
  visible: boolean;
  serviceReportId: string | null;
  customer: { name?: string; email?: string; phone?: string } | null;
  onClose: () => void;
};

export default function VisitRecapModal({
  visible, serviceReportId, customer, onClose,
}: VisitRecapModalProps) {
  // APR-IV — the legacy after-hours fallback was dropped in APR-II;
  // SMS availability now depends solely on primary phone.
  const hasPhone = !!customer?.phone;
  const hasEmail = !!customer?.email;
  const defaultChannel =
    hasPhone && hasEmail ? "both" : hasEmail ? "email" : hasPhone ? "sms" : "";
  const [channel, setChannel] = useState<string>(defaultChannel);
  const [includePhotos, setIncludePhotos] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RecapResult | null>(null);
  const [err, setErr] = useState("");

  const disabledMsg = useMemo(() => {
    if (!hasPhone && !hasEmail) return "Customer has no phone or email on file.";
    return "";
  }, [hasPhone, hasEmail]);

  const send = async () => {
    if (!channel || busy || !serviceReportId) return;
    setBusy(true); setErr(""); setResult(null);
    try {
      const r: any = await api.post(
        `/service-reports/${serviceReportId}/send-recap`,
        { channel, include_photos: includePhotos },
      );
      setResult(r);
      if (r?.sent) setTimeout(() => onClose(), 2000);
    } catch (e: any) {
      setErr(e?.message || "Send failed.");
    } finally { setBusy(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable onPress={onClose} style={styles.backdrop}>
        <Pressable onPress={() => {}} style={styles.card} testID="visit-recap-modal">
          <View style={styles.headerRow}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Ionicons name="send" size={16} color={colors.brand} />
              <Text style={styles.headerTitle}>Send visit recap?</Text>
            </View>
            <Pressable onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={18} color={colors.muted} />
            </Pressable>
          </View>

          <View style={{ padding: spacing.md }}>
            <Text style={styles.subCopy}>
              Text or email <Text style={styles.bold}>{customer?.name || "the customer"}</Text>{" "}
              a summary of today&apos;s visit — chemicals added, water readings
              {includePhotos ? " and up to 3 photos" : ""}.
            </Text>

            {disabledMsg ? (
              <View style={styles.errorBox}>
                <Ionicons name="warning-outline" size={12} color="#B91C1C" />
                <Text style={styles.errorText}>{disabledMsg}</Text>
              </View>
            ) : null}

            <View style={styles.pillRow}>
              <ChannelPill
                label="SMS" icon="chatbubble-outline" disabled={!hasPhone}
                selected={channel === "sms"} onPress={() => setChannel("sms")}
                testID="visit-recap-channel-sms"
              />
              <ChannelPill
                label="Email" icon="mail-outline" disabled={!hasEmail}
                selected={channel === "email"} onPress={() => setChannel("email")}
                testID="visit-recap-channel-email"
              />
              <ChannelPill
                label="Both" icon="send-outline" disabled={!(hasPhone && hasEmail)}
                selected={channel === "both"} onPress={() => setChannel("both")}
                testID="visit-recap-channel-both"
              />
            </View>

            <View style={styles.toggleRow} testID="visit-recap-include-photos">
              <Switch
                value={includePhotos}
                onValueChange={setIncludePhotos}
                trackColor={{ true: colors.brand, false: colors.border }}
              />
              <Ionicons name="camera-outline" size={13} color={colors.muted} />
              <Text style={styles.toggleText}>Include photos (up to 3)</Text>
            </View>

            {result ? <ResultBanner result={result} /> : null}
            {err ? (
              <View style={styles.errorBox}>
                <Ionicons name="warning-outline" size={12} color="#B91C1C" />
                <Text style={styles.errorText}>{err}</Text>
              </View>
            ) : null}
          </View>

          <View style={styles.footer}>
            <Pressable
              onPress={onClose}
              testID="visit-recap-skip-btn"
              style={styles.skipBtn}
            >
              <Text style={styles.skipText}>Skip</Text>
            </Pressable>
            <Pressable
              onPress={send}
              disabled={busy || !channel || !!disabledMsg}
              testID="visit-recap-send-btn"
              style={[
                styles.sendBtn,
                (busy || !channel || !!disabledMsg) && { opacity: 0.5 },
              ]}
            >
              {busy
                ? <ActivityIndicator size="small" color="#fff" />
                : <Ionicons name="send" size={13} color="#fff" />}
              <Text style={styles.sendText}>{busy ? "Sending…" : "Send"}</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function ChannelPill({
  label, icon, selected, disabled, onPress, testID,
}: { label: string; icon: any; selected: boolean; disabled: boolean; onPress: () => void; testID: string }) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      testID={testID}
      style={[
        styles.pill,
        selected && styles.pillSelected,
        disabled && { opacity: 0.5 },
      ]}
    >
      <Ionicons name={icon} size={13} color={selected ? "#fff" : (disabled ? colors.muted : colors.onSurface)} />
      <Text style={[
        styles.pillText,
        selected && { color: "#fff" },
        disabled && { color: colors.muted },
      ]}>{label}</Text>
    </Pressable>
  );
}

function ResultBanner({ result }: { result: RecapResult }) {
  const mockedChannels = result.mocked_channels || [];
  const okChannels = Object.entries(result.results || {})
    .filter(([, v]) => (v as any)?.sent)
    .map(([k]) => k);
  return (
    <View style={{ gap: 6, marginTop: 8 }}>
      {result.sent ? (
        <View style={styles.successBox} testID="visit-recap-success">
          <Ionicons name="checkmark-circle" size={13} color="#065F46" />
          <Text style={styles.successText}>Sent via {okChannels.join(" + ")}.</Text>
        </View>
      ) : null}
      {mockedChannels.map((ch) => {
        const reason = (result.results as any)[ch]?.reason || "no reason";
        return (
          <View key={ch} style={styles.mockedBox} testID="visit-recap-mocked-reason">
            <Ionicons name="warning-outline" size={12} color="#B45309" />
            <Text style={styles.mockedText}>
              <Text style={{ fontFamily: font.bold }}>{ch.toUpperCase()}</Text> not sent — {reason}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center", justifyContent: "center", padding: 16,
  },
  card: {
    width: "100%", maxWidth: 480, backgroundColor: colors.surface,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    overflow: "hidden",
  },
  headerRow: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  headerTitle: {
    fontFamily: font.bold, fontSize: fontSize.base, color: colors.onSurface,
  },
  subCopy: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.onSurface,
    marginBottom: spacing.sm, lineHeight: 20,
  },
  bold: { fontFamily: font.bold },
  errorBox: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#FEE2E2", borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 6, marginBottom: 8,
  },
  errorText: { fontFamily: font.semibold, fontSize: 11, color: "#B91C1C", flex: 1 },
  pillRow: { flexDirection: "row", gap: 8, marginBottom: 12, flexWrap: "wrap" },
  pill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999,
    backgroundColor: "#F1F5F9", borderWidth: 1, borderColor: colors.border,
  },
  pillSelected: { backgroundColor: colors.brand, borderColor: colors.brand },
  pillText: { fontFamily: font.semibold, fontSize: 13, color: colors.onSurface },
  toggleRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  toggleText: { fontFamily: font.regular, fontSize: 13, color: colors.onSurface },
  footer: {
    flexDirection: "row", alignItems: "center", justifyContent: "flex-end",
    gap: 8, paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderTopWidth: 1, borderTopColor: colors.border,
  },
  skipBtn: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.border, backgroundColor: "transparent",
  },
  skipText: { fontFamily: font.semibold, fontSize: 13, color: colors.onSurface },
  sendBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brand, borderRadius: radius.sm,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  sendText: { fontFamily: font.bold, fontSize: 13, color: "#fff" },
  successBox: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#D1FAE5", borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 6,
  },
  successText: { fontFamily: font.semibold, fontSize: 11, color: "#065F46" },
  mockedBox: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#FEF3C7", borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 6,
  },
  mockedText: { fontFamily: font.regular, fontSize: 11, color: "#B45309", flex: 1 },
});
