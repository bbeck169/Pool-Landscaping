/**
 * Phase 4 · Batch A — "Share to Customer Portal" modal.
 *
 * Opens from the fill page for finalized customer-facing instances.
 * Search box hits `/api/customers?search=...` (existing admin route),
 * user picks a customer, we call `POST /templates/instances/{id}/share-to-portal`.
 */
import React, { useEffect, useMemo, useState } from "react";
import { X, Search, Users, Loader2, Send } from "lucide-react";
import { colors, brandGradientCss } from "@/theme";
import { searchCustomers, shareInstanceToPortal } from "@/api/templates";

export default function SharePortalModal({ open, onClose, instanceId, onShared }) {
  const [query, setQuery] = useState("");
  const [customers, setCustomers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelectedId(null);
    setError("");
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const rows = await searchCustomers();
        if (!cancelled) setCustomers(Array.isArray(rows) ? rows : []);
      } catch (e) {
        if (!cancelled) setError(e.message || "Failed to load customers.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return customers.slice(0, 30);
    return customers.filter((c) =>
      (c.name || "").toLowerCase().includes(q) ||
      (c.email || "").toLowerCase().includes(q) ||
      (c.phone || "").toLowerCase().includes(q) ||
      (c.address || "").toLowerCase().includes(q),
    ).slice(0, 50);
  }, [customers, query]);

  const selected = customers.find((c) => c.id === selectedId) || null;

  const doShare = async () => {
    if (!selected) return;
    setSharing(true);
    setError("");
    try {
      const res = await shareInstanceToPortal(instanceId, selected.id);
      onShared?.({ customer: selected, response: res });
      onClose();
    } catch (e) {
      setError(e.message || "Failed to share.");
    } finally {
      setSharing(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      data-testid="share-portal-modal"
    >
      <div
        className="bg-white rounded-2xl w-full max-w-lg p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        style={{ border: `1px solid ${colors.border}` }}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-bold flex items-center gap-2" style={{ color: colors.onSurface }}>
            <Users size={18} style={{ color: colors.brand }} /> Share to customer portal
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-slate-100"
            style={{ color: colors.onSurfaceSecondary }}
            aria-label="Close"
            data-testid="share-portal-close"
          >
            <X size={16} />
          </button>
        </div>

        <p className="text-sm mb-3" style={{ color: colors.onSurfaceSecondary }}>
          Pick the customer who should see this document in their portal Documents tray.
        </p>

        <div
          className="flex items-center gap-2 px-3 py-2 rounded-xl mb-3"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}` }}
        >
          <Search size={14} style={{ color: colors.muted }} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name, email, phone, address…"
            className="flex-1 outline-none text-sm bg-transparent"
            data-testid="share-portal-search"
          />
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 rounded-lg text-sm" style={{ backgroundColor: "#FEE2E2", color: colors.error }} data-testid="share-portal-error">
            {error}
          </div>
        )}

        <div
          className="rounded-xl overflow-y-auto mb-4"
          style={{ border: `1px solid ${colors.border}`, maxHeight: 260 }}
          data-testid="share-portal-list"
        >
          {loading ? (
            <div className="p-4 text-sm inline-flex items-center gap-2" style={{ color: colors.muted }}>
              <Loader2 size={13} className="animate-spin" /> Loading customers…
            </div>
          ) : filtered.length === 0 ? (
            <div className="p-4 text-sm" style={{ color: colors.muted }}>
              No customers match your search.
            </div>
          ) : (
            filtered.map((c) => {
              const active = selectedId === c.id;
              return (
                <button
                  key={c.id}
                  onClick={() => setSelectedId(c.id)}
                  className="w-full text-left px-3 py-2 flex items-center justify-between gap-2"
                  style={{
                    backgroundColor: active ? colors.brandTertiary : "transparent",
                    borderBottom: `1px solid ${colors.border}`,
                    color: colors.onSurface,
                  }}
                  data-testid={`share-portal-row-${c.id}`}
                >
                  <div>
                    <div className="text-sm font-bold">{c.name || "(no name)"}</div>
                    <div className="text-[11px]" style={{ color: colors.muted }}>
                      {[c.email, c.phone].filter(Boolean).join(" · ") || c.address || ""}
                    </div>
                  </div>
                  {active && <span className="text-[10px] font-bold" style={{ color: colors.brand }}>Selected</span>}
                </button>
              );
            })
          )}
        </div>

        <div className="flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-2 rounded-xl text-sm font-semibold"
            style={{ backgroundColor: colors.surface, color: colors.onSurface, border: `1px solid ${colors.border}` }}
            data-testid="share-portal-cancel"
          >
            Cancel
          </button>
          <button
            onClick={doShare}
            disabled={!selected || sharing}
            className="inline-flex items-center gap-1 px-3 py-2 rounded-xl text-sm font-bold text-white disabled:opacity-60"
            style={{ background: brandGradientCss }}
            data-testid="share-portal-confirm"
          >
            {sharing ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
            {sharing ? "Sharing…" : selected ? `Share to ${selected.name}` : "Pick a customer"}
          </button>
        </div>
      </div>
    </div>
  );
}
