# Feature — Public Check-ins Feed · JSON-LD Structured Data (SEO)

**Phase**: Feb-2026  
**Scope**: Backend only (pure SEO enhancement — no user-facing UI change).

## Summary

Public check-in surfaces (feed JSON, embed widget preview, and a new
server-rendered HTML feed page) now emit schema.org JSON-LD blocks so
search engines can index them without executing JavaScript. Two blocks
per page:

- **`LocalBusiness`** — one per page, hydrated from the tenant's
  business card (company name, phone, website, service area).
- **`ItemList`** wrapping one **`Service`** per approved check-in with
  `serviceType`, `areaServed` (`PostalAddress` city + region), and an
  auto-generated neutral factual `description`.
- **`geo`** (`GeoCoordinates`) — attached to a Service only when both
  `lat_public` and `lng_public` are populated on the source row.

## Emitted schema.org types

| Type | Where | When |
|------|-------|------|
| `LocalBusiness` | JSON feed (`jsonld.local_business`), HTML feed head, widget preview head | Always (one per page) |
| `ItemList` | JSON feed (`jsonld.item_list`), HTML feed head, widget preview head | Always (one per page) |
| `Service` (nested inside `ItemList.itemListElement[].item`) | Same three surfaces | Per approved check-in |
| `GeoCoordinates` (nested in `Service.geo`) | Same three surfaces | Only when `lat_public` + `lng_public` are floats |
| `PostalAddress` (nested in `LocalBusiness.address` and `Service.areaServed`) | Same three surfaces | Only when city / region resolvable |

## Auto-description generator

Deterministic per `(service_type, city, state, zip)` combination. One
sentence, factual, no marketing hyperbole per Google's spam policy
(<https://developers.google.com/search/docs/essentials/spam-policies>):

| Inputs available | Output |
|------|--------|
| type + city + state + zip | `"{Type} service completed in {City}, {ST} {Zip}."` |
| type + city + state | `"{Type} service completed in {City}, {ST}."` |
| type + city only | `"{Type} service completed in {City}."` |
| type + state only | `"{Type} service completed in {ST}."` |
| type only (no location) | `"{Type} service completed in the local area."` |
| No type at all | `"Service completed in the local area."` |

Fallbacks are deterministic — same inputs always render the same
sentence, so the HTML byte-stream stays stable and Google's Rich
Results Test never sees a moving target.

## `geo` inclusion criterion

- `Service.geo` is only emitted when **both** `lat_public` and
  `lng_public` on the source `public_checkins` row can be cast to
  `float`. These are the obfuscated (~ ±300ft) coords the tech-submit
  path writes; they are safe to expose publicly.
- Malformed coords (strings, `None`, out-of-range) silently drop the
  `geo` block. The Service still validates as schema.org.
- Rows without coords surface via the description-only path — the
  wider customer-geocoding backfill (previous phase) is populating
  these over time.

## `postalCode` — intentionally omitted

The upstream `mask_address()` helper strips zip on the way into
`masked_address` to protect customer privacy. This phase does **not**
re-attach zip from `raw_address`; that would defeat the mask. Zip is
supported by the description generator when callers have a safe
zone-level source, but no current surface passes one.

## Embedding strategy

Three surfaces, all crawler-safe:

1. **JSON feed** — `GET /api/public/checkins/{slug}/feed`  
   Now returns a top-level `jsonld: { local_business, item_list }`
   dict. Existing sanitized `checkins` array shape is unchanged
   (whitelist test still passes).

2. **NEW server-rendered HTML feed** — `GET /api/public/checkins/{slug}/feed.html`  
   Returns a full HTML document with **two** `<script
   type="application/ld+json">` blocks inside `<head>` (one
   LocalBusiness + one ItemList). Minimal visible grid below so the
   page is also human-readable. CORS-open + 5-minute cache.

3. **Widget preview HTML** — `GET /api/widget/preview/{slug}`  
   Same two JSON-LD blocks are now emitted **server-side** in the
   preview HTML head, replacing the previous JS-only inject path.
   Client widget still injects its own JSON-LD block on external host
   sites (via `injectJsonLd()` inside `widget.js`) for defense in
   depth, but crawlers can now see the schema on the preview URL
   without executing JS.

The embed widget script (`/api/widget.js`) is unchanged in this phase
— its existing client-side JSON-LD inject remains as a fallback for
sites that embed the widget directly without hitting the HTML feed.

## Widget parity notes

- Widget preview and HTML feed emit **identical** JSON-LD payloads
  because both call `_load_feed_ld()` and `_render_jsonld_scripts()`.
- The `.js` widget's client-side `injectJsonLd()` is intentionally a
  lighter shape (`LocalBusiness` + `makesOffer`) — kept for backwards
  compat; sites that want full structured data should point crawlers
  at the `feed.html` URL instead.

## API surface delta

- **New route**: `GET /api/public/checkins/{tenant_slug}/feed.html`  
  (plus its `OPTIONS` twin for CORS pre-flight)
- **Modified response**: `GET /api/public/checkins/{tenant_slug}/feed`
  now includes a `jsonld` key at the response root. All existing keys
  and the check-in whitelist are unchanged.
- **Modified response**: `GET /api/widget/preview/{tenant_slug}` HTML
  now embeds JSON-LD in `<head>`.

**OpenAPI paths**: 1743 → **1744** (+1 net).

## Test coverage

Backend: `backend/tests/test_public_checkins_jsonld.py` — **16 tests
passing**:

- Description generator: 5 shape cases (full / with zip / partial /
  fallback / underscore-type)
- LocalBusiness: shape + omits-empty
- Service block: geo included when coords present, omitted when
  missing, omitted on malformed coords
- ItemList shape (position + wrapping)
- Feed JSON-LD top-level composition
- Feed JSON endpoint: `jsonld` field present, `geo` only on
  with-coords rows
- Feed HTML endpoint: two `<script type="application/ld+json">`
  blocks, both parse as valid JSON, CORS enabled
- Widget preview: same two schemas server-rendered into `<head>`

Legacy `backend/tests/test_public_widget.py` — all **13 tests still
pass** (no regression).

## SEO citation — why factual / no keyword stuffing

Per Google's [spam policy](https://developers.google.com/search/docs/essentials/spam-policies),
auto-generated content that adds no value (keyword-stuffed
descriptions, marketing hyperbole) risks manual actions. This
implementation:

- Uses a single factual sentence per Service.
- Never repeats the service type more than once.
- Never adds superlatives ("best", "fastest", etc.).
- Deterministic output → search-engine snapshots stay byte-stable.

## Out of scope

- Mobile SEO surface (there is no mobile crawler entry point).
- AI Employees RAG (separate queued phase).
- Customer geocoding changes (previous phase already shipped).
- Check-in submission or moderation logic.
- A–F backlog items.
