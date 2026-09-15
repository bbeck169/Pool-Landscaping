/**
 * Phase 4 · Batch A — Mobile Signature drawing-pad modal.
 *
 * Full-screen modal with a WebView-based signature canvas
 * (react-native-signature-canvas). On save, produces a PNG data URL +
 * signer name + ISO timestamp matching the web's value shape:
 *   { image_data_url, signer_name, signed_at }
 */
import React, { useRef, useState, useEffect } from "react";
import {
  View,
  Text,
  Modal,
  StyleSheet,
  TouchableOpacity,
  Alert,
  KeyboardAvoidingView,
  Platform } from "react-native";
import SignatureScreen from "react-native-signature-canvas";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";
import AppTextInput from "@/src/components/ui/AppTextInput";

type Props = {
  visible: boolean;
  onClose: () => void;
  onSave: (payload: {
    image_data_url: string;
    signer_name: string;
    signed_at: string;
  }) => void;
  defaultSignerName?: string;
  fieldLabel?: string;
};

const SIG_WEBSTYLE = `
  .m-signature-pad { box-shadow: none; border: none; }
  .m-signature-pad--body { border: none; }
  .m-signature-pad--body canvas { border-radius: 8px; }
  .m-signature-pad--footer { display: none; }
  body, html { margin: 0; padding: 0; }
`;

export default function SignaturePadModal({
  visible,
  onClose,
  onSave,
  defaultSignerName = "",
  fieldLabel = "Signature",
}: Props) {
  const sigRef = useRef<any>(null);
  const [signerName, setSignerName] = useState(defaultSignerName);
  const [isEmpty, setIsEmpty] = useState(true);

  useEffect(() => {
    if (visible) {
      setSignerName(defaultSignerName);
      setIsEmpty(true);
    }
  }, [visible, defaultSignerName]);

  const handleClear = () => {
    sigRef.current?.clearSignature();
    setIsEmpty(true);
  };

  const handleSave = () => {
    if (isEmpty) {
      Alert.alert("Draw your signature", "Please draw your signature before saving.");
      return;
    }
    if (!signerName.trim()) {
      Alert.alert("Name required", "Please enter your name to sign.");
      return;
    }
    sigRef.current?.readSignature();
  };

  const handleOK = (dataUrl: string) => {
    // react-native-signature-canvas returns a data URL from onOK
    if (!dataUrl || !dataUrl.startsWith("data:image")) {
      Alert.alert("Error", "Could not capture signature. Please try again.");
      return;
    }
    // Warn if large but proceed
    const approxKB = Math.round((dataUrl.length * 3) / 4 / 1024);
    if (approxKB > 500) {
      console.warn(`[SignaturePad] Signature is ~${approxKB}KB — larger than typical`);
    }
    onSave({
      image_data_url: dataUrl,
      signer_name: signerName.trim(),
      signed_at: new Date().toISOString(),
    });
  };

  const handleEmpty = () => {
    Alert.alert("Draw your signature", "Please draw your signature before saving.");
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
      testID="signature-pad-modal"
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={styles.root}
      >
        {/* Header */}
        <View style={styles.header} testID="signature-pad-header">
          <TouchableOpacity
            onPress={onClose}
            style={styles.headerButton}
            testID="signature-pad-cancel"
            activeOpacity={0.7}
          >
            <Text style={styles.cancelText}>Cancel</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle} numberOfLines={1}>
            Sign — {fieldLabel}
          </Text>
          <TouchableOpacity
            onPress={handleSave}
            style={[styles.headerButton, styles.saveButton]}
            testID="signature-pad-save"
            activeOpacity={0.7}
          >
            <Ionicons name="checkmark" size={16} color="#fff" />
            <Text style={styles.saveText}>Save</Text>
          </TouchableOpacity>
        </View>

        {/* Name input */}
        <View style={styles.nameSection}>
          <Text style={styles.labelText}>Signer name</Text>
          <AppTextInput
            value={signerName}
            onChangeText={setSignerName}
            style={styles.nameInput}
            placeholder="Full name of signer"
            placeholderTextColor={colors.muted}
            testID="signature-pad-name-input"
          />
        </View>

        {/* Canvas */}
        <View style={styles.canvasSection}>
          <Text style={styles.labelText}>Draw your signature below</Text>
          <View style={styles.canvasWrap} testID="signature-pad-canvas-wrap">
            <SignatureScreen
              ref={sigRef}
              onOK={handleOK}
              onEmpty={handleEmpty}
              onBegin={() => setIsEmpty(false)}
              webStyle={SIG_WEBSTYLE}
              backgroundColor="#FAFAFA"
              penColor={colors.onSurface}
              imageType="image/png"
              dataURL=""
              style={styles.canvas}
              descriptionText=""
            />
          </View>
          <Text style={styles.hintText}>
            Use your finger or stylus. This drawing will be embedded in the exported PDF.
          </Text>
        </View>

        {/* Bottom bar */}
        <View style={styles.bottomBar}>
          <TouchableOpacity
            onPress={handleClear}
            disabled={isEmpty}
            style={[styles.clearButton, isEmpty && styles.clearButtonDisabled]}
            testID="signature-pad-clear"
            activeOpacity={0.7}
          >
            <Ionicons
              name="trash-outline"
              size={16}
              color={isEmpty ? colors.muted : colors.onSurface}
            />
            <Text
              style={[
                styles.clearButtonText,
                isEmpty && { color: colors.muted },
              ]}
            >
              Clear
            </Text>
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.surfaceSecondary,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.lg,
    paddingVertical: 12,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: {
    fontSize: fontSize.base,
    fontFamily: font.bold,
    color: colors.onSurface,
    flex: 1,
    textAlign: "center",
    marginHorizontal: 8,
  },
  headerButton: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: radius.md,
  },
  cancelText: {
    fontSize: fontSize.sm,
    fontFamily: font.semibold,
    color: colors.onSurfaceSecondary,
  },
  saveButton: {
    backgroundColor: colors.brand,
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  saveText: {
    fontSize: fontSize.sm,
    fontFamily: font.bold,
    color: "#fff",
  },
  nameSection: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
  },
  labelText: {
    fontSize: 12,
    fontFamily: font.bold,
    color: colors.onSurfaceSecondary,
    marginBottom: 4,
  },
  nameInput: {
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
  canvasSection: {
    flex: 1,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
  },
  canvasWrap: {
    flex: 1,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    borderStyle: "dashed",
    overflow: "hidden",
    backgroundColor: "#FAFAFA",
    marginTop: 4,
  },
  canvas: {
    flex: 1,
  },
  hintText: {
    fontSize: 11,
    fontFamily: font.regular,
    color: colors.muted,
    marginTop: 6,
  },
  bottomBar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: 12,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  clearButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  clearButtonDisabled: {
    opacity: 0.5,
  },
  clearButtonText: {
    fontSize: fontSize.sm,
    fontFamily: font.semibold,
    color: colors.onSurface,
  },
});
