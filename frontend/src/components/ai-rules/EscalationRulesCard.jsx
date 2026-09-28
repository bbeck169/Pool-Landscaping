/**
 * MTH-B · Feb-2026 — Escalation Rules card.
 *
 * Table of ``{ keyword, is_regex, target_role, sla_minutes,
 * notify_channel }`` rules with add / edit / delete + regex
 * toggle.  The backend caps at 50 rules and validates the regex
 * server-side (client only checks emptiness + range).
 */
import React, { useState } from "react";
import { toast } from "sonner";
import {
  RotateCcw, Save, Plus, Trash2, AlertTriangle, Zap, Loader2,
} from "lucide-react";
import { api } from "@/api";
import { Button, Chip, TextInput } from "@/components/ui-kit";
import RulesReasonModal from "./RulesReasonModal";
import OverrideDiff from "./OverrideDiff";

const ROLES = ["admin", "super"];
const CHANNELS = ["email", "sms", "both"];
const SLA_MIN = 1;
const SLA_MAX = 1440;

function normalizeRule(r) {
  return {
    keyword: r?.keyword || "",
    is_regex: Boolean(r?.is_regex),
    target_role: ROLES.includes(r?.target_role) ? r.target_role : "admin",
    sla_minutes:
      typeof r?.sla_minutes === "number"
        ? Math.max(SLA_MIN, Math.min(SLA_MAX, r.sla_minutes))
        : 5,
    notify_channel: CHANNELS.includes(r?.notify_channel)
      ? r.notify_channel
      : "email",
  };
}

