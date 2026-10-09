// Phase 7B · Feb-2026 — Preview dispatcher.
//
// Routes the current ``formType`` to the matching preview mock
// defined in ``FormPreviews.jsx``.  Zero knowledge of the drag or
// style editing surfaces — just reads ``fields`` and renders.
import React from "react";
import {
  ServiceReportPreview,
  InvoiceEstimatePreview,
  CadOverlayPreview,
} from "./FormPreviews";
import { colors } from "@/theme";


export default function PreviewPanel({ formType, fields }) {
  const safeFields = Array.isArray(fields) ? fields : [];

  let body = null;
  if (formType === "estimate" || formType === "invoice") {
    body = <InvoiceEstimatePreview fields={safeFields} formType={formType} />;
  } else if (formType === "cad_overlay") {
    body = <CadOverlayPreview fields={safeFields} />;
  } else {
    // pool / landscape service reports + the three job_checklist_*
    // variants all render as a lightweight form-card mock.
    body = <ServiceReportPreview fields={safeFields} />;
  }

  return (
    <section
      className="rounded-lg border bg-white p-4"
      data-testid="form-editor-preview-panel"
    >
      <header className="flex items-center justify-between pb-2 mb-2 border-b">
        <h3 className="text-sm font-semibold uppercase tracking-wide"
            style={{ color: colors.onSurfaceSecondary || "#52525B" }}>
          Live Preview
        </h3>
        <code className="text-xs text-slate-500"
              data-testid="form-editor-preview-type">
          {formType || "—"}
        </code>
      </header>
      {body}
    </section>
  );
}
