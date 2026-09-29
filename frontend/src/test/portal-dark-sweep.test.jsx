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
// ``<PortalThemeShell>`` (via ``AppLayout``). New portal pages MUST
// be added here so the sweep guard tracks them.
const PORTAL_PAGES_UNDER_SHELL = [
  "src/pages/portal/PortalHome.jsx",
  "src/pages/portal/PortalPhotos.jsx",
  "src/pages/portal/PortalPhotosPage.jsx",
  "src/pages/portal/PortalVideos.jsx",
  "src/pages/portal/PortalVideosPage.jsx",
  "src/pages/portal/PortalServiceReports.jsx",
  "src/pages/portal/PortalTerms.jsx",
  "src/pages/portal/PortalWarranties.jsx",
  "src/pages/portal/PortalChatsPage.jsx",
  "src/pages/portal/PortalPaymentReturn.jsx",
  "src/pages/portal/MyReferralsSection.jsx",
  "src/pages/portal/ReferralSection.jsx",
];

// Portal-scoped module containing multiple sub-exports (PortalServices,
// PortalInvoices, PortalEstimates, PortalPayments, PortalDocuments,
// PortalMessages, PortalProfile, PortalRequestService, …). Same rule
// — module-level ``colors`` must bind to ``portalColors``.
const PORTAL_PAGES_MODULE = "src/pages/portal/PortalPages.jsx";

// Pages mounted OUTSIDE the portal shell (public magic-link landings
// / setup callbacks). Retained with the light ``colors`` binding so
// they read on a white body when the customer arrives from email.
const PORTAL_PAGES_PUBLIC = [
  "src/pages/portal/PortalReviews.jsx",       // /r/review magic-link + /portal/reviews shell
  "src/pages/portal/PortalPreferences.jsx",   // /r/preferences (public)
  "src/pages/portal/PortalReviewSubmit.jsx",  // /portal/review/submit (token)
  "src/pages/portal/PortalSign.jsx",          // /portal/sign/:token (public)
  "src/pages/portal/SetupSuccess.jsx",        // /portal/setup-success (public)
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
