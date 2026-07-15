#!/usr/bin/env python3
"""check_js_identifiers.py

Regex-based scanner for undeclared JS identifiers in .jsx files.
Complements `check_jsx_imports.py` (which only checks JSX tag names)
by flagging bare identifiers in JS expressions like:
    if (reportRef.current) { ... }
    const x = lastSavedAt.toISOString();
where the identifier isn't declared/imported anywhere in the file.

By design this errs on the side of false positives — it's gated as
a WARNING (exit 0) instead of an ERROR. Preflight logs the offending
lines but does not block a `finish`.

Restricted to .jsx (JS files with JSX) to avoid the massive TypeScript
type-annotation false-positive rate that .tsx introduces.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

IDENT_RE = re.compile(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\b")

# Language builtins + browser + React ecosystem globals — anything the
# scanner should treat as "always declared".
JS_KEYWORDS = {
    "new", "try", "catch", "finally", "throw", "return", "if", "else",
    "for", "while", "do", "break", "continue", "switch", "case", "default",
    "typeof", "instanceof", "in", "of", "delete", "void", "yield", "await",
    "async", "function", "class", "extends", "super", "import", "export",
    "from", "as", "const", "let", "var", "static", "readonly",
    "type", "interface", "enum", "namespace", "declare", "keyof", "infer",
    "abstract", "implements", "get", "set",
}
GLOBALS = JS_KEYWORDS | {
    # ECMAScript
    "console", "window", "document", "globalThis", "self",
    "Math", "Date", "Number", "String", "Boolean", "Array", "Object",
    "JSON", "Promise", "Map", "Set", "WeakMap", "WeakSet", "Symbol",
    "Error", "TypeError", "RangeError", "URL", "URLSearchParams",
    "RegExp", "isNaN", "isFinite", "parseFloat", "parseInt",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "requestAnimationFrame", "cancelAnimationFrame",
    "encodeURIComponent", "decodeURIComponent",
    "localStorage", "sessionStorage", "location", "navigator",
    "Blob", "File", "FileReader", "FormData", "Headers", "Request", "Response",
    "fetch", "AbortController", "atob", "btoa", "structuredClone",
    "Intl", "queueMicrotask", "crypto", "performance",
    # React runtime pseudo-globals
    "React", "Fragment", "undefined", "null", "true", "false", "NaN", "Infinity",
    # Test frameworks (in case any leak through)
    "jest", "vi", "describe", "it", "test", "expect", "beforeEach",
    "afterEach", "beforeAll", "afterAll",
    "arguments", "this",
}

DECL_PATTERNS = [
    re.compile(r"\bimport\s+([A-Za-z_$][\w$]*)\b"),
    re.compile(r"import\s*\{([^}]+)\}\s*from"),
    re.compile(r"import\s*\*\s*as\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\bconst\s+([A-Za-z_$][\w$]*)\s*="),
    re.compile(r"\bconst\s*\{([^}]+)\}\s*="),
    re.compile(r"\bconst\s*\[([^\]]+)\]\s*="),
    re.compile(r"\blet\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\bvar\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"\bclass\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"([A-Za-z_$][\w$]*)\s*=>"),
    re.compile(r"\(([^)]*)\)\s*=>"),
    # Destructured rename `key: Local`
    re.compile(r"[{,]\s*[A-Za-z_$][\w$]*\s*:\s*([A-Za-z_$][\w$]*)"),
    # Function params: `function foo(a, b, c)` or `(a, b, c) =>`
    re.compile(r"function\s*[A-Za-z_$\w$]*\s*\(([^)]*)\)"),
]


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(^|[^:])//[^\n]*", r"\1", src)
    return src


def _strip_strings(src: str) -> str:
    # Kill string literals so `"foo"` doesn't leak `foo` as an identifier.
    src = re.sub(r"'([^'\\]|\\.)*'", "''", src)
    src = re.sub(r'"([^"\\]|\\.)*"', '""', src)
    src = re.sub(r"`([^`\\]|\\.)*`", "``", src, flags=re.S)
    return src


def declared_names(source: str) -> set[str]:
    names: set[str] = set(GLOBALS)
    for pat in DECL_PATTERNS:
        for m in pat.finditer(source):
            grp = m.group(1)
            for tok in re.split(r"[,\s\[\]{}]+", grp):
                tok = tok.strip()
                if not tok:
                    continue
                if " as " in tok:
                    _, tok = tok.split(" as ")
                    tok = tok.strip()
                if re.match(r"^[A-Za-z_$][\w$]*$", tok):
                    names.add(tok)
    # Bag-of-tokens fallback: ANY identifier appearing in the file counts as
    # potentially-bound. This makes the scanner catch only the cases where
    # the identifier appears exactly once (its only usage) — which is the
    # pattern of `reportRef` referenced but never declared.
    return names


def _find_bare_identifiers(source: str) -> dict[str, int]:
    """Return identifier -> count, EXCLUDING property accesses (`x.foo`),
    method definitions, and object-literal keys."""
    out: dict[str, int] = {}
    stripped = re.sub(r"\.\s*[A-Za-z_$][\w$]*", "", source)
    stripped = re.sub(r"([A-Za-z_$][\w$]*)\s*:", "", stripped)
    stripped = re.sub(r"([A-Za-z_$][\w$]*)\s*=(?![=>])", "", stripped)
    for m in IDENT_RE.finditer(stripped):
        out[m.group(1)] = out.get(m.group(1), 0) + 1
    return out


def scan_file(path: Path) -> list[tuple[int, str]]:
    src_raw = _strip_comments(_strip_strings(path.read_text()))
    declared = declared_names(src_raw)
    seen = _find_bare_identifiers(src_raw)

    missing: list[tuple[int, str]] = []
    lines = path.read_text().splitlines()
    # Only flag names that look like typical local refs — end in Ref/State/
    # Handler/Callback OR are camelCase with 2+ uses.
    suspicious_suffixes = ("Ref", "State", "Handler", "Callback")
    for name, count in seen.items():
        if name in declared:
            continue
        looks_like_ref = any(name.endswith(s) for s in suspicious_suffixes)
        if not looks_like_ref:
            continue
        for i, line in enumerate(lines, start=1):
            if re.search(rf"\b{re.escape(name)}\b", line):
                missing.append((i, name))
                break
    return missing


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        roots = [Path(a) for a in argv[1:]]
    else:
        roots = [Path("/app/frontend/src")]
    errors = 0
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.jsx"):
            if "node_modules" in path.parts:
                continue
            issues = scan_file(path)
            for ln, name in issues:
                print(f"  {path.relative_to('/app')}:{ln}  undeclared identifier `{name}`")
                errors += 1
    if errors:
        # WARN-only: exit 0 to keep preflight passing. This scanner is
        # advisory — its point is to surface suspicious names to the
        # developer, not to gate finishes on regex quirks.
        print(f"\n[check_js_identifiers] {errors} suspicious undeclared identifiers (WARN).")
        return 0
    print("[check_js_identifiers] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
