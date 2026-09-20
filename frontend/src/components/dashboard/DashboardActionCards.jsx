/**
 * Phase L1.5 · Feb-2026 — Dashboard Action Cards row.
 *
 * Fetches ``GET /api/dashboard/action-cards`` on mount + every 60 s.
 * Renders 7 clickable cards; each card auto-hides when count is 0
 * EXCEPT the Intelligence Alerts card (always visible so the
 * operator has a stable link into the alerts page).
 *
 * Role-scoped upstream — parent (``Dashboard.jsx``) mounts this
 * component only for admin / super_admin / manager. Backend
 * mirrors the gate (403 ``insufficient_role_for_dashboard``).
 */
import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Truck, ClipboardCheck, DollarSign, AlertOctagon,
  Users, Bell, AlertTriangle,
} from "lucide-react";

import { api } from "@/api";
import { colors } from "@/theme";


const _POLL_MS = 60_000;


const _CARDS = [
  { key: "today_routes",          label: "Today's Routes",
    icon: Truck,           href: "/routes/today",
    accent: "#0284C7" },
  { key: "pending_checkins",      label: "Approve Check-ins",
    icon: ClipboardCheck,  href: "/admin/checkins",
    accent: "#0EA5E9" },
  { key: "unpaid_invoices",       label: "Unpaid Invoices",
    icon: DollarSign,      href: "/invoices?status=unpaid",
    accent: "#F59E0B" },
  { key: "overdue_invoices",      label: "Overdue Invoices",
    icon: AlertOctagon,    href: "/invoices?status=overdue",
    accent: "#DC2626" },
  { key: "new_leads_today",       label: "New Leads Today",
    icon: Users,           href: "/admin/leads?filter=today",
    accent: "#7C3AED" },
  { key: "open_alerts",           label: "Open Intelligence Alerts",
    icon: Bell,            href: "/admin/intelligence/alerts",
    accent: "#0284C7",     alwaysShow: true },
  { key: "missed_services_today", label: "Missed Services Today",
    icon: AlertTriangle,
    href: "/admin/intelligence/alerts?category=missed_service",
    accent: "#DC2626" },
];


export default function DashboardActionCards() {
  const navigate = useNavigate();
  const [counts, setCounts] = useState(null);
  const [error,  setError]  = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/dashboard/action-cards");
      setCounts(r || {});
      setError("");
    } catch (e) {
      setError((e && e.message) || "Failed to load dashboard summary");
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(load, _POLL_MS);
    return () => clearInterval(t);
  }, [load]);

  // First-load skeleton — keep it terse; parent already has a
  // heavy dashboard-wide loader.
  if (counts === null && !error) {
    return (
      <div
        className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2 mb-4"
        data-testid="dashboard-action-cards-skeleton"
      >
        {[0, 1, 2, 3, 4, 5, 6].map((k) => (
          <div key={k}
                className="h-20 rounded-xl animate-pulse"
                style={{ background: colors.surfaceSecondary }} />
        ))}
      </div>
    );
  }

  const visible = _CARDS.filter((c) =>
    (c.alwaysShow || (counts?.[c.key] || 0) > 0));

  if (!visible.length) {
    // Empty tenant — hide the row entirely.
    return null;
  }

  return (
    <div
      className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-2 mb-4"
      data-testid="dashboard-action-cards"
    >
      {visible.map((card) => {
        const Icon = card.icon;
        const n = counts?.[card.key] || 0;
        return (
          <button
            key={card.key}
            type="button"
            onClick={() => navigate(card.href)}
            data-testid={`dashboard-action-card-${card.key}`}
            className="rounded-xl p-3 text-left transition-colors hover:opacity-95 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-1"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              borderLeft: `4px solid ${card.accent}`,
            }}
          >
            <div className="flex items-center gap-2 mb-1">
              <Icon size={14} style={{ color: card.accent }} />
              <span className="text-[11px] font-semibold uppercase tracking-wide"
                     style={{ color: colors.muted }}>
                {n}
              </span>
            </div>
            <div className="text-xs font-medium leading-tight"
                   style={{ color: colors.onSurface }}>
              {card.label}
            </div>
          </button>
        );
      })}
    </div>
  );
}
