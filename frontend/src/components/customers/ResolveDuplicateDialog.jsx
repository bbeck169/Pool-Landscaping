/**
 * Resolve-duplicate · Phase 1 · Feb-2026 — admin "resolve the
 * portal-invite email collision" dialog.
 *
 * Opens from the ``PortalInviteQuickAction`` card when the invite
 * POST returns ``409 error_code=email_bound_to_other_customer``.
 * Side-by-side comparison of the current customer vs the
 * conflicting customer, with two options:
 *
 *   • Option A — remove the email from the conflicting record
 *     (THIS PHASE). Admin must check the ack checkbox AND type
 *     the conflicting customer's name verbatim before the submit
 *     button is enabled.
 *   • Option B — merge both records (Phase 2). Rendered disabled
 *     with a "Coming soon" tooltip; no code path for the merge in
 *     this ship.
 *
 * The unbind call hits ``POST /api/customers/{conflict_cid}/
 * unbind-portal-email`` with ``{confirmation_name}`` body. On
 * success the dialog closes and ``onResolved(released_email)`` is
 * invoked so the caller can auto-retry the original invite.
 *
 * Styling + testid conventions match ``HardDeleteModal.jsx``.
 */
import React, { useCallback, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AlertTriangle, ExternalLink } from "lucide-react";

import { Button, Modal, TextInput } from "@/components/ui-kit";
import { api } from "@/api";
import { colors } from "@/theme";


function _collapseWs(s) {
  return (s || "").replace(/\s+/g, " ").trim().toLowerCase();
}


function Row({ label, value, testid }) {
  return (
    <div className="flex flex-col gap-0.5" data-testid={testid}>
      <div
        className="text-xs uppercase tracking-wide"
        style={{ color: colors.muted }}
      >
        {label}
      </div>
      <div
        className="text-sm break-words"
        style={{ color: colors.onSurface }}
      >
        {value || <span style={{ color: colors.muted }}>—</span>}
      </div>
    </div>
  );
}


