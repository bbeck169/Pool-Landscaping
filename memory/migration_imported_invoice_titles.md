# TD-72 · migrate_imported_invoice_titles · run history

Companion to TD-71 (display-time resolver). This file
accumulates one entry per invocation of
`scripts/migrate_imported_invoice_titles.py` on either
preview or (operator-driven) prod.

### TD-72 · migrate_imported_invoice_titles · 2026-10-18T09:11:36.454943+00:00

- mode: `dry-run`
- tenant scope: `all`
- scanned: **0**
- matched (title regex + imported flag): **0**
- updated: **0**
- skipped (already fine): **0**
- failed: **0**
- non-imported invoice count (regression lock): **1068**
- updated-by-branch:
  * `line_item`: **0**
  * `notes`: **0**
  * `fallback`: **0**
### TD-72 · migrate_imported_invoice_titles · 2026-10-18T09:11:43.638893+00:00

- mode: `apply`
- tenant scope: `all`
- scanned: **0**
- matched (title regex + imported flag): **0**
- updated: **0**
- skipped (already fine): **0**
- failed: **0**
- non-imported invoice count (regression lock): **1068**
- updated-by-branch:
  * `line_item`: **0**
  * `notes`: **0**
  * `fallback`: **0**
