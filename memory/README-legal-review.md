# Legal-review flags — English-only copy

Certain user-facing strings ship as English-only pending legal review.
The Spanish / French translations reuse the English boilerplate verbatim
so the underlying legal meaning is preserved word-for-word until
counsel signs off on locale-specific wording.

Grep `[Legal review — English-only.]` in any locale file for the current set.

## Feb-2026 · Payment Processors (Ticket · Primary/Backup failover)

Copy in question: the disclosure that switching processors may reset
stored customer payment methods (used on the Business Settings ·
Payment Processors card).

* Location:
  - `frontend/src/i18n/locales/en/common.json` → `payment_providers.description`
  - `frontend/src/i18n/locales/es/common.json` → `payment_providers.description`
  - `frontend/src/i18n/locales/fr/common.json` → `payment_providers.description`
* Status: pending locale review — es/fr carry an English suffix
  `[Legal review — English-only.]` intentionally as the marker.
* Next steps: strip the English suffix from es/fr once counsel signs off.
