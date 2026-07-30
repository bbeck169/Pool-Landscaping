// Phase 2 · Feb-2026 — Share replay modal.
//
// Compact dialog used from the Route Replay panel on Driver Activity.
// Wires the two authed endpoints:
//   POST /api/gps/replay/share
//   POST /api/gps/replay/share/{share_id}/revoke
// Lists existing active shares via GET /api/gps/replay/shares.
import React from "react";
import { toast } from "sonner";
import { Copy, Check, X, Link as LinkIcon, ShieldOff } from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";

function _fmtExpires(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  } catch { return iso; }
}

function _asShareUrl(shareId) {
  // The backend hands us a share_url, but the origin it sees on
  // localhost calls isn't what the customer will open. Recompute from
  // the current window origin so the link is always customer-safe.
  return `${window.location.origin}/replay/${shareId}`;
}

export default function ShareReplayModal({ open, onClose, techId, day }) {
  const [loading, setLoading] = React.useState(false);
  const [creating, setCreating] = React.useState(false);
  const [revoking, setRevoking] = React.useState(false);
  const [copied, setCopied] = React.useState(false);
  const [active, setActive] = React.useState(null); // active share row
  const [error, setError] = React.useState(null);

  const refresh = React.useCallback(async () => {
    if (!techId || !day) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api.get(
        `/gps/replay/shares?user_id=${encodeURIComponent(techId)}&date=${encodeURIComponent(day)}`,
      );
      const first = (res?.items || []).find((r) => r.status === "active");
      setActive(first || null);
    } catch (e) {
      setError(e?.message || "Failed to load shares");
    } finally {
      setLoading(false);
    }
  }, [techId, day]);

  React.useEffect(() => { if (open) refresh(); }, [open, refresh]);
  if (!open) return null;

  const shareUrl = active ? _asShareUrl(active.share_id) : "";

  const create = async () => {
    if (!techId || !day) return;
    setCreating(true);
    setError(null);
    try {
      const res = await api.post("/gps/replay/share", {
        user_id: techId, replay_date: day,
      });
      setActive({
        share_id: res.share_id, expires_at: res.expires_at,
        status: "active", view_count: 0, replay_date: day, user_id: techId,
      });
      toast.success("Share link created");
    } catch (e) {
      setError(e?.message || "Failed to create share");
      toast.error(e?.message || "Failed to create share");
    } finally {
      setCreating(false);
    }
  };

  const revoke = async () => {
    if (!active) return;
    setRevoking(true);
    setError(null);
    try {
      await api.post(`/gps/replay/share/${active.share_id}/revoke`);
      setActive(null);
      setCopied(false);
      toast.success("Share link revoked");
    } catch (e) {
      setError(e?.message || "Failed to revoke");
      toast.error(e?.message || "Failed to revoke");
    } finally {
      setRevoking(false);
    }
  };

  const copy = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      toast.success("Link copied");
      setTimeout(() => setCopied(false), 1800);
    } catch {
      toast.error("Copy failed — copy manually");
    }
  };

  return (
    <div
      data-testid="share-replay-modal"
      role="dialog"
      style={{
        position: "fixed", inset: 0, zIndex: 5000, background: "rgba(15,23,42,0.6)",
        display: "flex", alignItems: "center", justifyContent: "center",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
    >
      <div style={{
        background: colors.surface || "#FFFFFF",
        borderRadius: 14, width: "100%", maxWidth: 520,
        padding: 24, boxShadow: "0 20px 48px rgba(15,23,42,0.24)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <LinkIcon size={18} color={colors.brand || "#0284C7"} />
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: colors.text || "#0F172A" }}>
              Share replay
            </h2>
          </div>
          <button
            data-testid="share-replay-close"
            onClick={onClose}
            style={{ background: "transparent", border: "none", cursor: "pointer", padding: 4, color: colors.muted }}
            aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div style={{ fontSize: 13, color: colors.muted, marginBottom: 20 }}>
          <b>Admins and Super Admins only.</b> Customers cannot view this link.
          Expires in 24 hours.
        </div>

        {loading && (
          <div data-testid="share-replay-loading"
                style={{ fontSize: 13, color: colors.muted }}>Loading…</div>
        )}

        {!loading && !active && (
          <button
            data-testid="share-replay-create"
            onClick={create}
            disabled={creating}
            style={{
              width: "100%", padding: "12px 16px", fontSize: 14, fontWeight: 600,
              background: creating ? "#94A3B8" : (colors.brand || "#0284C7"),
              color: "#FFFFFF", border: "none", borderRadius: 10, cursor: creating ? "wait" : "pointer",
            }}
          >
            {creating ? "Creating…" : "Generate share link"}
          </button>
        )}

        {!loading && active && (
          <>
            <label style={{ fontSize: 12, fontWeight: 600, color: colors.muted, letterSpacing: 0.4, textTransform: "uppercase" }}>
              Share URL
            </label>
            <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <input
                data-testid="share-replay-url"
                readOnly
                value={shareUrl}
                onFocus={(e) => e.target.select()}
                style={{
                  flex: 1, padding: "10px 12px", fontSize: 13, borderRadius: 8,
                  border: `1px solid ${colors.border || "#E2E8F0"}`,
                  background: colors.surfaceMuted || "#F8FAFC",
                  color: colors.text || "#0F172A", fontFamily: "monospace",
                }}
              />
              <button
                data-testid="share-replay-copy"
                onClick={copy}
                style={{
                  padding: "10px 14px", background: copied ? "#16A34A" : (colors.brand || "#0284C7"),
                  color: "#FFFFFF", border: "none", borderRadius: 8, cursor: "pointer",
                  display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600,
                }}>
                {copied ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy</>}
              </button>
            </div>
            <div style={{ fontSize: 12, color: colors.muted, marginTop: 12 }}>
              Expires <b>{_fmtExpires(active.expires_at)}</b>{" "}
              · <span data-testid="share-replay-view-count">{active.view_count ?? 0} views</span>
            </div>

            <button
              data-testid="share-replay-revoke"
              onClick={revoke}
              disabled={revoking}
              style={{
                marginTop: 20, width: "100%", padding: "10px 16px", fontSize: 13,
                background: "transparent", color: "#B91C1C",
                border: "1px solid #FECACA", borderRadius: 10, cursor: revoking ? "wait" : "pointer",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 6, fontWeight: 600,
              }}>
              <ShieldOff size={14} />
              {revoking ? "Revoking…" : "Revoke link"}
            </button>
          </>
        )}

        {error && (
          <div data-testid="share-replay-error"
                style={{ marginTop: 12, padding: 10, background: "#FEF2F2",
                          border: "1px solid #FECACA", borderRadius: 8,
                          color: "#B91C1C", fontSize: 12 }}>{error}</div>
        )}
      </div>
    </div>
  );
}
