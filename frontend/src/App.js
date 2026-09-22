import React from "react";
import { BrowserRouter, Routes, Route, Navigate, useParams } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth";
// Phase G4 · Feb-2026 — Route-level lazy loading. `<PageSkeleton />`
// is the shared Suspense fallback used while a route chunk is being
// fetched. Kept intentionally dependency-free so it lives in the
// main bundle at ~1 KB gzip.
import PageSkeleton from "@/components/PageSkeleton";
// Phase I1.5.c · Feb-2026 — Tenant theme provider (CSS-var overlay).
// Wraps the authenticated app so ``useTenantTheme()`` returns the
// tenant-persisted palette and the DOM has ``--tenant-*`` vars set
// on ``<html>`` for any consumer opting into the overlay.
import { TenantThemeProvider } from "@/hooks/useTenantTheme";
import { ConfirmProvider } from "@/components/ui/confirm-dialog";
import { Toaster as SonnerToaster } from "@/components/ui/sonner";
import ScrollToTop from "@/components/ScrollToTop";
import useTelephonyLiveEvents from "@/hooks/useTelephonyLiveEvents";
import AppLayout from "@/layouts/AppLayout";
const PublicEstimateLanding = React.lazy(() => import(/* webpackChunkName: "p-portal-publicestimatelanding" */ "@/pages/portal/PublicEstimateLanding"));
import Login from "@/pages/Login";
// Phase 34 · Feb 2026 — self-serve password reset landing (stub UI).
// Backend endpoint tracked in /app/memory/todo_password_reset.md.
import ForgotPassword from "@/pages/ForgotPassword";
import ResetPassword from "@/pages/ResetPassword";
const PortalReviewSubmit = React.lazy(() => import(/* webpackChunkName: "p-portal-portalreviewsubmit" */ "@/pages/portal/PortalReviewSubmit"));
const PortalAgreementRenew = React.lazy(() => import(/* webpackChunkName: "p-portal-portalagreementrenew" */ "@/pages/portal/PortalAgreementRenew"));

