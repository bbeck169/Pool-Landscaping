/**
 * Feb 2026 · Phase 2 Custom Trigger Builder · top-level.
 *
 * Owns the ``trigger`` state ({ logic, conditions[] }) that the
 * parent SequenceEditor persists via PATCH /marketing/sequences/{sid}.
 * Renders:
 *   * AND / OR toggle for how conditions combine.
 *   * List of ConditionRow instances.
 *   * "Add condition" button.
 *   * LiveMatchPreview panel on the right.
 *
 * Persists an unsaved draft under
 * ``localStorage['sequence.<id>.draftTrigger']`` so an accidental
 * refresh doesn't lose work.
 */
import React, { useEffect, useMemo, useState } from "react";
import { Plus, Zap } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";

import { ConditionRow } from "./ConditionRow";
import { LiveMatchPreview } from "./LiveMatchPreview";
import {
  loadDraft, saveDraft, validateTrigger,
} from "./helpers";


const EMPTY_CONDITION = () => ({
  event: "",
  delay: { mode: "immediate" },
  filters: {},
});


export function TriggerBuilder({
  sequenceId,
  initialTrigger,
  onChange,
  onValidityChange,
}) {
  // Boot state: prefer any localStorage draft over the persisted
  // trigger so an accidental refresh keeps unsaved work.
  const [trigger, setTrigger] = useState(() => {
    const draft = loadDraft(sequenceId);
    if (draft && Array.isArray(draft.conditions)) return draft;
    if (initialTrigger && Array.isArray(initialTrigger.conditions)) {
      return {
        logic: (initialTrigger.logic || "AND").toUpperCase(),
        conditions: initialTrigger.conditions.map((c) => ({
          event: c.event || "",
          delay: c.delay || { mode: "immediate" },
          filters: c.filters || {},
        })),
      };
    }
    return { logic: "AND", conditions: [] };
  });

  const [catalog, setCatalog] = useState([]);
  const [technicians, setTechnicians] = useState([]);
  const [crews, setCrews] = useState([]);
  const [autoSwitchMap, setAutoSwitchMap] = useState({}); // per-row toast info

  // ─── Catalog + sidebar fetches ────────────────────────────────
  useEffect(() => {
    api.get("/marketing/sequences/event-catalog")
      .then((r) => setCatalog(r.events || []))
      .catch(() => setCatalog([]));
    api.get("/users?role=technician")
      .then((r) => {
        const rows = r.users || r || [];
        setTechnicians(rows.map((u) => ({
          id: u.technician_id || u.id,
          name: u.name || u.email || u.id,
        })));
      })
      .catch(() => setTechnicians([]));
    api.get("/crews")
      .then((r) => setCrews(r.crews || r || []))
      .catch(() => setCrews([]));
  }, []);

  // ─── Push state up + persist draft ────────────────────────────
  useEffect(() => {
    onChange?.(trigger);
    saveDraft(sequenceId, trigger);
  }, [trigger, sequenceId, onChange]);

  // ─── Client-side validity ─────────────────────────────────────
  const validity = useMemo(
    () => validateTrigger(trigger, catalog),
    [trigger, catalog],
  );
  useEffect(() => {
    onValidityChange?.(validity);
  }, [validity, onValidityChange]);

  // ─── Mutators ──────────────────────────────────────────────────
  const setLogic = (logic) => setTrigger((t) => ({ ...t, logic }));

  const addCondition = () =>
    setTrigger((t) => ({ ...t, conditions: [...(t.conditions || []), EMPTY_CONDITION()] }));

  const updateCondition = (i, next) => {
    setTrigger((t) => ({
      ...t,
      conditions: t.conditions.map((c, j) => (j === i ? next : c)),
    }));
  };

  const removeCondition = (i) => {
    setTrigger((t) => ({
      ...t,
      conditions: t.conditions.filter((_, j) => j !== i),
    }));
    setAutoSwitchMap((m) => {
      const next = { ...m };
      delete next[i];
      return next;
    });
  };

  // ─── Guard: switching event -> if new event blocks "before",
  //     auto-switch delay mode to "after" and surface a tiny hint.
  const handleConditionChange = (i, next) => {
    const prev = trigger.conditions[i];
    const eventChanged = prev && prev.event !== next.event;
    const meta = catalog.find((e) => e.id === next.event);
    if (eventChanged && meta && !meta.allow_negative_offset
        && (next.delay || {}).mode === "before") {
      next = {
        ...next,
        delay: { mode: "after", value: 1, unit: "day" },
      };
      setAutoSwitchMap((m) => ({
        ...m,
        [i]: `Auto-switched to "after" — ${meta.label} has no scheduled time to anchor a "before" delay.`,
      }));
      setTimeout(() => {
        setAutoSwitchMap((m) => {
          const nxt = { ...m };
          delete nxt[i];
          return nxt;
        });
      }, 5000);
    }
    updateCondition(i, next);
  };

  // ─── Render ───────────────────────────────────────────────────
  return (
    <div className="space-y-3" data-testid="trigger-builder-wrap">
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-bold uppercase tracking-wider" style={{ color: colors.muted }}>
          Custom trigger
        </div>
        <div className="flex items-center gap-1" data-testid="trigger-logic-toggle">
          <span className="text-[10px] mr-1" style={{ color: colors.muted }}>MATCH</span>
          <LogicChip active={trigger.logic === "AND"} onClick={() => setLogic("AND")} label="ALL (AND)" testId="trigger-logic-and" />
          <LogicChip active={trigger.logic === "OR"} onClick={() => setLogic("OR")} label="ANY (OR)" testId="trigger-logic-or" />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-3" style={{ minHeight: 260 }}>
        {/* Left: condition list */}
        <div className="lg:col-span-3 space-y-2" data-testid="trigger-conditions-list">
          {(trigger.conditions || []).length === 0 ? (
            <div
              className="text-sm rounded-xl p-4 text-center"
              style={{
                color: colors.muted,
                backgroundColor: colors.surface,
                border: `1px dashed ${colors.border}`,
              }}
              data-testid="trigger-conditions-empty"
            >
              <Zap size={16} className="mx-auto mb-1" style={{ color: colors.accent.sky[500] }} />
              No conditions yet — add one to start matching customers.
            </div>
          ) : (
            trigger.conditions.map((c, i) => (
              <ConditionRow
                key={i}
                index={i}
                condition={c}
                catalog={catalog}
                technicians={technicians}
                crews={crews}
                onChange={(next) => handleConditionChange(i, next)}
                onRemove={() => removeCondition(i)}
                autoSwitchedInfo={autoSwitchMap[i] || null}
                testIdPrefix="trigger"
              />
            ))
          )}
          <button
            type="button"
            onClick={addCondition}
            className="w-full flex items-center justify-center gap-1 px-3 py-2 rounded-xl text-xs font-semibold"
            style={{
              backgroundColor: colors.surface,
              color: colors.brand,
              border: `1px dashed ${colors.brand}`,
            }}
            data-testid="trigger-add-condition"
          >
            <Plus size={12} /> Add condition
          </button>

          {!validity.ok && trigger.conditions.length > 0 ? (
            <div
              className="text-xs p-2 rounded-lg"
              style={{
                color: colors.error,
                backgroundColor: colors.surface,
                border: `1px solid ${colors.error}`,
              }}
              data-testid="trigger-validation-errors"
            >
              <ul className="list-disc pl-4 space-y-0.5">
                {validity.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>

        {/* Right: live preview */}
        <div className="lg:col-span-2">
          <LiveMatchPreview
            sequenceId={sequenceId}
            trigger={trigger}
            enabled={validity.ok}
            testIdPrefix="trigger-preview"
          />
        </div>
      </div>
    </div>
  );
}


function LogicChip({ active, onClick, label, testId }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="px-2 py-1 rounded-lg text-[11px] font-bold"
      style={{
        backgroundColor: active ? colors.brand : colors.surfaceSecondary,
        color: active ? colors.onBrandPrimary : colors.onSurface,
        border: `1px solid ${active ? colors.brand : colors.border}`,
      }}
      data-testid={testId}
    >
      {label}
    </button>
  );
}
