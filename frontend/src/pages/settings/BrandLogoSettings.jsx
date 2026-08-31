/**
 * BrandLogoSettings — Feb-2026 · TD-08 promoted.
 *
 * Admin-only settings tile for the tenant brand logo. Preview area,
 * upload picker with pre-save preview, remove-with-confirm. Talks to
 * ``POST /api/tenants/branding/logo`` (multipart) + ``DELETE
 * /api/tenants/branding/logo``. On success, invalidates the
 * ``useTenantBrand`` cache so the app-shell top-left crown refreshes
 * without a page reload.
 *
 * Placement / routing: mounted at ``/settings/branding``. Existing
 * ``settings/tenant`` (TenantBrandSettings via TenantsAdminPage) is
 * super-admin only and edits colours; this new surface is admin +
 * super-admin and edits the logo file specifically.
 */
import React from "react";
import { toast } from "sonner";
import { Upload, Trash2, ImageIcon, Loader2, AlertCircle } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { api, api_base } from "@/api";
import { colors } from "@/theme";
import { invalidateTenantBrand } from "@/hooks/useTenantBrand";

const MAX_BYTES = 2 * 1024 * 1024;
const ALLOWED_MIME = new Set([
  "image/png", "image/svg+xml", "image/webp",
  "image/jpeg", "image/jpg",
]);
const ALLOWED_EXT_HINT = ".png,.svg,.webp,.jpg,.jpeg,image/png,image/svg+xml,image/webp,image/jpeg";

function humanBytes(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

/** Resolve the display URL for the logo. Relative paths (returned by
 *  the upload endpoint as ``/api/objects/...``) need to be joined with
 *  the frontend's configured backend origin so the <img> loads. */
function toAbsolute(url) {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://")
      || url.startsWith("data:")) return url;
  // ``api_base()`` already ends with ``/api``; the stored URL starts with
  // ``/api/objects/...`` — strip one ``/api`` to avoid ``/api/api``.
  const base = api_base();
  const origin = base.endsWith("/api") ? base.slice(0, -4) : base;
  return `${origin}${url.startsWith("/") ? "" : "/"}${url}`;
}

