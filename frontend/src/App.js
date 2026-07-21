import React from "react";
import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth";
import { ConfirmProvider } from "@/components/ui/confirm-dialog";
import { Toaster as SonnerToaster } from "@/components/ui/sonner";
import ScrollToTop from "@/components/ScrollToTop";
import AppLayout from "@/layouts/AppLayout";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import TenantPicker from "@/pages/TenantPicker";
import AdminDashboard from "@/pages/admin/Dashboard";
import Placeholder from "@/pages/Placeholder";
import CustomersList from "@/pages/customers/CustomersList";
import CustomerForm from "@/pages/customers/CustomerForm";
import CustomerDetail from "@/pages/customers/CustomerDetail";
import CustomerChemistry from "@/pages/customers/CustomerChemistry";
import CustomerChemistryHistory from "@/pages/customers/CustomerChemistryHistory";
import { RequestJobPage, AdminJobRequestsPage } from "@/pages/job_requests/JobRequestsPages";
import CalendarSchedule from "@/pages/schedule/CalendarSchedule";
import WorkstreamPage from "@/pages/workstream/WorkstreamPage";
import CFODashboard from "@/pages/cfo/CFODashboard";
import JobNew from "@/pages/jobs/JobNew";
import JobDetail from "@/pages/jobs/JobDetail";
import QuotesList from "@/pages/quotes/QuotesList";
import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";
import QuoteInvoiceDetail from "@/pages/quotes/QuoteInvoiceDetail";
import InvoicesList from "@/pages/invoices/InvoicesList";
import { MasterInvoicesList, MasterInvoiceNew, MasterInvoiceDetail } from "@/pages/invoices/MasterInvoice";
import PaymentHandlesSettings from "@/pages/settings/PaymentHandles";
import LateFeesSettings from "@/pages/settings/LateFees";
import BillingSettings from "@/pages/settings/BillingSettings";
import AutoVisitEmailSettings from "@/pages/settings/AutoVisitEmailSettings";
import PortalPhotos from "@/pages/portal/PortalPhotos";
import PortalReviews from "@/pages/portal/PortalReviews";
import AdminReviewsPage from "@/pages/admin/AdminReviewsPage";
import MarketingTemplatesLibraryPage from "@/pages/marketing/MarketingTemplatesLibraryPage";
import MarketingSegmentsPage from "@/pages/marketing/MarketingSegmentsPage";
import PortalVideos from "@/pages/portal/PortalVideos";
import {
  CommsTemplatesLibrary, CommsEmailBuilder, CommsSmsBuilder,
  CommsAutomationsPage, CommsSendsHistoryPage,
} from "@/pages/comms/CommsPages";
import {
  ReviewsDashboard, ReviewsRequestsPage,
  ReviewsPlatformsPage, ReviewsWidgetPage,
} from "@/pages/reviews/ReviewsPages";
import PublicReviewLanding from "@/pages/reviews/PublicReviewLanding";
import PublicReviewsWidgetPage from "@/pages/reviews/PublicReviewsWidgetPage";
// QuoteIQ Q1-UI · Feb 2026
import AICreditsPage from "@/pages/settings/AICreditsPage";
import ChemicalsPage from "@/pages/settings/ChemicalsPage";
import DealsKanbanPage from "@/pages/deals/DealsKanbanPage";
// QuoteIQ Q2-UI · Feb 2026
import AIEstimatorPage from "@/pages/estimates/AIEstimatorPage";
import PortalBook from "@/pages/portal/PortalBook";
import PortalChatsPage from "@/pages/portal/PortalChatsPage";
import AppointmentsQueue from "@/pages/admin/AppointmentsQueue";
import AdminAssets from "@/pages/admin/AdminAssets";
import MyOnboarding, { OnboardingTemplates, OnboardingQueue }
  from "@/pages/onboarding/EmployeeOnboarding";
import ReferralAnalyticsV2, { ReferralTiers }
  from "@/pages/admin/ReferralInsights";
