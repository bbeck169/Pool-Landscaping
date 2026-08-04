"""Phase 41.3 · Feb-2026 — SAFE unused-imports stripper (v2, multi-line aware).

Same guardrail as v1 (only delete if the identifier appears NOWHERE
else in the file), but handles multi-line ``import { ... }`` blocks
which is the shape lucide-react and shadcn ui-kit imports use.

Algorithm
---------
For each ESLint-flagged unused import at ``(file, line)``:

  1. Read the file. Find the enclosing ``import`` statement — walk
     backwards from ``line`` to the first line that starts with
     ``import``, then forward to the closing ``}`` (or line-end if
     it's a default/namespace import).

  2. Verify: does the identifier appear anywhere else in the file
     outside this import statement? If yes, SKIP (plugin
     false-positive — flag for human review).

  3. Rewrite the import block, dropping the identifier from the
     named-import list. If the list becomes empty AND there's no
     default binding, delete the whole block.

Idempotent — safe to re-run after ESLint reports the residual set.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


LINT = json.load(open("/tmp/lint.json"))
DELETED = 0
KEPT = []


def is_used_outside(src, import_start, import_end, name):
    """Verify `name` does NOT appear as a standalone token anywhere
    outside the [import_start, import_end] inclusive line range."""
    lines = src.split("\n")
    pattern = re.compile(rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])")
    for idx, ln in enumerate(lines):
        if import_start <= idx <= import_end:
            continue
        if pattern.search(ln):
            return True
    return False


def find_import_block(lines, hit_line):
    """Return (start_idx, end_idx) inclusive line indices of the
    ``import`` statement containing ``hit_line`` (0-indexed).
    Walks backwards for ``import``, forward for ``;`` or the end of
    the statement."""
    start = hit_line
    while start > 0 and not re.match(r"\s*import\b", lines[start]):
        start -= 1
    # forward until we hit a line ending with ";" (end of statement)
    # or a "from ..." followed by nothing more.
    end = start
    while end < len(lines) - 1:
        ln = lines[end]
        # Statement ends at the line that contains ``from "..."``
        # (with an optional ``;``). It's the FIRST ``from`` we hit.
        if re.search(r'\bfrom\s+["\'][^"\']+["\']\s*;?\s*$', ln):
            return start, end
        end += 1
    return start, end


for entry in LINT:
    path = Path(entry["filePath"])
    msgs = [
        m for m in entry["messages"]
        if m.get("ruleId") == "unused-imports/no-unused-imports"
    ]
    if not msgs:
        continue

    # Reload the file for every message — we mutate incrementally so
    # subsequent finds re-anchor correctly.
    for m in sorted(msgs, key=lambda x: -x["line"]):
        match = re.match(r"'([^']+)' is (?:defined|imported) but never used",
                         m.get("message", ""))
        if not match:
            KEPT.append((str(path), m["line"], m.get("message")))
            continue
        name = match.group(1)
        src = path.read_text()
        lines = src.split("\n")
        # Anchor: the exact line ESLint reported. If it's not an
        # ``import`` line, walk backwards.
        hit = m["line"] - 1
        if hit >= len(lines):
            continue
        start, end = find_import_block(lines, hit)
        block = "\n".join(lines[start:end + 1])
        # Sanity — block must contain the identifier.
        if not re.search(rf"(?<![A-Za-z0-9_$]){re.escape(name)}(?![A-Za-z0-9_$])", block):
            KEPT.append((str(path), m["line"], f"'{name}' not found in resolved import block"))
            continue
        # Independent usage check across the whole file (excluding the
        # import block itself).
        if is_used_outside(src, start, end, name):
            KEPT.append((str(path), m["line"], f"'{name}' — used elsewhere in the file (plugin false-positive)"))
            continue

        # Now rewrite. Match on the LOCAL binding after ``as`` if any.
        # Regex fragments:
        LOCAL_TOK = r"[A-Za-z_$][A-Za-z0-9_$]*"

        # A) Named-import inside the {...}. Match:
        #      Foo,      Foo as Bar,    Foo\n
        # We match ``[<foreign> as ]<name>[, or newline]`` and delete
        # it, plus adjacent whitespace/comma.
        # Strategy: parse the block into (prefix, {names}, suffix) and
        # rewrite the names list.
        named_re = re.compile(
            r"(?P<prefix>import\s+(?:[\w$]+\s*,\s*)?\{)(?P<names>[^}]*)(?P<suffix>\}\s*from\s*[\"'][^\"']+[\"']\s*;?)",
            re.DOTALL,
        )
        nm = named_re.search(block)
        if nm:
            names_raw = nm.group("names")
            # Split by comma while preserving order + whitespace-agnostic.
            items = [it.strip() for it in names_raw.split(",")]
            items = [it for it in items if it]  # drop empties
            def local_binding(it):
                # ``Foo as Bar`` → ``Bar``; ``Foo`` → ``Foo``.
                m2 = re.match(rf"({LOCAL_TOK})\s+as\s+({LOCAL_TOK})$", it)
                if m2:
                    return m2.group(2)
                return it
            new_items = [it for it in items if local_binding(it) != name]
            if len(new_items) == len(items):
                KEPT.append((str(path), m["line"], f"'{name}' — no match in named list"))
                continue
            if new_items:
                new_names = ", ".join(new_items)
                new_block = block[:nm.start("names")] + " " + new_names + " " + block[nm.end("names"):]
            else:
                # Empty named list.
                default_present = bool(re.search(r"import\s+[\w$]+\s*,\s*\{", block))
                if default_present:
                    # Strip the ``, {…}`` part.
                    new_block = named_re.sub(
                        lambda x: re.sub(r",\s*\{[^}]*\}", "", x.group(0)),
                        block,
                        count=1,
                    )
                else:
                    # Delete the whole statement.
                    new_block = ""
            # Splice back.
            new_lines = new_block.split("\n") if new_block else []
            lines = lines[:start] + new_lines + lines[end + 1:]
            path.write_text("\n".join(lines))
            DELETED += 1
            continue

        # B) Default-only ``import Foo from "..."``.
        default_re = re.compile(
            rf"^\s*import\s+{re.escape(name)}\s+from\s+[\"'][^\"']+[\"']\s*;?\s*$",
        )
        if default_re.match(block):
            lines = lines[:start] + lines[end + 1:]
            path.write_text("\n".join(lines))
            DELETED += 1
            continue

        # C) Namespace ``import * as Foo from "..."``.
        ns_re = re.compile(
            rf"^\s*import\s+\*\s+as\s+{re.escape(name)}\s+from\s+[\"'][^\"']+[\"']\s*;?\s*$",
        )
        if ns_re.match(block):
            lines = lines[:start] + lines[end + 1:]
            path.write_text("\n".join(lines))
            DELETED += 1
            continue

        KEPT.append((str(path), m["line"], f"'{name}' — unhandled import shape"))

print(f"[phase41.3] deleted {DELETED} unused-import binding(s); "
      f"kept {len(KEPT)} for review")
for p, ln, why in KEPT[:15]:
    print(f"  KEEP {p}:{ln} — {why}")
if len(KEPT) > 15:
    print(f"  ... plus {len(KEPT) - 15} more")
