{/*
  ATTORNEY REVIEW REQUIRED before App Store submission.
  This page makes specific factual claims about how customer data is
  (and isn't) handled by our AI features. Every row in the per-
  surface table below is a warranty that the corresponding backend
  behaviour actually enforces the disclosure. If any refactor changes
  what the LLM sees for a surface, this page MUST be updated in the
  same PR — the P22 static-grep test does not cross-reference this
  page.  Apple Guideline 5.1.1 applies here as well as to the
  Privacy Policy.
*/}
/**
 * Feb-2026 · P23 — Public AI Transparency page.
 *
 * Served at ``/ai-transparency``.  Public + unauthenticated so App
 * Store reviewers and prospects can read without a login.  Mirrors
 * the P21 / P21b page frame + typography scale.
 *
 * Sibling docs:
 *   * ``/privacy-policy`` (P21)  — full data-handling disclosure.
 *   * ``/terms-of-service`` (P21b) — general Terms of Service.
 *   * Backend enforcement:
 *       - ``services/ai/pii_redactor.py`` (P22)
 *       - ``tests/test_no_raw_customer_field_in_llm_prompts.py`` (P22)
 */
import React from "react";
import { Link } from "react-router-dom";
import { colors } from "@/theme";


const EFFECTIVE_DATE = "February 24, 2026";
const LAST_UPDATED = "February 24, 2026";


// ── Per-surface table content ─────────────────────────────────────────
// The audit + refactor that produced this list lives in Phase P22 —
// see ``routers/reviews_ai_reply.py``, ``routers/ai_employees.py``,
// ``routers/churn.py``, ``routers/portal.py``, ``routers/business_os.py``,
// ``routers/checkin_rewrite.py``, ``routers/ai_brain.py``.
const SURFACES = [
  {
    feature: "Marina — Customer Portal AI Concierge",
    where: "Customer portal chat (mobile + web)",
    sent: "Your message text and your account's outstanding balance summary — NO name, phone, email, or address.",
    provider: "OpenAI / Anthropic (via Emergent LLM Key)",
  },
  {
    feature: "Service note rewrites",
    where: "Technician check-in screen (mobile field app)",
    sent: "The technician's rough note with emails and phone numbers scrubbed by regex before send; the service category and a coarse city/state hint for SEO copy — NEVER your exact street address or personal name.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "AI water photo analysis",
    where: "Technician mobile app — pool water test-strip photo",
    sent: "The photo itself and any chemistry readings the tech typed in. NO customer identifier is attached to the image.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "Review reply drafts",
    where: "Admin dashboard — Google/Yelp/Facebook review responses",
    sent: "A [REVIEWER] placeholder and the public review text. The real reviewer name is substituted only into the AI's OUTPUT before publishing, never into the prompt.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "Vizzy call prep sheets",
    where: "Admin dashboard — pre-call briefing card",
    sent: "A symbolic [CUSTOMER …] reference, job history, open invoice/estimate summaries, and free-text customer notes with emails/phones regex-scrubbed. NO name/email/phone.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "Dexter analytics — top customers report",
    where: "Admin dashboard — data insights tab",
    sent: "Anonymized rows labelled ``Customer_1..N`` with only the ranked metric (revenue / visit count / chemicals cost). Real names are re-attached to the response display AFTER the AI call.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "Churn scoring and retention campaign drafts",
    where: "Admin dashboard — retention pipeline",
    sent: "Anonymized signal bundles (tenure days, NPS averages, job counts, complaint keyword counts) and ``Customer_N`` refs — NO name, email, phone.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "Lana — Ops copilot for staff",
    where: "Admin dashboard — right-side ops chat",
    sent: "The staff member's role (admin / manager / tech), the tenant's public business name, and aggregate operational counts (open jobs, open tasks, SOP titles). NO operator name or email.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "AI-assisted quote / estimator",
    where: "Admin dashboard — estimator screen",
    sent: "Service type, job title, and the admin-typed scope description (plus any attached job photos). NO customer identity.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "SEO / GBP / marketing copy drafting",
    where: "Admin dashboard — SEO, GBP posts, marketing studio",
    sent: "Your business's own public NAP (business name, address, phone), tenant tone, service ZIPs, and campaign topic strings. NO individual customer data.",
    provider: "OpenAI / Anthropic",
  },
  {
    feature: "Admin Copilot (disclosed exception)",
    where: "Admin dashboard — natural-language copilot chat",
    sent: "When an authenticated admin explicitly queries customer data (e.g. \"find customer Garcia\"), the requested customer records — including name, email, phone, and service address — ARE passed to the AI provider so the copilot can answer. This is the only surface where customer PII is intentionally sent to an AI provider.",
    provider: "Anthropic (Claude) — zero-retention agreement, not used for training",
    highlight: true,
  },
];


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


