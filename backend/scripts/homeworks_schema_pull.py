#!/usr/bin/env python3
"""Feb-2026 · Homeworks GraphQL introspection pull.

One-shot. Writes:

  * ``backend/services/homeworks_mcp/schema.json``    — raw introspection.
  * ``backend/services/homeworks_mcp/schema.graphql`` — SDL rendering.

The SDL rendering is deliberately minimal (no imports of
``graphql-core`` etc — the spec forbids adding a codegen dep at Phase
1a). It's enough to eyeball the type surface until Phase 1b picks it up.

Usage::

    cd /app/backend && python3 -m scripts.homeworks_schema_pull
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import httpx

GRAPHQL_ENDPOINT = "https://api.home.works/graphql"

# Standard GraphQL introspection query (v16 spec, minus deprecated
# ``onOperation`` / ``onFragment`` / ``onField`` fields on Directives).
INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types { ...FullType }
    directives {
      name
      description
      locations
      args { ...InputValue }
    }
  }
}
fragment FullType on __Type {
  kind
  name
  description
  fields(includeDeprecated: true) {
    name
    description
    args { ...InputValue }
    type { ...TypeRef }
    isDeprecated
    deprecationReason
  }
  inputFields { ...InputValue }
  interfaces { ...TypeRef }
  enumValues(includeDeprecated: true) {
    name
    description
    isDeprecated
    deprecationReason
  }
  possibleTypes { ...TypeRef }
}
fragment InputValue on __InputValue {
  name
  description
  type { ...TypeRef }
  defaultValue
}
fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType { kind name }
            }
          }
        }
      }
    }
  }
}
""".strip()


_OUT_DIR = Path("/app/backend/services/homeworks_mcp")


def fetch() -> Dict[str, Any]:
    print(f"→ POST {GRAPHQL_ENDPOINT} (introspection)")
    r = httpx.post(
        GRAPHQL_ENDPOINT,
        json={"query": INTROSPECTION_QUERY},
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30.0,
    )
    if r.status_code >= 400:
        print(f"✗ HTTP {r.status_code}\n{r.text[:600]}")
        sys.exit(2)
    payload = r.json()
    if payload.get("errors"):
        print("✗ GraphQL errors:")
        print(json.dumps(payload["errors"], indent=2)[:1200])
        sys.exit(3)
    return payload["data"]["__schema"]


# ── SDL rendering (dependency-free, "good enough for eyeballing") ────
def _type_ref(t: Dict[str, Any]) -> str:
    kind = t.get("kind")
    name = t.get("name")
    of = t.get("ofType")
    if kind == "NON_NULL":
        return f"{_type_ref(of)}!"
    if kind == "LIST":
        return f"[{_type_ref(of)}]"
    return name or "Unknown"


def _args(args: List[Dict[str, Any]]) -> str:
    if not args:
        return ""
    parts = []
    for a in args:
        s = f"{a['name']}: {_type_ref(a['type'])}"
        if a.get("defaultValue") is not None:
            s += f" = {a['defaultValue']}"
        parts.append(s)
    return "(" + ", ".join(parts) + ")"


def _fmt_desc(desc: str, indent: str = "") -> str:
    if not desc:
        return ""
    lines = desc.split("\n")
    return "\n".join(f"{indent}\"{line}\"" for line in lines[:1]) + "\n"


def to_sdl(schema: Dict[str, Any]) -> str:
    out: List[str] = []
    root = schema.get("queryType", {}).get("name")
    mut = (schema.get("mutationType") or {}).get("name")
    sub = (schema.get("subscriptionType") or {}).get("name")
    out.append("schema {")
    out.append(f"  query: {root}")
    if mut:
        out.append(f"  mutation: {mut}")
    if sub:
        out.append(f"  subscription: {sub}")
    out.append("}")
    out.append("")
    for t in sorted(schema.get("types") or [], key=lambda x: x.get("name") or ""):
        name = t.get("name") or ""
        kind = t.get("kind")
        if not name or name.startswith("__"):
            continue
        if t.get("description"):
            out.append(f"\"{t['description'].splitlines()[0]}\"")
        if kind == "SCALAR":
            out.append(f"scalar {name}")
        elif kind == "ENUM":
            out.append(f"enum {name} {{")
            for v in t.get("enumValues") or []:
                out.append(f"  {v['name']}")
            out.append("}")
        elif kind == "OBJECT" or kind == "INTERFACE":
            interfaces = t.get("interfaces") or []
            impl = ""
            if interfaces:
                impl = " implements " + " & ".join(
                    i["name"] for i in interfaces
                )
            keyword = "type" if kind == "OBJECT" else "interface"
            out.append(f"{keyword} {name}{impl} {{")
            for f in t.get("fields") or []:
                out.append(
                    f"  {f['name']}{_args(f.get('args') or [])}: "
                    f"{_type_ref(f['type'])}"
                )
            out.append("}")
        elif kind == "INPUT_OBJECT":
            out.append(f"input {name} {{")
            for f in t.get("inputFields") or []:
                out.append(f"  {f['name']}: {_type_ref(f['type'])}")
            out.append("}")
        elif kind == "UNION":
            members = " | ".join(
                (m.get("name") or "?") for m in (t.get("possibleTypes") or [])
            )
            out.append(f"union {name} = {members}")
        else:
            out.append(f"# unhandled kind={kind} name={name}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    schema = fetch()
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _OUT_DIR / "schema.json"
    sdl_path = _OUT_DIR / "schema.graphql"

    json_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    sdl_path.write_text(to_sdl(schema), encoding="utf-8")

    types = schema.get("types") or []
    types_named = [t for t in types if t.get("name") and not t["name"].startswith("__")]

    q_name = (schema.get("queryType") or {}).get("name")
    m_name = (schema.get("mutationType") or {}).get("name")
    s_name = (schema.get("subscriptionType") or {}).get("name")
    print(f"✓ schema.json  {json_path.stat().st_size:>8} bytes")
    print(f"✓ schema.graphql {sdl_path.stat().st_size:>8} bytes")
    print(f"  root Query type:        {q_name}")
    print(f"  root Mutation type:     {m_name}")
    print(f"  root Subscription type: {s_name}")
    print(f"  total types (excluding introspection meta): {len(types_named)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
