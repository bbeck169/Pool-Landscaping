# TD-seo-phase0 · SEO Phase 0 Scoping Doc

**Author:** TD-seo-phase0 recon cycle, Oct-2026
**Status:** Phase 0 (scoping, no code shipped)
**Dispatched:** operator approval of "defaults" on 3-feature backlog (SEO → AI → CAD)

---

## 0 · Executive summary (READ FIRST)

**Scope-reality delta surfaced during recon** — the dispatch's "default scope" wording describes a greenfield SEO project. **The codebase already carries extensive SEO/AEO infrastructure.** 8 BE router files, 1 admin UI page, cron-driven weekly AEO digest, embedded JSON-LD on the public widget, and a full operator-facing SEO content-generation + scanning pipeline. **However, the existing SEO stack targets a different problem** — it analyzes and generates content for the operator's EXTERNAL marketing website (WordPress). **It does NOT optimize the CRM's own public-facing pages** (portal, review landing, public cards, lead intake forms, public estimate pages).

**Classification of this ticket relative to current state**:
- Dispatch's default scope (b) + (c) + the 6 numbered SEO wins → **GAP-FILL + NEW TRACK, not greenfield**. The CRM's own public pages have minimal SEO (`index.html` has basic `<title>` + `<meta description>` only; no OG/Twitter cards, no JSON-LD, no per-page metadata, no sitemap/robots served by the CRM backend).
- The existing "SEO" admin UI (`WebsiteSeoPage.jsx`) is an **external-site scanner** for the operator's WordPress site — it is NOT a tenant-portal metadata manager. The dispatch's win #6 ("admin UI for operators to edit tenant-level SEO metadata") would need a NEW admin page or a NEW tab under the existing `WebsiteSeoPage.jsx` surface.

**Operator decision gate before Phase 1**: this scoping doc proceeds under the dispatch's defaults (operator may still counter), BUT flags the scope-reality delta prominently and lists 5 decisions the operator must make before Phase 1 can safely dispatch.

---

## 1 · Current-state audit (verbatim grep evidence)

### 1.1 Existing SEO plumbing (operator-WordPress-track, NOT CRM-page-track)

**Backend routers** (8 files, all under `backend/routers/`):
| File | Scope |
|---|---|
| `seo.py` | AI-driven keyword suggest + article drafting + WordPress publish (routes under `/seo/*`) |
| `seo_scans.py` | SEO scorecard scan jobs (`/seo/scans`, `/seo/scans/history`) |
| `seo_agentic.py` | Agentic SEO auditor — fetches target site, probes `/sitemap.xml` + `/robots.txt` on **external** host, scores JSON-LD presence |
| `seo_analyzer.py` | Deeper on-page SEO analyzer (JSON-LD LocalBusiness / Organization checks) |
| `seo_phase17c.py` | Auto-fix suggestions for missing SEO signals (patch snippets, including a `/sitemap.xml` suggestion) |
| `seo_content_refresh.py` | Cron-driven content-freshness tracker (ingests external sitemap) |
| `aeo.py` | Answer-Engine Optimization endpoints (JSON-LD generator, LLMs.txt generator, visibility runs, mentions tracking) |
| `aeo_digest.py` | Weekly AEO digest cron |

**Admin UI** (1 page):
- `frontend/src/pages/settings/WebsiteSeoPage.jsx` → calls `POST /seo/analyze` with a URL from `tenants.business_card.website_url`. Pulls scorecard + fixes. **Scans external site, does not edit tenant portal metadata.**

**Embedded JSON-LD** (1 surface):
- `backend/routers/public_widget.py:524-536` emits two `<script type="application/ld+json">` tags (LocalBusiness + ItemList) on the public-widget surface at `/public/checkins/{tenant_slug}/feed.html` and `/widget/preview/{tenant_slug}`. **Only the widget surfaces have JSON-LD today; no app-level pages do.**

**robots meta** (1 surface):
- `backend/routers/public_widget.py:550` emits `<meta name="robots" content="index,follow"/>` on the widget feed HTML. **No other surface emits a robots meta tag.**

