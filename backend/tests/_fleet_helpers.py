"""FLEET-A · Shared in-memory Motor stub for the fleet test suite.

Small, isolated copy of the ``_DB`` stub used by
``test_hard_delete_hd_a.py`` — self-contained so a single failing
HD test doesn't fail the fleet suite (and vice versa).
"""
from __future__ import annotations

import asyncio
import copy
from typing import Any, Dict, List


def _match(row: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if k == "$or":
            if not any(_match(row, sub) for sub in v):
                return False
            continue
        if k == "$and":
            if not all(_match(row, sub) for sub in v):
                return False
            continue
        row_val = row.get(k)
        if isinstance(v, dict):
            for op, opval in v.items():
                if op == "$exists":
                    if opval != (row_val is not None):
                        return False
                elif op == "$in":
                    if row_val not in opval:
                        return False
                elif op == "$nin":
                    if row_val in opval:
                        return False
                elif op == "$ne":
                    if row_val == opval:
                        return False
                elif op == "$lt":
                    if row_val is None or row_val >= opval:
                        return False
                elif op == "$gt":
                    if row_val is None or row_val <= opval:
                        return False
                elif op == "$gte":
                    if row_val is None or row_val < opval:
                        return False
                elif op == "$lte":
                    if row_val is None or row_val > opval:
                        return False
                else:
                    return False
            continue
        if row_val != v:
            return False
    return True


def _apply_update(row, update):
    if "$set" in update:
        for k, val in update["$set"].items():
            row[k] = val
    if "$unset" in update:
        for k in update["$unset"]:
            row.pop(k, None)


class _Cursor:
    def __init__(self, rows: List[Dict[str, Any]]):
        self._rows = [copy.deepcopy(r) for r in rows]

    def sort(self, key_or_list, direction=None):
        if isinstance(key_or_list, list):
            key_pairs = key_or_list
        else:
            key_pairs = [(key_or_list, direction if direction is not None else 1)]
        for key, dir_ in reversed(key_pairs):
            self._rows.sort(key=lambda r: (r.get(key) or ""),
                             reverse=(dir_ == -1))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    async def to_list(self, _n=None):
        return list(self._rows)

    def __aiter__(self):
        self._iter = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _Coll:
    def __init__(self, rows=None):
        self.rows: List[Dict[str, Any]] = [copy.deepcopy(r) for r in (rows or [])]

    async def find_one(self, query, projection=None, sort=None):
        matches = [r for r in self.rows if _match(r, query)]
        if sort:
            for key, dir_ in reversed(sort):
                matches.sort(key=lambda r: (r.get(key) or ""),
                             reverse=(dir_ == -1))
        return copy.deepcopy(matches[0]) if matches else None

    def find(self, query=None, projection=None):
        q = query or {}
        return _Cursor([r for r in self.rows if _match(r, q)])

    async def count_documents(self, query):
        return sum(1 for r in self.rows if _match(r, query))

    async def insert_one(self, doc):
        self.rows.append(copy.deepcopy(doc))
        return type("R", (), {"inserted_id": doc.get("id")})()

    async def update_one(self, query, update):
        for row in self.rows:
            if _match(row, query):
                _apply_update(row, update)
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()

    async def update_many(self, query, update):
        c = 0
        for row in self.rows:
            if _match(row, query):
                _apply_update(row, update)
                c += 1
        return type("R", (), {"modified_count": c})()

    async def delete_one(self, query):
        for row in list(self.rows):
            if _match(row, query):
                self.rows.remove(row)
                return type("R", (), {"deleted_count": 1})()
        return type("R", (), {"deleted_count": 0})()

    async def delete_many(self, query):
        n = 0
        for row in list(self.rows):
            if _match(row, query):
                self.rows.remove(row)
                n += 1
        return type("R", (), {"deleted_count": n})()

    def aggregate(self, _pipeline):
        return _Cursor([])


class _DB:
    def __init__(self):
        self._colls: Dict[str, _Coll] = {}

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = _Coll()
        return self._colls[name]

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self[name]


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)
