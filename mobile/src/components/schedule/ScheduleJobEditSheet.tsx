/**
 * Feb-2026 · Mobile Schedule inline-edit sheet.
 *
 * Bottom sheet counterpart to the web ``ScheduleJobEditModal``.
 * Same PUT / DELETE contract, same admin-gated exposure — reuses
 * the mobile ``Sheet`` primitive (no fork of the ``/job/new`` form,
 * which is create-only + carries create-only concepts). Keeps the
 * field set intentionally focused on what admins reach for from
 * the schedule: title, scheduled date, service type, technician,
 * notes, status.
 */
import React, { useEffect, useState } from "react";
import { View, Text, TextInput, Pressable, ActivityIndicator } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api";
import { colors, spacing, radius, font, fontSize } from "@/src/theme";
import { Sheet, PrimaryButton } from "@/src/components/ui";

const SERVICE_TYPES = [
  "Pool Cleaning", "Repair", "Landscaping", "Inspection",
  "Installation", "Weekly Pool", "Chemical Balance", "Filter Clean",
];
const STATUSES = [
  { value: "scheduled",   label: "Scheduled" },
  { value: "in_progress", label: "In progress" },
  { value: "completed",   label: "Completed" },
  { value: "cancelled",   label: "Cancelled" },
];

type Job = {
  id: string;
  title?: string;
  service_type?: string;
  scheduled_date?: string;
  technician_id?: string;
  notes?: string;
  status?: string;
  customer_name?: string;
};

type Props = {
  open: boolean;
  job: Job | null;
  onClose: () => void;
  onSaved: (patched: Job) => void;
  onDeleted: (jid: string) => void;
};

