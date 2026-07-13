import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "@/auth";
import AppLayout from "@/layouts/AppLayout";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
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

function AdminOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user || user.role !== "admin") {
    return <Navigate to="/" replace />;
  }
  return children;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/public/card/:slug" element={<PublicCard />} />

          {/* Everything else lives inside the protected shell (side nav + top bar + bottom tabs). */}
          <Route path="/" element={<AppLayout />}>
            {/* Admin */}
            <Route index element={<AdminDashboard />} />

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
            <Route path="access-settings" element={<AdminOnly><AccessSettings /></AdminOnly>} />
            <Route path="access-history" element={<AdminOnly><AccessHistory /></AdminOnly>} />
            <Route path="settings/ringcentral" element={<AdminOnly><RingCentralSettings /></AdminOnly>} />
            <Route path="call-logs" element={<AdminOnly><CallLogsPage /></AdminOnly>} />

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

            {/* Phase 10 — D2D Sales */}
            <Route path="d2d" element={<AdminOnly><D2dDashboard /></AdminOnly>} />
            <Route path="d2d/map" element={<AdminOnly><D2dMap /></AdminOnly>} />
            <Route path="d2d/knocks" element={<AdminOnly><D2dKnocks /></AdminOnly>} />
            <Route path="d2d/open-leads" element={<AdminOnly><D2dOpenLeads /></AdminOnly>} />
            <Route path="d2d/sold-leads" element={<AdminOnly><D2dSoldLeads /></AdminOnly>} />
            <Route path="d2d/report" element={<AdminOnly><D2dReport /></AdminOnly>} />
            <Route path="d2d/leaderboard" element={<AdminOnly><D2dLeaderboard /></AdminOnly>} />

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
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
