/**
 * Feb-2026 · Ticket γ · CombinedCategoryPopoverBadge
 *
 * Clickable wrapper around the shipped ``<CombinedCategoryBadge>``
 * (``components/customers/CombinedCategoryBadge.jsx``) that opens
 * an in-place popover listing every property with its label +
 * current service category and the SHARED chip-group selector so
 * the operator can edit any row without leaving the customer
 * profile.
 *
 * Architecture guardrails (operator-locked):
 *   - Does NOT reintroduce a customer-level writable toggle.
 *     The badge itself is still derived from the property-level
 *     categories; this component only adds a click-affordance that
 *     opens an editor over the per-property write path.
 *   - Reuses the shipped ``PATCH /properties/{pid}`` endpoint with
 *     body ``{service_category: next | null}`` (same contract as
 *     the Properties tab).  No new write endpoints.
 *   - Reuses the shared ``<PropertyCategorySelector>`` chip-group
 *     primitive so visual language + accessibility semantics stay
 *     byte-identical with the Properties tab.
 *   - Role gate mirrors the BE ``require_admin`` list
 *     (admin / super_admin / owner).  Lower roles get a static
 *     non-clickable chip identical to the pre-γ experience.
 *   - Esc / outside-click dismiss, aria-expanded on the trigger,
 *     role="dialog" on the popover, focus returns to the trigger
 *     on close.
 *   - Optimistic row updates with rollback on error toast.  After
 *     any successful save, calls ``onRefreshCustomer()`` so the
 *     parent re-fetches ``properties`` and the badge label re-
 *     derives naturally through the shipped ``_computeCombinedCategory``
 *     rule (All-Pool → "Pool", All-Landscaping → "Landscaping",
 *     any mix → canonical joined label, zero/all-null → "—").
 */
import React from "react";

import { api } from "@/api";
import { colors } from "@/theme";
import { CombinedCategoryBadge } from "@/components/customers/CombinedCategoryBadge";
import PropertyCategorySelector from "@/components/customers/PropertyCategorySelector";


const _EDIT_ROLES = new Set(["admin", "super_admin", "owner"]);


function _formatAddress(addr) {
  if (!addr) return "";
  const parts = [addr.line1, addr.city, addr.state,
                   addr.postal_code].filter(Boolean);
  return parts.join(", ");
}


export default function CombinedCategoryPopoverBadge({
  properties, userRole, onToast, onRefreshCustomer,
}) {
  const canEdit = _EDIT_ROLES.has((userRole || "").toLowerCase());
  const [open, setOpen] = React.useState(false);
  // Local optimistic shadow of ``properties`` so a chip click
  // reflects immediately without waiting for the parent refetch.
  const [local, setLocal] = React.useState(properties || []);
  const [pendingId, setPendingId] = React.useState(null);
  const triggerRef = React.useRef(null);
  const popoverRef = React.useRef(null);

  // Sync local shadow whenever the parent-provided ``properties``
  // identity changes (parent refetch after save).  Comparing by
  // reference is sufficient — ``PropertiesTab`` always builds a
  // fresh array on load.
  React.useEffect(() => { setLocal(properties || []); }, [properties]);

  // Esc + outside-click dismiss.
  React.useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    const onClick = (e) => {
      if (popoverRef.current?.contains(e.target)) return;
      if (triggerRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const onPick = React.useCallback(async (pid, nextCat) => {
    const prevRow = local.find((r) => r.id === pid);
    const prevCat = prevRow?.service_category || null;
    const payloadCat = nextCat === prevCat ? null : nextCat;
    setPendingId(pid);
    setLocal((rs) => rs.map((r) =>
      r.id === pid ? { ...r, service_category: payloadCat } : r,
    ));
    try {
      const updated = await api.patch(
        `/properties/${pid}`, { service_category: payloadCat },
      );
      setLocal((rs) => rs.map((r) =>
        r.id === pid ? { ...r, ...updated } : r,
      ));
      onToast?.({
        tone: "success",
        message: payloadCat
          ? `Property category set to ${payloadCat}`
          : "Property category cleared",
      });
      onRefreshCustomer?.();
    } catch (e) {
      setLocal((rs) => rs.map((r) =>
        r.id === pid ? { ...r, service_category: prevCat } : r,
      ));
      onToast?.({ tone: "error",
                     message: `Category update failed: ${e?.message || e}` });
    } finally {
      setPendingId(null);
    }
  }, [local, onToast, onRefreshCustomer]);

  // Non-privileged roles see the pre-γ static chip.  No trigger
  // button, no popover.  Mirrors the BE ``require_admin`` gate so
  // the FE never surfaces an affordance the user cannot complete.
  if (!canEdit) {
    return <CombinedCategoryBadge properties={local} />;
  }

  const activeRows = (local || []).filter((p) => p?.active !== false);

  return (
    <span className="relative inline-flex">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open ? "true" : "false"}
        aria-controls="customer-combined-category-popover"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center rounded-full p-0 border-none bg-transparent cursor-pointer"
        title="Edit service category per property"
        data-testid="customer-combined-category-badge-trigger"
      >
        <CombinedCategoryBadge properties={local} />
      </button>
      {open ? (
        <div
          ref={popoverRef}
          id="customer-combined-category-popover"
          role="dialog"
          aria-label="Edit property service categories"
          className="absolute left-0 top-full mt-2 z-50 rounded-xl shadow-xl p-3 min-w-[320px]"
          style={{
            backgroundColor: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="customer-combined-category-popover"
        >
          <div
            className="text-xs font-semibold uppercase tracking-wider mb-2"
            style={{ color: colors.onSurfaceSecondary }}
          >
            Service category by property
          </div>
          {activeRows.length === 0 ? (
            <div
              className="text-xs"
              style={{ color: colors.onSurfaceSecondary }}
              data-testid="customer-combined-category-popover-empty"
            >
              No active properties on this customer.
            </div>
          ) : (
            <ul className="flex flex-col gap-2">
              {activeRows.map((p) => (
                <li
                  key={p.id}
                  className="flex items-center justify-between gap-3"
                  data-testid={`customer-category-popover-row-${p.id}`}
                >
                  <div className="min-w-0 flex-1">
                    <div
                      className="text-sm font-medium truncate"
                      style={{ color: colors.onSurface }}
                      data-testid={`customer-category-popover-label-${p.id}`}
                    >
                      {p.label || "Property"}
                    </div>
                    <div
                      className="text-[11px] truncate"
                      style={{ color: colors.onSurfaceSecondary }}
                    >
                      {_formatAddress(p.address) || "—"}
                    </div>
                  </div>
                  <PropertyCategorySelector
                    propertyId={p.id}
                    current={p.service_category || null}
                    onPick={(v) => onPick(p.id, v)}
                    disabled={pendingId === p.id}
                  />
                </li>
              ))}
            </ul>
          )}
          <div
            className="text-[11px] mt-3 pt-2 border-t"
            style={{
              color: colors.onSurfaceSecondary,
              borderColor: colors.border,
            }}
          >
            Deep-edit all property fields in the Properties tab below.
          </div>
        </div>
      ) : null}
    </span>
  );
}
