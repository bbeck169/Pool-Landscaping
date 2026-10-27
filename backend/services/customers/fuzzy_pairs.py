"""Ticket 292982 · GIL-free pair search for the duplicate scans.

Both duplicate detectors used to compare every customer name against
every other one in pure Python (~2.9M pairs at 2.4K customers, 15-25 s
of CPU per scan).  Running that under ``asyncio.to_thread`` does not
help: the thread holds the GIL, so every concurrent request on the
worker (profile pages included) slows down while a scan is running.

The helpers here find the same pairs with ``rapidfuzz`` (C++, releases
the GIL, multi-threaded) in row blocks so memory stays bounded.  Results
are identical to the old loops: candidates found by the C++ scorer are
re-checked with the original Python scorer before they are returned, so
the only thing that changed is how fast non-matching pairs are rejected.
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Callable, Dict, List, Sequence, Set, Tuple

import numpy as np
from rapidfuzz import process
from rapidfuzz.distance import JaroWinkler, Levenshtein

# Rows per cdist block: block x N float32 matrix = 256 x 20k x 4B = 20MB max.
_BLOCK = 256
# Below this threshold the C++ pre-filter and the legacy scorer can disagree
# about the Winkler boost (rapidfuzz boosts only when jaro > 0.7); callers
# should use their legacy loop instead.
JW_MIN_SAFE_THRESHOLD = 0.85


def jaro_winkler_neighbors(
    names: Sequence[str],
    threshold: float,
    exact_scorer: Callable[[str, str], float],
) -> Dict[int, List[Tuple[int, float]]]:
    """``{i: [(j, score), ...]}`` for every ``j > i`` with
    ``names[i] != names[j]`` and ``exact_scorer(names[i], names[j]) >= threshold``.

    ``j`` is ascending per ``i`` (same order the old nested loop visited).
    """
    out: Dict[int, List[Tuple[int, float]]] = {}
    n = len(names)
    if n < 2:
        return out
    # Slightly lower cutoff for the C++ pass (float32 rounding), exact
    # re-check below decides.
    cutoff = max(0.0, threshold - 1e-3)
    for i0 in range(0, n, _BLOCK):
        i1 = min(i0 + _BLOCK, n)
        mat = process.cdist(
            names[i0:i1], names,
            scorer=JaroWinkler.similarity,
            score_cutoff=cutoff, dtype=np.float32, workers=-1,
        )
        rows_idx, cols_idx = np.nonzero(mat)
        for r, j in zip(rows_idx.tolist(), cols_idx.tolist()):
            i = i0 + r
            if j <= i or names[i] == names[j]:
                continue
            score = exact_scorer(names[i], names[j])
            if score >= threshold:
                out.setdefault(i, []).append((j, score))
    for lst in out.values():
        lst.sort(key=lambda t: t[0])
    return out


def _substring_pairs(names: Sequence[str], min_len: int) -> Set[Tuple[int, int]]:
    """Pairs ``(i, j)``, ``i < j``, where one name is a substring of the
    other (both >= ``min_len`` chars, names not equal).  Uses a single
    ``str.find`` sweep over the newline-joined names instead of N^2
    ``in`` checks."""
    pairs: Set[Tuple[int, int]] = set()
    # Names are whitespace-collapsed upstream, so '\n' is a safe separator;
    # defensive guard anyway.
    if any("\n" in s for s in names):
        for i, a in enumerate(names):
            for j in range(i + 1, len(names)):
                b = names[j]
                if a != b and len(a) >= min_len and len(b) >= min_len \
                        and (a in b or b in a):
                    pairs.add((i, j))
        return pairs
    blob = "\n".join(names)
    starts: List[int] = []
    pos = 0
    for s in names:
        starts.append(pos)
        pos += len(s) + 1
    for i, a in enumerate(names):
        if len(a) < min_len:
            continue
        p = blob.find(a)
        while p != -1:
            j = bisect_right(starts, p) - 1
            b = names[j]
            if j != i and a != b and len(b) >= min_len:
                pairs.add((i, j) if i < j else (j, i))
            nxt = starts[j + 1] if j + 1 < len(starts) else -1
            if nxt == -1:
                break
            p = blob.find(a, nxt)
    return pairs


def levenshtein_or_substring_pairs(
    names: Sequence[str],
    max_dist: int,
    min_len: int,
) -> List[Tuple[int, int]]:
    """All ``(i, j)``, ``i < j``, with ``names[i] != names[j]`` and
    (Levenshtein distance <= ``max_dist`` OR one is a substring of the
    other), sorted by ``(i, j)`` -- the order the old nested loop visited."""
    n = len(names)
    pairs: Set[Tuple[int, int]] = set()
    if n < 2:
        return []
    for i0 in range(0, n, _BLOCK):
        i1 = min(i0 + _BLOCK, n)
        mat = process.cdist(
            names[i0:i1], names,
            scorer=Levenshtein.distance,
            score_cutoff=max_dist, dtype=np.uint8, workers=-1,
        )
        # cdist reports ``cutoff + 1`` for anything over the cutoff.
        rows_idx, cols_idx = np.nonzero(mat <= max_dist)
        for r, j in zip(rows_idx.tolist(), cols_idx.tolist()):
            i = i0 + r
            if j > i and names[i] != names[j]:
                pairs.add((i, j))
    pairs |= _substring_pairs(names, min_len)
    return sorted(pairs)
