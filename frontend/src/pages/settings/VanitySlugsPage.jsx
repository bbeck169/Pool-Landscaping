import React from "react";
import { toast } from "sonner";
import { Trash2, Plus, ExternalLink, Lock, Info, Save } from "lucide-react";
import { api } from "@/api";
import { colors } from "@/theme";
import ConfirmDeleteDialog from "@/components/common/ConfirmDeleteDialog";

/**
 * Phase 21 · Feb 2026 — Vanity slug editor (super_admin only).
 *
 * Backend: `/api/tenants/current/slug-aliases`
 *   GET · POST · DELETE
 * Backend (bonus): `/api/tenants/current/primary-app-domain`
 *   GET · PATCH — Primary customer-facing URL surfaced in the same
 *   page since both settings target ``tenant.settings.*`` and are
 *   super_admin-scoped.
 *
 * Layout:
 *   1. Canonical slug displayed as a locked chip.
 *   2. Alias list — each alias is a chip with trash icon +
 *      ConfirmDeleteDialog on click.
 *   3. Add-form with regex helper text; inline error surfaces.
 *   4. Primary customer-facing URL — text input + Save +
 *      "Test URL" (opens the value in a new tab).
 */
const ALIAS_REGEX = /^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$/;
const RESERVED = new Set([
  "admin", "api", "public", "app", "static", "assets", "login",
  "logout", "signup", "signin", "auth", "www", "portal", "webhooks",
  "resend", "stripe", "docs", "openapi", "health",
]);

