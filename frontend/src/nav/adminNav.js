import {
  LayoutDashboard, Briefcase, CalendarDays, Truck, Route, Workflow, DoorOpen,
  Users, UserPlus, FileText, Calculator, Receipt, CreditCard, Repeat, DollarSign, Zap, Layers,
  UsersRound, UserCog, Clock, Timer, ShieldCheck, Wrench, BookOpen, Cog, Waves, History, CalendarClock, LineChart, Phone,
  Timer as TimerIcon, BarChart3, TrendingUp, PieChart, MegaphoneIcon, Megaphone, Palette,
  MessageSquare, Bell, CheckSquare, Bot, ListChecks, Send, Star as StarIcon, Search,
  Sparkles, Ruler, Image, MapPin, Sun, IdCard, Search as SearchIcon, Globe, FileEdit,
  BadgeCheck, Shield, Bell as BellIcon, Settings, MapIcon, ScrollText,
  Grid3x3, Compass, Rss, Wand2, PencilRuler, Building2,
  Map as MapPinIcon, Gauge, Timer as StopwatchIcon,
  Boxes, AlertTriangle as AlertTriangleIcon, ShoppingCart as ShoppingCartIcon,
  Home as HomeIcon,
  Cloud,
  LibraryBig,
  ClipboardList as ClipboardListIcon2,
} from "lucide-react";

/**
 * Phase 35 — Admin navigation single-source-of-truth (6-category IA).
 *
 * Contract preserved from Phase 15:
 *   { key, label, icon, entries: [{ to, label, icon, feature, hard_rule?, subsection? }] }
 *
 * Categories (top-level):
 *   1. Finance        — money in / out, warranties, dunning, checks, CFO
 *   2. AI Employees   — LLM-driven agents & inboxes
 *   3. Marketing      — studio, sequences, social, SEO, GBP, referrals
 *   4. Operations     — schedule, dispatch, workforce, inventory, business-OS,
 *                       AI tools, integrations, tenant settings
 *   5. Customers      — customers, leads, quotes, churn, business card
 *   6. Reports        — dashboard, analytics, reports hub, audit logs
 *
 * Every existing entry from Phase 15 is preserved; only the parent grouping
 * changes. RBAC `feature` gates and `hard_rule` flags are unchanged.
 */