// Phase P30 · Feb 2026 — Stripe Checkout setup-mode redirect target.
const SetupSuccess = React.lazy(() => import(/* webpackChunkName: "p-portal-setupsuccess" */ "@/pages/portal/SetupSuccess"));
const Signup = React.lazy(() => import(/* webpackChunkName: "p-signup" */ "@/pages/Signup"));
// Feb-2026 · Business Signup SP2 — new public + wizard surface.
const BusinessSignup = React.lazy(() => import(/* webpackChunkName: "p-businesssignup" */ "@/pages/BusinessSignup"));
const BusinessSignupVerify = React.lazy(() => import(/* webpackChunkName: "p-businesssignupverify" */ "@/pages/BusinessSignupVerify").then(m => ({ default: m.BusinessSignupVerify })));
const BusinessSignupVerifyEmailSent = React.lazy(() => import(/* webpackChunkName: "p-businesssignupverify" */ "@/pages/BusinessSignupVerify").then(m => ({ default: m.BusinessSignupVerifyEmailSent })));
const OnboardingWizard = React.lazy(() => import(/* webpackChunkName: "p-onboardingwizard" */ "@/pages/OnboardingWizard"));
const TenantPicker = React.lazy(() => import(/* webpackChunkName: "p-tenantpicker" */ "@/pages/TenantPicker"));
const AdminDashboard = React.lazy(() => import(/* webpackChunkName: "p-admin-dashboard" */ "@/pages/admin/Dashboard"));
import Placeholder from "@/pages/Placeholder";
const CustomersList = React.lazy(() => import(/* webpackChunkName: "p-customers-customerslist" */ "@/pages/customers/CustomersList"));
const CustomerForm = React.lazy(() => import(/* webpackChunkName: "p-customers-customerform" */ "@/pages/customers/CustomerForm"));
const CustomerDetail = React.lazy(() => import(/* webpackChunkName: "p-customers-customerdetail" */ "@/pages/customers/CustomerDetail"));
const CustomerChemistry = React.lazy(() => import(/* webpackChunkName: "p-customers-customerchemistry" */ "@/pages/customers/CustomerChemistry"));
const CustomerChemistryHistory = React.lazy(() => import(/* webpackChunkName: "p-customers-customerchemistryhistory" */ "@/pages/customers/CustomerChemistryHistory"));
const RequestJobPage = React.lazy(() => import(/* webpackChunkName: "p-job-requests-jobrequestspages" */ "@/pages/job_requests/JobRequestsPages").then(m => ({ default: m.RequestJobPage })));
const AdminJobRequestsPage = React.lazy(() => import(/* webpackChunkName: "p-job-requests-jobrequestspages" */ "@/pages/job_requests/JobRequestsPages").then(m => ({ default: m.AdminJobRequestsPage })));
const CalendarSchedule = React.lazy(() => import(/* webpackChunkName: "p-schedule-calendarschedule" */ "@/pages/schedule/CalendarSchedule"));
const WorkstreamPage = React.lazy(() => import(/* webpackChunkName: "p-workstream-workstreampage" */ "@/pages/workstream/WorkstreamPage"));
const ServiceLogPage = React.lazy(() => import(/* webpackChunkName: "p-workstream-servicelogpage" */ "@/pages/workstream/ServiceLogPage"));
const CFODashboard = React.lazy(() => import(/* webpackChunkName: "p-cfo-cfodashboard" */ "@/pages/cfo/CFODashboard"));
const JobNew = React.lazy(() => import(/* webpackChunkName: "p-jobs-jobnew" */ "@/pages/jobs/JobNew"));
const JobDetail = React.lazy(() => import(/* webpackChunkName: "p-jobs-jobdetail" */ "@/pages/jobs/JobDetail"));
const JobsList = React.lazy(() => import(/* webpackChunkName: "p-jobs-jobslist" */ "@/pages/jobs/JobsList"));
const AdminUsersList = React.lazy(() => import(/* webpackChunkName: "p-admin-adminuserslist" */ "@/pages/admin/AdminUsersList"));
const AdminTagsList = React.lazy(() => import(/* webpackChunkName: "p-admin-admintagslist" */ "@/pages/admin/AdminTagsList"));
const AdminCommsSuppressionLog = React.lazy(() => import(/* webpackChunkName: "p-admin-admincommssuppressionlog" */ "@/pages/admin/AdminCommsSuppressionLog"));
const AdminServiceReportsList = React.lazy(() => import(/* webpackChunkName: "p-admin-adminservicereportslist" */ "@/pages/admin/AdminServiceReportsList"));
const AdminTimeEntriesList = React.lazy(() => import(/* webpackChunkName: "p-admin-admintimeentrieslist" */ "@/pages/admin/AdminTimeEntriesList"));
const ReflowHistoryPage = React.lazy(() => import(/* webpackChunkName: "p-admin-reflowhistorypage" */ "@/pages/admin/ReflowHistoryPage"));
// Phase F2 · Feb-2026 — Charge Template Bundles admin CRUD.
const AdminChargeTemplatesPage = React.lazy(() => import(/* webpackChunkName: "p-admin-adminchargetemplatespage" */ "@/pages/admin/AdminChargeTemplatesPage"));
// Phase F3 · Feb-2026 — Soshie moderation queue.
const SoshieModerationQueuePage = React.lazy(() => import(/* webpackChunkName: "p-admin-soshiemoderationqueue" */ "@/pages/admin/SoshieModerationQueue"));
// Task RR/SS Phase 2 · Feb 2026 — AI Employee scope toggle + tool audit.
const AiPersonasScopePage = React.lazy(() => import(/* webpackChunkName: "p-admin-aipersonasscopepage" */ "@/pages/admin/AiPersonasScopePage"));
const AiToolAuditPage = React.lazy(() => import(/* webpackChunkName: "p-admin-aitoolauditpage" */ "@/pages/admin/AiToolAuditPage"));
const PortalPaymentReturn = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpaymentreturn" */ "@/pages/portal/PortalPaymentReturn"));
const QuickBooksIntegrationPage = React.lazy(() => import(/* webpackChunkName: "p-admin-integrations-quickbooksintegrationpage" */ "@/pages/admin/integrations/QuickBooksIntegrationPage"));
import {
  BulkChargeRunsList as _P14bRunsList,
  BulkChargeRunDetail as _P14bRunDetail,
} from "@/pages/admin/BulkChargeRunsPage";
const QuotesList = React.lazy(() => import(/* webpackChunkName: "p-quotes-quoteslist" */ "@/pages/quotes/QuotesList"));
const QuoteInvoiceNew = React.lazy(() => import(/* webpackChunkName: "p-quotes-quoteinvoicenew" */ "@/pages/quotes/QuoteInvoiceNew"));
const QuoteInvoiceDetail = React.lazy(() => import(/* webpackChunkName: "p-quotes-quoteinvoicedetail" */ "@/pages/quotes/QuoteInvoiceDetail"));
const InvoicesList = React.lazy(() => import(/* webpackChunkName: "p-invoices-invoiceslist" */ "@/pages/invoices/InvoicesList"));
const MasterInvoicesList = React.lazy(() => import(/* webpackChunkName: "p-invoices-masterinvoice" */ "@/pages/invoices/MasterInvoice").then(m => ({ default: m.MasterInvoicesList })));
const MasterInvoiceNew = React.lazy(() => import(/* webpackChunkName: "p-invoices-masterinvoice" */ "@/pages/invoices/MasterInvoice").then(m => ({ default: m.MasterInvoiceNew })));
const MasterInvoiceDetail = React.lazy(() => import(/* webpackChunkName: "p-invoices-masterinvoice" */ "@/pages/invoices/MasterInvoice").then(m => ({ default: m.MasterInvoiceDetail })));
const PaymentHandlesSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-paymenthandles" */ "@/pages/settings/PaymentHandles"));
const LateFeesSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-latefees" */ "@/pages/settings/LateFees"));
const IncomeCategoriesPage = React.lazy(() => import(/* webpackChunkName: "p-settings-incomecategoriespage" */ "@/pages/settings/IncomeCategoriesPage"));
const PricebookSuppliersAdmin = React.lazy(() => import(/* webpackChunkName: "p-settings-pricebooksuppliersadmin" */ "@/pages/settings/PricebookSuppliersAdmin"));
const PricebookCostComparison = React.lazy(() => import(/* webpackChunkName: "p-reports-pricebookcostcomparison" */ "@/pages/reports/PricebookCostComparison"));
// Pricebook × Profit-Reporting Phase 1 · Feb-2026 — consolidated
// Categories admin (Income + Service tabs) reached from the
// Pricebook toolbar. Coexists with the legacy standalone pages so
// bookmarked deep-links keep working.
const CategoriesAdmin = React.lazy(() => import(/* webpackChunkName: "p-pricebook-categoriesadmin" */ "@/pages/pricebook/CategoriesAdmin"));
const SupplierSpendReport = React.lazy(() => import(/* webpackChunkName: "p-reports-supplierspendreport" */ "@/pages/reports/SupplierSpendReport"));
const ServiceCategoriesPage = React.lazy(() => import(/* webpackChunkName: "p-settings-servicecategoriespage" */ "@/pages/settings/ServiceCategoriesPage"));
// Phase P16 · Feb-2026 — Master Services (Pricebook) settings page.
// Distinct from ServiceCategoriesPage (which manages the taxonomy);
// this one manages the flat name / default_price / category rows the
// Add-Recurring-Job combobox writes back into.
const MasterServicesSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-masterservicessettings" */ "@/pages/settings/MasterServicesSettings"));
const JobOutcomeReasonsPage = React.lazy(() => import(/* webpackChunkName: "p-settings-joboutcomereasonspage" */ "@/pages/settings/JobOutcomeReasonsPage"));
// Feb-2026 · P29b — Muted Reasons admin (super_admin / admin / manager).
const MutedReasonsPage = React.lazy(() => import(/* webpackChunkName: "p-settings-mutedreasonspage" */ "@/pages/settings/MutedReasonsPage"));
// Feb-2026 · P34 — Automation quiet-hours admin (super_admin / admin / manager).
const QuietHoursPage = React.lazy(() => import(/* webpackChunkName: "p-settings-quiethourspage" */ "@/pages/settings/QuietHoursPage"));
// Feb-2026 · P36 — Customer Tags settings manager (super_admin / admin / manager).
const CustomerTagsSettingsPage = React.lazy(() => import(/* webpackChunkName: "p-settings-customertagssettingspage" */ "@/pages/settings/CustomerTagsSettingsPage"));
// Feb-2026 · P37b — GPS auto-start settings (super_admin / admin / manager).
const GpsAutoStartPage = React.lazy(() => import(/* webpackChunkName: "p-settings-gpsautostartpage" */ "@/pages/settings/GpsAutoStartPage"));
const BillingSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-billingsettings" */ "@/pages/settings/BillingSettings"));
const SupplierSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-suppliersettings" */ "@/pages/settings/SupplierSettings"));
const SupplierSyncAnalytics = React.lazy(() => import(/* webpackChunkName: "p-reports-suppliersyncanalytics" */ "@/pages/reports/SupplierSyncAnalytics"));
// Phase 55-a · Aug-2026 — Homeworks (Copilot CRM) importer scaffold.
// Feb-2026 · K55.a — import removed as part of the SuperCool +
// HomeWorks integration sunset (PHASE_K55_a_FRONTEND_REMOVAL.md).
const AutoVisitEmailSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-autovisitemailsettings" */ "@/pages/settings/AutoVisitEmailSettings"));
const PortalPhotos = React.lazy(() => import(/* webpackChunkName: "p-portal-portalphotos" */ "@/pages/portal/PortalPhotos"));
const PortalReviews = React.lazy(() => import(/* webpackChunkName: "p-portal-portalreviews" */ "@/pages/portal/PortalReviews"));
const AdminReviewsPage = React.lazy(() => import(/* webpackChunkName: "p-admin-adminreviewspage" */ "@/pages/admin/AdminReviewsPage"));
// Phase A1 · Feb-2026 — Proactive Intelligence full-list page.
// Route ``/admin/intelligence/alerts`` — gated to admin + super_admin
// via <AdminOrSuperAdminOnly>; the backend router returns 403 for any
// other caller (``insufficient_role_for_alerts``), so the two gates
// stay in lock-step.
const IntelligenceAlerts = React.lazy(() => import(/* webpackChunkName: "p-admin-intelligencealerts" */ "@/pages/admin/IntelligenceAlerts"));
// Phase C · Feb-2026 — Sales Pipeline Kanban page.
// Route ``/admin/pipeline`` — gated to admin + super_admin + manager
// via ``<AdminOrManager>``. Backend returns 403
// ``insufficient_role_for_pipeline`` for any other caller.
const SalesPipeline = React.lazy(() => import(/* webpackChunkName: "p-admin-salespipeline" */ "@/pages/admin/SalesPipeline"));
const MarketingTemplatesLibraryPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingtemplateslibrarypage" */ "@/pages/marketing/MarketingTemplatesLibraryPage"));
// Phase 9B · Feb 2026 — Rebuilt Marketing Templates admin (TipTap +
// merge-tag palette + media picker + unresolved-token red-chip banner).
const MarketingTemplatesListPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingtemplatesadmin" */ "@/pages/marketing/MarketingTemplatesAdmin"));
const MarketingTemplateDetailPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingtemplatesadmin" */ "@/pages/marketing/MarketingTemplatesAdmin").then(m => ({ default: m.MarketingTemplateDetailPage })));
const MarketingMediaAdminPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingmediaadmin" */ "@/pages/marketing/MarketingMediaAdmin"));
// Feb-2026 · Phase B · Marketing Content Studio (Supercool image gen).
const ContentStudioPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-contentstudiopage" */ "@/pages/marketing/ContentStudioPage"));
// Phase 10 · Feb 2026 — Referrals + promo codes admin + portal.
const PortalReferralsPage = React.lazy(() => import(/* webpackChunkName: "p-portal-portalreferralspage" */ "@/pages/portal/PortalReferralsPage"));
const AdminPromoCodesPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-adminpromocodespage" */ "@/pages/marketing/AdminPromoCodesPage"));
const AdminReferralsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-adminreferralspage" */ "@/pages/marketing/AdminReferralsPage"));
const CustomerCreditsPage = React.lazy(() => import(/* webpackChunkName: "p-customers-customercreditspage" */ "@/pages/customers/CustomerCreditsPage"));
const MarketingSegmentsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingsegmentspage" */ "@/pages/marketing/MarketingSegmentsPage"));
const MarketingSequencesPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingsequencespage" */ "@/pages/marketing/MarketingSequencesPage"));
const MarketingReviewRequestsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingreviewrequestspage" */ "@/pages/marketing/MarketingReviewRequestsPage"));
const MarketingAnalyticsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketinganalyticspage" */ "@/pages/marketing/MarketingAnalyticsPage"));
const MarketingSuppressionsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingsuppressionspage" */ "@/pages/marketing/MarketingSuppressionsPage"));
const BroadcastsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-broadcastspage" */ "@/pages/marketing/BroadcastsPage"));
const CommunicationsLogPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-communicationslogpage" */ "@/pages/marketing/CommunicationsLogPage"));
const PortalPreferences = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpreferences" */ "@/pages/portal/PortalPreferences"));
const PrivacyPolicy = React.lazy(() => import(/* webpackChunkName: "p-privacypolicy" */ "@/pages/PrivacyPolicy"));
const TermsOfService = React.lazy(() => import(/* webpackChunkName: "p-termsofservice" */ "@/pages/TermsOfService"));
const AiTransparency = React.lazy(() => import(/* webpackChunkName: "p-aitransparency" */ "@/pages/AiTransparency"));
const PortalVideos = React.lazy(() => import(/* webpackChunkName: "p-portal-portalvideos" */ "@/pages/portal/PortalVideos"));
const CommsTemplatesLibrary = React.lazy(() => import(/* webpackChunkName: "p-comms-commspages" */ "@/pages/comms/CommsPages").then(m => ({ default: m.CommsTemplatesLibrary })));
const CommsEmailBuilder = React.lazy(() => import(/* webpackChunkName: "p-comms-commspages" */ "@/pages/comms/CommsPages").then(m => ({ default: m.CommsEmailBuilder })));
const CommsSmsBuilder = React.lazy(() => import(/* webpackChunkName: "p-comms-commspages" */ "@/pages/comms/CommsPages").then(m => ({ default: m.CommsSmsBuilder })));
const CommsAutomationsPage = React.lazy(() => import(/* webpackChunkName: "p-comms-commspages" */ "@/pages/comms/CommsPages").then(m => ({ default: m.CommsAutomationsPage })));
const CommsSendsHistoryPage = React.lazy(() => import(/* webpackChunkName: "p-comms-commspages" */ "@/pages/comms/CommsPages").then(m => ({ default: m.CommsSendsHistoryPage })));
const ReviewsDashboard = React.lazy(() => import(/* webpackChunkName: "p-reviews-reviewspages" */ "@/pages/reviews/ReviewsPages").then(m => ({ default: m.ReviewsDashboard })));
const ReviewsRequestsPage = React.lazy(() => import(/* webpackChunkName: "p-reviews-reviewspages" */ "@/pages/reviews/ReviewsPages").then(m => ({ default: m.ReviewsRequestsPage })));
const ReviewsPlatformsPage = React.lazy(() => import(/* webpackChunkName: "p-reviews-reviewspages" */ "@/pages/reviews/ReviewsPages").then(m => ({ default: m.ReviewsPlatformsPage })));
const ReviewsWidgetPage = React.lazy(() => import(/* webpackChunkName: "p-reviews-reviewspages" */ "@/pages/reviews/ReviewsPages").then(m => ({ default: m.ReviewsWidgetPage })));
const PublicReviewLanding = React.lazy(() => import(/* webpackChunkName: "p-reviews-publicreviewlanding" */ "@/pages/reviews/PublicReviewLanding"));
const PublicReviewsWidgetPage = React.lazy(() => import(/* webpackChunkName: "p-reviews-publicreviewswidgetpage" */ "@/pages/reviews/PublicReviewsWidgetPage"));
// QuoteIQ Q1-UI · Feb 2026
const AICreditsPage = React.lazy(() => import(/* webpackChunkName: "p-settings-aicreditspage" */ "@/pages/settings/AICreditsPage"));
const ChemicalsPage = React.lazy(() => import(/* webpackChunkName: "p-settings-chemicalspage" */ "@/pages/settings/ChemicalsPage"));
// Feb-2026 · Phase 20 P3 — Website SEO analyzer.
const WebsiteSeoPage = React.lazy(() => import(/* webpackChunkName: "p-settings-websiteseopage" */ "@/pages/settings/WebsiteSeoPage"));
// Feb-2026 · Phase 20 P4 — GBP checklist.
const LocalSeoPage = React.lazy(() => import(/* webpackChunkName: "p-settings-localseopage" */ "@/pages/settings/LocalSeoPage"));
// Feb-2026 · Phase 20 P1 — GBP post drafter.
const GbpPostsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-gbppostspage" */ "@/pages/marketing/GbpPostsPage"));
// Feb-2026 · Phase 20 P5 — Public NFC review card.
const NfcReviewCardPage = React.lazy(() => import(/* webpackChunkName: "p-public-nfcreviewcardpage" */ "@/pages/public/NfcReviewCardPage"));
// Feb-2026 · Item 4 — AI Brain + Copilot admin pages.
const AIBrainPage = React.lazy(() => import(/* webpackChunkName: "p-settings-aibrainpage" */ "@/pages/settings/AIBrainPage"));
const CopilotPage = React.lazy(() => import(/* webpackChunkName: "p-admin-copilotpage" */ "@/pages/admin/CopilotPage"));
const AiMeasurePage = React.lazy(() => import(/* webpackChunkName: "p-admin-aimeasurepage" */ "@/pages/admin/AiMeasurePage"));
const LuminoBackfillPage = React.lazy(() => import(/* webpackChunkName: "p-admin-luminobackfillpage" */ "@/pages/admin/LuminoBackfillPage"));
const ProfitReportPage = React.lazy(() => import(/* webpackChunkName: "p-admin-profitreportpage" */ "@/pages/admin/ProfitReportPage"));
const GpsSettingsPage = React.lazy(() => import(/* webpackChunkName: "p-admin-gpssettingspage" */ "@/pages/admin/GpsSettingsPage"));
// Feb-2026 · Item 6 — Business Card admin editor.
const BusinessCardSettingsPage = React.lazy(() => import(/* webpackChunkName: "p-settings-businesscardsettings" */ "@/pages/settings/BusinessCardSettings"));
// Phase MI1 · Feb 2026 — multi-industry checklist template editor.
const ChecklistTemplatesSettings = React.lazy(() => import(/* webpackChunkName: "p-admin-checklisttemplatessettings" */ "@/pages/admin/ChecklistTemplatesSettings"));
// Feb-2026 · TD-08 promoted — admin logo upload UI.
const BrandLogoSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-brandlogosettings" */ "@/pages/settings/BrandLogoSettings"));
// Phase I1.5.b · Feb-2026 — Tenant theme editor UI + live preview.
const ThemeSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-themesettings" */ "@/pages/settings/ThemeSettings"));
// Feb-2026 · Business Settings — company defaults + brand colours.
const BusinessSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-businesssettings" */ "@/pages/settings/BusinessSettings"));
const IndustriesSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-industriessettings" */ "@/pages/settings/IndustriesSettings"));
// Feb-2026 · Consolidated Settings Hub — shared layout + Social tab.
import SettingsHub, { SettingsGeneral } from "@/layouts/SettingsHub";
const ProposalAnalyticsPage = React.lazy(() => import(/* webpackChunkName: "p-settings-proposalanalyticspage" */ "@/pages/settings/ProposalAnalyticsPage"));
// Feb-2026 · Ticket #3 + #4 — Org Notifications + AI Configuration tabs.
const OrgNotificationsSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-orgnotificationssettings" */ "@/pages/settings/OrgNotificationsSettings"));
const AIConfigurationSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-aiconfigurationsettings" */ "@/pages/settings/AIConfigurationSettings"));
const ChemistryConfigurationSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-chemistryconfigurationsettings" */ "@/pages/settings/ChemistryConfigurationSettings"));
const FeatureMarketplaceSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-featuremarketplacesettings" */ "@/pages/settings/FeatureMarketplaceSettings"));
const SettingsSocial = React.lazy(() => import(/* webpackChunkName: "p-settings-settingssocial" */ "@/pages/settings/SettingsSocial"));
const MyProfilePage = React.lazy(() => import(/* webpackChunkName: "p-account-myprofilepage" */ "@/pages/account/MyProfilePage"));
const GoogleReviewSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-googlereviewsettings" */ "@/pages/settings/GoogleReviewSettings"));
const VanitySlugsPage = React.lazy(() => import(/* webpackChunkName: "p-settings-vanityslugspage" */ "@/pages/settings/VanitySlugsPage"));
const OrphanUsersPage = React.lazy(() => import(/* webpackChunkName: "p-settings-orphanuserspage" */ "@/pages/settings/OrphanUsersPage"));
const CitationBuilderPage = React.lazy(() => import(/* webpackChunkName: "p-settings-citationbuilderpage" */ "@/pages/settings/CitationBuilderPage"));
const RankTrackerPage = React.lazy(() => import(/* webpackChunkName: "p-settings-ranktrackerpage" */ "@/pages/settings/RankTrackerPage"));
const DealsKanbanPage = React.lazy(() => import(/* webpackChunkName: "p-deals-dealskanbanpage" */ "@/pages/deals/DealsKanbanPage"));
// QuoteIQ Q2-UI · Feb 2026
const AIEstimatorPage = React.lazy(() => import(/* webpackChunkName: "p-estimates-aiestimatorpage" */ "@/pages/estimates/AIEstimatorPage"));
// Phase 34 · Feb-2026 · Task H — the customer-facing Book Service
// surface has been retired. The route ``/portal/book`` now redirects
// to ``/portal/request-service`` (see below). The former
// ``PortalBook`` page component was deleted in Phase B1 (Feb 2026)
// after confirming no route or import referenced it.
const PortalChatsPage = React.lazy(() => import(/* webpackChunkName: "p-portal-portalchatspage" */ "@/pages/portal/PortalChatsPage"));
const PortalPhotosPage = React.lazy(() => import(/* webpackChunkName: "p-portal-portalphotospage" */ "@/pages/portal/PortalPhotosPage"));
const PortalVideosPage = React.lazy(() => import(/* webpackChunkName: "p-portal-portalvideospage" */ "@/pages/portal/PortalVideosPage"));
const AppointmentsQueue = React.lazy(() => import(/* webpackChunkName: "p-admin-appointmentsqueue" */ "@/pages/admin/AppointmentsQueue"));
const AdminAssets = React.lazy(() => import(/* webpackChunkName: "p-admin-adminassets" */ "@/pages/admin/AdminAssets"));
const MyOnboarding = React.lazy(() => import(/* webpackChunkName: "p-onboarding-employeeonboarding" */ "@/pages/onboarding/EmployeeOnboarding"));
const OnboardingTemplates = React.lazy(() => import(/* webpackChunkName: "p-onboarding-employeeonboarding" */ "@/pages/onboarding/EmployeeOnboarding").then(m => ({ default: m.OnboardingTemplates })));
const OnboardingQueue = React.lazy(() => import(/* webpackChunkName: "p-onboarding-employeeonboarding" */ "@/pages/onboarding/EmployeeOnboarding").then(m => ({ default: m.OnboardingQueue })));
const ReferralAnalyticsV2 = React.lazy(() => import(/* webpackChunkName: "p-admin-referralinsights" */ "@/pages/admin/ReferralInsights"));
const ReferralTiers = React.lazy(() => import(/* webpackChunkName: "p-admin-referralinsights" */ "@/pages/admin/ReferralInsights").then(m => ({ default: m.ReferralTiers })));
const SeoAudits = React.lazy(() => import(/* webpackChunkName: "p-seo-seoaudits" */ "@/pages/seo/SeoAudits"));
const SeoAuditDetail = React.lazy(() => import(/* webpackChunkName: "p-seo-seoaudits" */ "@/pages/seo/SeoAudits").then(m => ({ default: m.SeoAuditDetail })));
const ContentScorer = React.lazy(() => import(/* webpackChunkName: "p-seo-contentscorer" */ "@/pages/seo/ContentScorer"));
const RankHeatmap = React.lazy(() => import(/* webpackChunkName: "p-seo-rankheatmap" */ "@/pages/seo/RankHeatmap"));
const TopicalMap = React.lazy(() => import(/* webpackChunkName: "p-seo-topicalmap" */ "@/pages/seo/TopicalMap"));
const LlmVisibility = React.lazy(() => import(/* webpackChunkName: "p-seo-llmvisibility" */ "@/pages/seo/LlmVisibility"));
const AtlasAgent = React.lazy(() => import(/* webpackChunkName: "p-seo-atlasagent" */ "@/pages/seo/AtlasAgent"));
const OttoAutoFix = React.lazy(() => import(/* webpackChunkName: "p-seo-ottoautofix" */ "@/pages/seo/OttoAutoFix"));
const WebsiteStudio = React.lazy(() => import(/* webpackChunkName: "p-seo-websitestudio" */ "@/pages/seo/WebsiteStudio"));
const WebsiteStudioEditor = React.lazy(() => import(/* webpackChunkName: "p-seo-websitestudio" */ "@/pages/seo/WebsiteStudio").then(m => ({ default: m.WebsiteStudioEditor })));
const WhiteLabelReports = React.lazy(() => import(/* webpackChunkName: "p-seo-whitelabelreports" */ "@/pages/seo/WhiteLabelReports"));
const WhiteLabelReportDetail = React.lazy(() => import(/* webpackChunkName: "p-seo-whitelabelreports" */ "@/pages/seo/WhiteLabelReports").then(m => ({ default: m.WhiteLabelReportDetail })));
const EstimatorList = React.lazy(() => import(/* webpackChunkName: "p-estimator-estimatorpages" */ "@/pages/estimator/EstimatorPages"));
const EstimatorNew = React.lazy(() => import(/* webpackChunkName: "p-estimator-estimatorpages" */ "@/pages/estimator/EstimatorPages").then(m => ({ default: m.EstimatorNew })));
const EstimatorDetail = React.lazy(() => import(/* webpackChunkName: "p-estimator-estimatorpages" */ "@/pages/estimator/EstimatorPages").then(m => ({ default: m.EstimatorDetail })));
const EstimatorRates = React.lazy(() => import(/* webpackChunkName: "p-estimator-estimatorpages" */ "@/pages/estimator/EstimatorPages").then(m => ({ default: m.EstimatorRates })));
const DunningSettings = React.lazy(() => import(/* webpackChunkName: "p-dunning-dunningpages" */ "@/pages/dunning/DunningPages"));
const DunningQueue = React.lazy(() => import(/* webpackChunkName: "p-dunning-dunningpages" */ "@/pages/dunning/DunningPages").then(m => ({ default: m.DunningQueue })));
const DunningAnalytics = React.lazy(() => import(/* webpackChunkName: "p-dunning-dunningpages" */ "@/pages/dunning/DunningPages").then(m => ({ default: m.DunningAnalytics })));
const InventoryList = React.lazy(() => import(/* webpackChunkName: "p-inventory-inventorypages" */ "@/pages/inventory/InventoryPages"));
const InventoryDetail = React.lazy(() => import(/* webpackChunkName: "p-inventory-inventorypages" */ "@/pages/inventory/InventoryPages").then(m => ({ default: m.InventoryDetail })));
const InventoryPOs = React.lazy(() => import(/* webpackChunkName: "p-inventory-inventorypages" */ "@/pages/inventory/InventoryPages").then(m => ({ default: m.InventoryPOs })));
const InventoryAlerts = React.lazy(() => import(/* webpackChunkName: "p-inventory-inventorypages" */ "@/pages/inventory/InventoryPages").then(m => ({ default: m.InventoryAlerts })));
const InventoryAnalytics = React.lazy(() => import(/* webpackChunkName: "p-inventory-inventorypages" */ "@/pages/inventory/InventoryPages").then(m => ({ default: m.InventoryAnalytics })));
// Phase 18 · Feb-2026 — Chemical Cost Report (Admin+ only).
const ChemicalCostReport = React.lazy(() => import(/* webpackChunkName: "p-inventory-chemicalcostreport" */ "@/pages/inventory/ChemicalCostReport"));
const CheckRegister = React.lazy(() => import(/* webpackChunkName: "p-checks-checkspages" */ "@/pages/checks/ChecksPages"));
const CheckNew = React.lazy(() => import(/* webpackChunkName: "p-checks-checkspages" */ "@/pages/checks/ChecksPages").then(m => ({ default: m.CheckNew })));
const CheckDetail = React.lazy(() => import(/* webpackChunkName: "p-checks-checkspages" */ "@/pages/checks/ChecksPages").then(m => ({ default: m.CheckDetail })));
const CheckBanks = React.lazy(() => import(/* webpackChunkName: "p-checks-checkspages" */ "@/pages/checks/ChecksPages").then(m => ({ default: m.CheckBanks })));
const CheckPayees = React.lazy(() => import(/* webpackChunkName: "p-checks-checkspages" */ "@/pages/checks/ChecksPages").then(m => ({ default: m.CheckPayees })));
const CheckAnalytics = React.lazy(() => import(/* webpackChunkName: "p-checks-checkspages" */ "@/pages/checks/ChecksPages").then(m => ({ default: m.CheckAnalytics })));
const PropertyLookupPage = React.lazy(() => import(/* webpackChunkName: "p-property-lookup-propertylookuppage" */ "@/pages/property-lookup/PropertyLookupPage"));
const DispatchBoard = React.lazy(() => import(/* webpackChunkName: "p-dispatch-dispatchpages" */ "@/pages/dispatch/DispatchPages"));
const WeatherReschedule = React.lazy(() => import(/* webpackChunkName: "p-dispatch-dispatchpages" */ "@/pages/dispatch/DispatchPages").then(m => ({ default: m.WeatherReschedule })));
// Phase 17 · Feb 2026 — Google Maps + Directions redesigned dispatch board.
const DispatchBoardPage = React.lazy(() => import(/* webpackChunkName: "p-dispatch-dispatchboardpage" */ "@/pages/dispatch/DispatchBoardPage"));
// Feb-2026 · P1 diagnostic — wrap DispatchBoardPage in an ErrorBoundary
// so mobile crashes surface a friendly panel instead of a blank screen,
// and get reported to /api/client-errors for admin review.
import DispatchErrorBoundary from "@/components/errors/DispatchErrorBoundary";
const AdminDiagnosticsErrorsPage = React.lazy(() => import(/* webpackChunkName: "p-admin-admindiagnosticserrorspage" */ "@/pages/admin/AdminDiagnosticsErrorsPage"));
const DriverActivityPage = React.lazy(() => import(/* webpackChunkName: "p-admin-driveractivitypage" */ "@/pages/admin/DriverActivityPage"));
const ModerationCheckinsPage = React.lazy(() => import(/* webpackChunkName: "p-admin-moderationcheckinspage" */ "@/pages/admin/ModerationCheckinsPage"));
const SeoAuditorPage = React.lazy(() => import(/* webpackChunkName: "p-admin-seoauditorpage" */ "@/pages/admin/SeoAuditorPage"));
const AEOPage = React.lazy(() => import(/* webpackChunkName: "p-admin-aeopage" */ "@/pages/admin/AEOPage"));
const WeeklyDigestPage = React.lazy(() => import(/* webpackChunkName: "p-admin-weeklydigestpage" */ "@/pages/admin/WeeklyDigestPage"));
const AEODigestPage = React.lazy(() => import(/* webpackChunkName: "p-admin-aeodigestpage" */ "@/pages/admin/AEODigestPage"));
const ProspectsKanbanPage = React.lazy(() => import(/* webpackChunkName: "p-admin-outreach-prospectskanbanpage" */ "@/pages/admin/outreach/ProspectsKanbanPage"));
const OutreachTemplatesPage = React.lazy(() => import(/* webpackChunkName: "p-admin-outreach-templatespage" */ "@/pages/admin/outreach/TemplatesPage"));
const KeywordIdeatorPage = React.lazy(() => import(/* webpackChunkName: "p-admin-keywordideatorpage" */ "@/pages/admin/KeywordIdeatorPage"));
const GpsUsersPage = React.lazy(() => import(/* webpackChunkName: "p-admin-gpsuserspage" */ "@/pages/admin/GpsUsersPage"));
// Phase G5a · Feb-2026 — Geofences + crossings inbox.
const GeofencesPage = React.lazy(() => import(/* webpackChunkName: "p-admin-geofencespage" */ "@/pages/admin/GeofencesPage"));
const CrossingsInbox = React.lazy(() => import(/* webpackChunkName: "p-admin-crossingsinbox" */ "@/pages/admin/CrossingsInbox"));
// Phase G5b · Feb-2026 — Stop → Job attribution report.
const TimeOnSitePage = React.lazy(() => import(/* webpackChunkName: "p-admin-timeonsitepage" */ "@/pages/admin/TimeOnSitePage"));
// Phase G5d · Feb-2026 — Driver Scorecard / Leaderboard.
const DriverScorecardPage = React.lazy(() => import(/* webpackChunkName: "p-admin-driverscorecardpage" */ "@/pages/admin/DriverScorecardPage"));
const WidgetEmbedPage = React.lazy(() => import(/* webpackChunkName: "p-admin-widgetembedpage" */ "@/pages/admin/WidgetEmbedPage"));
// MR3 · Feb-2026 — Public widget analytics.
const WidgetAnalyticsPage = React.lazy(() => import(/* webpackChunkName: "p-admin-widgetanalyticspage" */ "@/pages/admin/WidgetAnalyticsPage"));
// Phase 2 · Feb-2026 (REWORKED) — Admin-only shared Route Replay viewer.
const AdminSharedReplayPage = React.lazy(() => import(/* webpackChunkName: "p-admin-adminsharedreplaypage" */ "@/pages/admin/AdminSharedReplayPage"));
const CheckBatchNew = React.lazy(() => import(/* webpackChunkName: "p-checks-checkbatchpages" */ "@/pages/checks/CheckBatchPages"));
const CheckPayrollImport = React.lazy(() => import(/* webpackChunkName: "p-checks-checkbatchpages" */ "@/pages/checks/CheckBatchPages").then(m => ({ default: m.CheckPayrollImport })));
const ChurnDashboard = React.lazy(() => import(/* webpackChunkName: "p-customer-success-churnpages" */ "@/pages/customer-success/ChurnPages"));
const ContentRefresh = React.lazy(() => import(/* webpackChunkName: "p-customer-success-churnpages" */ "@/pages/customer-success/ChurnPages").then(m => ({ default: m.ContentRefresh })));
// Feb-2026 · Import collision fix — the OLD PortalWarranties export
// inside WarrantyPages.jsx has been superseded by the read-only
// customer portal implementation at ``@/pages/portal/PortalWarranties``.
// Drop it from this named-import list so it doesn't clash with the
// default import from the portal module (see line ~361).
const WarrantyPlans = React.lazy(() => import(/* webpackChunkName: "p-warranties-warrantypages" */ "@/pages/warranties/WarrantyPages"));
const WarrantyContracts = React.lazy(() => import(/* webpackChunkName: "p-warranties-warrantypages" */ "@/pages/warranties/WarrantyPages").then(m => ({ default: m.WarrantyContracts })));
const WarrantyClaims = React.lazy(() => import(/* webpackChunkName: "p-warranties-warrantypages" */ "@/pages/warranties/WarrantyPages").then(m => ({ default: m.WarrantyClaims })));
const TermsSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-terms" */ "@/pages/settings/Terms"));
const LegalDocsList = React.lazy(() => import(/* webpackChunkName: "p-settings-legaldocs" */ "@/pages/settings/LegalDocs").then(m => ({ default: m.LegalDocsList })));
const LegalDocEditor = React.lazy(() => import(/* webpackChunkName: "p-settings-legaldocs" */ "@/pages/settings/LegalDocs").then(m => ({ default: m.LegalDocEditor })));
// Feb-2026 · Slice 2B — Multi-ToS admin editor (Pool + Landscaping).
const TosAdminEditor = React.lazy(() => import(/* webpackChunkName: "p-settings-tosadmineditor" */ "@/pages/settings/TosAdminEditor"));
const IntegrationsHub = React.lazy(() => import(/* webpackChunkName: "p-settings-integrationspages" */ "@/pages/settings/IntegrationsPages").then(m => ({ default: m.IntegrationsHub })));
const MapSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-integrationspages" */ "@/pages/settings/IntegrationsPages").then(m => ({ default: m.MapSettings })));
// Feb-2026 · K55.a — SuperCool + HomeWorks integration surfaces
// removed as part of the sunset.  Historical DB data (per-doc
// ``homeworks_*`` audit fields + ``db.mcp_oauth_tokens`` where
// ``provider="supercool"``) is preserved intact.  See
// /app/memory/PHASE_K55_a_FRONTEND_REMOVAL.md.
// Feb-2026 · Item 3 — Deletions audit page (super_admin only).
const DeletionsAuditPage = React.lazy(() => import(/* webpackChunkName: "p-admin-audit-deletionsauditpage" */ "@/pages/admin/audit/DeletionsAuditPage"));
// Feb-2026 · Admin migrations dashboard (super_admin only) — driver
// for one-off backfills (P19 empty-lead enrichment initially).
const AdminMigrationsPage = React.lazy(() => import(/* webpackChunkName: "p-admin-adminmigrationspage" */ "@/pages/admin/AdminMigrationsPage"));
// Phase H6 · Feb-2026 — Monthly analytics rollup dashboard.
const AnalyticsMonthlyPage = React.lazy(() => import(/* webpackChunkName: "p-admin-analyticsmonthlypage" */ "@/pages/admin/AnalyticsMonthlyPage"));
const PortalTerms = React.lazy(() => import(/* webpackChunkName: "p-portal-portalterms" */ "@/pages/portal/PortalTerms"));
const MarketingHub = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.MarketingHub })));
const BrandMemory = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.BrandMemory })));
const Posts = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.Posts })));
const ApprovalQueue = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.ApprovalQueue })));
const ContentCalendar = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.ContentCalendar })));
const SchedulingConfig = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.SchedulingConfig })));
const Performance = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.Performance })));
const TemplatesHub = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.TemplatesHub })));
const Reviews = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingpages" */ "@/pages/marketing/MarketingPages").then(m => ({ default: m.Reviews })));
// M2 UI — new Campaigns experience overrides the legacy placeholders
// from MarketingPages.jsx. Routes below (/marketing/campaigns*) point
// at these.
const CampaignsList = React.lazy(() => import(/* webpackChunkName: "p-marketing-m2campaigns" */ "@/pages/marketing/M2Campaigns").then(m => ({ default: m.CampaignsList })));
const CampaignNew = React.lazy(() => import(/* webpackChunkName: "p-marketing-m2campaigns" */ "@/pages/marketing/M2Campaigns").then(m => ({ default: m.CampaignNew })));
const CampaignDetail = React.lazy(() => import(/* webpackChunkName: "p-marketing-m2campaigns" */ "@/pages/marketing/M2Campaigns").then(m => ({ default: m.CampaignDetail })));
const BeforeAfterStudio = React.lazy(() => import(/* webpackChunkName: "p-marketing-beforeafterstudio" */ "@/pages/marketing/BeforeAfterStudio"));
const DirectoriesHub = React.lazy(() => import(/* webpackChunkName: "p-marketing-directories-directorieshub" */ "@/pages/marketing/directories/DirectoriesHub"));
const NapProfilePage = React.lazy(() => import(/* webpackChunkName: "p-marketing-directories-napprofilepage" */ "@/pages/marketing/directories/NapProfilePage"));
const DirectorySubmissionsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-directories-directorysubmissionspage" */ "@/pages/marketing/directories/DirectorySubmissionsPage"));
const AutopilotPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-autopilotpage" */ "@/pages/marketing/AutopilotPage"));
const InstaQuoteAdminPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-instaquoteadmin" */ "@/pages/marketing/InstaQuoteAdmin"));
const PublicInstaQuotePage = React.lazy(() => import(/* webpackChunkName: "p-public-publicinstaquote" */ "@/pages/public/PublicInstaQuote"));
const InstaScheduleAdminPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-instascheduleadmin" */ "@/pages/marketing/InstaScheduleAdmin"));
const PublicInstaSchedulePage = React.lazy(() => import(/* webpackChunkName: "p-public-publicinstaschedule" */ "@/pages/public/PublicInstaSchedule"));
const PublicInvoicePay = React.lazy(() => import(/* webpackChunkName: "p-public-publicinvoicepay" */ "@/pages/public/PublicInvoicePay"));
// Feb-2026 · Task 3 · Invoices bypass portal — new magic-link
// route `/i/:token` renders the full itemized InvoiceView with an
// inline Pay Now button. Coexists with `/pay/invoice/:id?token=…`
// (kept as backwards-compat alias for older emails).
const PublicInvoiceMagic = React.lazy(() => import(/* webpackChunkName: "p-public-publicinvoicemagic" */ "@/pages/public/PublicInvoiceMagic"));
// Phase 22 · Feb 2026 — Public Service Images portal (no auth).
const ServiceImagesPortalPage = React.lazy(() => import(/* webpackChunkName: "p-public-serviceimagesportalpage" */ "@/pages/public/ServiceImagesPortalPage"));
// Phase 47c (Feb 2026) — /portal/add-card RESTORED as a direct-Stripe
// magic-link flow (Elements + SetupIntent). Un-does the Phase LZ4
// retirement now that the user has directed every payment surface to
// route through Stripe directly (no Lumino / Zapier).
const AddCardPage = React.lazy(() => import(/* webpackChunkName: "p-public-addcardpage" */ "@/pages/public/AddCardPage"));
const TeamChatPage = React.lazy(() => import(/* webpackChunkName: "p-chat-teamchatpage" */ "@/pages/chat/TeamChatPage"));
const Walkie = React.lazy(() => import(/* webpackChunkName: "p-walkie-walkie" */ "@/pages/walkie/Walkie"));
const SequencesList = React.lazy(() => import(/* webpackChunkName: "p-marketing-sequencepages" */ "@/pages/marketing/SequencePages").then(m => ({ default: m.SequencesList })));
const SequenceNew = React.lazy(() => import(/* webpackChunkName: "p-marketing-sequencepages" */ "@/pages/marketing/SequencePages").then(m => ({ default: m.SequenceNew })));
const SequenceDetail = React.lazy(() => import(/* webpackChunkName: "p-marketing-sequencepages" */ "@/pages/marketing/SequencePages").then(m => ({ default: m.SequenceDetail })));
const SeoHub = React.lazy(() => import(/* webpackChunkName: "p-seo-seopages" */ "@/pages/seo/SeoPages").then(m => ({ default: m.SeoHub })));
const ArticlesList = React.lazy(() => import(/* webpackChunkName: "p-seo-seopages" */ "@/pages/seo/SeoPages").then(m => ({ default: m.ArticlesList })));
const ArticleEditor = React.lazy(() => import(/* webpackChunkName: "p-seo-seopages" */ "@/pages/seo/SeoPages").then(m => ({ default: m.ArticleEditor })));
const KeywordSuggest = React.lazy(() => import(/* webpackChunkName: "p-seo-seopages" */ "@/pages/seo/SeoPages").then(m => ({ default: m.KeywordSuggest })));
const SeoAudit = React.lazy(() => import(/* webpackChunkName: "p-seo-seopages" */ "@/pages/seo/SeoPages").then(m => ({ default: m.SeoAudit })));
const RankGrid = React.lazy(() => import(/* webpackChunkName: "p-seo-seopages" */ "@/pages/seo/SeoPages").then(m => ({ default: m.RankGrid })));
const WordPressSettings = React.lazy(() => import(/* webpackChunkName: "p-seo-seopages" */ "@/pages/seo/SeoPages").then(m => ({ default: m.WordPressSettings })));
const GbpHub = React.lazy(() => import(/* webpackChunkName: "p-seo-seopages" */ "@/pages/seo/SeoPages").then(m => ({ default: m.GbpHub })));
const AiEmployeesList = React.lazy(() => import(/* webpackChunkName: "p-aiops-aiopspages" */ "@/pages/aiops/AiOpsPages").then(m => ({ default: m.AiEmployeesList })));
const AiEmployeeDetail = React.lazy(() => import(/* webpackChunkName: "p-aiops-aiopspages" */ "@/pages/aiops/AiOpsPages").then(m => ({ default: m.AiEmployeeDetail })));
const TasksPage = React.lazy(() => import(/* webpackChunkName: "p-aiops-aiopspages" */ "@/pages/aiops/AiOpsPages").then(m => ({ default: m.TasksPage })));
const AccessSettings = React.lazy(() => import(/* webpackChunkName: "p-aiops-aiopspages" */ "@/pages/aiops/AiOpsPages").then(m => ({ default: m.AccessSettings })));
const AccessHistory = React.lazy(() => import(/* webpackChunkName: "p-aiops-aiopspages" */ "@/pages/aiops/AiOpsPages").then(m => ({ default: m.AccessHistory })));
const RingCentralSettings = React.lazy(() => import(/* webpackChunkName: "p-aiops-aiopspages" */ "@/pages/aiops/AiOpsPages").then(m => ({ default: m.RingCentralSettings })));
const CallLogsPage = React.lazy(() => import(/* webpackChunkName: "p-aiops-aiopspages" */ "@/pages/aiops/AiOpsPages").then(m => ({ default: m.CallLogsPage })));
// Phase S2 · Feb-2026 — Soshie Hub (Brand Brain + Autopilot + Review Queue).
const SoshieHub = React.lazy(() => import(/* webpackChunkName: "p-soshie-soshiehub" */ "@/pages/soshie/SoshieHub"));
// Phase 11 · Feb 2026 — Equipment Service Trackers (Filter & Salt Cell).
const FilterTrackerListPage = React.lazy(() => import(/* webpackChunkName: "p-tracking-equipmenttrackerpages" */ "@/pages/tracking/EquipmentTrackerPages").then(m => ({ default: m.FilterTrackerListPage })));
const FilterTrackerManagePage = React.lazy(() => import(/* webpackChunkName: "p-tracking-equipmenttrackerpages" */ "@/pages/tracking/EquipmentTrackerPages").then(m => ({ default: m.FilterTrackerManagePage })));
const SaltCellTrackerListPage = React.lazy(() => import(/* webpackChunkName: "p-tracking-equipmenttrackerpages" */ "@/pages/tracking/EquipmentTrackerPages").then(m => ({ default: m.SaltCellTrackerListPage })));
const SaltCellTrackerManagePage = React.lazy(() => import(/* webpackChunkName: "p-tracking-equipmenttrackerpages" */ "@/pages/tracking/EquipmentTrackerPages").then(m => ({ default: m.SaltCellTrackerManagePage })));
const NotificationsPage = React.lazy(() => import(/* webpackChunkName: "p-notifications-notificationspage" */ "@/pages/notifications/NotificationsPage"));
const NotificationPrefs = React.lazy(() => import(/* webpackChunkName: "p-settings-notificationprefs" */ "@/pages/settings/NotificationPrefs"));
const LeadAlertsSettings = React.lazy(() => import(/* webpackChunkName: "p-settings-leadalertssettings" */ "@/pages/settings/LeadAlertsSettings"));
// StripeReconciliation page removed in Phase LZ4 (Feb 2026);
// Stripe SDK is retired. Import + route deleted.
const D2dDashboard = React.lazy(() => import(/* webpackChunkName: "p-d2d-d2dpages" */ "@/pages/d2d/D2dPages").then(m => ({ default: m.D2dDashboard })));
const D2dMap = React.lazy(() => import(/* webpackChunkName: "p-d2d-d2dpages" */ "@/pages/d2d/D2dPages").then(m => ({ default: m.D2dMap })));
const D2dKnocks = React.lazy(() => import(/* webpackChunkName: "p-d2d-d2dpages" */ "@/pages/d2d/D2dPages").then(m => ({ default: m.D2dKnocks })));
const D2dOpenLeads = React.lazy(() => import(/* webpackChunkName: "p-d2d-d2dpages" */ "@/pages/d2d/D2dPages").then(m => ({ default: m.D2dOpenLeads })));
const D2dSoldLeads = React.lazy(() => import(/* webpackChunkName: "p-d2d-d2dpages" */ "@/pages/d2d/D2dPages").then(m => ({ default: m.D2dSoldLeads })));
const D2dReport = React.lazy(() => import(/* webpackChunkName: "p-d2d-d2dpages" */ "@/pages/d2d/D2dPages").then(m => ({ default: m.D2dReport })));
const D2dLeaderboard = React.lazy(() => import(/* webpackChunkName: "p-d2d-d2dpages" */ "@/pages/d2d/D2dPages").then(m => ({ default: m.D2dLeaderboard })));
const DispatchMap = React.lazy(() => import(/* webpackChunkName: "p-ops-mappages" */ "@/pages/ops/MapPages").then(m => ({ default: m.DispatchMap })));
const ScheduleMap = React.lazy(() => import(/* webpackChunkName: "p-ops-mappages" */ "@/pages/ops/MapPages").then(m => ({ default: m.ScheduleMap })));
const NotFound = React.lazy(() => import(/* webpackChunkName: "p-notfound" */ "@/pages/NotFound"));
const CheckinsList = React.lazy(() => import(/* webpackChunkName: "p-misc-gapclosures" */ "@/pages/misc/GapClosures").then(m => ({ default: m.CheckinsList })));
const CommunicationThread = React.lazy(() => import(/* webpackChunkName: "p-phase14-phase14pages" */ "@/pages/phase14/Phase14Pages").then(m => ({ default: m.CommunicationThread })));
const TechnicianProfile = React.lazy(() => import(/* webpackChunkName: "p-phase14-phase14pages" */ "@/pages/phase14/Phase14Pages").then(m => ({ default: m.TechnicianProfile })));
const FormsList = React.lazy(() => import(/* webpackChunkName: "p-phase14-phase14pages" */ "@/pages/phase14/Phase14Pages").then(m => ({ default: m.FormsList })));
const FormEditor = React.lazy(() => import(/* webpackChunkName: "p-phase14-phase14pages" */ "@/pages/phase14/Phase14Pages").then(m => ({ default: m.FormEditor })));
const PublicForm = React.lazy(() => import(/* webpackChunkName: "p-phase14-phase14pages" */ "@/pages/phase14/Phase14Pages").then(m => ({ default: m.PublicForm })));
import { PermissionsProvider } from "@/hooks/usePermissions";
const LandscapeAI = React.lazy(() => import(/* webpackChunkName: "p-aitools-aitoolspages" */ "@/pages/aitools/AiToolsPages").then(m => ({ default: m.LandscapeAI })));
const CadList = React.lazy(() => import(/* webpackChunkName: "p-aitools-aitoolspages" */ "@/pages/aitools/AiToolsPages").then(m => ({ default: m.CadList })));
const CadEditor = React.lazy(() => import(/* webpackChunkName: "p-aitools-aitoolspages" */ "@/pages/aitools/AiToolsPages").then(m => ({ default: m.CadEditor })));
const SatelliteMeasure = React.lazy(() => import(/* webpackChunkName: "p-aitools-aitoolspages" */ "@/pages/aitools/AiToolsPages").then(m => ({ default: m.SatelliteMeasure })));
const VirtualBid = React.lazy(() => import(/* webpackChunkName: "p-aitools-aitoolspages" */ "@/pages/aitools/AiToolsPages").then(m => ({ default: m.VirtualBid })));
const DigitalCardList = React.lazy(() => import(/* webpackChunkName: "p-aitools-aitoolspages" */ "@/pages/aitools/AiToolsPages").then(m => ({ default: m.DigitalCardList })));
const PublicCard = React.lazy(() => import(/* webpackChunkName: "p-aitools-aitoolspages" */ "@/pages/aitools/AiToolsPages").then(m => ({ default: m.PublicCard })));
const WeatherHub = React.lazy(() => import(/* webpackChunkName: "p-aitools-aitoolspages" */ "@/pages/aitools/AiToolsPages").then(m => ({ default: m.WeatherHub })));
const EstimatesList = React.lazy(() => import(/* webpackChunkName: "p-estimator-estimator" */ "@/pages/estimator/Estimator").then(m => ({ default: m.EstimatesList })));
const EstimatorSettings = React.lazy(() => import(/* webpackChunkName: "p-estimator-estimator" */ "@/pages/estimator/Estimator").then(m => ({ default: m.EstimatorSettings })));
const EstimatorTemplates = React.lazy(() => import(/* webpackChunkName: "p-estimator-estimator" */ "@/pages/estimator/Estimator").then(m => ({ default: m.EstimatorTemplates })));
const EstimatorEditor = React.lazy(() => import(/* webpackChunkName: "p-estimator-estimator" */ "@/pages/estimator/Estimator").then(m => ({ default: m.EstimatorEditor })));
const OpsHub = React.lazy(() => import(/* webpackChunkName: "p-ops-opshub" */ "@/pages/ops/OpsHub"));
// Feb-2026 · Job Timers Phase 1 + Chemical Cost Report — fresh pages.
const JobTimersPage = React.lazy(() => import(/* webpackChunkName: "p-timers-jobtimerspage" */ "@/pages/timers/JobTimersPage"));
const ChemicalCostReportPage = React.lazy(() => import(/* webpackChunkName: "p-reports-chemicalcostreportpage" */ "@/pages/reports/ChemicalCostReportPage"));
const RepairCalculatorPage = React.lazy(() => import(/* webpackChunkName: "p-ops-repaircalculatorpage" */ "@/pages/ops/RepairCalculatorPage"));
const ReportsHub = React.lazy(() => import(/* webpackChunkName: "p-reports-reportshub" */ "@/pages/reports/ReportsHub"));
const ReportsSuite = React.lazy(() => import(/* webpackChunkName: "p-reports-reportssuite" */ "@/pages/reports/ReportsSuite"));
const BusinessSummary = React.lazy(() => import(/* webpackChunkName: "p-reports-businesssummary" */ "@/pages/reports/BusinessSummary"));
const BusinessSnapshot = React.lazy(() => import(/* webpackChunkName: "p-reports-businesssnapshot" */ "@/pages/reports/BusinessSnapshot"));
// Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B).
const AttritionReport = React.lazy(() => import(/* webpackChunkName: "p-reports-attritionreport" */ "@/pages/reports/AttritionReport"));
const TimeToGetPaidReport = React.lazy(() => import(/* webpackChunkName: "p-reports-timetogetpaidreport" */ "@/pages/reports/TimeToGetPaidReport"));
// Feb-2026 · Reports Gap Fill Phase 5a.2 — cockpit-mirror trio.
const RevenueByServiceReport = React.lazy(() => import(/* webpackChunkName: "p-reports-revenuebyservicereport" */ "@/pages/reports/RevenueByServiceReport"));
const RecurringVsProjectReport = React.lazy(() => import(/* webpackChunkName: "p-reports-recurringvsprojectreport" */ "@/pages/reports/RecurringVsProjectReport"));
const ClientLifetimeValueReport = React.lazy(() => import(/* webpackChunkName: "p-reports-clientlifetimevaluereport" */ "@/pages/reports/ClientLifetimeValueReport"));
// Feb-2026 · Reports Gap Fill Phase 5b.1 — Close Ratio + Time to Close.
const CloseRatioReport = React.lazy(() => import(/* webpackChunkName: "p-reports-closeratioreport" */ "@/pages/reports/CloseRatioReport"));
const TimeToCloseReport = React.lazy(() => import(/* webpackChunkName: "p-reports-timetoclosereport" */ "@/pages/reports/TimeToCloseReport"));
// Feb-2026 · Reports Gap Fill Phase 5b.2 — Labor Efficiency + Booked Out / Capacity.
const LaborEfficiencyReport = React.lazy(() => import(/* webpackChunkName: "p-reports-laborefficiencyreport" */ "@/pages/reports/LaborEfficiencyReport"));
const BookedOutCapacityReport = React.lazy(() => import(/* webpackChunkName: "p-reports-bookedoutcapacityreport" */ "@/pages/reports/BookedOutCapacityReport"));
const Forecast = React.lazy(() => import(/* webpackChunkName: "p-reports-forecast" */ "@/pages/reports/Forecast"));
const CustomerRetentionReport = React.lazy(() => import(/* webpackChunkName: "p-reports-customerretentionreport" */ "@/pages/reports/CustomerRetentionReport"));
const GpsAutoStartAudit = React.lazy(() => import(/* webpackChunkName: "p-reports-gpsautostartaudit" */ "@/pages/reports/GpsAutoStartAudit"));
const IncomeByCategory = React.lazy(() => import(/* webpackChunkName: "p-reports-incomebycategorypage" */ "@/pages/reports/IncomeByCategoryPage"));
const UncategorizedItemsReport = React.lazy(() => import(/* webpackChunkName: "p-reports-uncategorizeditemsreport" */ "@/pages/reports/UncategorizedItemsReport"));
const RevenueByCity = React.lazy(() => import(/* webpackChunkName: "p-reports-revenueslices" */ "@/pages/reports/RevenueSlices").then(m => ({ default: m.RevenueByCity })));
const RevenueByCrew = React.lazy(() => import(/* webpackChunkName: "p-reports-revenueslices" */ "@/pages/reports/RevenueSlices").then(m => ({ default: m.RevenueByCrew })));
const RevenueByCustomer = React.lazy(() => import(/* webpackChunkName: "p-reports-revenueslices" */ "@/pages/reports/RevenueSlices").then(m => ({ default: m.RevenueByCustomer })));
const GrossSales = React.lazy(() => import(/* webpackChunkName: "p-reports-revenueslices" */ "@/pages/reports/RevenueSlices").then(m => ({ default: m.GrossSales })));
const InvoicedItems = React.lazy(() => import(/* webpackChunkName: "p-reports-revenueslices" */ "@/pages/reports/RevenueSlices").then(m => ({ default: m.InvoicedItems })));
const PaymentsLedger = React.lazy(() => import(/* webpackChunkName: "p-finance-financepages" */ "@/pages/finance/FinancePages").then(m => ({ default: m.PaymentsLedger })));
const AutoBilling = React.lazy(() => import(/* webpackChunkName: "p-finance-financepages" */ "@/pages/finance/FinancePages").then(m => ({ default: m.AutoBilling })));
const ImpExp = React.lazy(() => import(/* webpackChunkName: "p-finance-financepages" */ "@/pages/finance/FinancePages").then(m => ({ default: m.ImpExp })));
const IncomeCategoriesCrud = React.lazy(() => import(/* webpackChunkName: "p-finance-financepages" */ "@/pages/finance/FinancePages").then(m => ({ default: m.IncomeCategoriesCrud })));
const AutobillingRuns = React.lazy(() => import(/* webpackChunkName: "p-finance-autobillingruns" */ "@/pages/finance/AutobillingRuns"));
const PortalHome = React.lazy(() => import(/* webpackChunkName: "p-portal-portalhome" */ "@/pages/portal/PortalHome"));
const PortalServices = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalServices })));
const PortalServiceDetail = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalServiceDetail })));
const PortalInvoices = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalInvoices })));
const PortalInvoiceDetail = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalInvoiceDetail })));
const PortalEstimates = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalEstimates })));
const PortalEstimateDetail = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalEstimateDetail })));
const PortalPayments = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalPayments })));
const PortalPaymentMethod = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalPaymentMethod })));
const PortalDocuments = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalDocuments })));
const PortalMessages = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalMessages })));
const PortalProfile = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalProfile })));
const PortalRequestService = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalRequestService })));
const PortalPaymentComplete = React.lazy(() => import(/* webpackChunkName: "p-portal-portalpages" */ "@/pages/portal/PortalPages").then(m => ({ default: m.PortalPaymentComplete })));
const PortalWarranties = React.lazy(() => import(/* webpackChunkName: "p-portal-portalwarranties" */ "@/pages/portal/PortalWarranties"));
const PortalServiceReports = React.lazy(() => import(/* webpackChunkName: "p-portal-portalservicereports" */ "@/pages/portal/PortalServiceReports").then(m => ({ default: m.PortalServiceReports })));
const PortalServiceReportDetail = React.lazy(() => import(/* webpackChunkName: "p-portal-portalservicereports" */ "@/pages/portal/PortalServiceReports").then(m => ({ default: m.PortalServiceReportDetail })));
const PortalSignPage = React.lazy(() => import(/* webpackChunkName: "p-portal-portalsign" */ "@/pages/portal/PortalSign"));
const CsatDashboard = React.lazy(() => import(/* webpackChunkName: "p-csat-csatpages" */ "@/pages/csat/CsatPages").then(m => ({ default: m.CsatDashboard })));
const CsatDetail = React.lazy(() => import(/* webpackChunkName: "p-csat-csatpages" */ "@/pages/csat/CsatPages").then(m => ({ default: m.CsatDetail })));
const PublicCsat = React.lazy(() => import(/* webpackChunkName: "p-csat-csatpages" */ "@/pages/csat/CsatPages").then(m => ({ default: m.PublicCsat })));
import { RealtimeProvider } from "@/realtime/NotificationSocket";
const AnalyticsPage = React.lazy(() => import(/* webpackChunkName: "p-analytics-analyticspage" */ "@/pages/analytics/AnalyticsPage"));
import OnboardingPage from '@/pages/onboarding/OnboardingPage';
const LeadRequestPage = React.lazy(() => import(/* webpackChunkName: "p-leads-leadrequestpage" */ "@/pages/leads/LeadRequestPage"));
const LeadDetail = React.lazy(() => import(/* webpackChunkName: "p-leads-leaddetail" */ "@/pages/leads/LeadDetail"));
const PublicLeadIntake = React.lazy(() => import(/* webpackChunkName: "p-public-publicleadintake" */ "@/pages/public/PublicLeadIntake"));
const PublicLeadRequestPage = React.lazy(() => import(/* webpackChunkName: "p-public-publicleadrequest" */ "@/pages/public/PublicLeadRequest"));
const WidgetDemoPage = React.lazy(() => import(/* webpackChunkName: "p-widget-widgetdemopage" */ "@/pages/widget/WidgetDemoPage"));
const MarketingFormsPage = React.lazy(() => import(/* webpackChunkName: "p-marketing-marketingformspage" */ "@/pages/marketing/MarketingFormsPage"));
const LeadsDashboardPage = React.lazy(() => import(/* webpackChunkName: "p-leads-leadsdashboardpage" */ "@/pages/leads/LeadsDashboardPage"));
const TenantsAdminPage = React.lazy(() => import(/* webpackChunkName: "p-tenants-tenantsadminpage" */ "@/pages/tenants/TenantsAdminPage"));
const TenantBrandSettings = React.lazy(() => import(/* webpackChunkName: "p-tenants-tenantsadminpage" */ "@/pages/tenants/TenantsAdminPage").then(m => ({ default: m.TenantBrandSettings })));
import {
  TimesheetsPage as WorkforceTimesheets, CrewMapPage as WorkforceCrewMap,
  JobCostingPage as WorkforceJobCosting, MileagePage as WorkforceMileage,
} from "@/pages/workforce/WorkforcePages";
import {
  BusinessOSLayout, OverviewPage as OsOverview, SopsPage as OsSops,
  RolesPage as OsRoles, ScorecardsPage as OsScorecards, HuddlesPage as OsHuddles,
  LeanboardsPage as OsLeanboards, SprintsPage as OsSprints,
} from "@/pages/os/BusinessOS";
const OsLana = React.lazy(() => import(/* webpackChunkName: "p-os-lanaandplans" */ "@/pages/os/LanaAndPlans").then(m => ({ default: m.LanaChatPage })));
const TodaySchedule = React.lazy(() => import(/* webpackChunkName: "p-schedule-todayschedule" */ "@/pages/schedule/TodaySchedule"));
const TechHuddlePage = React.lazy(() => import(/* webpackChunkName: "p-tech-techpages" */ "@/pages/tech/TechPages").then(m => ({ default: m.TechHuddlePage })));
const TechTimeClockPage = React.lazy(() => import(/* webpackChunkName: "p-tech-techpages" */ "@/pages/tech/TechPages").then(m => ({ default: m.TechTimeClockPage })));
const ServiceReport = React.lazy(() => import(/* webpackChunkName: "p-tech-servicereport" */ "@/pages/tech/ServiceReport"));
const ToolsHub = React.lazy(() => import(/* webpackChunkName: "p-tech-toolshub" */ "@/pages/tech/ToolsHub"));
const ComingSoonPage = React.lazy(() => import(/* webpackChunkName: "p-common-comingsoonpage" */ "@/pages/common/ComingSoonPage"));
const PoolCalculators = React.lazy(() => import(/* webpackChunkName: "p-tech-poolcalculators" */ "@/pages/tech/PoolCalculators"));
const BusinessPricingTools = React.lazy(() => import(/* webpackChunkName: "p-admin-businesspricingtools" */ "@/pages/admin/BusinessPricingTools"));
const BusinessAnalysisTools = React.lazy(() => import(/* webpackChunkName: "p-admin-businessanalysistools" */ "@/pages/admin/BusinessAnalysisTools"));
const DocumentGenerators = React.lazy(() => import(/* webpackChunkName: "p-admin-documentgenerators" */ "@/pages/admin/DocumentGenerators"));
const ServicePriceChecker = React.lazy(() => import(/* webpackChunkName: "p-admin-servicepricechecker" */ "@/pages/admin/ServicePriceChecker"));
const PricingDefaultsEditor = React.lazy(() => import(/* webpackChunkName: "p-admin-pricingdefaultseditor" */ "@/pages/admin/PricingDefaultsEditor"));
const BusinessCard = React.lazy(() => import(/* webpackChunkName: "p-tech-businesscard" */ "@/pages/tech/BusinessCard"));
const LandscapingTimeClock = React.lazy(() => import(/* webpackChunkName: "p-tech-landscapingtimeclock" */ "@/pages/tech/LandscapingTimeClock"));
const PoolServiceReport = React.lazy(() => import(/* webpackChunkName: "p-reports-poolservicereport" */ "@/pages/reports/PoolServiceReport"));
const JobMarginLeaderboard = React.lazy(() => import(/* webpackChunkName: "p-admin-jobmarginleaderboard" */ "@/pages/admin/JobMarginLeaderboard"));
const ChemicalCosts = React.lazy(() => import(/* webpackChunkName: "p-admin-chemicalcosts" */ "@/pages/admin/ChemicalCosts"));
const RecurringJobs = React.lazy(() => import(/* webpackChunkName: "p-admin-recurringjobs" */ "@/pages/admin/RecurringJobs"));
const CFOReports = React.lazy(() => import(/* webpackChunkName: "p-admin-cforeports" */ "@/pages/admin/CFOReports"));
const VendorBills = React.lazy(() => import(/* webpackChunkName: "p-admin-vendorbills" */ "@/pages/admin/VendorBills"));
const PricingInsights = React.lazy(() => import(/* webpackChunkName: "p-admin-pricinginsights" */ "@/pages/admin/PricingInsights"));
const RingCentralAdmin = React.lazy(() => import(/* webpackChunkName: "p-admin-ringcentraladmin" */ "@/pages/admin/RingCentralAdmin"));
const TelephonyPage = React.lazy(() => import(/* webpackChunkName: "p-settings-telephonypage" */ "@/pages/settings/TelephonyPage"));
const TrainingList = React.lazy(() => import(/* webpackChunkName: "p-training-traininglist" */ "@/pages/training/TrainingList"));
const TrainingModuleDetail = React.lazy(() => import(/* webpackChunkName: "p-training-trainingmoduledetail" */ "@/pages/training/TrainingModuleDetail"));
const TrainingQuiz = React.lazy(() => import(/* webpackChunkName: "p-training-trainingquiz" */ "@/pages/training/TrainingQuiz"));
const AdminTraining = React.lazy(() => import(/* webpackChunkName: "p-training-admintraining" */ "@/pages/training/AdminTraining"));
const BudgetSetup = React.lazy(() => import(/* webpackChunkName: "p-budget-budgetsetup" */ "@/pages/budget/BudgetSetup"));
const BudgetDashboard = React.lazy(() => import(/* webpackChunkName: "p-budget-budgetdashboard" */ "@/pages/budget/BudgetDashboard"));
const BudgetWizard = React.lazy(() => import(/* webpackChunkName: "p-budget-budgetwizard" */ "@/pages/budget/BudgetWizard"));
import { ComposerPage as SocialComposer, CalendarPage as SocialCalendar,
         LibraryPage as SocialLibrary, DraftsPage as SocialDrafts } from "@/pages/social/SocialSuite";