import SeoAudits, { SeoAuditDetail } from "@/pages/seo/SeoAudits";
import ContentScorer from "@/pages/seo/ContentScorer";
import RankHeatmap from "@/pages/seo/RankHeatmap";
import TopicalMap from "@/pages/seo/TopicalMap";
import LlmVisibility from "@/pages/seo/LlmVisibility";
import AtlasAgent from "@/pages/seo/AtlasAgent";
import OttoAutoFix from "@/pages/seo/OttoAutoFix";
import WebsiteStudio, { WebsiteStudioEditor } from "@/pages/seo/WebsiteStudio";
import WhiteLabelReports, { WhiteLabelReportDetail } from "@/pages/seo/WhiteLabelReports";
import EstimatorList, { EstimatorNew, EstimatorDetail, EstimatorRates } from "@/pages/estimator/EstimatorPages";
import DunningSettings, { DunningQueue, DunningAnalytics } from "@/pages/dunning/DunningPages";
import InventoryList, { InventoryDetail, InventoryPOs, InventoryAlerts, InventoryAnalytics } from "@/pages/inventory/InventoryPages";
import CheckRegister, { CheckNew, CheckDetail, CheckBanks, CheckPayees, CheckAnalytics } from "@/pages/checks/ChecksPages";
import PropertyLookupPage from "@/pages/property-lookup/PropertyLookupPage";
import DispatchBoard, { WeatherReschedule } from "@/pages/dispatch/DispatchPages";
import CheckBatchNew, { CheckPayrollImport } from "@/pages/checks/CheckBatchPages";
import ChurnDashboard, { ContentRefresh } from "@/pages/customer-success/ChurnPages";
import WarrantyPlans, { WarrantyContracts, WarrantyClaims, PortalWarranties } from "@/pages/warranties/WarrantyPages";
import TermsSettings from "@/pages/settings/Terms";
import { LegalDocsList, LegalDocEditor } from "@/pages/settings/LegalDocs";
import { IntegrationsHub, MapSettings } from "@/pages/settings/IntegrationsPages";
import PortalTerms from "@/pages/portal/PortalTerms";
import {
  MarketingHub, BrandMemory,
  Posts, ApprovalQueue, ContentCalendar, SchedulingConfig, Performance,
  TemplatesHub, Reviews,
} from "@/pages/marketing/MarketingPages";
// M2 UI — new Campaigns experience overrides the legacy placeholders
// from MarketingPages.jsx. Routes below (/marketing/campaigns*) point
// at these.
import {
  CampaignsList, CampaignNew, CampaignDetail,
} from "@/pages/marketing/M2Campaigns";
import BeforeAfterStudio from "@/pages/marketing/BeforeAfterStudio";
import DirectoriesHub from "@/pages/marketing/directories/DirectoriesHub";
import NapProfilePage from "@/pages/marketing/directories/NapProfilePage";
import DirectorySubmissionsPage from "@/pages/marketing/directories/DirectorySubmissionsPage";
import AutopilotPage from "@/pages/marketing/AutopilotPage";
import InstaQuoteAdminPage from "@/pages/marketing/InstaQuoteAdmin";
import PublicInstaQuotePage from "@/pages/public/PublicInstaQuote";
import InstaScheduleAdminPage from "@/pages/marketing/InstaScheduleAdmin";
import PublicInstaSchedulePage from "@/pages/public/PublicInstaSchedule";
import TeamChatPage from "@/pages/chat/TeamChatPage";
import {
  SequencesList, SequenceNew, SequenceDetail,
} from "@/pages/marketing/SequencePages";
import {
  SeoHub, ArticlesList, ArticleEditor, KeywordSuggest, SeoAudit, RankGrid,
  WordPressSettings, GbpHub,
} from "@/pages/seo/SeoPages";
import {
  AiEmployeesList, AiEmployeeDetail, TasksPage,
  AccessSettings, AccessHistory, RingCentralSettings, CallLogsPage,
} from "@/pages/aiops/AiOpsPages";
import NotificationsPage from "@/pages/notifications/NotificationsPage";
import NotificationPrefs from "@/pages/settings/NotificationPrefs";
import StripeReconciliation from "@/pages/finance/StripeReconciliation";
import {
  D2dDashboard, D2dMap, D2dKnocks, D2dOpenLeads, D2dSoldLeads, D2dReport, D2dLeaderboard,
} from "@/pages/d2d/D2dPages";
import { DispatchMap, ScheduleMap } from "@/pages/ops/MapPages";
import NotFound from "@/pages/NotFound";
import { LeadsList, CheckinsList } from "@/pages/misc/GapClosures";
import { CommunicationThread, TechnicianProfile, FormsList, FormEditor, PublicForm } from "@/pages/phase14/Phase14Pages";
import { PermissionsProvider } from "@/hooks/usePermissions";
import {
  LandscapeAI, CadList, CadEditor, SatelliteMeasure, VirtualBid,
  DigitalCardList, PublicCard, WeatherHub,
} from "@/pages/aitools/AiToolsPages";
import { EstimatesList, EstimatorSettings, EstimatorTemplates, EstimatorEditor } from "@/pages/estimator/Estimator";
import OpsHub from "@/pages/ops/OpsHub";
import ReportsHub from "@/pages/reports/ReportsHub";
import BusinessSummary from "@/pages/reports/BusinessSummary";
import Forecast from "@/pages/reports/Forecast";
import CustomerRetentionReport from "@/pages/reports/CustomerRetentionReport";
import IncomeByCategory from "@/pages/reports/IncomeByCategoryPage";
import {
  RevenueByCity, RevenueByCrew, RevenueByCustomer, GrossSales, InvoicedItems,
} from "@/pages/reports/RevenueSlices";
import {
  PaymentsLedger, AutoBilling, ImpExp, IncomeCategoriesCrud,
} from "@/pages/finance/FinancePages";
import AutobillingRuns from "@/pages/finance/AutobillingRuns";
import PortalHome from "@/pages/portal/PortalHome";
import {
  PortalServices, PortalServiceDetail,
  PortalInvoices, PortalInvoiceDetail,
  PortalEstimates, PortalEstimateDetail,
  PortalPayments, PortalPaymentMethod,
  PortalDocuments, PortalMessages, PortalProfile,
  PortalRequestService, PortalPaymentComplete,
} from "@/pages/portal/PortalPages";
import {
  PortalServiceReports, PortalServiceReportDetail,
} from "@/pages/portal/PortalServiceReports";
import PortalSignPage from "@/pages/portal/PortalSign";
import { CsatDashboard, CsatDetail, PublicCsat } from "@/pages/csat/CsatPages";
import { RealtimeProvider } from "@/realtime/NotificationSocket";
import AnalyticsPage from "@/pages/analytics/AnalyticsPage";
import OnboardingPage from '@/pages/onboarding/OnboardingPage';
import LeadRequestPage from "@/pages/leads/LeadRequestPage";
import PublicLeadRequestPage from "@/pages/public/PublicLeadRequest";
import TenantsAdminPage, { TenantBrandSettings } from "@/pages/tenants/TenantsAdminPage";
import {
  TimesheetsPage as WorkforceTimesheets, CrewMapPage as WorkforceCrewMap,
  JobCostingPage as WorkforceJobCosting, MileagePage as WorkforceMileage,
} from "@/pages/workforce/WorkforcePages";
import {
  BusinessOSLayout, OverviewPage as OsOverview, SopsPage as OsSops,
  RolesPage as OsRoles, ScorecardsPage as OsScorecards, HuddlesPage as OsHuddles,
  LeanboardsPage as OsLeanboards, SprintsPage as OsSprints,
} from "@/pages/os/BusinessOS";
import { LanaChatPage as OsLana } from "@/pages/os/LanaAndPlans";
import TodaySchedule from "@/pages/schedule/TodaySchedule";
import { TechHuddlePage, TechTimeClockPage } from "@/pages/tech/TechPages";
import ServiceReport from "@/pages/tech/ServiceReport";
import ToolsHub from "@/pages/tech/ToolsHub";
import ComingSoonPage from "@/pages/common/ComingSoonPage";
import PoolCalculators from "@/pages/tech/PoolCalculators";
import BusinessPricingTools from "@/pages/admin/BusinessPricingTools";
import BusinessAnalysisTools from "@/pages/admin/BusinessAnalysisTools";
import DocumentGenerators from "@/pages/admin/DocumentGenerators";
import ServicePriceChecker from "@/pages/admin/ServicePriceChecker";
import PricingDefaultsEditor from "@/pages/admin/PricingDefaultsEditor";
import BusinessCard from "@/pages/tech/BusinessCard";
import LandscapingTimeClock from "@/pages/tech/LandscapingTimeClock";
import PoolServiceReport from "@/pages/reports/PoolServiceReport";
import JobMarginLeaderboard from "@/pages/admin/JobMarginLeaderboard";
import ChemicalCosts from "@/pages/admin/ChemicalCosts";
import RecurringJobs from "@/pages/admin/RecurringJobs";
import CFOReports from "@/pages/admin/CFOReports";
import VendorBills from "@/pages/admin/VendorBills";
import PricingInsights from "@/pages/admin/PricingInsights";
import RingCentralAdmin from "@/pages/admin/RingCentralAdmin";
import TrainingList from "@/pages/training/TrainingList";
import TrainingModuleDetail from "@/pages/training/TrainingModuleDetail";
import TrainingQuiz from "@/pages/training/TrainingQuiz";
import AdminTraining from "@/pages/training/AdminTraining";
import BudgetSetup from "@/pages/budget/BudgetSetup";
import BudgetDashboard from "@/pages/budget/BudgetDashboard";
import BudgetWizard from "@/pages/budget/BudgetWizard";
import { ComposerPage as SocialComposer, CalendarPage as SocialCalendar,
         LibraryPage as SocialLibrary, DraftsPage as SocialDrafts } from "@/pages/social/SocialSuite";
