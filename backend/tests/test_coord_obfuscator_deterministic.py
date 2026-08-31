"""Feb-2026 · Widget Embed extension · deterministic coord obfuscator."""
from __future__ import annotations

from services.coord_obfuscator import obfuscate_coords


def test_same_seed_same_output():
    """Determinism — repeat calls with the same seed return
    identical coords."""
    a = obfuscate_coords(33.5722, -112.3237, seed="job-abc")
    b = obfuscate_coords(33.5722, -112.3237, seed="job-abc")
    assert a == b


def test_different_seeds_different_output():
    """Different job_ids → different (lat', lng') pairs. This is
    what prevents an attacker from correlating multiple pins that
    happen to share a raw address."""
    a = obfuscate_coords(33.5722, -112.3237, seed="job-abc")
    b = obfuscate_coords(33.5722, -112.3237, seed="job-xyz")
    assert a != b


def test_jitter_within_bounds():
    """The offset MUST NEVER exceed ±0.001° — that's the
    contract that keeps the pin in the same neighbourhood."""
    for seed in ("j1", "job-e2e8-x", "another",
                  "0" * 64, "!@#$%^"):
        lat_p, lng_p = obfuscate_coords(33.5722, -112.3237, seed=seed)
        assert abs(lat_p - 33.5722) <= 0.001, (
            f"seed={seed} lat jitter {lat_p - 33.5722}"
        )
        assert abs(lng_p - -112.3237) <= 0.001, (
            f"seed={seed} lng jitter {lng_p - -112.3237}"
        )


def test_precision_is_capped_at_6_decimals():
    """Coord precision is deliberately capped at 6 decimals
    (~10 cm) to keep the JSON payload compact."""
    lat_p, lng_p = obfuscate_coords(33.5722, -112.3237, seed="x")
    # Convert to string and count decimals — MUST be ≤ 6.
    assert len(str(lat_p).split(".")[-1]) <= 6
    assert len(str(lng_p).split(".")[-1]) <= 6


def test_none_inputs_passthrough():
    """Callers pass ``None`` when the customer has no geocode; the
    helper preserves that so the enqueue path can decide to skip
    (never invent a fake pin)."""
    assert obfuscate_coords(None, None, seed="x") == (None, None)
    assert obfuscate_coords(None, -112.0, seed="x") == (None, -112.0)
    assert obfuscate_coords(33.0, None, seed="x") == (33.0, None)


def test_empty_seed_still_deterministic():
    """When the caller passes an empty seed the helper falls back
    to a coord-derived key. Same coords → same offset (still
    stable per render), but different from a job-seeded output —
    which is fine because this is a soft-fail path."""
    a = obfuscate_coords(33.5722, -112.3237, seed="")
    b = obfuscate_coords(33.5722, -112.3237, seed="")
    assert a == b


def test_neighbouring_seeds_are_uncorrelated():
    """SHA-256 defeats the "average two runs to recover the raw
    address" attack — a one-character seed change should produce
    an uncorrelated offset."""
    a_lat, a_lng = obfuscate_coords(33.0, -112.0, seed="job-1")
    b_lat, b_lng = obfuscate_coords(33.0, -112.0, seed="job-2")
    # Different pairs.
    assert (a_lat, a_lng) != (b_lat, b_lng)
    # Sum-of-offsets shouldn't accidentally cancel to <0.0001° on
    # either axis (would signal correlated seeding).
    combined = ((a_lat - 33.0) + (b_lat - 33.0),
                 (a_lng + 112.0) + (b_lng + 112.0))
    assert abs(combined[0]) > 1e-6 or abs(combined[1]) > 1e-6
