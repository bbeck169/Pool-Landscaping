// Phase 7B · Feb-2026 — Form Template Editor page.
//
// Consumes the Phase 7A ``/api/form-templates/*`` endpoints via the
// ``useFormTemplate`` hook.  Admin / super_admin / owner gated at
// the route level in ``App.js`` (``<AdminOnly>``) — this page
// trusts that guard.  The Phase 7A backend also enforces role on
// every mutating endpoint, so a stale manager session would see 403
// on save and (per the brief §7 defense-in-depth) fall into a
// read-only render — the component honors a ``readOnly`` prop for
// that path.
//
// Scope is deliberately narrow:
//   * Form type picker (dropdown)
//   * 3-column workspace: field list · detail panel · live preview
//   * Toolbar: Save · Discard · Version History
//   * Dirty guard on form_type switch + confirm on Discard
//
// NO wiring into the real service-report / estimate / invoice / CAD
// renderers — that's Phase 7C.  The preview panel renders a mock.
import React, { useCallback, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel,
  AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Save, Undo2, History } from "lucide-react";
import { colors } from "@/theme";

import {
  useFormTemplate, FORM_TYPES, FORM_TYPE_LABELS,
} from "@/hooks/useFormTemplate";
import FieldList from "@/components/form-editor/FieldList";
import FieldDetailPanel from "@/components/form-editor/FieldDetailPanel";
import PreviewPanel from "@/components/form-editor/PreviewPanel";
import VersionHistoryDrawer
  from "@/components/form-editor/VersionHistoryDrawer";


