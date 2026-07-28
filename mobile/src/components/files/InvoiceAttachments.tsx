/**
 * Phase F2b · Invoice / Estimate Attachments (mobile).
 *
 * Shared component for both invoice and estimate detail screens.
 *   purpose             = "invoice_attachment"
 *   linked_entity_type  = "invoice"
 *   linked_entity_id    = <doc.id>
 *   accept              = "image/*,application/pdf" (no video)
 *
 * Access control (mirrors web):
 *   Upload — admin / super_admin / manager only
 *   Delete — same (F0 backend gate enforces uploader-OR-admin)
 *   Customer / tech — read-only FileList, no FileUpload
 */
import React, { useCallback, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { FileUpload } from "./FileUpload";
import { FileList } from "./FileList";
import { colors, font, fontSize, spacing, radius } from "@/src/theme";

const PURPOSE = "invoice_attachment";
const ACCEPT = "image/*,application/pdf";

export function canUploadInvoiceAttachment(user: any): boolean {
  const role = String(user?.role || "").toLowerCase();
  return role === "admin" || role === "super_admin" || role === "manager";
}

type Props = {
  docId: string;
  isInvoice?: boolean;
  user: any;
  onCountChange?: (count: number) => void;
};

export function InvoiceAttachments({ docId, isInvoice = true, user, onCountChange }: Props) {
  const [nonce, setNonce] = useState(0);
  const [count, setCount] = useState<number | null>(null);
  const canUpload = canUploadInvoiceAttachment(user);
  const noun = isInvoice ? "invoice" : "estimate";

  const onUploaded = useCallback(() => setNonce((n) => n + 1), []);
  const onListChange = useCallback(
    (items: any[]) => {
      const c = (items || []).length;
      setCount(c);
      onCountChange?.(c);
    },
    [onCountChange],
  );

  if (!docId) return null;

  return (
    <View style={styles.card} testID="doc-attachments-card">
      <View style={styles.header}>
        <Ionicons name="attach-outline" size={18} color={colors.muted} />
        <Text style={styles.title}>
          Attachments{count != null && count > 0 ? ` (${count})` : ""}
        </Text>
      </View>
      <Text style={styles.subtitle}>
        Supporting documents for this {noun}.
      </Text>

      {canUpload && (
        <View style={styles.uploadWrap}>
          <FileUpload
            purpose={PURPOSE}
            linkedEntityType="invoice"
            linkedEntityId={docId}
            accept={ACCEPT}
            multiple
            maxFiles={10}
            onUploaded={onUploaded}
            buttonLabel="Choose Photo"
          />
        </View>
      )}

      <FileList
        key={nonce}
        linkedEntityType="invoice"
        linkedEntityId={docId}
        canDelete={canUpload}
        onChange={onListChange}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.lg,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginBottom: 4,
  },
  title: {
    fontFamily: font.bold,
    fontSize: fontSize.base,
    color: colors.onSurface,
  },
  subtitle: {
    fontFamily: font.regular,
    fontSize: fontSize.sm,
    color: colors.muted,
    marginBottom: spacing.md,
  },
  uploadWrap: {
    marginBottom: spacing.md,
  },
});

export default InvoiceAttachments;
