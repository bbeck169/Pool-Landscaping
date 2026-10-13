/**
 * P2 #10c · Feb-2026 — Transactional Templates editor page.
 *
 * Admin-only page at ``/settings/notifications/templates`` listing
 * every transactional slug registered in
 * ``backend/services/transactional_templates_registry.py`` plus the
 * tenant's current override row (if any) from
 * ``db.marketing_templates`` filtered by ``code`` presence.
 *
 * Lightweight list + inline editor — reuses the existing
 * ``PATCH /marketing/templates/{tid}`` endpoint for saves. "Reset"
 * calls the new ``POST /marketing/templates/by-code/{code}/reset``
 * which soft-resets by flipping ``active=False`` (hardcoded fallback
 * resumes in the send-site caller).
 *
 * Scope caveats (per the P2 #10 audit — deferred to follow-up
 * tickets, not blocking the MVP):
 *   * Test-send button — TD-17
 *   * Multi-locale picker — TD-18
 *   * Rich HTML preview — reuses P2 #5 ``<SafeEmailIframe>`` which
 *     is not yet in this file; current preview is plain-text with
 *     ``<pre>`` wrapping.
 */
import React, { useEffect, useState } from "react";
import { api } from "@/api";
import { toast } from "sonner";


function _mergeTagsIntoString(subject, body) {
  const haystack = `${subject || ""} ${body || ""}`;
  return haystack;
}


function _validateRow(entry, subject, body) {
  const errors = [];
  if (entry.channel === "email" && !subject.trim()) {
    errors.push("Subject is required for email templates.");
  }
  if (!body.trim()) {
    errors.push("Body is required.");
  }
  const bodyBytes = new Blob([body]).size;
  if (entry.channel === "email" && bodyBytes > 100_000) {
    errors.push(`Body exceeds 100 KB (currently ${(bodyBytes / 1024).toFixed(1)} KB).`);
  }
  if (entry.channel === "sms" && body.length > 1600) {
    errors.push(`SMS body exceeds 1600 chars (currently ${body.length}).`);
  }
  const haystack = _mergeTagsIntoString(subject, body);
  const missing = (entry.required_tags || []).filter(
    (tag) => !haystack.includes(`{{${tag}}}`)
  );
  if (missing.length > 0) {
    errors.push(`Missing required merge tags: ${missing.map((t) => `{{${t}}}`).join(", ")}`);
  }
  return errors;
}


