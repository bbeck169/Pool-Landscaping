"""Feb-2026 · pytest for ``backend/scripts/deactivate_ghost_employees.py``.

Operator spec cases:
  (1) Dry-run finds correct match set.
  (2) Multi-match name → STOP + exit code non-zero.
  (3) ``--apply`` without TENANT_ID → refuse.
  (4) Backup file written before DB mutation.

Pattern: run ``main(argv, stdin, coll_override)`` with an isolated
pymongo collection fixture + patched env — avoids live-DB coupling
and lets us test the typed-yes confirmation path deterministically.
"""
from __future__ import annotations

import io
import json
import os
import uuid
from pathlib import Path
from typing import Dict, List
from unittest.mock import patch

import pytest
from pymongo import MongoClient

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]


_PFX = "TESTdgh_"
_TENANT = f"{_PFX}tenant"


_client = MongoClient(MONGO_URL)
_users = _client[DB_NAME].users


def _wipe() -> None:
    _users.delete_many({"id": {"$regex": f"^{_PFX}"}})


@pytest.fixture(autouse=True)
def _clean():
    _wipe()
    yield
    _wipe()


def _seed_user(
    *, name: str, tenant_id: str = _TENANT, role: str = "technician",
) -> str:
    uid = f"{_PFX}usr_{uuid.uuid4().hex[:10]}"
    _users.insert_one({
        "id": uid,
        "tenant_id": tenant_id,
        "name": name,
        "role": role,
        "active": True,
    })
    return uid


def _run_main(
    argv: List[str],
    *,
    env: Dict[str, str],
    stdin_text: str = "",
    log_dir: Path,
) -> tuple[int, str]:
    """Invoke the script's ``main`` with env overrides + captured
    stdout."""
    from scripts.deactivate_ghost_employees import main
    out = io.StringIO()
    stdin = io.StringIO(stdin_text)
    full_argv = list(argv) + ["--log-dir", str(log_dir)]
    with patch.dict(os.environ, env, clear=False):
        exit_code = main(
            argv=full_argv,
            stdin=stdin,
            stdout=out,
            coll_override=_users,
        )
    return exit_code, out.getvalue()


def _mandatory_env() -> Dict[str, str]:
    return {
        "MONGO_URI": MONGO_URL,
        "MONGO_DB_NAME": DB_NAME,
        "TENANT_ID": _TENANT,
    }


# ═══════════════════════════════════════════════════════════════════
# §1 · Operator case (1) — dry-run finds the correct match set
# ═══════════════════════════════════════════════════════════════════
def test_dry_run_finds_correct_matches(tmp_path):
    """3 seeded ghosts, 1 non-ghost, 1 name with no match. Dry-run
    should surface only the 3 ghosts in the matched set and must
    NOT mutate anything."""
    uid_a = _seed_user(name="Anthony Sotelo")
    uid_b = _seed_user(name="Brian Beckman")
    uid_c = _seed_user(name="Carlos Rivera")
    uid_safe = _seed_user(name="Safe Keeper")  # not in input list

    code, _text = _run_main(
        ["--names", "Anthony Sotelo,Brian Beckman,Carlos Rivera,Nobody Here"],
        env=_mandatory_env(),
        log_dir=tmp_path,
    )
    assert code == 0
    # DB unchanged — all active still.
    for uid in (uid_a, uid_b, uid_c, uid_safe):
        row = _users.find_one({"id": uid})
        assert row["active"] is True, (
            f"{uid} mutated on dry-run: {row}"
        )
    # No backup file on dry-run.
    bak = list(tmp_path.glob("ghost_employees_backup_*.json"))
    assert bak == [], f"backup written on dry-run: {bak}"


# ═══════════════════════════════════════════════════════════════════
# §2 · Operator case (2) — multi-match name hard-stops
# ═══════════════════════════════════════════════════════════════════
def test_multi_match_name_hard_stops_with_non_zero_exit(tmp_path):
    """Two users share the same case-insensitive name. The script
    MUST return a non-zero exit code and MUST NOT write anything
    even with --apply + a yes-reply piped in."""
    _seed_user(name="Luis Marquez")
    _seed_user(name="LUIS MARQUEZ")  # dup — same case-insensitive

    code, text = _run_main(
        ["--names", "Luis Marquez", "--apply"],
        env=_mandatory_env(),
        stdin_text="yes\n",
        log_dir=tmp_path,
    )
    assert code != 0, f"multi-match leaked through: text={text!r}"
    assert code == 3  # documented STOP code
    # No DB mutation (both still active).
    cnt_active = _users.count_documents({
        "tenant_id": _TENANT, "active": True,
        "name": {"$regex": "luis marquez", "$options": "i"},
    })
    assert cnt_active == 2, (
        f"multi-match deactivation leaked: active={cnt_active}"
    )


# ═══════════════════════════════════════════════════════════════════
# §3 · Operator case (3) — --apply without TENANT_ID refuses
# ═══════════════════════════════════════════════════════════════════
def test_apply_without_tenant_id_refuses(tmp_path):
    """Missing TENANT_ID on --apply is a HARD refuse — protects
    against cross-tenant data mutation. Exit code 2 per the
    script's env-guard protocol."""
    _seed_user(name="Steven Martinez")

    env = _mandatory_env()
    env.pop("TENANT_ID", None)
    # Explicitly scrub the parent env too — patch.dict only ADDS,
    # it doesn't remove, so set it to empty.
    env["TENANT_ID"] = ""

    code, text = _run_main(
        ["--names", "Steven Martinez", "--apply"],
        env=env,
        stdin_text="yes\n",
        log_dir=tmp_path,
    )
    assert code != 0
    assert code == 2
    assert "TENANT_ID" in text
    # No DB mutation.
    row = _users.find_one({"name": "Steven Martinez"})
    assert row["active"] is True