export default function FormEditor({ readOnly = false }) {
  const [formType, setFormType] = useState(FORM_TYPES[0]);
  const [pendingType, setPendingType] = useState(null);
  const [discardConfirm, setDiscardConfirm] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [selectedFieldId, setSelectedFieldId] = useState(null);

  const {
    template, draft, dirty, loading, saving, versions,
    save, discard, revert, loadVersions,
    updateField, reorderFields,
  } = useFormTemplate(formType);

  const selectedField = useMemo(() => (
    draft.find((f) => f.field_id === selectedFieldId) || draft[0] || null
  ), [draft, selectedFieldId]);

  const requestFormTypeSwitch = useCallback((next) => {
    if (dirty) { setPendingType(next); return; }
    setFormType(next);
    setSelectedFieldId(null);
  }, [dirty]);

  const confirmSwitch = useCallback(() => {
    if (!pendingType) return;
    discard();
    setFormType(pendingType);
    setPendingType(null);
    setSelectedFieldId(null);
  }, [pendingType, discard]);

  const cancelSwitch = useCallback(() => setPendingType(null), []);

  const handleSave = useCallback(async () => {
    const result = await save();
    if (result) setSelectedFieldId(null);
  }, [save]);

  const handleDiscardRequest = useCallback(() => {
    if (!dirty) { discard(); return; }
    setDiscardConfirm(true);
  }, [dirty, discard]);

  const confirmDiscard = useCallback(() => {
    discard();
    setDiscardConfirm(false);
    setSelectedFieldId(null);
  }, [discard]);

  const handleRevert = useCallback(async (version) => {
    await revert(version);
    setHistoryOpen(false);
    setSelectedFieldId(null);
  }, [revert]);

  return (
    <div
      className="max-w-7xl mx-auto p-4 md:p-6"
      data-testid="form-editor-page"
    >
      <header className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div>
          <h1 className="text-2xl font-bold"
              style={{ color: colors.onSurface }}>Form Editor</h1>
          <p className="text-sm text-slate-500">
            Reorder fields and restyle. Add / delete lands in Phase 7B+.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Select
            value={formType}
            onValueChange={requestFormTypeSwitch}
            data-testid="form-type-select"
          >
            <SelectTrigger className="w-64"
                            data-testid="form-type-select-trigger">
              <SelectValue />
            </SelectTrigger>
            <SelectContent data-testid="form-type-select-content">
              {FORM_TYPES.map((ft) => (
                <SelectItem
                  key={ft} value={ft}
                  data-testid={`form-type-option-${ft}`}
                >{FORM_TYPE_LABELS[ft] || ft}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {!readOnly ? (
            <>
              <Button
                type="button" variant="outline" size="sm"
                onClick={() => setHistoryOpen(true)}
                data-testid="form-editor-history-btn"
              >
                <History size={14} className="mr-1" />
                Versions
                {template ? (
                  <span className="ml-1 text-xs text-slate-500">
                    (v{template.version})
                  </span>
                ) : null}
              </Button>
              <Button
                type="button" variant="outline" size="sm"
                onClick={handleDiscardRequest}
                disabled={!dirty || saving}
                data-testid="form-editor-discard-btn"
              >
                <Undo2 size={14} className="mr-1" />
                Discard
              </Button>
              <Button
                type="button" size="sm"
                onClick={handleSave}
                disabled={!dirty || saving || loading}
                data-testid="form-editor-save-btn"
              >
                <Save size={14} className="mr-1" />
                {saving ? "Saving…" : "Save"}
              </Button>
            </>
          ) : (
            <span
              className="text-xs uppercase font-bold px-2 py-1 rounded"
              style={{ background: "#FEF3C7", color: "#92400E" }}
              data-testid="form-editor-readonly-badge"
            >Read-only</span>
          )}
        </div>
      </header>

      {dirty ? (
        <div
          className="mb-3 rounded border px-3 py-2 text-xs"
          style={{ background: "#FEF9C3", borderColor: "#FDE68A",
                   color: "#854D0E" }}
          data-testid="form-editor-dirty-banner"
        >
          Unsaved changes
        </div>
      ) : null}

      <div className="grid grid-cols-12 gap-4">
        {/* Field list — left (5 cols on wide, full on narrow) */}
        <div className="col-span-12 md:col-span-5"
             data-testid="form-editor-field-list-col">
          {loading ? (
            <div className="rounded-lg border bg-white p-6 text-sm text-slate-500"
                 data-testid="form-editor-loading">Loading…</div>
          ) : (
            <FieldList
              fields={draft}
              selectedFieldId={selectedField?.field_id || null}
              onSelectField={setSelectedFieldId}
              onReorder={reorderFields}
            />
          )}
        </div>

        {/* Detail panel — right-top (7 cols) */}
        <div className="col-span-12 md:col-span-7"
             data-testid="form-editor-detail-col">
          {selectedField ? (
            <FieldDetailPanel
              field={selectedField}
              onChange={updateField}
              readOnly={readOnly}
            />
          ) : (
            <aside
              className="rounded-lg border bg-white p-6 text-sm text-slate-500"
              data-testid="form-editor-detail-empty"
            >
              Pick a field on the left to edit its styles.
            </aside>
          )}
        </div>

        {/* Live preview — full-width below */}
        <div className="col-span-12">
          <PreviewPanel formType={formType} fields={draft} />
        </div>
      </div>

      {/* Confirm form_type switch when dirty */}
      <AlertDialog
        open={pendingType != null}
        onOpenChange={(o) => { if (!o) cancelSwitch(); }}
      >
        <AlertDialogContent data-testid="form-editor-switch-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved edits on the current form.  Switching
              forms will drop those edits.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={cancelSwitch}
              data-testid="form-editor-switch-cancel"
            >Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmSwitch}
              data-testid="form-editor-switch-ok"
            >Discard &amp; switch</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Confirm Discard */}
      <AlertDialog
        open={discardConfirm}
        onOpenChange={setDiscardConfirm}
      >
        <AlertDialogContent data-testid="form-editor-discard-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              Reset the editor back to v{template?.version || "?"}.
              Your in-progress edits will be lost.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => setDiscardConfirm(false)}
              data-testid="form-editor-discard-cancel"
            >Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDiscard}
              data-testid="form-editor-discard-ok"
            >Discard</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <VersionHistoryDrawer
        open={historyOpen}
        versions={versions}
        readOnly={readOnly}
        onClose={() => setHistoryOpen(false)}
        onRefresh={loadVersions}
        onRevert={handleRevert}
      />
    </div>
  );
}
