"""Feb-2026 · P16B — shared cross-router helpers.

Small utilities that aren't tied to any single domain (auth,
customers, service reports, etc.).  Extraction is triggered by the
"rule of three": once three routers need the same helper, we lift
it here rather than copy-paste for the third time.

Contents:
  * ``http.client_ip(request, default=…)`` — reverse-proxy-aware
    client-IP resolver shared by every audit-trail write path.
"""
