# SPEC: MARCO AI Web Builder (queued brief)

**Status:** QUEUED — position 6. **DO NOT START.**
Saved at: Feb-2026 (during MARCO Sub-phase D debug window)

## Scope
Upgrade the existing "Public Forms" system into a full AI-generated marketing site builder.

## Sub-phases (5)

### WB-A — Site Data Model
- New `websites` collection. Document shape:
  - `_id`, `tenant_id`, `slug`, `name`, `status` (draft/published), `pages: [Page]`, `global_theme: Theme`, `navigation_menu: [NavItem]`, `custom_domain: str | null`, `lead_sense_injected: bool` (auto), `created_by`, `created_at`, `updated_at`
- `Page`: `{id, path, title, meta, sections: [Section]}`
- `Section`: discriminated union — `Hero | Features | Testimonials | Gallery | RichText | FormEmbed | ImageBlock` (extend existing Section registry from Marketing Form Builder Phase 4)
- `Theme`: `{primary, secondary, fontFamily, buttonRadius, ...}` — reuse Marketing Form Builder theme schema, add cross-page globals
- Extend existing `marketing_forms` form model NOT `websites` — form pages remain forms. Sites are new.
- Add CRUD router `backend/routers/websites.py`: GET/POST/PATCH/DELETE + `POST /api/websites/{id}/publish` state transition.
- Idempotent migration `backend/migrations/websites_collection_v1.py` — creates indexes on `tenant_id`, `slug`, `custom_domain`.

### WB-B — AI Site Generation (NOVA + SCRIBE + CREATIVE orchestration)
- New endpoint `POST /api/websites/generate` accepting `{topic: str, tenant_id: str}`.
- Flow:
  1. MARCO (or ATLAS if user prefers workforce chief-of-staff routing) receives the "Build a site for [Topic]" utterance via existing conversation surface OR direct endpoint call.
  2. MARCO invokes `delegate_task` on NOVA with `{action: "draft_site_structure", topic}`.
  3. NOVA returns `{pages: [...], navigation_menu: [...]}` skeleton (page structure + section types, no copy).
  4. NOVA invokes `delegate_task` on SCRIBE for each section requiring copy → SCRIBE fills `content` fields.
  5. NOVA invokes `delegate_task` on CREATIVE for `global_theme` + placeholder image prompts.
  6. Final `websites` doc written with `status="draft"`.
- Uses the tool loop from MARCO Sub-phase B. Cap iterations sensibly (probably 20 for a full-site build vs. the standard 5).
- Fallback: if any specialist fails, log warning and use a sensible default section/copy.

### WB-C — Visual Designer expansion
- Extend existing Marketing Form Builder UI (grep `MarketingFormBuilder*.jsx` or `FormBuilder*.jsx`) to render `websites` documents as multi-page sites.
- Add `Global Theme` settings panel — applied across all pages.
- Add page management: add/remove/reorder pages, set as home, edit path.
- Auto-inject the Lead-Sense pixel snippet into every page's `<head>` when `lead_sense_injected=true` (default true) and tenant has a `lead_sense_pixel_id` set. Rendered server-side on page publish.

### WB-D — Custom Domains
- Add `Site Settings → Custom Domain` panel: input for tenant's custom domain (e.g., `web.plofv.com`), instructions showing the required CNAME target, DNS verification status polling.
- Grep for existing CNAME / custom-domain logic — the brief says "using our existing CNAME/DNS logic". If it exists, reuse. If not, add minimal:
  - `POST /api/websites/{id}/custom-domain` — sets requested domain
  - `POST /api/websites/{id}/custom-domain/verify` — polls DNS, updates status
  - Router logic to serve `websites` docs when incoming request `Host` matches a verified `custom_domain`
- Certificate handling: if the platform has Let's Encrypt / ACME wiring, use it. Otherwise document as a manual ops step in the commit.

### WB-E — UI: sidebar grouping + branding
- `adminNav.js`: add `Marketing → Website Builder` entry pointing at the new builder route.
- Preserve existing sidebar order; place under the existing Marketing group (may need to promote Marketing to an expandable group if not already).
- Palette: Navy `#1B1F5C` / Blue `#3B82F6` per the standard brand tokens.

## Dependencies (must land before WB starts)
1. 18-employee hierarchical workforce deploy (creates NOVA, SCRIBE, CREATIVE personas + `delegate_task` role_level guards)
2. Self-hosted MARCO Lead-Sense pixel (WB-C auto-injection depends on `lead_sense_pixel_id` being set on tenants)
3. MARCO Sub-phase D + E stable

## Design forks to resolve inline when dispatched
- Existing Marketing Form Builder architecture — does it already support multi-page docs, or are forms single-page? If single-page, WB-A + WB-C become a significant refactor rather than an extension.
- Existing CNAME/DNS logic — grep first. If absent, WB-D scope balloons substantially.
- Whether sites live in the same schema as forms with a discriminator, or fully separate collections (brief recommends fully separate — cleaner).
