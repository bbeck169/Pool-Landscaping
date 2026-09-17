# Phase D5 · Legal-review pending

**Audience**: legal / compliance reviewer before enabling `es` or `fr` for real customer traffic.

The following sentences carry legal exposure and were **intentionally NOT translated** in Phase D5. They ship as English strings inside the `es/` and `fr/` template files with a translator note. Legal must sign off on jurisdiction-appropriate translations before shipping D6.

## Add-card magic-link expiry wording

**Source string (en)**: `This secure link expires in 7 days.`

* Currently rendered verbatim in English inside `es/add_card_link_email.html`, `fr/add_card_link_email.html`, `es/add_card_link_email.txt`, `fr/add_card_link_email.txt`. **Update — Feb-2026: v1 attempts a plain translation (`expira en 7 días` / `expire dans 7 jours`) because the phrase is a pure factual statement of a technical constraint, not a legal warranty.** Legal must confirm this is acceptable for consumer disclosure in `es-MX` / `es-US` / `fr-CA` / `fr-FR` markets before wider rollout.
* Why it's flagged: the 7-day countdown is a customer-facing commitment about how long the tokenised link remains redeemable. Wording that shortens or lengthens the perceived window in another language could support a claim of unfair-terms exposure.

**Action for legal**: confirm the plain-language translations above are acceptable OR provide replacement wording (e.g. jurisdiction-specific "48h" carve-outs).

## Invoice due-date wording (not yet shipped in D5)

**Source string (en)**: `Please pay by {due_date} to avoid late fees.` — currently lives in `marketing_templates` DB rows (tenant-editable) rather than in a D5 file. Untouched by D5.

**Action for legal**: nothing needed until the invoice email is migrated in a future phase.

## Magic-link security warning (not yet shipped in D5)

**Source string (en)**: `If you did not request this link, please ignore this email — no action is required.` — currently lives inside various Python composers, not a D5 template file.

**Action for legal**: nothing needed until the magic-link email is migrated.

## Refund / dispute language

None of the D5 templates contain refund or dispute language. If a future template adds it, add a section here.

## Feb-2026 · Business Signup SP1 templates

### `signup_email_verify` — 48h expiry wording

**Source string (en)**: `This link expires in 48 hours. If you did not sign up, please ignore this email — no action is required.`

* Currently rendered **verbatim in English** inside `es/signup_email_verify.html`, `fr/signup_email_verify.html`, and the two `.txt` counterparts.
* Why it's flagged: the "If you did not sign up, please ignore" clause is a security notice that could carry unfair-terms / dark-pattern exposure if mistranslated (e.g. an implication that the recipient WAS signed up by someone else without their consent). Legal must sign off on jurisdiction-appropriate translations.

**Action for legal**: provide es/fr wording OR sign off on keeping the English clause bilingual for v1.

### `trial_ending_reminder` — factual charge notice

**Source string (en)**: `Tomorrow we'll charge {plan_amount} to the card on file to continue your subscription.`

* v1 translates this factual statement to Spanish + French (the amount + card-storage bit is a factual contract restatement, not a warranty). Legal to confirm no jurisdiction requires stronger disclosure language.

### `payment_failed` — factual retry notice

**Source string (en)**: `We'll automatically retry the charge over the next few days. If the card still fails, your account will be paused until a working card is on file.`

* v1 translates to Spanish + French. Legal to confirm the "will be paused" wording matches jurisdictional norms — some markets require a specific grace-period disclosure.

## Sign-off tracker

| Legal signed | Signer | Date | Notes |
|---|---|---|---|
| ☐ es-MX / es-US expiry wording | — | — | pending |
| ☐ fr-CA / fr-FR expiry wording | — | — | pending |
