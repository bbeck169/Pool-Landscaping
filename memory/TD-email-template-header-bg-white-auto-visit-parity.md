# TD-email-template-header-bg-white-auto-visit-parity · follow-up (P3)

**Parent:** `TD-email-template-header-bg-white` (shipped as a sibling of this doc, pending operator logo-contrast confirmation).

## Gap

`backend/services/auto_visit_email.py` builds its OWN branded email
shell using `brand_primary_hex` for header bg (lines 416–1216,
multiple table-based card renderers). It does NOT use
`services.email.theming.wrap_html_in_shell`, so the Ticket O
header-bg-white flip does not affect auto-visit summary emails.

If operator wants brand parity — every customer-facing email with
a shared visual language — auto-visit emails need the same flip.

## Why P3

- Auto-visit summary emails are a different template family
  (visit summaries, before/after photos, service completion
  recaps) than the invoice/quote/dunning emails Ticket O
  covered.
- Operator's Ticket O framing scoped "ALL email templates" but
  recon-anchored on `wrap_html_in_shell`. Auto-visit is
  explicitly a separate shell with its own design history.
- Not a correctness bug. Pure visual-brand consistency.

## Fix shape

Two options:

**Option A — port auto-visit to the canonical shell.**
Rewrite `_build_html` et al. to pass a body-only fragment to
`wrap_html_in_shell`. Biggest payoff (one shell to maintain)
but larger diff — auto-visit's layout logic is deeply
intertwined with its own tables.

**Option B — mirror the Ticket O flip in-place.**
Change the local `brand_primary_hex` → `#FFFFFF` substitution
only at the header rendering site(s), keep the rest of the
auto-visit template structure. Smaller diff, keeps the two
shells independent (two maintenance surfaces).

Recommendation: Option B. The two shells have diverged
intentionally over time (quote/invoice stay compact,
auto-visit uses photo cards + table layouts). Collapsing them
is a bigger project than this ticket wants to be.

## Testing contract

- Auto-visit email HTML output contains `background:#FFFFFF`
  on the header cell (regression lock mirroring the Ticket O
  pytest).
- Logo contrast fallback (if auto-visit has a no-logo text
  header, same `#FFFFFF`-on-`#FFFFFF` invisibility risk) —
  flip fallback text to a dark color.
- Visit summary rendering (customer name, photos, service
  notes) unchanged.

## Priority rationale

P3 — brand consistency, no correctness impact. Depends on
operator confirming the Ticket O flip is working as expected
on prod customer-facing emails first.
