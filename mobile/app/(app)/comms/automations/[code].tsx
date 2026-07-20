/**
 * Comms Automation Detail — Phase 4 · Mobile Parity.
 *
 * Read-only detail for one automation rule. Includes test-fire modal
 * which picks a customer and fires the rule via POST.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Modal,
  Alert,
  Platform,
} from "react-native";
import { useLocalSearchParams, useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import { getAutomation, testFireAutomation, listAutomationEvents } from "@/src/api/comms";
import { api } from "@/src/api";
import ChannelIcon from "@/src/components/comms/ChannelIcon";

export default function CommsAutomationDetailScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const insets = useSafeAreaInsets();

  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [testVisible, setTestVisible] = useState(false);
  const [events, setEvents] = useState<any[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);

  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      setError("");
      getAutomation(code!)
        .then((d) => setData(d))
        .catch((e: any) => setError(e.message || "Failed to load"))
        .finally(() => setLoading(false));
      // Load latest 10 fire events in parallel — best-effort.
      setEventsLoading(true);
      listAutomationEvents({ automation_code: code!, limit: "10" })
        .then((d: any) => {
          const rows = d?.events || d?.automation_events || (Array.isArray(d) ? d : []) || [];
          setEvents(Array.isArray(rows) ? rows : []);
        })
        .catch(() => setEvents([]))
        .finally(() => setEventsLoading(false));
    }, [code])
  );

  if (loading) {
    return (
      <View style={styles.root}>
        <Header title="Automation" back />
        <ActivityIndicator
          testID="comms-automation-detail-loader"
          style={{ marginTop: 40 }}
          color={colors.brand}
        />
      </View>
    );
  }

  if (error || !data) {
    return (
      <View style={styles.root}>
        <Header title="Automation" back />
        <View style={styles.errorWrap}>
          <Ionicons name="alert-circle-outline" size={28} color={colors.error} />
          <Text style={styles.errorText}>{error || "Not found"}</Text>
        </View>
      </View>
    );
  }

  return (
    <View testID="comms-automation-detail" style={styles.root}>
      <Header
        title={data.name || data.code}
        subtitle="Automation rule"
        back
        right={
          <TouchableOpacity
            testID="comms-automation-testfire-btn"
            style={styles.testBtn}
            onPress={() => setTestVisible(true)}
          >
            <Ionicons name="play-outline" size={16} color="#fff" />
            <Text style={styles.testBtnLabel}>Test Fire</Text>
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
        <View style={styles.metaCard}>
          <MetaRow label="Code" value={data.code} />
          <MetaRow label="Name" value={data.name} />
          <MetaRow label="Description" value={data.description} />
          <MetaRow label="Trigger" value={data.trigger_event} />
          <View style={styles.metaRowFlex}>
            <Text style={styles.metaLabel}>Channel</Text>
            <ChannelIcon channel={data.channel} />
          </View>
          <MetaRow label="Template" value={data.template_code} />
          <MetaRow
            label="Delay"
            value={`${data.send_delay_minutes || 0} minutes`}
          />
          <MetaRow label="Active" value={data.active ? "Yes" : "No"} />
        </View>

        {data.trigger_conditions &&
        Object.keys(data.trigger_conditions).length > 0 ? (
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Trigger Conditions</Text>
            <View style={styles.codeBox}>
              <Text style={styles.codeText}>
                {JSON.stringify(data.trigger_conditions, null, 2)}
              </Text>
            </View>
          </View>
        ) : null}

        {/* Recent fire events — Phase 3 automation-engine journal. */}
        <View style={styles.section} testID="comms-automation-events">
          <Text style={styles.sectionTitle}>
            Recent fires (last {events.length || 10})
          </Text>
          {eventsLoading ? (
            <ActivityIndicator style={{ marginVertical: 12 }} color={colors.brand} />
          ) : events.length ? (
            <View style={styles.eventsList}>
              {events.map((ev, idx) => (
                <View
                  key={ev.id || idx}
                  style={styles.eventRow}
                  testID={`comms-automation-event-${idx}`}
                >
                  <View style={styles.eventLeft}>
                    <View
                      style={[
                        styles.eventDot,
                        {
                          backgroundColor: statusColor(ev.status),
                        },
                      ]}
                    />
                    <Text style={styles.eventStatus}>{ev.status || "—"}</Text>
                  </View>
                  <Text style={styles.eventDate} numberOfLines={1}>
                    {(ev.fired_at || ev.created_at || "")
                      .slice(0, 19)
                      .replace("T", " ")}
                  </Text>
                </View>
              ))}
            </View>
          ) : (
            <View style={styles.eventsEmpty}>
              <Ionicons name="pulse-outline" size={20} color={colors.muted} />
              <Text style={styles.eventsEmptyText}>
                No fires yet — flip the rule active + trigger the event.
              </Text>
            </View>
          )}
        </View>
      </ScrollView>

      {/* Test Fire Modal */}
      <TestFireModal
        visible={testVisible}
        ruleCode={data.code}
        onClose={() => setTestVisible(false)}
      />
    </View>
  );
}

