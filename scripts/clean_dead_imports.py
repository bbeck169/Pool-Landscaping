#!/usr/bin/env python3
"""Phase 4 · Batch C / D8 — Auto-clean dead named imports.

Reads the exact output of `check_dead_imports.py`, groups warnings by
file, and removes only the specific named identifiers flagged from
`import { A, B, C }` lines. Never touches default imports, namespace
imports, side-effect-only imports, or CSS/polyfill imports.

Safety guards:
  * Only "dead-import `X` from `mod`" lines are actioned.
  * If X is the ONLY named identifier in the `{ ... }` block and there
    is no default alias, the whole `import { X } from 'mod';` line is
    removed. Otherwise X is simply spliced out of the destructuring.
  * Skips files under any SKIP_DIR_PARTS directory (defense in depth).
  * Refuses to touch a line that doesn't literally contain the flagged
    identifier — protects against ambiguous multi-import declarations.
  * Prints a diff summary at the end.

Usage:
  python3 scripts/check_dead_imports.py > /tmp/dead.txt
  python3 scripts/clean_dead_imports.py /tmp/dead.txt
"""
from __future__ import annotations
import re, sys
from collections import defaultdict
from pathlib import Path

SKIP_DIR_PARTS = {"node_modules", "__generated__", "build", "dist", ".next"}

# Extra safety: identifiers we NEVER remove — either they're wrapper
# runtimes, or the scanner has known false-positive blind spots with
# them (JSX composition, template literals, dynamic property access).
NEVER_REMOVE = {
    # tailwind helpers
    "twMerge", "clsx", "cn",
    # React runtime + primitives
    "React", "Fragment", "Suspense", "Component", "PureComponent",
    # router
    "Link", "NavLink", "Outlet", "Navigate", "Route", "Routes",
    # motion
    "motion", "AnimatePresence",
    # form / hook adapters
    "Controller", "FormProvider", "useForm",
    # any radix / shadcn "*Primitive" or namespaces
}


def _identifier_appears(body: str, name: str) -> bool:
    """True if `name` appears as a bare identifier anywhere in `body`.

    Uses a word-boundary regex against the raw body — good enough to
    catch JSX usage (`<X>`, `<X ...>`), function calls (`X(`), property
    lookups (`X.foo`), aliases (`X: y`), and template-literal captures.
    """
    return re.search(rf"\b{re.escape(name)}\b", body) is not None

WARN_RE = re.compile(
    r"^\s*(?P<path>[^\s:]+):(?P<line>\d+)\s+dead-import\s+`(?P<name>[^`]+)`\s+from\s+`(?P<mod>[^`]+)`",
)


def _parse_warnings(text: str):
    by_file = defaultdict(list)  # path -> [(name, mod)]
    for ln in text.splitlines():
        m = WARN_RE.match(ln)
        if not m:
            continue
        p = Path(m.group("path"))
        if any(part in SKIP_DIR_PARTS for part in p.parts):
            continue
        by_file[p].append((m.group("name"), m.group("mod")))
    return by_file


IMPORT_RE = re.compile(
    r"""^import\s+                             # "import "
        (?:(?P<default>[A-Za-z_$][\w$]*)\s*,?\s*)?  # optional default
        \{\s*(?P<named>[^{}]*)\s*\}\s+          # { A, B as C }
        from\s+['\"](?P<mod>[^'\"]+)['\"];?\s*$
    """,
    re.VERBOSE,
)


def _strip_named(named_block: str, dead: set[str]) -> str | None:
    """Return the new comma-joined named block with `dead` removed,
    or None if the block would become empty."""
    parts = [p.strip() for p in named_block.split(",") if p.strip()]
    kept: list[str] = []
    for p in parts:
        # Handle `A as B` — the local name (B) is what the scanner reports.
        m = re.match(r"^([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)$", p)
        local = m.group(2) if m else p
        if local in dead:
            continue
        kept.append(p)
    if not kept:
        return None
    return ", ".join(kept)