function ProfileColumn({ title, customer, viewLinkTo, badges, testidPrefix }) {
  return (
    <div
      className="flex-1 rounded-xl p-3 space-y-3 min-w-0"
      style={{
        backgroundColor: colors.surfaceSecondary,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={`${testidPrefix}-column`}
    >
      <div className="flex items-center justify-between gap-2">
        <div
          className="text-xs font-bold uppercase"
          style={{ color: colors.muted }}
          data-testid={`${testidPrefix}-title`}
        >
          {title}
        </div>
        {viewLinkTo ? (
          <Link
            to={viewLinkTo}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs underline inline-flex items-center gap-1"
            style={{ color: colors.brand }}
            data-testid={`${testidPrefix}-view-full`}
          >
            View full profile <ExternalLink size={10} />
          </Link>
        ) : null}
      </div>
      <Row
        label="Name"
        value={customer.name}
        testid={`${testidPrefix}-name`}
      />
      <Row
        label="Email"
        value={customer.email}
        testid={`${testidPrefix}-email`}
      />
      <Row
        label="Phone"
        value={customer.phone}
        testid={`${testidPrefix}-phone`}
      />
      <Row
        label="Mailing address"
        value={customer.address}
        testid={`${testidPrefix}-address`}
      />
      <Row
        label="Created"
        value={customer.created_at}
        testid={`${testidPrefix}-created-at`}
      />
      {badges && badges.length > 0 ? (
        <div
          className="flex flex-wrap gap-1 pt-1"
          data-testid={`${testidPrefix}-badges`}
        >
          {badges.map((b) => (
            <span
              key={b.label}
              className="text-xs px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: b.bg || colors.brandTertiary,
                color: b.fg || colors.onBrandTertiary,
              }}
            >
              {b.label}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}


/**
 * @param {object} props
 * @param {boolean} props.open
 * @param {function} props.onClose
 * @param {object} props.currentCustomer — the invite target
 *   (id, name, email, phone, address, created_at).
 * @param {object} props.conflict — backend 409 conflict payload
 *   (customer_id, customer_name, email_bound_at,
 *   has_active_portal_session, has_portal_password_set).
 * @param {function=} props.onResolved — called with the released
 *   email on successful unbind so the parent can auto-retry.
 */
export default function ResolveDuplicateDialog({
  open,
  onClose,
  currentCustomer,
  conflict,
  onResolved,
}) {
  const [confirmChecked, setConfirmChecked] = useState(false);
  const [typedName, setTypedName] = useState("");
  const [busy, setBusy] = useState(false);

  const conflictName = conflict?.customer_name || "";
  const conflictCid = conflict?.customer_id || "";

  const nameMatches = useMemo(
    () =>
      _collapseWs(typedName).length > 0
      && _collapseWs(typedName) === _collapseWs(conflictName),
    [typedName, conflictName],
  );
  const canSubmit = confirmChecked && nameMatches && !busy;

  const reset = useCallback(() => {
    setConfirmChecked(false);
    setTypedName("");
    setBusy(false);
  }, []);

  const handleClose = useCallback(() => {
    if (busy) return;
    reset();
    onClose?.();
  }, [busy, reset, onClose]);

  const submit = useCallback(async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      const resp = await api.post(
        `/customers/${conflictCid}/unbind-portal-email`,
        { confirmation_name: typedName },
      );
      reset();
      onClose?.();
      // Fire-and-forget: parent decides what to do with the
      // released email (typically auto-retry the original invite).
      onResolved?.(resp?.released_email || null, resp);
    } catch (e) {
      const detail = e?.data?.detail;
      if (
        e?.status === 400
        && detail?.error_code === "confirmation_name_mismatch"
      ) {
        toast.error(
          "The typed name does not match. Type the conflicting "
          + "customer's name exactly as shown.",
        );
      } else if (e?.status === 403) {
        toast.error(
          "You need admin permission to unbind a portal email.",
        );
      } else if (e?.status === 404) {
        toast.error("Conflicting customer not found in this tenant.");
      } else {
        toast.error(e?.message || "Unbind failed. Please try again.");
      }
      setBusy(false);
    }
  }, [canSubmit, conflictCid, typedName, reset, onClose, onResolved]);

  if (!open) return null;

  const sessionBadges = [];
  if (conflict?.has_active_portal_session) {
    sessionBadges.push({
      label: "Has portal account",
      bg: "#FEF3C7",
      fg: "#92400E",
    });
  }
  if (conflict?.has_portal_password_set) {
    sessionBadges.push({
      label: "Password set",
      bg: "#DBEAFE",
      fg: "#1E40AF",
    });
  }
  if (!conflict?.has_portal_password_set) {
    sessionBadges.push({
      label: "No portal account",
      bg: colors.surfaceSecondary,
      fg: colors.muted,
    });
  }

  return (
    <Modal
      open={open}
      onClose={handleClose}
      testid="resolve-duplicate-modal"
      title="Resolve duplicate portal email"
      wide
      footer={
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            onClick={handleClose}
            disabled={busy}
            testid="resolve-duplicate-cancel"
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={submit}
            disabled={!canSubmit}
            testid="resolve-duplicate-unbind-submit"
            aria-disabled={!canSubmit}
          >
            {busy ? "Unbinding…" : "Unbind email"}
          </Button>
        </div>
      }
    >
      <div
        className="space-y-4 text-sm"
        data-testid="resolve-duplicate-body"
      >
        <div
          className="rounded-md p-3 flex gap-2"
          style={{
            backgroundColor: "#FEF3C7",
            color: "#92400E",
            border: "1px solid #FDE68A",
          }}
          data-testid="resolve-duplicate-intro"
        >
          <AlertTriangle size={16} className="shrink-0 mt-0.5" />
          <div>
            This email is already linked to another customer in this
            tenant. Review the records below and pick how to resolve.
          </div>
        </div>

        <div className="flex flex-col md:flex-row gap-3">
          <ProfileColumn
            title="Current customer (invite target)"
            customer={currentCustomer || {}}
            viewLinkTo={
              currentCustomer?.id
                ? `/customers/${currentCustomer.id}`
                : null
            }
            testidPrefix="resolve-duplicate-current"
          />
          <ProfileColumn
            title="Conflicting customer"
            customer={{
              name: conflictName,
              email: currentCustomer?.email || "",
              phone: conflict?.phone || "",
              address: conflict?.address || "",
              created_at: conflict?.email_bound_at || "",
            }}
            viewLinkTo={
              conflictCid ? `/customers/${conflictCid}` : null
            }
            badges={sessionBadges}
            testidPrefix="resolve-duplicate-conflict"
          />
        </div>

        {/* Option A — unbind email (Phase 1, functional) */}
        <div
          className="rounded-xl p-3 space-y-3"
          style={{
            border: `1px solid ${colors.border}`,
            backgroundColor: colors.surface,
          }}
          data-testid="resolve-duplicate-option-a"
        >
          <div
            className="text-sm font-bold"
            style={{ color: colors.onSurface }}
          >
            Option A · Remove email from the conflicting customer
          </div>
          <label
            className="flex items-start gap-2 cursor-pointer"
            data-testid="resolve-duplicate-ack-label"
          >
            <input
              type="checkbox"
              className="mt-0.5"
              checked={confirmChecked}
              onChange={(e) => setConfirmChecked(e.target.checked)}
              data-testid="resolve-duplicate-ack-checkbox"
              disabled={busy}
            />
            <span
              className="text-xs"
              style={{ color: colors.onSurface }}
            >
              I understand this will remove the email from
              {" "}<strong>{conflictName || "the conflicting record"}</strong>
              {" "}and (if applicable) log them out of the portal.
            </span>
          </label>
          <TextInput
            label={`Type the conflicting customer's name to confirm`}
            placeholder={conflictName}
            value={typedName}
            onChange={(e) => setTypedName(e.target.value)}
            testid="resolve-duplicate-name-input"
            disabled={busy}
          />
          <div
            className="text-xs"
            style={{
              color: nameMatches ? "#059669" : colors.muted,
            }}
            data-testid="resolve-duplicate-name-hint"
          >
            {nameMatches
              ? "Match confirmed."
              : "Case-insensitive; extra spaces ignored."}
          </div>
        </div>

        {/* Option B — merge records (Phase 2, DISABLED) */}
        <div
          className="rounded-xl p-3 space-y-1 opacity-60 cursor-not-allowed"
          style={{
            border: `1px dashed ${colors.border}`,
            backgroundColor: colors.surfaceSecondary,
          }}
          title="Coming soon — contact support for merges today."
          data-testid="resolve-duplicate-option-b"
        >
          <div
            className="text-sm font-bold flex items-center gap-2"
            style={{ color: colors.muted }}
          >
            Option B · Merge both records into one
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: colors.brandTertiary,
                color: colors.onBrandTertiary,
              }}
              data-testid="resolve-duplicate-option-b-coming-soon"
            >
              Coming soon
            </span>
          </div>
          <div
            className="text-xs"
            style={{ color: colors.muted }}
          >
            Contact support for merges today — the self-serve merge
            workflow ships in Phase 2.
          </div>
        </div>
      </div>
    </Modal>
  );
}
