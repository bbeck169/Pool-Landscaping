"""MTH-A · Feb-2026 — Fake Motor collection for isolated pytests.

Lightweight in-memory Motor stand-in reused across every MTH-A
test file.  Deliberately *not* placed in ``conftest.py`` — the
scope is narrow and adding a fixture to conftest would risk name
collisions with the rest of the suite.  Every MTH-A test file
imports this helper explicitly.

Supports the operations the ``services.tenant_ai_rules`` module
actually uses:

  * ``find_one(filter, projection=None)``
  * ``find(filter, projection=None)`` + ``.sort(...).to_list(N).limit(N)``
  * ``insert_one(doc)``
  * ``update_one(filter, update, upsert=False)``
  * ``update_many(filter, update)``  (unused today but future-proof)
  * ``delete_many(filter)``

Not intended as a full-motor stub — the moment a test needs
something more exotic, add it here rather than diverging.
"""
from __future__ import annotations

import asyncio
import copy
import re
from typing import Any, Dict, List, Optional


def _match(doc: Dict[str, Any], predicate: Dict[str, Any]) -> bool:
    """Very small mongo-filter evaluator — enough for MTH-A."""
    for k, v in predicate.items():
        if isinstance(v, dict) and set(v.keys()) & {"$in", "$gte",
                                                     "$lte", "$gt",
                                                     "$lt", "$regex"}:
            cur = doc.get(k)
            if "$in" in v:
                if cur not in v["$in"]:
                    return False
            if "$gte" in v and (cur is None or cur < v["$gte"]):
                return False
            if "$lte" in v and (cur is None or cur > v["$lte"]):
                return False
            if "$gt" in v and (cur is None or cur <= v["$gt"]):
                return False
            if "$lt" in v and (cur is None or cur >= v["$lt"]):
                return False
            if "$regex" in v:
                if not re.search(v["$regex"], str(cur or "")):
                    return False
            continue
        if doc.get(k) != v:
            return False
    return True


def _project(doc: Dict[str, Any],
             projection: Optional[Dict[str, int]]) -> Dict[str, Any]:
    if not projection:
        return dict(doc)
    include_mode = any(v == 1 for k, v in projection.items()
                       if k != "_id")
    exclude_mode = any(v == 0 for k, v in projection.items()
                       if k != "_id")
    if include_mode:
        out = {k: doc[k] for k in projection
               if k != "_id" and projection[k] == 1 and k in doc}
    elif exclude_mode:
        out = {k: v for k, v in doc.items()
               if projection.get(k) != 0}
    else:
        out = dict(doc)
    return out


class _Cursor:
    def __init__(self, docs: List[Dict[str, Any]]):
        self._docs = docs

    def sort(self, key: str, direction: int = 1) -> "_Cursor":
        self._docs.sort(key=lambda d: d.get(key),
                         reverse=(direction == -1))
        return self

    def limit(self, n: int) -> "_Cursor":
        self._docs = self._docs[:max(0, int(n))]
        return self

    async def to_list(self, n: int) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._docs[:max(0, int(n))])


class _Coll:
    def __init__(self, name: str):
        self.name = name
        self.rows: List[Dict[str, Any]] = []

    async def find_one(self, predicate: Dict[str, Any],
                        projection: Optional[Dict[str, int]] = None,
                        **_kw) -> Optional[Dict[str, Any]]:
        for r in self.rows:
            if _match(r, predicate):
                return _project(copy.deepcopy(r), projection)
        return None

    def find(self, predicate: Dict[str, Any],
             projection: Optional[Dict[str, int]] = None,
             **_kw) -> "_Cursor":
        docs = [_project(copy.deepcopy(r), projection)
                for r in self.rows if _match(r, predicate)]
        return _Cursor(docs)

    async def insert_one(self, doc: Dict[str, Any]) -> Any:
        self.rows.append(copy.deepcopy(doc))
        return type("_IR", (), {"inserted_id": doc.get("id")})()

    async def update_one(self, predicate: Dict[str, Any],
                          update: Dict[str, Any],
                          upsert: bool = False) -> Any:
        matched = 0
        modified = 0
        for r in self.rows:
            if _match(r, predicate):
                matched += 1
                if "$set" in update:
                    for k, v in update["$set"].items():
                        r[k] = copy.deepcopy(v)
                if "$unset" in update:
                    for k in update["$unset"]:
                        r.pop(k, None)
                if "$setOnInsert" in update:
                    pass                                          # existing → skip
                modified += 1
                break
        if matched == 0 and upsert:
            new_row = {}
            for k, v in predicate.items():
                if isinstance(v, dict):
                    continue
                new_row[k] = v
            if "$set" in update:
                for k, v in update["$set"].items():
                    new_row[k] = copy.deepcopy(v)
            if "$setOnInsert" in update:
                for k, v in update["$setOnInsert"].items():
                    new_row.setdefault(k, copy.deepcopy(v))
            self.rows.append(new_row)
            matched = 1
        return type("_UR", (), {"matched_count": matched,
                                  "modified_count": modified})()

    async def update_many(self, predicate: Dict[str, Any],
                           update: Dict[str, Any]) -> Any:
        n = 0
        for r in self.rows:
            if _match(r, predicate):
                if "$set" in update:
                    for k, v in update["$set"].items():
                        r[k] = copy.deepcopy(v)
                n += 1
        return type("_UR", (), {"matched_count": n,
                                  "modified_count": n})()

    async def delete_many(self, predicate: Dict[str, Any]) -> Any:
        before = len(self.rows)
        self.rows = [r for r in self.rows if not _match(r, predicate)]
        return type("_DR", (),
                     {"deleted_count": before - len(self.rows)})()

    async def create_indexes(self, models: List[Any]) -> None:
        # No-op — index shape is asserted separately in the
        # ``test_tenant_ai_rules_schema`` suite by inspecting the
        # ``ensure_tenant_ai_rules_indexes`` invocations.
        return None


class FakeDB:
    """One collection per attribute — matches Motor's shape."""
    def __init__(self):
        self.tenant_ai_rules = _Coll("tenant_ai_rules")
        self.tenant_ai_rules_revisions = _Coll(
            "tenant_ai_rules_revisions",
        )
        self.platform_ai_rule_defaults = _Coll(
            "platform_ai_rule_defaults",
        )

    def reset(self) -> None:
        self.tenant_ai_rules.rows.clear()
        self.tenant_ai_rules_revisions.rows.clear()
        self.platform_ai_rule_defaults.rows.clear()


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)
