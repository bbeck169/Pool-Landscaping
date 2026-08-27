/**
 * Feb 2026 · Phase 2 Custom Trigger Builder · FilterBuilder.
 *
 * All 9 filter dimensions from the Phase-1 evaluator, each rendered
 * in its own collapsible row. Empty dims are omitted from the saved
 * payload by :func:`stripEmptyFilters` — this component just tracks
 * the working state.
 */
import React, { useState } from "react";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import { colors } from "@/theme";


const SEGMENT_OPTIONS = [
  { id: "pool",      label: "Pool" },
  { id: "landscape", label: "Landscape" },
  { id: "both",      label: "Pool + Landscape" },
];

const WORK_CLASS_OPTIONS = [
  { id: "service", label: "Service" },
  { id: "repair",  label: "Repair" },
];


/** Toggle chip used by multi-select filter rows. */
function Chip({ label, active, onToggle, testId }) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className="px-2.5 py-1 rounded-full text-xs font-semibold"
      style={{
        backgroundColor: active ? colors.brandTertiary : colors.surfaceSecondary,
        color: active ? colors.onBrandTertiary : colors.onSurface,
        border: `1px solid ${active ? colors.brand : colors.border}`,
      }}
      data-testid={testId}
    >
      {label}
    </button>
  );
}


/** Free-text multi-input rendered as pills. Enter or comma adds. */
function PillInput({ values, onChange, placeholder, testId }) {
  const [draft, setDraft] = useState("");
  const commit = () => {
    const bits = draft.split(",").map((s) => s.trim()).filter(Boolean);
    if (bits.length === 0) return;
    const merged = Array.from(new Set([...(values || []), ...bits]));
    onChange(merged);
    setDraft("");
  };
  return (
    <div
      className="flex items-center flex-wrap gap-1 px-2 py-1.5 rounded-lg"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={testId}
    >
      {(values || []).map((v, i) => (
        <span
          key={`${v}-${i}`}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs"
          style={{
            backgroundColor: colors.accent.sky[100],
            color: colors.accent.sky[700],
          }}
          data-testid={`${testId}-pill-${i}`}
        >
          {v}
          <button
            type="button"
            onClick={() => onChange(values.filter((_, j) => j !== i))}
            data-testid={`${testId}-pill-${i}-remove`}
          >
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          }
        }}
        placeholder={placeholder}
        className="flex-1 min-w-[80px] text-sm outline-none"
        style={{ backgroundColor: colors.surface, color: colors.onSurface }}
        data-testid={`${testId}-input`}
      />
    </div>
  );
}


