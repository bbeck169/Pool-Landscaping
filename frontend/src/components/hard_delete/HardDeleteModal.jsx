/**
 * HARD-DELETE · HD-B · Feb-2026 — shared "Move to Trash" modal.
 *
 * Sits on top of the HD-A backend surface. Every one of the five
 * entity detail pages mounts this component; each supplies its own
 * ``entityType`` (`customer`, `job`, `quote` for both invoice +
 * estimate, `service_report`) and the target `entityId`. The
 * component handles:
 *
 *   1. Loading the cascade preview via
 *      `POST /api/hard-delete/{entity_type}/{id}/preview-cascade`.
 *   2. Rendering child counts + external-ref warnings.
 *   3. An 8-char-min reason gate — the Confirm button is disabled
 *      until the operator has typed at least eight characters.
 *   4. Firing the actual soft-delete when the operator confirms
 *      and calling the parent-supplied ``onSuccess`` / ``onBlocked``
 *      handlers.
 *
 * Uses the ui-kit ``Button`` (danger variant) + ``Modal`` + toast
 * primitives already shipped in the codebase. No new visual
 * language introduced.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Trash2, AlertTriangle, Loader } from "lucide-react";

import { Button, Modal, TextInput } from "@/components/ui-kit";
import { api } from "@/api";

const REASON_MIN = 8;

const CHILD_LABELS = {
  jobs: "job",
  quotes: "estimate/invoice",
  service_reports: "service report",
  files: "attachment",
  photos: "photo",
};

const ENTITY_LABELS = {
  customer: "customer",
  job: "job",
  quote: "estimate/invoice",
  service_report: "service report",
  file: "attachment",
};

function pluralize(n, singular) {
  if (n === 1) return `1 ${singular}`;
  return `${n} ${singular}s`;
}

function renderChildLine(collection, n) {
  const label = CHILD_LABELS[collection] || collection;
  return pluralize(n, label);
}

/**
 * @param {object} props
 * @param {boolean} props.open — modal visibility flag.
 * @param {string}  props.entityType — HD-A entity type slug.
 * @param {string}  props.entityId
 * @param {string=} props.entityLabel — friendly display (e.g. the customer's name).
 * @param {function} props.onClose — dismiss handler.
 * @param {function=} props.onSuccess — invoked on 200 soft-delete
 *   with the response body. Parent typically navigates away here.
 * @param {function=} props.onBlocked — invoked when the backend
 *   returns 409 blocked_external_reference. Parent SHOULD NOT
 *   navigate away.
 * @param {string=} props.testidPrefix — prefix for data-testids so
 *   multiple modals coexist on the same page tree.
 */
