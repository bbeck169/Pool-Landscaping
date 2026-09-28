"""HD-A · Entity registry — the single source of truth for which
collections HD-A can operate on, how their children cascade, and
which external references block a purge.

Every entity type advertised by ``/api/hard-delete/{entity_type}/*``
MUST have an ``EntitySpec`` here. Missing entries surface as HTTP
400 ``unsupported_entity_type`` in the router.

Cascade model
-------------
* ``children_specs`` — list of Cascade rules. Each rule names a
  child collection, the field in the child that points back to the
  parent (``parent_field``), and any additional match constraints
  (``extra_query``). Cascade is one direction only: parent → child.
* Photos live embedded inside ``jobs.photos[]`` and
  ``service_reports.photos[]``. HD-A treats those arrays as one
  logical entity — they cascade as part of the parent doc's
  soft-delete (no separate ``deleted_at`` per photo; the parent
  guards visibility).
* ``files`` live in their own collection (``db.files``) already
  bearing ``is_deleted``; HD-A also stamps ``deleted_at`` for
  parity.
* ``quotes`` cover BOTH estimates AND invoices, distinguished by
  ``doc_type``. Callers pass ``entity_type="quote"`` for either;
  the tombstone captures ``doc_type`` so auditors can filter.

External-reference blocking
---------------------------
Per user brief §5, children NEVER block a purge — cascade handles
them. Only *external* references block:

* Invoices carrying ``payment_intent_id`` — the Stripe charge has
  cleared to the merchant's bank; deleting the local row without a
  refund would create an unreconcilable ledger gap. The purge is
  refused with HTTP 409 ``blocked_external_reference`` and the
  referring Stripe id is included in the error body.
* Customers cascade-purging invoices are subject to the same
  Stripe check — the customer's purge blocks if ANY owned invoice
  carries a ``payment_intent_id``.
* ``communication_sends`` and ``outbound_emails`` do NOT block —
  they're logged into the tombstone's ``external_refs`` array for
  the audit trail only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class CascadeRule:
    """One parent → child cascade edge.

    Attributes:
        collection: The Mongo collection name of the child (e.g.
            ``"jobs"``).
        parent_field: The field on the child doc that references the
            parent's id (e.g. ``"customer_id"``).
        entity_type: The HD-A entity_type slug the child registers
            under. Enables recursive cascade descent — jobs cascade
            to service_reports, service_reports have their own
            children, etc.
    """
    collection: str
    parent_field: str
    entity_type: str


@dataclass(frozen=True)
class EntitySpec:
    """Metadata for one HD-A entity type."""

    entity_type: str
    collection: str
    # Which children cascade with a soft-delete + purge of this parent.
    children_specs: List[CascadeRule] = field(default_factory=list)
    # Extra query filters applied when reading the row (e.g.
    # ``doc_type`` split on the quotes collection).
    row_filter: Dict[str, Any] = field(default_factory=dict)
    # Human label surfaced in the Trash UI.
    label: str = ""


# ─── Registry ────────────────────────────────────────────────────────
# Order matters only for cascade descent (parents before children in
# the recursion) — the dict itself is order-preserving in py3.7+.

_REGISTRY: Dict[str, EntitySpec] = {
    "customer": EntitySpec(
        entity_type="customer",
        collection="customers",
        label="Customer",
        children_specs=[
            CascadeRule(collection="jobs", parent_field="customer_id",
                          entity_type="job"),
            CascadeRule(collection="quotes", parent_field="customer_id",
                          entity_type="quote"),
            CascadeRule(collection="service_reports",
                          parent_field="customer_id",
                          entity_type="service_report"),
            CascadeRule(collection="files", parent_field="customer_id",
                          entity_type="file"),
        ],
    ),
    "job": EntitySpec(
        entity_type="job",
        collection="jobs",
        label="Job",
        children_specs=[
            CascadeRule(collection="service_reports", parent_field="job_id",
                          entity_type="service_report"),
            CascadeRule(collection="files", parent_field="job_id",
                          entity_type="file"),
        ],
    ),
    "quote": EntitySpec(
        entity_type="quote",
        collection="quotes",
        label="Estimate / Invoice",
        children_specs=[
            CascadeRule(collection="files", parent_field="quote_id",
                          entity_type="file"),
        ],
    ),
    "service_report": EntitySpec(
        entity_type="service_report",
        collection="service_reports",
        label="Service Report",
        children_specs=[
            CascadeRule(collection="files",
                          parent_field="service_report_id",
                          entity_type="file"),
        ],
    ),
    "file": EntitySpec(
        entity_type="file",
        collection="files",
        label="Attachment",
        children_specs=[],
    ),
}


ELIGIBLE_COLLECTIONS: List[str] = sorted(
    {spec.collection for spec in _REGISTRY.values()}
)


def get_spec(entity_type: str) -> Optional[EntitySpec]:
    """Return the ``EntitySpec`` for ``entity_type``, or ``None``.

    Case-insensitive; leading/trailing whitespace stripped.
    """
    if not entity_type:
        return None
    return _REGISTRY.get(entity_type.strip().lower())


def all_specs() -> List[EntitySpec]:
    """Return every registered spec in insertion order."""
    return list(_REGISTRY.values())
