#!/usr/bin/env python3
"""check_dead_imports.py

Advisory scanner — flag `import { X, Y }` / `import Default from ...` /
`import * as ns from ...` where the imported symbol is never referenced
elsewhere in the same file.

Rationale: dead imports accumulate when a component is refactored but
the old symbol is left behind. They bloat bundle chunk graphs, mask
real usage from grep, and (occasionally) mask a genuine typo (imported
`useMemo`, meant to call `useMemo` but actually referenced `useMemos`
lower down — the scanner would still miss that particular case but
flags all the trailing dead-weight).

Same posture as `check_js_identifiers.py`: prints advisory lines and
exits 0. Wired into preflight.sh with a trailing `|| true` so an
overzealous flag never blocks a phase from shipping.

Restricted to `.jsx` / `.tsx` / `.js` / `.ts` under `/app/frontend/src`
and `/app/mobile/{src,app}` (skipping generated / vendored code).

Adversarial test harness at the bottom of this file — run `python3
check_dead_imports.py --self-test` to exercise it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

# ─── Configuration ─────────────────────────────────────────────────────
ROOTS = [
    Path("/app/frontend/src"),
    Path("/app/mobile/src"),
    Path("/app/mobile/app"),
]
EXTS = {".jsx", ".tsx", ".js", ".ts"}
# Never scan these — they either don't have real dead-import surface
# area or produce too many false positives to be actionable.
SKIP_DIR_PARTS = {"node_modules", "__generated__", "build", "dist", ".next"}

# Modules whose "imports" are side-effect only (CSS, polyfills, tests,
# type-only namespaces) — skip them so we don't yell about `import
# './styles.css'` etc. This list is intentionally short; anything the
# scanner can't confidently classify is left flagged so a human can
# eyeball it.
SIDE_EFFECT_MODULES = {"react-native-gesture-handler"}

# Names that are commonly imported for JSX runtime side-effects (classic
# React transform) even when they don't appear elsewhere in the file.
# The modern automatic JSX transform doesn't need them, but a lot of
# our files still `import React from 'react'` out of habit. Suppress
# the flag rather than nagging on every JSX component.
ALWAYS_LIVE_NAMES = {"React", "h" }


# ─── Import parsing ────────────────────────────────────────────────────
# Matches full multi-line imports terminated by a semicolon or newline.
# Handles:
#   import X from 'foo'
#   import X, { Y, Z as W } from 'foo'
#   import { A, B as C } from 'foo'
#   import * as ns from 'foo'
#   import 'side-effect'         ← side-effect, no bound name
#   import type { T } from 'foo' ← TS type-only, ignored (see below)
IMPORT_RE = re.compile(
    r"^\s*import\s+"
    r"(?P<clauses>[^'\";]+?)"
    r"\s+from\s+['\"](?P<module>[^'\"]+)['\"]\s*;?\s*$",
    re.MULTILINE,
)
SIDE_EFFECT_IMPORT_RE = re.compile(
    r"^\s*import\s+['\"](?P<module>[^'\"]+)['\"]\s*;?\s*$", re.MULTILINE,
)


def _parse_clause(clauses: str) -> list[tuple[str, str]]:
    """Given the middle of an import ("A, { B as C, D }"), return a list
    of (bound_name, original_name) tuples. `original_name` is what was
    imported from the module (used only for reporting; the "dead"
    check runs against `bound_name`).
    """
    out: list[tuple[str, str]] = []
    clauses = clauses.strip()
    if not clauses:
        return out

    # `import * as ns from '...'` — namespace binding.
    star = re.match(r"\*\s*as\s+([A-Za-z_$][A-Za-z0-9_$]*)$", clauses)
    if star:
        return [(star.group(1), "*")]

    # Split default binding from the named block.
    default = None
    named_block = None
    if "{" in clauses:
        pre, rest = clauses.split("{", 1)
        default = pre.strip().rstrip(",").strip() or None
        named_block = rest.rstrip("}").strip()
    else:
        default = clauses.strip()

    if default:
        # Could still contain `X, * as ns` — split on comma.
        for part in default.split(","):
            part = part.strip()
            if not part:
                continue
            star2 = re.match(r"\*\s*as\s+([A-Za-z_$][A-Za-z0-9_$]*)$", part)
            if star2:
                out.append((star2.group(1), "*"))
            else:
                out.append((part, part))

    if named_block:
        for item in named_block.split(","):
            item = item.strip()
            if not item:
                continue
            # `X as Y` — Y is what gets bound in the file.
            m = re.match(r"([A-Za-z_$][A-Za-z0-9_$]*)(?:\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*))?$", item)
            if not m:
                continue
            orig, alias = m.group(1), m.group(2)
            out.append((alias or orig, orig))
    return out


def _strip_comments_and_strings(src: str) -> str:
    """Very rough scrubber so we don't flag identifiers that only appear
    in comments or string literals. Not a full JS lexer — but good
    enough to drop the obvious false-positive class of a name only
    referenced inside a `//`-comment or `"..."` string.
    """
    # Line comments.
    src = re.sub(r"//.*", "", src)
    # Block comments.
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    # Double-quoted strings (but not template literals — template
    # literals can reference identifiers via ${x} so we keep them).
    src = re.sub(r'"(?:\\.|[^"\\])*"', '""', src)
    # Single-quoted strings.
    src = re.sub(r"'(?:\\.|[^'\\])*'", "''", src)
    return src


def _find_dead_imports(path: Path) -> list[tuple[int, str, str]]:
    """Return a list of `(line_no, imported_name, module)` tuples for
    dead imports in this file. Returns [] if the file scans clean.
    """
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return []

    # Also skip TS type-only imports — the scanner regex would flag
    # them because types don't show up in runtime references. Simplest
    # is to strip whole `import type { ... } from '...'` lines before
    # parsing.
    src = re.sub(r"^\s*import\s+type\s+[^;]+;?\s*$", "", src, flags=re.MULTILINE)

    # Body = everything after the top of the file where imports live.
    # We use the whole file minus the import lines themselves for the
    # "usage" search — importing a symbol AND using it later in the
    # same file is valid; only importing without using is dead.
    non_import_body = re.sub(r"^\s*import\s+[^;]+;?\s*$", "", src, flags=re.MULTILINE)
    stripped = _strip_comments_and_strings(non_import_body)

    out: list[tuple[int, str, str]] = []
    for m in IMPORT_RE.finditer(src):
        module = m.group("module").strip()
        if module in SIDE_EFFECT_MODULES:
            continue
        # Count line number by position within source.
        line_no = src.count("\n", 0, m.start()) + 1
        for bound, _orig in _parse_clause(m.group("clauses")):
            if bound in ALWAYS_LIVE_NAMES:
                continue
            # `*` namespace bindings can be referenced as `ns.member`
            # so require a word boundary after them either way — same
            # rule as any other identifier.
            pattern = re.compile(r"\b" + re.escape(bound) + r"\b")
            if not pattern.search(stripped):
                out.append((line_no, bound, module))
    return out


# ─── File walking ──────────────────────────────────────────────────────
def _walk(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix not in EXTS:
                continue
            if set(p.parts) & SKIP_DIR_PARTS:
                continue
            yield p


def _run_sweep() -> int:
    total = 0
    for f in _walk(ROOTS):
        dead = _find_dead_imports(f)
        for line, name, module in dead:
            rel = f
            try:
                rel = f.relative_to("/app")
            except ValueError:
                pass
            print(f"  {rel}:{line}  dead-import `{name}` from `{module}`")
            total += 1
    if total:
        print(f"\n[check_dead_imports] {total} suspicious dead imports (WARN).")
    else:
        print("[check_dead_imports] clean.")
    return 0  # advisory — never block a `finish`.


# ─── Adversarial self-test ─────────────────────────────────────────────
def _self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmpp = Path(tmp)
        # (1) Obvious dead import — must be flagged.
        (tmpp / "a.jsx").write_text(
            "import React, { useState, useEffect } from 'react';\n"
            "export default function A() {\n"
            "  const [x] = useState(0);\n"  # useEffect never referenced
            "  return <div>{x}</div>;\n"
            "}\n",
        )
        # (2) All imports used — must be silent.
        (tmpp / "b.jsx").write_text(
            "import React, { useState } from 'react';\n"
            "export default function B() {\n"
            "  const [x, setX] = useState(0);\n"
            "  return <div onClick={() => setX(1)}>{x}</div>;\n"
            "}\n",
        )
        # (3) Namespace import used via dotted access — must be silent.
        (tmpp / "c.tsx").write_text(
            "import * as fs from 'node:fs';\n"
            "export const readIt = () => fs.readFileSync('x');\n",
        )
        # (4) Imported only inside a string / comment — MUST be flagged.
        (tmpp / "d.jsx").write_text(
            "import { NeverReallyUsed } from 'somewhere';\n"
            "export default function D() {\n"
            "  return <div title='NeverReallyUsed literal string'>hi</div>;\n"
            "  // NeverReallyUsed in a comment doesn't count either\n"
            "}\n",
        )
        # (5) `as` rename — dead alias must be flagged with the alias.
        (tmpp / "e.jsx").write_text(
            "import { useState as useLocalState } from 'react';\n"
            "export default function E() { return null; }\n",
        )
        # (6) type-only import — MUST NOT be flagged.
        (tmpp / "f.tsx").write_text(
            "import type { Foo } from './types';\n"
            "export const g = () => 1;\n",
        )

        expected_hits = {
            (tmpp / "a.jsx", "useEffect"),
            (tmpp / "d.jsx", "NeverReallyUsed"),
            (tmpp / "e.jsx", "useLocalState"),
        }
        must_be_silent = {tmpp / "b.jsx", tmpp / "c.tsx", tmpp / "f.tsx"}

        errs = 0
        for p in [tmpp / n for n in ("a.jsx", "b.jsx", "c.tsx", "d.jsx", "e.jsx", "f.tsx")]:
            dead = _find_dead_imports(p)
            hits = {(p, name) for (_ln, name, _m) in dead}
            expected_for_this = {(pp, nm) for (pp, nm) in expected_hits if pp == p}
            if hits != expected_for_this:
                print(f"  SELF-TEST FAIL {p.name}: expected {expected_for_this}, got {hits}")
                errs += 1
            elif p in must_be_silent and dead:
                print(f"  SELF-TEST FAIL {p.name}: expected silent, got {dead}")
                errs += 1
            else:
                print(f"  SELF-TEST PASS {p.name}: {sorted(nm for (_ln, nm, _m) in dead)}")
        if errs:
            print(f"\n[self-test] {errs} failures")
            return 1
        print("\n[self-test] all cases OK")
        return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(_self_test())
    sys.exit(_run_sweep())
