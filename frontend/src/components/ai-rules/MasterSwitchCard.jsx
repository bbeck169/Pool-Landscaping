/**
 * MTH-B · Feb-2026 — Master Switch card.
 *
 * "Live AI Comms — Master Switch" on the Rules tab.  Super_admin
 * can flip; admin sees the switch state but the toggle is disabled
 * with a tooltip.
 *
 * The backend enforces super-only on
 * ``PUT /api/tenant-ai-rules/master-switch`` — this card mirrors
 * the gate client-side so the toggle short-circuits before ever
 * hitting the network for a non-super user.
 */
import React, { useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, ShieldOff, Lock } from "lucide-react";
import { api } from "@/api";
import { Button } from "@/components/ui-kit";
import RulesReasonModal from "./RulesReasonModal";

export default function MasterSwitchCard({
  masterEnabled,
  lastUpdatedByName,
  lastUpdatedAt,
  lastUpdateReason,
  isSuper,
  onFlipped,
}) {
  const [modalOpen, setModalOpen] = useState(false);
  const target = !masterEnabled;

  const openModal = () => {
    if (!isSuper) return;
    setModalOpen(true);
  };

  const confirm = async (reason) => {
    try {
      const res = await api.put("/tenant-ai-rules/master-switch", {
        enabled: target,
        reason,
      });
      toast.success(
        target
          ? "Live AI comms ENABLED — every authorized employee can now send."
          : "Live AI comms disabled — sandbox mode.",
      );
      setModalOpen(false);
      if (onFlipped) onFlipped(res);
    } catch (e) {
      const detail = e?.data?.detail;
      const msg =
        (detail && typeof detail === "object" && detail.message) ||
        e?.message ||
        "Flip failed";
      toast.error(`Master switch flip failed: ${msg}`);
    }
  };

  return (
    <div
      className="rounded-2xl p-5 border"
      style={{
        background: "#fff",
        borderColor: masterEnabled ? "#BBF7D0" : "#FECACA",
      }}
      data-testid="ai-rules-master-switch-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-2xl flex items-center justify-center"
            style={{
              background: masterEnabled ? "#DCFCE7" : "#FEE2E2",
              color: masterEnabled ? "#166534" : "#991B1B",
            }}
          >
            {masterEnabled ? (
              <ShieldCheck size={22} />
            ) : (
              <ShieldOff size={22} />
            )}
          </div>
          <div>
            <div
              className="text-base font-bold"
              data-testid="ai-rules-master-switch-title"
            >
              Live AI Comms — Master Switch
            </div>
            <div
              className="text-xs opacity-70 mt-0.5"
              data-testid="ai-rules-master-switch-state-label"
            >
              {masterEnabled
                ? "LIVE — authorized AI employees will send live customer comms."
                : "SANDBOX — every outbound is held for admin approval."}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span
            className="text-xs font-bold px-3 py-1.5 rounded-full"
            style={{
              background: masterEnabled ? "#166534" : "#991B1B",
              color: "#fff",
            }}
            data-testid="ai-rules-master-switch-pill"
          >
            {masterEnabled ? "LIVE" : "SANDBOX"}
          </span>
          {isSuper ? (
            <Button
              variant={masterEnabled ? "danger" : "primary"}
              onClick={openModal}
              testid="ai-rules-master-switch-toggle"
            >
              {masterEnabled ? "Turn OFF" : "Turn ON"}
            </Button>
          ) : (
            <button
              type="button"
              disabled
              title="Requires super-admin"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold opacity-60 cursor-not-allowed"
              style={{
                background: "#F1F5F9",
                color: "#64748B",
                border: "1px solid #E2E8F0",
              }}
              data-testid="ai-rules-master-switch-toggle-disabled"
            >
              <Lock size={14} />
              Super-admin only
            </button>
          )}
        </div>
      </div>

      {lastUpdatedAt || lastUpdatedByName ? (
        <div
          className="mt-3 text-xs opacity-60"
          data-testid="ai-rules-master-switch-audit"
        >
          Last change:{" "}
          {lastUpdatedByName ? <strong>{lastUpdatedByName}</strong> : "unknown"}
          {lastUpdatedAt ? ` · ${lastUpdatedAt}` : ""}
          {lastUpdateReason ? ` · reason: ${lastUpdateReason}` : ""}
        </div>
      ) : null}

      <RulesReasonModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={
          target
            ? "Enable Live AI Comms?"
            : "Disable Live AI Comms (return to Sandbox)?"
        }
        description={
          target
            ? "Every authorized AI employee will begin sending live customer emails, SMS, and voice comms as soon as this flips."
            : "Every outbound AI communication will be held for admin approval until this is re-enabled."
        }
        warning={
          target ? (
            <>
              <div className="font-semibold">
                Confirm every employee's authorization gate has been reviewed
              </div>
              <div className="text-xs">
                Only enable if every employee's{" "}
                <code>authorized_for_public_use</code> gate has been reviewed
                by an owner. This bypasses the sandbox for the entire tenant.
              </div>
            </>
          ) : null
        }
        confirmLabel={target ? "Enable Live Comms" : "Return to Sandbox"}
        confirmVariant={target ? "danger" : "primary"}
        onConfirm={confirm}
        testidPrefix="ai-rules-master-switch-reason"
        placeholder={
          target
            ? "e.g. Owner review complete — enabling live comms for pilot"
            : "e.g. Pausing live comms during Q1 audit"
        }
      />
    </div>
  );
}
