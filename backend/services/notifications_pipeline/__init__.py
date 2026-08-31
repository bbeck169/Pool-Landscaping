"""Feb-2026 · Service Notifications Pipeline.

Home for **customer-facing service lifecycle notifications** that
aren't marketing (which lives under ``services/marketing``) and
aren't dispatch-side (``services/notifications.py`` is the bell/
staff alerting hub).

Currently ships:

* ``service_notifications.py`` — 24-hr service reminder cron +
  reschedule notification event helper. Both share the identity
  guard, opt-out enforcement, template renderers, and
  ``notifications_sent_log`` audit trail.

Design principles inherited from the F1/F2/F3 arc:

* **Identity guard.** Every send path re-verifies
  ``job.customer_id == cust.id`` before rendering the template.
  A mismatch is a P0 invariant (see ``routers/customer_portal.py``)
  and MUST NOT ship SMS to the wrong recipient.
* **Adapter reuse.** SMS via ``services.comms_sms_adapter.send_sms``
  and email via ``services.comms_email_adapter.send_email``. Never
  re-implement opt-out or quiet-hours logic — the adapters
  already handle it.
* **Idempotency.** Cron stamps ``service_reminder_sent_at`` on the
  job row; a second cron tick finds the stamp and skips.
  Reschedule event stamps ``reschedule_notification_sent_at``
  keyed on the ``old→new`` pair so a second PATCH with the same
  transition is a no-op.
"""
