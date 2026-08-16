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
"""
from __future__ import annotations

# Total count of inactive-or-written-off customers (excluding soft-
# deleted). Used by the dry-run to size the import.
COUNT_QUERY = """
query CountInactive {
  customers(
    where: {
      status: { in: [INACTIVE, WRITTEN_OFF] },
      isDeleted: false
    }
    take: 1000
    skip: 0
  ) {
    id
  }
}
""".strip()

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
    address { street city state zip country }
    location { lat lng }
    status
    description
    discount
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
    dispatchNotes { id note createdAt }
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
