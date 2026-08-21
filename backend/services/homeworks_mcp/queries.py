"""Feb-2026 · Phase 1b — GraphQL queries for the inactive-customers
importer.

Kept as Python string constants (not ``.graphql`` files) so the module
loader picks them up without extra tooling and so the test suite can
introspect the exact string sent to Homeworks.

Schema decisions (all verified against ``schema.graphql`` at pull
time, Feb-2026):

* Customer query root: ``customers(where, skip, take, orderBy)`` — offset
  pagination, max 1000 per page.
* "Inactive" = ``CustomerStatus IN (INACTIVE, WRITTEN_OFF)`` AND
  ``isDeleted: false``. Homeworks has no ``ARCHIVED`` / ``CHURNED`` — the
  user's original assumption was based on other CRMs. See report.
* Related entities all filter by ``customerId`` — one query per entity
  per customer. No nested selection because the schema doesn't expose
  ``Customer.events`` / ``Customer.invoices``.
* Photos: NO galleries in the schema. Only ``Customer.pic`` (avatar
  URL). Everything else in the "photos" bucket is a Homeworks-UI-only
  concept.
* Notes: NO notes collection. Only ``Customer.description`` and
  ``Event.dispatchNotes``.

Feb-2026 · schema drift — Homeworks removed the scalar ``discount``
field from the ``Customer`` type at some point after our
``schema.graphql`` snapshot. The old selection surfaced as::

    GraphQL request failed with status 400:
      Cannot query field "discount" on type "Customer".

Both the inactive-cohort and active-cohort page queries dropped the
``discount`` selection; no downstream consumer read the value (grep
``discount`` on services/homeworks_mcp/, services/homeworks/, and
routers/integrations_homeworks*.py returns only the query-string
references). No mapping surface change required. If Homeworks
reintroduces discount under a different name (``discountPercent``,
``pricing.discount``, etc.), reinstate the selection here — the
mapper doesn't need to change.
"""
from __future__ import annotations

# Total count of inactive-or-written-off customers (excluding soft-
# deleted). Homeworks does NOT expose a scalar ``customerCount`` on
# their public schema, so we paginate id-only pages of 1000 and count.
# One page (~1000 rows) is cheap; even 10 pages is <10 s.
COUNT_PAGE_QUERY = """
query CountInactivePage($skip: SafeInt!, $take: SafeInt!) {
  customers(
    where: {
      status: { in: [INACTIVE, WRITTEN_OFF] },
      isDeleted: false
    }
    orderBy: [{ id: asc }]
    skip: $skip
    take: $take
  ) {
    id
  }
}
""".strip()

# Backwards-compatible alias — tests / callers can keep referring to
# ``COUNT_QUERY`` while getting the paginated shape.
COUNT_QUERY = COUNT_PAGE_QUERY

# Customer core query — full profile block. `pic` is a URL string; we
# fetch the bytes in a separate HTTP call (see importer).
CUSTOMER_PAGE_QUERY = """
query InactiveCustomerPage($skip: SafeInt!, $take: SafeInt!) {
  customers(
    where: {
      status: { in: [INACTIVE, WRITTEN_OFF] },
      isDeleted: false
    }
    orderBy: [{ id: asc }]
    skip: $skip
    take: $take
  ) {
    id
    email
    ccEmail
    fullName
    firstName
    lastName
    dateRegistered
    phone
    cell
    fax
    address { street1 street2 city state zip country }
    location { latitude longitude }
    status
    description
    credit
    outstanding
    lifetimePaid
    pastDue
    pic
    createdAt
    updatedAt
    lastUpdated
    www
    title
    invoiceTerms
    number
    tags
    customerType { id name }
    isReceivePhone
    isReceiveEmail
    isReceiveText
  }
}
""".strip()

CUSTOMER_EVENTS_QUERY = """
query CustomerEvents($customerId: SafeInt!) {
  events(
    where: {
      customerId: { equals: $customerId }
      isDeleted: false
    }
    take: 1000
    orderBy: [{ startDate: desc }]
  ) {
    id
    type
    title
    status
    startDate
    startDateTime
    endDate
    endDateTime
    description
    dispatchNotes { message author date }
    budgetedHours
    lineItems { id description quantity price total }
  }
}
""".strip()

CUSTOMER_INVOICES_QUERY = """
query CustomerInvoices($customerId: SafeInt!) {
  invoices(
    where: {
      customerId: { equals: $customerId }
    }
    take: 1000
    orderBy: [{ date: desc }]
  ) {
    id
    number
    date
    status
    title
    purchaseOrder
    isArchived
    updatedAt
    createdAt
  }
}
""".strip()

