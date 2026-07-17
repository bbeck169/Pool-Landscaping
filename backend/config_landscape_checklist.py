"""Phase 56.16 — Landscape Checklist template (default).

The canonical 10-item ordered checklist that ships with every fresh
landscape service report. Order matters: field techs prefer the same
sequence every visit for muscle-memory speed. Tenant-custom checklists
in `db.service_report_templates` override this default and are NOT
touched by shipping a new default (see `_get_template` in
`routers/service_reports.py`).
"""
from typing import List

LANDSCAPE_CHECKLIST_TEMPLATE_DEFAULT: List[str] = [
    "Sprayed or Pulled Weeds",
    "Checked Irrigation",
    "Trimmed Bushes",
    "Mowed Grass",
    "Edged Grass",
    "Blow Property",
    "Raked Rocks",
    "Locked Gate",
    "Trimmed Trees",
    "Irrigation Repair",
]
