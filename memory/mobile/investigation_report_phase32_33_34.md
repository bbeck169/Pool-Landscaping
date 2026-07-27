# Investigation Report — Phase 32, 33, 34 Delegation Briefs

**Generated**: 2026-07-27
**Total briefs examined**: 31 files in `/app/memory/delegations/`
**Phases in scope**: Phase 32 (1), Phase 33 (10), Phase 34 (16)
**Earlier phases (already done)**: Phase 22, 27, 28, 29

---

## Phase 33 — Customer Portal Parity (10 briefs → 10 ACTIONABLE)

| # | Brief | Surface | Priority | Status |
|---|-------|---------|----------|--------|
| 1 | `phase33_brand_logo_mobile.md` | Both (login, splash, all screens) | P2 | Implement |
| 2 | `phase33_forgot_password_mobile.md` | Both (auth) | P2 | Implement (UI stub only) |
| 3 | `phase33_portal_home_hero_top_mobile.md` | Customer Portal | P2 | Implement |
| 4 | `phase33_portal_top_cta_row_mobile.md` | Customer Portal | P2 | Implement |
| 5 | `phase33_portal_ask_concierge_highlight_mobile.md` | Customer Portal | P2 | Implement |
| 6 | `phase33_portal_ask_concierge_reorder_mobile.md` | Customer Portal | P2 | Implement |
| 7 | `phase33_portal_last_visit_above_concierge_mobile.md` | Customer Portal | P3 | Implement |
| 8 | `phase33_portal_refer_friend_highlight_mobile.md` | Customer Portal | P2 | Implement |
| 9 | `phase33_portal_media_date_grouping_mobile.md` | Customer Portal | P2 | Implement |
| 10 | `phase33_portal_request_service_simplify_mobile.md` | Customer Portal | P1 | Implement |

---

## Phase 34 — Mixed (16 briefs → 8 ACTIONABLE, 4 ADMIN-SKIP, 4 DEFERRED)

### Actionable (8)

| # | Brief | Surface | Priority | Status |
|---|-------|---------|----------|--------|
| 1 | `phase34_business_card_website_and_width_mobile.md` | Customer Portal | P2 | Implement |
| 2 | `phase34_portal_tos_banner_remove_mobile.md` | Customer Portal | P3 | Implement |
| 3 | `phase34_referral_reward_amount_mobile.md` | Customer Portal | P2 | Implement |
| 4 | `phase34_portal_tour_v2_mobile.md` | Customer Portal | P2 | Implement (lightweight) |
| 5 | `phase34_auto_send_completion_notify_mobile.md` | Tech App | P1 | Implement |
| 6 | `phase34_password_reset_flows_mobile.md` | Both (auth) | P1 | Implement |
| 7 | `phase34_leads_status_standardization_mobile.md` | Both (leads views) | — | Implement (points to BB+CC brief) |
| 8 | `phase34_ai_employees_dedupe_mobile.md` | Both | — | Minimal (key props) |

### Admin-Only — SKIP

| # | Brief | Reason |
|---|-------|--------|
| 1 | `phase34_admin_edit_any_job_mobile.md` | Admin job detail surface |
| 2 | `phase34_bulk_select_crm_wide_mobile.md` | 7 admin-only CRM surfaces |
| 3 | `phase34_invoices_estimates_bulk_select_mobile.md` | Admin bulk-select (bulk-delete part) |
| 4 | `phase34_leads_bulk_status_change_mobile.md` | Admin bulk status change |
| 5 | `phase34_task_ll_ui_wrapup_web_brief.md` | Web-only reference doc |

### Deferred / Blocked

| # | Brief | Reason |
|---|-------|--------|
| 1 | `phase34_digest_attention_tracker_deferred.md` | Explicitly DEFERRED |
| 2 | `phase34_portal_profile_editable_mobile.md` | Backend NOT YET SHIPPED |
| 3 | `phase34_review_gating_mobile.md` | Backend NOT YET SHIPPED |

---

## Phase 32 — Offline Capability (1 brief → FOUNDATION ONLY)

| # | Brief | Surface | Priority | Status |
|---|-------|---------|----------|--------|
| 1 | `phase32_mobile_offline_capability.md` | Tech App | P1 | Foundation (bundle + sync pill + basic outbox) |

Full outbox/conflict resolution deferred to conserve context. Foundation includes:
- `GET /api/mobile/offline-bundle` download + local cache
- Sync status pill in tech header
- Basic `POST /api/mobile/sync` integration
- NetInfo connectivity detection

---

## Execution Order

1. **Phase 33** — Portal home restructure, brand logo, forgot password, media date grouping, request service simplify
2. **Phase 34** — Business card, ToS removal, $55 referral, tour v2, auto-send completion, password reset, leads enum, AI dedupe
3. **Phase 32** — Offline foundation

---

## Key Risks & Notes

- Portal Home needs major rewrite: new section order, gradient cards, CTA row
- Forgot Password + Reset Password are UI stubs until backend ships `POST /api/auth/forgot-password`
- Password reset flows (Phase 34) supersede the Phase 33 stub with actual endpoint wiring
- Review gating blocked on backend — skip entirely
- Profile editable blocked on backend — skip entirely
- Offline (Phase 32) is massive scope — foundation approach covers bundle download + status UI
