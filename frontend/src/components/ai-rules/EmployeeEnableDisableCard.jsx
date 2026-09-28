/**
 * MTH-B · Feb-2026 — Employee Enable/Disable card.
 *
 * Renders the 18-employee AIHUB-A registry (fetched via
 * ``GET /api/ai-employees`` so we get ``human_name``,
 * ``org_department`` and the CDN avatar URL alongside the
 * ``key``).  Each row has a toggle wired to
 * ``employee_enable_disable[key]``.  A disabled row surfaces the
 * "Disabled for this tenant" pill and mutes the row background.
 *
 * The rule takes precedence over an employee's
 * ``authorized_for_public_use`` gate — the info footer states
 * that explicitly so admins don't get surprised.
 */
import React, { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { RotateCcw, Save, Users } from "lucide-react";
import { api } from "@/api";
import { Button, Chip, Skeleton } from "@/components/ui-kit";
import RulesReasonModal from "./RulesReasonModal";

export default function EmployeeEnableDisableCard({
  value,
  overrideMap,
  employeeKeys,
  onSaved,
  onReset,
  readOnly = false,
  endpointPrefix = "/tenant-ai-rules",
  showReset = true,
  employees: injectedEmployees, // test hook — bypass the network call.
}) {
  const [draft, setDraft] = useState(value || {});
  const [saveOpen, setSaveOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [employees, setEmployees] = useState(injectedEmployees || null);
  const [loading, setLoading] = useState(!injectedEmployees);

  useEffect(() => {
    setDraft(value || {});
  }, [value]);

  useEffect(() => {
    if (injectedEmployees) {
      setEmployees(injectedEmployees);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    api
      .get("/ai-employees")
      .then((rows) => {
        if (!alive) return;
        setEmployees(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!alive) return;
        // Fall back to key-only rendering — better than a blank card.
        setEmployees([]);
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [injectedEmployees]);

  const grouped = useMemo(() => {
    const roster = (employees || []).filter(Boolean);
    const byKey = new Map(roster.map((e) => [e.key, e]));
    // Merge in any keys the backend inventory knows about that the
    // per-tenant roster call omitted — keeps the surface complete
    // during a partial seed.
    (employeeKeys || []).forEach((k) => {
      if (!byKey.has(k)) {
        byKey.set(k, {
          key: k,
          human_name: k,
          org_department: "operations",
          avatar_url: "",
        });
      }
    });
    const rows = [...byKey.values()].sort(
      (a, b) =>
        (a.hierarchy_order || 999) - (b.hierarchy_order || 999) ||
        (a.human_name || "").localeCompare(b.human_name || ""),
    );
    const buckets = new Map();
    rows.forEach((r) => {
      const dept = r.org_department || "operations";
      if (!buckets.has(dept)) buckets.set(dept, []);
      buckets.get(dept).push(r);
    });
    const order = ["executive", "marketing", "operations"];
    return order
      .filter((d) => buckets.has(d))
      .map((d) => ({ dept: d, rows: buckets.get(d) }));
  }, [employees, employeeKeys]);

  const overrideCount = useMemo(() => {
    if (!overrideMap) return 0;
    return Object.entries(overrideMap).filter(
      ([k, v]) =>
        v === "tenant" && k.startsWith("employee_enable_disable."),
    ).length;
  }, [overrideMap]);

  const setEmployee = (key, enabled) => {
    setDraft((prev) => ({ ...prev, [key]: enabled }));
  };

  const doSave = async (reason) => {
    try {
      await api.put(`${endpointPrefix}/employee_enable_disable`, {
        value: draft,
        reason,
      });
      toast.success("Employee enable/disable saved.");
      setSaveOpen(false);
      if (onSaved) await onSaved();
    } catch (e) {
      toast.error(
        `Save failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  const doReset = async (reason) => {
    try {
      await api.post(`${endpointPrefix}/reset/employee_enable_disable`, {
        reason,
      });
      toast.success("Employee toggles reset to platform defaults.");
      setResetOpen(false);
      if (onReset) await onReset();
    } catch (e) {
      toast.error(
        `Reset failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  return (
    <div
      className="rounded-2xl bg-white border p-5 space-y-4"
      style={{ borderColor: "#E2E8F0" }}
      data-testid="ai-rules-employee-enable-card"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "#FCE7F3", color: "#BE185D" }}
          >
            <Users size={16} />
          </div>
          <div>
            <div className="text-sm font-bold">Employee Enable / Disable</div>
            <div className="text-xs opacity-60">
              Force an employee dormant for this tenant, regardless of
              their global ``authorized_for_public_use`` gate.
            </div>
          </div>
        </div>
        {overrideCount > 0 ? (
          <Chip
            label={`${overrideCount} tenant override${overrideCount === 1 ? "" : "s"}`}
            tone="brand"
            testid="ai-rules-employee-enable-override-pill"
          />
        ) : null}
      </div>

      {loading ? (
        <Skeleton className="h-24" />
      ) : (
        <div className="space-y-4">
          {grouped.map((g) => (
            <div key={g.dept} data-testid={`ai-rules-employee-dept-${g.dept}`}>
              <div
                className="text-xs font-bold tracking-wide mb-1 px-1"
                style={{ color: "#334155" }}
              >
                {g.dept === "executive"
                  ? "Executive Tier"
                  : g.dept === "marketing"
                    ? "Marketing"
                    : "Operations"}
              </div>
              <div
                className="rounded-lg border overflow-hidden"
                style={{ borderColor: "#E2E8F0" }}
              >
                {g.rows.map((emp, idx) => {
                  const enabled =
                    draft[emp.key] === undefined ? true : Boolean(draft[emp.key]);
                  return (
                    <div
                      key={emp.key}
                      className="flex items-center justify-between px-3 py-2 gap-3"
                      style={{
                        background: enabled
                          ? idx % 2 === 0
                            ? "#FFFFFF"
                            : "#F8FAFC"
                          : "#F1F5F9",
                        borderTop:
                          idx === 0 ? "none" : "1px solid #F1F5F9",
                        opacity: enabled ? 1 : 0.65,
                      }}
                      data-testid={`ai-rules-employee-row-${emp.key}`}
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        {emp.avatar_url ? (
                          <img
                            src={emp.avatar_url}
                            alt={emp.human_name || emp.key}
                            className="w-10 h-10 rounded-full object-cover"
                            style={{ background: "#E0F2FE" }}
                            data-testid={`ai-rules-employee-row-${emp.key}-avatar`}
                          />
                        ) : (
                          <div
                            className="w-10 h-10 rounded-full flex items-center justify-center text-xs font-bold"
                            style={{
                              background: "#E0F2FE",
                              color: "#0369A1",
                            }}
                            data-testid={`ai-rules-employee-row-${emp.key}-avatar-fallback`}
                          >
                            {(emp.human_name || emp.key || "?")
                              .slice(0, 2)
                              .toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0">
                          <div className="text-sm font-semibold truncate">
                            {emp.human_name || emp.key}
                            {emp.codename ? (
                              <span className="opacity-60 font-mono text-[11px] ml-2">
                                {emp.codename}
                              </span>
                            ) : null}
                          </div>
                          <div className="text-[11px] opacity-70 truncate">
                            {emp.role_title || emp.role || ""}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        {!enabled ? (
                          <Chip
                            label="Disabled"
                            tone="danger"
                            testid={`ai-rules-employee-row-${emp.key}-disabled-pill`}
                          />
                        ) : null}
                        <button
                          type="button"
                          role="switch"
                          aria-checked={enabled}
                          onClick={() => setEmployee(emp.key, !enabled)}
                          disabled={readOnly}
                          className="relative inline-flex items-center rounded-full transition-colors"
                          style={{
                            width: 44,
                            height: 24,
                            background: enabled ? "#166534" : "#94A3B8",
                          }}
                          data-testid={`ai-rules-employee-row-${emp.key}-toggle`}
                        >
                          <span
                            className="inline-block rounded-full bg-white shadow transition-transform"
                            style={{
                              width: 18,
                              height: 18,
                              transform: enabled
                                ? "translateX(22px)"
                                : "translateX(4px)",
                            }}
                          />
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      <div
        className="text-xs opacity-70 rounded-md p-2"
        style={{ background: "#F8FAFC", color: "#334155" }}
        data-testid="ai-rules-employee-enable-note"
      >
        Disabling here overrides <code>authorized_for_public_use</code>. Even
        authorized employees won't act if disabled here.
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        {showReset ? (
          <Button
            variant="ghost"
            onClick={() => setResetOpen(true)}
            disabled={readOnly}
            testid="ai-rules-employee-enable-reset"
          >
            <RotateCcw size={14} /> Reset to Platform Default
          </Button>
        ) : null}
        <Button
          variant="primary"
          onClick={() => setSaveOpen(true)}
          disabled={readOnly}
          testid="ai-rules-employee-enable-save"
        >
          <Save size={14} /> Save
        </Button>
      </div>

      <RulesReasonModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="Save Employee Enable / Disable"
        description="Disabled employees will stop taking actions for this tenant immediately."
        onConfirm={doSave}
        confirmLabel="Save Employees"
        testidPrefix="ai-rules-employee-enable-save-reason"
      />
      <RulesReasonModal
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title="Reset Employee Toggles"
        description="Reverts every employee to the platform-default enabled/disabled state."
        onConfirm={doReset}
        confirmLabel="Reset to Default"
        confirmVariant="danger"
        testidPrefix="ai-rules-employee-enable-reset-reason"
      />
    </div>
  );
}
