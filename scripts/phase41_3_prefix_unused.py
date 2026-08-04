"""Phase 41.3 · Feb-2026 — Bulk prefix unused vars with `_` (smart).

v2 fix: skip PascalCase identifiers entirely. Those are almost always
React component definitions or exported types — prefixing them with
``_`` breaks ``react-hooks/rules-of-hooks`` because the rule requires
component function names to start with an uppercase letter. Leave
PascalCase identifiers untouched; a follow-up commit can either
delete truly-dead components or annotate them for keep.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


LINT = json.load(open("/tmp/lint.json"))
PREFIXED = 0
SKIPPED_PASCAL = 0
SKIPPED_ALREADY = 0
SKIPPED_OTHER = 0

for entry in LINT:
    path = Path(entry["filePath"])
    msgs = [
        m for m in entry["messages"]
        if m.get("ruleId") == "unused-imports/no-unused-vars"
    ]
    if not msgs:
        continue
    src = path.read_text()
    lines = src.split("\n")
    per_line = {}
    for m in msgs:
        match = re.match(r"'([^']+)' is", m.get("message", ""))
        if not match:
            SKIPPED_OTHER += 1
            continue
        name = match.group(1)
        if name.startswith("_"):
            SKIPPED_ALREADY += 1
            continue
        # PascalCase = starts with an uppercase letter followed by any
        # combination of letters / digits. Includes plain single-char
        # uppercase like ``H`` and mixed like ``BtnPrimary``.
        if re.match(r"^[A-Z][A-Za-z0-9]*$", name):
            SKIPPED_PASCAL += 1
            continue
        per_line.setdefault(m["line"], []).append(name)
    for ln, names in per_line.items():
        idx = ln - 1
        if idx >= len(lines):
            continue
        original = lines[idx]
        new = original
        for name in names:
            pattern = re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])")
            new_candidate = pattern.sub(f"_{name}", new, count=1)
            if new_candidate != new:
                new = new_candidate
        if new != original:
            lines[idx] = new
            PREFIXED += 1
    path.write_text("\n".join(lines))

print(f"[phase41.3] prefixed lines: {PREFIXED} · "
      f"skipped PascalCase: {SKIPPED_PASCAL} · "
      f"already prefixed: {SKIPPED_ALREADY} · "
      f"other: {SKIPPED_OTHER}")