**Cron scheduling** (1 job):
- `backend/server.py:2820-2824` schedules `services.aeo_digest.weekly_digest_cron` on `cron, minute=10`.

### 1.2 CRM app's own SEO surface (THE GAP)

**`frontend/public/index.html` current head**:
```html
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#000000" />
<meta name="description" content="Pool & Landscaping of Vistancia — field-service CRM for a pool and landscaping company." />
<title>Pool &amp; Landscaping of Vistancia</title>
```

**Missing**:
- No `<meta property="og:*">` (Open Graph)
- No `<meta name="twitter:*">` (Twitter cards)
- No `<link rel="canonical">`
- No `<script type="application/ld+json">`
- No `<link rel="alternate">` for i18n (not scope today)
- No per-page meta — the `<title>` is a build-time constant; it does not change across routes.

**Package.json FE deps**: `grep react-helmet frontend/package.json` returned empty. No `<Helmet>` library installed.

**`/sitemap.xml` or `/robots.txt` served by backend**: `grep "@app.*sitemap\|@app.*robots"` returned empty. **No endpoints serve either today.** The CRM's own sitemap + robots don't exist at the HTTP layer.

### 1.3 Public routes (candidates for SEO treatment)

From `frontend/src/App.js:822-890` — public (unauthenticated) routes exist for:
| Route | Component | Public? | Tenant-scoped? |
|---|---|---|---|
| `/login` | `Login` | yes | no (global login) |
| `/portal/login` | customer-portal login | yes | yes (resolved by subdomain/slug) |
| `/privacy-policy` | `PrivacyPolicy` | yes | no |
| `/terms-of-service` | `TermsOfService` | yes | no |
| `/ai-transparency` | `AiTransparency` | yes | no |
| `/signup`, `/business-signup`, `/business-signup/verify` | signup flow | yes | no |
| `/public/card/:slug` | `PublicCard` (tenant business card landing) | **yes + indexable** | **yes** |
| `/nfc/:slug` | `NfcReviewCardPage` | yes | yes (slug) |
| `/widget-demo`, `/widget/preview/:tenant_slug` | widget preview | yes | yes |
| `/public/checkins/{slug}/feed(.html)` | widget feed | **yes + indexable** | yes |
| `/f/:slug` | `PublicForm` (lead-intake form) | yes | yes |
| `/csat/:token` | one-time CSAT landing | token-gated (no SEO) | n/a |
| `/portal/sign/:token` | portal signing | token-gated (no SEO) | n/a |
| `/e/estimate` | public estimate landing | yes | yes |
| `/lead-request/:token` | token-gated lead request | no SEO | n/a |
| `/public/leads` | public lead intake | yes | yes |
| `/reviews/r/:token` | one-time review landing | token-gated | n/a |
| `/reviews/:tenant_slug` | **public reviews widget page** | **yes + indexable** | **yes** |

**Indexable + tenant-scoped (highest SEO value)**:
- `/public/card/:slug` → tenant business card landing (branded)
- `/reviews/:tenant_slug` → public reviews widget (social proof, high value)
- `/public/checkins/{slug}/feed.html` → public check-in feed (local SEO, LocalBusiness JSON-LD already embedded in widget)
- `/f/:slug` + `/public/leads` + `/e/estimate` → tenant-scoped lead/estimate funnels

**Dispatch default public pages** (tenant landing, service list, service detail, contact) → **DO NOT EXIST** as routes today. The CRM's public surface is lead-funnel + review-widget shaped, not marketing-site shaped. **This is a critical scope-reality gap** — operator may have been thinking of a marketing website that lives outside the CRM.

### 1.4 Multi-tenancy routing

`backend/routers/tenants.py:133-166` — tenant resolver cascade:
1. `?tenant=<id>` query parameter (impersonation / super_admin)
2. `X-Tenant-Id` header (API client)
3. `*.subdomain.plofv.com` subdomain lookup (slug match)
4. `custom_domain` Host-header match on `tenants.custom_domain`

Current prod: `app.plofv.com` (single-origin SPA). Tenant-scoped SEO pages would need to be reachable via EITHER subdomain OR custom-domain OR path-prefix. **Decision point for operator** — see §7.

