{/*
  ATTORNEY REVIEW REQUIRED before App Store submission.
  This draft was generated to satisfy Apple Guideline 5.1.1 and provide
  starting content for legal review. Do not submit as final without an
  attorney's sign-off, particularly on pricing/refund terms, arbitration
  and class-action waiver language, limitation of liability caps, and
  state-specific consumer-protection carveouts.
*/}
/**
 * Feb-2026 · P21b — Public Terms of Service (App Store surface).
 *
 * Distinct from the tenant-editable per-service acceptance ToS
 * managed by ``TosAdminEditor`` / ``TosGate`` (P30 series) — that
 * surface is a tenant-scoped acceptance flow; this is the app-level
 * public policy for App Store review + brand ToS URL.
 */
import React from "react";
import { Link } from "react-router-dom";
import { colors } from "@/theme";


const EFFECTIVE_DATE = "February 21, 2026";
const LAST_UPDATED = "February 21, 2026";


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


export default function TermsOfService() {
  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: colors.background }}
      data-testid="terms-of-service-page"
    >
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">

        {/* ─────────── 1. Header ─────────── */}
        <h1
          className="text-3xl font-bold tracking-tight"
          style={{ color: colors.onSurface }}
          data-testid="terms-of-service-title"
        >
          Terms of Service
        </h1>
        <div className="text-sm mt-2" style={{ color: colors.muted }}>
          <div><b>Pool &amp; Landscaping of Vistancia LLC</b></div>
          <div data-testid="tos-effective-date">Effective: {EFFECTIVE_DATE}</div>
          <div>Last Updated: {LAST_UPDATED}</div>
        </div>

        {/* ─────────── 2. Acceptance ─────────── */}
        <section id="acceptance">
          <H2 id="acceptance-h">1. Acceptance of Terms</H2>
          <P>By accessing or using the Pool &amp; Landscaping of Vistancia LLC (&ldquo;we,&rdquo; &ldquo;us,&rdquo; or &ldquo;PLOFV&rdquo;) mobile app, web portal, or any related service (collectively, the &ldquo;Services&rdquo;), you agree to be bound by these Terms of Service (&ldquo;Terms&rdquo;). If you do not agree, do not access or use the Services.</P>
        </section>

        {/* ─────────── 3. Description ─────────── */}
        <section id="description">
          <H2>2. Description of Service</H2>
          <P>The Services provide a customer-relationship-management, dispatch, scheduling, and communications platform for residential pool and landscape service providers and their customers. Business-facing surfaces (admin dashboard, technician mobile app) are used by service-provider organizations; end-customer surfaces (customer portal, notifications) are used by residential adults who have engaged a provider on the platform.</P>
        </section>

        {/* ─────────── 4. Eligibility ─────────── */}
        <section id="eligibility">
          <H2>3. Eligibility</H2>
          <P>You must be at least 18 years of age and a resident of the United States to use the Services. By using the Services you represent and warrant that you meet these eligibility requirements.</P>
        </section>

        {/* ─────────── 5. Account Registration ─────────── */}
        <section id="account">
          <H2>4. Account Registration</H2>
          <P>You agree to provide accurate, current, and complete information when creating an account and to keep such information up to date. You are responsible for safeguarding your credentials and for all activity that occurs under your account. You must not share your account credentials or maintain more than one account per person.</P>
        </section>

        {/* ─────────── 6. Payment ─────────── */}
        <section id="payment">
          <H2>5. Payment Terms</H2>
          <P>Fees for services scheduled through the platform are payable per the pricing terms disclosed at the time of booking. Card payments are processed by Stripe, Inc.; we never see or store your full card number, CVV, or expiration date. Recurring subscription pricing (where applicable) will be disclosed prior to charge.</P>
          <P><i>TODO(pricing): attorney to finalize subscription vs per-visit fee schedule + auto-renew disclosures per applicable state law.</i></P>
          <P><i>TODO(refund): attorney to finalize refund policy (customer-initiated cancellations, weather cancellations, service quality disputes).</i></P>
        </section>

        {/* ─────────── 7. Cancellation & Termination ─────────── */}
        <section id="termination">
          <H2>6. Cancellation and Termination</H2>
          <P>You may terminate your account at any time via Settings &rarr; Delete My Account in the customer portal or mobile app; upon deletion your personal information is anonymized as described in our <Link to="/privacy-policy" className="underline" style={{ color: colors.brand }}>Privacy Policy</Link>. We may suspend or terminate your access to the Services if we determine, in our reasonable discretion, that you have violated these Terms; where practicable we will provide advance notice.</P>
        </section>

        {/* ─────────── 8. User Content ─────────── */}
        <section id="user-content">
          <H2>7. User Content</H2>
          <P>You retain all ownership rights in any photos, service notes, or other content you upload (&ldquo;User Content&rdquo;). You grant us a limited, non-exclusive, worldwide, royalty-free license to host, store, process, transmit, and display User Content solely for the purpose of providing the Services to you and your service provider. We will not use User Content for advertising or sell it to third parties.</P>
        </section>

        {/* ─────────── 9. Prohibited Uses ─────────── */}
        <section id="prohibited">
          <H2>8. Prohibited Uses</H2>
          <P>You agree not to: (a) scrape, crawl, or automate access to the Services; (b) reverse-engineer, decompile, or attempt to derive source code; (c) use the Services for any unlawful purpose or in violation of any applicable law; (d) transmit spam, malware, or harassing content; (e) attempt to circumvent authentication, rate-limiting, or access controls; or (f) resell or sublicense access to the Services without our prior written consent.</P>
        </section>

        {/* ─────────── 10. Intellectual Property ─────────── */}
        <section id="ip">
          <H2>9. Intellectual Property</H2>
          <P>The Services, including all software, designs, trademarks, and content (excluding User Content), are the exclusive property of PLOFV and its licensors and are protected by U.S. and international intellectual-property laws. Except for the limited license expressly granted in these Terms, no rights are transferred to you.</P>
        </section>

        {/* ─────────── 11. Third-Party Services ─────────── */}
        <section id="third-parties">
          <H2>10. Third-Party Services</H2>
          <P>The Services rely on third-party providers including Stripe (payments), Mapbox and Google Maps (routing), RingCentral and Twilio (SMS), Resend (email), and others. A complete list is available in our <Link to="/privacy-policy#vendors" className="underline" style={{ color: colors.brand }}>Privacy Policy</Link>. Your use of any third-party service is subject to that provider&apos;s own terms.</P>
        </section>

        {/* ─────────── 12. Disclaimers ─────────── */}
        <section id="disclaimers">
          <H2>11. Disclaimers</H2>
          <P>THE SERVICES ARE PROVIDED &ldquo;AS IS&rdquo; AND &ldquo;AS AVAILABLE&rdquo; WITHOUT WARRANTIES OF ANY KIND, WHETHER EXPRESS OR IMPLIED, INCLUDING WITHOUT LIMITATION IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT. WE DO NOT WARRANT THAT THE SERVICES WILL BE UNINTERRUPTED, TIMELY, ERROR-FREE, OR SECURE.</P>
        </section>

        {/* ─────────── 13. Limitation of Liability ─────────── */}
        <section id="liability">
          <H2>12. Limitation of Liability</H2>
          <P>TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL PLOFV BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, OR ANY LOSS OF PROFITS OR REVENUES, WHETHER INCURRED DIRECTLY OR INDIRECTLY, ARISING OUT OF OR IN CONNECTION WITH THESE TERMS OR THE SERVICES.</P>
          <P><i>TODO(liability-cap): attorney to specify the exact dollar cap or fee-based multiplier appropriate for Arizona jurisdiction.</i></P>
        </section>

        {/* ─────────── 14. Indemnification ─────────── */}
        <section id="indemnification">
          <H2>13. Indemnification</H2>
          <P>You agree to indemnify, defend, and hold harmless PLOFV, its affiliates, officers, directors, employees, and agents from and against any claims, liabilities, damages, losses, and expenses (including reasonable attorneys&apos; fees) arising out of or in any way connected with your use or misuse of the Services, your User Content, or your violation of these Terms.</P>
        </section>

        {/* ─────────── 15. Governing Law + Disputes ─────────── */}
        <section id="governing-law">
          <H2>14. Governing Law and Dispute Resolution</H2>
          <P>These Terms are governed by the laws of the State of Arizona, without regard to its conflict-of-laws principles. The exclusive venue for any judicial proceeding arising out of these Terms shall be the state and federal courts located in Maricopa County, Arizona.</P>
          <P><i>TODO(arbitration): attorney to decide whether to include a binding arbitration clause with class-action waiver, or preserve court-based dispute resolution. If arbitration is elected, attorney must add the required opt-out disclosures under applicable state law.</i></P>
        </section>

        {/* ─────────── 16. Changes to Terms ─────────── */}
        <section id="changes">
          <H2>15. Changes to Terms</H2>
          <P>We may modify these Terms from time to time. When we make material changes, we will notify you via email or an in-app notice. The &ldquo;Last Updated&rdquo; date at the top of this page reflects the most recent revision. Your continued use of the Services after an update constitutes acceptance of the modified Terms.</P>
        </section>

        {/* ─────────── 17. General Provisions ─────────── */}
        <section id="general-provisions">
          <H2 id="general-provisions-h">16. General Provisions</H2>
          <P><b>Severability.</b> If any provision of these Terms is held invalid or unenforceable by a court of competent jurisdiction, that provision shall be enforced to the maximum extent permissible and the remaining provisions of these Terms shall remain in full force and effect.</P>
          <P><b>Entire Agreement.</b> These Terms, together with our <Link to="/privacy-policy" className="underline" style={{ color: colors.brand }}>Privacy Policy</Link> and any tenant-scoped acceptance terms you may separately execute with your service provider, constitute the entire agreement between you and PLOFV regarding the Services and supersede all prior or contemporaneous communications, whether oral or written.</P>
          <P><b>Assignment.</b> You may not assign or transfer these Terms, by operation of law or otherwise, without our prior written consent; any attempted assignment in violation of the foregoing will be null and void. We may assign these Terms without restriction, including without limitation to any parent, subsidiary, affiliate, or successor in interest by merger, acquisition, or sale of substantially all of our assets.</P>
          <P><b>No Waiver.</b> Our failure to enforce any right or provision of these Terms will not be considered a waiver of such right or provision. Any waiver must be in writing and signed by an authorized representative of PLOFV.</P>
          <P><b>Notices.</b> You consent to receive notices from us electronically. We may provide notices to you via in-app notification or to the email address on file for your account. Notices to us must be sent to <a href="mailto:cs@plofv.com" className="underline" style={{ color: colors.brand }}>cs@plofv.com</a>.</P>
          <P><i>TODO(force-majeure): attorney to add a force-majeure carve-out (weather, utility outage, third-party API downtime) appropriate for a field-service platform.</i></P>
          <P><i>TODO(export-control): attorney to confirm whether U.S. export-control representations are required given the Services are U.S.-only.</i></P>
        </section>

        {/* ─────────── 18. Contact ─────────── */}
        <section id="contact">
          <H2>17. Contact</H2>
          <P>For questions about these Terms, contact us at:</P>
          <div
            className="text-sm p-4 rounded-lg"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="tos-contact-block"
          >
            <div><b>Pool &amp; Landscaping of Vistancia LLC</b></div>
            <div>16165 N 83rd Ave #200</div>
            <div>Peoria, AZ 85382</div>
            <div>
              <a
                href="mailto:cs@plofv.com"
                className="underline"
                style={{ color: colors.brand }}
                data-testid="tos-contact-link"
              >
                cs@plofv.com
              </a>
            </div>
          </div>
        </section>

        <div className="mt-8">
          <Link
            to="/"
            className="text-sm font-semibold"
            style={{ color: colors.brand }}
            data-testid="terms-of-service-home-link"
          >
            &larr; Back to home
          </Link>
        </div>
      </div>
    </div>
  );
}
