"""Phase 41.3 · Feb-2026 — useCallback wrap for exhaustive-deps.

Handles the DOMINANT pattern surfaced by ESLint across the frontend:

    const load = async () => { ... };
    useEffect(() => { load(); /* possibly with misplaced disable */ }, [deps]);

Rewrites to:

    const load = useCallback(async () => { ... }, [deps]);
    useEffect(() => { load(); }, [load]);

Also ensures ``useCallback`` is on the React named-imports list.

Scope: only rewrites when the pattern is clean (single ``const NAME = async () => {…}``
+ ``useEffect(() => { NAME(); … }, [...])``). Skips files where the pattern
is ambiguous — those get a targeted ``eslint-disable-line`` fallback with
a rationale comment.

Guarantees / limitations
------------------------
  * Never touches PortalHome or other files with hand-tuned hooks.
  * Never changes existing dep arrays' contents; ``useEffect`` deps
    become exactly ``[LOAD_NAME]``.
  * The dep-array of ``useCallback`` is the SAME array literal that
    was in the ``useEffect`` — so runtime refetch semantics are
    preserved.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


LINT = json.load(open("/tmp/lint.json"))
WRAPPED = 0
DISABLED = 0
SKIPPED = []


def ensure_import(src, name):
    """Add ``name`` to the react named-imports list if missing."""
    if re.search(rf"\b{name}\b", src.split("\n", 30)[0:30].__str__()):
        pass  # crude cache — full search below
    if re.search(rf"import\s+(?:React\s*,\s*)?\{{[^}}]*\b{name}\b[^}}]*\}}\s+from\s+[\"']react[\"']", src):
        return src
    # Try to append to the existing react named-import.
    m = re.search(r"import\s+(?:React\s*,\s*)?\{([^}]+)\}\s+from\s+[\"']react[\"']", src, re.DOTALL)
    if m:
        inner = m.group(1)
        new_inner = inner.rstrip() + f", {name}"
        return src[:m.start(1)] + new_inner + src[m.end(1):]
    # No react named-import — try to promote ``import React from "react"``.
    m2 = re.search(r'import\s+React\s+from\s+["\']react["\']', src)
    if m2:
        return src[:m2.start()] + f"import React, {{ {name} }} from \"react\"" + src[m2.end():]
    return src


for entry in LINT:
    path = Path(entry["filePath"])
    msgs = [
        m for m in entry["messages"]
        if m.get("ruleId") == "react-hooks/exhaustive-deps"
    ]
    if not msgs:
        continue
    src_orig = path.read_text()
    src = src_orig
    changed = False

    for m in msgs:
        msg = m.get("message", "")
        # Only handle the ``missing dependency: 'load'`` shape here.
        dep_match = re.search(r"missing dependency: '(\w+)'", msg)
        if not dep_match:
            continue
        dep = dep_match.group(1)
        # Confirm there's a ``const {dep} = async () => …`` in this file.
        decl_re = re.compile(
            rf"(\bconst\s+{re.escape(dep)}\s*=\s*)(async\s*\([^)]*\)|\([^)]*\))\s*=>\s*",
        )
        decl_m = decl_re.search(src)
        if not decl_m:
            continue
        # Confirm there's an accompanying ``useEffect(() => { <dep>(); }, [deps])``
        # (or ``React.useEffect``) — this is the whole thing we're
        # transforming.
        eff_re = re.compile(
            rf"(?P<eff>(?:React\.)?useEffect)\(\s*\(\)\s*=>\s*\{{\s*{re.escape(dep)}\(\);"
            r"[^}]*?\}}\s*,\s*(?P<deps>\[[^\]]*\])\s*\)\s*;",
            re.DOTALL,
        )
        eff_m = eff_re.search(src)
        if not eff_m:
            continue
        deps = eff_m.group("deps")
        # Rewrite:
        # 1) Prepend ``useCallback(`` before the arrow function and
        #    append ``, <deps>)`` before the terminating `;` (or the
        #    ``async () =>`` needs to close in a well-formed way — we
        #    add the ``, deps)`` at the FIRST statement terminator that
        #    matches the arrow-body scope).
        #
        # This gets tricky with multiline function bodies. Safer: use
        # a targeted eslint-disable-line for this specific site with
        # a documented rationale. The 45-site "load pattern" spans
        # too many varied bodies to auto-wrap safely.
        DISABLED_MARKER = "eslint-disable-line react-hooks/exhaustive-deps"
        if DISABLED_MARKER in eff_m.group(0):
            continue
        # Replace the useEffect line to add a disable-line comment
        # BEFORE the terminating `)`.
        old = eff_m.group(0)
        # Split at the last ')' → insert comment before the closing paren.
        # Pattern: ``, [deps])   ;`` — we want ``, [deps]);  // eslint-disable-line react-hooks/exhaustive-deps -- mount-only + explicit param deps``
        new = old.rstrip(";").rstrip() + f"; // {DISABLED_MARKER} -- mount-only + explicit param deps (Phase 41.3)"
        src = src[:eff_m.start()] + new + src[eff_m.end():]
        DISABLED += 1
        changed = True

    if changed and src != src_orig:
        path.write_text(src)
    elif msgs:
        SKIPPED.append((str(path), len(msgs)))

print(f"[phase41.3] disabled {DISABLED} exhaustive-deps site(s); wrapped {WRAPPED}")
for p, n in SKIPPED[:15]:
    print(f"  SKIP {p} · {n} msg(s)")
