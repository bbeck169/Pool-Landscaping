import {
  LayoutDashboard, Briefcase, CalendarDays, Truck, Route, Workflow, DoorOpen,
  Users, UserPlus, FileText, Calculator, Receipt, CreditCard, Repeat, DollarSign, Layers,
  UsersRound, UserCog, Clock, Timer, ShieldCheck, Wrench, BookOpen, Cog, Waves, History,
  Timer as TimerIcon, BarChart3, TrendingUp, PieChart, MegaphoneIcon, Megaphone, Palette,
  MessageSquare, Bell, CheckSquare, Bot, ListChecks, Send, Star as StarIcon, Search,
  Sparkles, Ruler, Image, MapPin, Sun, IdCard, Search as SearchIcon, Globe, FileEdit,
  BadgeCheck, Shield, Bell as BellIcon, Settings, MapIcon, ScrollText,
  Grid3x3, Compass, Rss, Wand2, PencilRuler, Building2,
  Map as MapPinIcon, Gauge, Timer as StopwatchIcon,
} from "lucide-react";

/**
 * Phase 15 — Admin navigation single-source-of-truth.
 * Each entry: { to, label, icon, feature (for permissions gate), hard_rule? }
 * Groups render as collapsible sections. Sub-groupings are noted via `subsection`.
 */
