import React from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider } from "@/auth";
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
import { EstimatesList, EstimatorSettings, EstimatorTemplates, EstimatorEditor } from "@/pages/estimator/Estimator";

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

            {/* Shared placeholders (later phases) */}
            <Route
              path="schedule"
              element={
                <Placeholder
                  title="Schedule"
                  phase={5}
                  note="For technicians: schedule visible read-only; clock in required to open jobs — full behavior arrives in Phase 5."
                />
              }
            />
            <Route path="tools" element={<Placeholder title="Calculators" phase={6} />} />
            <Route path="more" element={<Placeholder title="More" phase={7} />} />
            <Route path="leads/new" element={<Placeholder title="New Lead" phase={4} />} />

            {/* Customer portal placeholders */}
            <Route path="portal/home" element={<Placeholder title="Customer Home" phase={4} />} />
            <Route path="portal/services" element={<Placeholder title="My Services" phase={4} />} />
            <Route path="portal/invoices" element={<Placeholder title="My Invoices" phase={4} />} />
            <Route path="portal/estimates" element={<Placeholder title="My Estimates" phase={4} />} />
            <Route path="portal/payments" element={<Placeholder title="Payments" phase={4} />} />
            <Route path="portal/documents" element={<Placeholder title="Documents" phase={4} />} />
            <Route path="portal/messages" element={<Placeholder title="Messages" phase={4} />} />
            <Route path="portal/profile" element={<Placeholder title="Profile" phase={4} />} />
          </Route>

          {/* Anything unmatched → home */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
