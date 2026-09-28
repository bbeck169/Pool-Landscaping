"""FLEET-A · Feb-2026 — Fleet backend package.

Ships:
    * ``eta`` — pluggable ETA computer (Google → OSRM → crow-flies).
    * ``notifications`` — SYSTEM-context customer "on the way"
      pipeline (dedup + SAFE-SEND adapters).
    * ``rate_limit`` — in-memory per-tech ping rate-limit (1 per 5s).
    * ``indexes`` — TTL + query indexes for the FLEET-A collections.

FLEET-A is intentionally namespace-isolated from the pre-existing
``gps_*`` telematics stack. Both fleet-management stacks coexist:
telematics_geotab_poller feeds ``db.gps_pings`` from vendor APIs;
FLEET-A's ``db.tech_locations`` captures direct-from-app tech
breadcrumbs + manual check-ins.  Different sources, different
consumption surfaces, both are legitimate.
"""