Tenants have fields: `slug`, `custom_domain`, `primary_app_domain`, `business_card` (with `website_url`, `name`, `logo`, etc.). The last is already a semi-SEO-metadata doc; it could be the home for Phase 1 meta without introducing a new collection.

### 1.5 Customer portal surface

- `/portal/login` + `/r/review` + `/r/preferences` + `/customer-portal/agreements/:id/renew` — authed customer portal.
- `/portal/review/submit` — token-gated.
- The portal is BEHIND auth; SEO treatment is NOT applicable to authed portal pages. The dispatch's "(b) customer portal SEO-safe pages" default is a misread — there are no SEO-safe portal pages because the portal is gated. The dispatch may have intended "portal-adjacent public pages" (review landing, public card, lead intake) which DO exist.

---

## 2 · Proposed architecture

### 2.1 Three-track model (operator picks via §7 decision #1)

**Track A — CRM public pages (NEW, aligns with dispatch defaults as narrowed)**:
- Add OG/Twitter/JSON-LD to the ~6 indexable public routes identified in §1.3.
- Serve `/sitemap.xml` + `/robots.txt` from the FastAPI BE per-tenant.
- NEW admin page for editing tenant-portal SEO metadata (slots as a new sub-tab under existing `WebsiteSeoPage` OR as a new `/settings/portal-seo` route).

**Track B — Operator's external site (EXISTING, no work needed)**:
- 8 BE routers + `WebsiteSeoPage.jsx` already handle this. Explicitly NOT in scope — scope creep guard.

**Track C — Hybrid (Track A built on top of extending existing SEO plumbing)**:
- Reuse `aeo.py` JSON-LD generator (already proven) for CRM public-page JSON-LD emission.
- Reuse `tenants.business_card` doc for metadata source-of-truth (name, logo, website_url).
- Lightweight NEW admin UI, heavy data-reuse.

**Recommendation**: Track C. Avoids duplicate SEO code paths, reuses hardened AEO JSON-LD generator, extends `business_card` with a nested `seo` sub-document.

### 2.2 Backend architecture (Track C recommended)

**New BE endpoints**:
```
GET  /sitemap.xml                 — tenant-resolved via Host / subdomain / ?tenant= fallback
GET  /robots.txt                  — same resolver
GET  /api/tenants/portal-seo      — admin: fetch portal-SEO metadata
PUT  /api/tenants/portal-seo      — admin: update portal-SEO metadata
GET  /api/public/portal-seo/{slug}  — public: fetch tenant portal-SEO for SSR injection
```

**Data model** (extend existing `tenants.business_card` doc, do NOT introduce new collection):
```python
business_card = {
    # existing fields: name, website_url, logo, …
    "seo": {                                  # NEW nested sub-doc
        "og_title":     str,                  # default: business_card.name
        "og_description": str,                # default: business_card.description
        "og_image":     str,                  # default: business_card.logo
        "twitter_card": str = "summary_large_image",
        "twitter_site": str,                  # @handle, optional
        "canonical_base": str,                # overrides subdomain if set
        "service_areas": List[str],           # for LocalBusiness JSON-LD areaServed
        "opening_hours": List[Dict],          # for LocalBusiness JSON-LD
        "updated_at":   str,
        "updated_by_user_id": str,
    }
}
```

**Why extend `business_card` not a new collection**:
- Already carries `name`, `website_url`, `logo`, `description`.
- Existing read-path at `GET /api/tenants/business-card` can gain the nested `seo` without migrations.
- Zero schema migration — new tenants get `seo: null`, resolvers fall back to top-level `business_card` fields.

**Sitemap generation**: hand-roll in FastAPI. Enumerate the 6 indexable public routes per tenant, emit `<urlset>` XML. ~60-80 LOC in a new `backend/routers/public_sitemap.py`. No third-party dep.

**Robots.txt**: hand-roll. Per-tenant allow/disallow, defaults to allow-all for public routes + disallow all auth-gated routes. ~30 LOC in the same new router.

