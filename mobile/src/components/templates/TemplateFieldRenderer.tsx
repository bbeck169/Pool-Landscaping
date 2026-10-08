import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Switch,
  Platform,
  Image } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, radius } from "@/src/theme";
import TemplateTableField from "./TemplateTableField";
import SignaturePadModal from "./SignaturePadModal";
import AppTextInput from "@/src/components/ui/AppTextInput";
import { parseNumberInput, numberRangeError, makeSignatureStamp, todayISODate } from "./fieldUtils";

type Field = {
  type: string;
  key: string;
  label?: string;
  help_text?: string;
  required?: boolean;
  options?: string[];
  min?: number;
  max?: number;
  columns?: any[];
};

export default function TemplateFieldRenderer({
  field,
  value,
  onChange,
  disabled = false,
  currentUserName = "",
}: {
  field: Field;
  value: any;
  onChange: (v: any) => void;
  disabled?: boolean;
  currentUserName?: string;
}) {
  const { type, key, label, help_text, required, options } = field;
  const testIdBase = `template-field-${key || label || type}`;

  // Header type — just a section label
  if (type === "header") {
    return (
      <View style={styles.headerField} testID={testIdBase}>
        <Text style={styles.headerLabel}>{label}</Text>
        {help_text ? <Text style={styles.helpText}>{help_text}</Text> : null}
      </View>
    );
  }

  const renderLabel = () => (
    <Text style={styles.label}>
      {label}
      {required && <Text style={{ color: colors.error }}> *</Text>}
    </Text>
  );

  const renderHelp = () =>
    help_text ? <Text style={styles.helpText}>{help_text}</Text> : null;

  // Text field
  if (type === "text") {
    return (
      <View testID={testIdBase}>
        {renderLabel()}
        <AppTextInput
          value={value ?? ""}
          editable={!disabled}
          onChangeText={onChange}
          style={[styles.input, disabled && styles.inputDisabled]}
          testID={`${testIdBase}-input`}
        />
        {renderHelp()}
      </View>
    );
  }

  // Long text
  if (type === "long_text") {
    return (
      <View testID={testIdBase}>
        {renderLabel()}
        <AppTextInput
          value={value ?? ""}
          editable={!disabled}
          onChangeText={onChange}
          multiline
          numberOfLines={4}
          textAlignVertical="top"
          style={[styles.input, styles.textArea, disabled && styles.inputDisabled]}
          testID={`${testIdBase}-input`}
        />
        {renderHelp()}
      </View>
    );
  }

  // Number
  if (type === "number") {
    const rangeErr = numberRangeError(field, value);
    const hasMin = typeof field.min === "number";
    const hasMax = typeof field.max === "number";
    const rangeHint = hasMin && hasMax ? `Range ${field.min}–${field.max}` : hasMin ? `Min ${field.min}` : hasMax ? `Max ${field.max}` : "";
    return (
      <View testID={testIdBase}>
        {renderLabel()}
        <AppTextInput
          value={value != null ? String(value) : ""}
          editable={!disabled}
          onChangeText={(t) => onChange(parseNumberInput(t))}
          keyboardType="decimal-pad"
          style={[styles.input, disabled && styles.inputDisabled, rangeErr ? styles.inputError : null]}
          testID={`${testIdBase}-input`}
        />
        {rangeErr ? (
          <Text style={styles.errorText} testID={`${testIdBase}-range-error`}>{rangeErr}</Text>
        ) : rangeHint ? (
          <Text style={styles.helpText}>{rangeHint}</Text>
        ) : null}
        {renderHelp()}
      </View>
    );
  }

  // Date
  if (type === "date") {
    return (
      <View testID={testIdBase}>
        {renderLabel()}
        <View style={styles.dateRow}>
          <AppTextInput
            value={value ?? ""}
            editable={!disabled}
            onChangeText={onChange}
            placeholder="YYYY-MM-DD"
            placeholderTextColor={colors.muted}
            style={[styles.input, styles.dateInput, disabled && styles.inputDisabled]}
            testID={`${testIdBase}-input`}
          />
          {!disabled && (
            <TouchableOpacity onPress={() => onChange(todayISODate())} style={styles.todayBtn} testID={`${testIdBase}-today`}>
              <Text style={styles.todayText}>Today</Text>
            </TouchableOpacity>
          )}
        </View>
        {renderHelp()}
      </View>
    );
  }

  // Checkbox
  if (type === "checkbox") {
    return (
      <View testID={testIdBase} style={styles.checkboxRow}>
        <Switch
          value={!!value}
          disabled={disabled}
          onValueChange={onChange}
          trackColor={{ false: colors.border, true: colors.brand }}
          thumbColor={value ? "#fff" : "#f4f3f4"}
          testID={`${testIdBase}-input`}
        />
        <Text style={styles.checkboxLabel}>
          {label}
          {required && <Text style={{ color: colors.error }}> *</Text>}
        </Text>
        {help_text ? (
          <Text style={styles.checkboxHelp}>{help_text}</Text>
        ) : null}
      </View>
    );
  }

  // Select
  if (type === "select") {
    const opts = options || [];
    return (
      <View testID={testIdBase}>
        {renderLabel()}
        <View style={styles.selectContainer}>
          {[{ label: "— Select —", value: "" }, ...opts.map((o) => ({ label: o, value: o }))].map(
            (opt, i) => {
              const isActive = (value ?? "") === (typeof opt === "string" ? opt : opt.value);
              const optValue = typeof opt === "string" ? opt : opt.value;
              const optLabel = typeof opt === "string" ? opt : opt.label;
              return (
                <TouchableOpacity
                  key={i}
                  testID={`${testIdBase}-opt-${optValue}`}
                  onPress={() => !disabled && onChange(optValue)}
                  disabled={disabled}
                  style={[
                    styles.selectChip,
                    isActive && styles.selectChipActive,
                    disabled && { opacity: 0.6 },
                  ]}
                  activeOpacity={0.7}
                >
                  <Text
                    style={[
                      styles.selectChipText,
                      isActive && styles.selectChipTextActive,
                    ]}
                  >
                    {optLabel}
                  </Text>
                </TouchableOpacity>
              );
            }
          )}
        </View>
        {renderHelp()}
      </View>
    );
  }

  // Signature — Phase 4 drawing pad (replaces Phase 2 stamp)
  if (type === "signature") {
    return (
      <SignatureFieldInner
        field={field}
        value={value}
        onChange={onChange}
        disabled={disabled}
        currentUserName={currentUserName}
        testIdBase={testIdBase}
      />
    );
  }

  // Table
  if (type === "table") {
    return (
      <View testID={testIdBase}>
        {label ? renderLabel() : null}
        <TemplateTableField
          field={field}
          value={value}
          onChange={onChange}
          disabled={disabled}
        />
        {renderHelp()}
      </View>
    );
  }

  // Fallback
  return (
    <View testID={testIdBase}>
      {renderLabel()}
      <AppTextInput
        value={value ?? ""}
        editable={!disabled}
        onChangeText={onChange}
        style={[styles.input, disabled && styles.inputDisabled]}
        testID={`${testIdBase}-input`}
      />
      <Text style={styles.unknownType}>Unknown field type: {type}</Text>
    </View>
  );
}

