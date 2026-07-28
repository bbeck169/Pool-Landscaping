/**
 * Phase F2b · Feb 2026 — Invoice/Estimate Attachments (web).
 *
 * Shared attachments strip for both the invoice branch and estimate
 * branch of the QuoteInvoiceDetail page.  Uses the F0-native ``files``
 * collection:
 *   purpose             = "invoice_attachment"
 *   linked_entity_type  = "invoice"          (uniform for invoices +
 *                                              estimates — they share
 *                                              the underlying ``quotes``
 *                                              collection)
 *   linked_entity_id    = <doc.id>
 *
 * Access control:
 *   Upload    — admin / super_admin / manager (customer + tech: hidden)
 *   Delete    — uploader OR admin/super_admin (F0 backend gate; we
 *                 always show the button for allowed roles and let the
 *                 backend surface a 403 if the caller isn't allowed).
 *   Customer  — read-only (renders the FileList without FileUpload).
 */
import React, { useCallback, useState } from "react";
import { Paperclip } from "lucide-react";
import { FileUpload } from "@/components/files/FileUpload";
import { FileList } from "@/components/files/FileList";

const PURPOSE = "invoice_attachment";
const ACCEPT = "image/*,application/pdf";

/** Exported for Vitest — decides who can upload attachments. */
export function canUploadInvoiceAttachment(user) {
  const role = String(user?.role || "").toLowerCase();
  return role === "admin" || role === "super_admin" || role === "manager";
}

export function InvoiceAttachments({ docId, isInvoice, user, onCountChange }) {
  const [nonce, setNonce] = useState(0);
  const [count, setCount] = useState(null);

  const canUpload = canUploadInvoiceAttachment(user);
  const canDelete = canUpload;
  const noun = isInvoice ? "invoice" : "estimate";

  const onUploaded = useCallback(() => setNonce((n) => n + 1), []);
  const onListChange = useCallback((items) => {
    const c = (items || []).length;
    setCount(c);
    onCountChange?.(c);
  }, [onCountChange]);

  if (!docId) return null;

  return (
    <div
      className="rounded-2xl p-5 mb-4"
      style={{
        backgroundColor: "var(--surface, #FFFFFF)",
        border: "1px solid var(--border, #E4E4E7)",
      }}
      data-testid="doc-attachments-card"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Paperclip size={14} style={{ color: "var(--muted, #71717A)" }} />
          <div
            className="text-xs uppercase font-semibold tracking-wide"
            style={{ color: "var(--muted, #71717A)" }}
          >
            Attachments {count !== null ? `· ${count}` : ""}
          </div>
        </div>
        <div
          className="text-xs"
          style={{ color: "var(--muted, #71717A)" }}
          data-testid="doc-attachments-hint"
        >
          PDFs and images customers can view alongside this {noun}
        </div>
      </div>
      {canUpload ? (
        <div className="mb-3">
          <FileUpload
            purpose={PURPOSE}
            linkedEntityType="invoice"
            linkedEntityId={docId}
            accept={ACCEPT}
            multiple
            maxFiles={12}
            onUploaded={onUploaded}
            buttonLabel="Attach PDFs or images"
          />
        </div>
      ) : null}
      <FileList
        key={nonce}
        linkedEntityType="invoice"
        linkedEntityId={docId}
        purpose={PURPOSE}
        canDelete={canDelete}
        onChange={onListChange}
        emptyLabel={canUpload
          ? "No attachments yet — drop PDFs or images above."
          : "No attachments yet."}
      />
    </div>
  );
}

export default InvoiceAttachments;
