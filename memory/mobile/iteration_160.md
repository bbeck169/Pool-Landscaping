# Iteration 160 — TD-96-mobile (lead-detail action buttons)

Audit: `memory/mobile/td96_mobile_audit.md`. Decisions D1-D4 approved by the operator. Owner gets no mobile support (the backend decides).

## Web → mobile mapping
| Web | Mobile |
|---|---|
| Header `lead-detail-send-sms` / `-send-email` (canCompose) | "Reach out" card tiles, same testids, `isAdminPlus` |
| `LeadComposeModal` | `src/components/leads/LeadComposeSheet.tsx` (RN Modal + KeyboardAvoidingView) |
| Actions `lead-create-quote` + `-count` (isAdmin) | Full-width indigo button in the Reach-out card, `isStrictAdmin` |
| `lead-linked-quotes-panel` | `src/components/leads/LeadLinkedQuotesPanel.tsx`, mounted after the Actions card |
| View all → `/quotes?lead=` | Non-link `lead-linked-quotes-more` "+N more" (TD-96-g1) |
| `QuoteInvoiceNew` lead hydration | `app/quote/new.tsx` `GET /leads/{id}` |

## Known / deferred
- TD-96-g1, TD-96-g2 (web, P2), TD-96-mobile-reap, -owner-gate, -status, -timeline (P3) are all logged in TECH_DEBT.md.
- Manager role is verified by jest only (no manager creds). No live SMS/email send was fired.
- No new dependencies.
