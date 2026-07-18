import React from "react";
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  TouchableOpacity,
  Switch,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, radius } from "@/src/theme";
import TemplateTableField from "./TemplateTableField";

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
        <TextInput
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
        <TextInput
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
    return (
      <View testID={testIdBase}>
        {renderLabel()}
        <TextInput
          value={value != null ? String(value) : ""}
          editable={!disabled}
          onChangeText={(t) => onChange(t === "" ? "" : Number(t))}
          keyboardType="decimal-pad"
          style={[styles.input, disabled && styles.inputDisabled]}
          testID={`${testIdBase}-input`}
        />
        {renderHelp()}
      </View>
    );
  }

  // Date
  if (type === "date") {
    return (
      <View testID={testIdBase}>
        {renderLabel()}
        <TextInput
          value={value ?? ""}
          editable={!disabled}
          onChangeText={onChange}
          placeholder="YYYY-MM-DD"
          placeholderTextColor={colors.muted}
          style={[styles.input, disabled && styles.inputDisabled]}
          testID={`${testIdBase}-input`}
        />
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

  // Signature
  if (type === "signature") {
    const sig = value && typeof value === "object" ? value : null;
    return (
      <View testID={testIdBase}>
        {renderLabel()}
        {sig?.name ? (
          <View style={styles.signedBox}>
            <View style={styles.signedRow}>
              <Ionicons name="checkmark-circle" size={18} color={colors.success} />
              <View style={{ flex: 1 }}>
                <Text style={styles.signedName}>{sig.name}</Text>
                <Text style={styles.signedDate}>
                  Signed {new Date(sig.date).toLocaleString()}
                </Text>
              </View>
            </View>
            {!disabled && (
              <TouchableOpacity
                onPress={() => onChange(null)}
                testID={`${testIdBase}-clear`}
              >
                <Text style={styles.clearText}>Clear</Text>
              </TouchableOpacity>
            )}
          </View>
        ) : (
          <TouchableOpacity
            onPress={() => {
              if (disabled) return;
              onChange({
                name: currentUserName || "Signer",
                date: new Date().toISOString(),
              });
            }}
            disabled={disabled}
            style={[styles.signBtn, disabled && { opacity: 0.6 }]}
            activeOpacity={0.7}
            testID={`${testIdBase}-sign`}
          >
            <Ionicons name="pencil-outline" size={16} color={colors.brand} />
            <Text style={styles.signBtnText}>
              Sign as {currentUserName || "me"}
            </Text>
          </TouchableOpacity>
        )}
        {renderHelp()}
      </View>
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
      <TextInput
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
  signedBox: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: 12,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  signedRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    flex: 1,
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
  },
  clearText: {
    fontSize: 12,
    fontFamily: font.semibold,
    color: colors.error,
  },
  signBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
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
