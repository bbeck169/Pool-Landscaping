import { LayoutDashboard, CalendarDays, Truck, Route, Workflow, DoorOpen, Users, UserPlus, FileText, Calculator, Receipt, CreditCard, Repeat, DollarSign, Zap, Layers, UsersRound, UserCog, Clock, Timer, ShieldCheck, Wrench, BookOpen, Cog, Waves, History, CalendarClock, LineChart, Phone, Timer as TimerIcon, BarChart3, TrendingUp, PieChart, Megaphone, Palette, MessageSquare, Bell, CheckSquare, Bot, ListChecks, Send, Star as StarIcon, Sparkles, Ruler, Image, MapPin, Sun, IdCard, Search as SearchIcon, Globe, FileEdit, BadgeCheck, Shield, Bell as BellIcon, MapIcon, ScrollText, Grid3x3, Compass, Rss, PencilRuler, Building2, Map as MapPinIcon, Gauge, Boxes, AlertTriangle as AlertTriangleIcon, ShoppingCart as ShoppingCartIcon, Home as HomeIcon, Cloud, LibraryBig, ClipboardList as ClipboardListIcon2, Mail, FlaskConical, GitBranch, Tag, RefreshCw, Store, Scale, KanbanSquare, Gift, UploadCloud, Filter as FilterFunnelIcon, Droplets } from 'lucide-react';

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
    { to: "/cfo",                       label: "AI CFO",             icon: TrendingUp, feature: "reports", hard_rule: "admin_only", subsection: "CFO", aliases: ["Financial", "CFO Dashboard", "Chief Financial Officer"] },
    { to: "/income-by-category",        label: "Income by Category", icon: DollarSign, feature: "reports", subsection: "CFO" },
    // Invoicing
    { to: "/invoices",                  label: "Invoices",           icon: Receipt,    feature: "invoices",  subsection: "Invoicing", aliases: ["Bills", "Receivables", "Sales", "AR", "Customer Invoices"] },
    { to: "/payments",                  label: "Payments",           icon: CreditCard, feature: "payments",  subsection: "Invoicing", aliases: ["Received Payments", "Payment Log", "Deposits"] },
    { to: "/invoices/master",           label: "Master Invoices",    icon: Layers,     feature: "invoices",  subsection: "Invoicing" },
    { to: "/auto-billing",              label: "Auto-billing",       icon: Repeat,     feature: "invoices",  subsection: "Invoicing" },
    { to: "/admin/autobilling-runs",     label: "Autobilling runs",   icon: Repeat,     feature: "invoices",  subsection: "Invoicing" },
    // Task B · Feb-2026 — PDF Invoice Importer. Sits inside the
    // Invoicing subsection alongside the other invoice-producing
    // action rows (Auto-billing, Autobilling runs). Admin-only
    // per Phase 2 ruling E.4 (matches the ``require_admin`` gate
    // on the backend endpoints).
    //
    // History note: Phase 1 recon report §B mis-identified Vendor
    // Bills as sitting in the Finance group — Vendor Bills was
    // historically mis-grouped inside the Reports group (opened
    // at ``key: "reports"`` line ~294).  User ruled Option A on
    // the sidebar-placement halt: PDF Import lives here in
    // Finance/Invoicing, and Vendor Bills was relocated to sit
    // directly after PDF Import (see Commit 1.5 · Vendor Bills
    // relocation, below).
    { to: "/admin/imports/pdf-invoice",  label: "PDF Import",         icon: UploadCloud, feature: "invoices",  subsection: "Invoicing", hard_rule: "admin_only", aliases: ["PDF Upload", "Bulk Import", "Import PDFs", "Upload Invoices", "PDF Invoice Importer"] },
    // Task B · Commit 1.5 · Feb-2026 — Vendor Bills relocation.
    // Vendor Bills was historically mis-grouped inside the
    // Reports group (opened line 294) despite being a Finance /
    // Invoicing surface (payable-side invoices).  Relocated
    // here so operators find the receivable side (Invoices /
    // Master Invoices / Auto-billing) and the payable side
    // (PDF Import → Vendor Bills) in one place.  Row properties
    // (to / icon / label) preserved verbatim; ``feature`` flips
    // from ``reports`` to ``invoices`` to match the subsection
    // and match the surrounding invoicing rows.  Sits directly
    // after PDF Import — the two are a matched pair (import
    // action → resulting list).
    { to: "/admin/finance/bills",        label: "Vendor Bills",       icon: Receipt,     feature: "invoices",  subsection: "Invoicing", aliases: ["Payables", "AP", "Supplier Bills", "Vendor Invoices"] },
    { to: "/settings/late-fees",        label: "Late Fees",          icon: DollarSign, feature: "invoices",  subsection: "Invoicing" },
    { to: "/settings/billing",          label: "Billing Rules",      icon: Cog,        feature: "invoices",  subsection: "Invoicing" },
    { to: "/settings/payment-handles",  label: "Payment Handles",    icon: CreditCard, feature: "settings",  subsection: "Invoicing" },
    { to: "/settings/income-categories", label: "Income Categories",  icon: Tag,        feature: "invoices",  subsection: "Invoicing" },
    { to: "/settings/service-categories",label: "Service Categories", icon: Layers,     feature: "settings",  subsection: "Invoicing" },
    // Phase L1.1 · Feb-2026 — umbrella "Categories Management"
    // entry that lands on the consolidated CategoriesAdmin page.
    // Sits alongside the two axis-specific entries above so any
    // bookmarked deep-links keep working — the umbrella becomes
    // the recommended admin entry point.
    { to: "/pricebook/categories",       label: "Categories Management", icon: Layers,  feature: "settings",  subsection: "Invoicing" },
    // Checks & payroll
    { to: "/admin/checks",              label: "Check Writer",       icon: FileEdit,   feature: "invoices",  subsection: "Checks & Payroll", aliases: ["Checks", "Write Checks", "Print Checks"] },
    { to: "/admin/checks/bank-accounts",label: "Bank Accounts",      icon: Building2,  feature: "invoices",  subsection: "Checks & Payroll" },
    { to: "/admin/checks/payees",       label: "Payees",             icon: UsersRound, feature: "invoices",  subsection: "Checks & Payroll" },
    { to: "/admin/checks/analytics",    label: "Check Analytics",    icon: BarChart3,  feature: "reports",   subsection: "Checks & Payroll" },
    { to: "/admin/checks/batch/new",    label: "Batch Print",        icon: Layers,     feature: "invoices",  subsection: "Checks & Payroll" },
    { to: "/admin/checks/payroll",      label: "Payroll Import",     icon: UsersRound, feature: "invoices",  subsection: "Checks & Payroll" },
    // Dunning / AR
    { to: "/admin/dunning/queue",       label: "Dunning Queue",      icon: Repeat,     feature: "invoicing", subsection: "AR & Dunning", aliases: ["Late Invoices", "Overdue", "Collections", "Past Due"] },
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
    // Feb-2026 · Item 4 — Master AI Copilot + Knowledge Base (admin only).
    { to: "/admin/copilot",      label: "AI Copilot",          icon: Sparkles,     feature: "settings", hard_rule: "admin_only" },
    { to: "/settings/ai-brain",  label: "AI Brain",            icon: Sparkles,     feature: "settings", hard_rule: "admin_only" },
    { to: "/os/lana",            label: "Lana AI Assistant",   icon: Sparkles,     feature: "settings" },
    { to: "/admin/seo/atlas",    label: "Atlas SEO Agent",     icon: SearchIcon,   feature: "seo" },
    { to: "/communications",     label: "Communications",      icon: MessageSquare,feature: "marketing" },
    { to: "/admin/portal-inbox", label: "Portal Inbox",        icon: MessageSquare,feature: "marketing" },
    { to: "/marketing/gbp-posts",label: "GBP Post Drafter",     icon: Sparkles,     feature: "marketing", hard_rule: "admin_only" },
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
    // Automations (K69 rename · Feb-2026 — UI string only; API
    // route ``/api/marketing/sequences`` and internal collection
    // names are unchanged for backwards compat).
    { to: "/admin/marketing/automations",   label: "Automations",        icon: Workflow,     feature: "marketing", subsection: "Automations & Templates" },
    { to: "/admin/marketing/review-requests", label: "Review Requests", icon: StarIcon,   feature: "marketing", subsection: "Automations & Templates" },
    { to: "/admin/marketing/analytics",   label: "Analytics",         icon: BarChart3,    feature: "marketing", subsection: "Automations & Templates" },
    { to: "/admin/marketing/suppressions", label: "Suppressions",     icon: Shield,       feature: "marketing", subsection: "Automations & Templates" },
    { to: "/marketing/templates",   label: "Templates",        icon: FileText,     feature: "marketing", subsection: "Automations & Templates" },
    { to: "/notifications",         label: "Notifications",    icon: BellIcon,     feature: "marketing", subsection: "Automations & Templates" },
    { to: "/settings/notifications", label: "Notification Prefs", icon: BellIcon,    feature: "marketing", subsection: "Automations & Templates" },
    { to: "/tasks",                 label: "Tasks",            icon: CheckSquare,  feature: "marketing", subsection: "Automations & Templates" },
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
    // Phase SEO-B · Feb-2026 — Backlink outreach CRM (admin+/manager).
    { to: "/admin/outreach/prospects",  label: "Outreach Prospects", icon: SearchIcon, feature: "seo", subsection: "Outreach" },
    { to: "/admin/outreach/templates",  label: "Outreach Templates", icon: FileText,   feature: "seo", subsection: "Outreach" },
    // GBP
    { to: "/gbp",          label: "GBP Hub",      icon: Building2, feature: "gbp", subsection: "Google Business" },
    { to: "/gbp/posts",    label: "GBP Posts",    icon: FileText,  feature: "gbp", subsection: "Google Business" },
    { to: "/gbp/reviews",  label: "GBP Reviews",  icon: StarIcon,  feature: "gbp", subsection: "Google Business" },
    { to: "/gbp/business", label: "GBP Business", icon: Building2, feature: "gbp", subsection: "Google Business" },
  ]},

  { key: "operations", label: "Operations", icon: Wrench, entries: [
    // Schedule & dispatch
    { to: "/schedule",               label: "Schedule",           icon: CalendarDays, feature: "jobs", subsection: "Schedule & Dispatch", aliases: ["Calendar", "Bookings", "Jobs Calendar", "Appointments"] },
    { to: "/admin/jobs",             label: "Jobs (admin)",       icon: ListChecks,   feature: "jobs", subsection: "Schedule & Dispatch" },
    // Feb 2026 · Task A — top-level Recurring Jobs shortcut. Placed
    // adjacent to Schedule + Jobs so users don't have to hunt for
    // it under Reports. Gated to super_admin / admin / manager via
    // ``manager_only``; techs and portal customers never see it.
    // Route target is the existing ``/admin/recurring-jobs`` page
    // (also still linked from Reports for backwards compat).
    // Phase K3 · Feb-2026 — swapped the icon from ``CalendarClock``
    // to ``Repeat`` so the visual signals "recurring" instead of
    // "scheduled once".
    { to: "/admin/recurring-jobs",   label: "Recurring Jobs",     icon: Repeat,       feature: "scheduling", hard_rule: "manager_only", subsection: "Schedule & Dispatch" },
    // Feb 2026 · Sidebar Pricebook shortcut — promoted from the
    // former Field Service subsection so it sits with the other
    // manager-facing quick-links (Recurring Jobs, Dispatch). Same
    // three-role gate as Recurring Jobs via ``manager_only``;
    // techs and portal customers never see it. Route target is the
    // existing OpsHub Price Book grid at ``/price-book``.
    { to: "/price-book",             label: "Pricebook",          icon: Tag,          feature: "jobs",       hard_rule: "manager_only", subsection: "Schedule & Dispatch" },
    // Phase F2 · Feb-2026 — Charge Template Bundles admin CRUD.
    { to: "/admin/charge-templates", label: "Charge Templates",    icon: Tag,          feature: "jobs",       hard_rule: "admin_only", subsection: "Schedule & Dispatch" },
    { to: "/admin/reflow-history",   label: "Reflow History",     icon: History,      feature: "jobs", subsection: "Schedule & Dispatch" },
    // Task RR/SS Phase 2 · Feb 2026 — AI Employee data-access controls.
    { to: "/admin/ai-personas-scope", label: "AI Access Scope",    icon: History,      subsection: "AI Operations" },
    { to: "/admin/ai-tool-audit",     label: "AI Tool Audit",      icon: History,      subsection: "AI Operations" },
    // Phase F3 · Feb-2026 — Soshie moderation queue.
    { to: "/admin/soshie/moderation", label: "Soshie Moderation",  icon: History,      subsection: "AI Operations" },
    { to: "/dispatch",               label: "Dispatch Board",     icon: Truck,        feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/walkie",                 label: "Walkie-Talkie",      icon: Phone,        subsection: "Schedule & Dispatch" },
    { to: "/admin/dispatch",         label: "Auto-Dispatch",      icon: Zap,          feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/admin/dispatch/weather", label: "Weather Reschedule", icon: Cloud,        feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/routes",                 label: "Routes",             icon: Route,        feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/workstream",             label: "Workstream", icon: Workflow,     feature: "jobs", subsection: "Service Log" },
    { to: "/admin/appointments",     label: "Appointments",       icon: CalendarDays, feature: "jobs", subsection: "Schedule & Dispatch" },
    { to: "/settings/job-outcome-reasons", label: "Job Outcome Reasons", icon: AlertTriangleIcon, feature: "settings", hard_rule: "admin_only", subsection: "Schedule & Dispatch" },
    // Feb-2026 · P29b — Muted Reasons picker manager. Admin + manager +
    // super_admin all see it in the nav (route wrapper enforces the
    // three-role gate); no `hard_rule` so managers keep visibility.
    { to: "/settings/muted-reasons", label: "Muted Reasons", icon: AlertTriangleIcon, feature: "settings", subsection: "Schedule & Dispatch" },
    // Feb-2026 · P34 — Automation quiet-hours window. Same role set
    // as muted-reasons (super_admin / admin / manager); route wrapper
    // handles enforcement so no `hard_rule` here either.
    { to: "/settings/quiet-hours", label: "Quiet Hours", icon: AlertTriangleIcon, feature: "settings", subsection: "Schedule & Dispatch" },
    // Feb-2026 · P36 — Customer Tags settings manager. Same role set
    // as muted-reasons + quiet-hours; nav placement kept adjacent.
    { to: "/settings/customer-tags", label: "Customer Tags", icon: AlertTriangleIcon, feature: "settings", subsection: "Schedule & Dispatch" },
    // Feb-2026 · P37b — GPS auto-start. Same role set as the other
    // Schedule & Dispatch settings surfaces; route wrapper enforces.
    { to: "/settings/gps-auto-start", label: "GPS Auto-Start", icon: AlertTriangleIcon, feature: "settings", subsection: "Schedule & Dispatch" },
    // Workforce
    { to: "/team?t=team",              label: "Team",             icon: UsersRound,  feature: "jobs", subsection: "Workforce" },
    { to: "/admin/users",              label: "Team (admin)",     icon: UserCog,     feature: "settings", subsection: "Workforce" },
    { to: "/admin/time-entries",       label: "Time Entries",     icon: Clock,       feature: "jobs", subsection: "Workforce" },
    { to: "/crews?t=crews",             label: "Crews",            icon: UserCog,     feature: "jobs", subsection: "Workforce" },
    { to: "/timesheets?t=timesheets",   label: "Timesheets",       icon: Clock,       feature: "jobs", subsection: "Workforce" },
    { to: "/timesheets?t=timeclock",    label: "Timeclock",        icon: Timer,       feature: "jobs", subsection: "Workforce" },
    { to: "/coverage",          label: "Coverage",         icon: ShieldCheck, feature: "jobs", subsection: "Workforce" },
    { to: "/time-off",          label: "Time Off",         icon: Clock,       feature: "jobs", subsection: "Workforce" },
    { to: "/admin/time-off",    label: "Time Off Approvals", icon: ShieldCheck, hard_rule: "admin_only", subsection: "Workforce" },
    // Task D · Feb-2026 — Employee Benefits catalog. Every
    // authenticated user can VIEW; admin/super_admin CRUD controls
    // self-gate inside the component. No ``hard_rule`` so
    // technicians still see the sidebar link (same posture as
    // ``Team`` above).
    { to: "/workforce/benefits", label: "Employee Benefits", icon: Gift, feature: "dashboard", subsection: "Workforce" },
    { to: "/workforce/timesheets", label: "Workyard Timesheets", icon: Clock,      feature: "jobs", subsection: "Workforce" },
    { to: "/workforce/crew-map",   label: "Crew Map",            icon: MapPinIcon, feature: "jobs", subsection: "Workforce" },
    { to: "/checkins",          label: "Check-ins",        icon: MapPin,      feature: "jobs", subsection: "Workforce" },
    { to: "/job-timers",        label: "Job Timers",       icon: TimerIcon,   feature: "jobs", subsection: "Workforce" },
    { to: "/avg-job-time",      label: "Avg Job Time",     icon: TrendingUp,  feature: "jobs", subsection: "Workforce" },
    { to: "/log-history",       label: "Log History",      icon: History,     feature: "jobs", subsection: "Workforce" },
    // Field service
    { to: "/maintenance",  label: "Maintenance",  icon: Cog,      feature: "jobs", subsection: "Field Service" },
    { to: "/pool-service", label: "Pool Service", icon: Waves,    feature: "jobs", industry: "pools", subsection: "Field Service" },
    { to: "/equipment",    label: "Equipment",    icon: Wrench,   feature: "jobs", subsection: "Field Service" },
    { to: "/admin/assets", label: "Assets",       icon: Wrench,   feature: "jobs", subsection: "Field Service" },
    // Feb-2026 · C3 — Chemical Applications regulatory spray log.
    // Route gated by ``AdminOrManager`` in App.js (admin +
    // super_admin + manager). ``hard_rule: "manager_only"`` mirrors
    // Recurring Jobs / Pricebook so managers see it in the sidebar.
    // Technicians create sprays from mobile / field-log surfaces
    // and do not need the admin list view — the ``manager_only``
    // filter hides it from tech nav.
    { to: "/admin/chemical-applications", label: "Chemical Applications", icon: FlaskConical, feature: "jobs", hard_rule: "manager_only", subsection: "Field Service", aliases: ["Spray Log", "Pesticide Log", "Chemical Log", "REI Tracking"] },
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
    { to: "/landscape",   label: "Landscape AI",       icon: Image,       feature: "landscape",   industry: "landscaping", hard_rule: "admin_only", subsection: "AI Tools" },
    { to: "/cad",         label: "CAD Studio",         icon: PencilRuler, feature: "cad",         hard_rule: "admin_only", subsection: "AI Tools" },
    { to: "/measure",     label: "Satellite Measure",  icon: Ruler,       feature: "measure",     hard_rule: "admin_only", subsection: "AI Tools" },
    { to: "/virtual-bid", label: "Virtual Bid",        icon: Sparkles,    feature: "virtual_bid", hard_rule: "admin_only", subsection: "AI Tools" },
    { to: "/weather",     label: "Weather",            icon: Sun,         feature: "weather",     hard_rule: "admin_only", subsection: "AI Tools" },
    // System settings
    { to: "/settings/onboarding",   label: "Onboarding",    icon: Sparkles,   feature: "settings", subsection: "Settings" },
    { to: "/settings/tenant",       label: "Tenant Brand",  icon: Sparkles,   feature: "settings", subsection: "Settings" },
    { to: "/tenants",               label: "Tenants (super)", icon: Shield,   feature: "settings", hard_rule: "super_admin_only", subsection: "Settings" },
    { to: "/admin/comms/suppression-log", label: "Comms Suppression Log", icon: Shield, feature: "settings", hard_rule: "super_admin_only", subsection: "Settings" },
    { to: "/access-settings",       label: "Access Settings", icon: Shield,   feature: "permissions", subsection: "Settings" },
    { to: "/settings/integrations", label: "Integrations",    icon: Compass,  feature: "settings", subsection: "Settings" },
    // Feb-2026 · K55.a — Homeworks (POC) + Import from Homeworks nav
    // entries removed as part of the SuperCool + HomeWorks
    // integration sunset (see PHASE_K55_a_FRONTEND_REMOVAL.md).
    // Historical audit fields on customer/job/invoice docs are
    // preserved intact; only the write-path UI is gone.
    // Feb-2026 · Item 3 — Deletions audit (super_admin only).
    { to: "/admin/audit/deletions", label: "Deletion audit", icon: ShieldCheck, feature: "settings", hard_rule: "super_admin_only", subsection: "Settings" },
    // G0 · Feb-2026 — GPS driver-activity settings (admin-only).
    { to: "/admin/settings/gps",    label: "GPS Driver Activity", icon: MapPin, feature: "settings", hard_rule: "admin_only", subsection: "Settings" },
    { to: "/settings/maps",         label: "Maps",            icon: MapIcon,  feature: "settings", subsection: "Settings" },
    { to: "/settings/terms",        label: "Terms",           icon: ScrollText, feature: "settings", subsection: "Settings" },
    { to: "/settings/legal",        label: "Legal Docs",      icon: ScrollText, feature: "settings", subsection: "Settings" },
    { to: "/settings/ringcentral",  label: "RingCentral",     icon: Bell,     feature: "settings", subsection: "Settings" },
    // QuoteIQ Q1-UI · Feb 2026
    { to: "/admin/ai-credits", label: "AI Credits",     icon: Sparkles,   feature: "settings", subsection: "Settings" },
    { to: "/admin/chemicals",  label: "Chemical Products", icon: FlaskConical, feature: "settings", subsection: "Settings" },
    // Feb-2026 · Item 6 — Business Card editor (company-only vCard).
    { to: "/settings/business-card", label: "Business Card", icon: IdCard, feature: "settings", hard_rule: "admin_only", subsection: "Settings" },
    // Feb-2026 · Phase 20 P3 — Website SEO analyzer.
    { to: "/settings/website-seo",   label: "Website SEO", icon: SearchIcon, feature: "settings", hard_rule: "admin_only", subsection: "Settings" },
    // Feb-2026 · Phase 20 P4 — Local SEO checklist.
    { to: "/settings/local-seo",     label: "Local SEO",   icon: SearchIcon, feature: "settings", hard_rule: "admin_only", subsection: "Settings" },
  ]},

  // Feb-2026 · Pool Service PS-C — dedicated "Specialty Services"
  // group housing the recurring equipment-cleaning trackers.
  // Placed immediately after Operations (which owns "Field
  // Service" + "Inventory") so field-ops admins can pivot between
  // day-to-day dispatch and long-horizon maintenance cadence
  // without hopping across the Reports/Customers sections.  A
  // top-level group (not a subsection under Operations) per the
  // brief so the trackers show up as first-class nav destinations
  // when they become tenant-primary revenue drivers.
  { key: "specialty_services", label: "Specialty Services", icon: Waves, entries: [
    { to: "/tracking/filter",    label: "Filter Tracker",    icon: FilterFunnelIcon, feature: "jobs", industry: "pools", aliases: ["Filter Cleaning", "Filter Cleanings", "Cartridge Cleanings"] },
    { to: "/tracking/salt-cell", label: "Salt Cell Tracker", icon: Droplets,         feature: "jobs", industry: "pools", aliases: ["Salt Cell Replacements", "Salt Cell Cleanings", "Cell Replacements"] },
  ]},

  { key: "customers", label: "Customers", icon: Users, entries: [
    { to: "/customers",             label: "Customers",        icon: Users,      feature: "customers", subsection: "Directory", aliases: ["Clients", "Contacts", "Customer List", "Accounts"] },
    { to: "/admin/tags",            label: "Customer Tags",    icon: BadgeCheck, feature: "customers", subsection: "Directory" },
    { to: "/admin/service-reports", label: "Service Reports",  icon: ClipboardListIcon2, feature: "jobs",  subsection: "Directory" },
    { to: "/leads",                 label: "Leads",            icon: UserPlus,   feature: "customers", subsection: "Directory" },
    { to: "/leads/request",         label: "Lead Requests",    icon: Send,       feature: "customers", subsection: "Directory" },
    { to: "/tech/property-lookup",  label: "Property Lookup",  icon: HomeIcon,   feature: "customers", subsection: "Directory" },
    { to: "/deals",                 label: "Deals (Kanban)",   icon: GitBranch,  feature: "customers", subsection: "Sales" },
    // Phase C · Feb-2026 — Sales Pipeline Kanban (status-derived
    // across leads/quotes/jobs + intelligence-alerts risk swimlane).
    // Admin+super_admin+manager only; ``manager_only`` gate matches
    // the App.js ``<AdminOrManager>`` wrapper and the backend
    // ``insufficient_role_for_pipeline`` 403.
    { to: "/admin/pipeline",        label: "Sales Pipeline",   icon: KanbanSquare, feature: "customers", hard_rule: "manager_only", subsection: "Sales" },
    { to: "/ai-estimator",          label: "AI Estimator",      icon: Sparkles,   feature: "customers", subsection: "Sales" },
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
    { to: "/reports",                     label: "Reports Hub",       icon: BarChart3, feature: "reports", aliases: ["Analytics", "Reporting", "Business Reports"] },
    { to: "/analytics",                   label: "Analytics",         icon: TrendingUp, feature: "reports" },
    { to: "/reports/business-summary",    label: "Business Summary",  icon: PieChart,  feature: "reports" },
    { to: "/reports/forecast",            label: "Forecast",          icon: TrendingUp, feature: "reports" },
    { to: "/reports/customer-retention",  label: "Customer Retention",icon: Users,      feature: "reports" },
    // Feb-2026 · P37d — dispatcher-facing GPS Auto-Start audit
    // dashboard. Ops uses this to tune the 75m radius default and
    // diagnose consent / throttle patterns.
    { to: "/reports/gps-auto-start-audit", label: "GPS Auto-Start Audit", icon: MapPin,   feature: "reports" },
    { to: "/reports/revenue-slices",      label: "Revenue Slices",    icon: PieChart,  feature: "reports" },
    { to: "/admin/recurring-jobs",         label: "Recurring Jobs",      icon: CalendarClock, feature: "scheduling" },
    { to: "/admin/reports/pool-service",   label: "Pool Service Report", icon: Waves,   feature: "reports", industry: "pools" },
    { to: "/admin/reports/job-margins",    label: "Job Margin Leaderboard", icon: TrendingUp, feature: "reports" },
    // G2 · Feb-2026 — Driver Activity (server-detected GPS stops).
    { to: "/admin/reports/driver-activity", label: "Driver Activity",   icon: Truck, feature: "reports", hard_rule: "manager_only" },
    // MR0 · Feb-2026 — Public check-in moderation queue.
    { to: "/admin/moderation/checkins",     label: "Check-in Moderation", icon: ShieldCheck, feature: "reports", hard_rule: "manager_only" },
    // Phase SEO-A · Feb-2026 — Free on-page SEO auditor.
    { to: "/admin/seo/auditor",             label: "SEO Auditor",         icon: SearchIcon, feature: "reports", hard_rule: "manager_only" },
    // Phase SEO-C · Feb-2026 — Free keyword ideation (autocomplete + trends).
    { to: "/admin/seo/keywords",            label: "Keyword Ideation",    icon: SearchIcon, feature: "reports", hard_rule: "manager_only" },
    // Phase G4 · Feb-2026 — Per-user GPS controls (admin+/manager).
    { to: "/admin/settings/gps-users",      label: "GPS Per-User Controls", icon: MapPin, feature: "reports", hard_rule: "manager_only" },
    // MR1+MR2 · Feb-2026 — Public widget embed preview.
    { to: "/admin/moderation/widget-embed", label: "Widget Embed",        icon: Globe, feature: "reports", hard_rule: "manager_only" },
    { to: "/admin/reports/pricing-insights",label: "Pricing Insights",    icon: LineChart, feature: "reports" },
    // Phase 56-c · Aug-2026 — Pricebook cost comparison (per-item
    // supplier spread report). Same three-role gate as neighbouring
    // reports rows (admin + super_admin + manager) via
    // ``manager_only`` hard_rule.
    { to: "/admin/reports/pricebook-cost-comparison", label: "Cost Comparison", icon: Scale, feature: "reports", hard_rule: "manager_only" },
    // Phase 56-d · Aug-2026 — Supplier spend + margin report.
    // Tighter role gate than Cost Comparison — admin + super_admin
    // only, no manager. Cost basis is sensitive.
    { to: "/admin/reports/supplier-spend", label: "Supplier Spend & Margin", icon: TrendingUp, feature: "reports", hard_rule: "admin_only" },
    // Phase 54g · Feb-2026 — Wholesale supplier sync analytics.
    // Route guard: ``AdminOrManagerForSuppliers`` in App.js → admin +
    // super_admin + manager. Mirror by using ``feature: "reports"``
    // with ``hard_rule: "manager_only"`` (same pattern as the other
    // reports rows above — all three roles pass the filter because
    // ``manager_only`` isn't handled restrictively in the sidebar
    // filter and every one of those roles reads the ``reports``
    // feature).
    { to: "/reports/supplier-syncs",       label: "Supplier Syncs",       icon: RefreshCw, feature: "reports", hard_rule: "manager_only" },
    // Phase 54h · Aug-2026 — Wholesale Suppliers credentials/config page.
    // Sibling of the analytics-facing "Supplier Syncs" row above —
    // this one links operators to the credentials + connection-test
    // surface at ``/settings/suppliers``. Same three-role gate
    // (admin / super_admin / manager) via ``AdminOrManagerForSuppliers``
    // in App.js. ``feature: "settings"`` lands the entry in the same
    // RBAC bucket as neighbouring integrations rows below.
    { to: "/settings/suppliers",           label: "Wholesale Suppliers", icon: Boxes,     feature: "settings", hard_rule: "manager_only" },
    // Phase 56-a.5 · Aug-2026 — Pricebook Suppliers admin (vendor CRUD
    // that feeds the Ops Hub Price Book multi-supplier grid). Sibling
    // of the Wholesale Suppliers row above, but tighter role gate
    // (admin + super_admin only, no manager) per preflight §3.
    { to: "/settings/pricebook-suppliers", label: "Pricebook Suppliers", icon: Store,     feature: "settings", hard_rule: "admin_only" },
    // PB1 · Feb-2026 — Internal profit report (admin/super_admin only).
    { to: "/admin/reports/profit",         label: "Profit Report",       icon: TrendingUp, feature: "reports", hard_rule: "admin_only" },
    { to: "/admin/cfo/reports",            label: "CFO Reports",         icon: PieChart, feature: "reports" },
    // ``Vendor Bills`` (was here) relocated to Finance/Invoicing
    // in Commit 1.5 · Feb-2026 — see adminNav.js top of file for
    // rationale (payable-side invoice surface belongs in
    // Finance, not Reports).
    // Phase LZ4 (Feb 2026) — "Stripe Payments" nav entry removed
    // now that Stripe SDK is retired. Payment link generation
    // happens transparently via Lumino/Zapier; there is no
    // longer a Stripe reconciliation screen to link to.
    { to: "/admin/settings/chemical-costs",label: "Chemical Costs",      icon: Calculator, feature: "settings" },
    { to: "/admin/settings/ringcentral",   label: "RingCentral",         icon: Phone, feature: "settings" },
    { to: "/admin/budget",                 label: "Budget Setup",        icon: Calculator, feature: "settings" },
    { to: "/admin/budget/dashboard",       label: "Budget Dashboard",    icon: TrendingUp, feature: "reports" },
    { to: "/admin/budget/wizard",          label: "Budget Wizard",       icon: Sparkles, feature: "settings" },
    { to: "/landscape/time-clock",         label: "Landscape Time Clock", icon: Timer,  feature: "jobs", industry: "landscaping" },
    { to: "/access-history",              label: "Access History",    icon: ScrollText, feature: "audit_logs" },
    // Feb-2026 · Diagnostics — browse client-side errors captured by
    // the frontend Error Boundary (admin+ / super_admin only).
    { to: "/admin/diagnostics/errors",    label: "Client Errors",     icon: AlertTriangleIcon, feature: "audit_logs", hard_rule: "admin_only" },
    // LZ5 · Feb-2026 — Lumino payment-link backfill (super_admin only).
    // Not pinned by default; visible only to super_admin via hard_rule.
    { to: "/admin/tools/lumino-backfill", label: "Lumino Backfill",   icon: Zap,        feature: "reports", hard_rule: "super_admin_only" },
  ]},

  { key: "communications", label: "Communications", icon: Send, entries: [
    { to: "/admin/comms/email",       label: "Email Builder",  icon: Mail,          feature: "settings", hard_rule: "admin_only" },
    { to: "/admin/comms/sms",         label: "SMS Builder",    icon: MessageSquare, feature: "settings", hard_rule: "admin_only" },
    { to: "/admin/comms/templates",   label: "Templates",      icon: Layers,        feature: "settings", hard_rule: "admin_only" },
    { to: "/admin/comms/automations", label: "Automations",    icon: Zap,           feature: "settings", hard_rule: "admin_only" },
    { to: "/admin/comms/sends",       label: "Sends History",  icon: History,       feature: "settings", hard_rule: "admin_only" },
    { to: "/admin/comms/notes-archive", label: "Notes Archive", icon: FileText,     feature: "settings", hard_rule: "admin_only" },
  ]},

  { key: "reviews", label: "Reviews", icon: StarIcon, entries: [
    { to: "/admin/reviews",            label: "Dashboard", icon: StarIcon,       feature: "marketing", hard_rule: "admin_only" },
    { to: "/admin/reviews/requests",   label: "Requests",  icon: Send,           feature: "marketing", hard_rule: "admin_only" },
    { to: "/admin/reviews/platforms",  label: "Platforms", icon: Globe,          feature: "marketing", hard_rule: "admin_only" },
    { to: "/admin/reviews/widget",     label: "Widget",    icon: Globe,          feature: "marketing", hard_rule: "admin_only" },
  ]},

  // Phase A1 · Feb-2026 — Proactive Intelligence.
  // Bell + full-list page for missed-service (A1), chemistry upsell
  // (A2), churn risk (A3), and renewal-due (A4) alerts. The single
  // Alerts entry here lives at the same admin surface as the top-nav
  // <AlertBell/>; A2/A3/A4 will add sub-entries later. ``hard_rule``
  // is ``admin_or_super_admin`` — mirrors the backend contract
  // (``insufficient_role_for_alerts`` 403) so no other role sees the
  // link, even though the full-list page also role-gates itself.
  { key: "intelligence", label: "Intelligence", icon: BellIcon, entries: [
    { to: "/admin/intelligence/alerts", label: "Alerts", icon: BellIcon, feature: "settings", hard_rule: "admin_or_super_admin" },
  ]},

];

// Flatten for the command palette page-search.
export const NAV_FLAT = ADMIN_NAV_V2.flatMap((g) =>
  g.entries.map((e) => ({ ...e, group: g.label }))
);

// ─── Phase Feb-2026 · Multi-industry Phase C helper ────────────────
// Filter a nav-entry list by the tenant's active industries.
// Entries tagged with an ``industry`` slug are hidden unless that
// slug appears in ``industries``. Untagged entries (the vast
// majority) are always shown — Phase C's "light touch" scope only
// gates a handful of pool/landscape-specific surfaces.
//
// Empty ``industries`` array (tenant migration hasn't landed yet,
// or an admin explicitly cleared the array) → show everything
// (fail-open) so the sidebar never mysteriously empties out.
export function filterNavByIndustries(entries, industries) {
  if (!Array.isArray(entries)) return entries;
  const arr = Array.isArray(industries) ? industries : [];
  if (arr.length === 0) return entries;
  return entries.filter((e) => {
    if (!e || typeof e !== "object") return true;
    if (typeof e.industry !== "string") return true;
    return arr.includes(e.industry);
  });
}

export const KEYBOARD_SHORTCUTS = [
  { keys: "⌘K / Ctrl+K", label: "Focus global search" },
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
