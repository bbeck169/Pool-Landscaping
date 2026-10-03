/**
 * ConvertToInvoiceButton — shared button for quote and estimate detail screens.
 *
 * Mobile parity for web f5dd1eb0a. Renders one of three states:
 * - Convert button (default — not yet converted)
 * - "View invoice →" link (converted — has converted_invoice_id)
 * - null (role not permitted)
 *
 * Props:
 * - docType: "quote" | "estimate" — controls endpoint + testID prefix
 * - docId: the document's id
 * - convertedInvoiceId: from the fetched document (null if not converted)
 * - userRole: current user's role string
 * - onConverted(invoiceId): callback after successful conversion
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api";
import { useToast } from "@/src/components/ToastProvider";
import { canUserConvertToInvoice } from "@/src/utils/convertToInvoice";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";

interface Props {
  docType: "quote" | "estimate";
  docId: string;
  convertedInvoiceId?: string | null;
  userRole?: string | null;
  onConverted?: (invoiceId: string) => void;
}

export default function ConvertToInvoiceButton({
  docType,
  docId,
  convertedInvoiceId,
  userRole,
  onConverted,
}: Props) {
  const router = useRouter();
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [localConvertedId, setLocalConvertedId] = useState<string | null>(null);

  const prefix = docType === "quote" ? "qd" : "est";
  const effectiveConvertedId = convertedInvoiceId || localConvertedId;

  // Role gate
  if (!canUserConvertToInvoice(userRole)) return null;

  // Converted state → "View invoice →" link
  if (effectiveConvertedId) {
    return (
      <Pressable
        testID={`${prefix}-view-converted-invoice`}
        style={s.viewLink}
        onPress={() => router.push(`/quote/${effectiveConvertedId}`)}
      >
        <Ionicons name="document-text-outline" size={16} color={colors.brand} />
        <Text style={s.viewLinkText}>View invoice →</Text>
      </Pressable>
    );
  }

  // Default state → Convert button
  const handleConvert = async () => {
    setBusy(true);
    try {
      const endpoint =
        docType === "quote"
          ? `/quotes/${docId}/convert-to-invoice`
          : `/estimates/${docId}/convert-to-invoice`;

      const resp = await api.post(endpoint, {});
      const invoiceId = resp?.invoice_id;

      if (invoiceId) {
        showToast("Converted to invoice", "success");
        setLocalConvertedId(invoiceId);
        onConverted?.(invoiceId);
        router.push(`/quote/${invoiceId}`);
      } else {
        // 201 but no invoice_id — reload detail without navigating
        showToast("Converted — reloading…", "success");
        onConverted?.("");
      }
    } catch (e: any) {
      const status = e?.status;
      const detail = e?.body?.detail || e?.data?.detail;

      if (status === 409) {
        // Already converted
        const existingId =
          typeof detail === "object" ? detail?.invoice_id : undefined;

        if (existingId) {
          setLocalConvertedId(existingId);
          showToast("Already converted — opening invoice", "info");
          router.push(`/quote/${existingId}`);
        } else {
          showToast("This document was already converted to an invoice", "warning");
        }
      } else {
        const msg =
          typeof detail === "string"
            ? detail
            : e?.message || "Convert to invoice failed";
        showToast(msg, "error");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Pressable
      testID={`${prefix}-convert-to-invoice`}
      style={[s.btn, busy && s.btnDisabled]}
      onPress={handleConvert}
      disabled={busy}
    >
      {busy ? (
        <ActivityIndicator size={16} color="#fff" />
      ) : (
        <Ionicons name="swap-horizontal-outline" size={18} color="#fff" />
      )}
      <Text style={s.btnText}>Convert to Invoice</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  btn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.brand,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: 20,
    minHeight: 48,
  },
  btnDisabled: {
    opacity: 0.6,
  },
  btnText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#fff",
  },
  viewLink: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: 16,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  viewLinkText: {
    fontFamily: font.semibold,
    fontSize: fontSize.sm,
    color: colors.brand,
  },
});