export default function EscalationRulesCard({
  value,
  overrideMap,
  platformValue,
  onSaved,
  onReset,
  readOnly = false,
  endpointPrefix = "/tenant-ai-rules",
  showReset = true,
  showDiff = true,
}) {
  const [rules, setRules] = useState(() =>
    (Array.isArray(value) ? value : []).map(normalizeRule),
  );
  const [saveOpen, setSaveOpen] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  // MTH-D · Feb-2026 — server-driven testbench state.
  const [testMessages, setTestMessages] = useState("");
  const [testBusy, setTestBusy] = useState(false);
  const [testResult, setTestResult] = useState(null);

  React.useEffect(() => {
    setRules((Array.isArray(value) ? value : []).map(normalizeRule));
  }, [value]);

  const isOverridden = overrideMap?.escalation_rules === "tenant";

  const patch = (idx, field, val) => {
    setRules((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: val };
      return next;
    });
  };
  const addRule = () => {
    setRules((prev) => [
      ...prev,
      {
        keyword: "",
        is_regex: false,
        target_role: "admin",
        sla_minutes: 5,
        notify_channel: "email",
      },
    ]);
  };
  const removeRule = (idx) => {
    setRules((prev) => prev.filter((_, i) => i !== idx));
  };

  const doSave = async (reason) => {
    // Client-side sanity — the backend validator is authoritative.
    const cleaned = rules.map(normalizeRule).filter((r) => r.keyword.trim());
    try {
      await api.put(`${endpointPrefix}/escalation_rules`, {
        value: cleaned,
        reason,
      });
      toast.success(
        `Escalation rules saved (${cleaned.length} rule${cleaned.length === 1 ? "" : "s"}).`,
      );
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
      await api.post(`${endpointPrefix}/reset/escalation_rules`, { reason });
      toast.success("Escalation rules reset to platform default.");
      setResetOpen(false);
      if (onReset) await onReset();
    } catch (e) {
      toast.error(
        `Reset failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    }
  };

  const runTestbench = async () => {
    if (testBusy) return;
    const cleaned = rules.map(normalizeRule).filter((r) => r.keyword.trim());
    const messages = testMessages
      .split("\n")
      .map((m) => m.trim())
      .filter(Boolean)
      .slice(0, 5);
    if (!messages.length) {
      toast.error("Add at least one test message (one per line).");
      return;
    }
    setTestBusy(true);
    setTestResult(null);
    try {
      const res = await api.post("/tenant-ai-rules/preview", {
        category: "escalation_rules",
        pending_value: cleaned,
        preview_kind: "escalation_match",
        preview_input: { test_messages: messages },
      });
      setTestResult(res);
    } catch (e) {
      toast.error(
        `Test failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    } finally {
      setTestBusy(false);
    }
  };

  return (
    <div
      className="rounded-2xl bg-white border p-5 space-y-4"
      style={{ borderColor: "#E2E8F0" }}
      data-testid="ai-rules-escalation-card"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "#FEE2E2", color: "#991B1B" }}
          >
            <AlertTriangle size={16} />
          </div>
          <div>
            <div className="text-sm font-bold">Escalation Rules</div>
            <div className="text-xs opacity-60">
              Route matching customer messages to an admin queue with an SLA.
            </div>
          </div>
        </div>
        {isOverridden ? (
          <Chip
            label="tenant override"
            tone="brand"
            testid="ai-rules-escalation-override-pill"
          />
        ) : null}
      </div>

      <OverrideDiff
        category="escalation_rules"
        overrideMap={overrideMap}
        tenantValue={value}
        platformValue={platformValue}
        testid="ai-rules-escalation-diff"
        readOnly={!showDiff}
      />

      <div
        className="rounded-lg border overflow-hidden"
        style={{ borderColor: "#E2E8F0" }}
        data-testid="ai-rules-escalation-table"
      >
        <div
          className="grid grid-cols-12 text-[11px] font-semibold tracking-wide px-3 py-2"
          style={{ background: "#F1F5F9", color: "#334155" }}
        >
          <div className="col-span-4">KEYWORD / REGEX</div>
          <div className="col-span-2">REGEX?</div>
          <div className="col-span-2">TARGET ROLE</div>
          <div className="col-span-2">SLA (min)</div>
          <div className="col-span-1">CHANNEL</div>
          <div className="col-span-1 text-right">ACT</div>
        </div>
        {rules.length === 0 ? (
          <div
            className="p-4 text-sm opacity-60 text-center"
            data-testid="ai-rules-escalation-empty"
          >
            No escalation rules yet. Add one below.
          </div>
        ) : (
          rules.map((r, idx) => (
            <div
              key={idx}
              className="grid grid-cols-12 gap-2 items-center px-3 py-2 text-sm"
              style={{
                background: idx % 2 === 0 ? "#FFFFFF" : "#F8FAFC",
                borderTop: idx === 0 ? "none" : "1px solid #F1F5F9",
              }}
              data-testid={`ai-rules-escalation-row-${idx}`}
            >
              <div className="col-span-4">
                <TextInput
                  value={r.keyword}
                  onChange={(e) => patch(idx, "keyword", e.target.value)}
                  placeholder={r.is_regex ? "e.g. \\brefund|cancel\\b" : "refund"}
                  disabled={readOnly}
                  testid={`ai-rules-escalation-row-${idx}-keyword`}
                />
              </div>
              <div className="col-span-2">
                <label
                  className="inline-flex items-center gap-2 text-xs"
                  data-testid={`ai-rules-escalation-row-${idx}-regex-label`}
                >
                  <input
                    type="checkbox"
                    checked={r.is_regex}
                    onChange={(e) => patch(idx, "is_regex", e.target.checked)}
                    disabled={readOnly}
                    data-testid={`ai-rules-escalation-row-${idx}-regex`}
                  />
                  Regex
                </label>
              </div>
              <div className="col-span-2">
                <select
                  value={r.target_role}
                  onChange={(e) => patch(idx, "target_role", e.target.value)}
                  disabled={readOnly}
                  className="w-full px-2 py-1.5 rounded-md border text-sm bg-white"
                  style={{ borderColor: "#E2E8F0" }}
                  data-testid={`ai-rules-escalation-row-${idx}-role`}
                >
                  {ROLES.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-span-2">
                <input
                  type="number"
                  min={SLA_MIN}
                  max={SLA_MAX}
                  value={r.sla_minutes}
                  onChange={(e) =>
                    patch(
                      idx,
                      "sla_minutes",
                      Math.max(
                        SLA_MIN,
                        Math.min(SLA_MAX, Number(e.target.value) || SLA_MIN),
                      ),
                    )
                  }
                  disabled={readOnly}
                  className="w-full px-2 py-1.5 rounded-md border text-sm bg-white"
                  style={{ borderColor: "#E2E8F0" }}
                  data-testid={`ai-rules-escalation-row-${idx}-sla`}
                />
              </div>
              <div className="col-span-1">
                <select
                  value={r.notify_channel}
                  onChange={(e) => patch(idx, "notify_channel", e.target.value)}
                  disabled={readOnly}
                  className="w-full px-1 py-1.5 rounded-md border text-xs bg-white"
                  style={{ borderColor: "#E2E8F0" }}
                  data-testid={`ai-rules-escalation-row-${idx}-channel`}
                >
                  {CHANNELS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-span-1 flex justify-end">
                <button
                  type="button"
                  onClick={() => removeRule(idx)}
                  disabled={readOnly}
                  className="text-xs opacity-70 hover:opacity-100"
                  data-testid={`ai-rules-escalation-row-${idx}-remove`}
                  aria-label="Remove"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Button
          variant="ghost"
          onClick={addRule}
          disabled={readOnly}
          testid="ai-rules-escalation-add"
        >
          <Plus size={14} /> Add Rule
        </Button>
        <div className="flex items-center gap-2">
          {showReset ? (
            <Button
              variant="ghost"
              onClick={() => setResetOpen(true)}
              disabled={readOnly}
              testid="ai-rules-escalation-reset"
            >
              <RotateCcw size={14} /> Reset to Platform Default
            </Button>
          ) : null}
          <Button
            variant="primary"
            onClick={() => setSaveOpen(true)}
            disabled={readOnly}
            testid="ai-rules-escalation-save"
          >
            <Save size={14} /> Save
          </Button>
        </div>
      </div>

      <div
        className="rounded-lg border p-3 space-y-2"
        style={{ borderColor: "#E2E8F0", background: "#F8FAFC" }}
        data-testid="ai-rules-escalation-testbench"
      >
        <div className="text-xs font-bold flex items-center gap-2"
             style={{ color: "#334155" }}>
          <Zap size={12} /> TEST YOUR RULES
        </div>
        {(testResult?.warnings || [])
          .filter((w) => w.toLowerCase().includes("malformed"))
          .map((w, i) => (
            <div
              key={i}
              className="rounded-md p-2 text-xs flex gap-2"
              style={{
                background: "#FEF3C7",
                color: "#92400E",
                border: "1px solid #FDE68A",
              }}
              data-testid={`ai-rules-escalation-testbench-warning-${i}`}
            >
              <AlertTriangle size={14} className="shrink-0 mt-0.5" />
              <div>{w}</div>
            </div>
          ))}
        <textarea
          rows={3}
          value={testMessages}
          onChange={(e) => setTestMessages(e.target.value)}
          placeholder={"e.g.\nrefund my last visit\nmy pump is broken\nsee you next week"}
          disabled={readOnly || testBusy}
          className="w-full px-3 py-2 rounded-lg text-sm bg-white border focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
          style={{ borderColor: "#E2E8F0" }}
          data-testid="ai-rules-escalation-testbench-input"
        />
        <div className="flex items-center justify-between">
          <span className="text-[11px] opacity-60">
            Up to 5 messages, one per line.
          </span>
          <Button
            variant="primary"
            onClick={runTestbench}
            disabled={readOnly || testBusy}
            testid="ai-rules-escalation-testbench-run"
          >
            {testBusy ? (
              <><Loader2 size={12} className="animate-spin" /> Testing…</>
            ) : (
              <><Zap size={12} /> Test rules</>
            )}
          </Button>
        </div>
        {testResult?.output?.results?.length ? (
          <div
            className="space-y-1"
            data-testid="ai-rules-escalation-testbench-results"
          >
            {testResult.output.results.map((r, i) => (
              <div
                key={i}
                className="flex items-start gap-2 text-xs bg-white rounded-md p-2 border"
                style={{ borderColor: "#E2E8F0" }}
                data-testid={`ai-rules-escalation-testbench-result-${i}`}
              >
                {r.matched_rule ? (
                  <Chip label="ESCALATES" tone="danger"
                         testid={`ai-rules-escalation-testbench-result-${i}-match`} />
                ) : (
                  <Chip label="no match" tone="brand"
                         testid={`ai-rules-escalation-testbench-result-${i}-nomatch`} />
                )}
                <div className="flex-1 min-w-0">
                  <div className="font-mono truncate">{r.message}</div>
                  <div className="opacity-70 mt-0.5">{r.reasoning}</div>
                  {r.matched_rule ? (
                    <div className="opacity-70 mt-0.5">
                      → route to <strong>{r.matched_rule.target_role}</strong>
                      {" · SLA "}
                      <strong>{r.matched_rule.sla_minutes}m</strong>
                      {" · "}
                      <strong>{r.matched_rule.notify_channel}</strong>
                    </div>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <RulesReasonModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="Save Escalation Rules"
        description="Empty keywords are dropped on save. Regex rules are validated server-side."
        onConfirm={doSave}
        confirmLabel="Save Rules"
        testidPrefix="ai-rules-escalation-save-reason"
      />
      <RulesReasonModal
        open={resetOpen}
        onClose={() => setResetOpen(false)}
        title="Reset Escalation Rules"
        description="Reverts to the platform-default rules list."
        onConfirm={doReset}
        confirmLabel="Reset to Default"
        confirmVariant="danger"
        testidPrefix="ai-rules-escalation-reset-reason"
      />
    </div>
  );
}
