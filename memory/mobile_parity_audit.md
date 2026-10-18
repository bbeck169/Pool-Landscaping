# Mobile Parity Audit — Customer Portal fixes (TD-67 … TD-77)

Pre-flight only — **no code written**. Audited at HEAD `b856d35d6` against web commits of record.
Live data probed on preview with `preview-portal0161@preview.local` + `customer@aquaterra.com`.

> Label note: commit subjects differ from the dispatch labels — `c782fd23a` is titled **td68** (theme bundle,
> dispatch says TD-70) and `b6244ad2a` is titled **td70** (PAID stamp, dispatch says TD-72). Also relevant and
> not in the dispatch list: `227a471ed` td76b (`withAuthToken` stamps `?auth=` instead of `?token=`).

## 1. Per-fix status

| Fix | Web change | Mobile screen(s) | Current mobile | Gap? |
|---|---|---|---|---|
| **TD-67** `?auth=` for image src | BE accepts `?auth=`; web stamps it on `/api/customers/me/jobs/…/photos/…` | `app/portal/photos.tsx`, `app/portal/service-report/[id].tsx`, `app/portal/videos.tsx` | Photos: `photo.thumb \|\| photo.url` passed raw. Videos already use `?auth=` (`buildStreamUrl`) and read `.videos` / `entity_title` | **YES** (photos). Videos already at parity |
| **TD-76 A** canonical `{thumb_url, full_url}` + grouped layout | Grid `thumb_url → thumb → url`; lightbox `full_url → url → thumb_url → thumb`; date header → visit sub-header → photos; days DESC, visits `submitted_at` ASC then `job_id` ASC | same as above | Grid ignores `thumb_url`; lightbox uses `url`; groups by **date only**, items `submitted_at` **DESC**, no visit sub-header; rows without `submitted_at`/`created_at` are **dropped**. SR detail renders `sr.photos[].url` only and **never renders `sr.job_photos`** (web does) | **YES** |
| **TD-69** service-type resolver | `resolveServiceType` — scans template/service_type/service_line/service_category + `job.*`; landscape wins; chemistry only when `kind === "pool"` | `app/portal/service-reports.tsx`, `app/portal/service-report/[id].tsx` | Both still have the OLD inline first-truthy `reportKind()` (the exact TD-69 bug). SR detail: single-body chemistry gated on pool, but **the multi-water-body block (`water_bodies.length > 1`) is NOT gated**; web gates it on `kind === "pool"` | **YES** |
| **TD-68/70** theme bundle (white card on navy) | `PortalPageShell` = white card on deep-navy page bg on SR list, SR detail, Reviews | `service-reports.tsx`, `service-report/[id].tsx`, `portal/review-submit.tsx` | Only `portal/home.tsx` uses navy `#03002e`. SR list / SR detail = light grey `#F4F4F5` with white cards; review-submit = white | **YES** |
| **TD-75** SR list search removal + darker copy | Removed "Search notes, name, address…" input; instructional copy → `#374151` | `service-reports.tsx` | Mobile **never had** the search input or the "Click any visit below…" copy | **NO-OP** |
| **TD-74** remove NEXT VISIT overlay | Hero overlay removed | `portal/home.tsx` | Mobile hero = Balance Due + 2 pills; **no** next-visit overlay | **NO-OP** |
| **TD-71** invoice list Created date + `Import #<n>` resolver | `Created MM/DD/YYYY` under title; 4-branch title resolver | `app/portal/invoices.tsx` | Raw `item.title`; no Created line. Same endpoint as web (`/quotes?doc_type=invoice`) | **YES** |
| **TD-72b** estimates list title resolver | Same resolver on estimates | `app/portal/estimates.tsx` | Raw `item.title` | **YES** |
| **TD-77** remove Total outstanding tile | Tile removed | `app/portal/invoices.tsx` | Mobile **never had** the tile | **NO-OP** |
| **TD-73** Edit Profile green + modal retheme | Hero "Edit profile" pill + modal Save → `#16A34A` (Call Now green); white modal, light inputs | `portal/home.tsx`, `portal/profile.tsx` | **No hero Edit-profile pill and no modal** on mobile. Profile is a full page with brand-colour `PrimaryButton` Save. Note: mobile Call Now is **teal `#0F766E`**, not web `#16A34A` | **NO DIRECT PARALLEL** — operator decision |
| **TD-72/70** PAID stamp top-center | CSS rubber-stamp overlay moved to top-center | `app/invoice/[id].tsx`, `src/utils/exportInvoicePdf.ts` | Customer invoice view shows a green **header chip** (`invoice-paid-chip`), not an overlay stamp. The only mobile PDF (`exportInvoicePdf`, expo-print, called from **admin** `app/quote/[id].tsx`) has **no stamp at all** | **SKIP** — no stamp to reposition |

