{/*
  ATTORNEY REVIEW REQUIRED before App Store submission.
  This draft was generated to satisfy Apple Guideline 5.1.1 and provide
  starting content for legal review. Do not submit as final without an
  attorney's sign-off, particularly on state-specific privacy rights,
  data retention timelines, and international transfer language.
*/}
/**
 * Feb-2026 · P21 — Privacy Policy content (replaces P11b placeholder).
 *
 * Served at ``/privacy-policy``.  Route wiring lives in ``App.js``.
 * Mobile links to this URL via ``expo-linking`` (see P11b mobile
 * ``DeleteAccountSection`` sibling row) so a policy edit here
 * propagates to every surface with a redeploy.
 */
import React from "react";
import { Link } from "react-router-dom";
import { colors } from "@/theme";


const EFFECTIVE_DATE = "February 21, 2026";
const LAST_UPDATED = "February 21, 2026";


const VENDORS = [
  {
    name: "Stripe",
    purpose: "Payment processing",
    data: "Card details tokenized by Stripe (we never store card numbers); billing name; billing email",
    href: "https://stripe.com/privacy",
  },
  {
    name: "Mapbox",
    purpose: "Map tiles + geocoding for dispatch and routing",
    data: "Service address; approximate device location during active routing",
    href: "https://www.mapbox.com/legal/privacy",
  },
  {
    name: "Google Maps API",
    purpose: "Fallback geocoding + route optimization",
    data: "Service address only",
    href: "https://policies.google.com/privacy",
  },
  {
    name: "RingCentral",
    purpose: "Outbound SMS + voice for service notifications",
    data: "Phone number; message content of transactional SMS",
    href: "https://www.ringcentral.com/legal/privacy-notice.html",
  },
  {
    name: "Twilio",
    purpose: "SMS fallback provider for transactional messages",
    data: "Phone number; message content of transactional SMS",
    href: "https://www.twilio.com/en-us/legal/privacy",
  },
  {
    name: "Resend",
    purpose: "Transactional email delivery (receipts, service reports, alerts)",
    data: "Email address; email body content",
    href: "https://resend.com/legal/privacy-policy",
  },
  {
    name: "OpenAI / Anthropic (via Emergent LLM Key)",
    purpose: "AI-assisted service note summarization + admin copilots",
    data: "Redacted service notes; job summaries. We do NOT send customer names, addresses, or phone numbers to LLM providers.",
    href: "https://openai.com/policies/privacy-policy",
  },
  {
    name: "Homeworks",
    purpose: "CRM sync for tenants who migrated from Homeworks",
    data: "Customer name, email, phone, address, service history",
    href: "https://home.works/privacy",
  },
];