function SurfaceTable() {
  return (
    <div
      className="overflow-x-auto rounded-lg border"
      style={{ borderColor: colors.border }}
    >
      <table
        className="w-full text-sm"
        data-testid="ai-transparency-surface-table"
      >
        <thead>
          <tr style={{ background: colors.surfaceSecondary || "#F8FAFC" }}>
            <th className="text-left px-3 py-2 font-semibold"
                 style={{ color: colors.onSurface }}>Feature</th>
            <th className="text-left px-3 py-2 font-semibold"
                 style={{ color: colors.onSurface }}>Where it appears</th>
            <th className="text-left px-3 py-2 font-semibold"
                 style={{ color: colors.onSurface }}>What is sent to AI</th>
            <th className="text-left px-3 py-2 font-semibold"
                 style={{ color: colors.onSurface }}>Data provider</th>
          </tr>
        </thead>
        <tbody>
          {SURFACES.map((s) => (
            <tr
              key={s.feature}
              style={{
                borderTop: `1px solid ${colors.border}`,
                background: s.highlight
                  ? "rgba(234, 179, 8, 0.06)"
                  : "transparent",
              }}
              data-testid={`ai-surface-row-${s.feature.split(" ")[0].toLowerCase()}`}
            >
              <td className="px-3 py-2 align-top font-semibold"
                   style={{ color: colors.onSurface }}>
                {s.feature}
              </td>
              <td className="px-3 py-2 align-top"
                   style={{ color: colors.onSurface }}>{s.where}</td>
              <td className="px-3 py-2 align-top"
                   style={{ color: colors.onSurface }}>{s.sent}</td>
              <td className="px-3 py-2 align-top"
                   style={{ color: colors.onSurface }}>{s.provider}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


export default function AiTransparency() {
  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: colors.background }}
      data-testid="ai-transparency-page"
    >
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-10">

        {/* ─────────── Header ─────────── */}
        <h1
          className="text-3xl font-bold tracking-tight"
          style={{ color: colors.onSurface }}
          data-testid="ai-transparency-title"
        >
          AI Transparency
        </h1>
        <div className="text-sm mt-2" style={{ color: colors.muted }}>
          <div><b>Pool &amp; Landscaping of Vistancia LLC</b></div>
          <div data-testid="ai-transparency-effective-date">
            Effective: {EFFECTIVE_DATE}
          </div>
          <div>Last Updated: {LAST_UPDATED}</div>
        </div>

        <P>
          This page lists every AI-powered feature you may encounter in
          our app and describes what information is (and isn&apos;t)
          sent to our AI providers. If you have questions after
          reading, email{" "}
          <a
            href="mailto:cs@plofv.com"
            className="underline"
            style={{ color: colors.brand }}
          >
            cs@plofv.com
          </a>{" "}
          with subject line &ldquo;AI transparency&rdquo; and we
          will respond within 5 business days.
        </P>

        {/* ─────────── 1. At a glance ─────────── */}
        <section id="at-a-glance">
          <H2 id="at-a-glance-h">1. At a glance</H2>
          <div
            className="text-sm p-4 rounded-lg"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="ai-transparency-at-a-glance"
          >
            <ul className="list-disc pl-6 space-y-2"
                 style={{ lineHeight: 1.6 }}>
              <li>
                We use AI to speed up admin work — drafting messages,
                summarising notes, spotting patterns. AI does <b>not</b>{" "}
                make legally-effective decisions about you.
              </li>
              <li>
                For our normal operational features we do <b>not</b>{" "}
                send your name, phone, email, or exact street address
                to AI providers. See the table below for what each
                feature actually sends.
              </li>
              <li>
                One narrow admin-facing feature — the{" "}
                <b>Admin Copilot</b> — may show your account data to
                an AI provider when an authenticated administrator
                explicitly asks about it. This runs under a strict
                zero-retention contract with the provider and is
                disclosed in the table below and in our{" "}
                <Link
                  to="/privacy-policy#vendors"
                  className="underline"
                  style={{ color: colors.brand }}
                >
                  Privacy Policy
                </Link>.
              </li>
            </ul>
          </div>
        </section>

        {/* ─────────── 2. Per-surface table ─────────── */}
        <section id="surfaces">
          <H2 id="surfaces-h">2. AI features and what each one sends</H2>
          <P>
            The rows below are one-to-one with the AI code paths in
            our backend. If any of these behaviours change, this page
            is updated in the same release.
          </P>
          <SurfaceTable />
        </section>

        {/* ─────────── 3. Your rights ─────────── */}
        <section id="rights">
          <H2 id="rights-h">3. Your rights and choices</H2>
          <ul className="list-disc pl-6 text-sm mb-3"
               style={{ color: colors.onSurface, lineHeight: 1.6 }}>
            <li>
              <b>Ask for an audit.</b> You may email{" "}
              <a
                href="mailto:cs@plofv.com"
                className="underline"
                style={{ color: colors.brand }}
              >
                cs@plofv.com
              </a>{" "}
              to request a summary of what AI features touched your
              account during a given time window.
            </li>
            <li>
              <b>Opt out of AI-drafted communications.</b> Reply to
              any AI-drafted message with &ldquo;human please&rdquo;
              or email us at the address above; future messages to
              you will be manually written. Manual turnaround may be
              slower.
            </li>
            <li>
              <b>Delete your account.</b> Deleting your account
              (Settings → Delete My Account, described in the{" "}
              <Link
                to="/privacy-policy"
                className="underline"
                style={{ color: colors.brand }}
              >
                Privacy Policy
              </Link>) prevents any future AI touches on your data.
              Historical AI-generated content already delivered to
              you (invoices, service reports) is retained as required
              by law.
            </li>
            <li>
              <b>Read the full disclosure.</b> Cross-reference this
              page with the{" "}
              <Link
                to="/privacy-policy"
                className="underline"
                style={{ color: colors.brand }}
                data-testid="ai-transparency-privacy-policy-link"
              >
                Privacy Policy
              </Link>{" "}
              (§4 covers third-party data sharing including our AI
              providers).
            </li>
          </ul>
        </section>

        {/* ─────────── 4. Provider commitments ─────────── */}
        <section id="providers">
          <H2 id="providers-h">4. Our AI provider commitments</H2>
          <ul className="list-disc pl-6 text-sm mb-3"
               style={{ color: colors.onSurface, lineHeight: 1.6 }}>
            <li>
              <b>OpenAI and Anthropic</b> (accessed via the Emergent
              LLM Key) — data sent to these providers is <b>not</b>{" "}
              used to train their models. Zero-retention agreements
              are in effect for the surfaces disclosed above.
            </li>
            <li>
              <b>No third-party ad networks.</b> We do not send your
              data to advertising or ad-tech AI systems.
            </li>
            <li>
              <b>No analytics AI.</b> We do not run behavioural
              analytics AI on your app usage.
            </li>
            <li>
              <b>No automated legal decisions.</b> AI does not make
              decisions about your service pricing, credit terms,
              or account standing. A human on our team reviews any
              AI-generated draft before it becomes a bill, quote, or
              contract.
            </li>
          </ul>
        </section>

        {/* ─────────── 5. Report a concern ─────────── */}
        <section id="report">
          <H2 id="report-h">5. How to report a concern</H2>
          <P>
            If you believe an AI feature has handled your data in a
            way that doesn&apos;t match this page, please tell us
            directly:
          </P>
          <div
            className="text-sm p-4 rounded-lg"
            style={{
              background: colors.surface,
              border: `1px solid ${colors.border}`,
              color: colors.onSurface,
            }}
            data-testid="ai-transparency-contact-block"
          >
            <div><b>Pool &amp; Landscaping of Vistancia LLC</b></div>
            <div>
              Email:{" "}
              <a
                href="mailto:cs@plofv.com?subject=AI%20transparency"
                className="underline"
                style={{ color: colors.brand }}
                data-testid="ai-transparency-contact-link"
              >
                cs@plofv.com
              </a>{" "}
              &nbsp;·&nbsp; Subject line: &ldquo;AI transparency&rdquo;
            </div>
            <div>We respond within 5 business days.</div>
          </div>
        </section>

        <div className="mt-8">
          <Link
            to="/"
            className="text-sm font-semibold"
            style={{ color: colors.brand }}
            data-testid="ai-transparency-home-link"
          >
            &larr; Back to home
          </Link>
        </div>
      </div>
    </div>
  );
}
