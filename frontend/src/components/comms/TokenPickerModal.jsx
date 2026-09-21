/**
 * TokenPickerModal — Phase 2 (Feb 2026).
 *
 * Searchable list of all available comm-tokens (``GET /comms/tokens``).
 * Used by the email subject input, email text blocks, and SMS body.
 */
import React, { useEffect, useMemo, useState } from "react";
import { X, Search } from "lucide-react";
import { getTokensCatalog } from "@/api/comms";
import { colors } from "@/theme";

export default function TokenPickerModal({ open, onClose, onInsert }) {
  const [tokens, setTokens] = useState([]);
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!open) return;
    getTokensCatalog().then((d) => {
      const list = (d.tokens || []).map((t) => ({
        name: t.name || t.token || "",
        label: t.label || "",
        sample: (t.sample_value != null ? t.sample_value : t.sample) ?? "",
      }));
      setTokens(list);
    }).catch(() => setTokens([]));
  }, [open]);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return tokens;
    return tokens.filter((t) => t.name.toLowerCase().includes(s) || (t.label || "").toLowerCase().includes(s));
  }, [tokens, q]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
         style={{ backgroundColor: "rgba(0,0,0,0.55)" }}
         onClick={onClose}
         data-testid="token-picker-backdrop">
      <div className="rounded-2xl w-full max-w-lg shadow-xl overflow-hidden"
           style={{ background: colors.surface, border: `1px solid ${colors.border}` }}
           onClick={(e) => e.stopPropagation()}
           data-testid="token-picker-modal">
        <div className="px-4 py-3 flex items-center justify-between"
             style={{ borderBottom: `1px solid ${colors.border}` }}>
          <div className="font-bold text-base" style={{ color: colors.onSurface }}>
            Insert token
          </div>
          <button onClick={onClose} aria-label="Close"
                  data-testid="token-picker-close">
            <X size={18} style={{ color: colors.muted }} />
          </button>
        </div>
        <div className="px-4 py-2 flex items-center gap-2"
             style={{ borderBottom: `1px solid ${colors.border}` }}>
          <Search size={14} style={{ color: colors.searchIcon }} />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter tokens…"
            className="w-full text-sm outline-none bg-transparent"
            style={{ color: colors.onSurface }}
            data-testid="token-picker-search"
          />
        </div>
        <div className="max-h-96 overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="text-sm text-center py-8" style={{ color: colors.muted }}>
              No tokens match "{q}"
            </div>
          ) : filtered.map((t) => (
            <button
              key={t.name}
              onClick={() => { onInsert(`{{${t.name}}}`); onClose(); }}
              className="w-full text-left px-4 py-2.5 hover:opacity-80"
              style={{ borderBottom: `1px solid ${colors.border}` }}
              data-testid={`token-picker-item-${t.name}`}
            >
              <div className="text-sm font-mono font-semibold" style={{ color: colors.brand }}>
                {`{{${t.name}}}`}
              </div>
              <div className="text-xs" style={{ color: colors.muted }}>
                {t.label} {t.sample ? `· sample: ${String(t.sample).slice(0, 40)}` : ""}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
