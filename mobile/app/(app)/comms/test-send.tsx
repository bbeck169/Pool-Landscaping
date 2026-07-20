/**
 * Comms Test Send — Phase 4 · Mobile Parity.
 *
 * Manual form: pick channel → template → customer → POST /send-now.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  Alert,
  Platform,
  KeyboardAvoidingView,
} from "react-native";
import { useFocusEffect } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Header } from "@/src/components/widgets";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import {
  listEmailTemplates,
  listSmsTemplates,
  sendNow,
} from "@/src/api/comms";
import { api } from "@/src/api";

export default function CommsTestSendScreen() {
  const insets = useSafeAreaInsets();

  const [channel, setChannel] = useState<"email" | "sms">("email");
  const [templates, setTemplates] = useState<any[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [customers, setCustomers] = useState<any[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [templatesExpanded, setTemplatesExpanded] = useState(false);
  const [customersExpanded, setCustomersExpanded] = useState(false);

  const loadTemplates = useCallback(async () => {
    try {
      const d =
        channel === "email"
          ? await listEmailTemplates()
          : await listSmsTemplates();
      setTemplates(
        d.templates ||
          d[channel === "email" ? "email_templates" : "sms_templates"] ||
          d ||
          []
      );
    } catch {
      setTemplates([]);
    }
  }, [channel]);

  const loadCustomers = useCallback(async () => {
    try {
      const rows = await api.get("/customers");
      setCustomers(Array.isArray(rows) ? rows : []);
    } catch {
      setCustomers([]);
    }
  }, []);

  useFocusEffect(
    useCallback(() => {
      setLoading(true);
      Promise.all([loadTemplates(), loadCustomers()]).finally(() =>
        setLoading(false)
      );
    }, [loadTemplates, loadCustomers])
  );

  useEffect(() => {
    setSelectedTemplate("");
    loadTemplates();
  }, [channel, loadTemplates]);

  const onSend = async () => {
    if (!selectedTemplate || !selectedCustomer) {
      Alert.alert("Missing fields", "Select a template and customer.");
      return;
    }
    setSending(true);
    try {
      const d = await sendNow({
        channel,
        template_code: selectedTemplate,
        recipient_id: selectedCustomer,
      });
      Alert.alert(
        "Sent!",
        `Send ${d.send_id || d.id || "queued"} created successfully.`
      );
      setSelectedTemplate("");
      setSelectedCustomer("");
    } catch (e: any) {
      Alert.alert("Error", e.message || "Failed to send");
    } finally {
      setSending(false);
    }
  };

  const selectedTemplateName =
    templates.find((t) => t.code === selectedTemplate)?.name ||
    selectedTemplate ||
    "Select template…";
  const selectedCustomerName =
    customers.find((c) => c.id === selectedCustomer)?.name ||
    selectedCustomer ||
    "Select customer…";

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
    >
      <View testID="comms-test-send" style={styles.root}>
        <Header title="Test Send" subtitle="Send a template now" back />

        {loading ? (
          <ActivityIndicator
            testID="comms-test-send-loader"
            style={{ marginTop: 40 }}
            color={colors.brand}
          />
        ) : (
          <ScrollView
            contentContainerStyle={[
              styles.content,
              { paddingBottom: insets.bottom + 24 },
            ]}
            showsVerticalScrollIndicator={false}
            keyboardShouldPersistTaps="handled"
          >
            {/* Channel picker */}
            <Text style={styles.label}>Channel</Text>
            <View style={styles.channelRow}>
              <TouchableOpacity
                testID="comms-test-send-channel-email"
                style={[
                  styles.channelBtn,
                  channel === "email" && styles.channelBtnActive,
                ]}
                onPress={() => setChannel("email")}
              >
                <Ionicons
                  name="mail-outline"
                  size={18}
                  color={channel === "email" ? "#fff" : colors.onSurface}
                />
                <Text
                  style={[
                    styles.channelBtnLabel,
                    channel === "email" && styles.channelBtnLabelActive,
                  ]}
                >
                  Email
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                testID="comms-test-send-channel-sms"
                style={[
                  styles.channelBtn,
                  channel === "sms" && styles.channelBtnActive,
                ]}
                onPress={() => setChannel("sms")}
              >
                <Ionicons
                  name="chatbubble-outline"
                  size={18}
                  color={channel === "sms" ? "#fff" : colors.onSurface}
                />
                <Text
                  style={[
                    styles.channelBtnLabel,
                    channel === "sms" && styles.channelBtnLabelActive,
                  ]}
                >
                  SMS
                </Text>
              </TouchableOpacity>
            </View>

            {/* Template picker */}
            <Text style={styles.label}>Template</Text>
            <TouchableOpacity
              testID="comms-test-send-template-picker"
              style={styles.picker}
              onPress={() => {
                setTemplatesExpanded(!templatesExpanded);
                setCustomersExpanded(false);
              }}
            >
              <Text
                style={[
                  styles.pickerText,
                  !selectedTemplate && styles.pickerPlaceholder,
                ]}
                numberOfLines={1}
              >
                {selectedTemplateName}
              </Text>
              <Ionicons
                name={templatesExpanded ? "chevron-up" : "chevron-down"}
                size={16}
                color={colors.muted}
              />
            </TouchableOpacity>
            {templatesExpanded && (
              <View style={styles.dropdownList}>
                {templates.length === 0 ? (
                  <Text style={styles.dropdownEmpty}>
                    No {channel} templates
                  </Text>
                ) : (
                  templates.map((t) => (
                    <TouchableOpacity
                      key={t.code}
                      testID={`comms-test-send-tpl-${t.code}`}
                      style={[
                        styles.dropdownItem,
                        selectedTemplate === t.code &&
                          styles.dropdownItemSelected,
                      ]}
                      onPress={() => {
                        setSelectedTemplate(t.code);
                        setTemplatesExpanded(false);
                      }}
                    >
                      <Text style={styles.dropdownItemText}>
                        {t.name || t.code}
                      </Text>
                      <Text style={styles.dropdownItemCode}>{t.code}</Text>
                    </TouchableOpacity>
                  ))
                )}
              </View>
            )}

            {/* Customer picker */}
            <Text style={[styles.label, { marginTop: spacing.lg }]}>
              Recipient Customer
            </Text>
            <TouchableOpacity
              testID="comms-test-send-customer-picker"
              style={styles.picker}
              onPress={() => {
                setCustomersExpanded(!customersExpanded);
                setTemplatesExpanded(false);
              }}
            >
              <Text
                style={[
                  styles.pickerText,
                  !selectedCustomer && styles.pickerPlaceholder,
                ]}
                numberOfLines={1}
              >
                {selectedCustomerName}
              </Text>
              <Ionicons
                name={customersExpanded ? "chevron-up" : "chevron-down"}
                size={16}
                color={colors.muted}
              />
            </TouchableOpacity>
            {customersExpanded && (
              <View style={styles.dropdownList}>
                {customers.length === 0 ? (
                  <Text style={styles.dropdownEmpty}>No customers</Text>
                ) : (
                  customers.map((c) => (
                    <TouchableOpacity
                      key={c.id}
                      testID={`comms-test-send-cust-${c.id}`}
                      style={[
                        styles.dropdownItem,
                        selectedCustomer === c.id &&
                          styles.dropdownItemSelected,
                      ]}
                      onPress={() => {
                        setSelectedCustomer(c.id);
                        setCustomersExpanded(false);
                      }}
                    >
                      <Text style={styles.dropdownItemText}>{c.name}</Text>
                      {c.email ? (
                        <Text style={styles.dropdownItemCode}>
                          {c.email}
                        </Text>
                      ) : null}
                    </TouchableOpacity>
                  ))
                )}
              </View>
            )}

            {/* Send button */}
            <TouchableOpacity
              testID="comms-test-send-go"
              style={[
                styles.sendBtn,
                (!selectedTemplate || !selectedCustomer || sending) &&
                  styles.sendBtnDisabled,
              ]}
              onPress={onSend}
              disabled={!selectedTemplate || !selectedCustomer || sending}
            >
              {sending ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <>
                  <Ionicons name="rocket-outline" size={18} color="#fff" />
                  <Text style={styles.sendBtnLabel}>Send Now</Text>
                </>
              )}
            </TouchableOpacity>
          </ScrollView>
        )}
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  content: { padding: spacing.lg },
  label: {
    fontFamily: font.bold,
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  channelRow: {
    flexDirection: "row",
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  channelBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  channelBtnActive: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  channelBtnLabel: {
    fontFamily: font.semibold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  channelBtnLabelActive: { color: "#fff" },
  picker: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
  },
  pickerText: {
    fontFamily: font.medium,
    fontSize: fontSize.base,
    color: colors.onSurface,
    flex: 1,
    marginRight: 8,
  },
  pickerPlaceholder: { color: colors.muted },
  dropdownList: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    marginTop: 4,
    maxHeight: 200,
  },
  dropdownItem: {
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  dropdownItemSelected: {
    backgroundColor: colors.brand + "10",
  },
  dropdownItemText: {
    fontFamily: font.medium,
    fontSize: fontSize.sm,
    color: colors.onSurface,
  },
  dropdownItemCode: {
    fontFamily: font.regular,
    fontSize: 10,
    color: colors.muted,
    marginTop: 1,
  },
  dropdownEmpty: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    textAlign: "center",
    paddingVertical: 16,
  },
  sendBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.brand,
    borderRadius: radius.sm,
    paddingVertical: 14,
    marginTop: spacing.xl,
  },
  sendBtnDisabled: { opacity: 0.4 },
  sendBtnLabel: {
    fontFamily: font.bold,
    fontSize: fontSize.lg,
    color: "#fff",
  },
});
