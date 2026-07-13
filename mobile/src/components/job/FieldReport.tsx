import React, { useState } from "react";
import { View, Text, ScrollView, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { colors } from "@/src/theme";
import { api } from "@/src/api";
import { cacheJob, queueMutation } from "@/src/offline";
import { Sheet } from "@/src/components/ui";
import { styles, READING_RANGES, chemOptions, readingOptions } from "./styles";
import ChecklistSection from "./ChecklistSection";
import ChemicalReadings from "./ChemicalReadings";
import ChemicalsAdded from "./ChemicalsAdded";
import NotesSection from "./NotesSection";

export default function FieldReport({ job, online, onSaved, readOnly }: { job: any; online: boolean; onSaved: (j: any) => void; readOnly: boolean }) {
  const isPool = job.job_type === "pool";
  const [checklist, setChecklist] = useState<any[]>(job.checklist || []);
  const [readings, setReadings] = useState<Record<string, string>>(() => {
    const r: Record<string, string> = {};
    (job.reading_fields || []).forEach((f: any) => {
      const v = job.chemical_readings?.[f.key];
      r[f.key] = v === undefined || v === null ? "" : String(v);
    });
    return r;
  });
  const [chemicals, setChemicals] = useState<any[]>(job.chemicals_added || []);
  const [chemAmounts, setChemAmounts] = useState<Record<string, string>>(() => {
    const m: Record<string, string> = {};
    (job.chemicals_added || []).forEach((c: any) => { m[c.name] = String(c.amount ?? ""); });
    return m;
  });
  const [picker, setPicker] = useState<{ title: string; unit?: string; options: string[]; current: string; onSelect: (v: string) => void } | null>(null);
  const [saving, setSaving] = useState(false);

  const save = async (partial: any) => {
    if (!online) {
      // Offline: apply optimistically, cache, and queue for sync on reconnect.
      const merged = { ...job, ...partial };
      onSaved(merged);
      cacheJob(merged);
      await queueMutation(`/jobs/${job.id}/field-report`, partial);
      return;
    }
    setSaving(true);
    try {
      const updated = await api.put(`/jobs/${job.id}/field-report`, partial);
      onSaved(updated);
      cacheJob(updated);
    } catch {
      const merged = { ...job, ...partial };
      onSaved(merged);
      cacheJob(merged);
      await queueMutation(`/jobs/${job.id}/field-report`, partial);
    }
    finally { setSaving(false); }
  };

  const toggleItem = (idx: number) => {
    if (readOnly) return;
    const next = checklist.map((c, i) => (i === idx ? { ...c, done: !c.done } : c));
    setChecklist(next);
    save({ checklist: next });
  };

  const saveChemicals = (amounts: Record<string, string>) => {
    const list = (job.chemical_catalog || [])
      .map((item: any) => {
        const amt = (amounts[item.name] || "").trim();
        const n = parseFloat(amt);
        if (!amt || isNaN(n) || n <= 0) return null;
        return { id: item.name, name: item.name, amount: amt, unit: item.unit || "" };
      })
      .filter(Boolean);
    setChemicals(list);
    save({ chemicals_added: list });
  };

  const openChemPicker = (item: any) => setPicker({
    title: item.name,
    unit: item.unit,
    options: chemOptions(item.unit),
    current: chemAmounts[item.name] || "",
    onSelect: (v) => {
      setPicker(null);
      setChemAmounts((m) => { const next = { ...m, [item.name]: v }; saveChemicals(next); return next; });
    },
  });

  const setReadingValue = (f: any, v: string) => {
    setReadings((r) => {
      const next = { ...r, [f.key]: v };
      const payload: Record<string, number> = {};
      Object.entries(next).forEach(([k, val]) => { const n = parseFloat(val); if (!isNaN(n)) payload[k] = n; });
      save({ chemical_readings: payload });
      return next;
    });
  };

  const idealValue = (f: any): string | null => {
    const c = READING_RANGES[f.key];
    if (!c || f.min === undefined || f.min === null || f.max === undefined || f.max === null) return null;
    const mid = (f.min + f.max) / 2;
    const snapped = c.min + Math.round((mid - c.min) / c.step) * c.step;
    const clamped = Math.min(Math.max(snapped, c.min), c.max);
    return c.step < 1 ? clamped.toFixed(1) : String(Math.round(clamped));
  };

  const openReadingPicker = (f: any) => setPicker({
    title: f.label,
    unit: f.unit,
    options: readingOptions(f.key),
    current: readings[f.key] || "",
    onSelect: (v) => {
      setPicker(null);
      setReadingValue(f, v);
    },
  });

  const setAllIdeal = () => {
    setReadings((r) => {
      const next = { ...r };
      (job.reading_fields || []).forEach((f: any) => {
        const idv = idealValue(f);
        if (idv) next[f.key] = idv;
      });
      const payload: Record<string, number> = {};
      Object.entries(next).forEach(([k, val]) => { const n = parseFloat(val); if (!isNaN(n)) payload[k] = n; });
      save({ chemical_readings: payload });
      return next;
    });
  };

  const done = checklist.filter((c) => c.done).length;
  const report = job.reading_report || [];
  // Customer report: only surface completed work & recorded data.
  const checklistToShow = readOnly ? checklist.filter((c) => c.done) : checklist;
  const showChecklist = !readOnly || checklistToShow.length > 0;
  const showReadings = !readOnly || report.length > 0;
  const showChemicals = !readOnly || chemicals.length > 0;

  return (
    <View style={styles.reportWrap}>
      {showChecklist ? (
        <ChecklistSection
          isPool={isPool}
          readOnly={readOnly}
          checklist={checklist}
          checklistToShow={checklistToShow}
          done={done}
          toggleItem={toggleItem}
        />
      ) : null}

      {isPool ? (
        <>
          {showReadings ? (
            <ChemicalReadings
              readOnly={readOnly}
              report={report}
              readingFields={job.reading_fields || []}
              readings={readings}
              idealValue={idealValue}
              setReadingValue={setReadingValue}
              openReadingPicker={openReadingPicker}
              setAllIdeal={setAllIdeal}
            />
          ) : null}

          {showChemicals ? (
            <ChemicalsAdded
              readOnly={readOnly}
              chemicals={chemicals}
              chemicalCatalog={job.chemical_catalog || []}
              chemAmounts={chemAmounts}
              openChemPicker={openChemPicker}
            />
          ) : null}
        </>
      ) : null}

      <NotesSection job={job} readOnly={readOnly} save={save} />

      {readOnly ? null : !online ? <Text style={styles.offlineHint}>Offline — changes save when you reconnect.</Text> : saving ? <Text style={styles.savingHint}>Saving…</Text> : null}

      <Sheet visible={!!picker} onClose={() => setPicker(null)} title={picker?.title || ""} testID="chem-amount-sheet">
        <ScrollView style={{ maxHeight: 380 }} showsVerticalScrollIndicator={false}>
          <Pressable style={styles.amtOpt} onPress={() => picker?.onSelect("")} testID="amt-opt-none">
            <Text style={styles.amtOptText}>None</Text>
            {picker && !picker.current ? <Ionicons name="checkmark" size={20} color={colors.brand} /> : null}
          </Pressable>
          {picker?.options.map((v) => (
            <Pressable key={v} style={styles.amtOpt} onPress={() => picker.onSelect(v)} testID={`amt-opt-${v}`}>
              <Text style={styles.amtOptText}>{v}{picker.unit ? ` ${picker.unit}` : ""}</Text>
              {picker.current && parseFloat(picker.current) === parseFloat(v) ? <Ionicons name="checkmark" size={20} color={colors.brand} /> : null}
            </Pressable>
          ))}
        </ScrollView>
      </Sheet>
    </View>
  );
}