### 2.3 Frontend architecture

**Library pick**: **react-helmet-async** (not react-helmet).
- `react-helmet` is deprecated (not React 18+ compatible, no concurrent-mode support).
- `react-helmet-async` is the maintained fork, same API, works with React 18+ + Vite SPA, zero SSR requirement for correct behavior on CSR.
- Install cost: 1 `yarn add react-helmet-async` + root `<HelmetProvider>` wrapper in `App.js`.

**JSON-LD injection pattern**:
- Route-level component `<RouteSEO kind="LocalBusiness" tenant={...} />` that composes JSON-LD + injects via `<Helmet><script type="application/ld+json">…</script></Helmet>`.
- Reuse `backend/routers/aeo.py` JSON-LD generator — call `POST /aeo/jsonld/generate` from the FE at page mount, OR server-render the snippet in `index.html` via a Vite plugin (requires Vite SSR which is a larger lift). **Recommend CSR injection for Phase 2**; defer SSR snippet injection to a Phase 3 opportunistic ticket if crawler coverage proves insufficient.

**No TypeScript**: codebase is JS, not TS. Skip `schema-dts`; hand-roll JSON-LD payloads matching schema.org LocalBusiness / Organization / Service / ContactPoint shapes.

### 2.4 Admin UI architecture

**Where it slots**: `frontend/src/pages/settings/WebsiteSeoPage.jsx` already exists but is an external-site scanner. Options:
- **(α) New sub-tab under `WebsiteSeoPage.jsx`** — "External Scan" vs "Portal SEO" tabs. Keeps the two SEO surfaces in one settings page.
- **(β) New standalone page `PortalSeoPage.jsx` at `/settings/portal-seo`** — cleaner separation of concerns.
- **(γ) Extend `BusinessCardSettings` (if exists)** — slots under tenant-identity settings.

**Recommend (α)** — reduces nav sprawl, keeps "SEO" discoverable in one place. Operator may counter per §7 decision #4.

### 2.5 File manifest (Phase 1 scope)

| New file | LOC est | Phase |
|---|---|---|
| `backend/routers/public_sitemap.py` | ~120 (sitemap + robots) | 1 |
| `backend/routers/portal_seo_admin.py` | ~80 (CRUD endpoints) | 1 |
| `backend/tests/test_public_sitemap.py` | ~150 | 1 |
| `backend/tests/test_portal_seo_admin.py` | ~120 | 1 |
| `frontend/src/components/seo/RouteSEO.jsx` | ~80 | 2 |
| `frontend/src/components/seo/__tests__/RouteSEO.test.jsx` | ~100 | 2 |
| (modifications to existing public-route components) | ~5-10 per route × 6 routes = ~40 | 2 |
| `frontend/src/pages/settings/WebsiteSeoPage.jsx` (add tab) | ~100 edit + ~60 new component | 3 |
| `frontend/src/pages/settings/__tests__/PortalSeoAdmin.test.jsx` | ~120 | 3 |

**Total LOC estimate across phases 1-3**: ~1000 LOC source + ~500 LOC tests.

---

## 3 · Phase breakdown

### Phase 1 — BE sitemap + robots + metadata CRUD (BE only)
- Endpoints: `GET /sitemap.xml`, `GET /robots.txt`, `GET/PUT /api/tenants/portal-seo`, `GET /api/public/portal-seo/{slug}`.
- `tenants.business_card.seo` nested sub-doc.
- Pytest coverage: ~15 cases (sitemap XML shape, per-tenant resolution, robots.txt per-tenant, metadata CRUD, admin-gate on PUT, portal visibility on public endpoint, defaulting from `business_card` when `seo` is null).
- Est: ~200 LOC source + ~270 LOC tests · 2 atomic commits (BE route + admin CRUD).

### Phase 2 — FE Helmet integration + JSON-LD (FE only, depends on Phase 1)
- `yarn add react-helmet-async` + root `<HelmetProvider>` wrapper.
- `<RouteSEO>` component (fetches `/api/public/portal-seo/{slug}`, composes OG/Twitter/JSON-LD).
- Wire into 6 indexable public routes.
- Vitest coverage: ~12 cases (component renders OG tags, JSON-LD valid LocalBusiness shape, fallback when tenant SEO null, per-route canonical URL).
- Est: ~120 LOC source + ~180 LOC tests · 2 atomic commits (component + wire-into-routes).