export const ADMIN_NAV_V2 = [

  { key: "finance", label: "Finance", icon: DollarSign, entries: [
    // CFO
    { to: "/cfo",                       label: "AI CFO",             icon: TrendingUp, feature: "reports", hard_rule: "admin_only", subsection: "CFO" },
    { to: "/income-by-category",        label: "Income by Category", icon: DollarSign, feature: "reports", subsection: "CFO" },
    // Invoicing
    { to: "/invoices",                  label: "Invoices",           icon: Receipt,    feature: "invoices",  subsection: "Invoicing" },
    { to: "/payments",                  label: "Payments",           icon: CreditCard, feature: "payments",  subsection: "Invoicing" },
    { to: "/invoices/master",           label: "Master Invoices",    icon: Layers,     feature: "invoices",  subsection: "Invoicing" },
    { to: "/auto-billing",              label: "Auto-billing",       icon: Repeat,     feature: "invoices",  subsection: "Invoicing" },
    { to: "/admin/autobilling-runs",     label: "Autobilling runs",   icon: Repeat,     feature: "invoices",  subsection: "Invoicing" },
    { to: "/settings/late-fees",        label: "Late Fees",          icon: DollarSign, feature: "invoices",  subsection: "Invoicing" },
    { to: "/settings/billing",          label: "Billing Rules",      icon: Cog,        feature: "invoices",  subsection: "Invoicing" },
    { to: "/settings/payment-handles",  label: "Payment Handles",    icon: CreditCard, feature: "settings",  subsection: "Invoicing" },
    // Checks & payroll
    { to: "/admin/checks",              label: "Check Writer",       icon: FileEdit,   feature: "invoices",  subsection: "Checks & Payroll" },
    { to: "/admin/checks/bank-accounts",label: "Bank Accounts",      icon: Building2,  feature: "invoices",  subsection: "Checks & Payroll" },
    { to: "/admin/checks/payees",       label: "Payees",             icon: UsersRound, feature: "invoices",  subsection: "Checks & Payroll" },
    { to: "/admin/checks/analytics",    label: "Check Analytics",    icon: BarChart3,  feature: "reports",   subsection: "Checks & Payroll" },
    { to: "/admin/checks/batch/new",    label: "Batch Print",        icon: Layers,     feature: "invoices",  subsection: "Checks & Payroll" },
    { to: "/admin/checks/payroll",      label: "Payroll Import",     icon: UsersRound, feature: "invoices",  subsection: "Checks & Payroll" },
    // Dunning / AR
    { to: "/admin/dunning/queue",       label: "Dunning Queue",      icon: Repeat,     feature: "invoicing", subsection: "AR & Dunning" },
    { to: "/admin/dunning/analytics",   label: "AR Aging",           icon: DollarSign, feature: "invoicing", subsection: "AR & Dunning" },
    { to: "/admin/dunning/settings",    label: "Dunning Setup",      icon: Zap,        feature: "invoicing", subsection: "AR & Dunning" },
    // Warranties
    { to: "/admin/warranties/plans",       label: "Warranty Plans",     icon: Shield,    feature: "customers", subsection: "Warranties" },
    { to: "/admin/warranties/contracts",   label: "Warranty Contracts", icon: FileText,  feature: "customers", subsection: "Warranties" },
    { to: "/admin/warranties/claims",      label: "Warranty Claims",    icon: BadgeCheck,feature: "customers", subsection: "Warranties" },
    // Workforce cost analytics
    { to: "/workforce/job-costing",     label: "Job Costing",        icon: Gauge,      feature: "reports",   subsection: "Cost Analytics" },
    { to: "/workforce/mileage",         label: "Mileage",            icon: TrendingUp, feature: "reports",   subsection: "Cost Analytics" },
  ]},

  { key: "ai_employees", label: "AI Employees", icon: Bot, entries: [
    { to: "/ai-employees",       label: "AI Employees Hub",    icon: Bot,          feature: "ai_employees" },
    { to: "/os/lana",            label: "Lana AI Assistant",   icon: Sparkles,     feature: "settings" },
    { to: "/admin/seo/atlas",    label: "Atlas SEO Agent",     icon: SearchIcon,   feature: "seo" },
    { to: "/communications",     label: "Communications",      icon: MessageSquare,feature: "marketing" },
    { to: "/admin/portal-inbox", label: "Portal Inbox",        icon: MessageSquare,feature: "marketing" },
  ]},

  { key: "marketing", label: "Marketing", icon: Megaphone, entries: [
    // Studio
    { to: "/marketing",             label: "Studio",           icon: Palette,      feature: "marketing", subsection: "Studio" },
    { to: "/marketing/campaigns",   label: "Campaigns",        icon: Megaphone,    feature: "marketing", subsection: "Studio" },
    { to: "/marketing/posts",       label: "Posts",            icon: FileText,     feature: "marketing", subsection: "Studio" },
    { to: "/marketing/queue",       label: "Approval Queue",   icon: ListChecks,   feature: "marketing", subsection: "Studio" },
    { to: "/marketing/calendar",    label: "Marketing Calendar", icon: CalendarDays,feature: "marketing", subsection: "Studio" },
    { to: "/marketing/performance", label: "Performance",      icon: BarChart3,    feature: "marketing", subsection: "Studio" },
    { to: "/marketing/brand",       label: "Brand Memory",     icon: Palette,      feature: "marketing", subsection: "Studio" },
    // Sequences
    { to: "/marketing/sequences",   label: "Sequences",        icon: Workflow,     feature: "marketing", subsection: "Sequences & Templates" },
    { to: "/marketing/templates",   label: "Templates",        icon: FileText,     feature: "marketing", subsection: "Sequences & Templates" },
    { to: "/notifications",         label: "Notifications",    icon: BellIcon,     feature: "marketing", subsection: "Sequences & Templates" },
    { to: "/settings/notifications", label: "Notification Prefs", icon: BellIcon,    feature: "marketing", subsection: "Sequences & Templates" },
    { to: "/tasks",                 label: "Tasks",            icon: CheckSquare,  feature: "marketing", subsection: "Sequences & Templates" },
    // Reviews & public
    { to: "/marketing/reviews",     label: "Reviews",          icon: StarIcon,     feature: "marketing", subsection: "Reviews & Public" },
    { to: "/csat",                  label: "CSAT / NPS",       icon: Sparkles,     feature: "marketing", subsection: "Reviews & Public" },
    { to: "/forms",                 label: "Forms",            icon: FileEdit,     feature: "marketing", subsection: "Reviews & Public" },
    // Referrals
    { to: "/admin/referrals/analytics", label: "Referral Analytics", icon: BarChart3, feature: "marketing", subsection: "Referrals" },
    { to: "/admin/referrals/settings",  label: "Referral Tiers",     icon: StarIcon,  feature: "marketing", subsection: "Referrals" },
    // Social
    { to: "/social/composer",     label: "Social Composer",  icon: FileEdit,     feature: "marketing", subsection: "Social" },
    { to: "/social/calendar",     label: "Social Calendar",  icon: CalendarDays, feature: "marketing", subsection: "Social" },
    { to: "/social/library",      label: "Social Library",   icon: Image,        feature: "marketing", subsection: "Social" },
    { to: "/social/drafts",       label: "Social Drafts",    icon: ListChecks,   feature: "marketing", subsection: "Social" },
    { to: "/social/approvals",    label: "Social Approvals", icon: BadgeCheck,   feature: "marketing", subsection: "Social" },
    { to: "/social/bulk-upload",  label: "Bulk Upload",      icon: FileEdit,     feature: "marketing", subsection: "Social" },
    { to: "/social/short-links",  label: "Short Links",      icon: MapPin,       feature: "marketing", subsection: "Social" },
    { to: "/social/brand-kit",    label: "Brand Kit",        icon: Palette,      feature: "marketing", subsection: "Social" },
    // SEO
    { to: "/seo",                       label: "SEO Hub",          icon: SearchIcon, feature: "seo", subsection: "SEO Suite" },
    { to: "/seo/articles",              label: "Articles",         icon: FileText,   feature: "seo", subsection: "SEO Suite" },
    { to: "/seo/keywords",              label: "Keywords",         icon: Rss,        feature: "seo", subsection: "SEO Suite" },
    { to: "/seo/audit",                 label: "Audit",            icon: BadgeCheck, feature: "seo", subsection: "SEO Suite" },
    { to: "/seo/rank-grid",             label: "Rank Grid",        icon: Grid3x3,    feature: "seo", subsection: "SEO Suite" },
    { to: "/seo/wordpress",             label: "WordPress",        icon: Globe,      feature: "seo", subsection: "SEO Suite" },
    { to: "/admin/seo/audits",          label: "Site Auditor",     icon: BadgeCheck, feature: "seo", subsection: "SEO Suite" },
    { to: "/admin/seo/content-scorer",  label: "Content Scorer",   icon: FileText,   feature: "seo", subsection: "SEO Suite" },
    { to: "/admin/seo/rank-heatmap",    label: "Rank Heatmap",     icon: Grid3x3,    feature: "seo", subsection: "SEO Suite" },
    { to: "/admin/seo/topical-map",     label: "Topical Map",      icon: Grid3x3,    feature: "seo", subsection: "SEO Suite" },
    { to: "/admin/seo/llm-visibility",  label: "LLM Visibility",   icon: SearchIcon, feature: "seo", subsection: "SEO Suite" },
    { to: "/admin/seo/studio",          label: "Website Studio",   icon: FileText,   feature: "seo", subsection: "SEO Suite" },
    { to: "/admin/seo/reports",         label: "White-Label Reports", icon: FileText, feature: "seo", subsection: "SEO Suite" },
    { to: "/admin/seo/content-refresh", label: "Content Refresh",  icon: Sparkles,   feature: "seo", subsection: "SEO Suite" },
    // GBP
    { to: "/gbp",          label: "GBP Hub",      icon: Building2, feature: "gbp", subsection: "Google Business" },
    { to: "/gbp/posts",    label: "GBP Posts",    icon: FileText,  feature: "gbp", subsection: "Google Business" },
    { to: "/gbp/reviews",  label: "GBP Reviews",  icon: StarIcon,  feature: "gbp", subsection: "Google Business" },
    { to: "/gbp/business", label: "GBP Business", icon: Building2, feature: "gbp", subsection: "Google Business" },
  ]},

  { key: "operations", label: "Operations", icon: Wrench, entries: [
    // Schedule & dispatch
    { to: "/schedule",               label: "Schedule",           icon: CalendarDays, feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/dispatch",               label: "Dispatch Board",     icon: Truck,        feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/admin/dispatch",         label: "Auto-Dispatch",      icon: Zap,          feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/admin/dispatch/weather", label: "Weather Reschedule", icon: Cloud,        feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/routes",                 label: "Routes",             icon: Route,        feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/workstream",             label: "Workstream",         icon: Workflow,     feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/admin/appointments",     label: "Appointments",       icon: CalendarDays, feature: "jobs", subsection: "Schedule & Dispatch" },
    // Workforce
    { to: "/team",              label: "Team",             icon: UsersRound,  feature: "jobs", subsection: "Workforce" },
    { to: "/crews",             label: "Crews",            icon: UserCog,     feature: "jobs", subsection: "Workforce" },
    { to: "/timesheets",        label: "Timesheets",       icon: Clock,       feature: "jobs", subsection: "Workforce" },
    { to: "/timeclock/today",   label: "Timeclock",        icon: Timer,       feature: "jobs", subsection: "Workforce" },
    { to: "/coverage",          label: "Coverage",         icon: ShieldCheck, feature: "jobs", subsection: "Workforce" },
    { to: "/workforce/timesheets", label: "Workyard Timesheets", icon: Clock,      feature: "jobs", subsection: "Workforce" },
    { to: "/workforce/crew-map",   label: "Crew Map",            icon: MapPinIcon, feature: "jobs", subsection: "Workforce" },
    { to: "/checkins",          label: "Check-ins",        icon: MapPin,      feature: "jobs", subsection: "Workforce" },
    { to: "/job-timers",        label: "Job Timers",       icon: TimerIcon,   feature: "jobs", subsection: "Workforce" },
    { to: "/avg-job-time",      label: "Avg Job Time",     icon: TrendingUp,  feature: "jobs", subsection: "Workforce" },
    { to: "/log-history",       label: "Log History",      icon: History,     feature: "jobs", subsection: "Workforce" },
    // Field service
    { to: "/maintenance",  label: "Maintenance",  icon: Cog,      feature: "jobs", subsection: "Field Service" },
    { to: "/pool-service", label: "Pool Service", icon: Waves,    feature: "jobs", subsection: "Field Service" },
    { to: "/equipment",    label: "Equipment",    icon: Wrench,   feature: "jobs", subsection: "Field Service" },
    { to: "/admin/assets", label: "Assets",       icon: Wrench,   feature: "jobs", subsection: "Field Service" },
    { to: "/price-book",   label: "Price Book",   icon: BookOpen, feature: "jobs", subsection: "Field Service" },
    // Inventory
    { to: "/admin/inventory",                 label: "Inventory",            icon: Boxes,             feature: "jobs",    subsection: "Inventory" },
    { to: "/admin/inventory/alerts",          label: "Stock Alerts",         icon: AlertTriangleIcon, feature: "jobs",    subsection: "Inventory" },
    { to: "/admin/inventory/purchase-orders", label: "Purchase Orders",      icon: ShoppingCartIcon,  feature: "jobs",    subsection: "Inventory" },
    { to: "/admin/inventory/analytics",       label: "Inventory Analytics",  icon: BarChart3,         feature: "reports", subsection: "Inventory" },
    // Business OS
    { to: "/os/dashboard",  label: "Four Pillars", icon: Compass,       feature: "settings", subsection: "Business OS" },
    { to: "/os/sops",       label: "SOPs",         icon: BookOpen,      feature: "settings", subsection: "Business OS" },
    { to: "/os/roles",      label: "Roles",        icon: UsersRound,    feature: "settings", subsection: "Business OS" },
    { to: "/os/scorecards", label: "Scorecards",   icon: Gauge,         feature: "settings", subsection: "Business OS" },
    { to: "/os/huddle",     label: "Huddles",      icon: MessageSquare, feature: "settings", subsection: "Business OS" },
    { to: "/os/leanboards", label: "LeanBoards",   icon: ListChecks,    feature: "settings", subsection: "Business OS" },
    { to: "/os/sprints",    label: "Sprints",      icon: Workflow,      feature: "settings", subsection: "Business OS" },
    { to: "/admin/onboarding/templates", label: "Onboarding Templates", icon: FileText,   feature: "settings", subsection: "Business OS" },
    { to: "/admin/onboarding/queue",     label: "Onboarding Queue",     icon: ListChecks, feature: "settings", subsection: "Business OS" },
    { to: "/admin/templates",            label: "Templates Library",    icon: LibraryBig, feature: "settings", subsection: "Business OS" },
    { to: "/handbook",                    label: "Handbook",              icon: BookOpen,   feature: "dashboard", subsection: "Business OS" },
    { to: "/admin/onboarding",            label: "Onboarding Dashboard", icon: ClipboardListIcon2, feature: "settings", subsection: "Business OS" },
    // AI Tools (admin only)
    { to: "/landscape",   label: "Landscape AI",       icon: Image,       feature: "landscape",   hard_rule: "admin_only", subsection: "AI Tools" },
    { to: "/cad",         label: "CAD Studio",         icon: PencilRuler, feature: "cad",         hard_rule: "admin_only", subsection: "AI Tools" },
    { to: "/measure",     label: "Satellite Measure",  icon: Ruler,       feature: "measure",     hard_rule: "admin_only", subsection: "AI Tools" },
    { to: "/virtual-bid", label: "Virtual Bid",        icon: Sparkles,    feature: "virtual_bid", hard_rule: "admin_only", subsection: "AI Tools" },
    { to: "/weather",     label: "Weather",            icon: Sun,         feature: "weather",     hard_rule: "admin_only", subsection: "AI Tools" },
    // System settings
    { to: "/settings/onboarding",   label: "Onboarding",    icon: Sparkles,   feature: "settings", subsection: "Settings" },
    { to: "/settings/tenant",       label: "Tenant Brand",  icon: Sparkles,   feature: "settings", subsection: "Settings" },
    { to: "/tenants",               label: "Tenants (super)", icon: Shield,   feature: "settings", hard_rule: "super_admin_only", subsection: "Settings" },
    { to: "/access-settings",       label: "Access Settings", icon: Shield,   feature: "permissions", subsection: "Settings" },
    { to: "/settings/integrations", label: "Integrations",    icon: Compass,  feature: "settings", subsection: "Settings" },
    { to: "/settings/maps",         label: "Maps",            icon: MapIcon,  feature: "settings", subsection: "Settings" },
    { to: "/settings/terms",        label: "Terms",           icon: ScrollText, feature: "settings", subsection: "Settings" },
    { to: "/settings/legal",        label: "Legal Docs",      icon: ScrollText, feature: "settings", subsection: "Settings" },
    { to: "/settings/ringcentral",  label: "RingCentral",     icon: Bell,     feature: "settings", subsection: "Settings" },
  ]},

  { key: "customers", label: "Customers", icon: Users, entries: [
    { to: "/customers",             label: "Customers",        icon: Users,      feature: "customers", subsection: "Directory" },
    { to: "/leads",                 label: "Leads",            icon: UserPlus,   feature: "customers", subsection: "Directory" },
    { to: "/leads/request",         label: "Lead Requests",    icon: Send,       feature: "customers", subsection: "Directory" },
    { to: "/tech/property-lookup",  label: "Property Lookup",  icon: HomeIcon,   feature: "customers", subsection: "Directory" },
    { to: "/quotes",                label: "Quotes",           icon: FileText,   feature: "quotes",    subsection: "Sales" },
    { to: "/estimator",             label: "Estimator",        icon: Calculator, feature: "estimator", subsection: "Sales" },
    { to: "/admin/estimator",       label: "Field Estimator",  icon: Wrench,     feature: "estimator", subsection: "Sales" },
    { to: "/d2d",                   label: "D2D Canvassing",   icon: DoorOpen,   feature: "d2d", hard_rule: "admin_only", subsection: "Sales" },
    { to: "/admin/customer-success/churn", label: "Churn Analyzer", icon: TrendingUp, feature: "customers", subsection: "Success" },
    { to: "/tech/card",             label: "Business Card", icon: IdCard,     feature: "dashboard", subsection: "Success" },
    { to: "/card",                  label: "Digital Card",     icon: IdCard,     feature: "card",      subsection: "Success" },
  ]},

  { key: "reports", label: "Reports", icon: BarChart3, entries: [
    { to: "/",                            label: "Dashboard",         icon: LayoutDashboard, feature: "dashboard" },
    { to: "/reports",                     label: "Reports Hub",       icon: BarChart3, feature: "reports" },
    { to: "/analytics",                   label: "Analytics",         icon: TrendingUp, feature: "reports" },
    { to: "/reports/business-summary",    label: "Business Summary",  icon: PieChart,  feature: "reports" },
    { to: "/reports/forecast",            label: "Forecast",          icon: TrendingUp, feature: "reports" },
    { to: "/reports/customer-retention",  label: "Customer Retention",icon: Users,      feature: "reports" },
    { to: "/reports/revenue-slices",      label: "Revenue Slices",    icon: PieChart,  feature: "reports" },
    { to: "/admin/recurring-jobs",         label: "Recurring Jobs",      icon: CalendarClock, feature: "scheduling" },
    { to: "/admin/reports/pool-service",   label: "Pool Service Report", icon: Waves,   feature: "reports" },
    { to: "/admin/reports/job-margins",    label: "Job Margin Leaderboard", icon: TrendingUp, feature: "reports" },
    { to: "/admin/reports/pricing-insights",label: "Pricing Insights",    icon: LineChart, feature: "reports" },
    { to: "/admin/cfo/reports",            label: "CFO Reports",         icon: PieChart, feature: "reports" },
    { to: "/admin/finance/bills",          label: "Vendor Bills",        icon: Receipt, feature: "reports" },
    { to: "/admin/finance/stripe-payments", label: "Stripe Payments",    icon: DollarSign, feature: "reports" },
    { to: "/admin/settings/chemical-costs",label: "Chemical Costs",      icon: Calculator, feature: "settings" },
    { to: "/admin/settings/ringcentral",   label: "RingCentral",         icon: Phone, feature: "settings" },
    { to: "/admin/budget",                 label: "Budget Setup",        icon: Calculator, feature: "settings" },
    { to: "/admin/budget/dashboard",       label: "Budget Dashboard",    icon: TrendingUp, feature: "reports" },
    { to: "/admin/budget/wizard",          label: "Budget Wizard",       icon: Sparkles, feature: "settings" },
    { to: "/landscape/time-clock",         label: "Landscape Time Clock", icon: Timer,  feature: "jobs" },
    { to: "/access-history",              label: "Access History",    icon: ScrollText, feature: "audit_logs" },
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
  d: "/", j: "/schedule", c: "/customers", i: "/invoices",
  q: "/quotes", r: "/reports", m: "/marketing", s: "/access-settings",
};
