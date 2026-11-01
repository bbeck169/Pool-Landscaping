/**
 * DTP-2 · Feb-2026 — Portal dark-theme sweep source-grep guard.
 *
 * Every portal page mounted INSIDE the ``AppLayout`` protected-shell
 * (i.e. rendered inside ``<PortalThemeShell>``) must consume the
 * portal dark palette by importing ``portalColors as colors`` from
 * ``@/theme``. Pages that render OUTSIDE the shell (public magic-
 * link routes like ``PortalReviews`` mounted at ``/r/review`` and
 * ``PortalPreferences`` mounted at ``/r/preferences``, plus one-off
 * public landings) intentionally keep the light ``colors`` binding.
 *
 * Mounting every portal page end-to-end under jsdom is prohibitively
 * expensive — most pages fetch on mount and pull deep sub-trees. A
 * source-grep guard is the pragmatic contract for the sweep: it
 * locks the import shape (or the absence of a theme import for
 * pages that only reach for Tailwind atomics remapped inside
 * ``portal-dark.css``).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

// Every entry here maps to a route that mounts INSIDE
// ``<PortalThemeShell>`` (via ``AppLayout``) OR is a portal surface
// that renders on the dark navy palette even on a public magic-link
// route (DTP-2b brought the review / preferences / renewal / walk-
// through / referrals-page wrappers into the dark family). New
// portal pages MUST be added here so the sweep guard tracks them.
const PORTAL_PAGES_UNDER_SHELL = [
  "src/pages/portal/PortalHome.jsx",
  "src/pages/portal/PortalPhotosPage.jsx",
  "src/pages/portal/PortalVideosPage.jsx",
  "src/pages/portal/PortalServiceReports.jsx",
  "src/pages/portal/PortalTerms.jsx",
  "src/pages/portal/PortalWarranties.jsx",
  "src/pages/portal/PortalChatsPage.jsx",
  "src/pages/portal/PortalPaymentReturn.jsx",
  "src/pages/portal/MyReferralsSection.jsx",
  "src/pages/portal/ReferralSection.jsx",
  // DTP-2b · Feb-2026 — sweep finish.
  "src/pages/portal/PortalReviews.jsx",
  "src/pages/portal/PortalReviewSubmit.jsx",
  "src/pages/portal/PortalPreferences.jsx",
  "src/pages/portal/PortalReferralsPage.jsx",
  "src/pages/portal/PortalWalkthrough.jsx",
  "src/pages/portal/PortalAgreementRenew.jsx",
];

// Portal-scoped module containing multiple sub-exports (PortalServices,
// PortalInvoices, PortalEstimates, PortalPayments, PortalDocuments,
// PortalMessages, PortalProfile, PortalRequestService, …). Same rule
// — module-level ``colors`` must bind to ``portalColors``.
const PORTAL_PAGES_MODULE = "src/pages/portal/PortalPages.jsx";

// Pages mounted OUTSIDE the portal shell AND intentionally kept on
// the light palette. Post-DTP-2b there is only one true light-scope
// portal surface — PortalSign — plus two non-portal public landings
// that never carried a portal binding.
const PORTAL_PAGES_PUBLIC = [
  "src/pages/portal/PortalSign.jsx",           // /portal/sign/:token (public — signature print surface, light-scope carve-out)
  "src/pages/portal/SetupSuccess.jsx",         // /portal/setup-success (public)
  "src/pages/portal/PublicEstimateLanding.jsx", // /e/estimate (public)
];

const themeImportLine = (src) =>
  src.match(/import\s*\{[^}]*\}\s*from\s*['"]@\/theme['"]/g) || [];

describe("DTP-2 · Portal dark-theme sweep · source-grep guard", () => {
  it.each(PORTAL_PAGES_UNDER_SHELL)(
    "%s consumes portalColors (aliased as colors) or no theme import",
    (rel) => {
      const src = read(rel);
      const lines = themeImportLine(src);
      // Pages that don't touch the ``@/theme`` module (Tailwind-only
      // surfaces like PortalWalkthrough / PortalReferralsPage) satisfy
      // the sweep contract via ``portal-dark.css`` atomic overrides.
      if (lines.length === 0) return;
      for (const line of lines) {
        const hasBareColors    = /(^|[,\s{])colors\b/.test(line);
        const hasAliasedColors = /portalColors\s+as\s+colors/.test(line);
        // If the line pulls ``colors`` it MUST be via the alias.
        expect(hasBareColors && !hasAliasedColors).toBe(false);
      }
    },
  );

  it("PortalPages.jsx (multi-export module) binds module-level colors to portalColors", () => {
    const src = read(PORTAL_PAGES_MODULE);
    expect(src).toMatch(
      /import\s*\{[^}]*portalColors\s+as\s+colors[^}]*\}\s*from\s*['"]@\/theme['"]/,
    );
    // The pre-DTP-2 per-export ``const colors = portalColors`` shadow
    // lines must be gone now that the module-level import IS dark.
    expect(src).not.toMatch(/const\s+colors\s*=\s*portalColors\s*;/);
  });

  it.each(PORTAL_PAGES_PUBLIC)(
    "%s intentionally keeps the light ``colors`` binding (public route)",
    (rel) => {
      const src = read(rel);
      const lines = themeImportLine(src);
      // Not every public page pulls ``@/theme`` — that's fine too.
      // If it DOES, the sweep must NOT have flipped it to portalColors.
      for (const line of lines) {
        const hasAliasedColors = /portalColors\s+as\s+colors/.test(line);
        expect(hasAliasedColors).toBe(false);
      }
    },
  );
});
