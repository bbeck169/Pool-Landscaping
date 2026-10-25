# TD-email-template-header-bg-white-portal-welcome-legacy · follow-up (P3)

**Parent:** `TD-email-template-header-bg-white` (shipped as a sibling of this doc, pending operator logo-contrast confirmation).

## Gap

`backend/emailer.py:95-110` renders the portal-welcome email with a
hardcoded direct-HTML header card:

```python
<div style="background:#003C5F;padding:24px;border-radius:12px 12px 0 0;">
  <h1 style="color:#fff;margin:0;font-size:20px;">{company_name}</h1>
```

- Does NOT go through `wrap_html_in_shell`.
- Uses a hardcoded `#003C5F` dark-blue (not even the tenant's
  `primary_hex` — this is a legacy pre-shell template that
  predates the shared branding plumbing).
- Header has a 12px top-corners `border-radius` + 24px padding —
  different design language than the current shared shell.

If operator wants brand parity across all customer-facing emails,
this legacy template needs the same header-bg-white flip (and
probably a parallel ports-to-shell cleanup).

## Why P3

- Portal-welcome fires on initial customer-portal activation —
  low frequency compared to invoice reminders / dunning.
- Legacy pre-shell template with its own design history.
- Not a correctness bug. Visual-brand consistency.

## Fix shape

Two options:

**Option A — port portal-welcome to the canonical shell.**
Rewrite the embedded card renderer to pass a body-only fragment
to `wrap_html_in_shell`. Decouples portal-welcome from its
hardcoded `#003C5F` + removes a one-off template path.

**Option B — flip in-place.**
Change `background:#003C5F` → `background:#FFFFFF` + flip the
`color:#fff` h1 text to a dark color (same invisible-text
problem as the main shell's text-fallback header). Add the
same `border-bottom:1px solid #E5E7EB` separator Ticket O
ships on the shared shell.

Recommendation: Option A for the eventual refactor. One shared
shell is cleaner than three independent templates. If
operator wants to ship this fast, Option B is 4 lines of CSS
change.

## Testing contract

- Portal-welcome HTML output contains `background:#FFFFFF` on
  the header card.
- Header h1 color NOT `#fff` (invisible-text regression lock).
- `border-bottom:1px solid #E5E7EB` present on the header
  (matches shared shell separator).
- Welcome CTA button + body copy unchanged.

## Priority rationale

P3 — low-frequency template, visual-brand only. Operator can
schedule alongside the auto-visit parity ticket for one brand-
consistency sweep.
