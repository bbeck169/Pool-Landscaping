/**
 * Phase L1.4 · Feb-2026 — Global "Quick Add" dropdown.
 *
 * Circular ``+`` trigger in the topbar right cluster; opens a
 * dropdown menu with 4 create entrypoints (Lead · Job · Estimate ·
 * Customer). Gated to ``admin | super_admin | manager`` — techs and
 * customers never see it.
 *
 * Route destinations grepped from ``App.js``:
 *   - Lead     → ``/leads/new``   (placeholder route; still lands
 *                                    on the leads dashboard for now)
 *   - Job      → ``/jobs/new``    (JobNew)
 *   - Estimate → ``/quotes/new``  (QuoteInvoiceNew)
 *   - Customer → ``/customers/new`` (CustomerForm)
 */
import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, UserPlus, Briefcase, FileText, ClipboardList } from "lucide-react";

import { useAuth } from "@/auth";
import { colors, gradients } from "@/theme";


const _MENU = [
  { key: "lead",     label: "New Lead",     icon: ClipboardList,
    to: "/leads/new" },
  { key: "job",      label: "New Job",      icon: Briefcase,
    to: "/jobs/new" },
  { key: "estimate", label: "New Estimate", icon: FileText,
    to: "/quotes/new" },
  { key: "customer", label: "New Customer", icon: UserPlus,
    to: "/customers/new" },
];


export default function QuickAddButton() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);
  const role = auth?.user?.role;

  useEffect(() => {
    if (!open) return;
    const onDoc = (ev) => {
      if (!wrap.current || !wrap.current.contains(ev.target)) {
        setOpen(false);
      }
    };
    const onEsc = (ev) => { if (ev.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  if (role !== "admin" && role !== "super_admin" && role !== "manager") {
    return null;
  }

  return (
    <div className="relative" ref={wrap}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center justify-center h-8 w-8 rounded-full text-white shadow-sm hover:brightness-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
        style={{ background: gradients.navyToGreen.css }}
        data-testid="topbar-quick-add-btn"
        aria-label="Quick add"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Plus size={16} />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-52 rounded-xl shadow-lg z-40 py-1"
          style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
          }}
          data-testid="topbar-quick-add-menu"
        >
          {_MENU.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  navigate(item.to);
                }}
                data-testid={`topbar-quick-add-${item.key}`}
                className="w-full text-left flex items-center gap-2 px-3 py-2 text-sm hover:bg-black/[.04]"
                style={{ color: colors.onSurface }}
              >
                <Icon size={14} style={{ color: colors.muted }} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
