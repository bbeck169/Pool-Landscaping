import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth";
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
import JobsList from "@/pages/jobs/JobsList";
import JobNew from "@/pages/jobs/JobNew";
import JobDetail from "@/pages/jobs/JobDetail";
import QuotesList from "@/pages/quotes/QuotesList";
import QuoteInvoiceNew from "@/pages/quotes/QuoteInvoiceNew";
import QuoteInvoiceDetail from "@/pages/quotes/QuoteInvoiceDetail";
import InvoicesList from "@/pages/invoices/InvoicesList";
import { MasterInvoicesList, MasterInvoiceNew, MasterInvoiceDetail } from "@/pages/invoices/MasterInvoice";
import PaymentHandlesSettings from "@/pages/settings/PaymentHandles";
import LateFeesSettings from "@/pages/settings/LateFees";
import TermsSettings from "@/pages/settings/Terms";
import { LegalDocsList, LegalDocEditor } from "@/pages/settings/LegalDocs";
import { IntegrationsHub, MapSettings } from "@/pages/settings/IntegrationsPages";
import PortalTerms from "@/pages/portal/PortalTerms";
import {
  MarketingHub, BrandMemory, CampaignsList, CampaignNew, CampaignDetail,
  Posts, ApprovalQueue, ContentCalendar, SchedulingConfig, Performance,
  TemplatesHub, Reviews,
} from "@/pages/marketing/MarketingPages";
import {
  SequencesList, SequenceNew, SequenceDetail,
} from "@/pages/marketing/SequencePages";
import {
  SeoHub, ArticlesList, ArticleEditor, KeywordSuggest, SeoAudit, RankGrid,
  WordPressSettings, GbpHub,
} from "@/pages/seo/SeoPages";
import {
  AiEmployeesList, AiEmployeeDetail, TasksPage, NotificationsPage,
  AccessSettings, AccessHistory, RingCentralSettings, CallLogsPage,
} from "@/pages/aiops/AiOpsPages";
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
import IncomeByCategory from "@/pages/reports/IncomeByCategoryPage";
import {
  RevenueByCity, RevenueByCrew, RevenueByCustomer, GrossSales, InvoicedItems,
} from "@/pages/reports/RevenueSlices";
import {
  PaymentsLedger, AutoBilling, ImpExp, IncomeCategoriesCrud,
} from "@/pages/finance/FinancePages";
import PortalHome from "@/pages/portal/PortalHome";
import {
  PortalServices, PortalServiceDetail,
  PortalInvoices, PortalInvoiceDetail,
  PortalEstimates, PortalEstimateDetail,
  PortalPayments, PortalPaymentMethod,
  PortalDocuments, PortalMessages, PortalProfile,
  PortalRequestService, PortalPaymentComplete,
} from "@/pages/portal/PortalPages";
import PortalSignPage from "@/pages/portal/PortalSign";
import { CsatDashboard, CsatDetail, PublicCsat } from "@/pages/csat/CsatPages";
import { RealtimeProvider } from "@/realtime/NotificationSocket";
import AnalyticsPage from "@/pages/analytics/AnalyticsPage";
import OnboardingPage, { OnboardingLoginModal } from "@/pages/onboarding/OnboardingPage";
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
import { ComposerPage as SocialComposer, CalendarPage as SocialCalendar,
         LibraryPage as SocialLibrary, DraftsPage as SocialDrafts } from "@/pages/social/SocialSuite";
import { ApprovalsPage as SocialApprovals, BulkUploadPage as SocialBulkUpload,
         ShortLinksPage as SocialShortLinks, BrandKitPage as SocialBrandKit }
  from "@/pages/social/SocialExtras";
import ServiceTemplatesEditor from "@/pages/admin/ServiceTemplatesEditor";

function AdminOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user || (user.role !== "admin" && user.role !== "super_admin")) {
    return <Navigate to="/" replace />;
  }
  return children;
}

/** Root "/" gate: admin/super sees the AdminDashboard, techs get their
 *  schedule (Dashboard is removed for tech role in Phase 16C add-on),
 *  customers get sent to their portal home. */
function RoleAwareIndex() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user?.role === "technician") return <Navigate to="/schedule/today" replace />;
  if (user?.role === "customer") return <Navigate to="/portal/home" replace />;
  return <AdminDashboard />;
}

