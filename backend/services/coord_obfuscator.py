"""Feb-2026 · Coord Obfuscator — deterministic ±0.001° jitter.

Rationale: the widget-embed check-ins map surfaces every approved
job as a pin on a public map. Rendering exact customer-address
coords is a PII leak (someone could reverse-map the pin to a
specific address). Rendering everyone at the CITY centroid loses
the "we service YOUR neighbourhood" signal that makes the widget
valuable.

Solution: apply a small deterministic offset (±0.001° ≈ ±111 m at
the equator, ~90 m at 34°N) to each pin, seeded on the source
job_id. Same job_id always renders at the same obfuscated coords,
so:

* Re-renders of the same feed are stable (no jitter-per-refresh).
* An attacker who scrapes the endpoint twice sees the same
  numbers — no ability to average out the jitter to recover the
  real address.

Contract:

    obfuscate_coords(lat, lng, seed="<job_id>")  →  (lat', lng')

    * Same ``(lat, lng, seed)`` triple → same ``(lat', lng')`` pair.
    * ``|lat' − lat| ≤ 0.001`` and ``|lng' − lng| ≤ 0.001``.
    * Different seeds shift the pin in a different direction.
    * ``None`` inputs pass through as ``None`` — callers decide
      whether to persist that (typically: skip the pin).
"""
from __future__ import annotations

import hashlib
import struct
from typing import Optional, Tuple


# Half-window magnitude for the jitter. 0.001° ≈ ~111 m at the
# equator, ~90 m at 34° N (the Phoenix/Peoria service area). Small
# enough to keep the pin in the same neighbourhood, large enough
# that reverse-mapping to a specific address is defeated.
_JITTER_DEG = 0.001


def _deterministic_unit(seed: str) -> Tuple[float, float]:
    """Return two floats in ``[-1, +1]`` derived from ``seed``.

    Uses SHA-256 so a small seed change (e.g., one character)
    produces uncorrelated outputs — an attacker who guesses one
    job_id can't infer the offset of a neighbouring row.
    """
    digest = hashlib.sha256(str(seed).encode("utf-8")).digest()
    # Two independent 32-bit unsigned ints out of the digest → map
    # onto [-1, +1). ``struct.unpack`` is 5x faster than int(hex).
    a, b = struct.unpack("!II", digest[:8])
    max_u32 = 0xFFFFFFFF
    return (
        (a / max_u32) * 2.0 - 1.0,
        (b / max_u32) * 2.0 - 1.0,
    )


def obfuscate_coords(
    lat: Optional[float],
    lng: Optional[float],
    *,
    seed: str,
) -> Tuple[Optional[float], Optional[float]]:
    """Return ``(lat', lng')`` with a ±0.001° jitter seeded on
    ``seed``. Preserves ``None`` inputs untouched — callers that
    ingest a customer with no geocode should skip the pin, not
    ship a fake one.

    Args:
        lat:  Raw latitude in decimal degrees, or ``None``.
        lng:  Raw longitude in decimal degrees, or ``None``.
        seed: Deterministic key (usually the source job_id).

    Returns:
        ``(lat', lng')`` — same shape as input. Values rounded to
        6 decimal places (~10cm precision) so the JSON payload
        stays compact.
    """
    if lat is None or lng is None:
        return (lat, lng)
    if not isinstance(seed, str) or not seed:
        # No deterministic seed → fall back to seed=str(lat, lng).
        # This is a soft-fail: still deterministic per point, just
        # not per job.
        seed = f"{lat:.6f},{lng:.6f}"
    u_lat, u_lng = _deterministic_unit(seed)
    return (
        round(float(lat) + u_lat * _JITTER_DEG, 6),
        round(float(lng) + u_lng * _JITTER_DEG, 6),
    )