CUSTOMER_PAYMENTS_QUERY = """
query CustomerPayments($customerId: SafeInt!) {
  payments(
    where: {
      customerId: { equals: $customerId }
      isDeleted: false
    }
    take: 1000
    orderBy: [{ date: desc }]
  ) {
    id
    method
    date
    totalAmount
    invoiceAmount
    creditAmount
    notes
    isRefund
    tipAmount
    invoiceId
    createdAt
    updatedAt
  }
}
""".strip()

CUSTOMER_ESTIMATES_QUERY = """
query CustomerEstimates($customerId: SafeInt!) {
  estimates(
    where: {
      customerId: { equals: $customerId }
      isDeleted: false
      isArchived: false
    }
    take: 1000
    orderBy: [{ date: desc }]
  ) {
    id
    number
    date
    status
    title
    notes
    terms
    subtotal
    discountPercent
    discountAmount
    tax
    total
    hasBeenViewed
    requestedChanges
  }
}
""".strip()

# Status enum values that constitute "not active" per Homeworks'
# ``CustomerStatus`` enum. Exported so tests can lock the mapping.
INACTIVE_STATUS_VALUES: tuple = ("INACTIVE", "WRITTEN_OFF")

# ── Phase 1b-B (Feb 2026): Active-customers filter ──────────────────
# CustomerStatus enum only exposes 4 values: INACTIVE, ACTIVE,
# WRITTEN_OFF, PENDING_APPROVAL. The user's "ACTIVE + LEAD + PROSPECT"
# request maps best to ACTIVE + PENDING_APPROVAL — "lead" / "prospect"
# do not exist as enum values (they live in `CustomerSource` /
# `CustomerType` tables). See dispatch report for rationale.
ACTIVE_STATUS_VALUES: tuple = ("ACTIVE", "PENDING_APPROVAL")

ACTIVE_COUNT_PAGE_QUERY = """
query CountActivePage($skip: SafeInt!, $take: SafeInt!) {
  customers(
    where: {
      status: { in: [ACTIVE, PENDING_APPROVAL] },
      isDeleted: false
    }
    orderBy: [{ id: asc }]
    skip: $skip
    take: $take
  ) {
    id
  }
}
""".strip()

ACTIVE_CUSTOMER_PAGE_QUERY = """
query ActiveCustomerPage($skip: SafeInt!, $take: SafeInt!) {
  customers(
    where: {
      status: { in: [ACTIVE, PENDING_APPROVAL] },
      isDeleted: false
    }
    orderBy: [{ id: asc }]
    skip: $skip
    take: $take
  ) {
    id
    email
    ccEmail
    fullName
    firstName
    lastName
    dateRegistered
    phone
    cell
    fax
    address { street1 street2 city state zip country }
    location { latitude longitude }
    status
    description
    credit
    outstanding
    lifetimePaid
    pastDue
    createdAt
    updatedAt
    lastUpdated
    www
    title
    invoiceTerms
    number
    customerType { id name }
    isReceivePhone
    isReceiveEmail
    isReceiveText
  }
}
""".strip()


# ── Feb-2026 · Queue Item 5b (pricebook / income items) ──────────────
# Homeworks exposes income items through the top-level ``items``
# query. The ``ItemFilter`` type defaults ``isDeleted`` to ``false``
# server-side (see schema.graphql `type Query { items(where: ItemFilter
# = {isDeleted: false}, …) }`), so passing an explicit filter is
# defensive-not-required; we send it anyway so the query is
# self-describing and immune to any future default change.
#
# ItemType enum values (locked to the schema): SERVICE, ITEM, LABOR,
# OTHER.
ITEM_TYPE_VALUES: tuple = ("SERVICE", "ITEM", "LABOR", "OTHER")

ITEM_COUNT_PAGE_QUERY = """
query CountItemsPage($skip: SafeInt!, $take: SafeInt!) {
  items(
    where: { isDeleted: false }
    orderBy: [{ id: asc }]
    skip: $skip
    take: $take
  ) {
    id
  }
}
""".strip()

ITEM_PAGE_QUERY = """
query ItemPage($skip: SafeInt!, $take: SafeInt!) {
  items(
    where: { isDeleted: false }
    orderBy: [{ id: asc }]
    skip: $skip
    take: $take
  ) {
    id
    name
    description
    type
    price
    unit
    tax1
    tax2
    isTaxable
    materialCost
    equipmentCost
    subcontractCost
    wholesaleCost
    markup
    markupType
    category { id name }
  }
}
""".strip()

