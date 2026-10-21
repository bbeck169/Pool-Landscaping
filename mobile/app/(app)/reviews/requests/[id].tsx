/** Request detail — Phase 3 mobile. */
import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, ActivityIndicator, Alert } from "react-native";
import { useLocalSearchParams, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { getRequest, resendRequest } from "@/src/api/reviews";
import { OutcomePillNative } from "@/src/components/reviews/OutcomePillNative";
import { StarRatingDisplayNative } from "@/src/components/reviews/StarRatingDisplayNative";
import { formatCustomerName } from "@/src/utils/formatCustomerName";
import { useToast } from "@/src/components/ToastProvider";

export default function ReviewsRequestDetailScreen() {
  const { showToast } = useToast(); // TD-96-mobile-toast-sweep (undefined since 4a8d04429)
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useFocusEffect(useCallback(() => {
    setLoading(true);
    getRequest(id!).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
  }, [id]));

  const onResend = async () => {
    setBusy(true);
    try {
      await resendRequest(id!);
      showToast("Request resent to the customer.");
      getRequest(id!).then(setData);
    } catch (e: any) {
      Alert.alert("Blocked", e.message || "Rate-limit or duplicate — cannot resend this week.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) return <View style={styles.root}><Header title="Request" back /><ActivityIndicator style={{ marginTop: 40 }} color={colors.brand} /></View>;
  if (!data) return <View style={styles.root}><Header title="Request" back /><Text style={styles.err}>Not found</Text></View>;

  return (
    <View testID="reviews-request-detail" style={styles.root}>
      <Header
        title={formatCustomerName(data) || "Review request"}
        back
        right={
          <TouchableOpacity testID="reviews-request-resend" style={styles.actionBtn} onPress={onResend} disabled={busy}>
            {busy ? <ActivityIndicator size="small" color="#fff" /> : (
              <><Ionicons name="refresh-outline" size={14} color="#fff" /><Text style={styles.actionBtnLabel}>Resend</Text></>
            )}
          </TouchableOpacity>
        }
      />
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: insets.bottom + 24 }}>
        <View style={styles.metaCard}>
          <Kv k="Customer" v={formatCustomerName(data)} />
          <Kv k="Tech" v={data.technician_name || "unassigned"} />
          <Kv k="Sent via" v={(data.sent_via || "").replace("_", " ")} />
          <Kv k="Sent at" v={(data.sent_at || "").replace("T", " ").slice(0, 16)} />
          <Kv k="Expires" v={(data.expires_at || "").replace("T", " ").slice(0, 16)} />
        </View>

        <View style={styles.timeline}>
          <Text style={styles.sectionTitle}>Timeline</Text>
          <TL label="Sent" done={!!data.sent_at} ts={data.sent_at} />
          <TL label="Landed" done={!!data.landing_visited_at} ts={data.landing_visited_at} />
          <TL label="Rated" done={!!data.star_rating_submitted}
              ts={data.star_submitted_at}
              extra={data.star_rating_submitted ? <StarRatingDisplayNative value={data.star_rating_submitted} size={12} /> : null} />
          <TL label="Routed" done={data.outcome && data.outcome !== "pending"}
              ts={data.platform_clicked_at || (data.outcome === "private_feedback_captured" ? data.sent_at : null)}
              extra={<OutcomePillNative outcome={data.outcome} />} />
        </View>

        {data.public_url ? (
          <View style={styles.metaCard}>
            <Text style={styles.sectionTitle}>Public link</Text>
            <Text style={styles.link} numberOfLines={2}>{data.public_url}</Text>
          </View>
        ) : null}
      </ScrollView>
    </View>
  );
}

function Kv({ k, v }: { k: string; v?: string }) {
  return (
    <View style={styles.kvRow}>
      <Text style={styles.kvLabel}>{k}</Text>
      <Text style={styles.kvValue} numberOfLines={2}>{v || "—"}</Text>
    </View>
  );
}

function TL({ label, done, ts, extra }: { label: string; done: boolean; ts?: string; extra?: React.ReactNode }) {
  return (
    <View style={styles.tlRow}>
      <View style={[styles.tlDot, { backgroundColor: done ? "#16A34A" : colors.border }]} />
      <Text style={[styles.tlLabel, !done && { color: colors.muted }]}>{label}</Text>
      {ts ? <Text style={styles.tlDate}>{(ts || "").slice(0, 16).replace("T", " ")}</Text> : null}
      {extra ? <View style={{ marginLeft: 8 }}>{extra}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  err: { fontFamily: font.medium, textAlign: "center", marginTop: 40, color: colors.error },
  actionBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brand, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.sm },
  actionBtnLabel: { fontFamily: font.semibold, fontSize: 12, color: "#fff" },
  metaCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, gap: 8, marginBottom: spacing.lg },
  kvRow: { flexDirection: "row", justifyContent: "space-between" },
  kvLabel: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.5, width: 80, textTransform: "uppercase" },
  kvValue: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, flex: 1, textAlign: "right", textTransform: "capitalize" },
  timeline: { marginBottom: spacing.lg },
  sectionTitle: { fontFamily: font.bold, fontSize: 10, color: colors.muted, letterSpacing: 0.5, textTransform: "uppercase", marginBottom: 8 },
  tlRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  tlDot: { width: 10, height: 10, borderRadius: 5 },
  tlLabel: { fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurface, flex: 1 },
  tlDate: { fontFamily: font.regular, fontSize: 10, color: colors.muted },
  link: { fontFamily: font.regular, fontSize: 11, color: colors.brand, marginTop: 4 },
});
