import React, { useState } from "react";
import { api } from "@/api";
import { colors } from "@/theme";
import { Modal, Button } from "@/components/ui-kit";
import { usePermissions } from "@/hooks/usePermissions";

/**
 * Phase 56.2 — Customer activation control.
 *
 * Renders a status pill (green "Active" / gray "Inactive") next to the
 * customer name. For admin / super_admin the pill is paired with an
 * inline toggle switch that flips `is_active` via the shared
 * `PATCH /customers/{id}/activation` endpoint. Non-admin roles see the
 * pill only (read-only visual state).
 *
 * The toggle:
 *   • Optimistically flips the local `is_active` while the request is
 *     in flight, and reverts on error.
 *   • Confirms via a Radix-style modal before mutating:
 *       - active → inactive : destructive tone, mentions job cascade
 *       - inactive → active : neutral tone
 *   • Reuses the Phase 34f cascade on the backend (auto-cancel future
 *     scheduled jobs). No duplicate cascade logic here.
 *
 *   testID: `customer-active-toggle`
 */
export function ActivationControl({ customer, onOptimisticFlip, onSuccess, onError }) {
  const { role, effectiveRole } = usePermissions();
  const canEdit =
    role === "admin" || role === "super_admin" ||
    effectiveRole === "admin" || effectiveRole === "super_admin";
  // Missing/legacy field ⇒ active per Phase 34f semantics.
  const isActive = customer?.is_active !== false;
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const targetLabel = isActive ? "inactive" : "active";
  const nextActive = !isActive;

  const commit = async () => {
    setBusy(true);
    // Optimistic flip.
    onOptimisticFlip?.(nextActive);
    try {
      const updated = await api.patch(`/customers/${customer.id}/activation`, {
        is_active: nextActive,
      });
      onSuccess?.(updated);
      setConfirmOpen(false);
    } catch (e) {
      // Revert.
      onOptimisticFlip?.(isActive);
      onError?.(e.message || "Failed to update customer status");
    } finally {
      setBusy(false);
    }
  };

  const pillStyle = isActive
    ? { backgroundColor: "#DCFCE7", color: "#166534", border: "1px solid #86EFAC" }
    : { backgroundColor: "#E5E7EB", color: "#4B5563", border: "1px solid #9CA3AF" };

  return (
    <>
      <span
        className="inline-flex items-center gap-2 pl-2.5 pr-1 py-1 rounded-full text-xs font-bold uppercase tracking-wider"
        style={pillStyle}
        data-testid="customer-status-pill"
      >
        {isActive ? "Active" : "Inactive"}
        {canEdit ? (
          <button
            type="button"
            role="switch"
            aria-checked={isActive}
            aria-label={`Mark ${customer.name} ${targetLabel}`}
            onClick={() => setConfirmOpen(true)}
            disabled={busy}
            className="relative inline-flex items-center rounded-full transition"
            style={{
              width: 34,
              height: 18,
              backgroundColor: isActive ? "#16A34A" : "#9CA3AF",
              border: "1px solid rgba(0,0,0,0.1)",
              cursor: busy ? "wait" : "pointer",
              opacity: busy ? 0.6 : 1,
            }}
            data-testid="customer-active-toggle"
          >
            <span
              className="absolute rounded-full bg-white"
              style={{
                width: 12,
                height: 12,
                top: 2,
                left: isActive ? 19 : 3,
                transition: "left 120ms ease-out",
                boxShadow: "0 1px 2px rgba(0,0,0,0.25)",
              }}
            />
          </button>
        ) : null}
      </span>

      <Modal
        open={confirmOpen}
        onClose={() => (busy ? null : setConfirmOpen(false))}
        title={isActive ? "Mark customer inactive?" : "Reactivate customer?"}
        testid="customer-activation-confirm"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button
              variant={isActive ? "danger" : "primary"}
              onClick={commit}
              disabled={busy}
              testid="customer-activation-confirm-submit"
            >
              {busy ? "Working…" : isActive ? "Mark inactive" : "Reactivate"}
            </Button>
          </>
        }
      >
        <p className="text-sm" style={{ color: colors.onSurfaceSecondary }}>
          {isActive ? (
            <>
              Marking <strong>{customer.name}</strong> inactive will auto-cancel their
              scheduled jobs. Continue?
            </>
          ) : (
            <>
              Reactivate <strong>{customer.name}</strong>? Their jobs will need to be
              re-scheduled manually.
            </>
          )}
        </p>
      </Modal>
    </>
  );
}

export default ActivationControl;