function TestFireModal({
  visible,
  ruleCode,
  onClose,
}: {
  visible: boolean;
  ruleCode: string;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  const [customers, setCustomers] = useState<any[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [loadingCustomers, setLoadingCustomers] = useState(false);

  useEffect(() => {
    if (!visible) return;
    setLoadingCustomers(true);
    api
      .get("/customers")
      .then((rows) => setCustomers(Array.isArray(rows) ? rows : []))
      .catch(() => setCustomers([]))
      .finally(() => setLoadingCustomers(false));
  }, [visible]);

  const fire = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const d = await testFireAutomation(ruleCode, selected);
      Alert.alert(
        "Test Fired",
        `Send ${d.send_id || d.id || "queued"} created.`
      );
      onClose();
    } catch (e: any) {
      Alert.alert("Error", e.message || "Failed to test fire");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onClose}
    >
      <View style={styles.modalOverlay}>
        <View
          testID="comms-auto-testfire-modal"
          style={[styles.modalContent, { paddingBottom: insets.bottom + 16 }]}
        >
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Test Fire · {ruleCode}</Text>
            <TouchableOpacity testID="comms-testfire-close" onPress={onClose}>
              <Ionicons name="close" size={22} color={colors.muted} />
            </TouchableOpacity>
          </View>

          <Text style={styles.pickLabel}>Select recipient customer</Text>

          {loadingCustomers ? (
            <ActivityIndicator
              style={{ marginVertical: 20 }}
              color={colors.brand}
            />
          ) : (
            <ScrollView style={styles.customerList}>
              {customers.map((c) => (
                <TouchableOpacity
                  key={c.id}
                  testID={`comms-testfire-customer-${c.id}`}
                  style={[
                    styles.customerRow,
                    selected === c.id && styles.customerRowSelected,
                  ]}
                  onPress={() => setSelected(c.id)}
                >
                  <Ionicons
                    name={
                      selected === c.id
                        ? "radio-button-on"
                        : "radio-button-off"
                    }
                    size={18}
                    color={
                      selected === c.id ? colors.brand : colors.muted
                    }
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.customerName}>{c.name}</Text>
                    {c.email ? (
                      <Text style={styles.customerEmail}>{c.email}</Text>
                    ) : null}
                  </View>
                </TouchableOpacity>
              ))}
              {customers.length === 0 && (
                <Text style={styles.noCustomers}>No customers found</Text>
              )}
            </ScrollView>
          )}

          <View style={styles.modalActions}>
            <TouchableOpacity style={styles.cancelBtn} onPress={onClose}>
              <Text style={styles.cancelBtnLabel}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity
              testID="comms-auto-testfire-go"
              style={[
                styles.fireBtn,
                (!selected || busy) && styles.fireBtnDisabled,
              ]}
              onPress={fire}
              disabled={!selected || busy}
            >
              {busy ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Text style={styles.fireBtnLabel}>Fire</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
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

function statusColor(status?: string): string {
  switch (status) {
    case "sent":
      return "#16A34A";
    case "failed":
      return "#DC2626";
    case "skipped_deduped":
      return "#F59E0B";
    case "skipped_conditions_not_met":
      return "#94A3B8";
    case "skipped_no_customer":
      return "#94A3B8";
    case "scheduled":
      return "#0284C7";
    default:
      return "#6B7280";
  }
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
  testBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brand,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.sm,
  },
  testBtnLabel: {
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
  section: { marginBottom: spacing.lg },
  sectionTitle: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
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
  eventsList: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  eventRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: 9,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  eventLeft: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  eventDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  eventStatus: {
    fontFamily: font.medium,
    fontSize: 11,
    color: colors.onSurface,
    textTransform: "capitalize",
  },
  eventDate: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
  },
  eventsEmpty: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  eventsEmptyText: {
    flex: 1,
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
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
    maxHeight: "80%",
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
  pickLabel: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.muted,
    paddingHorizontal: spacing.lg,
    marginBottom: spacing.sm,
  },
  customerList: { paddingHorizontal: spacing.lg, maxHeight: 300 },
  customerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  customerRowSelected: {
    backgroundColor: colors.brand + "0D",
  },
  customerName: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  customerEmail: {
    fontFamily: font.regular,
    fontSize: 11,
    color: colors.muted,
  },
  noCustomers: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: 20,
  },
  modalActions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.lg,
  },
  cancelBtn: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: radius.sm,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cancelBtnLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  fireBtn: {
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: radius.sm,
    backgroundColor: colors.brand,
    minWidth: 80,
    alignItems: "center",
  },
  fireBtnDisabled: { opacity: 0.4 },
  fireBtnLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
});
