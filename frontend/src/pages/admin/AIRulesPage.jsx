/**
 * MTH-B · Feb-2026 — /admin/ai-rules page shell.
 *
 * Three tabs:
 *   • Rules             — master switch + 5 category cards (admin + super)
 *   • Revisions         — history + revert (admin + super)
 *   • Platform Defaults — super_admin ONLY; the tab is hidden entirely
 *                          from admin-role users (not just disabled).
 *
 * Backend contract (MTH-A · commit 39acf6beb):
 *   GET  /api/tenant-ai-rules            → resolved rules + override_map
 *                                            + master switch state
 *                                            + action_inventory
 *                                            + employee_keys
 *   PUT  /api/tenant-ai-rules/{category} → save one category (reason req)
 *   POST /api/tenant-ai-rules/reset/{cat}→ reset one category
 *   PUT  /api/tenant-ai-rules/master-switch  → super-only flip
 *   GET  /api/tenant-ai-rules/revisions      → immutable history
 *   POST /api/tenant-ai-rules/revert/{rev_num} → revert
 *   GET  /api/platform-ai-rules              → super-only
 *   PUT  /api/platform-ai-rules/{category}   → super-only
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Wrench } from "lucide-react";
import { api } from "@/api";
import { useAuth } from "@/auth";
import { PageHeader, Skeleton } from "@/components/ui-kit";

import MasterSwitchCard from "@/components/ai-rules/MasterSwitchCard";
import ToneVoiceCard from "@/components/ai-rules/ToneVoiceCard";
import AutoActionAllowlistCard from "@/components/ai-rules/AutoActionAllowlistCard";
import EmployeeEnableDisableCard from "@/components/ai-rules/EmployeeEnableDisableCard";
import WorkingHoursCard from "@/components/ai-rules/WorkingHoursCard";
import EscalationRulesCard from "@/components/ai-rules/EscalationRulesCard";
import RevisionsTab from "@/components/ai-rules/RevisionsTab";
import PlatformDefaultsTab from "@/components/ai-rules/PlatformDefaultsTab";

const TAB_RULES = "rules";
const TAB_REVISIONS = "revisions";
const TAB_PLATFORM = "platform";

export default function AIRulesPage() {
  const { user } = useAuth();
  const role = user?.role || "";
  const isSuper = role === "super_admin";
  const isAdmin = role === "admin" || isSuper;

  const [tab, setTab] = useState(TAB_RULES);
  const [data, setData] = useState(null);
  const [platformSnapshot, setPlatformSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadTenant = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/tenant-ai-rules");
      setData(res);
    } catch (e) {
      toast.error(
        `Load AI rules failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const loadPlatformSnapshot = useCallback(async () => {
    // Super can pull the true platform doc.  Admin can't (403) — we
    // reconstruct the platform-side values from the resolved payload
    // by falling back on any field where override_map says "platform".
    if (!isSuper) {
      setPlatformSnapshot(null);
      return;
    }
    try {
      const res = await api.get("/platform-ai-rules");
      setPlatformSnapshot(res);
    } catch {
      setPlatformSnapshot(null);
    }
  }, [isSuper]);

  useEffect(() => {
    if (!isAdmin) return;
    loadTenant();
    loadPlatformSnapshot();
  }, [isAdmin, loadTenant, loadPlatformSnapshot]);

  if (!isAdmin) {
    return (
      <div
        className="p-6 max-w-2xl mx-auto"
        data-testid="ai-rules-forbidden"
      >
        <PageHeader
          title="AI Rules"
          subtitle="Admin-only surface."
        />
        <div
          className="rounded-md p-3"
          style={{
            background: "#FEE2E2",
            color: "#7F1D1D",
            border: "1px solid #FCA5A5",
          }}
        >
          Requires admin or super-admin role.
        </div>
      </div>
    );
  }

  // Reconstruct platform-side per-category values so admin users get
  // a meaningful diff even without super access.  For a field that
  // ``override_map`` marks as "platform", the resolved value IS the
  // platform value.  For a tenant-overridden field we don't know the
  // platform side (admin can't call /platform-ai-rules) — pass
  // ``undefined`` and let the diff panel show "—".
  const platformFallback = (categoryKey) => {
    if (platformSnapshot?.rules?.[categoryKey] !== undefined) {
      return platformSnapshot.rules[categoryKey];
    }
    // Admin path — synthesize a best-effort platform view from the
    // resolved doc: for a dict category, only surface fields where
    // override_map says "platform".
    const rules = data?.rules?.[categoryKey];
    const om = data?.override_map || {};
    if (rules && typeof rules === "object" && !Array.isArray(rules)) {
      const out = {};
      Object.keys(rules).forEach((k) => {
        if (om[`${categoryKey}.${k}`] !== "tenant") {
          out[k] = rules[k];
        }
      });
      return out;
    }
    // Atomic category (escalation_rules).  If tenant overrode, we
    // don't know the platform side; return undefined to render "—".
    if (om[categoryKey] === "tenant") return undefined;
    return rules;
  };

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6" data-testid="ai-rules-page">
      <PageHeader
        title="AI Rules"
        subtitle="Tenant-scoped guard-rails for every AI-driven action, comm, and escalation."
        right={
          <div className="text-xs opacity-70 flex items-center gap-1">
            <Wrench size={14} />
            Operations · AI Rules
          </div>
        }
      />

      <div
        className="flex flex-wrap gap-1 border-b"
        style={{ borderColor: "#E2E8F0" }}
        role="tablist"
        data-testid="ai-rules-tabs"
      >
        <TabButton
          active={tab === TAB_RULES}
          onClick={() => setTab(TAB_RULES)}
          testid="ai-rules-tab-rules"
        >
          Rules
        </TabButton>
        <TabButton
          active={tab === TAB_REVISIONS}
          onClick={() => setTab(TAB_REVISIONS)}
          testid="ai-rules-tab-revisions"
        >
          Revisions
        </TabButton>
        {isSuper ? (
          <TabButton
            active={tab === TAB_PLATFORM}
            onClick={() => setTab(TAB_PLATFORM)}
            testid="ai-rules-tab-platform"
          >
            Platform Defaults
          </TabButton>
        ) : null}
      </div>

      {loading || !data ? (
        <Skeleton className="h-64" />
      ) : tab === TAB_RULES ? (
        <div className="space-y-4" data-testid="ai-rules-tab-panel-rules">
          <MasterSwitchCard
            masterEnabled={data.master_ai_send_live_comms}
            lastUpdatedByName={data.last_updated_by_name}
            lastUpdatedAt={data.last_updated_at}
            lastUpdateReason={data.last_update_reason}
            isSuper={isSuper}
            onFlipped={loadTenant}
          />
          <ToneVoiceCard
            value={data.rules?.tone_voice}
            overrideMap={data.override_map}
            platformValue={platformFallback("tone_voice")}
            onSaved={loadTenant}
            onReset={loadTenant}
          />
          <AutoActionAllowlistCard
            value={data.rules?.auto_action_allowlist}
            overrideMap={data.override_map}
            platformValue={platformFallback("auto_action_allowlist")}
            actionInventory={data.action_inventory}
            onSaved={loadTenant}
            onReset={loadTenant}
          />
          <EmployeeEnableDisableCard
            value={data.rules?.employee_enable_disable}
            overrideMap={data.override_map}
            employeeKeys={data.employee_keys}
            onSaved={loadTenant}
            onReset={loadTenant}
          />
          <WorkingHoursCard
            value={data.rules?.working_hours}
            overrideMap={data.override_map}
            platformValue={platformFallback("working_hours")}
            onSaved={loadTenant}
            onReset={loadTenant}
          />
          <EscalationRulesCard
            value={data.rules?.escalation_rules}
            overrideMap={data.override_map}
            platformValue={platformFallback("escalation_rules")}
            onSaved={loadTenant}
            onReset={loadTenant}
          />
        </div>
      ) : tab === TAB_REVISIONS ? (
        <RevisionsTab onReverted={loadTenant} />
      ) : tab === TAB_PLATFORM ? (
        <PlatformDefaultsTab isSuper={isSuper} />
      ) : null}
    </div>
  );
}

function TabButton({ active, onClick, testid, children }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className="text-sm font-semibold px-4 py-2 rounded-t-lg transition-colors"
      style={{
        color: active ? "#0F172A" : "#64748B",
        borderBottom: active ? "2px solid #0F172A" : "2px solid transparent",
        marginBottom: -1,
      }}
      data-testid={testid}
    >
      {children}
    </button>
  );
}
