"""Phase 56.11 — Customer Equipment Photo Library.

Fixed, ordered enum of equipment types the field-service techs will
photograph at each customer site. Exposed via the API so web + mobile
stay in sync without duplicating the list.

Extending this list is a code change (not a runtime config) so the
enum can be referenced everywhere in the codebase without validating
each entry against the DB.
"""
from typing import List

EQUIPMENT_TYPES: List[str] = [
    "Filter Pump",
    "Cleaning Pump",
    "Waterfall Pump",
    "Filter",
    "Heater",
    "Salt Cell",
    "Cleaning System",
    "Automation",
    "Heater Plumbing",
    "Check Valves",
    "Jandy Valves",
]

# Max photos allowed per (customer, equipment_type). Bumping this is a
# UX + storage decision — the router enforces the cap at write time.
EQUIPMENT_PHOTO_CAP = 4

# Allowed tag values on a photo. `general` is the implicit default.
# `algae_before` / `algae_after` are the Phase 56.10 hook tags surfaced
# by the wizard step-4 photo prompt when visible_algae is set.
EQUIPMENT_PHOTO_TAGS = {"general", "algae_before", "algae_after"}
