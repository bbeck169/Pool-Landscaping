// Phase 7B · Feb-2026 — Form Template editor hook.
//
// Owns the fetch / save / revert / version-history round-trip
// against the Phase 7A ``/api/form-templates/*`` endpoints.  Pure
// data layer — the page + its sub-components consume the returned
// state + mutators.
//
// Dirty tracking lives here because the "did the admin change
// anything?" question is a pure JSON-compare against the last
// server-returned ``fields`` array; the page shouldn't have to
// re-derive that every render.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";


export const FORM_TYPES = [
  "pool_service_report",
  "landscape_service_report",
  "job_checklist_pool",
  "job_checklist_landscape",
  "job_checklist_generic",
  "estimate",
  "invoice",
];


export const FORM_TYPE_LABELS = {
  pool_service_report:      "Pool Service Report",
  landscape_service_report: "Landscape Service Report",
  job_checklist_pool:       "Job Checklist · Pool",
  job_checklist_landscape:  "Job Checklist · Landscape",
  job_checklist_generic:    "Job Checklist · Generic",
  estimate:                 "Estimate",
  invoice:                  "Invoice",
};


function _canonical(fields) {
  // Order-sensitive JSON compare — sorts object keys deterministically
  // so a style key reorder doesn't register as a drift.
  return JSON.stringify(fields, (_k, v) => {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      return Object.fromEntries(
        Object.keys(v).sort().map((k) => [k, v[k]]),
      );
    }
    return v;
  });
}


export function useFormTemplate(formType) {
  const [template, setTemplate] = useState(null);
  const [draft, setDraft]       = useState([]);
  const [loading, setLoading]   = useState(false);
  const [saving, setSaving]     = useState(false);
  const [error, setError]       = useState("");
  const [versions, setVersions] = useState([]);
  const _loadToken = useRef(0);

  const dirty = useMemo(() => {
    if (!template) return false;
    return _canonical(template.fields) !== _canonical(draft);
  }, [template, draft]);

  const load = useCallback(async () => {
    if (!formType) return;
    const my = ++_loadToken.current;
    setLoading(true);
    setError("");
    try {
      const body = await api.get(`/form-templates/${formType}`);
      if (my !== _loadToken.current) return;
      setTemplate(body);
      setDraft((body.fields || []).map((f) => ({
        ...f, style: { ...(f.style || {}) },
      })));
    } catch (e) {
      if (my !== _loadToken.current) return;
      const msg = e?.detail || e?.message || "Failed to load template";
      setError(msg);
      toast.error(msg);
    } finally {
      if (my === _loadToken.current) setLoading(false);
    }
  }, [formType]);

  const loadVersions = useCallback(async () => {
    if (!formType) return;
    try {
      const body = await api.get(`/form-templates/${formType}/versions`);
      setVersions(Array.isArray(body?.versions) ? body.versions : []);
    } catch (e) {
      toast.error(e?.detail || e?.message || "Failed to load versions");
    }
  }, [formType]);

  const save = useCallback(async () => {
    if (!formType) return null;
    setSaving(true);
    try {
      const body = await api.put(
        `/form-templates/${formType}`,
        { fields: draft },
      );
      setTemplate(body);
      setDraft((body.fields || []).map((f) => ({
        ...f, style: { ...(f.style || {}) },
      })));
      toast.success(`Form template saved (v${body.version})`);
      return body;
    } catch (e) {
      const msg = e?.detail || e?.message || "Save failed";
      toast.error(msg);
      return null;
    } finally {
      setSaving(false);
    }
  }, [formType, draft]);

  const discard = useCallback(() => {
    if (!template) return;
    setDraft((template.fields || []).map((f) => ({
      ...f, style: { ...(f.style || {}) },
    })));
  }, [template]);

  const revert = useCallback(async (version) => {
    if (!formType) return null;
    setSaving(true);
    try {
      const body = await api.post(
        `/form-templates/${formType}/revert/${version}`,
      );
      setTemplate(body);
      setDraft((body.fields || []).map((f) => ({
        ...f, style: { ...(f.style || {}) },
      })));
      toast.success(`Reverted to v${body.version}`);
      await loadVersions();
      return body;
    } catch (e) {
      const msg = e?.detail || e?.message || "Revert failed";
      toast.error(msg);
      return null;
    } finally {
      setSaving(false);
    }
  }, [formType, loadVersions]);

  // Edit helpers — keep as hook-returned mutators so React batches
  // state updates and the page can call them without threading a
  // ``setDraft`` across every child.
  const updateField = useCallback((fieldId, patch) => {
    setDraft((prev) => prev.map((f) => (
      f.field_id === fieldId
        ? { ...f, ...patch, style: patch.style
            ? { ...(f.style || {}), ...patch.style }
            : f.style }
        : f
    )));
  }, []);

  const reorderFields = useCallback((nextOrdered) => {
    // Re-stamp ``order`` so persistence matches on-screen position.
    setDraft(nextOrdered.map((f, i) => ({ ...f, order: i })));
  }, []);

  useEffect(() => { load(); }, [load]);

  return {
    template, draft, dirty, loading, saving, error, versions,
    load, loadVersions, save, discard, revert,
    updateField, reorderFields,
  };
}