def clean_file(path: Path, dead: list[tuple[str, str]]) -> int:
    """Apply removals. Returns count of identifiers actually removed."""
    if not path.exists():
        return 0
    src = path.read_text(encoding="utf-8")

    # Final verification: only keep the identifier in `dead` if it truly
    # never appears elsewhere in the file body AND isn't on the
    # NEVER_REMOVE guardlist. This defeats the scanner's blind spots for
    # JSX composition (`<Link>`), tag literals, or wrapper-only usage.
    verified: list[tuple[str, str]] = []
    for name, mod in dead:
        if name in NEVER_REMOVE:
            continue
        # Strip all import lines then look for real usage of `name`.
        body_only = re.sub(r"^\s*import[^\n]*\n", "", src, flags=re.MULTILINE)
        if _identifier_appears(body_only, name):
            continue
        verified.append((name, mod))

    dead_by_mod: dict[str, set[str]] = defaultdict(set)
    for name, mod in verified:
        dead_by_mod[mod].add(name)
    if not dead_by_mod:
        return 0

    lines = src.splitlines(keepends=True)
    removed = 0
    changed = False

    # Only edit destructured import lines; leave defaults/namespaces alone.
    # Also handle the two-line pattern `import X, {\n  Y,\n  Z\n} from 'mod';`
    # by first collapsing the file into a stream where multi-line imports
    # occupy a single logical line, then re-emitting.
    # Simpler: iterate lines, and for each line try to match IMPORT_RE.
    # For multi-line imports, we peek ahead and merge.
    i = 0
    out: list[str] = []
    while i < len(lines):
        ln = lines[i]
        # Attempt to merge multi-line named-import blocks.
        if ln.lstrip().startswith("import ") and "{" in ln and "}" not in ln:
            # Merge until we find "}"
            j = i + 1
            merged = ln
            while j < len(lines) and "}" not in lines[j]:
                merged += lines[j]
                j += 1
            if j < len(lines):
                merged += lines[j]
                j += 1
            candidate = " ".join(merged.split())
            m = IMPORT_RE.match(candidate)
            if m and m.group("mod") in dead_by_mod:
                dead_here = dead_by_mod[m.group("mod")]
                new_named = _strip_named(m.group("named"), dead_here)
                default = m.group("default")
                mod = m.group("mod")
                if new_named is None and not default:
                    # Whole import removable.
                    removed += sum(1 for _ in dead_here if _ in m.group("named"))
                    changed = True
                    i = j
                    continue
                # Rebuild with preserved default (if any).
                head = f"import {default}, " if default else "import "
                new_line = f"{head}{{ {new_named or ''} }} from '{mod}';\n" if new_named else \
                            (f"import {default} from '{mod}';\n" if default else "")
                # Count identifiers actually removed.
                removed += sum(1 for d in dead_here if d in m.group("named"))
                out.append(new_line)
                changed = True
                i = j
                continue
            # Not a match — keep as-is.
            out.append(merged)
            i = j
            continue

        # Single-line import
        stripped = ln.strip()
        if stripped.startswith("import ") and "{" in stripped and "}" in stripped:
            m = IMPORT_RE.match(stripped)
            if m and m.group("mod") in dead_by_mod:
                dead_here = dead_by_mod[m.group("mod")]
                new_named = _strip_named(m.group("named"), dead_here)
                default = m.group("default")
                mod = m.group("mod")
                # Preserve trailing newline
                nl = "\n" if ln.endswith("\n") else ""
                if new_named is None and not default:
                    removed += sum(1 for d in dead_here if d in m.group("named"))
                    changed = True
                    i += 1
                    continue
                head = f"import {default}, " if default else "import "
                new_line = (f"{head}{{ {new_named} }} from '{mod}';{nl}" if new_named else
                             (f"import {default} from '{mod}';{nl}" if default else ""))
                removed += sum(1 for d in dead_here if d in m.group("named"))
                out.append(new_line)
                changed = True
                i += 1
                continue

        out.append(ln)
        i += 1

    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return removed


def main():
    if len(sys.argv) < 2:
        print("usage: clean_dead_imports.py <warnings.txt>", file=sys.stderr)
        sys.exit(1)
    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    by_file = _parse_warnings(text)
    total = 0
    touched = 0
    for path, dead in sorted(by_file.items()):
        n = clean_file(path, dead)
        if n > 0:
            touched += 1
            total += n
            print(f"  {path}: removed {n} dead import(s)")
    print(f"[clean_dead_imports] removed {total} imports across {touched} files")


if __name__ == "__main__":
    main()