export default function VanitySlugsPage() {
  const [state, setState] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [adding, setAdding] = React.useState("");
  const [addError, setAddError] = React.useState("");
  const [pendingDelete, setPendingDelete] = React.useState(null);
  const [_domainState, setDomainState] = React.useState(null);
  const [domainDraft, setDomainDraft] = React.useState("");
  const [domainSaving, setDomainSaving] = React.useState(false);
  const [domainErr, setDomainErr] = React.useState("");

  const load = React.useCallback(async () => {
    try {
      const [aliases, dom] = await Promise.all([
        api.get("/tenants/current/slug-aliases"),
        api.get("/tenants/current/primary-app-domain"),
      ]);
      setState(aliases);
      setDomainState(dom);
      setDomainDraft(dom?.primary_app_domain || "");
    } catch (e) {
      toast.error(e.message || "Failed to load vanity settings");
    }
  }, []);
  React.useEffect(() => { load(); }, [load]);

  const validateAlias = (a) => {
    const v = (a || "").trim().toLowerCase();
    if (!v) return "Alias is required.";
    if (!ALIAS_REGEX.test(v)) {
      return "Use lowercase letters, digits, and hyphens (3–32 chars, alphanumeric at both ends).";
    }
    if (RESERVED.has(v)) return `'${v}' is a reserved word — try another.`;
    return "";
  };

  const addAlias = async () => {
    setAddError("");
    const err = validateAlias(adding);
    if (err) {
      setAddError(err);
      return;
    }
    setBusy(true);
    try {
      const res = await api.post("/tenants/current/slug-aliases", {
        alias: adding.trim().toLowerCase(),
      });
      setState((s) => ({ ...(s || {}), slug_aliases: res.slug_aliases }));
      setAdding("");
      toast.success("Vanity slug added");
    } catch (e) {
      const msg = e?.message || "Failed to add alias";
      if (/already in use|already claimed|409/i.test(msg)) {
        setAddError("This alias is already claimed by another tenant.");
      } else if (/reserved/i.test(msg)) {
        setAddError("Reserved word — try another.");
      } else if (/match/i.test(msg) || /^[a-z]/i.test(adding.trim().charAt(0))) {
        setAddError(msg);
      } else {
        setAddError(msg);
      }
    } finally {
      setBusy(false);
    }
  };

  const removeAlias = async (alias) => {
    setBusy(true);
    try {
      const res = await api.del(`/tenants/current/slug-aliases/${encodeURIComponent(alias)}`);
      setState((s) => ({ ...(s || {}), slug_aliases: res.slug_aliases }));
      toast.success(`Removed '${alias}'`);
    } catch (e) {
      toast.error(e?.message || "Failed to remove alias");
    } finally {
      setBusy(false);
      setPendingDelete(null);
    }
  };

  const saveDomain = async () => {
    setDomainErr("");
    setDomainSaving(true);
    try {
      const trimmed = (domainDraft || "").trim();
      const res = await api.patch("/tenants/current/primary-app-domain", {
        primary_app_domain: trimmed || null,
      });
      setDomainState((d) => ({ ...(d || {}), primary_app_domain: res.primary_app_domain }));
      toast.success(res.primary_app_domain
        ? "Primary URL updated"
        : "Primary URL cleared (fallback active)");
    } catch (e) {
      setDomainErr(e?.message || "Failed to save primary URL");
    } finally {
      setDomainSaving(false);
    }
  };

  const openTestUrl = () => {
    const val = (domainDraft || "").trim();
    if (!val) return;
    try { window.open(val, "_blank", "noopener,noreferrer"); } catch { /* noop */ }
  };

  if (!state) {
    return (
      <div className="p-6 text-sm" style={{ color: colors.muted }} data-testid="vanity-slugs-loading">
        Loading…
      </div>
    );
  }

  return (
    <div
      className="p-6 max-w-3xl mx-auto"
      style={{ color: colors.onSurface }}
      data-testid="vanity-slugs-page"
    >
      <h1 className="text-2xl font-bold mb-1" data-testid="vanity-slugs-title">
        Vanity slugs
      </h1>
      <p className="text-sm mb-6" style={{ color: colors.muted }}>
        Extra URL slugs that resolve to this tenant. Great for marketing
        microsites, campaign URLs, and partner co-brand pages.
      </p>

      {/* Canonical slug */}
      <div
        className="rounded-xl p-4 mb-6"
        style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
      >
        <div className="text-xs font-bold uppercase mb-2" style={{ color: colors.muted }}>
          Canonical slug
        </div>
        <div className="flex items-center gap-2">
          <span
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-semibold"
            style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
            data-testid="vanity-slug-canonical"
          >
            <Lock size={12} />
            {state.canonical_slug}
          </span>
          <span className="text-xs" style={{ color: colors.muted }}>
            (cannot be removed)
          </span>
        </div>
      </div>

      {/* Aliases */}
      <div
        className="rounded-xl p-4 mb-6"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="text-xs font-bold uppercase mb-3" style={{ color: colors.muted }}>
          Aliases
        </div>
        {(state.slug_aliases || []).length === 0 ? (
          <div className="text-sm mb-3" style={{ color: colors.muted }} data-testid="vanity-slugs-empty">
            No aliases yet.
          </div>
        ) : (
          <div className="flex flex-wrap gap-2 mb-4" data-testid="vanity-slugs-list">
            {state.slug_aliases.map((alias) => (
              <span
                key={alias}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm"
                style={{ backgroundColor: colors.surfaceSecondary, border: `1px solid ${colors.border}` }}
                data-testid={`vanity-slug-item-${alias}`}
              >
                <span className="font-semibold">{alias}</span>
                <button
                  onClick={() => setPendingDelete(alias)}
                  className="p-0.5 rounded hover:bg-red-50"
                  aria-label={`Remove ${alias}`}
                  data-testid={`vanity-slug-delete-${alias}`}
                >
                  <Trash2 size={12} color="#B91C1C" />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Add form */}
        <div className="flex items-start gap-2">
          <div className="flex-1">
            <input
              type="text"
              value={adding}
              onChange={(e) => { setAdding(e.target.value); setAddError(""); }}
              placeholder="e.g. vistancia-pools"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                borderColor: addError ? "#DC2626" : colors.border,
                backgroundColor: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="vanity-slug-add-input"
              disabled={busy}
              onKeyDown={(e) => { if (e.key === "Enter") addAlias(); }}
            />
            <p
              className="text-[11px] mt-1 flex items-center gap-1"
              style={{ color: addError ? "#DC2626" : colors.muted }}
              data-testid="vanity-slug-add-helper"
            >
              <Info size={11} />
              {addError || "Lowercase letters, digits, and hyphens. 3–32 chars. Must start and end with alphanumeric."}
            </p>
          </div>
          <button
            onClick={addAlias}
            disabled={busy || !adding.trim()}
            className="inline-flex items-center gap-1 h-[38px] px-4 rounded-lg text-sm font-bold text-white disabled:opacity-50"
            style={{ backgroundColor: colors.brand }}
            data-testid="vanity-slug-add-submit"
          >
            <Plus size={14} /> Add
          </button>
        </div>
      </div>

      {/* Primary customer-facing URL */}
      <div
        className="rounded-xl p-4"
        style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
      >
        <div className="text-xs font-bold uppercase mb-1" style={{ color: colors.muted }}>
          Primary customer-facing URL
        </div>
        <p className="text-xs mb-3" style={{ color: colors.muted }}>
          Used in outbound invoice pay links, review requests, and public NFC card URLs.
          Defaults to <b>https://app.plofv.com</b>.
        </p>
        <div className="flex items-start gap-2">
          <div className="flex-1">
            <input
              type="url"
              value={domainDraft}
              onChange={(e) => { setDomainDraft(e.target.value); setDomainErr(""); }}
              placeholder="https://app.plofv.com"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{
                borderColor: domainErr ? "#DC2626" : colors.border,
                backgroundColor: colors.surface,
                color: colors.onSurface,
              }}
              data-testid="primary-domain-input"
              disabled={domainSaving}
            />
            {domainErr ? (
              <p className="text-[11px] mt-1" style={{ color: "#DC2626" }} data-testid="primary-domain-error">
                {domainErr}
              </p>
            ) : null}
          </div>
          <button
            onClick={openTestUrl}
            disabled={!domainDraft.trim()}
            className="inline-flex items-center gap-1 h-[38px] px-3 rounded-lg text-sm font-semibold disabled:opacity-40"
            style={{ backgroundColor: colors.surfaceSecondary, color: colors.onSurface, border: `1px solid ${colors.border}` }}
            data-testid="primary-domain-test-btn"
            title="Open in a new tab"
          >
            <ExternalLink size={14} /> Test URL
          </button>
          <button
            onClick={saveDomain}
            disabled={domainSaving}
            className="inline-flex items-center gap-1 h-[38px] px-4 rounded-lg text-sm font-bold text-white disabled:opacity-50"
            style={{ backgroundColor: colors.brand }}
            data-testid="primary-domain-save-btn"
          >
            <Save size={14} /> {domainSaving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <ConfirmDeleteDialog
        open={!!pendingDelete}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => removeAlias(pendingDelete)}
        entityLabel={pendingDelete ? `alias '${pendingDelete}'` : "alias"}
        testid="vanity-slug-confirm-delete"
      />
    </div>
  );
}
