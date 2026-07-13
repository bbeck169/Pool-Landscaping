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
import PortalTerms from "@/pages/portal/PortalTerms";
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
            <Route path="settings/legal/:slug" element={<AdminOnly><LegalDocEditor /></AdminOnly>} />
            <Route path="portal/terms" element={<PortalTerms />} />

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
            <Route path="schedule" element={<OpsHub />} />
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
