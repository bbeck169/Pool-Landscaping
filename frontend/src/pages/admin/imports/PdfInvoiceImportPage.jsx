/**
 * Task B · Feb-2026 — PDF Invoice Importer admin page (scaffold).
 *
 * Route: ``/admin/imports/pdf-invoice`` (admin+ only via
 * ``<AdminOnly>`` in App.js).
 *
 * Backend endpoints (see recon halt report, §A):
 *
 *   POST /api/imports/pdf-invoice                       — kickoff
 *   GET  /api/imports/pdf-invoice/{batch_id}            — poll
 *   GET  /api/imports/pdf-invoice/{batch_id}/duplicates — pre-flight
 *   POST /api/imports/pdf-invoice/{batch_id}/commit     — commit
 *   POST /api/imports/pdf-invoice/{batch_id}/rollback   — rollback
 *
 * Backend caps (frozen in Phase 2 ruling E.1 / E.2):
 *
 *   * 10 MB per PDF (415 pdf_only / 413 pdf_too_large)
 *   * 3 concurrent in-flight per tenant (429 rate limit)
 *
 * Client-side caps (frozen in Phase 2 ruling E.1 / E.2):
 *
 *   * 20 PDFs max per selection (toast.error above cap).
 *   * Soft-warn at 10 PDFs (toast.warning).
 *   * 10 MB client-side reject before POST (belt-and-suspenders).
 *   * Concurrency pool of 2 uploads (leave 1 slot for co-admins).
 *
 * This module ships in phased commits — Phase 2 Commit 1 delivers
 * only the SCAFFOLD (page shell, idle state, route registration,
 * sidebar entry).  Subsequent commits wire the upload flow, poll
 * loop, preview table, and commit/rollback actions.
 *
 * Idle state contract (this commit):
 *
 *   * Root ``<div data-testid="pdf-invoice-import-page">``.
 *   * ``PageHeader`` title 'PDF Invoice Import' + short subtitle.
 *   * A single upload zone with a hidden native
 *     ``<input type="file" multiple accept="application/pdf">``
 *     triggered by a 'Choose PDF(s)' button
 *     (``data-testid="pdf-import-choose-files-btn"``).
 *   * A helper strip below the button listing the caps
 *     (max 20 files / 10 MB each / admin only).
 *   * NO API calls, NO batch state, NO polling.  The
 *     ``onChange`` handler is a stub that will be wired in
 *     Commit 2.
 */
import React, { useRef } from "react";
import { UploadCloud, FileText, ShieldCheck } from "lucide-react";
import { PageHeader, Button } from "@/components/ui-kit";
import { colors } from "@/theme";


// Frozen client-side caps — see module doc for rulings.
export const MAX_FILES_PER_BATCH = 20;
export const MAX_BYTES_PER_FILE = 10 * 1024 * 1024;   // 10 MB
export const SOFT_WARN_FILES = 10;
export const CONCURRENCY_POOL = 2;


export default function PdfInvoiceImportPage() {
  const fileInputRef = useRef(null);

  const openFileDialog = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const onFilesSelected = (_event) => {
    // Placeholder — Commit 2 wires validation + POST fan-out.
    // Reset the input so re-selecting the same file re-fires
    // onChange once the flow is wired.
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div
      data-testid="pdf-invoice-import-page"
      className="mx-auto max-w-5xl px-4 py-6"
    >
      <PageHeader
        title="PDF Invoice Import"
        subtitle={
          "Upload one or more supplier PDFs and turn them into "
          + "draft invoices.  Preview the extracted rows, review "
          + "duplicates, then commit — or roll back within the same "
          + "batch.  Admin-only."
        }
      />

      {/* Idle upload zone.  Commit 2 replaces this with a full
          multi-file state machine driven by the same input. */}
      <div
        data-testid="pdf-import-idle-zone"
        className="mt-6 rounded-lg border-2 border-dashed p-10 text-center"
        style={{
          borderColor: colors.border,
          backgroundColor: colors.surfaceSecondary,
        }}
      >
        <UploadCloud
          size={48}
          className="mx-auto mb-3"
          style={{ color: colors.muted }}
        />
        <div
          className="text-sm mb-4"
          style={{ color: colors.onSurfaceSecondary }}
        >
          Drag PDFs here, or choose them from your computer.
        </div>
        <Button
          variant="primary"
          onClick={openFileDialog}
          testid="pdf-import-choose-files-btn"
        >
          Choose PDF(s)
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept="application/pdf"
          hidden
          onChange={onFilesSelected}
          data-testid="pdf-import-file-input"
        />
      </div>

      {/* Cap-summary strip — admins see the limits up front. */}
      <div
        data-testid="pdf-import-caps-strip"
        className="mt-4 flex flex-wrap items-center gap-4 text-xs"
        style={{ color: colors.muted }}
      >
        <span className="inline-flex items-center gap-1.5">
          <FileText size={14} />
          Max {MAX_FILES_PER_BATCH} PDFs per batch
        </span>
        <span className="inline-flex items-center gap-1.5">
          <UploadCloud size={14} />
          Max 10 MB per PDF
        </span>
        <span className="inline-flex items-center gap-1.5">
          <ShieldCheck size={14} />
          Admin-only
        </span>
      </div>
    </div>
  );
}
