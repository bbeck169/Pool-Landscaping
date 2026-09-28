/**
 * MTH-B · Feb-2026 — Platform Defaults tab (super_admin only).
 *
 * Renders the same 5 category editors as the tenant Rules tab,
 * but scoped to ``GET /api/platform-ai-rules`` +
 * ``PUT /api/platform-ai-rules/{category}``.  Non-super users get
 * the empty-state lock — the whole tab is hidden from the page
 * shell for admin users, so this fallback is only ever hit if a
 * super loses their role mid-session.
 *
 * The header warning banner surfaces a live tenant count fetched
 * from ``GET /api/tenants`` (best-effort — network / permission
 * failures fall back to a generic warning without the number).
 *
 * Category cards are re-used with ``endpointPrefix="/platform-ai-rules"``
 * so their PUT / reset URLs route to the platform surface.  The
 * platform surface has no ``/reset`` endpoints, so ``showReset``
 * is hard-off here.  Override diff panels are hidden because the
 * "override_map" concept is a tenant-vs-platform relationship
 * that has no meaning when editing the platform doc itself.
 */
import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, Lock } from "lucide-react";
import { api } from "@/api";
import { Skeleton, EmptyState } from "@/components/ui-kit";

import ToneVoiceCard from "./ToneVoiceCard";
import AutoActionAllowlistCard from "./AutoActionAllowlistCard";
import EmployeeEnableDisableCard from "./EmployeeEnableDisableCard";
import WorkingHoursCard from "./WorkingHoursCard";
import EscalationRulesCard from "./EscalationRulesCard";

/**
 * @param {object} props
 * @param {boolean} props.isSuper
 */
export default function PlatformDefaultsTab({ isSuper }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tenantCount, setTenantCount] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get("/platform-ai-rules");
      setData(res);
    } catch (e) {
      toast.error(
        `Load platform defaults failed: ${e?.data?.detail?.message || e?.message || "unknown"}`,
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isSuper) return;
    load();
    // Best-effort tenant count.
    api
      .get("/tenants")
      .then((res) => {
        if (Array.isArray(res)) setTenantCount(res.length);
        else if (Array.isArray(res?.items)) setTenantCount(res.items.length);
        else if (Array.isArray(res?.tenants)) setTenantCount(res.tenants.length);
      })
      .catch(() => {
        setTenantCount(null); // silent — banner falls back to generic copy.
      });
  }, [isSuper, load]);

  if (!isSuper) {
    return (
      <EmptyState
        icon={Lock}
        title="Platform Defaults requires super-admin"
        hint="Only super-admins can edit the platform-wide rule defaults."
      />
    );
  }

  if (loading || !data) {
    return <Skeleton className="h-64" />;
  }

  const PREFIX = "/platform-ai-rules";

  return (
    <div className="space-y-4" data-testid="ai-rules-platform-defaults-tab">
      <div
        className="rounded-lg p-3 flex gap-2"
        style={{
          background: "#FEE2E2",
          color: "#7F1D1D",
          border: "1px solid #FCA5A5",
        }}
        data-testid="ai-rules-platform-defaults-banner"
      >
        <AlertTriangle size={16} className="shrink-0 mt-0.5" />
        <div>
          <div className="text-sm font-bold">
            Editing platform defaults affects EVERY tenant
          </div>
          <div className="text-xs">
            {tenantCount != null ? (
              <>
                <strong data-testid="ai-rules-platform-defaults-tenant-count">
                  {tenantCount}
                </strong>{" "}
                tenant{tenantCount === 1 ? "" : "s"} currently rely on these
                defaults for any field they haven't explicitly overridden.
              </>
            ) : (
              <>
                Every tenant on the platform relies on these defaults for any
                field they haven't explicitly overridden.
              </>
            )}
          </div>
        </div>
      </div>

      <ToneVoiceCard
        value={data.rules?.tone_voice}
        overrideMap={null}
        platformValue={data.rules?.tone_voice}
        onSaved={load}
        endpointPrefix={PREFIX}
        showReset={false}
        showDiff={false}
      />
      <AutoActionAllowlistCard
        value={data.rules?.auto_action_allowlist}
        overrideMap={null}
        platformValue={data.rules?.auto_action_allowlist}
        actionInventory={data.action_inventory}
        employeeKeys={data.employee_keys}
        onSaved={load}
        endpointPrefix={PREFIX}
        showReset={false}
      />
      <EmployeeEnableDisableCard
        value={data.rules?.employee_enable_disable}
        overrideMap={null}
        employeeKeys={data.employee_keys}
        onSaved={load}
        endpointPrefix={PREFIX}
        showReset={false}
      />
      <WorkingHoursCard
        value={data.rules?.working_hours}
        overrideMap={null}
        platformValue={data.rules?.working_hours}
        onSaved={load}
        endpointPrefix={PREFIX}
        showReset={false}
        showDiff={false}
      />
      <EscalationRulesCard
        value={data.rules?.escalation_rules}
        overrideMap={null}
        platformValue={data.rules?.escalation_rules}
        onSaved={load}
        endpointPrefix={PREFIX}
        showReset={false}
        showDiff={false}
      />
    </div>
  );
}
