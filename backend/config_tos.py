"""Feb-2026 · BUG E — Terms of Service gate configuration.

The active ToS version is stored as a semantic string constant in this
module (NOT in the DB, NOT in .env). Bump ``CURRENT_TOS_VERSION`` to
force every non-super_admin user to re-accept on their next request.

Historical note
---------------
This constant intentionally lives at ``backend/config_tos.py`` (not
``backend/config/tos.py``) because ``backend/config.py`` already exists
as a module in this codebase — introducing a ``config/`` package would
force a risky rewrite of ~150 files that import ``from config import``.
The naming convention follows the existing ``config_chemicals.py`` /
``config_chlorine_targets.py`` / ``config_equipment_types.py`` pattern.
"""
from __future__ import annotations

from typing import Any, Dict


# Active ToS version. Bump to force re-acceptance.
CURRENT_TOS_VERSION: str = "1.0.0"

# Effective date of the CURRENT_TOS_VERSION revision.
CURRENT_TOS_EFFECTIVE_DATE: str = "2026-02-15"

# Static markdown served by GET /api/legal/tos. Admin edits to the
# legacy /api/legal/{slug} CMS do NOT change this — the gate is the
# source of truth for what the user is agreeing to at gate time.
TOS_MARKDOWN: str = """## Pool & Landscaping of Vistancia — Terms of Service

**Version 1.0.0 · Effective 2026-02-15**

Please read these Terms of Service carefully. By clicking **"I Agree"** you acknowledge
that you have read, understood, and accepted the terms below in their entirety.

---

### 1. Service
Pool & Landscaping of Vistancia LLC ("we", "us") provides recurring pool/spa
maintenance and landscaping services under the plan you have selected in your
customer portal. Rates and cadence are defined by your active plan and may be
adjusted with written notice.

### 2. Billing
Invoices are generated in advance for service. A credit card or ACH method must
be kept on file. Past-due balances of more than 30 days will result in service
interruption. Late fees apply after 10 days.

### 3. Communication
Service reports, invoices, and account notifications are delivered via email and
your customer portal. You must keep a valid email on file to receive these.

### 4. Weather & Rescheduling
Service days may be rescheduled for weather, safety, or holidays. If service or
partial service is rendered, it will not be rescheduled.

### 5. Repairs
Repairs under $100 may be performed without prior authorization. Repairs above
$100 require your written approval via the estimate/quote flow in your portal.

### 6. Termination
Either party may terminate service at any time. Any prepaid balance will be
prorated to the last service date.

### 7. Limitation of Liability
Pool & Landscaping of Vistancia LLC is not responsible for damage caused by acts
of nature, misuse, or failure to maintain equipment between visits.

### 8. Portal Access
Your portal login provides access to invoices, service reports, and account
history. You are responsible for keeping your credentials confidential.

### 9. Updates to These Terms
We may update these Terms from time to time. Material changes will bump the
version number and require your re-acceptance on next login.

---

By clicking **"I Agree"** you acknowledge that this electronic acknowledgement
carries the same legal weight as a handwritten signature.
"""


def compute_must_accept_tos(user: Dict[str, Any]) -> bool:
    """Server-authoritative gate check.

    Super admins are ALWAYS exempt (they own the tenant + the terms —
    walling them out of their own setup would be silly). Every other
    role must have ``tos_version_accepted == CURRENT_TOS_VERSION``.
    """
    if not user:
        return False
    if user.get("role") == "super_admin":
        return False
    return user.get("tos_version_accepted") != CURRENT_TOS_VERSION