export default function HardDeleteModal({
  open,
  entityType,
  entityId,
  entityLabel,
  onClose,
  onSuccess,
  onBlocked,
  testidPrefix = "hard-delete",
}) {
  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) {
      setPreview(null);
      setPreviewError(null);
      setPreviewLoading(false);
      setReason("");
      setBusy(false);
      return;
    }
    let alive = true;
    setPreviewLoading(true);
    setPreviewError(null);
    api
      .post(`/hard-delete/${entityType}/${entityId}/preview-cascade`, null)
      .then((res) => {
        if (!alive) return;
        setPreview(res);
      })
      .catch((e) => {
        if (!alive) return;
        setPreviewError(e?.message || "Failed to load cascade preview");
      })
      .finally(() => {
        if (!alive) return;
        setPreviewLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open, entityType, entityId]);

  const reasonOk = reason.trim().length >= REASON_MIN;
  const externalRefs = preview?.external_refs || [];
  const hasExternalRefs = externalRefs.length > 0;

  const childRows = useMemo(() => {
    const counts = preview?.child_counts || {};
    return Object.entries(counts)
      .filter(([, n]) => n > 0)
      .map(([coll, n]) => ({ coll, n, line: renderChildLine(coll, n) }));
  }, [preview]);

  const confirm = useCallback(async () => {
    if (!reasonOk || busy) return;
    setBusy(true);
    try {
      const res = await api.post(
        `/hard-delete/${entityType}/${entityId}/soft`,
        { reason: reason.trim() }
      );
      toast.success(
        `Moved to Trash. Recover from /admin/trash for 30 days.`
      );
      if (onSuccess) onSuccess(res);
    } catch (e) {
      const detail = e?.data?.detail;
      const isDict = detail && typeof detail === "object";
      const isBlocked =
        e?.status === 409 &&
        isDict &&
        detail.error_code === "blocked_external_reference";
      if (isBlocked) {
        toast.error(
          `Cannot delete — this ${ENTITY_LABELS[entityType] || entityType} ` +
            `has a paid invoice on file. Refund or void it in Stripe first.`
        );
        if (onBlocked) onBlocked(detail);
      } else {
        toast.error(`Delete failed: ${e?.message || "unknown error"}`);
      }
    } finally {
      setBusy(false);
    }
  }, [
    reasonOk,
    busy,
    entityType,
    entityId,
    reason,
    onSuccess,
    onBlocked,
  ]);

  if (!open) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      testid={`${testidPrefix}-modal`}
      title={`Move ${ENTITY_LABELS[entityType] || entityType} to Trash`}
      footer={
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            onClick={onClose}
            testid={`${testidPrefix}-cancel`}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={confirm}
            disabled={!reasonOk || busy || previewLoading}
            testid={`${testidPrefix}-confirm`}
          >
            <Trash2 size={14} />
            {busy ? "Moving…" : "Move to Trash"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-sm" data-testid={`${testidPrefix}-body`}>
        <p>
          {entityLabel ? (
            <>
              <strong>{entityLabel}</strong> will be moved to the Trash.{" "}
            </>
          ) : (
            "This item will be moved to the Trash. "
          )}
          You can restore it from{" "}
          <code>/admin/trash</code> for 30 days before automatic purge.
        </p>

        {previewLoading ? (
          <div
            className="flex items-center gap-2 text-xs opacity-70"
            data-testid={`${testidPrefix}-preview-loading`}
          >
            <Loader size={12} className="animate-spin" /> Loading cascade
            preview…
          </div>
        ) : null}

        {previewError ? (
          <div
            className="rounded-md p-3"
            style={{
              background: "#FEF3C7",
              color: "#92400E",
              border: "1px solid #FDE68A",
            }}
            data-testid={`${testidPrefix}-preview-error`}
          >
            {previewError}
          </div>
        ) : null}

        {preview && childRows.length > 0 ? (
          <div
            className="rounded-md p-3"
            style={{
              background: "#FEF2F2",
              color: "#7F1D1D",
              border: "1px solid #FECACA",
            }}
            data-testid={`${testidPrefix}-cascade-summary`}
          >
            <div className="font-semibold mb-1">This will also delete:</div>
            <ul className="list-disc pl-5">
              {childRows.map((r) => (
                <li key={r.coll} data-testid={`${testidPrefix}-child-${r.coll}`}>
                  {r.line}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {preview && childRows.length === 0 && !previewError ? (
          <div
            className="text-xs opacity-70"
            data-testid={`${testidPrefix}-cascade-empty`}
          >
            No children — this action only affects the {ENTITY_LABELS[entityType] || entityType}.
          </div>
        ) : null}

        {hasExternalRefs ? (
          <div
            className="rounded-md p-3 flex gap-2"
            style={{
              background: "#FEF3C7",
              color: "#92400E",
              border: "1px solid #FDE68A",
            }}
            data-testid={`${testidPrefix}-external-ref-warning`}
          >
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold">
                External payment reference found
              </div>
              <div className="text-xs">
                {externalRefs.length} invoice(s) carry a Stripe
                <code>payment_intent_id</code>. Soft-delete is allowed, but
                the final purge will be blocked until you refund or void
                the charge in Stripe.
              </div>
            </div>
          </div>
        ) : null}

        <div>
          <TextInput
            label={`REASON (${REASON_MIN}-char min · required)`}
            testid={`${testidPrefix}-reason`}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Duplicate account, GDPR request, test data cleanup"
          />
          <div
            className="text-xs mt-1"
            style={{ color: reasonOk ? "#059669" : "#92400E" }}
            data-testid={`${testidPrefix}-reason-hint`}
          >
            {reasonOk
              ? `${reason.trim().length} chars — good.`
              : `Need ${REASON_MIN - reason.trim().length} more character(s).`}
          </div>
        </div>
      </div>
    </Modal>
  );
}
