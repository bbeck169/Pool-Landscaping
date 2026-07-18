/**
 * All My Tools — technician navigation hub (web).
 *
 * Mirrors the mobile /(app)/tools screen: sectioned grid of tiles that route
 * to every page a tech can access, with a live search. Non-tech / non-admin
 * roles get redirected home so the page can't be used to escalate visibility.
 */
import React, { useMemo, useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth";
import { brandGradientCss, colors, font } from "@/theme";
import {
  Search as SearchIcon, X as XIcon,
  CalendarDays, DoorOpen, Clock, MessageSquare,
  Calculator, FlaskConical, Home as HomeIcon, Boxes, Wrench, Magnet,
  ClipboardList, Trophy, IdCard, DollarSign, TrendingUp,
  UserCircle, MapPin,
} from "lucide-react";
const TECH_SECTIONS = [
  {
    key: "daily",
    title: "Daily Work",
    tiles: [
      { key: "schedule", icon: CalendarDays, label: "Schedule", desc: "Day / Week / Month calendar", to: "/schedule" },
      { key: "d2d", icon: DoorOpen, label: "D2D Canvassing", desc: "Log knocks & book leads", to: "/d2d" },
      { key: "time-clock", icon: Clock, label: "Time Clock", desc: "Clock in / out, breaks, mileage", to: "/tech/time-clock" },
      { key: "huddle", icon: MessageSquare, label: "Daily Huddle", desc: "Post yesterday / today / blockers", to: "/tech/huddle" },
    ],
  },
  {
    key: "job",
    title: "On the Job",
    tiles: [
      { key: "estimator", icon: Calculator, label: "Field Estimator", desc: "Quote on the spot", to: "/estimator" },
      { key: "pool-calculators", icon: FlaskConical, label: "Pool Calculators", desc: "LSI · Volume · Salt · Turnover · Heater size", to: "/tech/tools/calculators" },
      { key: "property-lookup", icon: HomeIcon, label: "Property Lookup", desc: "Owner, lot size, notes (Zillow)", to: "/tech/property-lookup" },
      { key: "d2d-map", icon: MapPin, label: "D2D Map", desc: "Canvassing map", to: "/d2d/map" },
      { key: "d2d-knocks", icon: DoorOpen, label: "Knocks", desc: "Recent door activity", to: "/d2d/knocks" },
      { key: "d2d-open-leads", icon: Magnet, label: "Open Leads", desc: "Follow-ups in your funnel", to: "/d2d/open-leads" },
    ],
  },
  {
    key: "records",
    title: "My Records",
    tiles: [
      { key: "onboarding", icon: ClipboardList, label: "My Onboarding", desc: "Checklist steps assigned to me", to: "/onboarding/mine" },
      { key: "d2d-leaderboard", icon: Trophy, label: "D2D Leaderboard", desc: "See where your knocks rank", to: "/d2d/leaderboard" },
      { key: "business-card", icon: IdCard, label: "Business Card", desc: "Your NFC-ready digital card & .vcf", to: "/tech/card" },
    ],
  },
  {
    key: "account",
    title: "Account",
    tiles: [
      { key: "profile", icon: UserCircle, label: "Profile", desc: "Name, email, sign out", to: "/portal/profile" },
    ],
  },
];

const ADMIN_SECTIONS = [
  {
    key: "adm-tools",
    title: "Tools",
    tiles: [
      { key: "business-card", icon: IdCard, label: "Business Card", desc: "NFC-ready digital card & .vcf", to: "/tech/card" },
      { key: "estimator", icon: Calculator, label: "Field Estimator", desc: "Build a quote on-site", to: "/estimator" },
      { key: "pool-calculators", icon: FlaskConical, label: "Pool Calculators", desc: "LSI · Volume · Salt · Turnover · Heater size", to: "/tech/tools/calculators" },
      { key: "property-lookup", icon: HomeIcon, label: "Property Lookup", desc: "Owner + lot size search", to: "/property-lookup" },
      { key: "inventory", icon: Boxes, label: "Inventory", desc: "Stock & purchase orders", to: "/admin/inventory" },
      { key: "pricing-tools", icon: DollarSign, label: "Pricing Tools", desc: "In-cost · Portfolio margins · Price recommender", to: "/admin/tools/pricing" },
      { key: "analysis-tools", icon: TrendingUp, label: "Business Analysis", desc: "Route valuation · Pay model comparator", to: "/admin/tools/analysis" },
      { key: "document-generators", icon: ClipboardList, label: "Document Generators", desc: "Printable checklist templates · Quick service reports", to: "/admin/tools/documents" },
      { key: "checks", icon: Wrench, label: "Check Register", desc: "Write checks, batch payroll", to: "/admin/checks" },
      { key: "dispatch", icon: CalendarDays, label: "Dispatch", desc: "Assign & auto-route jobs", to: "/admin/dispatch" },
    ],
  },
];

function Tile({ tile, onGo }) {
  const Icon = tile.icon;
  return (
    <button
      onClick={onGo}
      className="text-left rounded-2xl p-4 flex items-start gap-3 transition hover:brightness-95"
      style={{
        backgroundColor: colors.surface,
        border: `1px solid ${colors.border}`,
      }}
      data-testid={`tools-tile-${tile.key}`}
    >
      <div
        className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
        style={{ backgroundColor: colors.brandTertiary, color: colors.brand }}
      >
        <Icon size={20} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold" style={{ color: colors.onSurface }}>
          {tile.label}
        </div>
        <div className="text-xs mt-0.5 line-clamp-2" style={{ color: colors.muted }}>
          {tile.desc}
        </div>
      </div>
    </button>
  );
}

export default function ToolsHub() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  const role = user?.role;
  const isTech = role === "technician";
  const isAdmin = role === "admin" || role === "super_admin";

  const sections = isAdmin ? ADMIN_SECTIONS : TECH_SECTIONS;
  const q = query.trim().toLowerCase();
  const filtered = useMemo(() => {
    if (!q) return sections;
    return sections
      .map((s) => ({ ...s, tiles: s.tiles.filter((t) => t.label.toLowerCase().includes(q) || t.desc.toLowerCase().includes(q)) }))
      .filter((s) => s.tiles.length > 0);
  }, [q, sections]);
  const total = sections.reduce((a, s) => a + s.tiles.length, 0);

  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  // Customers can't peek at tech tooling; bounce them to their portal.
  if (!isTech && !isAdmin) {
    return <Navigate to="/portal/home" replace />;
  }

  return (
    <div
      className="min-h-full p-4 md:p-8 max-w-5xl mx-auto"
      style={{ fontFamily: font.family }}
      data-testid="tools-hub"
    >
      <div className="mb-6">
        <div
          className="inline-block text-xs font-semibold px-3 py-1 rounded-full mb-3"
          style={{ background: brandGradientCss, color: "#fff" }}
        >
          {isAdmin ? "Admin toolkit" : "Field toolkit"}
        </div>
        <h1
          className="text-3xl md:text-4xl font-bold"
          style={{ color: colors.onSurface }}
          data-testid="tools-hub-title"
        >
          All My Tools
        </h1>
        <p className="text-sm mt-1" style={{ color: colors.muted }}>
          {isAdmin ? "Jump into any workflow — no digging through the menu." : `${total} tools available to you today.`}
        </p>
      </div>

      <div
        className="flex items-center gap-2 rounded-xl px-3 mb-6"
        style={{
          backgroundColor: colors.surface,
          border: `1px solid ${colors.border}`,
          height: 44,
        }}
      >
        <SearchIcon size={16} style={{ color: colors.muted }} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search tools…"
          className="flex-1 bg-transparent outline-none text-sm"
          style={{ color: colors.onSurface }}
          data-testid="tools-search"
        />
        {query.length > 0 && (
          <button
            type="button"
            onClick={() => setQuery("")}
            className="p-1 rounded-md"
            style={{ color: colors.muted }}
            data-testid="tools-search-clear"
            aria-label="Clear search"
          >
            <XIcon size={14} />
          </button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div
          className="rounded-2xl py-10 text-center text-sm"
          style={{ backgroundColor: colors.surface, border: `1px solid ${colors.border}`, color: colors.muted }}
          data-testid="tools-empty"
        >
          No tools match “{query}”.
        </div>
      ) : (
        filtered.map((s) => (
          <div key={s.key} className="mb-8" data-testid={`tools-section-${s.key}`}>
            <div
              className="text-[11px] font-semibold uppercase tracking-widest mb-2"
              style={{ color: colors.onSurfaceSecondary }}
            >
              {s.title}
            </div>
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3">
              {s.tiles.map((t) => (
                <Tile key={t.key} tile={t} onGo={() => navigate(t.to)} />
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