# ═══════════════════════════════════════════════════════════════════
# §4 · Operator case (4) — backup file written BEFORE DB mutation
# ═══════════════════════════════════════════════════════════════════
def test_apply_writes_backup_file_before_mutation(tmp_path):
    """Real --apply with 2 matched ghosts + typed 'yes' + explicit
    tenant. Assert:
      (a) backup JSON file exists in the log dir;
      (b) backup file contains full ``$doc`` for each target (with
          ``active: true`` — the PRE-mutation state);
      (c) DB rows are now ``active: false`` + carry provenance
          fields (``deactivated_at`` / ``deactivated_reason`` /
          ``deactivated_by``);
      (d) ``$doc`` ``name`` fields in the backup match the seeded
          ones — guards against partial-projection bugs where
          only ``id`` would be backed up.
    """
    uid_a = _seed_user(name="Miguel Munoz")
    uid_b = _seed_user(name="Remington Nieman")

    code, _text = _run_main(
        ["--names", "Miguel Munoz,Remington Nieman", "--apply"],
        env=_mandatory_env(),
        stdin_text="yes\n",
        log_dir=tmp_path,
    )
    assert code == 0

    # (a) backup present.
    baks = list(tmp_path.glob("ghost_employees_backup_*.json"))
    assert len(baks) == 1, f"expected 1 backup file, got {baks}"
    backup_path = baks[0]
    # Filename carries the tenant slug.
    assert _TENANT in backup_path.name

    # (b) + (d) pre-mutation snapshot content.
    snapshot = json.loads(backup_path.read_text())
    assert isinstance(snapshot, list)
    assert len(snapshot) == 2
    for row in snapshot:
        assert row["active"] is True, (
            f"backup carries post-mutation state: {row}"
        )
        assert row["tenant_id"] == _TENANT
        assert row["name"] in ("Miguel Munoz", "Remington Nieman"), (
            f"backup name field missing / wrong: {row}"
        )
        assert row["id"] in (uid_a, uid_b)

    # (c) DB rows mutated.
    for uid in (uid_a, uid_b):
        row = _users.find_one({"id": uid})
        assert row["active"] is False
        assert row["deactivated_reason"] == "ghost_timecard_cleanup"
        assert row["deactivated_by"] == "operator_script"
        assert "deactivated_at" in row


# ═══════════════════════════════════════════════════════════════════
# §5 · Confirmation guard — a non-yes reply aborts without writing
# ═══════════════════════════════════════════════════════════════════
def test_apply_without_typed_yes_aborts_without_writing(tmp_path):
    """Operator discipline rail — if the --apply confirmation
    reply is anything other than 'yes', the script must abort
    WITHOUT writing. Non-zero exit code so a script wrapper
    can detect the abort."""
    uid = _seed_user(name="Anthony Sotelo")

    code, _text = _run_main(
        ["--names", "Anthony Sotelo", "--apply"],
        env=_mandatory_env(),
        stdin_text="n\n",  # not 'yes'
        log_dir=tmp_path,
    )
    assert code == 4  # abort code
    # DB unchanged.
    row = _users.find_one({"id": uid})
    assert row["active"] is True
    # No backup on abort.
    bak = list(tmp_path.glob("ghost_employees_backup_*.json"))
    assert bak == []


# ═══════════════════════════════════════════════════════════════════
# §6 · --ids path — safest alternative to fuzzy name match
# ═══════════════════════════════════════════════════════════════════
def test_ids_path_deactivates_explicit_users(tmp_path):
    """Operator's suggested disambiguation path when names collide.
    --ids skips the name-matching entirely and targets by UUID."""
    _seed_user(name="Luis Marquez")
    _seed_user(name="LUIS MARQUEZ")
    uid_c = _seed_user(name="Carlos Rivera")

    code, _text = _run_main(
        ["--ids", uid_c, "--apply"],
        env=_mandatory_env(),
        stdin_text="yes\n",
        log_dir=tmp_path,
    )
    assert code == 0
    row = _users.find_one({"id": uid_c})
    assert row["active"] is False
    # The two Luis Marquez users are UNTOUCHED.
    luis_cnt = _users.count_documents({
        "tenant_id": _TENANT, "active": True,
        "name": {"$regex": "luis marquez", "$options": "i"},
    })
    assert luis_cnt == 2


# ═══════════════════════════════════════════════════════════════════
# §7 · --hard-delete guard — needs BOTH --apply AND the ack flag
# ═══════════════════════════════════════════════════════════════════
def test_hard_delete_requires_destructive_ack(tmp_path):
    """--hard-delete without --i-know-this-is-destructive must
    refuse (exit 2). Prevents accidental destructive runs."""
    _seed_user(name="Anthony Sotelo")

    code, text = _run_main(
        ["--names", "Anthony Sotelo", "--apply", "--hard-delete"],
        env=_mandatory_env(),
        stdin_text="yes\nyes\n",
        log_dir=tmp_path,
    )
    assert code == 2
    assert "destructive" in text.lower()