export default function ScheduleJobEditSheet({ open, job, onClose, onSaved, onDeleted }: Props) {
  const [form, setForm] = useState<Job>(job || { id: "" });
  const [techs, setTechs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (!open || !job) return;
    setForm({ ...job });
    setErr(""); setConfirmDelete(false);
    (api as any).get("/technicians")
      .then((rows: any) => setTechs(Array.isArray(rows) ? rows : []))
      .catch(() => setTechs([]));
  }, [open, job?.id]);

  if (!open || !job) return null;

  const setField = (k: keyof Job) => (v: any) =>
    setForm((prev) => ({ ...prev, [k]: v }));

  const onSave = async () => {
    setBusy(true); setErr("");
    try {
      const patch: any = {};
      for (const k of ["title","service_type","scheduled_date",
                       "technician_id","notes","status"] as const) {
        if ((form[k] || "") !== (job[k] || "")) patch[k] = form[k];
      }
      if (Object.keys(patch).length === 0) {
        onClose(); setBusy(false); return;
      }
      const updated = await (api as any).put(`/jobs/${job.id}`, patch);
      onSaved({ ...job, ...patch, ...(updated || {}) });
    } catch (e: any) {
      setErr(String(e?.message || e || "Save failed"));
    } finally { setBusy(false); }
  };

  const onDelete = async () => {
    setBusy(true); setErr("");
    try {
      await (api as any).del(`/jobs/${job.id}`);
      onDeleted(job.id);
    } catch (e: any) {
      setErr(String(e?.message || e || "Delete failed"));
      setBusy(false);
    }
  };

  return (
    <Sheet visible={open} onClose={onClose} title="Edit job" testID="schedule-job-edit-sheet">
      <View style={{ gap: spacing.md }}>
        <View>
          <Text style={label}>Title</Text>
          <TextInput
            value={form.title || ""}
            onChangeText={setField("title")}
            style={input}
            testID="schedule-job-edit-title"
          />
        </View>

        <View>
          <Text style={label}>Service type</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
            {SERVICE_TYPES.map((s) => (
              <Pressable
                key={s}
                onPress={() => setField("service_type")(s)}
                style={[chip, form.service_type === s && chipActive]}
                testID={`schedule-job-edit-service-${s.replace(/\s+/g, "-")}`}
              >
                <Text style={form.service_type === s ? chipTextActive : chipText}>{s}</Text>
              </Pressable>
            ))}
          </View>
        </View>

        <View>
          <Text style={label}>Scheduled date</Text>
          <TextInput
            value={form.scheduled_date || ""}
            onChangeText={setField("scheduled_date")}
            placeholder="YYYY-MM-DD"
            placeholderTextColor={colors.muted}
            style={input}
            testID="schedule-job-edit-date"
          />
        </View>

        <View>
          <Text style={label}>Technician</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
            <Pressable
              onPress={() => setField("technician_id")("")}
              style={[chip, !form.technician_id && chipActive]}
              testID="schedule-job-edit-tech-unassigned"
            >
              <Text style={!form.technician_id ? chipTextActive : chipText}>Unassigned</Text>
            </Pressable>
            {techs.map((t: any) => {
              // Feb-2026 · Assignable-user widen — same role suffix
              // as the web modal so admins stand out in the picker.
              const r = String(t.role || "").toLowerCase();
              const suffix =
                r === "super_admin" ? " (Super Admin)"
                  : r === "admin"    ? " (Admin)"
                  : r === "manager"  ? " (Manager)"
                  : "";
              return (
                <Pressable
                  key={t.id}
                  onPress={() => setField("technician_id")(t.id)}
                  style={[chip, form.technician_id === t.id && chipActive]}
                  testID={`schedule-job-edit-tech-${t.id}`}
                >
                  <Text style={form.technician_id === t.id ? chipTextActive : chipText}>
                    {t.name}{suffix}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>

        <View>
          <Text style={label}>Status</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.xs }}>
            {STATUSES.map((s) => (
              <Pressable
                key={s.value}
                onPress={() => setField("status")(s.value)}
                style={[chip, form.status === s.value && chipActive]}
                testID={`schedule-job-edit-status-${s.value}`}
              >
                <Text style={form.status === s.value ? chipTextActive : chipText}>{s.label}</Text>
              </Pressable>
            ))}
          </View>
        </View>

        <View>
          <Text style={label}>Notes</Text>
          <TextInput
            value={form.notes || ""}
            onChangeText={setField("notes")}
            multiline
            numberOfLines={4}
            style={[input, { minHeight: 84, textAlignVertical: "top" }]}
            testID="schedule-job-edit-notes"
          />
        </View>

        {err ? (
          <Text style={{ color: colors.error, fontFamily: font.semibold }}
                testID="schedule-job-edit-error">
            {err}
          </Text>
        ) : null}

        {confirmDelete ? (
          <View style={{ padding: spacing.sm, borderRadius: radius.md,
                          backgroundColor: colors.surfaceSecondary }}
                testID="schedule-job-edit-confirm-delete">
            <Text style={{ color: colors.onSurface, fontFamily: font.semibold }}>
              Delete this job? This cannot be undone.
            </Text>
            <View style={{ flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm }}>
              <Pressable
                onPress={() => setConfirmDelete(false)}
                style={btnGhost}
                disabled={busy}
              >
                <Text style={btnGhostText}>Keep job</Text>
              </Pressable>
              <Pressable
                onPress={onDelete}
                style={btnDanger}
                disabled={busy}
                testID="schedule-job-edit-confirm-delete-btn"
              >
                <Text style={btnDangerText}>Yes, delete</Text>
              </Pressable>
            </View>
          </View>
        ) : null}

        <View style={{ flexDirection: "row", justifyContent: "space-between",
                        gap: spacing.sm, paddingTop: spacing.sm }}>
          <Pressable
            onPress={() => setConfirmDelete(true)}
            style={btnDanger}
            disabled={busy}
            testID="schedule-job-edit-delete"
          >
            <Ionicons name="trash-outline" size={14} color="#fff" />
            <Text style={btnDangerText}>Delete</Text>
          </Pressable>
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <Pressable onPress={onClose} style={btnGhost} disabled={busy}>
              <Text style={btnGhostText}>Cancel</Text>
            </Pressable>
            <PrimaryButton
              title={busy ? "Saving…" : "Save changes"}
              onPress={onSave}
              disabled={busy}
              testID="schedule-job-edit-save"
            />
          </View>
        </View>
      </View>
    </Sheet>
  );
}

// ── Inline styles (small; keeps sheet self-contained). ────────────────
const label = { fontFamily: font.semibold, fontSize: fontSize.xs,
                textTransform: "uppercase" as const, color: colors.muted,
                marginBottom: spacing.xs };
const input = { backgroundColor: colors.surface, color: colors.onSurface,
                borderWidth: 1, borderColor: colors.border,
                borderRadius: radius.md, paddingHorizontal: spacing.md,
                paddingVertical: spacing.sm, fontSize: fontSize.base,
                fontFamily: font.regular };
const chip = { paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
                borderRadius: 999, borderWidth: 1, borderColor: colors.border,
                backgroundColor: colors.surfaceSecondary };
const chipActive = { backgroundColor: colors.brand, borderColor: colors.brand };
const chipText = { fontFamily: font.semibold, fontSize: fontSize.sm,
                    color: colors.onSurface };
const chipTextActive = { ...chipText, color: "#fff" };
const btnGhost = { paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
                    borderRadius: radius.md, backgroundColor: colors.surfaceSecondary };
const btnGhostText = { fontFamily: font.semibold, fontSize: fontSize.base,
                        color: colors.onSurface };
const btnDanger = { flexDirection: "row" as const, alignItems: "center" as const,
                    gap: spacing.xs, paddingHorizontal: spacing.md,
                    paddingVertical: spacing.sm, borderRadius: radius.md,
                    backgroundColor: colors.error };
const btnDangerText = { fontFamily: font.semibold, fontSize: fontSize.base,
                        color: "#fff" };
