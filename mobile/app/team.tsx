/**
 * Team page — staff roster with kebab menu actions.
 *
 * Port of frontend/src/pages/ops/OpsHub.jsx (Team Roster section).
 *
 * Features:
 * - List all team members with role badges
 * - Kebab (⋮) menu per row with: Reset Password, Delete, Undelete
 * - Permission matrix enforced client-side (backend re-enforces):
 *   - Admin: can delete/reset techs only
 *   - Super_admin: can delete/reset anyone except self & last super_admin
 *   - Kebab hidden when no actions available
 * - Reset Password modal: custom pw OR auto-generate temp pw
 * - Delete confirm dialog
 * - Show Deleted toggle (super_admin only) with Undelete on grayed rows
 */
import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, RefreshControl, Pressable, Alert, Modal, Switch, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect } from "expo-router";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/ToastProvider";
import { writeCache, readCache } from "@/src/services/readCache";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Loading, EmptyState, PrimaryButton } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { useBulkSelect, BulkCheckbox, BulkActionBar } from "@/src/components/bulk-select/BulkSelectToolkit";
import AppTextInput from "@/src/components/ui/AppTextInput";

const TECH_ROLES = ["pool_tech", "landscape_tech", "technician"];

// Feb-2026 · Multi-category tech assignment — options mirror the
// web ``AdminUsersList`` inline dropdown.  Empty ``value`` maps to
// ``null`` on the wire (unassigned).
const DEPT_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "",                label: "Unassigned" },
  { value: "pool_tech",       label: "Pool tech" },
  { value: "landscape_tech",  label: "Landscape tech" },
  { value: "both",            label: "Both" },
];
const DEPT_LABEL: Record<string, string> = Object.fromEntries(
  DEPT_OPTIONS.map((o) => [o.value || "null", o.label]),
);

// Feb-2026 · Multi-category tech assignment P1 follow-up — same
// legacy→modern map as ``backend/migrations/normalize_user_department_tokens.py``.
// Used ONLY by the chip fallback / one-tap Normalize on rows whose
// stored value pre-dates the migration.
const LEGACY_DEPT_MAP: Record<string, string> = {
  pool:        "pool_tech",
  landscape:   "landscape_tech",
  landscaping: "landscape_tech",
};

