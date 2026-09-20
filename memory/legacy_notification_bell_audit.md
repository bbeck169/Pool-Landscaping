# Legacy NotificationBell Audit — Feb 2026 · Phase A1.5

## TL;DR
**Recommendation: Strategy A (no code change).** The legacy
`<NotificationBell />` correctly renders per-user notifications
for every role, including technicians. The 63-unread count the
tester saw for `mike@aquaterra.com` is **entirely direct-to-user
targeting** — zero broadcast, zero admin-only content leaks.
Hiding the bell for technicians would suppress notifications
they legitimately need (approval-flow feedback, personal access
changes, team-chat mentions).

## Endpoint contract (unchanged, verified correct)
`GET /api/notifications/unread-count` runs through
`_mine_filter(user, tenant_id)` in `backend/routers/notifications.py:39`:

```python
if user.role == "customer":
    q["user_id"]  = user["id"]           # portal-only
    q["audience"] = "portal"
else:
    q["$or"]      = [{"user_id": user.id}, {"user_id": "*"}]
    q["audience"] = {"$in": ["internal", None]}
```

Result: technicians see rows with **their own `user_id`** or
broadcast (`"*"`) rows tagged `internal` audience. Admin-only
producers using `enqueue_for_tenant_admins` target explicit
admin/super_admin user IDs, so techs never receive them.

## Live evidence — `mike@aquaterra.com` (technician)
```
Notifications targeting mike:  total=63  unread=63
Split · direct-to-mike unread=63   broadcast unread=0

Unread kinds for mike (top):
  route_optimization_request        × 42   ← flow feedback (approved / rejected)
  system_alert                      × 11   ← "Your access was updated"
  chat_message_in_channel           × 10   ← channel messages he's a member of
```

Sample rows (all `user_id = mike.id`, `audience = internal`):
- `"Route optimization approved"` / `"Route optimization rejected"`
- `"Your access was updated"`
- `"TEST-CHAN-*"` chat mentions

Every row is direct-to-mike targeting. There are no cross-role
leaks.

## Producer inventory (roles → who should see each)

| Producer helper | Producer sites | Who is currently targeted | Who SHOULD see it | Assessment |
|---|---|---|---|---|
| `emit(user_ids=[…])` | `routers/jobs.py`, `routers/chat.py`, `routers/route_optimization_approval.py::_notify_tech_of_resolution`, `routers/team.py`, `routers/job_requests.py`, `routers/notifications.py::test-push`, `routers/ai_ops.py` | Explicit user_id set (usually the recipient) | Same | **Correct.** |
| `enqueue_for_tenant_admins()` | `routers/route_optimization_approval.py::_fanout_admin_notification`, `routers/customers.py`, `routers/sequences.py`, `routers/checks.py`, `routers/training_nudge.py` | `role IN {admin, super_admin}` in tenant | admin + super_admin | **Correct — techs never receive.** |
| `enqueue_for_record_owner()` | Sales/deal ownership sites | Deal owner (`assigned_admin_user_id`) or falls back to `enqueue_for_tenant_admins` | Owner (any role) | **Correct.** |
| `services/notifications.emit` (job_assigned / job_unassigned) | `routers/jobs.py:2983, 3000` | Explicit tech `user_id` | Tech | **Correct — this is the primary legitimate tech notification.** |
| Muted-digest builder (`build_muted_digest`) | `routers/notifications.py::/digest/run` (admin trigger) | Per user, opt-in email digest — no bell fan-out | N/A | **Not bell-related.** |

## Per-kind role usefulness
- **`job_assigned` / `job_unassigned`** — techs are the recipient. Load-bearing. Must keep.
- **`route_optimization_request`** — the ADMIN-side row (fan-out via `enqueue_for_tenant_admins`) is admin-only. The TECH-side row (`_notify_tech_of_resolution`) sends "your request was approved/rejected" back to the requesting tech. Both are correctly targeted.
- **`system_alert`** — 11 targeted rows for mike are all "Your access was updated" — direct account-change feedback. Correct.
- **`chat_dm` / `chat_mention_in_channel` / `chat_message_in_channel`** — team messaging. Techs are first-class chat participants. Load-bearing.
- **`tech_note` / `tech_message`** — designed for tech-visibility.
- **`invoice_paid` / `payment_received` / `invoice_overdue`** — fanned out via `enqueue_for_tenant_admins`, so admin-only by construction. Techs never receive these.
- **RingCentral (`rc_sms_inbound`, `rc_call_inbound`, `rc_voicemail`, `rc_fax`, `_unmatched` variants)** — routed to record owners via `enqueue_for_record_owner`. Techs only see if they're the deal owner.
- **`autosave_conflict`** — targeted to the specific user who hit the conflict (any role).

## Strategy verdict
**A. Keep `<NotificationBell />` visible for every role.**

Reasoning:
1. The `unread-count` filter is already per-user and correctly excludes admin-only broadcasts from techs.
2. Every "leak" the tester was worried about is actually a legitimate per-user notification.
3. Techs' 63-unread count is dominated by `route_optimization_request` and `chat_message_in_channel` — both of which the tech authored or is a channel member of, respectively.
4. Hiding the bell for techs would blind them to approval-flow outcomes, chat mentions, and personal account changes.
5. Strategy B was the fallback for a case where "techs have no legitimate notifications" — data disproves that premise for `mike@aquaterra.com`.

## What this means for the A1 hotfix Round 2 report
The Round 2 forensics already established that the "63 badge" is
`<NotificationBell />` (`data-testid="notification-bell-badge"`),
not the A1 `<AlertBell />`. This audit confirms the 63 is
**correct product behavior**, not a bug:

- The A1 bell is admin/super_admin only (as designed).
- The legacy bell is per-user (as designed and required for job / chat / approval workflows).

No frontend or backend code change is required.

## Optional cleanups (out of scope, backlog only)
- **Test channel spam**: 10 unread `chat_message_in_channel` rows targeting `TEST-CHAN-*` are seed-fixture noise. A cleanup migration could delete them without impacting real chat data. **P2.**
- **Notification digest opt-in surface**: the muted-digest feature is admin-triggered only; a per-user "digest instead of live bell" opt-in on the preferences page could be exposed for techs who find the volume noisy. **P2.**
- **Retention policy**: stale unread rows older than N months could auto-archive to a cold collection. No such policy exists today. **P2.**

## Test coverage
- Existing suite `backend/tests/test_notifications_endpoint.py` (Phase 55) already covers the per-role scoping. No new tests required.
- No frontend mount-site test is added because the mount site is unchanged.