## 2. Live-data findings that shape the implementation

- `GET /api/portal/photos` returns **relative** URLs (`/api/public/job-photo/…`). RN `<Image>` cannot resolve relative URIs on native, so mobile Photos is likely rendering blank tiles on device today. Fix: prefix `EXPO_PUBLIC_BACKEND_URL` for `/`-relative paths. Public paths load with no auth (200), so no token is needed there.
- Some `/portal/photos` rows have **all URL fields empty** (`source: "job"`). They should be skipped, not rendered as blank tiles.
- SR detail `job_photos[]` carries canonical **absolute** URLs on `/api/customers/me/jobs/…/photos/…`. That endpoint returns **401 without auth**, 200 with Bearer or `?auth=`. BE emits **no** `?auth=` in the URL, so mobile must stamp it (port of `withAuthToken`).
- Their host is `APP_PUBLIC_URL` = `https://app.plofv.com` (prod) even on preview, so in **preview** these tiles will hit prod with a preview token and fail. Prod is fine. Screenshots of SR-detail job photos may therefore show broken tiles in preview.
- **Possible web regression (FYI, out of scope):** TD-76d dropped `withAuthToken` from web SR-detail job photos and uses `full_url` raw. The handler only accepts Bearer or `?auth=` (no cookie path), so browser `<img>` loads of those URLs likely 401 on web too. Mobile will NOT mirror this; it will stamp `?auth=`.
- No portal account in preview has `Import #<n>` titles, so TD-71/72b can be proven only via Jest fixtures. The screenshot will show the Created line.
- `GET /api/portal/videos` returns 0 videos for the seed customer, so Videos can't be screenshot-verified.

## 3. Mobile surfaces with NO web parallel (operator decides)

1. `app/portal/service/[id].tsx` — portal job detail photo grid uses `p.url || p.data_url` raw, the same relative-URL problem. Not in any TD commit. **Proposed: leave alone** unless approved to route through the new media-URI helper.
2. `app/invoice/[id].tsx` PAID header chip — a native chip, not a stamp. **Proposed: leave alone.**
3. `src/utils/exportInvoicePdf.ts` (admin quote/invoice PDF via expo-print) — no stamp exists. **Proposed: leave alone** (adding a stamp = new feature).
4. `app/portal/profile.tsx` — full-page profile editor, where web has a modal. See TD-73 options below.
5. `app/reviews.tsx` is the **admin** reviews screen, not the portal. Portal Reviews parallel = `app/portal/review-submit.tsx`.

## 4. Proposed commit scoping (adjusted to reality)

| # | Commit | Files | Content |
|---|---|---|---|
| 1 | `m-td67-td76` | new `src/lib/portalMediaUri.ts`; `app/portal/photos.tsx`; `app/portal/service-report/[id].tsx`; new test | Helper: data-URI passthrough → `/`-relative prefixed with backend URL → `?auth=` stamped (idempotent, fragment-safe, port of `withAuthToken`) only on `/api/customers/me/` + `/api/files/` paths. Photos: canonical field order + skip empty rows + date→visit grouping with web tiebreak + lightbox `full_url`. SR detail: absolutize `sr.photos` + **add the `job_photos` grid** (web renders it; mobile never did) |
| 2 | `m-td68-theme` (+ TD-75 no-op noted) | `service-reports.tsx`, `service-report/[id].tsx`, `review-submit.tsx`; test | Navy `#03002e` page bg + white rounded content card, matching `portal/home.tsx`. Header stays readable on navy |
| 3 | `m-td69` (+ TD-74 no-op noted) | new `src/lib/portalServiceType.ts`; `service-reports.tsx`; `service-report/[id].tsx`; test | Port the resolver; replace both inline `reportKind()`s; gate the multi-water-body block on `kind === "pool"` |
| 4 | `m-td71-td72b` (+ TD-77 no-op noted) | new `src/lib/portalInvoiceTitle.ts`; `invoices.tsx`; `estimates.tsx`; test | Title resolver on both lists + `Created MM/DD/YYYY` line on invoices |
| 5 | `m-td73` | **pending operator choice** | (a) skip; (b) recolour profile Save to `#16A34A` + white inputs/light-grey borders; (c) add hero Edit-profile pill + modal (new feature) |
| 6 | `m-td72-pdf` | — | **Skip** — no stamp surface on mobile |

Open questions: TD-73 option a/b/c? · Also recolour mobile Call Now teal → `#16A34A`? · Touch `portal/service/[id].tsx` photos? ·
Add web's `work_class === "repair"` chemistry suppression to the TD-69 commit (web has it; it's not in the TD list)?
