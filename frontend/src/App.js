import React from "react";
import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth";
import { ConfirmProvider } from "@/components/ui/confirm-dialog";
import { Toaster as SonnerToaster } from "@/components/ui/sonner";
import ScrollToTop from "@/components/ScrollToTop";
import useTelephonyLiveEvents from "@/hooks/useTelephonyLiveEvents";
import AppLayout from "@/layouts/AppLayout";
import Login from "@/pages/Login";
// Phase 34 · Feb 2026 — self-serve password reset landing (stub UI).
// Backend endpoint tracked in /app/memory/todo_password_reset.md.
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
import PortalReviewSubmit from "@/pages/portal/PortalReviewSubmit";
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
import ServiceLogPage from "@/pages/workstream/ServiceLogPage";
import CFODashboard from "@/pages/cfo/CFODashboard";
import JobNew from "@/pages/jobs/JobNew";
import JobDetail from "@/pages/jobs/JobDetail";
import JobsList from "@/pages/jobs/JobsList";
import AdminUsersList from "@/pages/admin/AdminUsersList";
import AdminTagsList from "@/pages/admin/AdminTagsList";
import AdminCommsSuppressionLog from "@/pages/admin/AdminCommsSuppressionLog";
import AdminServiceReportsList from "@/pages/admin/AdminServiceReportsList";
import AdminTimeEntriesList from "@/pages/admin/AdminTimeEntriesList";
import ReflowHistoryPage from "@/pages/admin/ReflowHistoryPage";
// Task RR/SS Phase 2 · Feb 2026 — AI Employee scope toggle + tool audit.
import AiPersonasScopePage from "@/pages/admin/AiPersonasScopePage";
import AiToolAuditPage from "@/pages/admin/AiToolAuditPage";
import PortalPaymentReturn from "@/pages/portal/PortalPaymentReturn";
// Feb-2026 P0 fix (Bug 2 · Item A) — legacy ``PortalPaymentMethods``
// (plural) removed. The one true portal card management surface is
// ``<PortalPaymentMethod>`` (singular) from ``PortalPages.jsx``, on
// route ``/portal/payment-method``.
import QuickBooksIntegrationPage from "@/pages/admin/integrations/QuickBooksIntegrationPage";
import {
  BulkChargeRunsList as _P14bRunsList,
  BulkChargeRunDetail as _P14bRunDetail,
} from "@/pages/admin/BulkChargeRunsPage";
import QuotesList from "@/pages/quotes/QuotesList";
import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";
import QuoteInvoiceDetail from "@/pages/quotes/QuoteInvoiceDetail";
import InvoicesList from "@/pages/invoices/InvoicesList";
import { MasterInvoicesList, MasterInvoiceNew, MasterInvoiceDetail } from "@/pages/invoices/MasterInvoice";
import PaymentHandlesSettings from "@/pages/settings/PaymentHandles";
import LateFeesSettings from "@/pages/settings/LateFees";
import IncomeCategoriesPage from "@/pages/settings/IncomeCategoriesPage";
import PricebookSuppliersAdmin from "@/pages/settings/PricebookSuppliersAdmin";
import PricebookCostComparison from "@/pages/reports/PricebookCostComparison";
import SupplierSpendReport from "@/pages/reports/SupplierSpendReport";
import ServiceCategoriesPage from "@/pages/settings/ServiceCategoriesPage";
import JobOutcomeReasonsPage from "@/pages/settings/JobOutcomeReasonsPage";
// Feb-2026 · P29b — Muted Reasons admin (super_admin / admin / manager).
import MutedReasonsPage from "@/pages/settings/MutedReasonsPage";
// Feb-2026 · P34 — Automation quiet-hours admin (super_admin / admin / manager).
import QuietHoursPage from "@/pages/settings/QuietHoursPage";
// Feb-2026 · P36 — Customer Tags settings manager (super_admin / admin / manager).
import CustomerTagsSettingsPage from "@/pages/settings/CustomerTagsSettingsPage";
// Feb-2026 · P37b — GPS auto-start settings (super_admin / admin / manager).
import GpsAutoStartPage from "@/pages/settings/GpsAutoStartPage";
import BillingSettings from "@/pages/settings/BillingSettings";
import SupplierSettings from "@/pages/settings/SupplierSettings";
import SupplierSyncAnalytics from "@/pages/reports/SupplierSyncAnalytics";
// Phase 55-a · Aug-2026 — Homeworks (Copilot CRM) importer scaffold.
import HomeworksImport from "@/pages/settings/HomeworksImport";
import AutoVisitEmailSettings from "@/pages/settings/AutoVisitEmailSettings";
import PortalPhotos from "@/pages/portal/PortalPhotos";
import PortalReviews from "@/pages/portal/PortalReviews";
import AdminReviewsPage from "@/pages/admin/AdminReviewsPage";
import MarketingTemplatesLibraryPage from "@/pages/marketing/MarketingTemplatesLibraryPage";
// Phase 9B · Feb 2026 — Rebuilt Marketing Templates admin (TipTap +
// merge-tag palette + media picker + unresolved-token red-chip banner).
import MarketingTemplatesListPage, {
  MarketingTemplateDetailPage,
} from "@/pages/marketing/MarketingTemplatesAdmin";
import MarketingMediaAdminPage from "@/pages/marketing/MarketingMediaAdmin";
// Feb-2026 · Phase B · Marketing Content Studio (Supercool image gen).
import ContentStudioPage from "@/pages/marketing/ContentStudioPage";
// Phase 10 · Feb 2026 — Referrals + promo codes admin + portal.
import PortalReferralsPage from "@/pages/portal/PortalReferralsPage";
import AdminPromoCodesPage from "@/pages/marketing/AdminPromoCodesPage";
import AdminReferralsPage from "@/pages/marketing/AdminReferralsPage";
import CustomerCreditsPage from "@/pages/customers/CustomerCreditsPage";
import MarketingSegmentsPage from "@/pages/marketing/MarketingSegmentsPage";
import MarketingSequencesPage from "@/pages/marketing/MarketingSequencesPage";
import MarketingReviewRequestsPage from "@/pages/marketing/MarketingReviewRequestsPage";
import MarketingAnalyticsPage from "@/pages/marketing/MarketingAnalyticsPage";
import MarketingSuppressionsPage from "@/pages/marketing/MarketingSuppressionsPage";
import BroadcastsPage from "@/pages/marketing/BroadcastsPage";
import CommunicationsLogPage from "@/pages/marketing/CommunicationsLogPage";
import PortalPreferences from "@/pages/portal/PortalPreferences";
import PrivacyPolicy from "@/pages/PrivacyPolicy";
import TermsOfService from "@/pages/TermsOfService";
import AiTransparency from "@/pages/AiTransparency";
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
// Feb-2026 · Phase 20 P3 — Website SEO analyzer.
import WebsiteSeoPage from "@/pages/settings/WebsiteSeoPage";
// Feb-2026 · Phase 20 P4 — GBP checklist.
import LocalSeoPage from "@/pages/settings/LocalSeoPage";
// Feb-2026 · Phase 20 P1 — GBP post drafter.
import GbpPostsPage from "@/pages/marketing/GbpPostsPage";
// Feb-2026 · Phase 20 P5 — Public NFC review card.
import NfcReviewCardPage from "@/pages/public/NfcReviewCardPage";
// Feb-2026 · Item 4 — AI Brain + Copilot admin pages.
import AIBrainPage from "@/pages/settings/AIBrainPage";
import CopilotPage from "@/pages/admin/CopilotPage";
import LuminoBackfillPage from "@/pages/admin/LuminoBackfillPage";
import ProfitReportPage from "@/pages/admin/ProfitReportPage";
import GpsSettingsPage from "@/pages/admin/GpsSettingsPage";
// Feb-2026 · Item 6 — Business Card admin editor.
import BusinessCardSettingsPage from "@/pages/settings/BusinessCardSettings";
import MyProfilePage from "@/pages/account/MyProfilePage";
import GoogleReviewSettings from "@/pages/settings/GoogleReviewSettings";
import VanitySlugsPage from "@/pages/settings/VanitySlugsPage";
import OrphanUsersPage from "@/pages/settings/OrphanUsersPage";
import CitationBuilderPage from "@/pages/settings/CitationBuilderPage";
import RankTrackerPage from "@/pages/settings/RankTrackerPage";
import DealsKanbanPage from "@/pages/deals/DealsKanbanPage";
// QuoteIQ Q2-UI · Feb 2026
import AIEstimatorPage from "@/pages/estimates/AIEstimatorPage";
// Phase 34 · Feb-2026 · Task H — the customer-facing Book Service
// surface has been retired. The route ``/portal/book`` now redirects
// to ``/portal/request-service`` (see below). The former
// ``PortalBook`` page component was deleted in Phase B1 (Feb 2026)
// after confirming no route or import referenced it.
import PortalChatsPage from "@/pages/portal/PortalChatsPage";
import PortalPhotosPage from "@/pages/portal/PortalPhotosPage";
import PortalVideosPage from "@/pages/portal/PortalVideosPage";
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
// Phase 18 · Feb-2026 — Chemical Cost Report (Admin+ only).
import ChemicalCostReport from "@/pages/inventory/ChemicalCostReport";
import CheckRegister, { CheckNew, CheckDetail, CheckBanks, CheckPayees, CheckAnalytics } from "@/pages/checks/ChecksPages";
import PropertyLookupPage from "@/pages/property-lookup/PropertyLookupPage";
import DispatchBoard, { WeatherReschedule } from "@/pages/dispatch/DispatchPages";
// Phase 17 · Feb 2026 — Google Maps + Directions redesigned dispatch board.
import DispatchBoardPage from "@/pages/dispatch/DispatchBoardPage";
// Feb-2026 · P1 diagnostic — wrap DispatchBoardPage in an ErrorBoundary
// so mobile crashes surface a friendly panel instead of a blank screen,
// and get reported to /api/client-errors for admin review.
import DispatchErrorBoundary from "@/components/errors/DispatchErrorBoundary";
import AdminDiagnosticsErrorsPage from "@/pages/admin/AdminDiagnosticsErrorsPage";
import DriverActivityPage from "@/pages/admin/DriverActivityPage";
import ModerationCheckinsPage from "@/pages/admin/ModerationCheckinsPage";
import SeoAuditorPage from "@/pages/admin/SeoAuditorPage";
import AEOPage from "@/pages/admin/AEOPage";
import WeeklyDigestPage from "@/pages/admin/WeeklyDigestPage";
import AEODigestPage from "@/pages/admin/AEODigestPage";
import ProspectsKanbanPage from "@/pages/admin/outreach/ProspectsKanbanPage";
import OutreachTemplatesPage from "@/pages/admin/outreach/TemplatesPage";
import KeywordIdeatorPage from "@/pages/admin/KeywordIdeatorPage";
import GpsUsersPage from "@/pages/admin/GpsUsersPage";
// Phase G5a · Feb-2026 — Geofences + crossings inbox.
import GeofencesPage from "@/pages/admin/GeofencesPage";
import CrossingsInbox from "@/pages/admin/CrossingsInbox";
// Phase G5b · Feb-2026 — Stop → Job attribution report.
import TimeOnSitePage from "@/pages/admin/TimeOnSitePage";
// Phase G5d · Feb-2026 — Driver Scorecard / Leaderboard.
import DriverScorecardPage from "@/pages/admin/DriverScorecardPage";
import WidgetEmbedPage from "@/pages/admin/WidgetEmbedPage";
// MR3 · Feb-2026 — Public widget analytics.
import WidgetAnalyticsPage from "@/pages/admin/WidgetAnalyticsPage";
// Phase 2 · Feb-2026 (REWORKED) — Admin-only shared Route Replay viewer.
import AdminSharedReplayPage from "@/pages/admin/AdminSharedReplayPage";
import CheckBatchNew, { CheckPayrollImport } from "@/pages/checks/CheckBatchPages";
import ChurnDashboard, { ContentRefresh } from "@/pages/customer-success/ChurnPages";
import WarrantyPlans, { WarrantyContracts, WarrantyClaims, PortalWarranties } from "@/pages/warranties/WarrantyPages";
import TermsSettings from "@/pages/settings/Terms";
import { LegalDocsList, LegalDocEditor } from "@/pages/settings/LegalDocs";
// Feb-2026 · Slice 2B — Multi-ToS admin editor (Pool + Landscaping).
import TosAdminEditor from "@/pages/settings/TosAdminEditor";
import { IntegrationsHub, MapSettings } from "@/pages/settings/IntegrationsPages";
// Phase 26 · Feb 2026 · Supercool MCP OAuth integration (super_admin only).
import SupercoolIntegrationPage from "@/pages/settings/integrations/SupercoolIntegrationPage";
// Phase 0 POC · Feb-2026 — Homeworks (home.works MCP) BYO-creds admin.
// Super_admin only. Separate surface from the env-var-driven
// /settings/integrations Homeworks card.
import HomeworksIntegrationPage from "@/pages/admin/integrations/HomeworksIntegrationPage";
import HomeworksOAuthCallback from "@/pages/admin/integrations/HomeworksOAuthCallback";
// Feb-2026 · Item 3 — Deletions audit page (super_admin only).
import DeletionsAuditPage from "@/pages/admin/audit/DeletionsAuditPage";
// Feb-2026 · Admin migrations dashboard (super_admin only) — driver
// for one-off backfills (P19 empty-lead enrichment initially).
import AdminMigrationsPage from "@/pages/admin/AdminMigrationsPage";
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
import PublicInvoicePay from "@/pages/public/PublicInvoicePay";
// Phase 22 · Feb 2026 — Public Service Images portal (no auth).
import ServiceImagesPortalPage from "@/pages/public/ServiceImagesPortalPage";
// Phase 47c (Feb 2026) — /portal/add-card RESTORED as a direct-Stripe
// magic-link flow (Elements + SetupIntent). Un-does the Phase LZ4
// retirement now that the user has directed every payment surface to
// route through Stripe directly (no Lumino / Zapier).
import AddCardPage from "@/pages/public/AddCardPage";
import TeamChatPage from "@/pages/chat/TeamChatPage";
import Walkie from "@/pages/walkie/Walkie";
import {
  SequencesList, SequenceNew, SequenceDetail,
} from "@/pages/marketing/SequencePages";
import {
  SeoHub, ArticlesList, ArticleEditor, KeywordSuggest, SeoAudit, RankGrid,
  WordPressSettings, GbpHub,
} from "@/pages/seo/SeoPages";
import { AiEmployeesList, AiEmployeeDetail, TasksPage,
  AccessSettings, AccessHistory, RingCentralSettings, CallLogsPage,
} from "@/pages/aiops/AiOpsPages";
// Phase S2 · Feb-2026 — Soshie Hub (Brand Brain + Autopilot + Review Queue).
import SoshieHub from "@/pages/soshie/SoshieHub";
// Phase 11 · Feb 2026 — Equipment Service Trackers (Filter & Salt Cell).
import {
  FilterTrackerListPage, FilterTrackerManagePage,
  SaltCellTrackerListPage, SaltCellTrackerManagePage,
} from "@/pages/tracking/EquipmentTrackerPages";
import NotificationsPage from "@/pages/notifications/NotificationsPage";
import NotificationPrefs from "@/pages/settings/NotificationPrefs";
// StripeReconciliation page removed in Phase LZ4 (Feb 2026);
// Stripe SDK is retired. Import + route deleted.
import {
  D2dDashboard, D2dMap, D2dKnocks, D2dOpenLeads, D2dSoldLeads, D2dReport, D2dLeaderboard,
} from "@/pages/d2d/D2dPages";
import { DispatchMap, ScheduleMap } from "@/pages/ops/MapPages";
import NotFound from "@/pages/NotFound";
import { CheckinsList } from "@/pages/misc/GapClosures";
import { CommunicationThread, TechnicianProfile, FormsList, FormEditor, PublicForm } from "@/pages/phase14/Phase14Pages";
import { PermissionsProvider } from "@/hooks/usePermissions";
import {
  LandscapeAI, CadList, CadEditor, SatelliteMeasure, VirtualBid,
  DigitalCardList, PublicCard, WeatherHub,
} from "@/pages/aitools/AiToolsPages";
import { EstimatesList, EstimatorSettings, EstimatorTemplates, EstimatorEditor } from "@/pages/estimator/Estimator";
import OpsHub from "@/pages/ops/OpsHub";
// Feb-2026 · Job Timers Phase 1 + Chemical Cost Report — fresh pages.
import JobTimersPage from "@/pages/timers/JobTimersPage";
import ChemicalCostReportPage from "@/pages/reports/ChemicalCostReportPage";
import RepairCalculatorPage from "@/pages/ops/RepairCalculatorPage";
import ReportsHub from "@/pages/reports/ReportsHub";
import BusinessSummary from "@/pages/reports/BusinessSummary";
import Forecast from "@/pages/reports/Forecast";
import CustomerRetentionReport from "@/pages/reports/CustomerRetentionReport";
import GpsAutoStartAudit from "@/pages/reports/GpsAutoStartAudit";
import IncomeByCategory from "@/pages/reports/IncomeByCategoryPage";
import UncategorizedItemsReport from "@/pages/reports/UncategorizedItemsReport";
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
import LeadDetail from "@/pages/leads/LeadDetail";
import PublicLeadIntake from "@/pages/public/PublicLeadIntake";
import PublicLeadRequestPage from "@/pages/public/PublicLeadRequest";
import WidgetDemoPage from "@/pages/widget/WidgetDemoPage";
import MarketingFormsPage from "@/pages/marketing/MarketingFormsPage";
import LeadsDashboardPage from "@/pages/leads/LeadsDashboardPage";
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
import TelephonyPage from "@/pages/settings/TelephonyPage";
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
import TimeOffPage from "@/pages/TimeOffPage";
import AdminTimeOffPage from "@/pages/AdminTimeOffPage";
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