import { ApprovalsPage as SocialApprovals, BulkUploadPage as SocialBulkUpload,
         ShortLinksPage as SocialShortLinks, BrandKitPage as SocialBrandKit }
  from "@/pages/social/SocialExtras";
const ServiceTemplatesEditor = React.lazy(() => import(/* webpackChunkName: "p-admin-servicetemplateseditor" */ "@/pages/admin/ServiceTemplatesEditor"));
// Phase 2 · Templates Library — Admin Web UI
const TemplatesLibraryPage = React.lazy(() => import(/* webpackChunkName: "p-admin-templateslibrarypage" */ "@/pages/admin/TemplatesLibraryPage"));
const TemplateFillPage = React.lazy(() => import(/* webpackChunkName: "p-admin-templatefillpage" */ "@/pages/admin/TemplateFillPage"));
const TemplateInstanceNewRedirect = React.lazy(() => import(/* webpackChunkName: "p-admin-templateinstancenewredirect" */ "@/pages/admin/TemplateInstanceNewRedirect"));
// Phase 4 · Batch B — Handbook + Onboarding
const HandbookPage = React.lazy(() => import(/* webpackChunkName: "p-handbookpage" */ "@/pages/HandbookPage"));
const TimeOffPage = React.lazy(() => import(/* webpackChunkName: "p-timeoffpage" */ "@/pages/TimeOffPage"));
const AdminTimeOffPage = React.lazy(() => import(/* webpackChunkName: "p-admintimeoffpage" */ "@/pages/AdminTimeOffPage"));
const EmployeeOnboardingChecklistPage = React.lazy(() => import(/* webpackChunkName: "p-onboardingpage" */ "@/pages/OnboardingPage"));
const AdminOnboardingDashboardPage = React.lazy(() => import(/* webpackChunkName: "p-admin-adminonboardingdashboardpage" */ "@/pages/admin/AdminOnboardingDashboardPage"));
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