### Phase 3 — Admin UI (FE only, depends on Phases 1 & 2)
- "Portal SEO" tab under existing `WebsiteSeoPage.jsx`.
- Form fields: OG title/desc/image, Twitter card type + handle, canonical base, service areas (chip list), opening hours (day-of-week grid).
- Vitest coverage: ~10 cases (form submits PUT, defaults from business_card, validation, admin-role gate, success toast).
- Est: ~160 LOC source + ~120 LOC tests · 1 atomic commit.

### Phase 4 (OPTIONAL) — Mobile parity
- Mobile currently has no SEO surface (customer-facing routes are app-shell, not SEO-indexable).
- **No scope**. Flagged as deferred.

---

## 4 · Integration decisions

| Decision | Pick | Justification |
|---|---|---|
| OG/Twitter meta library | **react-helmet-async** | React 18+ compat, Vite SPA friendly, zero SSR requirement, maintained fork of deprecated `react-helmet`. |
| JSON-LD construction | **Hand-roll** (reuse `aeo.py` generator where possible) | No TypeScript, so `schema-dts` adds no safety. `aeo.py` already produces schema.org LocalBusiness JSON-LD — reuse the proven generator and avoid duplicate code. |
| Sitemap generator | **Hand-roll in FastAPI** | Per-tenant resolution needs tenant-specific route enumeration; no third-party sitemap lib handles per-tenant well. ~60-80 LOC. |
| Robots.txt | **Hand-roll** | Per-tenant allow/disallow; trivial scope. |
| SSR for JSON-LD | **CSR with Helmet (Phase 2 default)**; defer SSR snippet injection to opportunistic Phase 3+ ticket | Full Vite SSR migration is a large lift (weeks). CSR coverage is sufficient for Google (JS-rendered JSON-LD is indexed since 2019); for sites with aggressive bot blocking, revisit. |
| Multi-tenant resolution for sitemap/robots | **Reuse existing `tenants.py:133-166` cascade** (Host → subdomain → ?tenant= → custom_domain) | Already battle-tested, zero new surface. |
| Metadata storage | **Extend `tenants.business_card.seo` nested sub-doc**, NOT new collection | Zero migration, reuses existing read-path, falls back cleanly to top-level `business_card` fields. |

---

## 5 · Risk + blockers

### 5.1 DEPLOYMENT HOLD impact
Per the system-notif active deployment surface at `https://app.plofv.com`: **SEO benefit is realized only after production deploy**. Preview-environment pages are not indexed by search engines (should not be — would create duplicate-content issues anyway). Phase 1-3 ship cleanly to preview + require a subsequent operator-initiated production deploy before Google/Bing/Twitter crawlers can observe the new meta tags, JSON-LD, sitemap, or robots.

**Mitigation**:
- Phases 1-3 are all additive — no public-URL changes, no removal of existing content. Zero regression risk on production until deploy.
- `robots.txt` served from preview-environment hosts MUST include `Disallow: /` to prevent accidental preview-domain indexing. Phase 1 implementation should check an env flag (`SEO_PUBLIC_INDEXABLE=true` in prod only) before emitting an allow-all robots.

### 5.2 Public-page auth gates
Current indexable candidates (§1.3): `/public/card/:slug`, `/reviews/:tenant_slug`, `/public/checkins/{slug}/feed.html`, `/f/:slug`, `/public/leads`, `/e/estimate` — all unauthenticated.

**No new whitelist decision needed**. `robots.txt` default allow-all for `/public/*` + `/reviews/*` + explicit `Disallow: /api/`, `/portal/`, `/customer-portal/`, `/dev/`, `/settings/`, `/jobs/`, `/invoices/`, `/schedule/`, `/leads/`, `/customers/`, `/dashboard/`, `/login`, `/reset-password`, `/forgot-password`, `/signup`, `/business-signup/*`, `/onboarding-wizard`, `/tenant-picker`.