// Phase 34 · Fix 2 · Feb 2026 — /estimates/:id → /estimator/:id
// alias so the new user-friendly URL preserves the row id.
function EstimateAliasRedirect() {
  const { id } = useParams();
  return <Navigate to={`/estimator/${id}`} replace />;
}

function AdminOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user || (user.role !== "admin" && user.role !== "super_admin")) {
    return <Navigate to="/" replace />;
  }
  return children;
}


// Feb 2026 · Task A hotfix (route-guard companion) — generic
// AdminOrManager wrapper. Matches the sidebar/top-bar filter's
// ``hard_rule: "manager_only"`` semantics (super_admin, admin,
// manager). Reused across every /admin route surfaced by a
// manager_only nav entry — recurring-jobs, driver-activity,
// checkins moderation, seo/auditor + seo/keywords, gps-users,
// widget-embed. Techs and portal customers still redirect to /.
// The bespoke ``AdminOrManagerForProfitReport / Workstream /
// Weather / Suppliers`` wrappers above stay put — they were
// introduced before this generic existed and swapping them is out
// of scope for this hotfix.
function AdminOrManager({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin" || role === "manager";
  if (!user || !allowed) {
    return <Navigate to="/" replace />;
  }
  return children;
}


// Phase 53c-fix · Feb-2026 — profit-report is the ONLY /admin route
// managers may reach (they render the EBIT panel read-only, and get
// the existing profit-report page in view-only mode). All other
// /admin/* routes stay ``AdminOnly``. This is a targeted rule.
function AdminOrManagerForProfitReport({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin" || role === "manager";
  if (!user || !allowed) {
    return <Navigate to="/" replace />;
  }
  return children;
}


// Feb-2026 · Workstream bulk-actions parity — managers now get the
// same Workstream affordances (checkbox, bulk-delete, inline edit)
// as admins. Mirrors the ``AdminOrManagerForProfitReport`` wrapper
// so the gate stays consistent across the manager-eligible surfaces.
function AdminOrManagerForWorkstream({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin" || role === "manager";
  if (!user || !allowed) {
    return <Navigate to="/" replace />;
  }
  return children;
}


// Phase 41.5c-fixup · Feb 2026 — /weather page. Field managers make
// scheduling decisions off the risk grid + reschedule-recommendations
// (both endpoints back /weather); the existing ``<AdminOnly>`` here
// was inherited boilerplate. Targeted widen to admin/super_admin/manager
// mirrors the pattern used for AdminOrManagerForProfitReport and
// AdminOrManagerForSuppliers.
function AdminOrManagerForWeather({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin" || role === "manager";
  if (!user || !allowed) {
    return <Navigate to="/" replace />;
  }
  return children;
}


// Phase 54b · Feb-2026 — wholesale supplier settings. Admin/super_admin
// edit; manager renders the page read-only (form disabled, action
// buttons hidden — enforced INSIDE ``SupplierSettings.jsx``);
// technician + customer roles are redirected out entirely.
function AdminOrManagerForSuppliers({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin" || role === "manager";
  if (!user || !allowed) {
    return <Navigate to="/" replace />;
  }
  return children;
}


// Feb-2026 · P29b — Muted Reasons manager. Admin/super_admin/manager
// may CRUD the tenant's picker list. Techs + customers redirect out.
// Mirrors AdminOrManagerForSuppliers but named for the muted-reasons
// surface so future changes stay scoped.
function AdminOrManagerForMutedReasons({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  const role = user?.role || "";
  const allowed = role === "admin" || role === "super_admin" || role === "manager";
  if (!user || !allowed) {
    return <Navigate to="/" replace />;
  }
  return children;
}


// Phase 21 · Feb 2026 · Vanity slug editor — super_admin gated.
// Anyone else lands on `/` (unauthorized surface for this app).
function SuperAdminOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user || user.role !== "super_admin") {
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
        <TelephonyLiveEventsBridge />
        <Routes>
          <Route path="/login" element={<Login />} />
          {/* Feb-2026 · P11b — Privacy Policy placeholder (App Store item 4). */}
          <Route path="/privacy-policy" element={<PrivacyPolicy />} />
          {/* Feb-2026 · P21b — Public Terms of Service (App Store item 4). */}
          <Route path="/terms-of-service" element={<TermsOfService />} />
          {/* Feb-2026 · P23 — Public AI Transparency page. */}
          <Route path="/ai-transparency" element={<AiTransparency />} />
          {/* Feb 2026 · Hotfix #2 (Option C) — customer-facing login
              surface. Renders the same Login page but with the
              demo-tiles block permanently disabled (no gate, no
              toggle, no render). Backed by the same auth endpoint. */}
          <Route path="/portal/login" element={<Login variant="customer" />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          {/* Phase 34 · Task T · Feb 2026 — Portal review submit page.
              Token-authed (no bearer). Consumes the existing gating
              endpoint at /api/public/r/{token}/rating. */}
          <Route path="/portal/review/submit" element={<PortalReviewSubmit />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/tenant-picker" element={<TenantPicker />} />
          <Route path="/public/card/:slug" element={<PublicCard />} />
          {/* Feb-2026 · Phase 20 P5 — Public NFC review card page. */}
          <Route path="/nfc/:slug" element={<NfcReviewCardPage />} />
          <Route path="/widget-demo" element={<WidgetDemoPage />} />
          {/* Phase 2 · Feb-2026 (REWORKED) — Route Replay share viewer.
              Admin/Super Admin only per policy update. */}
          <Route path="/replay/:shareId" element={<AdminOnly><AdminSharedReplayPage /></AdminOnly>} />
          <Route path="/f/:slug" element={<PublicForm />} />
          {/* Phase 15A public magic-link routes (no auth) */}
          <Route path="/csat/:token" element={<PublicCsat />} />
          <Route path="/portal/sign/:token" element={<PortalSignPage />} />
          {/* Phase 15B slot-in — Lead Request public form (no auth) */}
          <Route path="/lead-request/:token" element={<PublicLeadRequestPage />} />
          {/* Phase 8 · Feb 2026 — public leads intake (Turnstile-gated) */}
          <Route path="/public/leads" element={<PublicLeadIntake />} />

          {/* Reviews Subsystem · Phase 2 — public flows (no auth) */}
          <Route path="/reviews/r/:token" element={<PublicReviewLanding />} />
          <Route path="/reviews/:tenant_slug" element={<PublicReviewsWidgetPage />} />

          {/* Marketing M6 · Feb 2026 — magic-link review requests (no auth).
              PortalReviews reads ?token=… and hits the public verify +
              via-token endpoints, so this needs to render outside the
              ProtectedShell. */}
          <Route path="/r/review" element={<PortalReviews />} />

          {/* Marketing Slice F · Feb 2026 — magic-link unsubscribe (no auth). */}
          <Route path="/r/preferences" element={<PortalPreferences />} />

          {/* Phase F1 · Feb 2026 — dev smoke-test surface for the
              shared file-upload components. Only mounted in preview
              (env-gated); production build renders nothing here. */}
          {String(process.env.REACT_APP_PUBLIC_ENV || "").toLowerCase() === "preview" && (
            <Route
              path="/dev/file-upload"
              element={
                <React.Suspense fallback={<div style={{ padding: 24 }}>Loading…</div>}>
                  {React.createElement(React.lazy(() => import("@/pages/dev/FileUploadDemo")))}
                </React.Suspense>
              }
            />
          )}

          {/* QuoteIQ Q4 · public InstaQuote portal — no auth. */}
          <Route path="/quote/:slug" element={<PublicInstaQuotePage />} />

          {/* QuoteIQ Q5 · public InstaSchedule portal — no auth. */}
          <Route path="/book/:slug" element={<PublicInstaSchedulePage />} />

          {/* Phase 4B · Feb 2026 — public magic-link invoice payer (no auth). */}
          <Route path="/pay/invoice/:id" element={<PublicInvoicePay />} />

          {/* Phase 22 · Feb 2026 — public service-record images portal (no auth). */}
          <Route path="/portal/service/:uuid" element={<ServiceImagesPortalPage />} />

          {/* Phase 12 · Feb 2026 — public magic-link "Add card" page (no auth). */}
          {/* Phase 47c · Feb 2026 — RESTORED after the Phase LZ4 retirement.
              Direct Stripe SetupIntent flow (see /pages/public/AddCardPage). */}
          <Route path="/portal/add-card" element={<AddCardPage />} />

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
            {/* Phase 34 · Task LL Phase 2 UI wrap-up · Feb 2026 — admin-only
                jobs list surfacing /jobs/bulk-delete + bulk-update. */}
            <Route path="admin/jobs" element={<AdminOnly><JobsList /></AdminOnly>} />
            {/* Task OO · Feb 2026 — P1 bulk-select admin surfaces. */}
            <Route path="admin/users" element={<AdminOnly><AdminUsersList /></AdminOnly>} />
            <Route path="admin/tags" element={<AdminOnly><AdminTagsList /></AdminOnly>} />
            {/* Queue Item 4 · Feb-2026 — comms whitelist Suppression
                Log viewer, super_admin-only per P0 safety directive. */}
            <Route path="admin/comms/suppression-log" element={<SuperAdminOnly><AdminCommsSuppressionLog /></SuperAdminOnly>} />
            <Route path="admin/service-reports" element={<AdminOnly><AdminServiceReportsList /></AdminOnly>} />
            <Route path="admin/time-entries" element={<AdminOnly><AdminTimeEntriesList /></AdminOnly>} />
            <Route path="admin/reflow-history" element={<AdminOnly><ReflowHistoryPage /></AdminOnly>} />
            {/* Task RR/SS Phase 2 · Feb 2026 */}
            <Route path="admin/ai-personas-scope" element={<AdminOnly><AiPersonasScopePage /></AdminOnly>} />
            <Route path="admin/ai-tool-audit" element={<AdminOnly><AiToolAuditPage /></AdminOnly>} />
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

            <Route path="estimator" element={<NoTech><EstimatesList /></NoTech>} />
            {/* Phase 34 · Fix 2 · Feb 2026 — /estimates alias route.
                Ships the same EstimatesList (which shipped the Task BB
                bulk-select UI). The nav config already points at
                /estimator; the alias exists so tester bookmarks + the
                URL a customer might guess both resolve without a 404. */}
            <Route path="estimates" element={<NoTech><EstimatesList /></NoTech>} />
            <Route path="estimates/new" element={<Navigate to="/estimator/new" replace />} />
            <Route path="estimates/:id" element={<EstimateAliasRedirect />} />
            <Route path="estimator/settings" element={<NoTech><EstimatorSettings /></NoTech>} />
            <Route path="estimator/templates" element={<NoTech><EstimatorTemplates /></NoTech>} />
            <Route path="estimator/new" element={<NoTech><EstimatorEditor /></NoTech>} />
            <Route path="estimator/:id" element={<NoTech><EstimatorEditor /></NoTech>} />

            <Route path="settings/payment-handles" element={<PaymentHandlesSettings />} />
            <Route path="settings/late-fees" element={<AdminOnly><LateFeesSettings /></AdminOnly>} />
            <Route path="settings/income-categories" element={<AdminOnly><IncomeCategoriesPage /></AdminOnly>} />
            {/* Phase 56-a.5 · Aug-2026 — Pricebook Suppliers admin
                (vendor CRUD that feeds the Ops Hub Price Book grid). */}
            <Route path="settings/pricebook-suppliers" element={<AdminOnly><PricebookSuppliersAdmin /></AdminOnly>} />
            {/* Phase 55-a · Aug-2026 — Homeworks (Copilot CRM) importer. */}
            <Route path="settings/import/homeworks" element={<AdminOnly><HomeworksImport /></AdminOnly>} />
            {/* Phase 56-c · Aug-2026 — Pricebook Cost Comparison report. */}
            <Route path="admin/reports/pricebook-cost-comparison" element={<AdminOnly><PricebookCostComparison /></AdminOnly>} />
            {/* Phase 56-d · Aug-2026 — Supplier Spend / Margin report. */}
            <Route path="admin/reports/supplier-spend" element={<AdminOnly><SupplierSpendReport /></AdminOnly>} />
            <Route path="settings/service-categories" element={<AdminOnly><ServiceCategoriesPage /></AdminOnly>} />
            <Route path="settings/job-outcome-reasons" element={<AdminOnly><JobOutcomeReasonsPage /></AdminOnly>} />
            {/* Feb-2026 · P29b — Muted Reasons manager (super_admin / admin / manager). */}
            <Route path="settings/muted-reasons" element={<AdminOrManagerForMutedReasons><MutedReasonsPage /></AdminOrManagerForMutedReasons>} />
            {/* Feb-2026 · P34 — Quiet-hours settings (super_admin / admin / manager).
                Reuses the AdminOrManagerForMutedReasons gate since the role set
                is identical — no need for a third bespoke wrapper. */}
            <Route path="settings/quiet-hours" element={<AdminOrManagerForMutedReasons><QuietHoursPage /></AdminOrManagerForMutedReasons>} />
            {/* Feb-2026 · P36 — Customer Tags settings (super_admin / admin / manager).
                Same role set — reuse the same gate. */}
            <Route path="settings/customer-tags" element={<AdminOrManagerForMutedReasons><CustomerTagsSettingsPage /></AdminOrManagerForMutedReasons>} />
            {/* Feb-2026 · P37b — GPS auto-start settings (super_admin / admin / manager).
                Same role set — reuse the same gate. */}
            <Route path="settings/gps-auto-start" element={<AdminOrManagerForMutedReasons><GpsAutoStartPage /></AdminOrManagerForMutedReasons>} />
            <Route path="settings/billing" element={<AdminOnly><BillingSettings /></AdminOnly>} />
            <Route path="settings/terms" element={<AdminOnly><TermsSettings /></AdminOnly>} />
            <Route path="settings/legal" element={<AdminOnly><LegalDocsList /></AdminOnly>} />
            {/* Feb-2026 · Slice 2B — Multi-ToS admin editor. Registered
                BEFORE the legacy ``/settings/legal/:slug`` route so the
                literal path wins the match. */}
            <Route path="settings/legal/terms-of-service" element={<AdminOnly><TosAdminEditor /></AdminOnly>} />
            <Route path="settings/integrations" element={<AdminOnly><IntegrationsHub /></AdminOnly>} />
            {/* Phase 54b · Feb-2026 — Wholesale supplier settings. */}
            <Route path="settings/suppliers" element={<AdminOrManagerForSuppliers><SupplierSettings /></AdminOrManagerForSuppliers>} />
            {/* Phase 54g · Feb-2026 — supplier sync analytics dashboard. */}
            <Route path="reports/supplier-syncs" element={<AdminOrManagerForSuppliers><SupplierSyncAnalytics /></AdminOrManagerForSuppliers>} />
            {/* Phase 26 · Feb 2026 — Supercool MCP OAuth 2.1 (super_admin only). */}
            <Route path="settings/integrations/supercool" element={<SuperAdminOnly><SupercoolIntegrationPage /></SuperAdminOnly>} />
            {/* Phase 0 POC · Feb-2026 — Homeworks BYO-creds surface (super_admin only). */}
            <Route path="admin/integrations/homeworks" element={<SuperAdminOnly><HomeworksIntegrationPage /></SuperAdminOnly>} />
            <Route path="admin/integrations/homeworks/oauth/callback" element={<SuperAdminOnly><HomeworksOAuthCallback /></SuperAdminOnly>} />
            {/* Feb-2026 · Item 3 — Deletions audit page (super_admin only). */}
            <Route path="admin/audit/deletions" element={<SuperAdminOnly><DeletionsAuditPage /></SuperAdminOnly>} />
            <Route path="admin/migrations" element={<SuperAdminOnly><AdminMigrationsPage /></SuperAdminOnly>} />
            {/* Phase 21 · Feb 2026 — Vanity slug editor (super_admin only). */}
            <Route path="settings/vanity-slugs" element={<SuperAdminOnly><VanitySlugsPage /></SuperAdminOnly>} />
            {/* Feb-2026 — Orphan customer auth users admin (super_admin only). */}
            <Route path="settings/orphan-users" element={<SuperAdminOnly><OrphanUsersPage /></SuperAdminOnly>} />
            {/* Feb-2026 · Phase 22 — Citation Builder (admin + super_admin). */}
            <Route path="settings/citations" element={<AdminOnly><CitationBuilderPage /></AdminOnly>} />
            {/* Feb-2026 · Phase 23-A — Local Rank Tracker (admin + super_admin). */}
            <Route path="settings/rank-tracker" element={<AdminOnly><RankTrackerPage /></AdminOnly>} />
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
            <Route path="marketing/templates" element={<AdminOnly><MarketingTemplatesListPage /></AdminOnly>} />
            <Route path="marketing/broadcasts" element={<AdminOnly><BroadcastsPage /></AdminOnly>} />
            <Route path="admin/communications-log" element={<AdminOnly><CommunicationsLogPage /></AdminOnly>} />
            <Route path="marketing/templates/:id" element={<AdminOnly><MarketingTemplateDetailPage /></AdminOnly>} />
            <Route path="marketing/templates-hub" element={<AdminOnly><TemplatesHub /></AdminOnly>} />
            <Route path="marketing/template-library" element={<AdminOnly><MarketingTemplatesLibraryPage /></AdminOnly>} />
            <Route path="settings/marketing/media" element={<AdminOnly><MarketingMediaAdminPage /></AdminOnly>} />
            {/* Phase 10 · Feb 2026 — Promo codes + referrals admin + portal. */}
            <Route path="settings/promo-codes" element={<AdminOnly><AdminPromoCodesPage /></AdminOnly>} />
            <Route path="admin/referrals" element={<AdminOnly><AdminReferralsPage /></AdminOnly>} />
            <Route path="portal/referrals" element={<PortalReferralsPage />} />
            <Route path="customers/:id/credits" element={<NoTech><CustomerCreditsPage /></NoTech>} />
            <Route path="marketing/segments" element={<AdminOnly><MarketingSegmentsPage /></AdminOnly>} />
            {/* Feb-2026 · Phase B · Marketing Content Studio. */}
            <Route path="marketing/content-studio" element={<AdminOnly><ContentStudioPage /></AdminOnly>} />
            <Route path="admin/marketing/sequences" element={<AdminOnly><MarketingSequencesPage /></AdminOnly>} />
            <Route path="admin/marketing/review-requests" element={<AdminOnly><MarketingReviewRequestsPage /></AdminOnly>} />
            <Route path="admin/marketing/analytics" element={<AdminOnly><MarketingAnalyticsPage /></AdminOnly>} />
            <Route path="admin/marketing/suppressions" element={<AdminOnly><MarketingSuppressionsPage /></AdminOnly>} />
            <Route path="admin/marketing/forms" element={<AdminOnly><MarketingFormsPage /></AdminOnly>} />
            <Route path="admin/leads" element={<AdminOnly><LeadsDashboardPage /></AdminOnly>} />
            {/* Phase 8 · Feb 2026 — Lead detail (admin + manager) */}
            <Route path="leads/:id" element={<AdminOnly><LeadDetail /></AdminOnly>} />
            <Route path="admin/leads/:id" element={<AdminOnly><LeadDetail /></AdminOnly>} />
            <Route path="portal/preferences" element={<PortalPreferences />} />
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
            <Route path="walkie" element={<Walkie />} />

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
            {/* Phase S2 · Feb-2026 — Soshie hub (brand brain + autopilot + review queue) */}
            <Route path="soshie" element={<AdminOnly><SoshieHub /></AdminOnly>} />
            <Route path="tasks" element={<AdminOnly><TasksPage /></AdminOnly>} />
            <Route path="notifications" element={<NotificationsPage />} />
            <Route path="settings/notifications" element={<NotificationPrefs />} />
            {/* Stripe reconciliation route removed in Phase LZ4 (Feb 2026). */}

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
            {/* Phase 5A.2 · Feb 2026 — Workstream is admin-only,
                completed-jobs surface. Route + API + nav all gated. */}
            <Route path="workstream" element={<AdminOrManagerForWorkstream><WorkstreamPage /></AdminOrManagerForWorkstream>} />
            <Route path="workstream/:id" element={<AdminOrManagerForWorkstream><ServiceLogPage /></AdminOrManagerForWorkstream>} />
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
            {/* G2 · Feb-2026 — Driver Activity timeline (admin/super_admin/manager). */}
            <Route path="admin/reports/driver-activity" element={<AdminOrManager><DriverActivityPage /></AdminOrManager>} />
            {/* MR0 · Feb-2026 — Public check-in moderation queue (admin/super_admin/manager). */}
            <Route path="admin/moderation/checkins" element={<AdminOrManager><ModerationCheckinsPage /></AdminOrManager>} />
            {/* Phase SEO-A · Feb-2026 — Free on-page SEO auditor (admin+/manager). */}
            <Route path="admin/seo/auditor" element={<AdminOrManager><SeoAuditorPage /></AdminOrManager>} />
            <Route path="admin/marketing/aeo" element={<AdminOnly><AEOPage /></AdminOnly>} />
            <Route path="admin/reports/weekly-digest" element={<AdminOnly><WeeklyDigestPage /></AdminOnly>} />
            <Route path="admin/marketing/aeo/digest" element={<AdminOnly><AEODigestPage /></AdminOnly>} />
            {/* Phase SEO-B · Feb-2026 — Backlink outreach CRM (admin+/manager). */}
            <Route path="admin/outreach/prospects" element={<AdminOnly><ProspectsKanbanPage /></AdminOnly>} />
            <Route path="admin/outreach/templates" element={<AdminOnly><OutreachTemplatesPage /></AdminOnly>} />
            {/* Phase SEO-C · Feb-2026 — Keyword ideation (admin+/manager). */}
            <Route path="admin/seo/keywords" element={<AdminOrManager><KeywordIdeatorPage /></AdminOrManager>} />
            {/* Phase G4 · Feb-2026 — GPS per-user controls (admin+/manager). */}
            <Route path="admin/settings/gps-users" element={<AdminOrManager><GpsUsersPage /></AdminOrManager>} />
            {/* Phase G5a · Feb-2026 — Geofences + crossings inbox (admin+/manager). */}
            <Route path="admin/gps/geofences" element={<AdminOnly><GeofencesPage /></AdminOnly>} />
            <Route path="admin/gps/crossings" element={<AdminOnly><CrossingsInbox /></AdminOnly>} />
            {/* Phase G5b · Feb-2026 — Time on Site (attribution report). */}
            <Route path="admin/gps/time-on-site" element={<AdminOnly><TimeOnSitePage /></AdminOnly>} />
            {/* Phase G5d · Feb-2026 — Driver Scorecard / Leaderboard. */}
            <Route path="admin/gps/scorecard" element={<AdminOnly><DriverScorecardPage /></AdminOnly>} />
            {/* MR1+MR2 · Feb-2026 — Public widget embed preview + snippet. */}
            <Route path="admin/moderation/widget-embed" element={<AdminOrManager><WidgetEmbedPage /></AdminOrManager>} />
            {/* MR3 · Feb-2026 — Public widget analytics (impressions/clicks/CTR). */}
            <Route path="admin/moderation/widget-analytics" element={<AdminOnly><WidgetAnalyticsPage /></AdminOnly>} />
            {/* Phase 50.A — Chemical Costs CRUD (admin/super_admin) */}
            <Route path="admin/settings/chemical-costs" element={<AdminOnly><ChemicalCosts /></AdminOnly>} />
            {/* Phase 51.I — Recurring Jobs (admin/super_admin) */}
            <Route path="admin/recurring-jobs" element={<AdminOrManager><RecurringJobs /></AdminOrManager>} />
            {/* Phase 51.K — CFO Reports (admin/super_admin) */}
            <Route path="admin/cfo/reports" element={<AdminOnly><CFOReports /></AdminOnly>} />
            <Route path="admin/finance/bills" element={<AdminOnly><VendorBills /></AdminOnly>} />
            <Route path="admin/reports/pricing-insights" element={<AdminOnly><PricingInsights /></AdminOnly>} />
            {/* Phase 54 — RingCentral admin (settings + test + event log) */}
            <Route path="admin/settings/ringcentral" element={<AdminOnly><RingCentralAdmin /></AdminOnly>} />
            <Route path="admin/ringcentral-test" element={<AdminOnly><RingCentralAdmin /></AdminOnly>} />
            {/* Phase 6B · Feb 2026 — Telephony admin (RingCentral) */}
            <Route path="settings/telephony" element={<AdminOnly><TelephonyPage /></AdminOnly>} />
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
            <Route path="time-off" element={<TimeOffPage />} />
            <Route path="admin/time-off" element={<AdminOnly><AdminTimeOffPage /></AdminOnly>} />
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
            {/* Feb-2026 · P37d — Dispatcher GPS Auto-Start audit. */}
            <Route path="reports/gps-auto-start-audit" element={<AdminOrManagerForProfitReport><GpsAutoStartAudit /></AdminOrManagerForProfitReport>} />
            <Route path="reports/revenue-by-city" element={<AdminOnly><RevenueByCity /></AdminOnly>} />
            <Route path="reports/revenue-by-crew" element={<AdminOnly><RevenueByCrew /></AdminOnly>} />
            <Route path="reports/revenue-by-customer" element={<AdminOnly><RevenueByCustomer /></AdminOnly>} />
            <Route path="reports/gross-sales" element={<AdminOnly><GrossSales /></AdminOnly>} />
            <Route path="reports/invoiced-items" element={<AdminOnly><InvoicedItems /></AdminOnly>} />
            {/* Feb-2026 · Dashboard "Review →" click-through — was
                a 404, now a real page. */}
            <Route path="reports/uncategorized-items" element={<AdminOnly><UncategorizedItemsReport /></AdminOnly>} />
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
            {/* Feb-2026 · Pool Repair Pricing Calculator (admin+super_admin, techs hidden). */}
            <Route path="ops/repair-calculator" element={<AdminOnly><RepairCalculatorPage /></AdminOnly>} />
            {/* Phase 17 · Feb 2026 — /dispatch now renders the Google Maps
                + Directions redesigned board. Admin-only; techs never
                see pricing/routing. Legacy path preserved at /ops/dispatch. */}
            <Route path="dispatch" element={<AdminOnly><DispatchErrorBoundary component="DispatchBoard" componentLabel="Dispatch Board"><DispatchBoardPage /></DispatchErrorBoundary></AdminOnly>} />
            <Route path="admin/diagnostics/errors" element={<AdminOnly><AdminDiagnosticsErrorsPage /></AdminOnly>} />
            <Route path="ops/dispatch" element={<OpsHub />} />
            <Route path="dispatch/map" element={<AdminOnly><DispatchMap /></AdminOnly>} />
            <Route path="schedule" element={<OpsHub />} />
            <Route path="schedule/map" element={<AdminOnly><ScheduleMap /></AdminOnly>} />
            <Route path="routes" element={<OpsHub />} />
            {/* Phase 5A.2 · Feb 2026 — Workstream duplicate removed; the
                admin-only route defined earlier owns the /workstream URL. */}
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
            <Route path="job-timers" element={<AdminOnly><JobTimersPage /></AdminOnly>} />
            <Route path="avg-job-time" element={<AdminOnly><JobTimersPage /></AdminOnly>} />
            {/* Feb-2026 · Chemical Cost Report — /admin/reports/chemical-costs. */}
            <Route path="admin/reports/chemical-costs"
                element={<AdminOnly><ChemicalCostReportPage /></AdminOnly>} />

            {/* Phase 11 · Feb 2026 — Equipment Service Trackers.
                Filter & Salt Cell cleaning trackers with per-tenant
                local-time weekly digest + optional customer reminders. */}
            <Route path="tracking/filter" element={<AdminOnly><FilterTrackerListPage /></AdminOnly>} />
            <Route path="tracking/filter/manage" element={<AdminOnly><FilterTrackerManagePage /></AdminOnly>} />
            <Route path="tracking/salt-cell" element={<AdminOnly><SaltCellTrackerListPage /></AdminOnly>} />
            <Route path="tracking/salt-cell/manage" element={<AdminOnly><SaltCellTrackerManagePage /></AdminOnly>} />

            {/* Phase 13 parity-gap closures */}
            {/* Phase 8 · Feb 2026 — /leads points at the real dashboard,
                replacing the pre-Phase-8 GapClosures placeholder. */}
            <Route path="leads" element={<AdminOnly><LeadsDashboardPage /></AdminOnly>} />
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
            <Route path="weather" element={<AdminOrManagerForWeather><WeatherHub /></AdminOrManagerForWeather>} />

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
            {/* Task QQ Phase 2 · Feb 2026 — Lumino hosted-checkout return. */}
            <Route path="portal/payment-method/return" element={<PortalPaymentReturn />} />
            {/* BUG D fix (Feb-2026) — defensive redirect so any
                stray link to bare ``/portal`` lands on the home page
                instead of NotFound. */}
            <Route path="portal" element={<Navigate to="/portal/home" replace />} />
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
            {/* Feb-2026 P0 fix (Bug 2 · Item A) — legacy plural
                ``portal/payment-methods`` route + component removed;
                the singular route above is the one true portal card
                management surface. */}
            {/* Phase 14b · Feb 2026 — Bulk charge runs history + detail. */}
            <Route path="admin/finance/bulk-charge-runs" element={<_P14bRunsList />} />
            <Route path="admin/finance/bulk-charge-runs/:runId" element={<_P14bRunDetail />} />
            {/* Phase 17 · Feb 2026 — QuickBooks Online read-sync integration. */}
            <Route path="admin/integrations/qbo" element={<QuickBooksIntegrationPage />} />
            <Route path="portal/documents" element={<PortalDocuments />} />
            <Route path="portal/messages" element={<PortalMessages />} />
            <Route path="portal/chats" element={<PortalChatsPage />} />
            <Route path="portal/photos" element={<PortalPhotosPage />} />
            <Route path="portal/videos" element={<PortalVideosPage />} />
            {/* Phase 34 · Feb-2026 · Task H — the ``/portal/book`` route
                has been removed from the customer portal. The Request
                Service flow (below) supersedes it. Redirect any bookmark
                traffic to ``/portal/request-service`` so we don't leave
                a 404 landmine. */}
            <Route path="portal/book" element={<Navigate to="/portal/request-service" replace />} />
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
            {/* Feb-2026 · Item 4 — AI Brain (knowledge base) + Copilot chat. */}
            <Route path="settings/ai-brain" element={<AdminOnly><AIBrainPage /></AdminOnly>} />
            <Route path="admin/copilot" element={<AdminOnly><CopilotPage /></AdminOnly>} />
            {/* LZ5 · Feb-2026 — Lumino payment-link backfill (super_admin only). */}
            <Route path="admin/tools/lumino-backfill" element={<SuperAdminOnly><LuminoBackfillPage /></SuperAdminOnly>} />
            {/* PB1 · Feb-2026 — Profit report (admin-only; internal margin data). */}
            <Route path="admin/reports/profit" element={<AdminOrManagerForProfitReport><ProfitReportPage /></AdminOrManagerForProfitReport>} />
            {/* G0 · Feb-2026 — GPS driver-activity settings (admin-only). */}
            <Route path="admin/settings/gps" element={<AdminOnly><GpsSettingsPage /></AdminOnly>} />
            {/* Feb-2026 · Item 6 — Business Card admin editor. */}
            <Route path="settings/business-card" element={<AdminOnly><BusinessCardSettingsPage /></AdminOnly>} />
            <Route path="account/profile" element={<MyProfilePage />} />
            {/* Phase 34 · Task GG · Feb 2026 — Google Business Profile
                review URL admin settings screen. Uses AdminOnly so
                admin + super_admin can edit; add ``owner`` role to
                AdminOnly if that role needs access (matches Task X). */}
            <Route path="settings/reviews" element={<AdminOnly><GoogleReviewSettings /></AdminOnly>} />
            {/* Feb-2026 · Phase 20 P3 — Website SEO analyzer. */}
            <Route path="settings/website-seo" element={<AdminOnly><WebsiteSeoPage /></AdminOnly>} />
            {/* Feb-2026 · Phase 20 P4 — Local SEO checklist. */}
            <Route path="settings/local-seo" element={<AdminOnly><LocalSeoPage /></AdminOnly>} />
            {/* Feb-2026 · Phase 20 P1 — GBP post drafter. */}
            <Route path="marketing/gbp-posts" element={<AdminOnly><GbpPostsPage /></AdminOnly>} />
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
            {/* Phase 18 · Feb-2026 — Chemical Cost Report */}
            <Route path="admin/inventory/chemical-cost-report" element={<AdminOnly><ChemicalCostReport /></AdminOnly>} />
            <Route path="admin/inventory/:id" element={<AdminOnly><InventoryDetail /></AdminOnly>} />
            {/* Phase 24 — Check Writer */}
            <Route path="admin/checks" element={<AdminOnly><CheckRegister /></AdminOnly>} />
            <Route path="admin/checks/new" element={<AdminOnly><CheckNew /></AdminOnly>} />
            <Route path="admin/checks/bank-accounts" element={<AdminOnly><CheckBanks /></AdminOnly>} />
            <Route path="admin/checks/payees" element={<AdminOnly><CheckPayees /></AdminOnly>} />
            <Route path="admin/checks/analytics" element={<AdminOnly><CheckAnalytics /></AdminOnly>} />
            <Route path="admin/checks/:id" element={<AdminOnly><CheckDetail /></AdminOnly>} />
            {/* Phase 5A · Feb 2026 — Property Lookup is admin/manager
                only. Route gates + backend gates both deny techs. */}
            <Route path="tech/property-lookup" element={<NoTech><PropertyLookupPage /></NoTech>} />
            <Route path="property-lookup" element={<NoTech><PropertyLookupPage /></NoTech>} />
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

/** Phase 6B · Feb 2026 — mounts the RingCentral SSE listener at the App
 *  shell so any admin/manager user gets inbound-call toasts on every
 *  page. The hook self-gates on role (see useTelephonyLiveEvents.js). */
function TelephonyLiveEventsBridge() {
  useTelephonyLiveEvents();
  return null;
}