export default function Team() {
  const { user } = useAuth();
  const { showToast } = useToast();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [showDeleted, setShowDeleted] = useState(false);

  // Modal targets
  const [resetTarget, setResetTarget] = useState<any>(null);
  const [deleteTarget, setDeleteTarget] = useState<any>(null);
  const [actionTarget, setActionTarget] = useState<any>(null);
  // Feb-2026 · Multi-category tech assignment — separate target so
  // the dept-picker sheet can open independently from the action
  // sheet without losing the row context on the parent tap.
  const [deptTarget, setDeptTarget] = useState<any>(null);

  const myRole = (user?.role || "").toLowerCase();
  const isSuperAdmin = myRole === "super_admin";
  const isAdmin = myRole === "admin" || isSuperAdmin;

  const load = useCallback(async () => {
    try {
      const path = showDeleted ? "/team?include_deleted=true" : "/team";
      const data = await api.get(path);
      setItems(data);
      writeCache(`team:${showDeleted ? "deleted" : "active"}`, data).catch(() => {});
    } catch {
      const cached = await readCache<any[]>(`team:${showDeleted ? "deleted" : "active"}`);
      setItems(cached ?? []);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [showDeleted]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const canResetRow = (row: any) => {
    if (!isAdmin) return false;
    if (row.id === user?.id) return false;
    if (row.deleted_at) return false;
    const targetRole = (row.role || "").toLowerCase();
    if (isSuperAdmin) return true;
    return TECH_ROLES.includes(targetRole);
  };

  const canDeleteRow = (row: any) => {
    if (!isAdmin) return false;
    if (row.id === user?.id) return false;
    if (row.deleted_at) return false;
    const targetRole = (row.role || "").toLowerCase();
    if (isSuperAdmin) return true;
    return TECH_ROLES.includes(targetRole);
  };

  const canUndeleteRow = (row: any) => isSuperAdmin && !!row.deleted_at;

  // Feb-2026 · Multi-category tech assignment — admins can edit
  // dept for any non-deleted tech-role row (admin/owner/office
  // stay unassigned or "both" only on the backend).
  const canEditDeptRow = (row: any) => {
    if (!isAdmin) return false;
    if (row.deleted_at) return false;
    return TECH_ROLES.includes((row.role || "").toLowerCase());
  };

  // Feb-2026 · Multi-category tech assignment — optimistic dept
  // update, mirrors the web AdminUsersList.doDeptChange.  Empty
  // ``nextDeptRaw`` maps to ``null`` on the wire.
  const doDeptChange = async (row: any, nextDeptRaw: string) => {
    const nextDept = nextDeptRaw === "" ? null : nextDeptRaw;
    const prevDept = row.department ?? null;
    if (nextDept === prevDept) { setDeptTarget(null); return; }
    setItems((prev) => prev.map((r) =>
      r.id === row.id ? { ...r, department: nextDept } : r,
    ));
    setDeptTarget(null);
    try {
      await api.put(`/admin/users/${row.id}/department`, {
        department: nextDept,
      });
      Alert.alert(
        "Department updated",
        `${row.name || row.email} → ${DEPT_LABEL[nextDept || "null"] || "Unassigned"}`,
      );
    } catch (e: any) {
      setItems((prev) => prev.map((r) =>
        r.id === row.id ? { ...r, department: prevDept } : r,
      ));
      Alert.alert("Department update failed", e?.message || "Try again");
    }
  };

  const doUndelete = async (row: any) => {
    try {
      await api.post(`/users/${row.id}/undelete`, {});
      Alert.alert("Restored", `${row.name || row.email} has been restored.`);
      load();
    } catch (e: any) {
      Alert.alert("Undelete failed", e.message);
    }
  };

  const renderRow = ({ item }: { item: any }) => {
    const isSelf = item.id === user?.id;
    const isDeleted = !!item.deleted_at;
    const cReset = canResetRow(item);
    const cDelete = canDeleteRow(item);
    const cUndelete = canUndeleteRow(item);
    const cEditDept = canEditDeptRow(item);
    const anyKebab = cReset || cDelete || cUndelete || cEditDept;
    const role = (item.role || "unknown").toLowerCase();
    const isItemAdmin = role === "admin" || role === "super_admin";

    return (
      <View
        style={[styles.row, isDeleted && { opacity: 0.5 }]}
        testID={`team-${item.id}`}
      >
        <View
          style={[
            styles.avatar,
            { backgroundColor: isItemAdmin ? "#E0F2FE" : "#DCFCE7" },
          ]}
        >
          <Text
            style={[
              styles.avatarText,
              { color: isItemAdmin ? "#0369A1" : "#16A34A" },
            ]}
          >
            {item.name?.charAt(0)?.toUpperCase() || "?"}
          </Text>
        </View>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Text style={styles.name}>{item.name || item.email}</Text>
            {isSelf && <Text style={styles.youTag}>(you)</Text>}
            {isDeleted && (
              <View style={styles.deletedBadge} testID={`team-row-deleted-badge-${item.id}`}>
                <Text style={styles.deletedText}>DELETED</Text>
              </View>
            )}
          </View>
          <Text style={styles.sub}>{item.email}</Text>
          {TECH_ROLES.includes((item.role || "").toLowerCase()) && (() => {
            const cur = (item.department || "").toString();
            const isKnown = cur === "" || DEPT_OPTIONS.some((o) => o.value === cur);
            const legacyTarget = LEGACY_DEPT_MAP[cur.toLowerCase()] || null;
            if (!isKnown && legacyTarget) {
              // Legacy stored value — surface it AND make the pill a
              // one-tap Normalize (admin only; techs see the badge
              // read-only via canEditDeptRow gate below).
              return (
                <Pressable
                  onPress={() => canEditDeptRow(item) && doDeptChange(item, legacyTarget)}
                  testID={`team-row-dept-legacy-${item.id}`}
                >
                  <View style={styles.deptChipLegacy}>
                    <Ionicons name="alert-circle-outline" size={11} color="#92400E" />
                    <Text style={styles.deptChipLegacyText}>
                      Legacy: {cur}{canEditDeptRow(item) ? "  · tap to fix" : ""}
                    </Text>
                  </View>
                </Pressable>
              );
            }
            return (
              <View style={styles.deptChip} testID={`team-row-dept-chip-${item.id}`}>
                <Ionicons name="pricetag-outline" size={11} color={colors.muted} />
                <Text style={styles.deptChipText}>
                  {DEPT_LABEL[cur || "null"] || "Unassigned"}
                </Text>
              </View>
            );
          })()}
        </View>
        <View style={styles.rolePill}>
          <Ionicons
            name={isItemAdmin ? "briefcase" : "construct"}
            size={12}
            color={colors.brand}
          />
          <Text style={styles.roleText}>
            {role === "super_admin" ? "Super Admin" : role === "admin" ? "Admin" : "Tech"}
          </Text>
        </View>
        {anyKebab && (
            <Pressable
              style={styles.kebabBtn}
              onPress={() => setActionTarget(item)}
              testID={`team-row-kebab-${item.id}`}
              hitSlop={8}
            >
              <Ionicons name="ellipsis-vertical" size={18} color={colors.onSurfaceSecondary} />
            </Pressable>
        )}
      </View>
    );
  };

  return (
    <View style={styles.root}>
      <Header title="Team" back subtitle="Staff & field crew" />

      {/* Super admin: Show Deleted toggle */}
      {isSuperAdmin && (
        <View style={styles.toggleBar} testID="team-show-deleted-toggle">
          <Text style={styles.toggleLabel}>Show deleted</Text>
          <Switch value={showDeleted} onValueChange={setShowDeleted} />
        </View>
      )}

      {loading ? (
        <Loading testID="team-loading" />
      ) : items.length === 0 ? (
        <EmptyState icon="people-outline" title="No team members" testID="team-empty" />
      ) : (
        <FlatList
          testID="team-list"
          data={items}
          keyExtractor={(i) => i.id}
          contentContainerStyle={{ padding: spacing.lg, paddingBottom: 100 }}
          refreshControl={
            <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />
          }
          renderItem={renderRow}
        />
      )}

      {/* Action Sheet (kebab replacement) */}
      <ActionSheetModal
        target={actionTarget}
        canReset={actionTarget ? canResetRow(actionTarget) : false}
        canDelete={actionTarget ? canDeleteRow(actionTarget) : false}
        canUndelete={actionTarget ? canUndeleteRow(actionTarget) : false}
        canEditDept={actionTarget ? canEditDeptRow(actionTarget) : false}
        currentDeptLabel={
          actionTarget
            ? (DEPT_LABEL[actionTarget.department || "null"] || "Unassigned")
            : ""
        }
        onClose={() => setActionTarget(null)}
        onReset={(t) => { setActionTarget(null); setResetTarget(t); }}
        onDelete={(t) => { setActionTarget(null); setDeleteTarget(t); }}
        onUndelete={(t) => { setActionTarget(null); doUndelete(t); }}
        onEditDept={(t) => { setActionTarget(null); setDeptTarget(t); }}
      />

      {/* Feb-2026 · Multi-category tech assignment — dept picker */}
      <DepartmentPickerModal
        target={deptTarget}
        onClose={() => setDeptTarget(null)}
        onPick={(t, v) => doDeptChange(t, v)}
      />

      {/* Reset Password Modal */}
      <ResetPasswordModal
        target={resetTarget}
        onClose={() => setResetTarget(null)}
        onDone={(msg) => { setResetTarget(null); showToast(msg); load(); }}
      />

      {/* Delete Confirm Modal */}
      <DeleteTeamModal
        target={deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onDone={(name) => {
          setDeleteTarget(null);
          showToast(`${name} has been removed from the team.`);
          load();
        }}
      />
    </View>
  );
}

/* ---------- Action Sheet Modal (kebab replacement) ---------- */
function ActionSheetModal({
  target, canReset, canDelete, canUndelete, canEditDept, currentDeptLabel,
  onClose, onReset, onDelete, onUndelete, onEditDept,
}: {
  target: any; canReset: boolean; canDelete: boolean; canUndelete: boolean;
  canEditDept: boolean; currentDeptLabel: string;
  onClose: () => void; onReset: (t: any) => void; onDelete: (t: any) => void;
  onUndelete: (t: any) => void; onEditDept: (t: any) => void;
}) {
  if (!target) return null;
  return (
    <Modal visible={!!target} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={m.overlay} onPress={onClose}>
        <View style={m.actionSheet} testID={`team-action-sheet-${target.id}`}>
          <View style={m.sheetHandle} />
          <Text style={m.sheetName}>{target.name || target.email}</Text>
          {canEditDept && (
            <Pressable
              style={m.sheetItem}
              onPress={() => onEditDept(target)}
              testID={`team-row-edit-dept-btn-${target.id}`}
            >
              <Ionicons name="pricetag-outline" size={18} color={colors.onSurface} />
              <View style={{ flex: 1 }}>
                <Text style={m.sheetLabel}>Set department</Text>
                <Text style={m.sheetSubLabel}>Current: {currentDeptLabel}</Text>
              </View>
            </Pressable>
          )}
          {canReset && (
            <Pressable style={m.sheetItem} onPress={() => onReset(target)} testID={`team-row-reset-btn-${target.id}`}>
              <Ionicons name="key-outline" size={18} color={colors.onSurface} />
              <Text style={m.sheetLabel}>Reset password</Text>
            </Pressable>
          )}
          {canDelete && (
            <Pressable style={m.sheetItem} onPress={() => onDelete(target)} testID={`team-row-delete-btn-${target.id}`}>
              <Ionicons name="trash-outline" size={18} color="#B91C1C" />
              <Text style={[m.sheetLabel, { color: "#B91C1C" }]}>Delete team member</Text>
            </Pressable>
          )}
          {canUndelete && (
            <Pressable style={m.sheetItem} onPress={() => onUndelete(target)} testID={`team-row-undelete-btn-${target.id}`}>
              <Ionicons name="arrow-undo-outline" size={18} color="#166534" />
              <Text style={[m.sheetLabel, { color: "#166534" }]}>Undelete</Text>
            </Pressable>
          )}
          <Pressable style={[m.sheetItem, { marginTop: spacing.sm }]} onPress={onClose} testID="team-action-cancel">
            <Text style={[m.sheetLabel, { color: colors.muted, textAlign: "center", flex: 1 }]}>Cancel</Text>
          </Pressable>
        </View>
      </Pressable>
    </Modal>
  );
}

/* ---------- Department Picker Modal (Feb-2026 multi-category) ---------- */
function DepartmentPickerModal({
  target, onClose, onPick,
}: {
  target: any;
  onClose: () => void;
  onPick: (t: any, value: string) => void;
}) {
  if (!target) return null;
  const current = target.department || "";
  return (
    <Modal visible={!!target} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={m.overlay} onPress={onClose}>
        <View style={m.actionSheet} testID={`team-dept-picker-${target.id}`}>
          <View style={m.sheetHandle} />
          <Text style={m.sheetName}>Set department</Text>
          <Text style={[m.sheetSubLabel, { textAlign: "center", marginBottom: spacing.md }]}>
            {target.name || target.email}
          </Text>
          {DEPT_OPTIONS.map((o) => {
            const isCurrent = current === o.value;
            return (
              <Pressable
                key={o.value || "unassigned"}
                style={m.sheetItem}
                onPress={() => onPick(target, o.value)}
                testID={`team-dept-picker-option-${o.value || "unassigned"}-${target.id}`}
              >
                <Ionicons
                  name={isCurrent ? "checkmark-circle" : "ellipse-outline"}
                  size={18}
                  color={isCurrent ? colors.brand : colors.muted}
                />
                <Text
                  style={[
                    m.sheetLabel,
                    isCurrent && { color: colors.brand, fontFamily: font.bold },
                  ]}
                >
                  {o.label}
                </Text>
              </Pressable>
            );
          })}
          <Pressable
            style={[m.sheetItem, { marginTop: spacing.sm }]}
            onPress={onClose}
            testID="team-dept-picker-cancel"
          >
            <Text style={[m.sheetLabel, { color: colors.muted, textAlign: "center", flex: 1 }]}>
              Cancel
            </Text>
          </Pressable>
        </View>
      </Pressable>
    </Modal>
  );
}

/* ---------- Reset Password Modal ---------- */
function ResetPasswordModal({
  target, onClose, onDone,
}: { target: any; onClose: () => void; onDone: (msg: string) => void }) {
  const [mode, setMode] = useState<"custom" | "auto">("custom");
  const [pw, setPw] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tempPw, setTempPw] = useState<string | null>(null);

  React.useEffect(() => {
    if (target) { setMode("custom"); setPw(""); setShowPw(false); setBusy(false); setTempPw(null); }
  }, [target]);

  if (!target) return null;

  const customValid = pw.length >= 8 && /[A-Za-z]/.test(pw) && /\d/.test(pw);

  const submit = async () => {
    if (mode === "custom" && !customValid) {
      Alert.alert("Invalid password", "Must be at least 8 chars with 1 letter and 1 digit.");
      return;
    }
    setBusy(true);
    try {
      const body = mode === "auto" ? { auto_generate: true } : { new_password: pw };
      const r = await api.post(`/users/${target.id}/reset-password`, body);
      if (mode === "auto" && r?.temporary_password) {
        setTempPw(r.temporary_password);
      } else {
        onDone(`Password reset for ${target.name || target.email}`);
      }
    } catch (e: any) {
      Alert.alert("Reset failed", e.message || "Unknown error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible={!!target} transparent animationType="fade" onRequestClose={onClose}>
      <View style={[m.overlay, m.overlayCenter]}>
        <View style={m.sheet} testID="team-reset-modal">
          <Text style={m.title}>Reset password</Text>
          <Text style={m.sub}>For {target.name || target.email}</Text>

          {tempPw ? (
            <View style={{ marginTop: spacing.md }}>
              <Text style={m.tempLabel}>Temporary password (copy now — shown only once):</Text>
              <View style={m.tempRow}>
                <Text style={m.tempPw} selectable testID="team-reset-temp-pw">{tempPw}</Text>
              </View>
              <View style={{ marginTop: spacing.lg }}>
                <PrimaryButton title="Done" onPress={() => onDone(`Password reset for ${target.name || target.email}`)} testID="team-reset-done" />
              </View>
            </View>
          ) : (
            <>
              {/* Mode selector */}
              <View style={m.modeRow}>
                <Pressable
                  style={[m.modeBtn, mode === "custom" && m.modeBtnActive]}
                  onPress={() => setMode("custom")}
                  testID="team-reset-mode-custom"
                >
                  <Text style={[m.modeText, mode === "custom" && m.modeTextActive]}>Custom</Text>
                </Pressable>
                <Pressable
                  style={[m.modeBtn, mode === "auto" && m.modeBtnActive]}
                  onPress={() => setMode("auto")}
                  testID="team-reset-mode-auto"
                >
                  <Text style={[m.modeText, mode === "auto" && m.modeTextActive]}>Auto-generate</Text>
                </Pressable>
              </View>

              {mode === "custom" && (
                <View style={{ marginTop: spacing.md }}>
                  <Text style={m.label}>New password</Text>
                  <View style={m.inputRow}>
                    <AppTextInput
                      style={m.input}
                      value={pw}
                      onChangeText={setPw}
                      secureTextEntry={!showPw}
                      placeholder="Min 8 chars, 1 letter, 1 digit"
                      placeholderTextColor={colors.muted}
                      testID="team-reset-pw-input"
                    />
                    <Pressable onPress={() => setShowPw((v) => !v)} hitSlop={8}>
                      <Ionicons name={showPw ? "eye-off-outline" : "eye-outline"} size={18} color={colors.muted} />
                    </Pressable>
                  </View>
                </View>
              )}

              {mode === "auto" && (
                <Text style={m.autoHint}>
                  A strong temporary password will be generated. You&apos;ll see it once to share with the team member.
                </Text>
              )}

              <View style={m.actions}>
                <Pressable style={m.cancelBtn} onPress={onClose} disabled={busy} testID="team-reset-cancel">
                  <Text style={m.cancelText}>Cancel</Text>
                </Pressable>
                <View style={{ flex: 1 }}>
                  <PrimaryButton
                    title={busy ? "Resetting..." : "Reset Password"}
                    loading={busy}
                    onPress={submit}
                    disabled={busy || (mode === "custom" && !customValid)}
                    testID="team-reset-submit"
                  />
                </View>
              </View>
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

/* ---------- Delete Team Member Modal ---------- */
function DeleteTeamModal({
  target, onClose, onDone,
}: { target: any; onClose: () => void; onDone: (name: string) => void }) {
  const [busy, setBusy] = useState(false);

  if (!target) return null;

  const submit = async () => {
    setBusy(true);
    try {
      await api.post(`/users/${target.id}/soft-delete`, {});
      onDone(target.name || target.email || target.id);
    } catch (e: any) {
      Alert.alert("Delete failed", e.message || "Unknown error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal visible={!!target} transparent animationType="fade" onRequestClose={onClose}>
      <View style={[m.overlay, m.overlayCenter]}>
        <View style={m.sheet} testID="team-delete-modal">
          <Text style={m.title}>Delete team member?</Text>
          <Text style={m.deleteBody}>
            Are you sure you want to delete{" "}
            <Text style={{ fontFamily: font.bold }}>{target.name || target.email}</Text>?
          </Text>
          <Text style={m.deleteHint}>
            They will be hidden from all rosters and their active jobs will be reassigned to
            {'"'}Unassigned{'"'}. This can be undone by a super admin.
          </Text>
          <View style={m.actions}>
            <Pressable style={m.cancelBtn} onPress={onClose} disabled={busy} testID="team-delete-cancel">
              <Text style={m.cancelText}>Cancel</Text>
            </Pressable>
            <Pressable
              style={[m.dangerBtn, busy && { opacity: 0.6 }]}
              onPress={submit}
              disabled={busy}
              testID="team-delete-submit"
            >
              {busy ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <>
                  <Ionicons name="trash-outline" size={14} color="#fff" />
                  <Text style={m.dangerText}>Delete</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

/* ---------- Styles ---------- */
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surfaceSecondary },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surface, borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  avatar: { width: 46, height: 46, borderRadius: 23, alignItems: "center", justifyContent: "center" },
  avatarText: { fontFamily: font.bold, fontSize: fontSize.lg },
  name: { fontFamily: font.semibold, fontSize: fontSize.lg, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  youTag: { fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted },
  deletedBadge: {
    backgroundColor: "#FEE2E2", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 4,
  },
  deletedText: { fontFamily: font.bold, fontSize: 9, color: "#991B1B", letterSpacing: 0.5 },
  rolePill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brandTertiary, paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: radius.pill,
  },
  roleText: { fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.brand },
  kebabBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
  },
  // Feb-2026 · Multi-category tech assignment — compact department
  // chip under the email on each tech row, so admins can see the
  // current setting at a glance without opening the action sheet.
  deptChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    marginTop: 4, alignSelf: "flex-start",
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.pill,
    paddingHorizontal: 8, paddingVertical: 2,
  },
  deptChipText: {
    fontFamily: font.semibold, fontSize: 11, color: colors.onSurfaceSecondary,
  },
  deptChipLegacy: {
    flexDirection: "row", alignItems: "center", gap: 4,
    marginTop: 4, alignSelf: "flex-start",
    backgroundColor: "#FEF3C7",  // amber-100 — matches the web warningBg default
    borderWidth: 1, borderColor: "#F59E0B",
    borderRadius: radius.pill,
    paddingHorizontal: 8, paddingVertical: 2,
  },
  deptChipLegacyText: {
    fontFamily: font.semibold, fontSize: 11, color: "#92400E",
  },
  toggleBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.sm,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  toggleLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
});

const m = StyleSheet.create({
  overlay: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.5)",
    justifyContent: "flex-end",
  },
  actionSheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    paddingHorizontal: spacing.lg, paddingBottom: 40, paddingTop: spacing.md,
  },
  sheetHandle: {
    width: 36, height: 4, borderRadius: 2, backgroundColor: colors.border,
    alignSelf: "center", marginBottom: spacing.md,
  },
  sheetName: {
    fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
    marginBottom: spacing.md, textAlign: "center",
  },
  sheetItem: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    paddingVertical: 14, borderTopWidth: 1, borderTopColor: colors.border,
  },
  sheetLabel: { fontFamily: font.medium, fontSize: fontSize.base, color: colors.onSurface },
  sheetSubLabel: {
    fontFamily: font.regular, fontSize: fontSize.xs, color: colors.muted, marginTop: 2,
  },
  overlayCenter: {
    justifyContent: "center", paddingHorizontal: spacing.lg,
  },
  sheet: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.xl,
  },
  title: { fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface },
  sub: { fontFamily: font.regular, fontSize: fontSize.base, color: colors.muted, marginTop: 4 },
  label: {
    fontFamily: font.semibold, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: 4,
  },
  inputRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.md, backgroundColor: colors.surfaceSecondary, height: 48,
  },
  input: {
    flex: 1, fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface,
  },
  modeRow: {
    flexDirection: "row", gap: spacing.sm, marginTop: spacing.md,
  },
  modeBtn: {
    flex: 1, alignItems: "center", paddingVertical: 10,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  modeBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  modeText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.onSurfaceSecondary },
  modeTextActive: { color: "#FFFFFF" },
  autoHint: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted,
    marginTop: spacing.md, lineHeight: 18,
  },
  tempLabel: {
    fontFamily: font.medium, fontSize: fontSize.sm, color: colors.onSurfaceSecondary, marginBottom: spacing.sm,
  },
  tempRow: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
  },
  tempPw: {
    fontFamily: font.bold, fontSize: fontSize.xl, color: colors.onSurface,
    letterSpacing: 1, textAlign: "center",
  },
  actions: {
    flexDirection: "row", gap: spacing.sm, marginTop: spacing.xl, alignItems: "center",
  },
  cancelBtn: {
    paddingHorizontal: spacing.lg, paddingVertical: 12,
  },
  cancelText: { fontFamily: font.semibold, fontSize: fontSize.base, color: colors.muted },
  deleteBody: {
    fontFamily: font.regular, fontSize: fontSize.base, color: colors.onSurface, marginTop: spacing.md,
  },
  deleteHint: {
    fontFamily: font.regular, fontSize: fontSize.sm, color: colors.muted, marginTop: spacing.sm, lineHeight: 18,
  },
  dangerBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: spacing.xs, backgroundColor: "#DC2626",
    paddingVertical: 12, borderRadius: radius.md,
  },
  dangerText: { fontFamily: font.bold, fontSize: fontSize.base, color: "#FFFFFF" },
});