### 5.3 PII leak risk from scraped tenant SEO metadata
Tenant-portal metadata is INTENTIONALLY public:
- `business_card.name`, `logo`, `website_url` are already on `GET /tenants/business-card` + the public widget surface.
- `seo.og_description` + `seo.service_areas` are operator-authored, operator-gated.
- `seo.opening_hours` is business-hours (not personal).

**Zero new PII surface** introduced by the metadata extension. Admin PUT endpoint stays admin-gated.

### 5.4 "Service list / service detail / contact" routes
Dispatch's default public-page list mentions "tenant landing, service list, service detail per service type, contact". **None of these routes exist today.** The CRM is a backend-of-office tool with public lead-funnel pages, NOT a marketing-site builder. **Operator confusion flagged** — see §7 decision #2.

### 5.5 Mobile parity
Mobile app is operator-facing (field techs + admins). No customer-public mobile surface. Phase 4 (mobile parity) is NOT applicable; the dispatch's inclusion was precautionary. **Formally scoped out.**

### 5.6 Existing JSON-LD on widget surface
`backend/routers/public_widget.py:524-536` already emits LocalBusiness + ItemList JSON-LD on `/public/checkins/{slug}/feed.html` + `/widget/preview/{slug}`. **Phase 2 must NOT duplicate** — the `<RouteSEO>` component should check if a route is widget-sourced BE-rendered (where JSON-LD is already present) and skip JSON-LD emission for those routes. Doc flag for Phase 2 implementation.

### 5.7 Scope creep risk
Existing 8 SEO/AEO routers are extensive. Developers could easily be tempted to "unify" the two SEO surfaces (Track B operator-WordPress-SEO + Track A CRM-portal-SEO) in one ticket. **Hard scope lock** — Track B is explicitly out of scope. Phase 1-3 touch ONLY CRM-portal-SEO. Any unification is a SEPARATE P3 refactor ticket raised AFTER Track A ships.

---

## 6 · Default scope confirmation

**Scope deltas vs dispatch defaults**:

| Dispatch default | Reality / recommendation |
|---|---|
| (b) customer portal SEO-safe pages | **MISREAD** — authed portal is NOT SEO-indexable. Reinterpret as "portal-adjacent public pages" (public card, reviews widget, lead intake, public estimate landing). CONFIRM with operator. |
| (c) admin SEO tooling for tenant portal metadata | ✅ confirmed, new admin UI needed. Existing `WebsiteSeoPage.jsx` is external-site scanner, not portal metadata editor. |
| Win #1 OG/Twitter | ✅ confirmed. Zero today. High value. |
| Win #2 Meta title + description | ✅ confirmed. Only root `index.html` has static values today. |
| Win #3 JSON-LD | **PARTIAL** — widget surface already has it; portal/public-card/reviews/lead-intake do NOT. Expand to those surfaces. |
| Win #4 XML sitemap | ✅ confirmed. Zero today at CRM backend. |
| Win #5 robots.txt | ✅ confirmed. Zero today at CRM backend. |
| Win #6 Admin UI | ✅ confirmed. See §2.4 for slot options. |
| SSR scope: client-side Helmet | ✅ confirmed with caveat — defer SSR snippet injection to opportunistic Phase 3+ ticket if CSR JSON-LD proves insufficient. |
| Prioritized public pages | **FLAG** — dispatch names "service list / service detail / contact" which DO NOT exist. Replace with the 6 indexable routes from §1.3. |
| Multi-tenancy | ✅ confirmed — reuse existing `tenants.py` cascade. |

---

## 7 · Open operator decisions (approve before Phase 1 dispatch)

5 Y/N decisions needed before Phase 1 can safely dispatch:

**Decision #1 — Track selection (Y/N on Track C hybrid)**:
- (Y) Track C recommended — build CRM-portal-SEO on top of existing SEO plumbing, reuse `aeo.py` JSON-LD generator + extend `tenants.business_card.seo` nested sub-doc.
- (N) Pick Track A greenfield instead — ignore existing plumbing, build parallel CRM-portal-SEO stack.
- **Default on no-reply**: Y (Track C).

