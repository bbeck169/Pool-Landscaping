"""Phase 17 · Feb-2026 — QuickBooks Online (QBO) inbound read-sync package.

Zero write-back to Intuit. Every module here reads from QBO and mirrors
data into ``db.qbo_*`` collections owned by the CRM. Match links between
CRM records and QBO records are optional and admin-created — never auto.
"""
