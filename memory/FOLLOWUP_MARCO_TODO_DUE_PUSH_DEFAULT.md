# FOLLOWUP: marco_todo_due push default

**Status:** parked for user preference decision.

## Context
Sub-phase E added `"marco_todo_due"` to `KIND_LABELS` in `services/notifications.py`.
The push-default sets in that same file:
- `_ADMIN_PUSH_DEFAULT_ON` — kinds that flip Expo push=on for admins by default.
- `_NONADMIN_PUSH_DEFAULT_ON` — same for techs/sales.

`marco_todo_due` is currently NOT in either. Admins get in-app bell + SSE only; push
requires an explicit per-user opt-in via `/settings/notifications`.

## Decision needed
- **Option A** — keep off. Todos already fire in-app + SSE; push adds mobile noise.
- **Option B** — add to `_ADMIN_PUSH_DEFAULT_ON` so admins get pinged even when the
  app isn't open. Aligns with "reminder" intent.

## To implement if Option B chosen
Single-line change in `services/notifications.py`:
```python
_ADMIN_PUSH_DEFAULT_ON = {
    ...,
    "marco_todo_due",   # Feb-2026 · MARCO Sub-phase E follow-up
}
```
Plus a data-only migration to flip `push=True` on existing `notification_preferences`
rows for this kind (or leave existing users on their current settings and only default
new users to on — safer).
