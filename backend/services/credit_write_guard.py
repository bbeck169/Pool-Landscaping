"""Credit write-path guard — P0b Stage 2 S2-1 · Feb-2026.

Boot-time static scan that refuses to let a NEW direct writer to the
canonical credit storage (``db.customer_credits`` / ``db.customer_
credits_balance`` / ``customers.credit_balance_cents``) slip past the
``services.customer_balance.mutate_credit`` choke point.

Runs once at backend startup. On preview env, orphan writers fail
boot loudly so a bad PR never ships. On production env, orphan writers
log ``ERROR`` so an on-call operator sees the regression but the pod
still boots (we don't want to black-hole prod on a static-analysis
false-positive).

The scan is a shallow grep — regex-literal matches against known-
dangerous call patterns. Any line that matches ONE of the dangerous
patterns MUST either (a) live in an allowlisted file + line range or
(b) carry an inline ``# credit-write-allowlist: <reason>`` marker on
the same or preceding line. The allowlist is intentionally sparse so
future reviewers see the full set in one place.

The guard is purely a code-shape check. It does NOT touch the
database, it does NOT run on request path, it does NOT add any
latency to normal operation.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger("services.credit_write_guard")

_BACKEND_ROOT = Path(__file__).resolve().parent.parent  # backend/

# Patterns that identify a direct write to canonical credit storage.
# Each tuple: (compiled_regex, human_label).
_DANGEROUS_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"db\.customer_credits\.insert_one\b"),
     "db.customer_credits.insert_one"),
    (re.compile(r"db\.customer_credits\.insert_many\b"),
     "db.customer_credits.insert_many"),
    (re.compile(r"db\.customer_credits_balance\.update_one\b"),
     "db.customer_credits_balance.update_one"),
    (re.compile(r"db\.customer_credits_balance\.update_many\b"),
     "db.customer_credits_balance.update_many"),
    (re.compile(r"db\.customer_credits_balance\.replace_one\b"),
     "db.customer_credits_balance.replace_one"),
    # Direct update to the denormalised singular field on the
    # customers collection outside the ``customer_balance`` service.
    # Phrased so legitimate reads (``find_one({...}, {"credit_
    # balance_cents": 1})``) don't trip the pattern.
    (re.compile(r'\$set.*["\']credit_balance_cents["\']'),
     "$set credit_balance_cents"),
]

# Files that are KNOWN to perform the writes legitimately — the
# choke point itself + its test harness. Keep this list to the
# smallest surface possible.
_ALLOWLISTED_FILES = {
    "services/customer_balance.py",       # The choke point.
    "services/credit_write_guard.py",     # This file (regex literals).
    "services/credit_write_guard.pyc",
}

# Files that should be scanned. Scoped tightly to the modules where
# credit writes could plausibly originate.
_SCANNED_DIRS = ("routers", "services")

# Inline opt-out marker — if a line (or the line immediately before)
# carries this exact string, the match is treated as justified.
_INLINE_ALLOW = "credit-write-allowlist:"


def _scan_file(path: Path) -> List[Dict[str, object]]:
    """Return a list of orphan-write records found in ``path``."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    offenders: List[Dict[str, object]] = []
    for idx, line in enumerate(lines, start=1):
        for pat, label in _DANGEROUS_PATTERNS:
            if not pat.search(line):
                continue
            # Inline justification check — same line.
            if _INLINE_ALLOW in line:
                continue
            # OR previous line.
            if idx >= 2 and _INLINE_ALLOW in lines[idx - 2]:
                continue
            offenders.append({
                "file": str(path.relative_to(_BACKEND_ROOT)),
                "line": idx,
                "pattern": label,
                "snippet": line.strip()[:160],
            })
    return offenders


def _is_production_env() -> bool:
    return (os.environ.get("APP_ENV") or "").strip().lower() == "production"


def assert_no_orphan_credit_writes() -> Dict[str, object]:
    """Run the scan. Returns a structured report.

    Shape::

        {
          "status":           "ok" | "orphan_writes" ,
          "scanned_dirs":     [str, ...],
          "files_scanned":    int,
          "offenders":        [{file, line, pattern, snippet}, ...],
          "allowlisted_files":[str, ...],
          "env":              "production" | <preview>,
        }

    On preview env with offenders present, raises ``AssertionError``
    AFTER populating + returning the report (so the caller can log it
    before the raise propagates). On production env with offenders,
    logs ERROR and returns the report WITHOUT raising.
    """
    report: Dict[str, object] = {
        "status": "ok",
        "scanned_dirs": list(_SCANNED_DIRS),
        "files_scanned": 0,
        "offenders": [],
        "allowlisted_files": sorted(_ALLOWLISTED_FILES),
        "env": "production" if _is_production_env() else "preview",
    }

    for d in _SCANNED_DIRS:
        root = _BACKEND_ROOT / d
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = str(path.relative_to(_BACKEND_ROOT))
            if rel in _ALLOWLISTED_FILES:
                continue
            if "__pycache__" in rel:
                continue
            report["files_scanned"] = int(report["files_scanned"]) + 1
            report["offenders"].extend(_scan_file(path))  # type: ignore[arg-type]

    if report["offenders"]:
        report["status"] = "orphan_writes"
        _msg = (
            "[credit-write-guard] %d orphan credit-write(s) detected "
            "outside services.customer_balance.mutate_credit:\n%s"
            "\nFix: refactor each site to call mutate_credit(), OR add "
            "an inline '# credit-write-allowlist: <reason>' marker on "
            "the same (or preceding) line with a human-readable "
            "justification."
        )
        bullets = "\n".join(
            f"  · {o['file']}:{o['line']}  [{o['pattern']}]  {o['snippet']}"
            for o in report["offenders"]  # type: ignore[attr-defined]
        )
        if _is_production_env():
            logger.error(_msg, len(report["offenders"]), bullets)
        else:
            logger.error(_msg, len(report["offenders"]), bullets)
            raise AssertionError(
                f"credit-write-guard: {len(report['offenders'])} orphan "
                f"writer(s) detected — see pod logs for the per-file "
                f"line listing."
            )
    else:
        logger.info(
            "[credit-write-guard] OK — scanned %d file(s) across %s; "
            "zero orphan credit writes outside the choke point.",
            report["files_scanned"],
            ", ".join(_SCANNED_DIRS),
        )
    return report


__all__ = ["assert_no_orphan_credit_writes"]