export default function TransactionalTemplates() {
  const [registry, setRegistry] = useState([]);
  const [overrides, setOverrides] = useState({});
  const [loading, setLoading] = useState(true);
  const [editingCode, setEditingCode] = useState(null);
  const [editSubject, setEditSubject] = useState("");
  const [editBody, setEditBody] = useState("");
  const [saving, setSaving] = useState(false);

  async function _loadAll() {
    setLoading(true);
    try {
      const reg = await api.get("/marketing/transactional-registry");
      const list = await api.get("/marketing/templates?limit=200");
      const byCode = {};
      (list.items || list || []).forEach((row) => {
        if (row.code) byCode[row.code] = row;
      });
      setRegistry(reg.templates || []);
      setOverrides(byCode);
    } catch (e) {
      toast.error(`Load failed: ${e?.message || e}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { _loadAll(); }, []);

  function _startEdit(entry) {
    const override = overrides[entry.code];
    setEditingCode(entry.code);
    setEditSubject(override?.subject || "");
    setEditBody(override?.body || "");
  }

  function _cancelEdit() {
    setEditingCode(null);
    setEditSubject("");
    setEditBody("");
  }

  async function _save(entry) {
    const errors = _validateRow(entry, editSubject, editBody);
    if (errors.length > 0) {
      toast.error(errors.join(" · "));
      return;
    }
    setSaving(true);
    try {
      const existing = overrides[entry.code];
      if (existing) {
        await api.patch(`/marketing/templates/${existing.id}`, {
          subject: entry.channel === "email" ? editSubject : null,
          body: editBody,
          active: true,
        });
      } else {
        await api.post("/marketing/templates", {
          name: entry.code,
          channel: entry.channel,
          category: "general",
          code: entry.code,
          subject: entry.channel === "email" ? editSubject : null,
          body: editBody,
          active: true,
        });
      }
      toast.success("Template saved");
      _cancelEdit();
      await _loadAll();
    } catch (e) {
      toast.error(`Save failed: ${e?.message || e}`);
    } finally {
      setSaving(false);
    }
  }

  async function _reset(entry) {
    if (!window.confirm(`Reset ${entry.code} to the system default?`)) return;
    try {
      await api.post(`/marketing/templates/by-code/${entry.code}/reset`);
      toast.success("Reset — system default restored.");
      await _loadAll();
    } catch (e) {
      toast.error(`Reset failed: ${e?.message || e}`);
    }
  }

  if (loading) {
    return (
      <div className="p-8" data-testid="transactional-templates-loading">
        Loading templates…
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto" data-testid="transactional-templates-page">
      <h1 className="text-2xl font-semibold mb-2">Notification templates</h1>
      <p className="text-sm text-gray-600 mb-6">
        Customize the subject and body of system-triggered emails and SMS
        messages. Changes save per-tenant; "Reset" restores the built-in
        default. Required merge tags for each template are listed in the
        docs panel.
      </p>

      <div className="space-y-3" data-testid="transactional-templates-list">
        {registry.map((entry) => {
          const override = overrides[entry.code];
          const isEditing = editingCode === entry.code;
          return (
            <div
              key={entry.code}
              className="border rounded-lg p-4 bg-white"
              data-testid={`transactional-template-row-${entry.code}`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-semibold">
                      {entry.code}
                    </span>
                    <span className="text-xs px-2 py-0.5 rounded bg-gray-100">
                      {entry.channel}
                    </span>
                    {override?.active && (
                      <span className="text-xs px-2 py-0.5 rounded bg-emerald-100 text-emerald-800">
                        customized
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-1">
                    {entry.description}
                  </p>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  {!isEditing && (
                    <>
                      <button
                        type="button"
                        className="text-xs px-3 py-1.5 rounded border hover:bg-gray-50"
                        onClick={() => _startEdit(entry)}
                        data-testid={`transactional-template-edit-btn-${entry.code}`}
                      >
                        Edit
                      </button>
                      {override?.active && (
                        <button
                          type="button"
                          className="text-xs px-3 py-1.5 rounded border border-red-300 text-red-600 hover:bg-red-50"
                          onClick={() => _reset(entry)}
                          data-testid={`transactional-template-reset-btn-${entry.code}`}
                        >
                          Reset
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>

              {isEditing && (
                <div
                  className="mt-4 space-y-3"
                  data-testid="transactional-template-editor"
                >
                  {entry.channel === "email" && (
                    <div>
                      <label className="block text-xs font-semibold mb-1">
                        Subject
                      </label>
                      <input
                        type="text"
                        value={editSubject}
                        onChange={(e) => setEditSubject(e.target.value)}
                        className="w-full border rounded px-2 py-1 text-sm"
                        data-testid="transactional-template-subject-input"
                      />
                    </div>
                  )}
                  <div>
                    <label className="block text-xs font-semibold mb-1">
                      Body
                    </label>
                    <textarea
                      value={editBody}
                      onChange={(e) => setEditBody(e.target.value)}
                      rows={entry.channel === "sms" ? 4 : 10}
                      className="w-full border rounded px-2 py-1 text-sm font-mono"
                      data-testid="transactional-template-body-input"
                    />
                  </div>
                  <div
                    className="text-xs bg-gray-50 border rounded p-2"
                    data-testid="transactional-template-docs-panel"
                  >
                    <div className="font-semibold mb-1">
                      Required merge tags
                    </div>
                    <div className="font-mono">
                      {(entry.required_tags || []).map((t) => (
                        <span key={t} className="mr-2">{`{{${t}}}`}</span>
                      ))}
                    </div>
                    {(entry.optional_tags || []).length > 0 && (
                      <>
                        <div className="font-semibold mt-2 mb-1">
                          Optional merge tags
                        </div>
                        <div className="font-mono text-gray-500">
                          {entry.optional_tags.map((t) => (
                            <span key={t} className="mr-2">{`{{${t}}}`}</span>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={saving}
                      onClick={() => _save(entry)}
                      className="text-xs px-4 py-1.5 rounded bg-slate-900 text-white disabled:opacity-50"
                      data-testid="transactional-template-save-btn"
                    >
                      {saving ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      onClick={_cancelEdit}
                      className="text-xs px-4 py-1.5 rounded border"
                      data-testid="transactional-template-cancel-btn"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