import { ApprovalsPage as SocialApprovals, BulkUploadPage as SocialBulkUpload,
         ShortLinksPage as SocialShortLinks, BrandKitPage as SocialBrandKit }
  from "@/pages/social/SocialExtras";
import ServiceTemplatesEditor from "@/pages/admin/ServiceTemplatesEditor";
// Phase 2 · Templates Library — Admin Web UI
import TemplatesLibraryPage from "@/pages/admin/TemplatesLibraryPage";
import TemplateFillPage from "@/pages/admin/TemplateFillPage";
import TemplateInstanceNewRedirect from "@/pages/admin/TemplateInstanceNewRedirect";
// Phase 4 · Batch B — Handbook + Onboarding
import HandbookPage from "@/pages/HandbookPage";
import EmployeeOnboardingChecklistPage from "@/pages/OnboardingPage";
import AdminOnboardingDashboardPage from "@/pages/admin/AdminOnboardingDashboardPage";

function CustomerServiceReportRedirect() {
  // Preserve the report id when redirecting from the /customer alias to
  // the primary /portal path. Kept alongside AdminOnly/NoTech so route
  // wiring stays self-contained.
  const { id } = useParams();
  return <Navigate to={`/portal/service-reports/${id}`} replace />;
}

// Phase 56.19 · P0 — Preserve :id when bouncing bookmarked
// /master-invoices/:id links to the current /invoices/master/:id
// canonical path. Mirrors CustomerServiceReportRedirect above.
function MasterInvoicesRedirect() {
  const { id } = useParams();
  return <Navigate to={`/invoices/master/${id}`} replace />;
}

function AdminOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user || (user.role !== "admin" && user.role !== "super_admin")) {
    return <Navigate to="/" replace />;
  }
  return children;
}

// Phase 49.4 + 49.5 — Block technicians from customer + billing routes.
// Admins/super/customer still allowed (customer for their portal, admin
// for management). Tech → back to /.
function NoTech({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user?.role === "technician") return <Navigate to="/" replace />;
  return children;
}

/** Root "/" gate: admin/super sees the AdminDashboard, techs get their
 *  schedule (Dashboard is removed for tech role in Phase 16C add-on),
 *  customers get sent to their portal home. */
function RoleAwareIndex() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user?.role === "technician") return <Navigate to="/schedule" replace />;
  if (user?.role === "customer") return <Navigate to="/portal/home" replace />;
  return <AdminDashboard />;
}

