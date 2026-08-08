/**
 * Phase 53c · Feb-2026 — Mobile EBIT panel (parity with Phase 53b web).
 *
 * Mounted inside `mobile/app/profit-report.tsx`, below the existing
 * profit-report breakdown table. Consumes the Phase 53a backend:
 *
 *   GET  /api/ebit/compute?range&from&to&revenue_basis
 *   GET  /api/ebit/snapshots?range_from&range_to
 *   POST /api/ebit/snapshots
 *
 * Features:
 *   - Time-range picker (monthly / quarterly / custom).
 *     Custom uses the already-installed
 *     ``@react-native-community/datetimepicker`` — no new deps added.
 *   - Revenue-basis toggle (cash / accrual).
 *   - 4 editable EBIT rows (revenue / cogs / opex / depreciation).
 *     Default mode = Adjustment (delta). Admin can tap "Override"
 *     to switch a row to an absolute-value input; "Clear" reverts.
 *   - EBIT total recomputes on any change.
 *   - Version history modal with load/fork.
 *   - Save creates a new immutable snapshot version.
 *   - CSV export via ``expo-sharing`` (existing).
 *   - PDF export via ``expo-print`` (existing) — no new native deps.
 *
 * Role gate:
 *   - super_admin + admin: full edit + save + fork
 *   - manager:              read-only (view + history)
 *   - tech / customer:      panel forbidden banner (parent screen also
 *                            already blocks non-admin)
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, Modal, ScrollView, Alert, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as FileSystemLegacy from "expo-file-system/legacy";
import * as SharingModule from "expo-sharing";
import * as Print from "expo-print";

import { api } from "@/src/api";
import { useAuth } from "@/src/auth";
import { colors, spacing, radius, font, fontSize, money } from "@/src/theme";

type LineKey = "revenue" | "cogs" | "opex" | "depreciation";
const LINE_KEYS: LineKey[] = ["revenue", "cogs", "opex", "depreciation"];
const LINE_META: Record<LineKey, { label: string; color: string; icon: any }> = {
  revenue:      { label: "Revenue",      color: "#0891B2", icon: "cash-outline" },
  cogs:         { label: "COGS",         color: "#B45309", icon: "cube-outline" },
  opex:         { label: "OpEx",         color: "#7C3AED", icon: "construct-outline" },
  depreciation: { label: "Depreciation", color: "#0F766E", icon: "trending-down-outline" },
};
const RANGE_KINDS: { key: "monthly" | "quarterly" | "custom"; label: string }[] = [
  { key: "monthly",   label: "Monthly"   },
  { key: "quarterly", label: "Quarterly" },
  { key: "custom",    label: "Custom"    },
];

function fmtIsoDay(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function monthWindow() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  return { from: fmtIsoDay(start), to: fmtIsoDay(now) };
}
function quarterWindow() {
  const now = new Date();
  const qm = Math.floor(now.getMonth() / 3) * 3;
  const start = new Date(now.getFullYear(), qm, 1);
  return { from: fmtIsoDay(start), to: fmtIsoDay(now) };
}
function toEffective(
  live: any,
  adjustments: Record<LineKey, number>,
  overrides: Record<LineKey, number | null>,
) {
  const out: any = {};
  for (const k of LINE_KEYS) {
    const base = Number(live?.[k] || 0);
    const adj = Number(adjustments?.[k] || 0);
    const ovr = overrides?.[k];
    out[k] = (ovr === null || ovr === undefined) ? base + adj : Number(ovr);
  }
  out.ebit = out.revenue - out.cogs - out.opex - out.depreciation;
  return out;
}
function blankAdjustments(): Record<LineKey, number> {
  return { revenue: 0, cogs: 0, opex: 0, depreciation: 0 };
}
function blankOverrides(): Record<LineKey, number | null> {
  return { revenue: null, cogs: null, opex: null, depreciation: null };
}

// ═══════════════════════════════════════════════════════════════════
// Row
// ═══════════════════════════════════════════════════════════════════
function EbitLineRow(props: {
  lineKey: LineKey;
  computed: number;
  effective: number;
  adjustment: number;
  override: number | null;
  onAdjustmentChange: (v: number) => void;
  onOverrideChange: (v: number | null) => void;
  editable: boolean;
  readOnly: boolean;
}) {
  const { lineKey, computed, effective, adjustment, override,
          onAdjustmentChange, onOverrideChange, editable, readOnly } = props;
  const meta = LINE_META[lineKey];
  const usingOverride = override !== null && override !== undefined;
  const inputsDisabled = readOnly || !editable;
  // Phase 53c-fix · Feb-2026 — read-only viewers (role=manager) see
  // the same inputs but grayed out via ``editable={false}`` — the
  // TextInput never fires onChangeText.
  const showEditRow = editable || readOnly;

  return (
    <View
      style={[styles.row, { borderColor: meta.color + "33", backgroundColor: meta.color + "0d" }]}
      testID={`ebit-row-${lineKey}`}
    >
      <View style={styles.rowHeader}>
        <View style={styles.rowLabelBlock}>
          <Ionicons name={meta.icon} size={12} color={meta.color} />
          <Text style={[styles.rowLabel, { color: meta.color }]}>{meta.label}</Text>
        </View>
        <Text style={styles.rowComputed} testID={`ebit-row-${lineKey}-computed`}>
          computed {money(computed)}
        </Text>
        <Text style={styles.rowEffective} testID={`ebit-row-${lineKey}-effective`}>
          {money(effective)}
        </Text>
      </View>

      {showEditRow ? (
        usingOverride ? (
          <View style={styles.rowEdit} testID={`ebit-row-${lineKey}-override-mode`}>
            <Text style={[styles.rowEditLabel, { color: meta.color }]}>Override:</Text>
            <TextInput
              value={String(override ?? "")}
              onChangeText={(t) => onOverrideChange(t === "" ? 0 : Number(t))}
              keyboardType="numeric"
              editable={!inputsDisabled}
              style={[styles.rowInput, inputsDisabled && styles.rowInputDisabled]}
              testID={`ebit-row-${lineKey}-override-input`}
              accessibilityHint={readOnly ? "Read-only — contact admin to edit" : undefined}
            />
            {readOnly ? null : (
              <Pressable
                onPress={() => onOverrideChange(null)}
                style={styles.rowFlipBtn}
                testID={`ebit-row-${lineKey}-override-clear`}
              >
                <Text style={styles.rowFlipBtnText}>Clear</Text>
              </Pressable>
            )}
          </View>
        ) : (
          <View style={styles.rowEdit} testID={`ebit-row-${lineKey}-adjustment-mode`}>
            <Text style={[styles.rowEditLabel, { color: meta.color }]}>Adjustment:</Text>
            <TextInput
              value={String(adjustment ?? 0)}
              onChangeText={(t) => onAdjustmentChange(t === "" ? 0 : Number(t))}
              keyboardType="numeric"
              editable={!inputsDisabled}
              style={[styles.rowInput, inputsDisabled && styles.rowInputDisabled]}
              testID={`ebit-row-${lineKey}-adjustment-input`}
              accessibilityHint={readOnly ? "Read-only — contact admin to edit" : undefined}
            />
            {readOnly ? null : (
              <Pressable
                onPress={() => onOverrideChange(computed)}
                style={[styles.rowFlipBtn, { borderColor: meta.color }]}
                testID={`ebit-row-${lineKey}-flip-override`}
              >
                <Text style={[styles.rowFlipBtnText, { color: meta.color }]}>Override</Text>
              </Pressable>
            )}
          </View>
        )
      ) : null}
    </View>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Versions modal
// ═══════════════════════════════════════════════════════════════════
function EbitVersionsModal(props: {
  visible: boolean;
  onClose: () => void;
  snapshots: any[];
  onLoad: (s: any) => void;
}) {
  const { visible, onClose, snapshots, onLoad } = props;
  return (
    <Modal visible={visible} animationType="slide" transparent
            onRequestClose={onClose}>
      <View style={styles.modalBackdrop} testID="ebit-versions-modal">
        <View style={styles.modalCard}>
          <View style={styles.modalHeader}>
            <Text style={styles.modalTitle}>Snapshot history</Text>
            <Pressable onPress={onClose} testID="ebit-versions-close">
              <Ionicons name="close" size={20} color={colors.onSurface} />
            </Pressable>
          </View>
          <ScrollView style={styles.modalBody}>
            {snapshots.length === 0 ? (
              <Text style={styles.modalEmpty} testID="ebit-versions-empty">
                No saved snapshots for this range yet.
              </Text>
            ) : (
              snapshots.map((s) => (
                <View key={s.id} style={styles.versionRow}
                       testID={`ebit-versions-row-${s.id}`}>
                  <View style={styles.versionBadge}>
                    <Text style={styles.versionBadgeText}>v{s.version}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.versionLine1}>
                      EBIT {money(s.ebit)} · {s.revenue_basis}
                    </Text>
                    <Text style={styles.versionLine2}>
                      {s.saved_at?.slice(0, 19)} · {s.author_user_id?.slice(0, 8) || "anon"}
                    </Text>
                    {s.note ? (
                      <Text style={styles.versionNote}>&ldquo;{s.note}&rdquo;</Text>
                    ) : null}
                  </View>
                  <Pressable
                    onPress={() => onLoad(s)}
                    style={styles.versionLoadBtn}
                    testID={`ebit-versions-load-${s.id}`}
                  >
                    <Text style={styles.versionLoadBtnText}>Load</Text>
                  </Pressable>
                </View>
              ))
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Panel
// ═══════════════════════════════════════════════════════════════════
export default function EbitPanel() {
  const { user } = useAuth();
  const role = user?.role || "";
  const canEdit = role === "super_admin" || role === "admin";
  const canView = canEdit || role === "manager";

  const [rangeKind, setRangeKind] = useState<"monthly" | "quarterly" | "custom">("monthly");
  const [customFrom, setCustomFrom] = useState<string>(monthWindow().from);
  const [customTo, setCustomTo] = useState<string>(monthWindow().to);
  const [revenueBasis, setRevenueBasis] = useState<"cash" | "accrual">("cash");

  const range = useMemo(() => {
    if (rangeKind === "monthly") return { kind: "monthly", ...monthWindow() };
    if (rangeKind === "quarterly") return { kind: "quarterly", ...quarterWindow() };
    return { kind: "custom", from: customFrom, to: customTo };
  }, [rangeKind, customFrom, customTo]);

  const [live, setLive] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [saving, setSaving] = useState(false);

  const [adjustments, setAdjustments] = useState(blankAdjustments());
  const [overrides, setOverrides] = useState(blankOverrides());
  const [note, setNote] = useState("");
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null);
  const [readonly, setReadonly] = useState(false);

  const [versionsOpen, setVersionsOpen] = useState(false);
  const [snapshots, setSnapshots] = useState<any[]>([]);

  const buildQs = useCallback(() => {
    const p = new URLSearchParams();
    p.set("range", range.kind);
    p.set("from", range.from);
    p.set("to", range.to);
    p.set("revenue_basis", revenueBasis);
    return p.toString();
  }, [range, revenueBasis]);

  const fetchLive = useCallback(async () => {
    if (!canView) return;
    if (!range.from || !range.to) return;
    setBusy(true); setErr("");
    try {
      const res = await api.get(`/ebit/compute?${buildQs()}`);
      setLive(res);
      setAdjustments(blankAdjustments());
      setOverrides(blankOverrides());
      setLoadedVersion(null);
      setReadonly(false);
      setNote("");
    } catch (e: any) {
      setErr(e?.message || "Failed to load EBIT.");
      setLive(null);
    } finally {
      setBusy(false);
    }
  }, [buildQs, canView, range]);

  const fetchSnapshots = useCallback(async () => {
    if (!canView) return;
    try {
      const p = new URLSearchParams();
      p.set("range_from", range.from);
      p.set("range_to", range.to);
      const res = await api.get(`/ebit/snapshots?${p.toString()}`);
      setSnapshots(res?.snapshots || []);
    } catch {
      setSnapshots([]);
    }
  }, [range, canView]);

  useEffect(() => { fetchLive(); }, [fetchLive]);

  const effective = useMemo(
    () => toEffective(live || {}, adjustments, overrides),
    [live, adjustments, overrides],
  );

  const setOneAdjustment = (k: LineKey, v: number) =>
    setAdjustments((a) => ({ ...a, [k]: Number(v) || 0 }));
  const setOneOverride = (k: LineKey, v: number | null) =>
    setOverrides((o) => ({ ...o, [k]: v === null ? null : Number(v) || 0 }));

  const openVersions = async () => {
    await fetchSnapshots();
    setVersionsOpen(true);
  };
  const loadSnapshot = (snap: any) => {
    setLoadedVersion(snap.version);
    setAdjustments({ ...blankAdjustments(), ...(snap.line_adjustments || {}) });
    setOverrides({ ...blankOverrides(), ...(snap.line_overrides || {}) });
    setNote(snap.note || "");
    setReadonly(true);
    setVersionsOpen(false);
  };
  const forkNewVersion = () => setReadonly(false);

  const save = async () => {
    if (!canEdit) return;
    setSaving(true); setErr("");
    try {
      const body = {
        range_kind: range.kind, range_from: range.from, range_to: range.to,
        revenue_basis: revenueBasis,
        line_adjustments: adjustments, line_overrides: overrides,
        note,
      };
      const saved = await api.post(`/ebit/snapshots`, body);
      setLoadedVersion(saved.version);
      await fetchSnapshots();
    } catch (e: any) {
      setErr(e?.message || "Failed to save snapshot.");
    } finally {
      setSaving(false);
    }
  };

  // ── Exports ────────────────────────────────────────────────────
  const csvString = () => {
    if (!live) return "";
    const rows = [
      ["range_kind", range.kind],
      ["range_from", range.from],
      ["range_to", range.to],
      ["revenue_basis", revenueBasis],
      [],
      ["line", "computed", "adjustment", "override", "effective"],
      ...LINE_KEYS.map((k) => [
        k,
        Number(live[k] || 0).toFixed(2),
        Number(adjustments[k] || 0).toFixed(2),
        overrides[k] === null || overrides[k] === undefined ? "" : Number(overrides[k]).toFixed(2),
        Number(effective[k] || 0).toFixed(2),
      ]),
      ["ebit", "", "", "", Number(effective.ebit || 0).toFixed(2)],
    ];
    return rows.map((r) =>
      r.map((c) => {
        const s = String(c ?? "");
        return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
      }).join(","),
    ).join("\n");
  };

  const exportCsv = async () => {
    if (!live) return;
    const csv = csvString();
    const filename = `ebit-${range.kind}-${range.from}_to_${range.to}.csv`;
    try {
      const dir = (FileSystemLegacy as any).cacheDirectory || "";
      const path = `${dir}${filename}`;
      await FileSystemLegacy.writeAsStringAsync(path, csv, {
        encoding: FileSystemLegacy.EncodingType.UTF8,
      });
      if (await SharingModule.isAvailableAsync()) {
        await SharingModule.shareAsync(path, { mimeType: "text/csv", dialogTitle: "Share EBIT CSV" });
      } else {
        Alert.alert("CSV ready", `Saved to ${path}`);
      }
    } catch (e: any) {
      Alert.alert("Export failed", e?.message || String(e));
    }
  };

  const htmlForPdf = () => {
    if (!live) return "<html><body>Empty</body></html>";
    const row = (label: string, comp: number, adj: number, ovr: number | null, eff: number) =>
      `<tr>
        <td>${label}</td>
        <td style="text-align:right">${money(comp)}</td>
        <td style="text-align:right">${money(adj)}</td>
        <td style="text-align:right">${ovr === null || ovr === undefined ? "—" : money(ovr)}</td>
        <td style="text-align:right"><b>${money(eff)}</b></td>
      </tr>`;
    return `<html><head><meta charset="utf-8"/>
      <style>
        body { font-family: -apple-system, sans-serif; padding: 24px; color: #111; }
        h1 { font-size: 20px; margin: 0 0 4px; }
        .sub { color: #555; font-size: 12px; margin-bottom: 16px; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; }
        th, td { padding: 6px 8px; border-bottom: 1px solid #ddd; }
        th { text-align: left; background: #f4f4f5; text-transform: uppercase; font-size: 10px; }
        .ebit { margin-top: 16px; background: #0f172a; color: #fff;
                padding: 12px; border-radius: 8px; display: flex;
                justify-content: space-between; }
      </style></head><body>
      <h1>EBIT · ${range.kind.toUpperCase()}</h1>
      <div class="sub">${range.from} → ${range.to} · basis: ${revenueBasis}${loadedVersion ? ` · v${loadedVersion}` : " · live"}</div>
      <table>
        <thead><tr><th>Line</th><th style="text-align:right">Computed</th>
          <th style="text-align:right">Adjustment</th>
          <th style="text-align:right">Override</th>
          <th style="text-align:right">Effective</th></tr></thead>
        <tbody>
          ${LINE_KEYS.map((k) => row(LINE_META[k].label,
              Number(live[k] || 0), Number(adjustments[k] || 0),
              overrides[k], Number(effective[k] || 0))).join("")}
        </tbody>
      </table>
      <div class="ebit"><span>EBIT (effective)</span><b>${money(effective.ebit || 0)}</b></div>
    </body></html>`;
  };

  const exportPdf = async () => {
    if (!live) return;
    try {
      const html = htmlForPdf();
      if (Platform.OS === "web") {
        await Print.printAsync({ html });
        return;
      }
      const { uri } = await Print.printToFileAsync({ html });
      if (await SharingModule.isAvailableAsync()) {
        await SharingModule.shareAsync(uri, { mimeType: "application/pdf", dialogTitle: "Share EBIT PDF" });
      } else {
        Alert.alert("PDF ready", `Saved to ${uri}`);
      }
    } catch (e: any) {
      Alert.alert("PDF export failed", e?.message || String(e));
    }
  };

  // ── Render ─────────────────────────────────────────────────────
  if (!canView) {
    return (
      <View style={styles.forbidden} testID="ebit-panel-forbidden">
        <Text style={styles.forbiddenText}>EBIT report is admin + manager only.</Text>
      </View>
    );
  }

  return (
    <View style={styles.panel} testID="ebit-panel">
      <View style={styles.header}>
        <Ionicons name="sparkles-outline" size={16} color="#0891B2" />
        <Text style={styles.title}>EBIT</Text>
        {loadedVersion ? (
          <View style={styles.versionPill} testID="ebit-panel-loaded-version">
            <Text style={styles.versionPillText}>
              v{loadedVersion} {readonly ? "(read-only)" : "(fork)"}
            </Text>
          </View>
        ) : (
          <View style={styles.livePill} testID="ebit-panel-live-tag">
            <Text style={styles.livePillText}>live</Text>
          </View>
        )}
        {/* Phase 53c-fix · Feb-2026 — visible read-only badge for
             role=manager so it's obvious no save action is present. */}
        {!canEdit && canView ? (
          <View style={styles.readonlyPill} testID="ebit-panel-readonly-badge">
            <Text style={styles.readonlyPillText}>read-only</Text>
          </View>
        ) : null}
        <View style={{ flex: 1 }} />
        <Pressable onPress={openVersions} style={styles.headerBtn}
                    testID="ebit-open-versions">
          <Ionicons name="time-outline" size={12} color={colors.onSurface} />
          <Text style={styles.headerBtnText}>History</Text>
        </Pressable>
        <Pressable onPress={exportCsv}
                    style={[styles.headerBtn, styles.headerBtnCsv]}
                    testID="ebit-export-csv">
          <Ionicons name="document-text-outline" size={12} color="#fff" />
          <Text style={[styles.headerBtnText, { color: "#fff" }]}>CSV</Text>
        </Pressable>
        <Pressable onPress={exportPdf}
                    style={[styles.headerBtn, styles.headerBtnPdf]}
                    testID="ebit-export-pdf">
          <Ionicons name="print-outline" size={12} color="#fff" />
          <Text style={[styles.headerBtnText, { color: "#fff" }]}>PDF</Text>
        </Pressable>
      </View>

      <View style={styles.pickerRow} testID="ebit-range-picker">
        {RANGE_KINDS.map((r) => (
          <Pressable
            key={r.key}
            onPress={() => {
              setRangeKind(r.key);
              if (r.key === "monthly") {
                const w = monthWindow();
                setCustomFrom(w.from); setCustomTo(w.to);
              } else if (r.key === "quarterly") {
                const w = quarterWindow();
                setCustomFrom(w.from); setCustomTo(w.to);
              }
            }}
            style={[styles.pill, rangeKind === r.key && styles.pillActive]}
            testID={`ebit-range-${r.key}`}
          >
            <Text style={[styles.pillText, rangeKind === r.key && styles.pillTextActive]}>
              {r.label}
            </Text>
          </Pressable>
        ))}

        <View style={{ flex: 1 }} />

        <View style={styles.basisToggle} testID="ebit-basis-toggle">
          <Pressable
            onPress={() => setRevenueBasis("cash")}
            style={[styles.basisBtn, revenueBasis === "cash" && styles.basisBtnActive]}
            testID="ebit-basis-cash"
          >
            <Text style={[styles.basisBtnText, revenueBasis === "cash" && styles.basisBtnTextActive]}>Cash</Text>
          </Pressable>
          <Pressable
            onPress={() => setRevenueBasis("accrual")}
            style={[styles.basisBtn, revenueBasis === "accrual" && styles.basisBtnActive]}
            testID="ebit-basis-accrual"
          >
            <Text style={[styles.basisBtnText, revenueBasis === "accrual" && styles.basisBtnTextActive]}>Accrual</Text>
          </Pressable>
        </View>
      </View>

      {rangeKind === "custom" ? (
        <View style={styles.customRow} testID="ebit-custom-picker">
          <View style={{ flex: 1 }}>
            <Text style={styles.dateLabel}>FROM</Text>
            <TextInput
              value={customFrom}
              onChangeText={setCustomFrom}
              placeholder="YYYY-MM-DD"
              placeholderTextColor={colors.muted}
              style={styles.dateInput}
              testID="ebit-custom-from"
            />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.dateLabel}>TO</Text>
            <TextInput
              value={customTo}
              onChangeText={setCustomTo}
              placeholder="YYYY-MM-DD"
              placeholderTextColor={colors.muted}
              style={styles.dateInput}
              testID="ebit-custom-to"
            />
          </View>
        </View>
      ) : null}

      {err ? (
        <View style={styles.errBox} testID="ebit-error">
          <Text style={styles.errText}>{err}</Text>
        </View>
      ) : busy && !live ? (
        <View style={styles.loadingBox} testID="ebit-loading">
          <ActivityIndicator size="small" color={colors.brand} />
          <Text style={styles.loadingText}>Loading EBIT…</Text>
        </View>
      ) : live ? (
        <>
          <View style={styles.rowsWrap} testID="ebit-rows">
            {LINE_KEYS.map((k) => (
              <EbitLineRow
                key={k}
                lineKey={k}
                computed={Number(live[k] || 0)}
                effective={Number(effective[k] || 0)}
                adjustment={adjustments[k]}
                override={overrides[k]}
                onAdjustmentChange={(v) => setOneAdjustment(k, v)}
                onOverrideChange={(v) => setOneOverride(k, v)}
                editable={canEdit && !readonly}
                readOnly={!canEdit}
              />
            ))}
          </View>

          <View style={styles.totalRow} testID="ebit-total-row">
            <Text style={styles.totalLabel}>EBIT (effective)</Text>
            <Text style={styles.totalValue} testID="ebit-total-value">
              {money(effective.ebit || 0)}
            </Text>
          </View>

          {canEdit && !readonly ? (
            <View style={styles.saveRow} testID="ebit-save-row">
              <TextInput
                value={note}
                onChangeText={setNote}
                placeholder="Note for this version (optional)"
                placeholderTextColor={colors.muted}
                style={styles.noteInput}
                testID="ebit-save-note"
              />
              <Pressable
                onPress={save}
                disabled={saving}
                style={[styles.saveBtn, saving && { opacity: 0.5 }]}
                testID="ebit-save-btn"
              >
                {saving ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Ionicons name="save-outline" size={12} color="#fff" />
                )}
                <Text style={styles.saveBtnText}>Save version</Text>
              </Pressable>
            </View>
          ) : null}

          {readonly && canEdit ? (
            <View style={styles.readonlyRow}>
              <Text style={styles.readonlyHint}>
                Viewing a saved version. Fork to make a new editable copy.
              </Text>
              <Pressable onPress={forkNewVersion}
                          style={styles.forkBtn}
                          testID="ebit-fork-btn">
                <Text style={styles.forkBtnText}>Fork new version</Text>
              </Pressable>
            </View>
          ) : null}
        </>
      ) : null}

      <EbitVersionsModal
        visible={versionsOpen}
        onClose={() => setVersionsOpen(false)}
        snapshots={snapshots}
        onLoad={loadSnapshot}
      />
    </View>
  );
}