// Phase K69 · Feb-2026 — /marketing/sequences/:id → /marketing/
// automations/:id. The rename is UI-string-only so we redirect
// stale bookmarks without changing the backend route
// (``/api/marketing/sequences``) or the underlying doc collection.
function SequenceIdRedirect() {
  const { id } = useParams();
  return <Navigate to={`/marketing/automations/${id}`} replace />;
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
      <TenantThemeProvider>
      <PermissionsBridge>
      <RealtimeProvider>
      <ConfirmProvider>
      <BrowserRouter>
        <ScrollToTop />
        <TelephonyLiveEventsBridge />
        <React.Suspense fallback={<PageSkeleton />}>
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
          {/* Phase F1.2 · Feb-2026 — public customer-portal
              agreement renewal page. Token-authed via ?token= from
              the A4-produced renewal proposal email. */}
          <Route path="/customer-portal/agreements/:agreement_id/renew"
                  element={<PortalAgreementRenew />} />
          <Route path="/signup" element={<Signup />} />
          {/* Feb-2026 · Business Signup SP2 — public self-serve
              tenant signup + email-verify landing + wizard. */}
          <Route path="/business-signup"
                  element={<BusinessSignup />} />
          <Route path="/business-signup/verify"
                  element={<BusinessSignupVerify />} />
          <Route path="/business-signup/verify-email-sent"
                  element={<BusinessSignupVerifyEmailSent />} />
          <Route path="/onboarding-wizard"
                  element={<OnboardingWizard />} />
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
          {/* Feb-2026 · Phase A · Item 1 — public estimate-approve /
              decline landing page. The magic-link generator emits
              ``/e/estimate?token=…``; this route reads the token
              from the query and hands it straight to EstimateView,
              which activates the Phase A path-based endpoints for
              per-line + top-level approve / decline. Sits OUTSIDE
              AppLayout so no auth guard runs. */}
          <Route path="/e/estimate" element={<PublicEstimateLanding />} />
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
          {/* Feb-2026 · Task 3 — Invoices bypass portal. New canonical
              magic-link route. Decodes the JWT payload client-side to
              extract invoice_id, then renders full InvoiceView + inline
              Pay Now via the existing magic-pay flow. */}
          <Route path="/i/:token" element={<PublicInvoiceMagic />} />

          {/* Phase 22 · Feb 2026 — public service-record images portal (no auth). */}
          <Route path="/portal/service/:uuid" element={<ServiceImagesPortalPage />} />

          {/* Phase 12 · Feb 2026 — public magic-link "Add card" page (no auth). */}
          {/* Phase 47c · Feb 2026 — RESTORED after the Phase LZ4 retirement.
              Direct Stripe SetupIntent flow (see /pages/public/AddCardPage). */}
          <Route path="/portal/add-card" element={<AddCardPage />} />

          {/* Phase P30 · Feb 2026 — Stripe-hosted Checkout Session
              (mode=setup) redirect target. No auth — customer arrives
              from email/SMS link. */}
          <Route path="/portal/setup-success" element={<SetupSuccess />} />
          <Route path="/portal/setup-cancelled" element={<SetupSuccess />} />

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
            {/* Phase F2 · Feb-2026 — Charge Template Bundles admin CRUD. */}
            <Route path="admin/charge-templates" element={<AdminOnly><AdminChargeTemplatesPage /></AdminOnly>} />
            {/* Phase F3 · Feb-2026 — Soshie moderation queue. */}
            <Route path="admin/soshie/moderation" element={<AdminOnly><SoshieModerationQueuePage /></AdminOnly>} />
            {/* Task RR/SS Phase 2 · Feb 2026 */}
            <Route path="admin/ai-personas-scope" element={<AdminOnly><AiPersonasScopePage /></AdminOnly>} />
            <Route path="admin/ai-tool-audit" element={<AdminOnly><AiToolAuditPage /></AdminOnly>} />
            {/* Phase A1 · Feb-2026 — Proactive Intelligence full-list
                page. ``AdminOnly`` already resolves to admin +
                super_admin (see line 493 wrapper), which matches the
                backend contract exactly. Manager/technician/customer
                bounce to ``/`` — the AlertBell in AdminTopBar is
                self-gated to the same two roles so the surface stays
                consistent end-to-end. */}
            <Route path="admin/intelligence/alerts" element={<AdminOnly><IntelligenceAlerts /></AdminOnly>} />
            {/* Phase C · Feb-2026 — Sales Pipeline Kanban page. Admin +
                super_admin + manager only (mirrors the sidebar
                ``manager_only`` hard_rule + backend 403
                ``insufficient_role_for_pipeline``). Techs and portal
                customers bounce to ``/``. */}
            <Route path="admin/pipeline" element={<AdminOrManager><SalesPipeline /></AdminOrManager>} />
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
            {/* Phase 55-a · Aug-2026 — Homeworks importer route.
                Feb-2026 · K55.a — removed as part of the SuperCool +
                HomeWorks integration sunset. */}
            {/* Phase 56-c · Aug-2026 — Pricebook Cost Comparison report. */}
            <Route path="admin/reports/pricebook-cost-comparison" element={<AdminOnly><PricebookCostComparison /></AdminOnly>} />
            {/* Phase 56-d · Aug-2026 — Supplier Spend / Margin report. */}
            <Route path="admin/reports/supplier-spend" element={<AdminOnly><SupplierSpendReport /></AdminOnly>} />
            <Route path="settings/service-categories" element={<AdminOnly><ServiceCategoriesPage /></AdminOnly>} />
            {/* Phase P16 · Feb-2026 — Master Services (Pricebook) settings.
                Admin OR manager can reach the page (CRUD); DELETE is still
                admin-only on the backend and hidden as a disabled button
                for managers in the UI. */}
            <Route path="settings/master-services" element={<AdminOrManager><MasterServicesSettings /></AdminOrManager>} />
            {/* Pricebook × Profit-Reporting Phase 1 · Feb-2026 —
                consolidated Categories admin (Income + Service tabs)
                reached from the Pricebook toolbar. */}
            <Route path="pricebook/categories" element={<AdminOnly><CategoriesAdmin /></AdminOnly>} />
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
            {/* Feb-2026 · Consolidated Settings Hub — `/settings/integrations`
                now nests inside <SettingsHub> above so the hub sidebar
                stays visible.  K55.a removed the SuperCool + HomeWorks
                sub-detail routes; historical audit fields on data
                documents are preserved intact. */}
            {/* Phase 54b · Feb-2026 — Wholesale supplier settings. */}
            <Route path="settings/suppliers" element={<AdminOrManagerForSuppliers><SupplierSettings /></AdminOrManagerForSuppliers>} />
            {/* Phase 54g · Feb-2026 — supplier sync analytics dashboard. */}
            <Route path="reports/supplier-syncs" element={<AdminOrManagerForSuppliers><SupplierSyncAnalytics /></AdminOrManagerForSuppliers>} />
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
            <Route path="admin/marketing/sequences" element={<Navigate to="/admin/marketing/automations" replace />} />
            <Route path="admin/marketing/automations" element={<AdminOnly><MarketingSequencesPage /></AdminOnly>} />
            <Route path="admin/marketing/review-requests" element={<AdminOnly><MarketingReviewRequestsPage /></AdminOnly>} />
            <Route path="admin/marketing/analytics" element={<AdminOnly><MarketingAnalyticsPage /></AdminOnly>} />
            {/* Phase H6 · Feb-2026 — Monthly analytics dashboard (Soshie moderation, charge-template usage, drift alerts, manual-post conversion). */}
            <Route path="admin/analytics-monthly" element={<AdminOnly><AnalyticsMonthlyPage /></AdminOnly>} />
            <Route path="admin/marketing/suppressions" element={<AdminOnly><MarketingSuppressionsPage /></AdminOnly>} />
            <Route path="admin/marketing/forms" element={<AdminOnly><MarketingFormsPage /></AdminOnly>} />
            <Route path="admin/leads" element={<AdminOnly><LeadsDashboardPage /></AdminOnly>} />
            {/* Phase 8 · Feb 2026 — Lead detail (admin + manager) */}
            <Route path="leads/:id" element={<AdminOnly><LeadDetail /></AdminOnly>} />
            <Route path="admin/leads/:id" element={<AdminOnly><LeadDetail /></AdminOnly>} />
            <Route path="portal/preferences" element={<PortalPreferences />} />
            <Route path="marketing/reviews" element={<AdminOnly><Reviews /></AdminOnly>} />
            <Route path="marketing/sequences" element={<Navigate to="/marketing/automations" replace />} />
            <Route path="marketing/sequences/new" element={<Navigate to="/marketing/automations/new" replace />} />
            <Route path="marketing/sequences/:id" element={<SequenceIdRedirect />} />
            <Route path="marketing/automations" element={<AdminOnly><SequencesList /></AdminOnly>} />
            <Route path="marketing/automations/new" element={<AdminOnly><SequenceNew /></AdminOnly>} />
            <Route path="marketing/automations/:id" element={<AdminOnly><SequenceDetail /></AdminOnly>} />
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
            <Route path="settings/notifications/lead-alerts" element={<AdminOnly><LeadAlertsSettings /></AdminOnly>} />
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
            {/* Phase AIM0 · Feb-2026 — AI Measure POC. The page component
                has its OWN role guard (``AiMeasurePageRoleGuard``) so
                owners get access; we intentionally do NOT wrap it in
                ``AdminOnly`` (which excludes owners on other routes). */}
            <Route path="admin/tools/ai-measure" element={<AiMeasurePage />} />
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
            {/* Phase MI1 · Feb 2026 — multi-industry checklist template editor. */}
            <Route path="admin/settings/checklists" element={<AdminOnly><ChecklistTemplatesSettings /></AdminOnly>} />

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
            {/* Phase R0 · Feb-2026 — new tabbed Reports Suite shell.
                R1–R7 dashboards hang off this route. Legacy
                ReportsHub tile grid stays live at ``/reports``
                during the R-series rollout; migration will happen
                once R5 (Overview) is fully wired. */}
            <Route path="reports/suite" element={<AdminOnly><ReportsSuite /></AdminOnly>} />
            <Route path="reports/business-summary" element={<AdminOnly><BusinessSummary /></AdminOnly>} />
            {/* Feb-2026 · Reports Gap Fill Phase 5a.1 — Business Snapshot. */}
            <Route path="reports/business-snapshot" element={<AdminOnly><BusinessSnapshot /></AdminOnly>} />
            {/* Feb-2026 · Reports Gap Fill Phase 5a.1 (Part B) — Attrition + Time to Get Paid. */}
            <Route path="reports/attrition" element={<AdminOnly><AttritionReport /></AdminOnly>} />
            <Route path="reports/time-to-get-paid" element={<AdminOnly><TimeToGetPaidReport /></AdminOnly>} />
            {/* Feb-2026 · Reports Gap Fill Phase 5a.2 — cockpit-mirror trio. */}
            <Route path="reports/revenue-by-service" element={<AdminOnly><RevenueByServiceReport /></AdminOnly>} />
            <Route path="reports/recurring-vs-project-revenue" element={<AdminOnly><RecurringVsProjectReport /></AdminOnly>} />
            <Route path="reports/client-lifetime-value" element={<AdminOnly><ClientLifetimeValueReport /></AdminOnly>} />
            {/* Feb-2026 · Reports Gap Fill Phase 5b.1 — Close Ratio + Time to Close. */}
            <Route path="reports/close-ratio" element={<AdminOnly><CloseRatioReport /></AdminOnly>} />
            <Route path="reports/time-to-close" element={<AdminOnly><TimeToCloseReport /></AdminOnly>} />
            {/* Feb-2026 · Reports Gap Fill Phase 5b.2 — Labor Efficiency + Booked Out / Capacity. */}
            <Route path="reports/labor-efficiency" element={<AdminOnly><LaborEfficiencyReport /></AdminOnly>} />
            <Route path="reports/booked-out-capacity" element={<AdminOnly><BookedOutCapacityReport /></AdminOnly>} />
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
            <Route path="portal/warranties" element={<PortalWarranties />} />
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
            {/* Feb-2026 · Consolidated Settings Hub — parent index +
                nested tabs. Branding + Integrations + Social live
                INSIDE the hub shell so the sidebar stays visible
                while switching tabs. Everything else still resolves
                to its historic path from the "General" quick-links. */}
            <Route path="settings" element={<AdminOnly><SettingsHub /></AdminOnly>}>
              <Route index element={<SettingsGeneral />} />
              <Route path="general" element={<SettingsGeneral />} />
              <Route path="branding" element={<BrandLogoSettings />} />
              <Route path="business" element={<BusinessSettings />} />
              <Route path="industries" element={<IndustriesSettings />} />
              <Route path="theme" element={<ThemeSettings />} />
              <Route path="integrations" element={<IntegrationsHub />} />
              <Route path="social" element={<SettingsSocial />} />
              {/* Feb-2026 · Ticket #3 — Org Notifications toggles. */}
              <Route path="org-notifications" element={<OrgNotificationsSettings />} />
              {/* Feb-2026 · Ticket #4 — AI Configuration. */}
              <Route path="ai-configuration" element={<AIConfigurationSettings />} />
              {/* Sprint 3b · Feb-2026 — Chemistry Configuration. */}
              <Route path="chemistry-configuration" element={<ChemistryConfigurationSettings />} />
              {/* Sprint 3c · Feb-2026 — Feature Marketplace. */}
              <Route path="feature-marketplace" element={<FeatureMarketplaceSettings />} />
              {/* Feb-2026 · Proposal Analytics — flipbook estimate
                  engagement dashboard. Admin-only via the parent
                  <AdminOnly> wrapper on the ``settings`` route. */}
              <Route path="proposal-analytics" element={<ProposalAnalyticsPage />} />
            </Route>
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
            {/* Feb-2026 · Housekeeping Batch A — the stranded
                ``portal/profile/payment-methods`` route + its
                plural component were removed. All portal
                payment-method flows now go through the singular
                ``portal/payment-method`` route above. See
                FLAKE_STABILIZATION_BACKLOG §1 (resolved). */}
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
        </React.Suspense>
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
      </TenantThemeProvider>
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
