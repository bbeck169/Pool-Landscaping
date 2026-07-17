"""Phase 56.5 — Chlorine target + tab-preference constants.

Isolated from `pool_dosing.py` so future ops tweaks are a one-line
change without touching the dosing math. All values are US customary.
"""
# High-swim season (Mar 1 – Sep 30 inclusive). Tenant timezone drives the
# month lookup — Arizona-based seeds default to `America/Phoenix`.
CHLORINE_HIGH_SEASON_MONTHS = {3, 4, 5, 6, 7, 8, 9}

# Free chlorine ppm targets by season.
CHLORINE_HIGH_SEASON_TARGET_PPM = 5.0
CHLORINE_LOW_SEASON_TARGET_MIN_PPM = 1.0
CHLORINE_LOW_SEASON_TARGET_MAX_PPM = 3.0

# Manufacturer typical: 1 tab (3" 8oz trichlor) treats ~10,000 gallons per week.
CHLORINE_TAB_GALLONS_PER_TAB_PER_WEEK = 10_000

# Rapid-boost threshold — when free chlorine is this many ppm BELOW the
# seasonal target in high season, prefer liquid over tabs (tabs dissolve
# too slowly for a sanitation emergency).
CHLORINE_RAPID_BOOST_GAP_PPM = 2.0

# How many recent visits to look back on for tab rotation ("don't stack
# tabs indefinitely"). If tabs were used in any of the last N reports,
# we rotate to liquid on the next recommendation.
CHLORINE_TAB_ROTATION_LOOKBACK_VISITS = 3