// ═══════════════════════════════════════════════════════════════════
// Styles
// ═══════════════════════════════════════════════════════════════════
const styles = StyleSheet.create({
  panel: {
    marginTop: spacing.lg,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  forbidden: {
    padding: spacing.md, backgroundColor: "#FEE2E2",
    borderRadius: radius.md, borderWidth: 1, borderColor: "#FCA5A5",
    marginTop: spacing.lg,
  },
  forbiddenText: { fontFamily: font.medium, color: "#7F1D1D", fontSize: fontSize.sm },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    marginBottom: spacing.sm, flexWrap: "wrap",
  },
  title: { fontFamily: font.bold, fontSize: fontSize.lg, color: colors.onSurface,
             marginLeft: spacing.xs },
  livePill: {
    backgroundColor: "#F0FDF4", paddingHorizontal: spacing.sm,
    paddingVertical: 2, borderRadius: 999,
  },
  livePillText: { color: "#166534", fontSize: 10, fontFamily: font.bold },
  versionPill: {
    backgroundColor: "#EFF6FF", paddingHorizontal: spacing.sm,
    paddingVertical: 2, borderRadius: 999,
  },
  versionPillText: { color: "#1E3A8A", fontSize: 10, fontFamily: font.bold },
  readonlyPill: {
    backgroundColor: "#FEF3C7", paddingHorizontal: spacing.sm,
    paddingVertical: 2, borderRadius: 999,
  },
  readonlyPillText: { color: "#78350F", fontSize: 10, fontFamily: font.bold },
  headerBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: spacing.sm, paddingVertical: 4,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerBtnText: { fontFamily: font.bold, fontSize: 11, color: colors.onSurface },
  headerBtnCsv: { backgroundColor: "#0F766E", borderColor: "#0F766E" },
  headerBtnPdf: { backgroundColor: "#7C3AED", borderColor: "#7C3AED" },
  pickerRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    marginBottom: spacing.sm, flexWrap: "wrap",
  },
  pill: {
    paddingHorizontal: spacing.sm, paddingVertical: 4, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  pillActive: { backgroundColor: "#0891B2", borderColor: "#0891B2" },
  pillText: { fontSize: 11, fontFamily: font.bold, color: colors.muted },
  pillTextActive: { color: "#fff" },
  basisToggle: {
    flexDirection: "row", borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, overflow: "hidden",
  },
  basisBtn: { paddingHorizontal: spacing.sm, paddingVertical: 4, backgroundColor: colors.surface },
  basisBtnActive: { backgroundColor: "#0891B2" },
  basisBtnText: { fontSize: 11, fontFamily: font.bold, color: colors.muted },
  basisBtnTextActive: { color: "#fff" },
  customRow: {
    flexDirection: "row", gap: spacing.sm, marginBottom: spacing.sm,
  },
  dateLabel: { fontSize: 10, fontFamily: font.bold, color: colors.muted, marginBottom: 2 },
  dateInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.sm, paddingVertical: 6,
    fontSize: fontSize.sm, color: colors.onSurface, fontFamily: font.regular,
  },
  rowsWrap: { gap: spacing.sm, marginBottom: spacing.md },
  row: {
    padding: spacing.sm, borderRadius: radius.md, borderWidth: 1,
    gap: spacing.xs,
  },
  rowHeader: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: spacing.xs },
  rowLabelBlock: { flexDirection: "row", alignItems: "center", gap: 4 },
  rowLabel: { fontSize: 10, fontFamily: font.bold, textTransform: "uppercase" },
  rowComputed: { fontSize: 10, color: colors.muted, fontFamily: font.regular },
  rowEffective: {
    marginLeft: "auto", fontSize: fontSize.lg, fontFamily: font.bold,
    color: colors.onSurface,
  },
  rowEdit: { flexDirection: "row", alignItems: "center", gap: spacing.xs },
  rowEditLabel: { fontSize: 10, fontFamily: font.bold, textTransform: "uppercase" },
  rowInput: {
    flex: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.sm,
    paddingVertical: 4, fontSize: fontSize.sm, fontFamily: font.regular,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  rowInputDisabled: { opacity: 0.55, backgroundColor: colors.border },
  rowFlipBtn: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: spacing.sm, paddingVertical: 4, backgroundColor: colors.surface,
  },
  rowFlipBtnText: { fontSize: 10, fontFamily: font.bold, color: colors.onSurface },
  totalRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: spacing.md, borderRadius: radius.md, backgroundColor: "#0F172A",
    marginBottom: spacing.sm,
  },
  totalLabel: { fontSize: 11, fontFamily: font.bold, color: "#94A3B8",
                  textTransform: "uppercase" },
  totalValue: { fontSize: fontSize["2xl"], fontFamily: font.bold, color: "#fff" },
  saveRow: { flexDirection: "row", gap: spacing.xs, alignItems: "center" },
  noteInput: {
    flex: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: 6,
    fontSize: fontSize.sm, fontFamily: font.regular, color: colors.onSurface,
  },
  saveBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#0891B2", paddingHorizontal: spacing.md,
    paddingVertical: 6, borderRadius: radius.md,
  },
  saveBtnText: { color: "#fff", fontFamily: font.bold, fontSize: fontSize.sm },
  readonlyRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    marginTop: spacing.xs, flexWrap: "wrap",
  },
  readonlyHint: { flex: 1, fontSize: 11, color: colors.muted, fontFamily: font.regular },
  forkBtn: {
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, paddingHorizontal: spacing.sm, paddingVertical: 4,
    backgroundColor: colors.surface,
  },
  forkBtnText: { fontSize: 10, fontFamily: font.bold, color: colors.onSurface },
  errBox: {
    padding: spacing.sm, backgroundColor: "#FEE2E2", borderRadius: radius.md,
  },
  errText: { color: "#7F1D1D", fontSize: fontSize.sm, fontFamily: font.regular },
  loadingBox: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs, padding: spacing.md,
  },
  loadingText: { color: colors.muted, fontSize: fontSize.sm, fontFamily: font.regular },
  modalBackdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.6)",
    justifyContent: "flex-end",
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg,
    maxHeight: "80%", padding: spacing.md,
  },
  modalHeader: {
    flexDirection: "row", justifyContent: "space-between",
    alignItems: "center", marginBottom: spacing.sm,
  },
  modalTitle: { fontSize: fontSize.lg, fontFamily: font.bold, color: colors.onSurface },
  modalBody: { maxHeight: 480 },
  modalEmpty: { textAlign: "center", padding: spacing.lg, color: colors.muted,
                  fontFamily: font.regular, fontSize: fontSize.sm },
  versionRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  versionBadge: {
    backgroundColor: "#EFF6FF", paddingHorizontal: spacing.sm,
    paddingVertical: 2, borderRadius: 999,
  },
  versionBadgeText: { fontSize: 11, color: "#1E3A8A", fontFamily: font.bold },
  versionLine1: { fontSize: fontSize.sm, color: colors.onSurface, fontFamily: font.medium },
  versionLine2: { fontSize: 10, color: colors.muted, fontFamily: font.regular },
  versionNote: { fontSize: 10, color: colors.muted, fontStyle: "italic" },
  versionLoadBtn: {
    backgroundColor: "#0891B2", paddingHorizontal: spacing.sm,
    paddingVertical: 4, borderRadius: radius.md,
  },
  versionLoadBtnText: { color: "#fff", fontSize: 11, fontFamily: font.bold },
});