function VendorTable() {
  return (
    <div className="overflow-x-auto rounded-lg border" style={{ borderColor: colors.border }}>
      <table className="w-full text-sm" data-testid="privacy-vendor-table">
        <thead>
          <tr style={{ background: colors.surfaceSecondary || "#F8FAFC" }}>
            <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurface }}>Vendor</th>
            <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurface }}>Purpose</th>
            <th className="text-left px-3 py-2 font-semibold" style={{ color: colors.onSurface }}>Data categories shared</th>
          </tr>
        </thead>
        <tbody>
          {VENDORS.map((v) => (
            <tr key={v.name} style={{ borderTop: `1px solid ${colors.border}` }}>
              <td className="px-3 py-2 align-top">
                <a
                  href={v.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-semibold underline"
                  style={{ color: colors.brand }}
                >
                  {v.name}
                </a>
              </td>
              <td className="px-3 py-2 align-top" style={{ color: colors.onSurface }}>{v.purpose}</td>
              <td className="px-3 py-2 align-top" style={{ color: colors.onSurface }}>{v.data}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function H2({ children, id }) {
  return (
    <h2
      id={id}
      className="text-xl font-bold mt-8 mb-3"
      style={{ color: colors.onSurface }}
    >
      {children}
    </h2>
  );
}


function P({ children }) {
  return (
    <p
      className="text-sm mb-3"
      style={{ color: colors.onSurface, lineHeight: 1.6 }}
    >
      {children}
    </p>
  );
}


export default function PrivacyPolicy() {
  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: colors.background }}
      data-testid="privacy-policy-page"
    >
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">

        {/* ─────────── 1. Header ─────────── */}
        <h1
          className="text-3xl font-bold tracking-tight"
          style={{ color: colors.onSurface }}
          data-testid="privacy-policy-title"
        >
          Privacy Policy
        </h1>
        <div className="text-sm mt-2" style={{ color: colors.muted }}>
          <div><b>Pool &amp; Landscaping of Vistancia LLC</b></div>
          <div data-testid="privacy-effective-date">Effective: {EFFECTIVE_DATE}</div>
          <div>Last Updated: {LAST_UPDATED}</div>
        </div>

        {/* ─────────── 2. Introduction ─────────── */}
        <H2 id="introduction">1. Introduction</H2>
        <P>
          Pool &amp; Landscaping of Vistancia LLC (&ldquo;we,&rdquo;
          &ldquo;us,&rdquo; or &ldquo;PLOFV&rdquo;) provides residential
          pool-service, landscape-maintenance, and related field-service
          software and services in Arizona. This policy explains what
          personal information we collect, how we use it, who we share
          it with, and what choices you have. We do not sell your
          personal information and we do not run any advertising or
          third-party analytics on our platform.
        </P>

        {/* ─────────── 3. Information We Collect ─────────── */}
        <H2 id="collect">2. Information We Collect</H2>
        <h3 className="font-semibold mt-4 mb-2" style={{ color: colors.onSurface }}>Account information</h3>
        <P>Name, email address, phone number, service address, password (bcrypt-hashed &mdash; we never see or store the plain-text value), and role (customer / technician / admin).</P>
        <h3 className="font-semibold mt-4 mb-2" style={{ color: colors.onSurface }}>Service information</h3>
        <P>Job history, chemistry readings (pH, chlorine levels, alkalinity, cyanuric acid), before/after service photos, tech notes, appointment schedules, and invoice records.</P>
        <h3 className="font-semibold mt-4 mb-2" style={{ color: colors.onSurface }}>Location information</h3>
        <P>Precise GPS coordinates from field technicians during active service routes (used for dispatch and ETA calculation only &mdash; NOT collected from customer devices). Service-address geocoding for customer accounts.</P>
        <h3 className="font-semibold mt-4 mb-2" style={{ color: colors.onSurface }}>Payment information</h3>
        <P>Payment card numbers are tokenized by Stripe on your device and transmitted directly to Stripe &mdash; we never see or store your full card number, CVV, or expiration date. We retain the last four digits and card brand for receipt display only.</P>
        <h3 className="font-semibold mt-4 mb-2" style={{ color: colors.onSurface }}>Communications</h3>
        <P>Transactional SMS and email records (delivery status, timestamps, message content) for service confirmations, appointment reminders, and receipts. We retain these for compliance and support.</P>
        <h3 className="font-semibold mt-4 mb-2" style={{ color: colors.onSurface }}>Device information</h3>
        <P>Browser type, operating system, IP address, and request timestamps &mdash; collected for security monitoring, fraud prevention, and technical support.</P>

        {/* ─────────── 4. How We Use Information ─────────── */}
        <H2 id="use">3. How We Use Information</H2>
        <ul className="list-disc pl-6 text-sm mb-3" style={{ color: colors.onSurface, lineHeight: 1.6 }}>
          <li>Delivering the pool-service and landscaping work you scheduled.</li>
          <li>Dispatching technicians and optimizing service routes.</li>
          <li>Generating and delivering invoices, receipts, and service reports.</li>
          <li>Providing customer support and responding to your inquiries.</li>
          <li>Sending transactional communications (appointment confirmations, service completion notices, invoice notices).</li>
          <li>Complying with legal obligations and enforcing our terms of service.</li>
          <li>Detecting, preventing, and investigating fraud or security incidents.</li>
        </ul>
        <P><b>We do not sell your personal information.</b> We do not run advertising on our platform. We do not share your data with data brokers or ad networks.</P>

        {/* ─────────── 5. Third Parties We Share Data With ─────────── */}
        <H2 id="vendors">4. Third Parties We Share Data With</H2>
        <P>We share limited categories of your data with the following service providers, each bound by their own privacy policies and data-processing agreements with us:</P>
        <VendorTable />

        {/* ─────────── 6. Data Retention ─────────── */}
        <H2 id="retention">5. Data Retention</H2>
        <P>We retain account and service records for as long as your account is active, plus a retention tail thereafter as required by law or for legitimate business purposes (typically 7 years for financial records under Arizona tax and accounting rules). Transactional SMS and email logs are retained for 24 months. Location breadcrumbs from field technicians are retained for 90 days. Payment tokens are retained by Stripe on our behalf.</P>
        <P>You may delete your account at any time via the mobile app or web portal (Settings &rarr; Delete My Account). Upon deletion, your personal information is anonymized within 30 days &mdash; your service history remains on file with your service provider (as required for warranty, insurance, and audit purposes) but your name, email, phone, and address are permanently removed and cannot be recovered.</P>

        {/* ─────────── 7. Your Rights ─────────── */}
        <H2 id="rights">6. Your Rights</H2>
        <P>You have the right to:</P>
        <ul className="list-disc pl-6 text-sm mb-3" style={{ color: colors.onSurface, lineHeight: 1.6 }}>
          <li><b>Access and correction</b> &mdash; review your account information via the customer portal and correct inaccuracies.</li>
          <li>
            <b>Deletion</b> &mdash; delete your account via Settings &rarr; Delete My Account (
            <Link to="/portal/preferences" className="underline" style={{ color: colors.brand }}>customer portal settings</Link>) or by emailing us at{" "}
            <a href="mailto:cs@plofv.com" className="underline" style={{ color: colors.brand }}>cs@plofv.com</a>.
          </li>
          <li><b>Portability</b> &mdash; request a portable copy of your data by emailing <a href="mailto:cs@plofv.com" className="underline" style={{ color: colors.brand }}>cs@plofv.com</a>.</li>
          <li><b>Opt-out of marketing</b> &mdash; reply STOP to any marketing SMS or use the unsubscribe link in any marketing email. Transactional messages (appointment confirmations, receipts) cannot be opted out while you have an active account.</li>
        </ul>
        <h3 className="font-semibold mt-4 mb-2" style={{ color: colors.onSurface }}>State-specific rights</h3>
        <P>Residents of <b>California</b> (CCPA/CPRA), <b>Virginia</b> (VCDPA), <b>Colorado</b> (CPA), and <b>Texas</b> (TDPSA) have additional rights under state law, including the right to know what personal information we collect, request deletion, correct inaccuracies, and opt out of certain data-processing activities. Because we do not sell your data and do not run targeted advertising, most opt-out rights are inapplicable to our processing. To exercise state-specific rights, email us at <a href="mailto:cs@plofv.com" className="underline" style={{ color: colors.brand }}>cs@plofv.com</a> with your state of residence and a description of your request.</P>

        {/* ─────────── 8. Children's Privacy ─────────── */}
        <H2 id="children">7. Children&apos;s Privacy</H2>
        <P>Our services are residential-service oriented and directed to adults. We do not knowingly collect personal information from children under 13. If you believe we have inadvertently collected data from a child under 13, please contact us at <a href="mailto:cs@plofv.com" className="underline" style={{ color: colors.brand }}>cs@plofv.com</a> and we will delete it promptly.</P>

        {/* ─────────── 9. Data Security ─────────── */}
        <H2 id="security">8. Data Security</H2>
        <P>We use industry-standard protections including TLS 1.2+ for all data in transit, bcrypt password hashing (we never store plain-text passwords), encrypted secrets at rest, role-based access controls on admin surfaces, audit logging for administrative actions, and rate-limited authentication endpoints to slow credential-stuffing attempts. In the event of a data breach affecting Arizona residents, we will notify affected users consistent with Arizona Revised Statutes &sect; 18-552.</P>

        {/* ─────────── 10. International Users ─────────── */}
        <H2 id="international">9. International Users</H2>
        <P>Our services are offered exclusively in the United States. If you access our services from outside the United States, your personal information will be transferred to, stored, and processed in the United States, which may have data-protection laws different from those in your jurisdiction.</P>

        {/* ─────────── 11. Changes to This Policy ─────────── */}
        <H2 id="changes">10. Changes to This Policy</H2>
        <P>We may update this policy from time to time. When we make material changes, we will notify you via email or an in-app notice. The &ldquo;Last Updated&rdquo; date at the top of this page reflects the most recent revision. Continued use of our services after an update constitutes acceptance of the revised policy.</P>

        {/* ─────────── 12. Contact Us ─────────── */}
        <H2 id="contact">11. Contact Us</H2>
        <P>For questions, concerns, or to exercise your privacy rights, contact us at:</P>
        <div
          className="text-sm p-4 rounded-lg"
          style={{
            background: colors.surface,
            border: `1px solid ${colors.border}`,
            color: colors.onSurface,
          }}
          data-testid="privacy-contact-block"
        >
          <div><b>Pool &amp; Landscaping of Vistancia LLC</b></div>
          <div>16165 N 83rd Ave #200</div>
          <div>Peoria, AZ 85382</div>
          <div>
            <a
              href="mailto:cs@plofv.com"
              className="underline"
              style={{ color: colors.brand }}
              data-testid="privacy-policy-contact-link"
            >
              cs@plofv.com
            </a>
          </div>
        </div>

        {/* ─────────── 13. Governing Law ─────────── */}
        <H2 id="governing-law">12. Governing Law</H2>
        <P>This Privacy Policy is governed by the laws of the State of Arizona, without regard to its conflict-of-laws principles.</P>

        <div className="mt-8">
          <Link
            to="/"
            className="text-sm font-semibold"
            style={{ color: colors.brand }}
            data-testid="privacy-policy-home-link"
          >
            &larr; Back to home
          </Link>
        </div>
      </div>
    </div>
  );
}