export default function App() {
  return (
    <AuthProvider>
      <PermissionsBridge>
      <RealtimeProvider>
      <BrowserRouter>
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

          {/* Everything else lives inside the protected shell (side nav + top bar + bottom tabs). */}
          <Route path="/" element={<AppLayout />}>
            {/* Root — techs are redirected to their schedule (Dashboard removed for tech role). */}
            <Route index element={<RoleAwareIndex />} />

            {/* Customers (Phase 2) */}
            <Route path="customers" element={<CustomersList />} />
            <Route path="customers/new" element={<CustomerForm />} />
            <Route path="customers/:id" element={<CustomerDetail />} />
            <Route path="customers/:id/edit" element={<CustomerForm />} />
            <Route path="customers/:id/chemistry" element={<CustomerChemistry />} />

            {/* Jobs (Phase 2) */}
            <Route path="jobs" element={<JobsList />} />
            <Route path="jobs/new" element={<JobNew />} />
            <Route path="jobs/:id" element={<JobDetail />} />

            {/* Quotes / Invoices / Master / Estimator / Settings (Phase 3) */}
            <Route path="quotes" element={<QuotesList />} />
            <Route path="quotes/new" element={<QuoteInvoiceNew docType="quote" />} />
            <Route path="quotes/:id" element={<QuoteInvoiceDetail docType="quote" />} />

            <Route path="invoices" element={<InvoicesList />} />
            <Route path="invoices/new" element={<QuoteInvoiceNew docType="invoice" />} />
            <Route path="invoices/master" element={<MasterInvoicesList />} />
            <Route path="invoices/master/new" element={<MasterInvoiceNew />} />
            <Route path="invoices/master/:id" element={<MasterInvoiceDetail />} />
            <Route path="invoices/:id" element={<QuoteInvoiceDetail docType="invoice" />} />

            <Route path="estimator" element={<EstimatesList />} />
            <Route path="estimator/settings" element={<EstimatorSettings />} />
            <Route path="estimator/templates" element={<EstimatorTemplates />} />
            <Route path="estimator/new" element={<EstimatorEditor />} />
            <Route path="estimator/:id" element={<EstimatorEditor />} />

            <Route path="settings/payment-handles" element={<PaymentHandlesSettings />} />
            <Route path="settings/late-fees" element={<AdminOnly><LateFeesSettings /></AdminOnly>} />
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
            <Route path="marketing/reviews" element={<AdminOnly><Reviews /></AdminOnly>} />
            <Route path="marketing/sequences" element={<AdminOnly><SequencesList /></AdminOnly>} />
            <Route path="marketing/sequences/new" element={<AdminOnly><SequenceNew /></AdminOnly>} />
            <Route path="marketing/sequences/:id" element={<AdminOnly><SequenceDetail /></AdminOnly>} />

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
            <Route path="notifications" element={<AdminOnly><NotificationsPage /></AdminOnly>} />

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
            <Route path="schedule/today" element={<TodaySchedule />} />
            <Route path="tech/huddle" element={<TechHuddlePage />} />
            <Route path="tech/time-clock" element={<TechTimeClockPage />} />
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
            <Route path="reports/revenue-by-city" element={<AdminOnly><RevenueByCity /></AdminOnly>} />
            <Route path="reports/revenue-by-crew" element={<AdminOnly><RevenueByCrew /></AdminOnly>} />
            <Route path="reports/revenue-by-customer" element={<AdminOnly><RevenueByCustomer /></AdminOnly>} />
            <Route path="reports/gross-sales" element={<AdminOnly><GrossSales /></AdminOnly>} />
            <Route path="reports/invoiced-items" element={<AdminOnly><InvoicedItems /></AdminOnly>} />
            <Route path="income-by-category" element={<AdminOnly><IncomeByCategory /></AdminOnly>} />
            <Route path="income-categories" element={<AdminOnly><IncomeCategoriesCrud /></AdminOnly>} />
            <Route path="payments" element={<AdminOnly><PaymentsLedger /></AdminOnly>} />
            <Route path="auto-billing" element={<AdminOnly><AutoBilling /></AdminOnly>} />
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
            <Route path="portal/invoices" element={<PortalInvoices />} />
            <Route path="portal/invoices/:id" element={<PortalInvoiceDetail />} />
            <Route path="portal/estimates" element={<PortalEstimates />} />
            <Route path="portal/estimates/:id" element={<PortalEstimateDetail />} />
            <Route path="portal/payments" element={<PortalPayments />} />
            <Route path="portal/payment-method" element={<PortalPaymentMethod />} />
            <Route path="portal/documents" element={<PortalDocuments />} />
            <Route path="portal/messages" element={<PortalMessages />} />
            <Route path="portal/profile" element={<PortalProfile />} />
            <Route path="portal/request-service" element={<PortalRequestService />} />
            <Route path="portal/payment-complete" element={<PortalPaymentComplete />} />
          </Route>

          {/* Anything unmatched → home */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
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