export default function App() {
  return (
    <AuthProvider>
      <PermissionsBridge>
      <RealtimeProvider>
      <ConfirmProvider>
      <BrowserRouter>
        <ScrollToTop />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/tenant-picker" element={<TenantPicker />} />
          <Route path="/public/card/:slug" element={<PublicCard />} />
          <Route path="/f/:slug" element={<PublicForm />} />
          {/* Phase 15A public magic-link routes (no auth) */}
          <Route path="/csat/:token" element={<PublicCsat />} />
          <Route path="/portal/sign/:token" element={<PortalSignPage />} />
          {/* Phase 15B slot-in — Lead Request public form (no auth) */}
          <Route path="/lead-request/:token" element={<PublicLeadRequestPage />} />

          {/* Reviews Subsystem · Phase 2 — public flows (no auth) */}
          <Route path="/reviews/r/:token" element={<PublicReviewLanding />} />
          <Route path="/reviews/:tenant_slug" element={<PublicReviewsWidgetPage />} />

          {/* QuoteIQ Q4 · public InstaQuote portal — no auth. */}
          <Route path="/quote/:slug" element={<PublicInstaQuotePage />} />

          {/* QuoteIQ Q5 · public InstaSchedule portal — no auth. */}
          <Route path="/book/:slug" element={<PublicInstaSchedulePage />} />

          {/* Everything else lives inside the protected shell (side nav + top bar + bottom tabs). */}
          <Route path="/" element={<AppLayout />}>
            {/* Root — techs are redirected to their schedule (Dashboard removed for tech role). */}
            <Route index element={<RoleAwareIndex />} />

            {/* Customers (Phase 2 / Phase 56.2 cohorts) */}
            <Route path="customers" element={<NoTech><CustomersList /></NoTech>} />
            <Route path="customers/active" element={<NoTech><CustomersList /></NoTech>} />
            <Route path="customers/inactive" element={<NoTech><CustomersList /></NoTech>} />
            <Route path="customers/new" element={<NoTech><CustomerForm /></NoTech>} />
            <Route path="customers/:id" element={<NoTech><CustomerDetail /></NoTech>} />
            <Route path="customers/:id/edit" element={<NoTech><CustomerForm /></NoTech>} />
            <Route path="customers/:id/chemistry" element={<NoTech><CustomerChemistry /></NoTech>} />

            {/* Phase 56.4 · Tech Job Request workflow */}
            <Route path="request-job" element={<RequestJobPage />} />
            <Route path="admin/job-requests" element={<AdminJobRequestsPage />} />
            <Route path="admin/reviews" element={<AdminOnly><AdminReviewsPage /></AdminOnly>} />

            {/* Jobs (Phase 2) */}
            {/* Phase 30 · Jobs list retired — techs & admins land on the unified calendar. */}
            <Route path="jobs" element={<Navigate to="/schedule" replace />} />
            <Route path="jobs/new" element={<JobNew />} />
            <Route path="jobs/:id" element={<JobDetail />} />

            {/* Quotes / Invoices / Master / Estimator / Settings (Phase 3) */}
            <Route path="quotes" element={<NoTech><QuotesList /></NoTech>} />
            <Route path="quotes/new" element={<NoTech><QuoteInvoiceNew docType="quote" /></NoTech>} />
            <Route path="quotes/:id" element={<NoTech><QuoteInvoiceDetail docType="quote" /></NoTech>} />

            <Route path="invoices" element={<NoTech><InvoicesList /></NoTech>} />
            <Route path="invoices/new" element={<NoTech><QuoteInvoiceNew docType="invoice" /></NoTech>} />
            <Route path="invoices/master" element={<NoTech><MasterInvoicesList /></NoTech>} />
            <Route path="invoices/master/new" element={<NoTech><MasterInvoiceNew /></NoTech>} />
            <Route path="invoices/master/:id" element={<NoTech><MasterInvoiceDetail /></NoTech>} />
            <Route path="invoices/:id" element={<NoTech><QuoteInvoiceDetail docType="invoice" /></NoTech>} />

            <Route path="estimator" element={<EstimatesList />} />
            <Route path="estimator/settings" element={<EstimatorSettings />} />
            <Route path="estimator/templates" element={<EstimatorTemplates />} />
            <Route path="estimator/new" element={<EstimatorEditor />} />
            <Route path="estimator/:id" element={<EstimatorEditor />} />

            <Route path="settings/payment-handles" element={<PaymentHandlesSettings />} />
            <Route path="settings/late-fees" element={<AdminOnly><LateFeesSettings /></AdminOnly>} />
            <Route path="settings/billing" element={<AdminOnly><BillingSettings /></AdminOnly>} />
            <Route path="settings/terms" element={<AdminOnly><TermsSettings /></AdminOnly>} />
            <Route path="settings/legal" element={<AdminOnly><LegalDocsList /></AdminOnly>} />
            <Route path="settings/integrations" element={<AdminOnly><IntegrationsHub /></AdminOnly>} />
            <Route path="settings/maps" element={<AdminOnly><MapSettings /></AdminOnly>} />
            <Route path="settings/legal/:slug" element={<AdminOnly><LegalDocEditor /></AdminOnly>} />
            <Route path="portal/terms" element={<PortalTerms />} />

            {/* Phase 7 — Marketing Studio */}
            <Route path="marketing" element={<AdminOnly><MarketingHub /></AdminOnly>} />
            <Route path="marketing/brand" element={<AdminOnly><BrandMemory /></AdminOnly>} />
            <Route path="marketing/campaigns" element={<AdminOnly><CampaignsList /></AdminOnly>} />
            <Route path="marketing/campaigns/new" element={<AdminOnly><CampaignNew /></AdminOnly>} />
            <Route path="marketing/campaigns/:id" element={<AdminOnly><CampaignDetail /></AdminOnly>} />
            <Route path="marketing/posts" element={<AdminOnly><Posts /></AdminOnly>} />
            <Route path="marketing/queue" element={<AdminOnly><ApprovalQueue /></AdminOnly>} />
            <Route path="marketing/calendar" element={<AdminOnly><ContentCalendar /></AdminOnly>} />
            <Route path="marketing/scheduling" element={<AdminOnly><SchedulingConfig /></AdminOnly>} />
            <Route path="marketing/performance" element={<AdminOnly><Performance /></AdminOnly>} />
            <Route path="marketing/templates" element={<AdminOnly><TemplatesHub /></AdminOnly>} />
            <Route path="marketing/template-library" element={<AdminOnly><MarketingTemplatesLibraryPage /></AdminOnly>} />
            <Route path="marketing/segments" element={<AdminOnly><MarketingSegmentsPage /></AdminOnly>} />
            <Route path="marketing/reviews" element={<AdminOnly><Reviews /></AdminOnly>} />
            <Route path="marketing/sequences" element={<AdminOnly><SequencesList /></AdminOnly>} />
            <Route path="marketing/sequences/new" element={<AdminOnly><SequenceNew /></AdminOnly>} />
            <Route path="marketing/sequences/:id" element={<AdminOnly><SequenceDetail /></AdminOnly>} />
            <Route path="marketing/before-after" element={<AdminOnly><BeforeAfterStudio /></AdminOnly>} />
            <Route path="marketing/directories" element={<AdminOnly><DirectoriesHub /></AdminOnly>} />
            <Route path="marketing/directories/nap-profile" element={<AdminOnly><NapProfilePage /></AdminOnly>} />
            <Route path="marketing/directories/submissions" element={<AdminOnly><DirectorySubmissionsPage /></AdminOnly>} />
            <Route path="marketing/autopilot" element={<AdminOnly><AutopilotPage /></AdminOnly>} />
            <Route path="marketing/instaquote" element={<AdminOnly><InstaQuoteAdminPage /></AdminOnly>} />
            <Route path="marketing/instaschedule" element={<AdminOnly><InstaScheduleAdminPage /></AdminOnly>} />
            <Route path="chat" element={<TeamChatPage />} />

            {/* Phase 8 — SEO + GBP */}
            <Route path="seo" element={<AdminOnly><SeoHub /></AdminOnly>} />
            <Route path="seo/articles" element={<AdminOnly><ArticlesList /></AdminOnly>} />
            <Route path="seo/articles/:id" element={<AdminOnly><ArticleEditor /></AdminOnly>} />
            <Route path="seo/keywords" element={<AdminOnly><KeywordSuggest /></AdminOnly>} />
            <Route path="seo/audit" element={<AdminOnly><SeoAudit /></AdminOnly>} />
            <Route path="seo/rank-grid" element={<AdminOnly><RankGrid /></AdminOnly>} />
            <Route path="seo/wordpress" element={<AdminOnly><WordPressSettings /></AdminOnly>} />
            <Route path="gbp" element={<AdminOnly><GbpHub /></AdminOnly>} />

            {/* Phase 9 — AI Ops */}
            <Route path="ai-employees" element={<AdminOnly><AiEmployeesList /></AdminOnly>} />
            <Route path="ai-employees/:id" element={<AdminOnly><AiEmployeeDetail /></AdminOnly>} />
            <Route path="ai-chat/:id" element={<AdminOnly><AiEmployeeDetail /></AdminOnly>} />
            <Route path="tasks" element={<AdminOnly><TasksPage /></AdminOnly>} />
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="settings/notifications" element={<NotificationPrefs />} />
            <Route path="admin/finance/stripe-payments" element={<AdminOnly><StripeReconciliation /></AdminOnly>} />

            {/* Phase 15A — CSAT admin */}
            <Route path="csat" element={<AdminOnly><CsatDashboard /></AdminOnly>} />
            <Route path="csat/detail/:sid" element={<AdminOnly><CsatDetail /></AdminOnly>} />

            {/* Phase 15B — Analytics + Onboarding */}
            <Route path="analytics" element={<AdminOnly><AnalyticsPage /></AdminOnly>} />
            <Route path="onboarding" element={<AdminOnly><OnboardingPage /></AdminOnly>} />
            <Route path="settings/onboarding" element={<AdminOnly><OnboardingPage /></AdminOnly>} />

            {/* Phase 15B slot-in — Lead Request Distributor */}
            <Route path="leads/request" element={<AdminOnly><LeadRequestPage /></AdminOnly>} />

            {/* Phase 15D Stage 2 — Tenants (super-admin) + own brand editor (admin) */}
            <Route path="tenants" element={<AdminOnly><TenantsAdminPage /></AdminOnly>} />
            <Route path="settings/tenant" element={<AdminOnly><TenantBrandSettings /></AdminOnly>} />
            <Route path="access-settings" element={<AdminOnly><AccessSettings /></AdminOnly>} />
            <Route path="access-history" element={<AdminOnly><AccessHistory /></AdminOnly>} />
            <Route path="settings/ringcentral" element={<AdminOnly><RingCentralSettings /></AdminOnly>} />
            <Route path="call-logs" element={<AdminOnly><CallLogsPage /></AdminOnly>} />

            {/* Phase 16A — Workforce Ops */}
            <Route path="workforce/timesheets" element={<AdminOnly><WorkforceTimesheets /></AdminOnly>} />
            <Route path="workforce/crew-map" element={<AdminOnly><WorkforceCrewMap /></AdminOnly>} />
            <Route path="workforce/job-costing" element={<AdminOnly><WorkforceJobCosting /></AdminOnly>} />
            <Route path="workforce/mileage" element={<AdminOnly><WorkforceMileage /></AdminOnly>} />

            {/* Phase 16C — Tech Today Schedule */}
            <Route path="schedule/today" element={<Navigate to="/schedule" replace />} />
            <Route path="schedule" element={<CalendarSchedule />} />
            <Route path="schedule/legacy-timeline" element={<TodaySchedule />} />
            {/* Phase 31 · Step 2b — Workstream (tap-job telemetry feed) */}
            <Route path="workstream" element={<WorkstreamPage />} />
            {/* Phase 32 · Step 2 — AI CFO dashboard (admin only, RBAC in-page) */}
            <Route path="cfo" element={<CFODashboard />} />
            <Route path="tech/huddle" element={<TechHuddlePage />} />
            <Route path="tech/time-clock" element={<TechTimeClockPage />} />
            {/* Phase 46.3 — Landscaping-only time clock (backend RBAC enforced) */}
            <Route path="landscape/time-clock" element={<LandscapingTimeClock />} />
            {/* Phase 46.4 — Pool Service Report (admin/super_admin) */}
            <Route path="admin/reports/pool-service" element={<AdminOnly><PoolServiceReport /></AdminOnly>} />
            {/* Phase 50.D — Job Margin Leaderboard (admin/super_admin) */}
            <Route path="admin/reports/job-margins" element={<AdminOnly><JobMarginLeaderboard /></AdminOnly>} />
            {/* Phase 50.A — Chemical Costs CRUD (admin/super_admin) */}
            <Route path="admin/settings/chemical-costs" element={<AdminOnly><ChemicalCosts /></AdminOnly>} />
            {/* Phase 51.I — Recurring Jobs (admin/super_admin) */}
            <Route path="admin/recurring-jobs" element={<AdminOnly><RecurringJobs /></AdminOnly>} />
            {/* Phase 51.K — CFO Reports (admin/super_admin) */}
            <Route path="admin/cfo/reports" element={<AdminOnly><CFOReports /></AdminOnly>} />
            <Route path="admin/finance/bills" element={<AdminOnly><VendorBills /></AdminOnly>} />
            <Route path="admin/reports/pricing-insights" element={<AdminOnly><PricingInsights /></AdminOnly>} />
            {/* Phase 54 — RingCentral admin (settings + test + event log) */}
            <Route path="admin/settings/ringcentral" element={<AdminOnly><RingCentralAdmin /></AdminOnly>} />
            <Route path="admin/ringcentral-test" element={<AdminOnly><RingCentralAdmin /></AdminOnly>} />
            {/* Phase 56.13b — Training web UI */}
            <Route path="tests" element={<TrainingList />} />
            <Route path="training" element={<Navigate to="/tests" replace />} />
            <Route path="tests/:code" element={<TrainingModuleDetail />} />
            <Route path="tests/:code/quiz" element={<TrainingQuiz />} />
            <Route path="admin/training" element={<AdminOnly><AdminTraining /></AdminOnly>} />
            {/* Phase 47 — Budgeting Suite */}
            <Route path="admin/budget" element={<AdminOnly><BudgetSetup /></AdminOnly>} />
            <Route path="admin/budget/dashboard" element={<AdminOnly><BudgetDashboard /></AdminOnly>} />
            <Route path="admin/budget/wizard" element={<AdminOnly><BudgetWizard /></AdminOnly>} />
            {/* Phase 29 — All My Tools hub (tech + admin). Non-role users are
                redirected inside the component. */}
            <Route path="tech/tools" element={<ToolsHub />} />
            <Route path="tech/tools/calculators" element={<PoolCalculators />} />
            {/* Tech Nav 404 fix · Feb 2026 — bare-path redirects + stubs so
                the tech hamburger menu links stop 404ing.
                  /calculators → /tech/tools/calculators (existing tech route)
                  /time-clock  → /tech/time-clock       (existing tech route)
                  /assets      → coming-soon stub       (admin/assets is AdminOnly)
                  /inventory   → coming-soon stub       (admin/inventory is AdminOnly)
                Follow-up P2 tasks: build real tech-side read-only variants
                of /assets and /inventory, plus a tech-side /inbox and
                /settings/auto-clockin. Those tech-menu entries were removed
                for now — see nav/roleNav.js. */}
            <Route path="calculators" element={<Navigate to="/tech/tools/calculators" replace />} />
            <Route path="time-clock" element={<Navigate to="/tech/time-clock" replace />} />
            <Route path="assets" element={<ComingSoonPage
              title="My Equipment (coming soon)"
              message="A read-only view of your assigned tools, meters, and truck kit is on the way."
              contactHint="In the meantime, ask an admin to look up assigned equipment on your behalf."
              testId="tech-assets-coming-soon"
            />} />
            <Route path="inventory" element={<ComingSoonPage
              title="Truck Inventory (coming soon)"
              message="Real-time truck-load counts and quick quantity adjustments are being built for the technician workspace."
              contactHint="Until then, an admin can adjust inventory levels for you from the admin dashboard."
              testId="tech-inventory-coming-soon"
            />} />
            <Route path="admin/tools/pricing" element={<AdminOnly><BusinessPricingTools /></AdminOnly>} />
            <Route path="admin/tools/analysis" element={<AdminOnly><BusinessAnalysisTools /></AdminOnly>} />
            <Route path="admin/tools/documents" element={<AdminOnly><DocumentGenerators /></AdminOnly>} />
            <Route path="admin/tools/price-check" element={<AdminOnly><ServicePriceChecker /></AdminOnly>} />
            <Route path="admin/settings/pricing-defaults" element={<AdminOnly><PricingDefaultsEditor /></AdminOnly>} />
            {/* NFC business card — role-agnostic personal view (uses /api/card).
                The /card route below is the admin-only team card manager. */}
            <Route path="tech/card" element={<BusinessCard />} />
            {/* Phase 18B follow-up — Service Report (auto-opens on clock-in) */}
            <Route path="jobs/:id/service-report" element={<ServiceReport />} />

            {/* Phase 18A — Social Suite (admin/marketing only) */}
            <Route path="social/composer" element={<AdminOnly><SocialComposer /></AdminOnly>} />
            <Route path="social/calendar" element={<AdminOnly><SocialCalendar /></AdminOnly>} />
            <Route path="social/library" element={<AdminOnly><SocialLibrary /></AdminOnly>} />
            <Route path="social/drafts" element={<AdminOnly><SocialDrafts /></AdminOnly>} />
            {/* Phase 18A.1 — approvals · bulk · short-links · brand kit */}
            <Route path="social/approvals" element={<AdminOnly><SocialApprovals /></AdminOnly>} />
            <Route path="social/bulk-upload" element={<AdminOnly><SocialBulkUpload /></AdminOnly>} />
            <Route path="social/short-links" element={<AdminOnly><SocialShortLinks /></AdminOnly>} />
            <Route path="social/brand-kit" element={<AdminOnly><SocialBrandKit /></AdminOnly>} />
            {/* Admin editor for service report templates (pool/landscape/generic) */}
            <Route path="admin/settings/service-templates" element={<AdminOnly><ServiceTemplatesEditor /></AdminOnly>} />
            {/* Phase 2 · Templates Library — Admin Web UI */}
            <Route path="admin/templates" element={<AdminOnly><TemplatesLibraryPage /></AdminOnly>} />
            <Route path="admin/templates/instances/new" element={<AdminOnly><TemplateInstanceNewRedirect /></AdminOnly>} />
            <Route path="admin/templates/instances/:id" element={<AdminOnly><TemplateFillPage /></AdminOnly>} />
            {/* Phase 4 · Batch B — Handbook + Onboarding */}
            <Route path="handbook" element={<HandbookPage />} />
            <Route path="handbook/:code" element={<HandbookPage />} />
            <Route path="onboarding-checklist" element={<EmployeeOnboardingChecklistPage />} />
            <Route path="admin/onboarding" element={<AdminOnly><AdminOnboardingDashboardPage /></AdminOnly>} />
            <Route path="admin/settings/auto-visit-email" element={<AdminOnly><AutoVisitEmailSettings /></AdminOnly>} />

            {/* Phase 16B — Business OS */}
            <Route path="os" element={<AdminOnly><BusinessOSLayout /></AdminOnly>}>
              <Route index element={<OsOverview />} />
              <Route path="dashboard" element={<OsOverview />} />
              <Route path="sops" element={<OsSops />} />
              <Route path="roles" element={<OsRoles />} />
              <Route path="scorecards" element={<OsScorecards />} />
              <Route path="huddle" element={<OsHuddles />} />
              <Route path="huddles" element={<OsHuddles />} />
              <Route path="leanboards" element={<OsLeanboards />} />
              <Route path="sprints" element={<OsSprints />} />
              <Route path="lana" element={<OsLana />} />
            </Route>

            {/* Phase 6 — Finance + Reports */}
            <Route path="reports" element={<AdminOnly><ReportsHub /></AdminOnly>} />
            <Route path="reports/business-summary" element={<AdminOnly><BusinessSummary /></AdminOnly>} />
            <Route path="reports/forecast" element={<AdminOnly><Forecast /></AdminOnly>} />
            <Route path="reports/customer-retention" element={<AdminOnly><CustomerRetentionReport /></AdminOnly>} />
            <Route path="reports/revenue-by-city" element={<AdminOnly><RevenueByCity /></AdminOnly>} />
            <Route path="reports/revenue-by-crew" element={<AdminOnly><RevenueByCrew /></AdminOnly>} />
            <Route path="reports/revenue-by-customer" element={<AdminOnly><RevenueByCustomer /></AdminOnly>} />
            <Route path="reports/gross-sales" element={<AdminOnly><GrossSales /></AdminOnly>} />
            <Route path="reports/invoiced-items" element={<AdminOnly><InvoicedItems /></AdminOnly>} />
            <Route path="income-by-category" element={<AdminOnly><IncomeByCategory /></AdminOnly>} />
            <Route path="income-categories" element={<AdminOnly><IncomeCategoriesCrud /></AdminOnly>} />
            <Route path="payments" element={<AdminOnly><PaymentsLedger /></AdminOnly>} />
            <Route path="auto-billing" element={<AdminOnly><AutoBilling /></AdminOnly>} />
            <Route path="admin/autobilling-runs" element={<AdminOnly><AutobillingRuns /></AdminOnly>} />
            {/* Phase 56.19 · P0 · permanent aliases for the legacy
                /master-invoices URLs — some users bookmarked the
                pre-refactor path. Preserves back-compat. */}
            <Route path="master-invoices" element={<Navigate to="/invoices/master" replace />} />
            <Route path="master-invoices/new" element={<Navigate to="/invoices/master/new" replace />} />
            <Route path="master-invoices/:id" element={<MasterInvoicesRedirect />} />
            {/* Phase 56.19 · RC-diagnostic href fix — the RC unmatched-
                SMS notification pointed at this path but no frontend
                page existed. Redirect to the notifications inbox filtered
                on the same kind so the click lands somewhere real. */}
            <Route path="admin/unmatched-communications" element={<AdminOnly><Navigate to="/notifications?kind=rc_sms_inbound_unmatched" replace /></AdminOnly>} />
            <Route path="impexp" element={<AdminOnly><ImpExp /></AdminOnly>} />

            {/* Ops hub (Phase 5) — all 16 sub-pages route into one tabbed shell */}
            <Route path="ops" element={<OpsHub />} />
            <Route path="dispatch" element={<OpsHub />} />
            <Route path="dispatch/map" element={<AdminOnly><DispatchMap /></AdminOnly>} />
            <Route path="schedule" element={<OpsHub />} />
            <Route path="schedule/map" element={<AdminOnly><ScheduleMap /></AdminOnly>} />
            <Route path="routes" element={<OpsHub />} />
            <Route path="workstream" element={<OpsHub />} />
            <Route path="crews" element={<OpsHub />} />
            <Route path="team" element={<OpsHub />} />
            <Route path="timesheets" element={<OpsHub />} />
            <Route path="timeclock/today" element={<OpsHub />} />
            <Route path="coverage" element={<OpsHub />} />
            <Route path="maintenance" element={<OpsHub />} />
            <Route path="pool-service" element={<OpsHub />} />
            <Route path="equipment" element={<OpsHub />} />
            <Route path="price-book" element={<OpsHub />} />
            <Route path="log-history" element={<OpsHub />} />
            <Route path="job-timers" element={<OpsHub />} />
            <Route path="avg-job-time" element={<OpsHub />} />

            {/* Phase 13 parity-gap closures */}
            <Route path="leads" element={<AdminOnly><LeadsList /></AdminOnly>} />
            <Route path="checkins" element={<AdminOnly><CheckinsList /></AdminOnly>} />

            {/* Phase 14 additions */}
            <Route path="communication/:id" element={<CommunicationThread />} />
            <Route path="technician/:id" element={<TechnicianProfile />} />
            <Route path="forms" element={<AdminOnly><FormsList /></AdminOnly>} />
            <Route path="forms/:id" element={<AdminOnly><FormEditor /></AdminOnly>} />

            {/* Phase 10 — D2D Sales (open to admin + technician) */}
            <Route path="d2d" element={<D2dDashboard />} />
            <Route path="d2d/map" element={<D2dMap />} />
            <Route path="d2d/knocks" element={<D2dKnocks />} />
            <Route path="d2d/open-leads" element={<D2dOpenLeads />} />
            <Route path="d2d/sold-leads" element={<D2dSoldLeads />} />
            <Route path="d2d/report" element={<AdminOnly><D2dReport /></AdminOnly>} />
            <Route path="d2d/leaderboard" element={<D2dLeaderboard />} />

            {/* Phase 11 — AI & Tools (admin-only) */}
            <Route path="landscape" element={<AdminOnly><LandscapeAI /></AdminOnly>} />
            <Route path="cad" element={<AdminOnly><CadList /></AdminOnly>} />
            <Route path="cad/editor/:id" element={<AdminOnly><CadEditor /></AdminOnly>} />
            <Route path="measure" element={<AdminOnly><SatelliteMeasure /></AdminOnly>} />
            <Route path="virtual-bid" element={<AdminOnly><VirtualBid /></AdminOnly>} />
            <Route path="card" element={<AdminOnly><DigitalCardList /></AdminOnly>} />
            <Route path="weather" element={<AdminOnly><WeatherHub /></AdminOnly>} />

            {/* Shared placeholders (later phases) */}
            <Route
              path="schedule-info"
              element={
                <Placeholder
                  title="Schedule"
                  phase={5}
                  note="For technicians: schedule visible read-only; clock in required to open jobs — full behavior arrives in Phase 5."
                />
              }
            />
            <Route path="tools" element={<OpsHub />} />
            <Route path="more" element={<OpsHub />} />
            <Route path="leads/new" element={<Placeholder title="New Lead" phase={4} />} />

            {/* Customer portal (Phase 4) */}
            <Route path="portal/home" element={<PortalHome />} />
            <Route path="portal/services" element={<PortalServices />} />
            <Route path="portal/services/:id" element={<PortalServiceDetail />} />
            <Route path="portal/service-reports" element={<PortalServiceReports />} />
            <Route path="portal/service-reports/:id" element={<PortalServiceReportDetail />} />
            {/* Phase 56.16-followup — alias for the /customer/... spec.
                Primary path stays under /portal/* to match the rest of the
                customer portal namespace. */}
            <Route path="customer/service-reports" element={<Navigate to="/portal/service-reports" replace />} />
            <Route path="customer/service-reports/:id" element={<CustomerServiceReportRedirect />} />
            <Route path="portal/invoices" element={<PortalInvoices />} />
            <Route path="portal/invoices/:id" element={<PortalInvoiceDetail />} />
            <Route path="portal/estimates" element={<PortalEstimates />} />
            <Route path="portal/estimates/:id" element={<PortalEstimateDetail />} />
            <Route path="portal/payments" element={<PortalPayments />} />
            <Route path="portal/payment-method" element={<PortalPaymentMethod />} />
            <Route path="portal/documents" element={<PortalDocuments />} />
            <Route path="portal/messages" element={<PortalMessages />} />
            <Route path="portal/chats" element={<PortalChatsPage />} />
            <Route path="portal/book" element={<PortalBook />} />
            <Route path="portal/photos" element={<PortalPhotos />} />
            <Route path="portal/videos" element={<PortalVideos />} />
            <Route path="admin/comms/templates"       element={<AdminOnly><CommsTemplatesLibrary /></AdminOnly>} />
            <Route path="admin/comms/email"           element={<AdminOnly><CommsTemplatesLibrary /></AdminOnly>} />
            <Route path="admin/comms/email/new"       element={<AdminOnly><CommsEmailBuilder /></AdminOnly>} />
            <Route path="admin/comms/email/:code"     element={<AdminOnly><CommsEmailBuilder /></AdminOnly>} />
            <Route path="admin/comms/sms"             element={<AdminOnly><CommsTemplatesLibrary /></AdminOnly>} />
            <Route path="admin/comms/sms/new"         element={<AdminOnly><CommsSmsBuilder /></AdminOnly>} />
            <Route path="admin/comms/sms/:code"       element={<AdminOnly><CommsSmsBuilder /></AdminOnly>} />
            <Route path="admin/comms/automations"     element={<AdminOnly><CommsAutomationsPage /></AdminOnly>} />
            <Route path="admin/comms/sends"           element={<AdminOnly><CommsSendsHistoryPage /></AdminOnly>} />
            {/* Reviews Subsystem · Phase 2 — admin surface */}
            <Route path="admin/reviews"               element={<AdminOnly><ReviewsDashboard /></AdminOnly>} />
            <Route path="admin/reviews/requests"      element={<AdminOnly><ReviewsRequestsPage /></AdminOnly>} />
            <Route path="admin/reviews/platforms"     element={<AdminOnly><ReviewsPlatformsPage /></AdminOnly>} />
            <Route path="admin/reviews/widget"        element={<AdminOnly><ReviewsWidgetPage /></AdminOnly>}/>
            {/* QuoteIQ Q1-UI · Feb 2026 */}
            <Route path="admin/ai-credits" element={<AdminOnly><AICreditsPage /></AdminOnly>} />
            <Route path="admin/chemicals" element={<AdminOnly><ChemicalsPage /></AdminOnly>} />
            <Route path="deals" element={<AdminOnly><DealsKanbanPage /></AdminOnly>} />
            <Route path="ai-estimator" element={<AdminOnly><AIEstimatorPage /></AdminOnly>} />
            <Route path="customers/:id/chemistry-history" element={<AdminOnly><CustomerChemistryHistory /></AdminOnly>} />
            <Route path="portal/profile" element={<PortalProfile />} />
            <Route path="portal/request-service" element={<PortalRequestService />} />
            <Route path="portal/reviews" element={<PortalReviews />} />
            <Route path="portal/payment-complete" element={<PortalPaymentComplete />} />
            <Route path="onboarding/mine" element={<MyOnboarding />} />
            <Route path="admin/portal-inbox" element={<AdminOnly><PortalChatsPage /></AdminOnly>} />
            <Route path="admin/appointments" element={<AdminOnly><AppointmentsQueue /></AdminOnly>} />
            <Route path="admin/assets" element={<AdminOnly><AdminAssets /></AdminOnly>} />
            <Route path="admin/onboarding/templates" element={<AdminOnly><OnboardingTemplates /></AdminOnly>} />
            <Route path="admin/onboarding/queue" element={<AdminOnly><OnboardingQueue /></AdminOnly>} />
            <Route path="admin/referrals/settings" element={<AdminOnly><ReferralTiers /></AdminOnly>} />
            <Route path="admin/referrals/analytics" element={<AdminOnly><ReferralAnalyticsV2 /></AdminOnly>} />
            <Route path="admin/seo/audits" element={<AdminOnly><SeoAudits /></AdminOnly>} />
            <Route path="admin/seo/audits/:id" element={<AdminOnly><SeoAuditDetail /></AdminOnly>} />
            <Route path="admin/seo/content-scorer" element={<AdminOnly><ContentScorer /></AdminOnly>} />
            <Route path="admin/seo/rank-heatmap" element={<AdminOnly><RankHeatmap /></AdminOnly>} />
            <Route path="admin/seo/topical-map" element={<AdminOnly><TopicalMap /></AdminOnly>} />
            <Route path="admin/seo/llm-visibility" element={<AdminOnly><LlmVisibility /></AdminOnly>} />
            <Route path="admin/seo/atlas" element={<AdminOnly><AtlasAgent /></AdminOnly>} />
            <Route path="admin/seo/audits/:id/otto" element={<AdminOnly><OttoAutoFix /></AdminOnly>} />
            <Route path="admin/seo/studio" element={<AdminOnly><WebsiteStudio /></AdminOnly>} />
            <Route path="admin/seo/studio/:id" element={<AdminOnly><WebsiteStudioEditor /></AdminOnly>} />
            <Route path="admin/seo/reports" element={<AdminOnly><WhiteLabelReports /></AdminOnly>} />
            <Route path="admin/seo/reports/:id" element={<AdminOnly><WhiteLabelReportDetail /></AdminOnly>} />
            <Route path="admin/estimator" element={<AdminOnly><EstimatorList /></AdminOnly>} />
            <Route path="admin/estimator/new" element={<AdminOnly><EstimatorNew /></AdminOnly>} />
            <Route path="admin/estimator/rates" element={<AdminOnly><EstimatorRates /></AdminOnly>} />
            <Route path="admin/estimator/:id" element={<AdminOnly><EstimatorDetail /></AdminOnly>} />
            <Route path="admin/dunning/settings" element={<AdminOnly><DunningSettings /></AdminOnly>} />
            <Route path="admin/dunning/queue" element={<AdminOnly><DunningQueue /></AdminOnly>} />
            <Route path="admin/dunning/analytics" element={<AdminOnly><DunningAnalytics /></AdminOnly>} />
            {/* Phase 23 — Inventory Tracker */}
            <Route path="admin/inventory" element={<AdminOnly><InventoryList /></AdminOnly>} />
            <Route path="admin/inventory/purchase-orders" element={<AdminOnly><InventoryPOs /></AdminOnly>} />
            <Route path="admin/inventory/alerts" element={<AdminOnly><InventoryAlerts /></AdminOnly>} />
            <Route path="admin/inventory/analytics" element={<AdminOnly><InventoryAnalytics /></AdminOnly>} />
            <Route path="admin/inventory/:id" element={<AdminOnly><InventoryDetail /></AdminOnly>} />
            {/* Phase 24 — Check Writer */}
            <Route path="admin/checks" element={<AdminOnly><CheckRegister /></AdminOnly>} />
            <Route path="admin/checks/new" element={<AdminOnly><CheckNew /></AdminOnly>} />
            <Route path="admin/checks/bank-accounts" element={<AdminOnly><CheckBanks /></AdminOnly>} />
            <Route path="admin/checks/payees" element={<AdminOnly><CheckPayees /></AdminOnly>} />
            <Route path="admin/checks/analytics" element={<AdminOnly><CheckAnalytics /></AdminOnly>} />
            <Route path="admin/checks/:id" element={<AdminOnly><CheckDetail /></AdminOnly>} />
            {/* Phase 25 — Property Lookup (tech + admin) */}
            <Route path="tech/property-lookup" element={<PropertyLookupPage />} />
            <Route path="property-lookup" element={<PropertyLookupPage />} />
            {/* Phase 26 Wave A — Dispatch + Batch Checks */}
            <Route path="admin/dispatch" element={<AdminOnly><DispatchBoard /></AdminOnly>} />
            <Route path="admin/dispatch/weather" element={<AdminOnly><WeatherReschedule /></AdminOnly>} />
            <Route path="admin/checks/batch/new" element={<AdminOnly><CheckBatchNew /></AdminOnly>} />
            <Route path="admin/checks/payroll" element={<AdminOnly><CheckPayrollImport /></AdminOnly>} />
            {/* Phase 27 Wave B */}
            <Route path="admin/customer-success/churn" element={<AdminOnly><ChurnDashboard /></AdminOnly>} />
            <Route path="admin/seo/content-refresh" element={<AdminOnly><ContentRefresh /></AdminOnly>} />
            {/* Phase 28.1 — Warranty Portal */}
            <Route path="admin/warranties/plans" element={<AdminOnly><WarrantyPlans /></AdminOnly>} />
            <Route path="admin/warranties/contracts" element={<AdminOnly><WarrantyContracts /></AdminOnly>} />
            <Route path="admin/warranties/claims" element={<AdminOnly><WarrantyClaims /></AdminOnly>} />
            <Route path="portal/warranties" element={<PortalWarranties />} />
          </Route>

          {/* Anything unmatched → home */}
          <Route path="*" element={<NotFound />} />
        </Routes>
        {/* Global Sonner host — MUST be mounted here or every `toast.*()`
             call across the app silently no-ops. Positioned top-right with
             a data-testid on the wrapper so E2E can locate it in the DOM. */}
        <div data-testid="app-toaster-root">
          <SonnerToaster position="top-right" richColors closeButton />
        </div>
      </BrowserRouter>
      </ConfirmProvider>
      </RealtimeProvider>
      </PermissionsBridge>
    </AuthProvider>
  );
}

/** Bridges user from AuthProvider into PermissionsProvider (needs to be a child of AuthProvider). */
function PermissionsBridge({ children }) {
  const { user } = useAuth();
  return <PermissionsProvider user={user}>{children}</PermissionsProvider>;
}