// ─── Signature sub-component (needs local state for modal) ──────────
function formatSignedAt(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return String(iso);
    return d.toLocaleString();
  } catch {
    return String(iso);
  }
}

function SignatureFieldInner({
  field,
  value,
  onChange,
  disabled,
  currentUserName,
  testIdBase,
}: {
  field: Field;
  value: any;
  onChange: (v: any) => void;
  disabled: boolean;
  currentUserName: string;
  testIdBase: string;
}) {
  const [padOpen, setPadOpen] = useState(false);

  // Phase 4 shape: { image_data_url, signer_name, signed_at }
  // Legacy Phase 2 stamp shape: { name, date }
  // Legacy plain string: treat as signer_name only
  let sig: any = null;
  let signerName: string | null = null;
  let signedAt: string | null = null;
  let imageDataUrl: string | null = null;

  if (typeof value === "string" && value) {
    // Backward compat: bare string = legacy stamp
    signerName = value;
  } else if (value && typeof value === "object") {
    sig = value;
    signerName = sig.signer_name || sig.name || null;
    signedAt = sig.signed_at || sig.date || null;
    imageDataUrl = sig.image_data_url || null;
  }

  const hasSig = Boolean(signerName);

  return (
    <View testID={testIdBase}>
      <Text style={styles.label}>
        {field.label}
        {field.required && <Text style={{ color: colors.error }}> *</Text>}
      </Text>

      {hasSig ? (
        <View style={styles.signedBox} testID={`${testIdBase}-signed`}>
          <View style={styles.signedContent}>
            {imageDataUrl ? (
              <Image
                source={{ uri: imageDataUrl }}
                style={styles.signatureImage}
                resizeMode="contain"
                testID={`${testIdBase}-image`}
              />
            ) : (
              <Ionicons name="checkmark-circle" size={18} color={colors.success} />
            )}
            <View style={{ flex: 1 }}>
              <Text style={styles.signedName} testID={`${testIdBase}-stamp`}>
                {signedAt ? `${signerName} • ${signedAt}` : `Signed by ${signerName}`}
              </Text>
              {signedAt ? (
                <Text style={styles.signedDate}>{formatSignedAt(signedAt)}</Text>
              ) : null}
            </View>
          </View>
          {!disabled && (
            <View style={styles.signActions}>
              <TouchableOpacity
                onPress={() => onChange(makeSignatureStamp(currentUserName))}
                testID={`${testIdBase}-resign`}
                activeOpacity={0.7}
              >
                <View style={styles.resignRow}>
                  <Ionicons name="refresh-outline" size={12} color={colors.brand} />
                  <Text style={styles.resignText}>Re-sign</Text>
                </View>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={() => onChange(null)}
                testID={`${testIdBase}-clear`}
              >
                <Text style={styles.clearText}>Clear</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
      ) : (
        <View style={styles.signBtnRow}>
          <TouchableOpacity
            onPress={() => !disabled && onChange(makeSignatureStamp(currentUserName))}
            disabled={disabled}
            style={[styles.signBtn, disabled && { opacity: 0.6 }]}
            activeOpacity={0.7}
            testID={`${testIdBase}-sign`}
          >
            <Ionicons name="checkmark-done-outline" size={16} color={colors.brand} />
            <Text style={styles.signBtnText}>Sign</Text>
          </TouchableOpacity>
          {!disabled && (
            <TouchableOpacity onPress={() => setPadOpen(true)} style={styles.drawLink} testID={`${testIdBase}-draw`}>
              <Text style={styles.drawLinkText}>Draw instead</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      {field.help_text ? (
        <Text style={styles.helpText}>{field.help_text}</Text>
      ) : null}

      <SignaturePadModal
        visible={padOpen}
        onClose={() => setPadOpen(false)}
        defaultSignerName={signerName || currentUserName || ""}
        fieldLabel={field.label || "Signature"}
        onSave={(payload) => {
          onChange(payload);
          setPadOpen(false);
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  headerField: {
    marginTop: 8,
    marginBottom: 4,
  },
  headerLabel: {
    fontSize: fontSize.base,
    fontFamily: font.bold,
    color: colors.onSurface,
  },
  label: {
    fontSize: 12,
    fontFamily: font.bold,
    color: colors.onSurfaceSecondary,
    marginBottom: 4,
  },
  helpText: {
    fontSize: 11,
    fontFamily: font.regular,
    color: colors.muted,
    marginTop: 4,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 12,
    paddingVertical: Platform.OS === "ios" ? 10 : 8,
    fontSize: fontSize.base,
    fontFamily: font.regular,
    color: colors.onSurface,
    backgroundColor: "#fff",
  },
  inputDisabled: {
    backgroundColor: colors.surfaceSecondary,
  },
  textArea: {
    minHeight: 90,
    textAlignVertical: "top",
  },
  checkboxRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  checkboxLabel: {
    fontSize: fontSize.base,
    fontFamily: font.regular,
    color: colors.onSurface,
  },
  checkboxHelp: {
    fontSize: 11,
    fontFamily: font.regular,
    color: colors.muted,
    marginLeft: 8,
  },
  selectContainer: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  selectChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  selectChipActive: {
    borderColor: colors.brand,
    backgroundColor: colors.brandTertiary,
  },
  selectChipText: {
    fontSize: fontSize.sm,
    fontFamily: font.medium,
    color: colors.onSurface,
  },
  selectChipTextActive: {
    color: colors.brand,
    fontFamily: font.bold,
  },
  // Signature styles
  signedBox: {
    padding: 12,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  signedContent: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
  },
  signatureImage: {
    width: 200,
    height: 80,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: "#fff",
  },
  signedName: {
    fontSize: fontSize.base,
    fontFamily: font.bold,
    color: colors.onSurface,
  },
  signedDate: {
    fontSize: 11,
    fontFamily: font.regular,
    color: colors.muted,
    marginTop: 2,
  },
  signActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
    marginTop: 8,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  resignRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  resignText: {
    fontSize: 12,
    fontFamily: font.semibold,
    color: colors.brand,
  },
  clearText: {
    fontSize: 12,
    fontFamily: font.semibold,
    color: colors.error,
  },
  inputError: { borderColor: colors.error },
  errorText: { fontSize: 11, fontFamily: font.semibold, color: colors.error, marginTop: 4 },
  dateRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  dateInput: { flex: 1 },
  todayBtn: {
    minHeight: 44, paddingHorizontal: 14, justifyContent: "center", borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.brandTertiary,
  },
  todayText: { fontSize: fontSize.sm, fontFamily: font.bold, color: colors.brand },
  signBtnRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  drawLink: { minHeight: 44, justifyContent: "center", paddingHorizontal: 4 },
  drawLinkText: { fontSize: 12, fontFamily: font.semibold, color: colors.onSurfaceSecondary, textDecorationLine: "underline" },
  signBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    minHeight: 44,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.brandTertiary,
    alignSelf: "flex-start",
  },
  signBtnText: {
    fontSize: fontSize.sm,
    fontFamily: font.bold,
    color: colors.brand,
  },
  unknownType: {
    fontSize: 11,
    fontFamily: font.regular,
    color: colors.warning,
    marginTop: 4,
  },
});
