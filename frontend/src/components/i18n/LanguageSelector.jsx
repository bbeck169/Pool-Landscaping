// Phase D3 · Feb 2026 — language selector dropdown.
//
// Home for the language switcher — lives in the admin topbar next
// to the Sign-out button. Persists the selection two ways:
//
//   1. localStorage key ``lang`` — instant effect for the current
//      browser + picked up by ``i18n`` on next boot.
//   2. ``PATCH /api/users/me`` with ``{ locale: <code> }`` — so
//      the choice follows the user across browsers and devices.
//
// Both writes are fire-and-forget; a Resend/api-timeout outage
// cannot bound the picker's click handler.
import React, { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Languages, ChevronDown } from "lucide-react";
import { api } from "@/api";
import { SUPPORTED_LOCALES } from "@/i18n";


export default function LanguageSelector({ compact = false }) {
  const { i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = (i18n.language || "en").slice(0, 2);
  const active = SUPPORTED_LOCALES.find((l) => l.code === current)
    || SUPPORTED_LOCALES[0];

  const pick = async (code) => {
    setOpen(false);
    if (code === current) return;
    // 1) Local write — immediate effect.
    try { localStorage.setItem("lang", code); } catch { /* no-op */ }
    // 2) Live change on i18next so the UI re-renders NOW.
    try { await i18n.changeLanguage(code); } catch { /* no-op */ }
    // 3) Fire-and-forget server-side persistence via the shared
    //    ``/users/me`` self-patch endpoint.
    try { await api.patch("/users/me", { locale: code }); }
    catch { /* selector never blocks on API errors */ }
  };

  return (
    <div className="relative inline-block" ref={ref}
         data-testid="language-selector">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 h-8 px-2 rounded-lg text-xs font-semibold shadow-sm text-slate-700 bg-white/90 hover:bg-white border border-slate-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#2563EB] focus-visible:ring-offset-1"
        data-testid="language-selector-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <Languages size={14} />
        {!compact ? (
          <span data-testid="language-selector-current">
            {active.nativeName}
          </span>
        ) : null}
        <ChevronDown size={12} />
      </button>
      {open ? (
        <ul
          role="listbox"
          className="absolute right-0 mt-1 min-w-[160px] rounded-lg bg-white border border-slate-200 shadow-lg z-50 py-1"
          data-testid="language-selector-menu"
        >
          {SUPPORTED_LOCALES.map((l) => (
            <li key={l.code}>
              <button
                type="button"
                role="option"
                aria-selected={l.code === current}
                onClick={() => pick(l.code)}
                className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                data-testid={`language-selector-option-${l.code}`}
              >
                <span>{l.nativeName}</span>
                {l.code === current ? (
                  <span className="text-[10px] text-slate-500">
                    ({l.code})
                  </span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