export default function BrandLogoSettings() {
  const [tenant, setTenant] = React.useState(null);
  const [pending, setPending] = React.useState(null);   // { file, previewUrl }
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [confirmRemove, setConfirmRemove] = React.useState(false);
  const fileInputRef = React.useRef(null);

  const refresh = React.useCallback(async () => {
    try {
      const t = await api.get("/tenants/current");
      setTenant(t);
    } catch (e) {
      toast.error(`Failed to load tenant: ${e.message || e}`);
    }
  }, []);
  React.useEffect(() => { refresh(); }, [refresh]);

  const currentLogoUrl = tenant?.branding?.logo_url || tenant?.logo_url || null;
  const currentLogoAbsolute = toAbsolute(currentLogoUrl);

  const pickFile = () => {
    setError("");
    if (fileInputRef.current) fileInputRef.current.click();
  };

  const onFileSelected = (evt) => {
    setError("");
    const f = evt?.target?.files?.[0];
    if (!f) return;
    if (!ALLOWED_MIME.has(f.type)) {
      setError(`Unsupported format (${f.type || "unknown"}). Use PNG, SVG, WEBP, or JPEG.`);
      evt.target.value = "";
      return;
    }
    if (f.size > MAX_BYTES) {
      setError(`File too large (${humanBytes(f.size)}). Max is 2 MB.`);
      evt.target.value = "";
      return;
    }
    const previewUrl = URL.createObjectURL(f);
    setPending({ file: f, previewUrl });
    // Reset input so re-picking the same file re-fires the change.
    evt.target.value = "";
  };

  const cancelPending = () => {
    if (pending?.previewUrl) URL.revokeObjectURL(pending.previewUrl);
    setPending(null);
    setError("");
  };

  const uploadPending = async () => {
    if (!pending?.file) return;
    setBusy(true);
    setError("");
    try {
      const fd = new FormData();
      fd.append("logo", pending.file, pending.file.name);
      // Use the existing token helper via a manual fetch — ``api.post``
      // stringifies the body as JSON so we can't reuse it for multipart.
      const resp = await fetch(`${api_base()}/tenants/branding/logo`, {
        method: "POST",
        credentials: "include",
        headers: (() => {
          const tok = localStorage.getItem("token") || "";
          return tok ? { Authorization: `Bearer ${tok}` } : {};
        })(),
        body: fd,
      });
      if (!resp.ok) {
        let body = null;
        try { body = await resp.json(); } catch { body = null; }
        const code = body?.detail?.error_code || body?.detail?.error;
        if (resp.status === 413 || code === "file_too_large") {
          setError("File too large — max 2 MB.");
        } else if (resp.status === 415 || code === "unsupported_media_type") {
          setError("Unsupported format. Use PNG, SVG, WEBP, or JPEG.");
        } else if (resp.status === 503 || code === "object_storage_unavailable") {
          setError("Storage is not ready right now — please try again in a minute.");
        } else {
          setError(body?.detail?.message || body?.detail || `Upload failed (${resp.status}).`);
        }
        return;
      }
      const saved = await resp.json();
      invalidateTenantBrand();       // app-shell re-fetches on next mount
      if (pending.previewUrl) URL.revokeObjectURL(pending.previewUrl);
      setPending(null);
      toast.success("Brand logo updated");
      // Nudge the app-shell to re-render the new logo without a page reload.
      window.dispatchEvent(new CustomEvent("tenant-brand:updated",
                                             { detail: { logo_url: saved.logo_url } }));
      await refresh();
    } catch (e) {
      setError(e?.message || "Upload failed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const removeLogo = async () => {
    setBusy(true);
    setError("");
    try {
      await api.del("/tenants/branding/logo");
      invalidateTenantBrand();
      toast.success("Brand logo removed — reverted to placeholder");
      window.dispatchEvent(new CustomEvent("tenant-brand:updated",
                                             { detail: { logo_url: null } }));
      setConfirmRemove(false);
      await refresh();
    } catch (e) {
      setError(e?.message || "Remove failed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  // Light-and-dark checker pattern so admins spot transparency artefacts.
  const checkerStyle = {
    backgroundColor: "#F8FAFC",
    backgroundImage:
      "linear-gradient(45deg, #E5E7EB 25%, transparent 25%)," +
      "linear-gradient(-45deg, #E5E7EB 25%, transparent 25%)," +
      "linear-gradient(45deg, transparent 75%, #E5E7EB 75%)," +
      "linear-gradient(-45deg, transparent 75%, #E5E7EB 75%)",
    backgroundSize: "20px 20px",
    backgroundPosition: "0 0, 0 10px, 10px -10px, -10px 0px",
  };

  return (
    <div className="p-4 md:p-8 max-w-4xl mx-auto space-y-4"
          data-testid="brand-logo-settings-page">
      <div>
        <h1
          className="text-2xl md:text-3xl font-bold tracking-tight"
          style={{ color: colors.onSurface }}
          data-testid="brand-logo-settings-title"
        >
          <ImageIcon size={20} className="inline mr-2 -mt-0.5"
                      style={{ color: colors.brand }} />
          Brand logo
        </h1>
        <p className="text-sm" style={{ color: colors.muted }}>
          The logo that appears in the app shell (top-left of every page) and
          on your public tenant surfaces.
        </p>
      </div>

      <div
        className="rounded-xl p-4 space-y-4"
        style={{ backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}` }}
        data-testid="brand-logo-settings-card"
      >
        {/* Preview */}
        <div>
          <div className="text-[11px] uppercase tracking-wide font-semibold mb-2"
                style={{ color: colors.muted }}>
            Current logo
          </div>
          <div
            className="w-full h-40 rounded-lg flex items-center justify-center overflow-hidden"
            style={checkerStyle}
            data-testid="brand-logo-preview"
          >
            {pending?.previewUrl ? (
              <img
                src={pending.previewUrl}
                alt="New logo preview"
                className="max-h-32 max-w-full object-contain"
                data-testid="brand-logo-preview-pending"
              />
            ) : currentLogoAbsolute ? (
              <img
                src={currentLogoAbsolute}
                alt="Current brand logo"
                className="max-h-32 max-w-full object-contain"
                data-testid="brand-logo-preview-current"
                onError={(e) => {
                  // Silent fallback — surface the placeholder path so admins
                  // realise the stored URL is broken instead of showing a
                  // broken-image glyph.
                  if (e.currentTarget && !e.currentTarget.src.endsWith("/brand/logo.png")) {
                    e.currentTarget.src = "/brand/logo.png";
                  }
                }}
              />
            ) : (
              <div className="flex flex-col items-center gap-1"
                    data-testid="brand-logo-preview-empty">
                <img src="/brand/logo.png" alt="Placeholder logo"
                      className="max-h-24 max-w-full object-contain opacity-70" />
                <div className="text-[10px] uppercase tracking-widest"
                      style={{ color: colors.muted }}>
                  Placeholder — no custom logo uploaded
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Feb-2026 enhancement — "Last changed <relative> by <name>"
            audit line. Renders ONLY when the backend surfaces both
            ``logo_updated_at`` AND a resolved ``logo_updated_by_name``.
            Empty tenant / never-uploaded state renders nothing. */}
        {tenant?.logo_updated_at && tenant?.logo_updated_by_name ? (
          <div
            className="text-[11px] flex items-center gap-1"
            style={{ color: colors.muted }}
            data-testid="brand-logo-last-changed"
          >
            <span>
              Last changed{" "}
              <span data-testid="brand-logo-last-changed-relative">
                {(() => {
                  try {
                    return formatDistanceToNow(
                      new Date(tenant.logo_updated_at),
                      { addSuffix: true },
                    );
                  } catch {
                    return "recently";
                  }
                })()}
              </span>{" "}
              by{" "}
              <span
                className="font-semibold"
                style={{ color: colors.onSurface }}
                data-testid="brand-logo-last-changed-actor"
              >
                {tenant.logo_updated_by_name}
              </span>
            </span>
          </div>
        ) : null}

        {/* Guidance */}
        <div className="text-xs" style={{ color: colors.muted }}
              data-testid="brand-logo-guidance">
          PNG, SVG, or WebP. Recommended: transparent background,
          at least 256×256, under 2 MB.
        </div>

        {/* Error surface (inline, non-blocking) */}
        {error ? (
          <div
            className="flex items-start gap-2 rounded-md px-3 py-2 text-sm"
            style={{ background: "#FEF2F2", color: "#7F1D1D",
                      border: "1px solid #FCA5A5" }}
            data-testid="brand-logo-error"
          >
            <AlertCircle size={14} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        ) : null}

        {/* Actions */}
        <input
          ref={fileInputRef}
          type="file"
          accept={ALLOWED_EXT_HINT}
          onChange={onFileSelected}
          className="hidden"
          data-testid="brand-logo-file-input"
        />
        {pending ? (
          <div
            className="rounded-md p-3 flex items-center gap-3"
            style={{ background: colors.surfaceSecondary,
                      border: `1px solid ${colors.border}` }}
            data-testid="brand-logo-pending"
          >
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate"
                    style={{ color: colors.onSurface }}
                    data-testid="brand-logo-pending-name">
                {pending.file.name}
              </div>
              <div className="text-[11px]" style={{ color: colors.muted }}
                    data-testid="brand-logo-pending-meta">
                {humanBytes(pending.file.size)} · {pending.file.type || "image"}
              </div>
            </div>
            <button
              type="button"
              onClick={cancelPending}
              disabled={busy}
              className="text-sm px-3 py-1.5 rounded-md"
              style={{ color: colors.muted }}
              data-testid="brand-logo-cancel-btn"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={uploadPending}
              disabled={busy}
              className="text-sm font-semibold px-3 py-1.5 rounded-md text-white flex items-center gap-1.5 disabled:opacity-60"
              style={{ backgroundColor: colors.brand }}
              data-testid="brand-logo-save-btn"
            >
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
              {busy ? "Uploading…" : "Save"}
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={pickFile}
              disabled={busy}
              className="text-sm font-semibold px-3 py-2 rounded-md text-white flex items-center gap-1.5 disabled:opacity-60"
              style={{ backgroundColor: colors.brand }}
              data-testid="brand-logo-upload-btn"
            >
              <Upload size={14} /> {currentLogoUrl ? "Replace logo" : "Upload logo"}
            </button>
            {currentLogoUrl ? (
              <button
                type="button"
                onClick={() => setConfirmRemove(true)}
                disabled={busy}
                className="text-sm font-semibold px-3 py-2 rounded-md flex items-center gap-1.5 disabled:opacity-60"
                style={{
                  backgroundColor: colors.surface,
                  border: `1px solid ${colors.border}`,
                  color: colors.error,
                }}
                data-testid="brand-logo-remove-btn"
              >
                <Trash2 size={14} /> Remove
              </button>
            ) : null}
          </div>
        )}
      </div>

      {/* Remove confirmation */}
      {confirmRemove ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          data-testid="brand-logo-remove-modal"
          onClick={() => { if (!busy) setConfirmRemove(false); }}
        >
          <div
            className="rounded-lg p-5 w-full max-w-md space-y-3 mx-4"
            style={{ backgroundColor: colors.surface,
                      border: `1px solid ${colors.border}` }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="text-lg font-semibold" style={{ color: colors.onSurface }}>
              Remove brand logo?
            </div>
            <div className="text-sm" style={{ color: colors.muted }}>
              The app-shell will fall back to the shipped placeholder logo
              until you upload a new one. This affects every user in your
              tenant right away.
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setConfirmRemove(false)}
                disabled={busy}
                className="text-sm px-3 py-1.5 rounded-md"
                style={{ color: colors.muted }}
                data-testid="brand-logo-remove-cancel-btn"
              >
                Keep it
              </button>
              <button
                type="button"
                onClick={removeLogo}
                disabled={busy}
                className="text-sm font-semibold px-3 py-1.5 rounded-md text-white disabled:opacity-60"
                style={{ backgroundColor: colors.error }}
                data-testid="brand-logo-remove-confirm-btn"
              >
                {busy ? "Removing…" : "Remove logo"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
