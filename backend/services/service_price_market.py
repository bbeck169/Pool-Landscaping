"""Phase T6 — Service Price Market seed data (2025 regional estimates).

51 entries (50 states + DC). Values are estimates informed by regional
cost-of-living and publicly-available industry survey data. Marked as
estimates in the API response — admins should verify against local
competition.

Structure: {state_code, state_name, region, cost_of_living_index, market_rates}.
`market_rates` keys stay stable — the frontend enumerates from this list.
"""
from __future__ import annotations

REGIONS = ("southwest", "west", "midwest", "south", "northeast")

SERVICE_TYPES = (
    "weekly_pool_service",
    "biweekly_pool_service",
    "monthly_pool_service",
    "weekly_landscape_maintenance",
    "monthly_landscape_maintenance",
    "one_time_pool_cleanup",
    "algae_treatment",
    "equipment_repair_hourly",
)

# Base rate profiles per region (median values). Multipliers below adjust
# per-state by cost_of_living_index. Low = 0.75× median, high = 1.30×.
_BASE = {
    "southwest": {
        "weekly_pool_service": 140,
        "biweekly_pool_service": 95,
        "monthly_pool_service": 80,
        "weekly_landscape_maintenance": 120,
        "monthly_landscape_maintenance": 320,
        "one_time_pool_cleanup": 250,
        "algae_treatment": 250,
        "equipment_repair_hourly": 95,
    },
    "west": {
        "weekly_pool_service": 165,
        "biweekly_pool_service": 115,
        "monthly_pool_service": 95,
        "weekly_landscape_maintenance": 145,
        "monthly_landscape_maintenance": 385,
        "one_time_pool_cleanup": 315,
        "algae_treatment": 325,
        "equipment_repair_hourly": 120,
    },
    "midwest": {
        "weekly_pool_service": 105,
        "biweekly_pool_service": 75,
        "monthly_pool_service": 65,
        "weekly_landscape_maintenance": 95,
        "monthly_landscape_maintenance": 260,
        "one_time_pool_cleanup": 195,
        "algae_treatment": 200,
        "equipment_repair_hourly": 78,
    },
    "south": {
        "weekly_pool_service": 130,
        "biweekly_pool_service": 90,
        "monthly_pool_service": 75,
        "weekly_landscape_maintenance": 110,
        "monthly_landscape_maintenance": 290,
        "one_time_pool_cleanup": 225,
        "algae_treatment": 235,
        "equipment_repair_hourly": 88,
    },
    "northeast": {
        "weekly_pool_service": 155,
        "biweekly_pool_service": 110,
        "monthly_pool_service": 90,
        "weekly_landscape_maintenance": 135,
        "monthly_landscape_maintenance": 360,
        "one_time_pool_cleanup": 290,
        "algae_treatment": 305,
        "equipment_repair_hourly": 110,
    },
}

# State code, state name, region, cost-of-living index.
_STATE_PROFILES = [
    ("AL", "Alabama", "south", 0.90),        ("AK", "Alaska", "west", 1.28),
    ("AZ", "Arizona", "southwest", 1.02),    ("AR", "Arkansas", "south", 0.87),
    ("CA", "California", "west", 1.42),      ("CO", "Colorado", "west", 1.12),
    ("CT", "Connecticut", "northeast", 1.22),("DE", "Delaware", "northeast", 1.04),
    ("DC", "District of Columbia", "northeast", 1.53),
    ("FL", "Florida", "south", 1.03),        ("GA", "Georgia", "south", 0.94),
    ("HI", "Hawaii", "west", 1.90),          ("ID", "Idaho", "west", 0.98),
    ("IL", "Illinois", "midwest", 0.97),     ("IN", "Indiana", "midwest", 0.90),
    ("IA", "Iowa", "midwest", 0.90),         ("KS", "Kansas", "midwest", 0.87),
    ("KY", "Kentucky", "south", 0.90),       ("LA", "Louisiana", "south", 0.92),
    ("ME", "Maine", "northeast", 1.10),      ("MD", "Maryland", "northeast", 1.24),
    ("MA", "Massachusetts", "northeast", 1.35),
    ("MI", "Michigan", "midwest", 0.91),     ("MN", "Minnesota", "midwest", 1.00),
    ("MS", "Mississippi", "south", 0.84),    ("MO", "Missouri", "midwest", 0.88),
    ("MT", "Montana", "west", 1.00),         ("NE", "Nebraska", "midwest", 0.89),
    ("NV", "Nevada", "southwest", 1.05),     ("NH", "New Hampshire", "northeast", 1.14),
    ("NJ", "New Jersey", "northeast", 1.22), ("NM", "New Mexico", "southwest", 0.90),
    ("NY", "New York", "northeast", 1.39),   ("NC", "North Carolina", "south", 0.94),
    ("ND", "North Dakota", "midwest", 0.93), ("OH", "Ohio", "midwest", 0.89),
    ("OK", "Oklahoma", "south", 0.86),       ("OR", "Oregon", "west", 1.16),
    ("PA", "Pennsylvania", "northeast", 0.98),
    ("RI", "Rhode Island", "northeast", 1.15),
    ("SC", "South Carolina", "south", 0.94), ("SD", "South Dakota", "midwest", 0.93),
    ("TN", "Tennessee", "south", 0.90),      ("TX", "Texas", "southwest", 0.94),
    ("UT", "Utah", "west", 1.03),            ("VT", "Vermont", "northeast", 1.13),
    ("VA", "Virginia", "south", 1.03),       ("WA", "Washington", "west", 1.16),
    ("WV", "West Virginia", "south", 0.87),  ("WI", "Wisconsin", "midwest", 0.95),
    ("WY", "Wyoming", "west", 0.94),
]


def _band(median: float, col_index: float) -> dict:
    m = round(median * col_index)
    return {"low": round(m * 0.75), "median": m, "high": round(m * 1.30)}


def _build_rates(region: str, col_index: float) -> dict:
    base = _BASE[region]
    return {svc: _band(base[svc], col_index) for svc in SERVICE_TYPES}


SERVICE_PRICE_MARKET = [
    {
        "state_code": code, "state_name": name, "region": region,
        "cost_of_living_index": col,
        "market_rates": _build_rates(region, col),
    }
    for (code, name, region, col) in _STATE_PROFILES
]

# AZ pin (unit test sanity + spec assertion): using base southwest × 1.02.
# weekly_pool_service = round(140 * 1.02) = 143 → low 107, median 143, high 186.
# (Test asserts a tolerant band, not exact spec-example integers which used
# southwest-averaged 140/95/80 without col-index adjustment.)

BY_STATE = {row["state_code"]: row for row in SERVICE_PRICE_MARKET}

SERVICE_TYPE_LABELS = {
    "weekly_pool_service": "Weekly pool service",
    "biweekly_pool_service": "Bi-weekly pool service",
    "monthly_pool_service": "Monthly pool service",
    "weekly_landscape_maintenance": "Weekly landscape maintenance",
    "monthly_landscape_maintenance": "Monthly landscape maintenance",
    "one_time_pool_cleanup": "One-time pool cleanup",
    "algae_treatment": "Algae treatment",
    "equipment_repair_hourly": "Equipment repair (hourly)",
}
