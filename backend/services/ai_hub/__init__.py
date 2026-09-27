"""AI Hub · Feb-2026 — 18-employee workforce package.

Ships (a) an immutable registry of the 18 spec personas
(``employee_registry.EMPLOYEES``) and (b) the SAFE-SEND-A
integration hook (``context_stamping.stamp_agent_context``)
used by every AI-comms callsite to gate real customer sends
behind the ``authorized_for_public_use`` flag.

See ``/app/memory/SPEC_AI_HUB_18_EMPLOYEE_WORKFORCE.md`` for
the source-of-truth roster + AI-Hub / SAFE-SEND contract.
"""