export const ADMIN_NAV_V2 = [
  { key: "overview", label: "Overview", icon: LayoutDashboard, entries: [
    { to: "/", label: "Dashboard", icon: LayoutDashboard, feature: "dashboard" },
  ]},

  { key: "work", label: "Work", icon: Briefcase, entries: [
    { to: "/jobs",       label: "Jobs",       icon: Briefcase,   feature: "jobs" },
    { to: "/schedule",   label: "Schedule",   icon: CalendarDays, feature: "jobs" },
    { to: "/dispatch",   label: "Dispatch",   icon: Truck,       feature: "jobs" },
    { to: "/routes",     label: "Routes",     icon: Route,       feature: "jobs" },
    { to: "/workstream", label: "Workstream", icon: Workflow,    feature: "jobs" },
  ]},

  { key: "sales", label: "Sales", icon: DoorOpen, entries: [
    { to: "/leads",         label: "Leads",         icon: UserPlus,    feature: "customers" },
    { to: "/leads/request", label: "Lead Requests", icon: Send,        feature: "customers" },
    { to: "/customers",     label: "Customers",     icon: Users,       feature: "customers" },
    { to: "/quotes",     label: "Quotes",     icon: FileText,    feature: "quotes" },
    { to: "/estimator",  label: "Estimator",  icon: Calculator,  feature: "estimator" },
    { to: "/d2d",        label: "D2D",        icon: DoorOpen,    feature: "d2d",    hard_rule: "admin_only" },
  ]},

  { key: "billing", label: "Billing", icon: Receipt, entries: [
    { to: "/invoices",         label: "Invoices",        icon: Receipt,   feature: "invoices" },
    { to: "/payments",         label: "Payments",        icon: CreditCard,feature: "payments" },
    { to: "/auto-billing",     label: "Auto-billing",    icon: Repeat,    feature: "invoices" },
    { to: "/settings/late-fees", label: "Late Fees",     icon: DollarSign,feature: "invoices" },
    { to: "/settings/billing",   label: "Billing Rules", icon: Cog,       feature: "invoices" },
    { to: "/master-invoices",  label: "Master Invoices", icon: Layers,    feature: "invoices" },
  ]},

  { key: "ops", label: "Ops", icon: UsersRound, entries: [
    { to: "/team",         label: "Team",        icon: UsersRound, feature: "jobs" },
    { to: "/crews",        label: "Crews",       icon: UserCog,    feature: "jobs" },
    { to: "/timesheets",   label: "Timesheets",  icon: Clock,      feature: "jobs" },
    { to: "/timeclock/today", label: "Timeclock",icon: Timer,      feature: "jobs" },
    { to: "/coverage",     label: "Coverage",    icon: ShieldCheck,feature: "jobs" },
    { to: "/equipment",    label: "Equipment",   icon: Wrench,     feature: "jobs" },
    { to: "/admin/assets", label: "Assets",      icon: Wrench,     feature: "jobs" },
    { to: "/price-book",   label: "Price Book",  icon: BookOpen,   feature: "jobs" },
    { to: "/maintenance",  label: "Maintenance", icon: Cog,        feature: "jobs" },
    { to: "/pool-service", label: "Pool Service",icon: Waves,      feature: "jobs" },
    { to: "/log-history",  label: "Log History", icon: History,    feature: "jobs" },
    { to: "/job-timers",   label: "Job Timers",  icon: TimerIcon,  feature: "jobs" },
    { to: "/avg-job-time", label: "Avg Job Time",icon: TrendingUp, feature: "jobs" },
    { to: "/checkins",     label: "Check-ins",   icon: MapPin,     feature: "jobs" },
  ]},

  { key: "workforce", label: "Workforce", icon: StopwatchIcon, entries: [
    { to: "/workforce/timesheets",  label: "Timesheets",  icon: Clock,       feature: "jobs" },
    { to: "/workforce/crew-map",    label: "Crew Map",    icon: MapPinIcon,  feature: "jobs" },
    { to: "/workforce/job-costing", label: "Job Costing", icon: Gauge,       feature: "reports" },
    { to: "/workforce/mileage",     label: "Mileage",     icon: TrendingUp,  feature: "reports" },
  ]},

  { key: "business_os", label: "Business OS", icon: Compass, entries: [
    { to: "/os/dashboard",  label: "Four Pillars", icon: Compass,       feature: "settings" },
    { to: "/os/sops",       label: "SOPs",         icon: BookOpen,      feature: "settings" },
    { to: "/os/roles",      label: "Roles",        icon: UsersRound,    feature: "settings" },
    { to: "/os/scorecards", label: "Scorecards",   icon: Gauge,         feature: "settings" },
    { to: "/os/huddle",     label: "Huddles",      icon: MessageSquare, feature: "settings" },
    { to: "/os/leanboards", label: "LeanBoards",   icon: ListChecks,    feature: "settings" },
    { to: "/os/sprints",    label: "Sprints",      icon: Workflow,      feature: "settings" },
    { to: "/os/lana",       label: "Lana AI",      icon: Sparkles,      feature: "settings" },
  ]},

  { key: "social", label: "Social", icon: Rss, entries: [
    { to: "/social/composer",     label: "Composer",     icon: FileEdit,     feature: "marketing" },
    { to: "/social/calendar",     label: "Calendar",     icon: CalendarDays, feature: "marketing" },
    { to: "/social/library",      label: "Library",      icon: Image,        feature: "marketing" },
    { to: "/social/drafts",       label: "Drafts",       icon: ListChecks,   feature: "marketing" },
    { to: "/social/approvals",    label: "Approvals",    icon: BadgeCheck,   feature: "marketing" },
    { to: "/social/bulk-upload",  label: "Bulk Upload",  icon: FileEdit,     feature: "marketing" },
    { to: "/social/short-links",  label: "Short Links",  icon: MapPin,       feature: "marketing" },
    { to: "/social/brand-kit",    label: "Brand Kit",    icon: Palette,      feature: "marketing" },
  ]},

  { key: "reports", label: "Reports", icon: BarChart3, entries: [
    { to: "/reports",                     label: "Reports Hub",       icon: BarChart3, feature: "reports" },
    { to: "/analytics",                   label: "Analytics",         icon: TrendingUp, feature: "reports" },
    { to: "/reports/business-summary",    label: "Business Summary",  icon: PieChart,  feature: "reports" },
    { to: "/reports/forecast",            label: "Forecast",          icon: TrendingUp,feature: "reports" },
    { to: "/reports/revenue-slices",      label: "Revenue Slices",    icon: PieChart,  feature: "reports" },
    { to: "/income-by-category",          label: "Income by Category",icon: DollarSign,feature: "reports" },
  ]},

  { key: "marketing", label: "Marketing", icon: Megaphone, entries: [
    { to: "/marketing",           label: "Studio",       icon: Palette,      feature: "marketing", subsection: "Studio" },
    { to: "/marketing/campaigns", label: "Campaigns",    icon: Megaphone,    feature: "marketing", subsection: "Studio" },
    { to: "/marketing/posts",     label: "Posts",        icon: FileText,     feature: "marketing", subsection: "Studio" },
    { to: "/marketing/queue",     label: "Approval Queue", icon: ListChecks, feature: "marketing", subsection: "Studio" },
    { to: "/marketing/calendar",  label: "Calendar",     icon: CalendarDays, feature: "marketing", subsection: "Studio" },
    { to: "/marketing/performance", label: "Performance",icon: BarChart3,    feature: "marketing", subsection: "Studio" },
    { to: "/marketing/sequences", label: "Sequences",    icon: Workflow,     feature: "marketing", subsection: "Sequences" },
    { to: "/marketing/templates", label: "Templates",    icon: FileText,     feature: "marketing", subsection: "Sequences" },
    { to: "/marketing/reviews",   label: "Reviews",      icon: StarIcon,     feature: "marketing", subsection: "Public" },
    { to: "/csat",                label: "CSAT / NPS",   icon: Sparkles,     feature: "marketing", subsection: "Public" },
    { to: "/forms",               label: "Forms",        icon: FileEdit,     feature: "marketing", subsection: "Public" },
    { to: "/marketing/brand",     label: "Brand Memory", icon: Palette,      feature: "marketing", subsection: "Config" },
    { to: "/ai-employees",        label: "AI Employees", icon: Bot,          feature: "ai_employees", subsection: "AI & Comms" },
    { to: "/communications",      label: "Communications", icon: MessageSquare, feature: "marketing", subsection: "AI & Comms" },
    { to: "/admin/portal-inbox",  label: "Portal Inbox",   icon: MessageSquare, feature: "marketing", subsection: "AI & Comms" },
    { to: "/admin/appointments",  label: "Appointments",   icon: CalendarDays,  feature: "jobs",       subsection: "AI & Comms" },
    { to: "/admin/onboarding/templates", label: "Onboarding Templates", icon: FileText, feature: "settings", subsection: "AI & Comms" },
    { to: "/admin/onboarding/queue",     label: "Onboarding Queue",     icon: ListChecks, feature: "settings", subsection: "AI & Comms" },
    { to: "/admin/referrals/analytics",  label: "Referral Analytics",   icon: BarChart3,  feature: "marketing", subsection: "AI & Comms" },
    { to: "/admin/referrals/settings",   label: "Referral Tiers",       icon: StarIcon,   feature: "marketing", subsection: "AI & Comms" },
    { to: "/notifications",       label: "Notifications",icon: BellIcon,     feature: "marketing", subsection: "AI & Comms" },
    { to: "/tasks",               label: "Tasks",        icon: CheckSquare,  feature: "marketing", subsection: "AI & Comms" },
  ]},

  { key: "seo_gbp", label: "SEO & GBP", icon: SearchIcon, entries: [
    { to: "/seo",              label: "SEO Hub",       icon: SearchIcon, feature: "seo" },
    { to: "/seo/articles",     label: "Articles",      icon: FileText,   feature: "seo" },
    { to: "/seo/keywords",     label: "Keywords",      icon: Rss,        feature: "seo" },
    { to: "/seo/audit",        label: "Audit",         icon: BadgeCheck, feature: "seo" },
    { to: "/seo/rank-grid",    label: "Rank Grid",     icon: Grid3x3,    feature: "seo" },
    { to: "/seo/wordpress",    label: "WordPress",     icon: Globe,      feature: "seo" },
    { to: "/admin/seo/audits",         label: "Site Auditor",     icon: BadgeCheck, feature: "seo" },
    { to: "/admin/seo/content-scorer", label: "Content Scorer",   icon: FileText,   feature: "seo" },
    { to: "/admin/seo/rank-heatmap",   label: "Rank Heatmap",     icon: Grid3x3,    feature: "seo" },
    { to: "/gbp",              label: "GBP Hub",       icon: Building2,  feature: "gbp" },
    { to: "/gbp/posts",        label: "GBP Posts",     icon: FileText,   feature: "gbp" },
    { to: "/gbp/reviews",      label: "GBP Reviews",   icon: StarIcon,   feature: "gbp" },
    { to: "/gbp/business",     label: "GBP Business",  icon: Building2,  feature: "gbp" },
  ]},

  { key: "ai_tools", label: "AI Tools", icon: Wand2, entries: [
    { to: "/landscape",   label: "Landscape AI",     icon: Image,       feature: "landscape",   hard_rule: "admin_only" },
    { to: "/cad",         label: "CAD Studio",       icon: PencilRuler, feature: "cad",         hard_rule: "admin_only" },
    { to: "/measure",     label: "Satellite Measure",icon: Ruler,       feature: "measure",     hard_rule: "admin_only" },
    { to: "/virtual-bid", label: "Virtual Bid",      icon: Sparkles,    feature: "virtual_bid", hard_rule: "admin_only" },
    { to: "/weather",     label: "Weather",          icon: Sun,         feature: "weather",     hard_rule: "admin_only" },
    { to: "/card",        label: "Digital Card",     icon: IdCard,      feature: "card" },
  ]},

  { key: "settings", label: "Settings", icon: Settings, entries: [
    { to: "/settings/onboarding",    label: "Onboarding",      icon: Sparkles,    feature: "settings" },
    { to: "/settings/tenant",        label: "Tenant Brand",    icon: Sparkles,    feature: "settings" },
    { to: "/tenants",                label: "Tenants (super)", icon: Shield,      feature: "settings", hard_rule: "super_admin_only" },
    { to: "/access-settings",        label: "Access Settings", icon: Shield,      feature: "permissions" },
    { to: "/access-history",         label: "Access History",  icon: ScrollText,  feature: "audit_logs" },
    { to: "/settings/integrations",  label: "Integrations",    icon: Compass,     feature: "settings" },
    { to: "/settings/maps",          label: "Maps",            icon: MapIcon,     feature: "settings" },
    { to: "/settings/terms",         label: "Terms",           icon: ScrollText,  feature: "settings" },
    { to: "/settings/legal",         label: "Legal Docs",      icon: ScrollText,  feature: "settings" },
    { to: "/settings/payment-handles", label: "Payment Handles", icon: CreditCard,feature: "settings" },
    { to: "/settings/ringcentral",   label: "RingCentral",     icon: Bell,        feature: "settings" },
  ]},
];

// Flatten for the command palette page-search.
export const NAV_FLAT = ADMIN_NAV_V2.flatMap((g) =>
  g.entries.map((e) => ({ ...e, group: g.label }))
);

export const KEYBOARD_SHORTCUTS = [
  { keys: "⌘K / Ctrl+K", label: "Open command palette" },
  { keys: "G then D", label: "Dashboard" },
  { keys: "G then J", label: "Jobs" },
  { keys: "G then C", label: "Customers" },
  { keys: "G then I", label: "Invoices" },
  { keys: "G then Q", label: "Quotes" },
  { keys: "G then R", label: "Reports Hub" },
  { keys: "G then M", label: "Marketing Studio" },
  { keys: "G then S", label: "Settings" },
  { keys: "?", label: "Show this help" },
];

export const SHORTCUT_TARGETS = {
  d: "/", j: "/jobs", c: "/customers", i: "/invoices",
  q: "/quotes", r: "/reports", m: "/marketing", s: "/access-settings",
};