**Decision #2 — Public-page scope substitution (Y/N)**:
- The dispatch names "tenant landing, service list, service detail per service type, contact" as prioritized public pages. **These routes DO NOT exist in the CRM.** Substitute with the 6 indexable routes identified in §1.3:
  1. `/public/card/:slug` (tenant business card landing)
  2. `/reviews/:tenant_slug` (public reviews widget)
  3. `/public/checkins/{slug}/feed.html` (public check-in feed — SKIP JSON-LD, already BE-rendered)
  4. `/f/:slug` (public lead intake form)
  5. `/public/leads` (public lead intake generic)
  6. `/e/estimate` (public estimate landing)
- (Y) accept substitution and scope Phase 2 to these 6 routes.
- (N) operator wants the dispatched route list — would require NEW route scaffolding (tenant landing + service list + service detail + contact) which is a MUCH larger scope (3-4 weeks additional) and needs its own feature ticket SEPARATE from SEO.
- **Default on no-reply**: Y (substitution).

**Decision #3 — Metadata storage location (Y/N)**:
- (Y) extend existing `tenants.business_card.seo` nested sub-doc. Zero migration, reuses existing read-path.
- (N) new standalone `db.tenant_seo_meta` collection. Pro: cleaner separation. Con: migration + new read-path + potential sync drift against business_card.
- **Default on no-reply**: Y (extend business_card).

**Decision #4 — Admin UI slot (Y/N on tab)**:
- (Y) new "Portal SEO" tab under existing `WebsiteSeoPage.jsx` — one SEO settings page covering both external-site scan + portal-metadata editor.
- (N) new standalone page `/settings/portal-seo` — cleaner separation but adds nav sprawl.
- **Default on no-reply**: Y (tab under WebsiteSeoPage).

**Decision #5 — Preview-environment robots policy (Y/N on hard-disallow)**:
- (Y) preview environment serves `robots.txt` with `Disallow: /` (via env flag `SEO_PUBLIC_INDEXABLE=true` for prod only) to prevent accidental duplicate-content indexing of preview URL.
- (N) preview matches prod — allows indexing on preview too (risk: duplicate-content SEO penalty).
- **Default on no-reply**: Y (hard-disallow on preview).

---

## 8 · Deployment-realization timeline

| Phase | Ships to preview | Visible on prod |
|---|---|---|
| 1 (BE) | immediately on commit | after next `app.plofv.com` production deploy |
| 2 (FE Helmet/JSON-LD) | immediately on commit | same deploy as Phase 1 |
| 3 (Admin UI) | immediately on commit | same deploy as Phase 1 |

**Full SEO value realized only after**:
1. Operator initiates production deploy.
2. Operator fills in tenant SEO metadata via new admin UI (OR accepts defaults derived from `business_card`).
3. Search engines re-crawl (typically 1-7 days post-deploy; `GET /sitemap.xml` submission to Google Search Console accelerates to ~24 hours).

---

## 9 · Guardrail compliance (recon)

- ✅ No code changes shipped this cycle.
- ✅ No BE schema migrations proposed; `business_card.seo` is additive-nullable.
- ✅ No FE package installs this cycle (`react-helmet-async` install deferred to Phase 2).
- ✅ No mobile edits proposed; Phase 4 formally scoped out.
- ✅ No testing agent used.
- ✅ No scope creep into AI Features or CAD Editor — those are separate Phase 0 tickets per dispatch chain.
- ✅ Route-optimizer V15 injection + Rauschenberger-urgency V15 #5 injection both remain HELD; no action taken, no code written against them.
- ✅ Deployment HOLD flagged in §5.1 — SEO value realization depends on production deploy, not on preview-environment ship.

---

## 10 · Next action

**Operator**: approve or counter the 5 decisions in §7. On approval of defaults (all Y), dispatch Phase 1 (BE sitemap + robots + metadata CRUD + pytest).

**Recon doc committed atomically**. No code touched.
