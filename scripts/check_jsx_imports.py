#!/usr/bin/env python3
"""check_jsx_imports.py

Scan JSX/TSX files and flag JSX element references (`<Capitalized ...>`)
that aren't declared via `import`, `const`, `let`, `var`, or `function`
in the same file.

This catches the exact bug class we hit 3× in `PoolChecklistForm.jsx`:
someone adds `<FlaskConical />` without adding it to the lucide-react
import statement. Webpack keeps compiling but the page throws
`ReferenceError` at runtime.

Exit code:
  0 — all references resolve
  1 — at least one undeclared JSX identifier
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

# JSX tag names: `<PascalCase` at the start of a tag, not part of `</...`.
JSX_TAG_RE = re.compile(r"<([A-Z][A-Za-z0-9_]*)")

# Any name-binding we care about. Very forgiving — false negatives beat
# false positives here.
DECL_PATTERNS = [
    re.compile(r"\bimport\s+([A-Z][A-Za-z0-9_]*)\b"),           # default import
    re.compile(r"import\s*\{([^}]+)\}\s*from"),                  # named imports
    re.compile(r"import\s*\*\s*as\s+([A-Z][A-Za-z0-9_]*)"),      # namespace import
    re.compile(r"\bconst\s+([A-Z][A-Za-z0-9_]*)\s*="),           # const Foo = ...
    re.compile(r"\bconst\s*\{([^}]+)\}\s*="),                    # const { A, B } = ...
    re.compile(r"\blet\s+([A-Z][A-Za-z0-9_]*)\s*="),
    re.compile(r"\bvar\s+([A-Z][A-Za-z0-9_]*)\s*="),
    re.compile(r"\bfunction\s+([A-Z][A-Za-z0-9_]*)"),
    re.compile(r"\bclass\s+([A-Z][A-Za-z0-9_]*)"),
    # Destructured rename inside function params or const:
    # `{ icon: Icon }`, `{ Component: Comp }`, etc.
    re.compile(r"[{,]\s*[a-zA-Z_][a-zA-Z0-9_]*\s*:\s*([A-Z][A-Za-z0-9_]*)"),
]

# HTML / SVG tags & other known-safe things — case-insensitive match on the
# lowercased first char isn't enough because we already gated on PascalCase.
BUILTIN_SAFE = {
    "React", "Fragment", "Suspense", "Component", "PureComponent",
    "StrictMode", "Profiler",
}


def _strip_comments(src: str) -> str:
    """Very lightweight comment stripper — removes // line comments
    FIRST (so a stray ``/*`` substring inside a ``//`` comment can't
    confuse the block-comment regex into eating subsequent real code),
    then removes /* ... */ blocks."""
    # // line comments (avoid protocol URLs like https://). Done FIRST.
    src = re.sub(r"(^|[^:])//[^\n]*", r"\1", src)
    # /* ... */ block comments. Non-greedy + DOTALL so unterminated
    # blocks fail to match rather than eating everything to EOF.
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return src


def declared_names(source: str) -> set[str]:
    names: set[str] = set(BUILTIN_SAFE)
    for pat in DECL_PATTERNS:
        for m in pat.finditer(source):
            group = m.group(1)
            for tok in re.split(r"[,\s]+", group):
                tok = tok.strip()
                if not tok:
                    continue
                # Handle `X as Y` — the local name is Y.
                if " as " in tok:
                    _, tok = tok.split(" as ")
                    tok = tok.strip()
                if re.match(r"^[A-Z][A-Za-z0-9_]*$", tok):
                    names.add(tok)
    # Also permit any PascalCase identifier that appears inside a
    # `.map((...) => ...)` destructure position — hard to catch with a
    # single regex, so we take a bag-of-tokens approach: any PascalCase
    # identifier that appears anywhere in the file OTHER than as a JSX
    # opening tag counts as "possibly bound" and won't be flagged. This
    # is intentionally lenient — the goal is zero false positives on
    # correctly-written files while still catching the "typo'd icon
    # import" bug where the identifier doesn't appear anywhere else.
    tag_positions = {m.start() for m in JSX_TAG_RE.finditer(source)}
    for m in re.finditer(r"\b([A-Z][A-Za-z0-9_]*)\b", source):
        # Skip the JSX tag hits themselves.
        if (m.start() - 1) in tag_positions:  # position of the `<`
            continue
        names.add(m.group(1))
    return names


def scan_file(path: Path) -> list[tuple[int, str]]:
    src = _strip_comments(path.read_text())
    declared = declared_names(src)
    missing: list[tuple[int, str]] = []
    for i, line in enumerate(src.splitlines(), start=1):
        for m in JSX_TAG_RE.finditer(line):
            tag = m.group(1)
            if tag not in declared:
                missing.append((i, tag))
    return missing


def main(argv: list[str]) -> int:
    # --prod-only excludes test / __tests__ directories. The scanner
    # cannot track vi.mock-injected names (they aren't declared in
    # the usual import / const / function patterns), and vitest is
    # the appropriate guard for test-file identifier bugs. CI uses
    # --prod-only so the ReferenceError-at-runtime class of bug
    # (which only matters in shipped production code) is blocked.
    prod_only = False
    args = list(argv[1:])
    if "--prod-only" in args:
        prod_only = True
        args = [a for a in args if a != "--prod-only"]
    if args:
        roots = [Path(a) for a in args]
    else:
        roots = [Path("/app/frontend/src"), Path("/app/mobile/app"),
                 Path("/app/mobile/src")]
    errors = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix != ".jsx":
                # TSX has type-annotation generics like `Array<Job>` or
                # `useState<User>()` that look identical to JSX tags via
                # regex. Restrict to .jsx where the false-positive rate is
                # essentially zero and where our recurring bug lives.
                continue
            if "node_modules" in path.parts:
                continue
            if prod_only:
                # Skip test harness directories — vitest is their guard.
                parts = set(path.parts)
                if "test" in parts or "__tests__" in parts:
                    continue
            issues = scan_file(path)
            if issues:
                # Deduplicate by tag but keep first line hit.
                seen: dict[str, int] = {}
                for ln, tag in issues:
                    seen.setdefault(tag, ln)
                for tag, ln in seen.items():
                    print(f"  {path.relative_to('/app')}:{ln}  undeclared JSX <{tag}>")
                    errors += 1
    if errors:
        print(f"\n[check_jsx_imports] {errors} undeclared JSX identifiers.")
        return 1
    print("[check_jsx_imports] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