/** A single collapsible filter row. */
function FilterRow({ id, label, expanded, onToggle, children }) {
  return (
    <div
      className="rounded-lg"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.divider}`,
      }}
      data-testid={`filter-row-${id}`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 text-sm font-semibold"
        style={{ color: colors.onSurface }}
        data-testid={`filter-row-${id}-toggle`}
      >
        <span className="flex items-center gap-1.5">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {label}
        </span>
      </button>
      {expanded ? <div className="px-3 pb-3">{children}</div> : null}
    </div>
  );
}


export function FilterBuilder({
  filters = {},
  onChange,
  technicians = [],
  crews = [],
  testIdPrefix = "trigger-filter",
}) {
  const [openRows, setOpenRows] = useState(() => {
    // Auto-expand rows that already carry values.
    const init = {};
    Object.keys(filters || {}).forEach((k) => { init[k] = true; });
    return init;
  });
  const toggleRow = (id) => setOpenRows((prev) => ({ ...prev, [id]: !prev[id] }));

  const setField = (k, v) => {
    const next = { ...(filters || {}) };
    if (v === null || v === undefined || (Array.isArray(v) && v.length === 0) || v === "") {
      delete next[k];
    } else {
      next[k] = v;
    }
    onChange?.(next);
  };

  const toggleMulti = (k, id) => {
    const cur = new Set(filters[k] || []);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    setField(k, Array.from(cur));
  };

  return (
    <div className="space-y-2" data-testid={`${testIdPrefix}-wrap`}>
      <FilterRow
        id="customer_segment"
        label="Customer segment"
        expanded={openRows.customer_segment}
        onToggle={() => toggleRow("customer_segment")}
      >
        <div className="flex flex-wrap gap-1.5">
          {SEGMENT_OPTIONS.map((o) => (
            <Chip
              key={o.id}
              label={o.label}
              active={(filters.customer_segment || []).includes(o.id)}
              onToggle={() => toggleMulti("customer_segment", o.id)}
              testId={`${testIdPrefix}-segment-${o.id}`}
            />
          ))}
        </div>
      </FilterRow>

      <FilterRow
        id="work_class"
        label="Work class"
        expanded={openRows.work_class}
        onToggle={() => toggleRow("work_class")}
      >
        <div className="flex flex-wrap gap-1.5">
          {WORK_CLASS_OPTIONS.map((o) => (
            <Chip
              key={o.id}
              label={o.label}
              active={(filters.work_class || []).includes(o.id)}
              onToggle={() => toggleMulti("work_class", o.id)}
              testId={`${testIdPrefix}-work-class-${o.id}`}
            />
          ))}
        </div>
      </FilterRow>

      <FilterRow
        id="tags"
        label="Tags"
        expanded={openRows.tags}
        onToggle={() => toggleRow("tags")}
      >
        <PillInput
          values={filters.tags || []}
          onChange={(v) => setField("tags", v)}
          placeholder="Add tag, press Enter"
          testId={`${testIdPrefix}-tags`}
        />
      </FilterRow>

      <FilterRow
        id="technician_id"
        label="Technician"
        expanded={openRows.technician_id}
        onToggle={() => toggleRow("technician_id")}
      >
        {technicians.length === 0 ? (
          <div className="text-xs" style={{ color: colors.muted }}>
            No technicians loaded.
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {technicians.map((t) => (
              <Chip
                key={t.id}
                label={t.name || t.email || t.id}
                active={(filters.technician_id || []).includes(t.id)}
                onToggle={() => toggleMulti("technician_id", t.id)}
                testId={`${testIdPrefix}-tech-${t.id}`}
              />
            ))}
          </div>
        )}
      </FilterRow>

      <FilterRow
        id="crew_id"
        label="Crew"
        expanded={openRows.crew_id}
        onToggle={() => toggleRow("crew_id")}
      >
        {crews.length === 0 ? (
          <div className="text-xs" style={{ color: colors.muted }}>
            No crews loaded.
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {crews.map((c) => (
              <Chip
                key={c.id}
                label={c.name || c.id}
                active={(filters.crew_id || []).includes(c.id)}
                onToggle={() => toggleMulti("crew_id", c.id)}
                testId={`${testIdPrefix}-crew-${c.id}`}
              />
            ))}
          </div>
        )}
      </FilterRow>

      <FilterRow
        id="job_value_gte"
        label="Job value ≥"
        expanded={openRows.job_value_gte}
        onToggle={() => toggleRow("job_value_gte")}
      >
        <div className="flex items-center gap-2">
          <span className="text-sm" style={{ color: colors.muted }}>$</span>
          <input
            type="number"
            min={0}
            value={filters.job_value_gte ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              setField("job_value_gte", v === "" ? null : Number(v));
            }}
            className="w-32 px-2 py-1.5 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`${testIdPrefix}-job-value-gte`}
          />
        </div>
      </FilterRow>

      <FilterRow
        id="zip"
        label="Zip / route zone"
        expanded={openRows.zip}
        onToggle={() => toggleRow("zip")}
      >
        <PillInput
          values={filters.zip || []}
          onChange={(v) => setField("zip", v)}
          placeholder="Add zip, press Enter"
          testId={`${testIdPrefix}-zip`}
        />
      </FilterRow>

      <FilterRow
        id="last_visit_gte_days"
        label="Last visit ≥"
        expanded={openRows.last_visit_gte_days}
        onToggle={() => toggleRow("last_visit_gte_days")}
      >
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            value={filters.last_visit_gte_days ?? ""}
            onChange={(e) => {
              const v = e.target.value;
              setField("last_visit_gte_days", v === "" ? null : Number(v));
            }}
            className="w-24 px-2 py-1.5 rounded-lg text-sm outline-none"
            style={{
              backgroundColor: colors.surface,
              color: colors.onSurface,
              border: `1px solid ${colors.border}`,
            }}
            data-testid={`${testIdPrefix}-last-visit-days`}
          />
          <span className="text-sm" style={{ color: colors.muted }}>days ago</span>
        </div>
      </FilterRow>

      <CustomFieldsBlock
        specs={filters.custom_fields || []}
        onChange={(v) => setField("custom_fields", v)}
        expanded={openRows.custom_fields}
        onToggle={() => toggleRow("custom_fields")}
        testIdPrefix={testIdPrefix}
      />
    </div>
  );
}


function CustomFieldsBlock({ specs = [], onChange, expanded, onToggle, testIdPrefix }) {
  const addSpec = () => onChange([...(specs || []), { key: "", op: "eq", value: "" }]);
  const updateSpec = (i, patch) =>
    onChange(specs.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const removeSpec = (i) => onChange(specs.filter((_, j) => j !== i));

  return (
    <FilterRow
      id="custom_fields"
      label="Custom field match"
      expanded={expanded}
      onToggle={onToggle}
    >
      <div className="space-y-1.5">
        {(specs || []).map((s, i) => (
          <div key={i} className="flex items-center gap-1.5" data-testid={`${testIdPrefix}-cf-row-${i}`}>
            <input
              type="text"
              placeholder="Field key"
              value={s.key || ""}
              onChange={(e) => updateSpec(i, { key: e.target.value })}
              className="flex-1 px-2 py-1.5 rounded-lg text-sm outline-none"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={`${testIdPrefix}-cf-row-${i}-key`}
            />
            <select
              value={s.op || "eq"}
              onChange={(e) => updateSpec(i, { op: e.target.value })}
              className="px-2 py-1.5 rounded-lg text-sm outline-none"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={`${testIdPrefix}-cf-row-${i}-op`}
            >
              <option value="eq">equals</option>
              <option value="neq">not equal</option>
              <option value="contains">contains</option>
              <option value="gte">≥</option>
              <option value="lte">≤</option>
            </select>
            <input
              type="text"
              placeholder="Value"
              value={s.value ?? ""}
              onChange={(e) => updateSpec(i, { value: e.target.value })}
              className="flex-1 px-2 py-1.5 rounded-lg text-sm outline-none"
              style={{
                backgroundColor: colors.surface,
                color: colors.onSurface,
                border: `1px solid ${colors.border}`,
              }}
              data-testid={`${testIdPrefix}-cf-row-${i}-value`}
            />
            <button
              type="button"
              onClick={() => removeSpec(i)}
              className="px-2 py-1.5"
              style={{ color: colors.error }}
              data-testid={`${testIdPrefix}-cf-row-${i}-remove`}
            >
              <X size={14} />
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addSpec}
          className="text-xs font-semibold"
          style={{ color: colors.brand }}
          data-testid={`${testIdPrefix}-cf-add`}
        >
          + Add custom field match
        </button>
      </div>
    </FilterRow>
  );
}
