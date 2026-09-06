/**
 * Phase 2 · Templates Library — schema-driven fill page.
 *
 * Route: `/admin/templates/instances/:id`
 *
 * • Autosave — debounced 750ms on every value change PLUS an every-15s
 *   safety net that flushes if the local state is dirty.
 * • Finalize → confirm → POST /finalize → inputs become read-only, banner
 *   appears prompting the user to duplicate for further edits.
 * • Duplicate / Delete / Download PDF actions live in the header.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  ArrowLeft, CheckCircle2, Copy, Download, Trash2, Save, Loader2, Lock, Send,
} from "lucide-react";
import { colors, gradients } from "@/theme";
import { useAuth } from "@/auth";
import {
  getInstance, getDefinition, updateInstance, finalizeInstance,
  duplicateInstance, deleteInstance, generatePdf, CATEGORY_LABEL,
} from "@/api/templates";
import TemplateFieldRenderer from "@/components/templates/TemplateFieldRenderer";
import TemplateStatusPill from "@/components/templates/TemplateStatusPill";
import SharePortalModal from "@/components/templates/SharePortalModal";

const AUTOSAVE_DEBOUNCE_MS = 750;
const AUTOSAVE_INTERVAL_MS = 15000;

export default function TemplateFillPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [instance, setInstance] = useState(null);
  const [definition, setDefinition] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saveState, setSaveState] = useState("idle"); // idle | saving | saved | error
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(null); // "finalize" | "delete" | null
  const [showLastSaved, setShowLastSaved] = useState(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [shareToast, setShareToast] = useState("");

  // Autosave plumbing — refs so the debounced/interval fns always see fresh values.
  const dirtyRef = useRef(false);
  const debounceRef = useRef(null);
  const intervalRef = useRef(null);
  const instanceRef = useRef(null);
  instanceRef.current = instance;

  const isFinalized = instance?.status === "finalized";
  const readOnly = isFinalized;

  // ─── Loaders ──────────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const inst = await getInstance(id);
      setInstance(inst);
      const defn = await getDefinition(inst.template_code);
      setDefinition(defn);
    } catch (e) {
      setError(e.message || "Failed to load template.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // ─── Autosave engine ─────────────────────────────────────────────
  const flushSave = useCallback(async () => {
    const inst = instanceRef.current;
    if (!inst || !dirtyRef.current || readOnly) return;
    dirtyRef.current = false;
    setSaveState("saving");
    try {
      const updated = await updateInstance(inst.id, {
        title: inst.title,
        values: inst.values || {},
      });
      instanceRef.current = updated;
      setInstance((prev) => (prev ? { ...prev, ...updated } : updated));
      setSaveState("saved");
      setShowLastSaved(new Date());
    } catch (e) {
      setSaveState("error");
      setError(e.message || "Autosave failed.");
      dirtyRef.current = true; // retry on next tick
    }
  }, [readOnly]);

  const scheduleSave = useCallback(() => {
    dirtyRef.current = true;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => { flushSave(); }, AUTOSAVE_DEBOUNCE_MS);
  }, [flushSave]);

  // 15s dirty-check safety net
  useEffect(() => {
    intervalRef.current = setInterval(() => {
      if (dirtyRef.current) flushSave();
    }, AUTOSAVE_INTERVAL_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [flushSave]);

  // Flush on unmount / navigation.
  useEffect(() => {
    return () => { flushSave(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Value handlers ───────────────────────────────────────────────
  const setValue = (key, val) => {
    if (readOnly) return;
    setInstance((prev) => ({
      ...prev,
      values: { ...(prev.values || {}), [key]: val },
    }));
    scheduleSave();
  };

  const setTitle = (val) => {
    if (readOnly) return;
    setInstance((prev) => ({ ...prev, title: val }));
    scheduleSave();
  };

  // ─── Header actions ───────────────────────────────────────────────
  const doFinalize = async () => {
    setConfirming(null);
    try {
      await flushSave();
      const updated = await finalizeInstance(id);
      setInstance(updated);
    } catch (e) {
      alert(e.message || "Could not finalize.");
    }
  };

  const doDuplicate = async () => {
    try {
      await flushSave();
      const dup = await duplicateInstance(id);
      navigate(`/admin/templates/instances/${dup.id}`);
    } catch (e) {
      alert(e.message || "Could not duplicate.");
    }
  };

  const doDelete = async () => {
    setConfirming(null);
    try {
      await deleteInstance(id);
      navigate("/admin/templates");
    } catch (e) {
      alert(e.message || "Could not delete.");
    }
  };

  const doDownload = async () => {
    try {
      await flushSave();
      await generatePdf(id, instance?.title || definition?.title || "template");
    } catch (e) {
      alert(e.message || "Could not generate PDF.");
    }
  };

  const currentUserName = useMemo(() => {
    if (!user) return "";
    return user.name || user.full_name || user.email || "";
  }, [user]);

  // ─── Render ───────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="p-8 text-sm" style={{ color: colors.muted }} data-testid="template-fill-loading">
        Loading…
      </div>
    );
  }

  if (error && !instance) {
    return (
      <div className="p-8" data-testid="template-fill-error">
        <div className="mb-4 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "#FEE2E2", color: colors.error }}>
          {error}
        </div>
        <Link
          to="/admin/templates"
          className="text-sm font-semibold inline-flex items-center gap-1"
          style={{ color: colors.brand }}
        >
          <ArrowLeft size={14} /> Back to Library
        </Link>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="template-fill-page">
      {/* Back link */}
      <Link
        to="/admin/templates"
        className="text-sm font-semibold inline-flex items-center gap-1 mb-3"
        style={{ color: colors.brand }}
        data-testid="template-fill-back"
      >
        <ArrowLeft size={14} /> Back to Library
      </Link>

      {/* Header card */}
      <div
        className="rounded-2xl p-5 mb-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        data-testid="template-fill-header"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex-1 min-w-[240px]">
            <input
              value={instance?.title || ""}
              onChange={(e) => setTitle(e.target.value)}
              disabled={readOnly}
              className="w-full text-2xl font-bold outline-none bg-transparent"
              style={{ color: colors.onSurface, borderBottom: `1px solid ${readOnly ? "transparent" : colors.border}` }}
              placeholder="Untitled template"
              data-testid="template-fill-title-input"
            />
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              {definition?.category && (
                <span
                  className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider"
                  style={{ backgroundColor: colors.brandTertiary, color: colors.onBrandTertiary }}
                >
                  {CATEGORY_LABEL[definition.category] || definition.category}
                </span>
              )}
              <TemplateStatusPill status={instance?.status} />
              <SaveIndicator state={saveState} lastSaved={showLastSaved} error={error} />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2" data-testid="template-fill-actions">
            {!isFinalized && (
              <button
                onClick={() => setConfirming("finalize")}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold text-white"
                style={{ background: gradients.navyToGreen.css }}
                data-testid="template-fill-finalize-btn"
              >
                <CheckCircle2 size={14} /> Finalize
              </button>
            )}
            <button
              onClick={doDuplicate}
              className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
              style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
              data-testid="template-fill-duplicate-btn"
            >
              <Copy size={14} /> Duplicate
            </button>
            <button
              onClick={doDownload}
              className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
              style={{ backgroundColor: colors.surface, color: colors.brand, border: `1px solid ${colors.border}` }}
              data-testid="template-fill-download-btn"
            >
              <Download size={14} /> Download PDF
            </button>
            {isFinalized && definition?.is_customer_facing && (
              <button
                onClick={() => setShareOpen(true)}
                className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold text-white"
                style={{ background: gradients.navyToGreen.css }}
                data-testid="template-fill-share-portal-btn"
              >
                <Send size={14} /> Share to Customer Portal
              </button>
            )}
            <button
              onClick={() => setConfirming("delete")}
              className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-semibold"
              style={{ backgroundColor: colors.surface, color: colors.error, border: `1px solid ${colors.border}` }}
              data-testid="template-fill-delete-btn"
            >
              <Trash2 size={14} /> Delete
            </button>
          </div>
        </div>
      </div>

      {isFinalized && (
        <div
          className="rounded-xl px-4 py-3 mb-4 text-sm flex items-center gap-2"
          style={{ backgroundColor: "#DCFCE7", color: "#166534", border: `1px solid #86EFAC` }}
          data-testid="template-fill-finalized-banner"
        >
          <Lock size={14} /> This template is finalized. <b>Duplicate</b> it to make further changes.
        </div>
      )}

      {/* Sections */}
      {definition?.schema?.map((section, si) => (
        <div
          key={section.title + si}
          className="rounded-2xl p-5 mb-4"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
          data-testid={`template-fill-section-${si}`}
        >
          {section.title && (
            <h2 className="text-base font-bold mb-4" style={{ color: colors.onSurface }}>
              {section.title}
            </h2>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {(section.fields || []).map((field, fi) => {
              // long_text, table, header should span the full width for readability.
              const fullSpan = ["long_text", "table", "header", "signature"].includes(field.type);
              return (
                <div key={field.key + fi} className={fullSpan ? "md:col-span-2" : ""}>
                  <TemplateFieldRenderer
                    field={field}
                    value={instance?.values?.[field.key]}
                    onChange={(v) => setValue(field.key, v)}
                    disabled={readOnly}
                    currentUserName={currentUserName}
                  />
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {/* Confirm modals */}
      {confirming === "finalize" && (
        <ConfirmModal
          title="Finalize this template?"
          body="Once finalized, the form fields become read-only. You can still download a PDF or duplicate it to make edits."
          confirmLabel="Finalize"
          onConfirm={doFinalize}
          onCancel={() => setConfirming(null)}
          testId="template-fill-confirm-finalize"
        />
      )}
      {confirming === "delete" && (
        <ConfirmModal
          title="Delete this template?"
          body="This will permanently remove this instance. Definitions in the Library are unaffected."
          confirmLabel="Delete"
          confirmDanger
          onConfirm={doDelete}
          onCancel={() => setConfirming(null)}
          testId="template-fill-confirm-delete"
        />
      )}

      <SharePortalModal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        instanceId={id}
        onShared={({ customer, response }) => {
          const link = response?.portal_link || "/portal/documents";
          setShareToast(`Shared to ${customer.name}'s portal. Preview: ${link}`);
          setTimeout(() => setShareToast(""), 6000);
        }}
      />

      {shareToast && (
        <div
          className="fixed bottom-6 right-6 z-40 px-4 py-3 rounded-xl text-sm font-semibold shadow-lg"
          style={{ backgroundColor: "#DCFCE7", color: "#166534", border: `1px solid #86EFAC` }}
          data-testid="template-fill-share-toast"
        >
          {shareToast}
        </div>
      )}
    </div>
  );
}

function SaveIndicator({ state, lastSaved, error }) {
  if (state === "saving") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px]" style={{ color: colors.onSurfaceSecondary }} data-testid="template-save-indicator">
        <Loader2 size={12} className="animate-spin" /> Saving…
      </span>
    );
  }
  if (state === "error") {
    return (
      <span className="inline-flex items-center gap-1 text-[11px]" style={{ color: colors.error }} data-testid="template-save-indicator-error">
        <Save size={12} /> {error || "Save failed"}
      </span>
    );
  }
  if (state === "saved" && lastSaved) {
    return (
      <span className="inline-flex items-center gap-1 text-[11px]" style={{ color: colors.success }} data-testid="template-save-indicator-saved">
        <CheckCircle2 size={12} /> Saved {lastSaved.toLocaleTimeString()}
      </span>
    );
  }
  return null;
}

function ConfirmModal({ title, body, confirmLabel, confirmDanger, onConfirm, onCancel, testId }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.5)" }}
      onClick={onCancel}
      data-testid={testId}
    >
      <div
        className="bg-white rounded-2xl max-w-md w-full p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        style={{ border: `1px solid ${colors.border}` }}
      >
        <h3 className="text-lg font-bold mb-2" style={{ color: colors.onSurface }}>{title}</h3>
        <p className="text-sm mb-4" style={{ color: colors.onSurfaceSecondary }}>{body}</p>
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="px-3 py-2 rounded-xl text-sm font-semibold"
            style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
            data-testid={`${testId}-cancel`}
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-3 py-2 rounded-xl text-sm font-bold text-white"
            style={{ background: confirmDanger ? colors.error : gradients.navyToGreen.css }}
            data-testid={`${testId}-confirm`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
