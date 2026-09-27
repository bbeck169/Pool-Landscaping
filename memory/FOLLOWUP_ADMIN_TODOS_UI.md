# FOLLOWUP: Admin Todos UI

**Status:** parked. Not a queued sub-phase yet.

## Context
MARCO Sub-phase E landed with notifications carrying `href="/admin/todos/{id}"`.
Frontend grep at commit `7b99d45ca` confirmed no matching admin UI exists — the bell
click will no-op until this UI ships.

## Suggested next-time-around scope
- List view: `GET /api/admin/todos` (already implemented in Sub-phase D).
- Detail view: `GET /api/admin/todos/{id}` + `PATCH` + `DELETE` (all implemented).
- Route: `/admin/todos` and `/admin/todos/:id`.
- Filters: status (open/done/snoozed/deleted), priority (low/med/high/urgent),
  due_before, due_after — all supported by the existing list endpoint.
- Row actions: mark done, snooze, delete (all supported via PATCH/DELETE).
- Design: match the notifications-page look; navy `#1B1F5C` + blue `#3B82F6` accents;
  urgent priority badge red, high orange, med gray, low subdued.
- Data-testids: `admin-todos-list`, `admin-todo-row-{id}`, `admin-todo-status-toggle-{id}`,
  `admin-todo-detail`, `admin-todo-delete-btn`, `admin-todo-priority-badge-{id}`.

## Dependencies before dispatch
None hard — this is purely a UI over an already-shipped backend. Can slot anywhere.
