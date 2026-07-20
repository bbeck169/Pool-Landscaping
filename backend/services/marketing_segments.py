"""Marketing · Phase M1 — Segment rule DSL compiler.

Converts a JSON rule tree into a MongoDB filter for the ``subscribers``
collection. Supports simple leaf rules and nested groups combined with
``and`` / ``or``.

Rule tree schema
----------------
Leaf::

    {"field": "<field-path>", "op": "<op>", "value": <any>}

Group::

    {"combinator": "and" | "or", "rules": [<leaf or group>, ...]}

Supported ops:
    eq, ne, contains, not_contains, gt, gte, lt, lte, in, not_in,
    exists, before, after

Supported field paths on subscriber docs:
    email, phone, first_name, last_name, status, source,
    tags, customer_id, created_at, confirmed_at, unsubscribed_at,
    attributes.<any-key>

Design notes:
    * ``contains`` on scalar fields → case-insensitive regex.
    * ``contains`` on the ``tags`` array field → membership check.
    * ``before`` / ``after`` compare ISO date strings lexicographically
      (matches how the rest of the codebase stores timestamps).
    * ``exists`` accepts value=True/False and compiles to ``$exists``.
    * Unknown ops or missing fields raise ``ValueError`` — surfaced back
      to the caller as HTTP 422 by the router.
"""
from __future__ import annotations

from typing import Any, Dict, List


ALLOWED_OPS = {
    "eq", "ne", "contains", "not_contains", "gt", "gte", "lt", "lte",
    "in", "not_in", "exists", "before", "after",
}

# Fields with an "in" / array semantic on the subscriber doc.
_ARRAY_FIELDS = {"tags"}

# Fields that are allowed at the top level. Attribute paths under
# ``attributes.<key>`` are always allowed.
_ALLOWED_TOP_FIELDS = {
    "email", "phone", "first_name", "last_name", "status", "source",
    "tags", "customer_id", "created_at", "confirmed_at",
    "unsubscribed_at",
    # Feb-2026 Customer Detail Additions — VIP flag mirrored from the
    # customer doc into the subscriber row so the auto-seeded "VIP
    # Customers" segment resolves to the right audience.
    "is_vip",
}


def _validate_field(field: str) -> None:
    if not field or not isinstance(field, str):
        raise ValueError("field must be a non-empty string")
    if field.startswith("attributes."):
        # Accept anything under attributes.
        return
    if field not in _ALLOWED_TOP_FIELDS:
        raise ValueError(
            f"unsupported field {field!r}. Allowed: "
            f"{sorted(_ALLOWED_TOP_FIELDS)} or attributes.<key>"
        )


def _compile_leaf(rule: Dict[str, Any]) -> Dict[str, Any]:
    field = rule.get("field")
    op = rule.get("op")
    value = rule.get("value")
    _validate_field(field)
    if op not in ALLOWED_OPS:
        raise ValueError(f"unsupported op {op!r}. Allowed: {sorted(ALLOWED_OPS)}")

    if op == "eq":
        return {field: value}
    if op == "ne":
        return {field: {"$ne": value}}
    if op == "contains":
        if field in _ARRAY_FIELDS:
            return {field: value}
        if value is None:
            raise ValueError("contains requires a non-null value")
        return {field: {"$regex": str(value), "$options": "i"}}
    if op == "not_contains":
        if field in _ARRAY_FIELDS:
            return {field: {"$ne": value}}
        if value is None:
            raise ValueError("not_contains requires a non-null value")
        return {field: {"$not": {"$regex": str(value), "$options": "i"}}}
    if op == "gt":
        return {field: {"$gt": value}}
    if op == "gte":
        return {field: {"$gte": value}}
    if op == "lt":
        return {field: {"$lt": value}}
    if op == "lte":
        return {field: {"$lte": value}}
    if op == "in":
        if not isinstance(value, list):
            raise ValueError("in requires a list value")
        return {field: {"$in": value}}
    if op == "not_in":
        if not isinstance(value, list):
            raise ValueError("not_in requires a list value")
        return {field: {"$nin": value}}
    if op == "exists":
        return {field: {"$exists": bool(value)}}
    if op == "before":
        # ISO-string lexicographic compare.
        return {field: {"$lt": str(value)}}
    if op == "after":
        return {field: {"$gt": str(value)}}
    # Defensive; should never reach here after the op-allowlist check.
    raise ValueError(f"unhandled op {op!r}")


def compile_rules(rule_tree: Dict[str, Any]) -> Dict[str, Any]:
    """Compile a rule tree to a Mongo filter fragment.

    Returns an empty dict (``{}``) if the tree is empty — that matches
    "everyone".
    """
    if not rule_tree:
        return {}
    # Leaf?
    if "field" in rule_tree and "op" in rule_tree:
        return _compile_leaf(rule_tree)
    combinator = (rule_tree.get("combinator") or "and").lower()
    if combinator not in ("and", "or"):
        raise ValueError(f"combinator must be 'and' or 'or', got {combinator!r}")
    rules = rule_tree.get("rules") or []
    if not isinstance(rules, list):
        raise ValueError("rules must be a list")
    if not rules:
        return {}
    compiled: List[Dict[str, Any]] = [compile_rules(r) for r in rules if r]
    compiled = [c for c in compiled if c]
    if not compiled:
        return {}
    if len(compiled) == 1:
        return compiled[0]
    mongo_op = "$and" if combinator == "and" else "$or"
    return {mongo_op: compiled}


def compile_to_filter(tenant_id: str, rule_tree: Dict[str, Any]) -> Dict[str, Any]:
    """Compile + tenant-scope. Always intersects with ``tenant_id``."""
    inner = compile_rules(rule_tree or {})
    if not inner:
        return {"tenant_id": tenant_id}
    if "$and" in inner:
        return {"$and": [{"tenant_id": tenant_id}, *inner["$and"]]}
    return {"$and": [{"tenant_id": tenant_id}, inner]}
