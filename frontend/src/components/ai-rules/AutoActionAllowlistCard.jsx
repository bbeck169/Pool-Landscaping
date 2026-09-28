/**
 * MTH-B · Feb-2026 — Auto-Action Allowlist card.
 *
 * Renders every server-side action key grouped by namespace with
 * a per-action toggle between ``auto`` and ``admin_approval``.
 * Group headers count Auto rows / total.  Search filter narrows
 * both group visibility (a group vanishes when no rows match) and
 * per-row visibility.  Override pill appears next to any row set
 * to a value different from the platform default.
 */
import React, { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  RotateCcw, Save, ListChecks, Zap, Loader2, Check, X,
} from "lucide-react";
import { api } from "@/api";
import { Button, Chip, TextInput, Modal } from "@/components/ui-kit";
import { groupActions, actionLabel } from "@/lib/aiRulesActionLabels";
import RulesReasonModal from "./RulesReasonModal";

const ALLOWLIST_MODES = ["auto", "admin_approval"];

export default function AutoActionAllowlistCard({
  value,
  overrideMap,
  platformValue,
  actionInventory,
  onSaved,
  onReset,
  readOnly = false,
  endpointPrefix = "/tenant-ai-rules",
  showReset = true,
  employeeKeys,
}) {
  const [draft, setDraft] = useState(value || {});
  const [search, setSearch] = useState("");
  const [saveOpen, setSaveOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  // MTH-D · Feb-2026 — auto-action walkthrough modal state.
  const [walkthroughOpen, setWalkthroughOpen] = useState(false);
  const [walkthroughAction, setWalkthroughAction] = useState(null);
  const [walkthroughEmp, setWalkthroughEmp] = useState("");
  const [walkthroughBusy, setWalkthroughBusy] = useState(false);
  const [walkthroughResult, setWalkthroughResult] = useState(null);

  React.useEffect(() => {
    setDraft(value || {});
  }, [value]);

  const groups = useMemo(() => groupActions(actionInventory || []), [actionInventory]);

  const filteredGroups = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({
        ...g,
        actions: g.actions.filter(
          (a) =>
            a.toLowerCase().includes(q) ||
            actionLabel(a).toLowerCase().includes(q),
        ),
      }))
      .filter((g) => g.actions.length > 0);
  }, [groups, search]);

  const overrideCount = useMemo(() => {
    if (!overrideMap) return 0;
    return Object.entries(overrideMap).filter(
      ([k, v]) =>
        v === "tenant" && k.startsWith("auto_action_allowlist."),
    ).length;
  }, [overrideMap]);

  const setAction = (key, mode) => {
    setDraft((prev) => ({ ...prev, [key]: mode }));
  };

  const openWalkthrough = (actionKey) => {
    setWalkthroughAction(actionKey);
    // Preselect the namespace as the employee_key for the first
    // pick — matches convention (marco.* → marco_executive is
    // aliased; casey.* → casey).  Admin can change in the modal.
    const [ns] = actionKey.split(".");
    const guess = ns === "marco" ? "marco_executive" : ns;
    setWalkthroughEmp(guess);
    setWalkthroughResult(null);
    setWalkthroughOpen(true);
  };

  const runWalkthrough = async () => {
    if (walkthroughBusy || !walkthroughAction || !walkthroughEmp) return;
    setWalkthroughBusy(true);
    setWalkthroughResult(null);
    try {
      const res = await api.post("/tenant-ai-rules/preview", {
        category: "auto_action_allowlist",
        pending_value: draft,
        preview_kind: "auto_action_walkthrough",
        preview_input: {
          employee_key: walkthroughEmp,
          action_key: walkthroughAction,
        },
      });
      setWalkthroughResult(res);
    } catch (e) {
      toast.error(
        `Test failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    } finally {
      setWalkthroughBusy(false);
    }
  };

  const doSave = async (reason) => {
    try {
      await api.put(`${endpointPrefix}/auto_action_allowlist`, {
        value: draft,
        reason,
      });
      toast.success("Auto-action allowlist saved.");
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
      await api.post(`${endpointPrefix}/reset/auto_action_allowlist`, {
        reason,
      });
      toast.success("Allowlist reset to platform defaults.");
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
      data-testid="ai-rules-auto-actions-card"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "#DBEAFE", color: "#1D4ED8" }}
          >
            <ListChecks size={16} />
          </div>
          <div>
            <div className="text-sm font-bold">Auto-Action Allowlist</div>
            <div className="text-xs opacity-60">
              Toggle each action between <strong>Auto</strong> (fires without
              approval) and <strong>Admin Approval</strong> (queued for
              admin review).
            </div>
          </div>
        </div>
        {overrideCount > 0 ? (
          <Chip
            label={`${overrideCount} tenant override${overrideCount === 1 ? "" : "s"}`}
            tone="brand"
            testid="ai-rules-auto-actions-override-pill"
          />
        ) : null}
      </div>

      <TextInput
        placeholder="Search actions… (e.g. clock_in, casey, refund)"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        testid="ai-rules-auto-actions-search"
      />

      <div
        className="space-y-4 max-h-[520px] overflow-y-auto pr-1"
        data-testid="ai-rules-auto-actions-groups"
      >
        {filteredGroups.length === 0 ? (
          <div
            className="text-sm opacity-60 py-4 text-center"
            data-testid="ai-rules-auto-actions-empty"
          >
            No actions match “{search}”.
          </div>
        ) : (
          filteredGroups.map((g) => {
            const autoCount = g.actions.filter(
              (a) => (draft[a] || "admin_approval") === "auto",
            ).length;
            return (
              <div
                key={g.namespace}
                data-testid={`ai-rules-auto-actions-group-${g.namespace}`}
              >
                <div
                  className="flex items-center justify-between mb-1 px-1 pt-2"
                  style={{ color: "#334155" }}
                >
                  <div className="text-xs font-bold tracking-wide">
                    {g.label}
                  </div>
                  <div
                    className="text-xs opacity-70"
                    data-testid={`ai-rules-auto-actions-group-count-${g.namespace}`}
                  >
                    {autoCount}/{g.actions.length} auto-approved
                  </div>
                </div>
                <div className="rounded-lg border overflow-hidden"
                     style={{ borderColor: "#E2E8F0" }}>
                  {g.actions.map((a, idx) => {
                    const mode = draft[a] || "admin_approval";
                    const platformMode =
                      (platformValue && platformValue[a]) || "admin_approval";
                    const overridden = mode !== platformMode;
                    return (
                      <div
                        key={a}
                        className="flex items-center justify-between px-3 py-2 gap-3"
                        style={{
                          background: idx % 2 === 0 ? "#FFFFFF" : "#F8FAFC",
                          borderTop:
                            idx === 0 ? "none" : "1px solid #F1F5F9",
                        }}
                        data-testid={`ai-rules-auto-action-row-${a}`}
                      >
                        <div className="min-w-0">
                          <div
                            className="text-sm font-semibold truncate"
                            style={{ color: "#1F2937" }}
                          >
                            {actionLabel(a)}
                          </div>
                          <div className="text-[11px] opacity-60 truncate font-mono">
                            {a}
                          </div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {overridden ? (
                            <Chip
                              label="override"
                              tone="warning"
                              testid={`ai-rules-auto-action-row-${a}-override`}
                            />
                          ) : null}
                          <button
                            type="button"
                            onClick={() => openWalkthrough(a)}
                            className="text-xs px-2 py-1 rounded-md opacity-70 hover:opacity-100"
                            style={{
                              background: "#F1F5F9",
                              color: "#334155",
                              border: "1px solid #E2E8F0",
                            }}
                            title="Test this action"
                            data-testid={`ai-rules-auto-action-row-${a}-test`}
                          >
                            <Zap size={12} />
                          </button>
                          <div
                            role="radiogroup"
                            className="inline-flex rounded-full overflow-hidden text-[11px] font-semibold"
                            style={{ border: "1px solid #CBD5E1" }}
                          >
                            {ALLOWLIST_MODES.map((m) => {
                              const active = mode === m;
                              return (
                                <button
                                  key={m}
                                  type="button"
                                  onClick={() => setAction(a, m)}
                                  disabled={readOnly}
                                  className="px-3 py-1"
                                  style={{
                                    background: active
                                      ? m === "auto"
                                        ? "#166534"
                                        : "#334155"
                                      : "#FFFFFF",
                                    color: active ? "#fff" : "#334155",
                                  }}
                                  data-testid={`ai-rules-auto-action-row-${a}-mode-${m}`}
                                >
                                  {m === "auto" ? "Auto" : "Admin"}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        {showReset ? (
          <Button
            variant="ghost"
            onClick={() => setResetOpen(true)}
            disabled={readOnly}
            testid="ai-rules-auto-actions-reset"
          >
            <RotateCcw size={14} /> Reset to Platform Default
          </Button>
        ) : null}
        <Button
          variant="primary"
          onClick={() => setSaveOpen(true)}
          disabled={readOnly}
          testid="ai-rules-auto-actions-save"
        >
          <Save size={14} /> Save
        </Button>
      </div>

      <RulesReasonModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="Save Auto-Action Allowlist"
        description="Auto actions fire immediately; Admin Approval routes the request to the review queue."
        onConfirm={doSave}
        confirmLabel="Save Allowlist"
        testidPrefix="ai-rules-auto-actions-save-reason"
      />
      <RulesReasonModal
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title="Reset Auto-Action Allowlist"
        description="Restores every action to the platform-default mode (typically Admin Approval)."
        onConfirm={doReset}
        confirmLabel="Reset to Default"
        confirmVariant="danger"
        testidPrefix="ai-rules-auto-actions-reset-reason"
      />

      <Modal
        open={walkthroughOpen}
        onClose={() => setWalkthroughOpen(false)}
        title={
          walkthroughAction
            ? `Walkthrough: ${walkthroughAction}`
            : "Auto-action walkthrough"
        }
        testid="ai-rules-auto-actions-walkthrough-modal"
        footer={
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => setWalkthroughOpen(false)}
              testid="ai-rules-auto-actions-walkthrough-close"
            >
              Close
            </Button>
          </div>
        }
      >
        <div className="space-y-3 text-sm">
          <div>
            <label className="text-xs font-semibold tracking-wide"
                    style={{ color: "#334155" }}>
              PICK AN EMPLOYEE
            </label>
            <select
              value={walkthroughEmp}
              onChange={(e) => setWalkthroughEmp(e.target.value)}
              className="w-full mt-1 px-3 py-2 rounded-lg text-sm bg-white border"
              style={{ borderColor: "#E2E8F0" }}
              data-testid="ai-rules-auto-actions-walkthrough-employee"
            >
              <option value="">— Select —</option>
              {(employeeKeys || []).map((k) => (
                <option key={k} value={k}>{k}</option>
              ))}
            </select>
          </div>
          <div className="flex justify-end">
            <Button
              variant="primary"
              onClick={runWalkthrough}
              disabled={walkthroughBusy || !walkthroughEmp}
              testid="ai-rules-auto-actions-walkthrough-run"
            >
              {walkthroughBusy ? (
                <><Loader2 size={12} className="animate-spin" /> Checking…</>
              ) : (
                <><Zap size={12} /> Run walkthrough</>
              )}
            </Button>
          </div>
          {walkthroughResult?.output?.reason_chain ? (
            <div
              className="space-y-1"
              data-testid="ai-rules-auto-actions-walkthrough-chain"
            >
              {walkthroughResult.output.reason_chain.map((step, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2 rounded-md p-2 border"
                  style={{
                    background: step.ok ? "#DCFCE7" : "#FEE2E2",
                    color: step.ok ? "#166534" : "#991B1B",
                    borderColor: step.ok ? "#BBF7D0" : "#FCA5A5",
                  }}
                  data-testid={`ai-rules-auto-actions-walkthrough-step-${i}`}
                >
                  {step.ok
                    ? <Check size={14} className="shrink-0 mt-0.5" />
                    : <X size={14} className="shrink-0 mt-0.5" />}
                  <div>
                    <div className="font-semibold">{step.check}</div>
                    <div className="text-xs opacity-80">{step.reason}</div>
                  </div>
                </div>
              ))}
              <div
                className="mt-2 rounded-md p-2 text-xs font-semibold"
                style={{
                  background: walkthroughResult.output.would_auto_execute
                    ? "#DCFCE7" : "#FEF3C7",
                  color: walkthroughResult.output.would_auto_execute
                    ? "#166534" : "#92400E",
                }}
                data-testid="ai-rules-auto-actions-walkthrough-verdict"
              >
                Final verdict: {walkthroughResult.output.final_verdict}
              </div>
            </div>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}
