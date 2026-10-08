/**
 * Templates Library — Phase 3 (Mobile) · My Templates group list.
 * Mirrors web `TemplateInstanceList.jsx`: one titled group (Drafts /
 * Finalized) with row actions Open (tap row), Duplicate, Delete, and
 * Download PDF (finalized only).
 */
import React from "react";
import { View, Text, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors, font, fontSize, radius, spacing } from "@/src/theme";
import { CATEGORY_LABEL } from "@/src/api/templates";
import TemplateStatusPill from "./TemplateStatusPill";

type Props = {
  title: string;
  instances: any[];
  definitionsByCode: Record<string, any>;
  pendingIds?: Set<string>;
  downloadingId?: string | null;
  onOpen: (inst: any) => void;
  onDuplicate: (inst: any) => void;
  onDelete: (inst: any) => void;
  onDownload?: (inst: any) => void;
};

function ActionBtn({ icon, color, onPress, testID, label }: {
  icon: any; color: string; onPress: () => void; testID: string; label: string;
}) {
  return (
    <TouchableOpacity onPress={onPress} style={styles.actionBtn} testID={testID} accessibilityLabel={label}>
      <Ionicons name={icon} size={19} color={color} />
    </TouchableOpacity>
  );
}

function InstanceRow({ inst, defn, pending, downloading, onOpen, onDuplicate, onDelete, onDownload }: any) {
  return (
    <TouchableOpacity style={styles.row} onPress={() => onOpen(inst)} activeOpacity={0.7} testID={`template-instance-row-${inst.id}`}>
      <View style={styles.info}>
        <Text style={styles.title} numberOfLines={1}>{inst.title || "(untitled)"}</Text>
        <Text style={styles.sub} numberOfLines={1}>
          {defn?.title || inst.template_code}
          {defn?.category ? ` · ${CATEGORY_LABEL[defn.category] || defn.category}` : ""}
        </Text>
        <View style={styles.meta}>
          <TemplateStatusPill status={inst.status} />
          {pending ? (
            <View style={styles.unsynced} testID={`template-instance-unsynced-${inst.id}`}>
              <Ionicons name="cloud-offline-outline" size={11} color="#A16207" />
              <Text style={styles.unsyncedText}>Unsynced</Text>
            </View>
          ) : null}
          <Text style={styles.date}>{inst.updated_at ? new Date(inst.updated_at).toLocaleDateString() : "—"}</Text>
        </View>
      </View>
      <View style={styles.actions}>
        {inst.status === "finalized" && onDownload ? (
          downloading ? <View style={styles.actionBtn}><ActivityIndicator size="small" color={colors.brand} /></View> :
          <ActionBtn icon="download-outline" color={colors.brand} label="Download PDF" onPress={() => onDownload(inst)} testID={`template-instance-download-${inst.id}`} />
        ) : null}
        <ActionBtn icon="copy-outline" color={colors.onSurfaceSecondary} label="Duplicate" onPress={() => onDuplicate(inst)} testID={`template-instance-duplicate-${inst.id}`} />
        <ActionBtn icon="trash-outline" color={colors.error} label="Delete" onPress={() => onDelete(inst)} testID={`template-instance-delete-${inst.id}`} />
      </View>
    </TouchableOpacity>
  );
}

export default function TemplateInstanceList({ title, instances, definitionsByCode, pendingIds, downloadingId, ...handlers }: Props) {
  if (!instances?.length) return null;
  return (
    <View style={styles.group} testID={`template-instance-group-${title.toLowerCase()}`}>
      <Text style={styles.groupTitle}>
        {title} <Text style={styles.groupCount}>({instances.length})</Text>
      </Text>
      {instances.map((inst) => (
        <InstanceRow
          key={inst.id}
          inst={inst}
          defn={definitionsByCode?.[inst.template_code]}
          pending={pendingIds?.has(inst.id)}
          downloading={downloadingId === inst.id}
          {...handlers}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  group: { marginBottom: spacing.xl },
  groupTitle: {
    fontSize: 12, fontFamily: font.bold, color: colors.onSurfaceSecondary,
    textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 8,
  },
  groupCount: { fontFamily: font.regular, color: colors.muted },
  row: {
    flexDirection: "row", alignItems: "center", paddingLeft: 14, paddingRight: 4, paddingVertical: 10,
    backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border, marginBottom: 8,
  },
  info: { flex: 1, gap: 2 },
  title: { fontSize: fontSize.base, fontFamily: font.semibold, color: colors.onSurface },
  sub: { fontSize: 12, fontFamily: font.regular, color: colors.onSurfaceSecondary },
  meta: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4, flexWrap: "wrap" },
  date: { fontSize: 11, fontFamily: font.regular, color: colors.muted },
  unsynced: { flexDirection: "row", alignItems: "center", gap: 3, backgroundColor: "#FEF9C3", paddingHorizontal: 6, paddingVertical: 1, borderRadius: 999 },
  unsyncedText: { fontSize: 10, fontFamily: font.bold, color: "#A16207" },
  actions: { flexDirection: "row", alignItems: "center" },
  actionBtn: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
});
