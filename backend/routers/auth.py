# ruff: noqa: F403,F405
import os
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel
import jwt

from config import db, logger, EMERGENT_LLM_KEY, JWT_SECRET, JWT_ALGO
from utils import (now_iso, new_id, hash_password, verify_password, create_token,
                   get_current_user, require_admin, send_sms, notify_customer, auth_response)
from routers.tenants import _ensure_default_tenant
from models import LoginRequest, SignupRequest

router = APIRouter()

# --- Brute-force / account-lockout policy (SOC2/ISO 27001 technical control) ---
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# ── Feb-2026 · Task 4 · Option A account chooser ──────────────────
# TTL of the short-lived choice_token issued when a single email
# password-matches two or more non-deleted ``users`` records with
# divergent roles.  The user has 5 minutes to pick which account they
# want to sign in as before the token expires and they must re-verify
# their password.  Value is intentionally short — password auth
# already happened once so a strong TTL is not required, but keeping
# it small caps the blast radius on any leak.
CHOICE_TOKEN_TTL_MINUTES = 5
_WORKFORCE_ROLES = (
    "super_admin", "admin", "manager", "technician", "tech",
)


def _account_display(user: dict) -> str:
    """Human-friendly one-line label for the account chooser card.

    Examples:
      * ``Customer account · Jane Doe``
      * ``Staff · Aquaterra Pools (admin)``
    """
    role = (user.get("role") or "").lower()
    if role == "customer":
        # Prefer the customer's linked ``customers`` row name if we can
        # peek at it without a round-trip — the users row already
        # carries ``name`` in this codebase.
        return f"Customer account · {user.get('name') or user.get('email')}"
    label = "Staff"
    tenant_hint = user.get("tenant_name") or user.get("name") or ""
    role_hint = f" ({role})" if role else ""
    return f"{label} · {tenant_hint or user.get('email')}{role_hint}".strip()


async def _audit_multi_account_choice(*, event: str, email: str, ip: str,
                                       user_agent: str, tenant_id: Optional[str],
                                       user_ids: List[str],
                                       chosen_user_id: Optional[str] = None,
                                       chosen_role: Optional[str] = None) -> None:
    """Write a row to ``auth_multi_account_choices`` for every chooser
    branch event.  Never bubbles — audit failures must not block auth."""
    try:
        await db.auth_multi_account_choices.insert_one({
            "id": new_id(),
            "event": event,                    # "required" | "selected"
            "email": email,
            "ip_address": ip,
            "user_agent": user_agent[:400],    # cap to avoid runaway rows
            "tenant_id": tenant_id,
            "user_ids": list(user_ids),
            "chosen_user_id": chosen_user_id,
            "chosen_role": chosen_role,
            "created_at": now_iso(),
        })
    except Exception as exc:                    # noqa: BLE001
        logger.warning(f"[auth] auth_multi_account_choices insert failed: {exc}")


def _issue_choice_token(email: str, verified_user_ids: List[str]) -> str:
    """Mint the short-lived JWT the FE sends back to
    ``/auth/login/select-account``.

    Security notes:
      * ``type = "choice"`` — the token is USELESS as an access token.
        ``get_current_user`` doesn't require a ``type`` claim today,
        BUT this token intentionally omits ``sub`` so even a naïve
        drop-in as ``Authorization: Bearer`` would fail the
        ``db.users.find_one({id: None})`` lookup and return 401.
      * ``verified`` carries the exact user_ids the password already
        matched; the selector endpoint MUST reject any account_id
        outside this list — the client cannot escalate to accounts
        that failed password verification.
      * Signed with the same ``JWT_SECRET`` so ops don't need a new
        env var; separation of concerns is enforced by the payload
        shape, not by a distinct key.
    """
    payload = {
        "type": "choice",
        "email": email,
        "verified": list(verified_user_ids),
        "exp": datetime.now(timezone.utc)
                + timedelta(minutes=CHOICE_TOKEN_TTL_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _decode_choice_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Choice token expired. Please sign in again.",
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid choice token")
    if payload.get("type") != "choice":
        raise HTTPException(status_code=401, detail="Invalid choice token")
    return payload


def _client_ip(request: Request) -> str:
    """Feb-2026 · P16B — delegates to the shared ``services._shared.http``
    helper so the same IP-resolution semantics live in one place.
    Fallback preserved as ``"unknown"`` to match every existing audit
    row grep-able in prod logs."""
    from services._shared.http import client_ip as _shared_client_ip
    return _shared_client_ip(request, default="unknown")


async def _audit_auth(event: str, email: str, ip: str, status: str, details: str = ""):
    """Immutable-ish audit record of authentication events."""
    try:
        await db.audit_logs.insert_one({
            "id": new_id(), "event": event, "email": email, "ip_address": ip,
            "status": status, "details": details, "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"audit log write failed: {e}")


# ── Feb-2026 · Customer temp password + first-access tracking ─────
# When an admin provisions/rotates a customer's portal password
# (``routers.portal_admin._upsert_customer_user``), the ``users`` row
# is stamped ``must_change_password_on_next_login = True``. On the
# customer's NEXT successful password verification, ``/auth/login``
# forks into a ``password_reset_required`` response that mints a
# short-lived opaque token in ``password_reset_tokens`` (reusing the
# existing Task-O self-serve reset primitive verbatim — no parallel
# flow) and never issues an access token. The customer is redirected
# to ``/reset-password?token=<reset_token>`` where the existing
# ``/auth/reset-password`` endpoint consumes the token, sets the new
# password, and clears the flag via ``_apply_new_password``.
#
# The mid-flow token has a shorter 15-minute TTL (the customer is
# actively signing in — no reason to keep a live handoff token for
# 30 min). If it lapses, the customer re-logs with the temp password
# and gets a fresh token. The TEMP PASSWORD ITSELF never expires
# until consumed.
_TEMP_PASSWORD_RESET_TTL_MINUTES = 15
_TEMP_PASSWORD_RESET_SOURCE = "temp_password_login"


async def _mint_temp_password_reset_token(user: dict, ip: str) -> dict:
    """Mint a single-use reset token for a temp-password login fork.
    Invalidates any prior unused tokens for this user, mirrors the
    Task-O shape 1:1, and returns the ``{status, reset_token,
    user_id, token_ttl_minutes}`` payload the FE consumes."""
    import secrets
    await db.password_reset_tokens.update_many(
        {"user_id": user["id"], "used_at": None},
        {"$set": {"invalidated_at": now_iso()}},
    )
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=_TEMP_PASSWORD_RESET_TTL_MINUTES)
    await db.password_reset_tokens.insert_one({
        "id": new_id(),
        "token": token,
        "user_id": user["id"],
        "tenant_id": user.get("tenant_id"),
        "email": user.get("email"),
        "expires_at": expires_at.isoformat(),
        "used_at": None,
        "invalidated_at": None,
        "created_at": now_iso(),
        "created_ip": ip,
        "source": _TEMP_PASSWORD_RESET_SOURCE,
    })
    return {
        "status": "password_reset_required",
        "reset_token": token,
        "user_id": user["id"],
        "token_ttl_minutes": _TEMP_PASSWORD_RESET_TTL_MINUTES,
        # Feb-2026 · P0 loop fix — expose the role so the FE can
        # defense-in-depth gate the reset redirect. Only customers
        # ever land here after the backend gate below; the field is
        # a belt-and-braces signal, not authorization.
        "role": user.get("role"),
    }


# ── Feb-2026 · P0 forced-reset-loop fix — trigger gate + audit ─────
# The temp-password fork must fire ONLY when ALL of:
#   1) user.role == "customer"                (non-customer roles
#      never hit the customer portal reset UX)
#   2) user.must_change_password_on_next_login is truthy
#   3) user.has_ever_logged_in is NOT truthy  (once a customer has
#      completed a real sign-in, the flag is stale — surfacing it
#      creates the reset loop the P0 was filed against)
#
# When (2) is truthy but (3) is ALSO truthy for a customer, we emit
# a ``customer.suspicious_forced_reset_flag`` audit row so ops can
# investigate why the flag was re-armed post-first-login. We do NOT
# fork in that state.
def _should_fork_temp_password_flow(user: dict) -> bool:
    role = (user.get("role") or "").strip().lower()
    if role != "customer":
        return False
    if not user.get("must_change_password_on_next_login"):
        return False
    if user.get("has_ever_logged_in"):
        return False
    return True


async def _audit_suspicious_forced_reset_flag(user: dict, ip: str) -> None:
    """Belt-and-braces observability: a customer with
    ``has_ever_logged_in=True`` should never carry
    ``must_change_password_on_next_login=True`` at the same time.
    If they do, log the anomaly (event + tenant + IDs) so ops can
    trace the write — but do NOT fork into the reset UX (Trigger
    condition #3 gates the modal)."""
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": user.get("tenant_id"),
            "event": "customer.suspicious_forced_reset_flag",
            "target_user_id": user.get("id"),
            "target_customer_id": user.get("customer_id"),
            "email": (user.get("email") or "").lower(),
            "ip_address": ip,
            "details": (
                "must_change_password_on_next_login=True on a "
                "customer with has_ever_logged_in=True — ignored "
                "by the login fork gate."
            ),
            "created_at": now_iso(),
        })
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "[forced-reset-audit] insert failed for uid=%s: %s",
            user.get("id"), exc,
        )


async def _stamp_first_access(user: dict, ip: str) -> None:
    """Idempotent — mark ``has_ever_logged_in=True`` + stamp
    ``first_access_at`` on the ``users`` row the FIRST time it
    completes a successful sign-in, and mirror
    ``portal_first_login_at`` onto the linked customer doc (for
    customer-role users) so the ``GET /customers?first_access=…``
    filter reads a pre-computed field.
    """
    if user.get("has_ever_logged_in"):
        return
    now_str = now_iso()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "has_ever_logged_in": True,
            "first_access_at": now_str,
            "first_access_ip": ip,
        }},
    )
    if user.get("role") == "customer" and user.get("customer_id"):
        try:
            # Only stamp if the customer doc hasn't already been
            # marked (belt-and-braces — the users flag is the
            # source of truth, this is the denorm for filtering).
            await db.customers.update_one(
                {"id": user["customer_id"],
                  "tenant_id": user.get("tenant_id"),
                  "$or": [{"portal_first_login_at": None},
                            {"portal_first_login_at": {"$exists": False}}]},
                {"$set": {"portal_first_login_at": now_str}},
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "[first-access] customer denorm failed cid=%s: %s",
                user.get("customer_id"), exc,
            )


# ─────────────────────────────────────────────────────────────────────
# Phase S1.1 · Feb-2026 — founder auto-promotion helper.
# ─────────────────────────────────────────────────────────────────────
FOUNDER_SUPER_ADMIN_EMAIL = (
    (os.environ.get("FOUNDER_SUPER_ADMIN_EMAIL") or "").strip().lower()
)


async def _maybe_promote_founder(user: dict, ip: str) -> None:
    """If ``user.email`` matches ``FOUNDER_SUPER_ADMIN_EMAIL`` and the
    stored role is not ``super_admin``, promote them. Idempotent —
    already-super founders are no-ops. Writes a single audit row per
    real promotion so ops can trace one-time role escalation.
    """
    if not FOUNDER_SUPER_ADMIN_EMAIL:
        return
    email = (user.get("email") or "").lower().strip()
    if email != FOUNDER_SUPER_ADMIN_EMAIL:
        return
    if (user.get("role") or "").lower() == "super_admin":
        return
    old_role = user.get("role")
    now = now_iso()
    try:
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "role":                       "super_admin",
                "role_changed_at":            now,
                "role_changed_by_user_id":    "system:founder_pin",
            }},
        )
        # In-place bump on the mutable dict so the token minted
        # downstream carries the new role without re-reading Mongo.
        user["role"] = "super_admin"
        await db.audit_log.insert_one({
            "id": new_id(),
            "tenant_id":       user.get("tenant_id"),
            "actor_user_id":   "system:founder_pin",
            "actor_email":     "system",
            "action":          "user.role_change",
            "target_user_id":  user["id"],
            "changes":         {"role": {"old": old_role, "new": "super_admin"}},
            "notes":           "founder auto-promotion (FOUNDER_SUPER_ADMIN_EMAIL match)",
            "at":              now,
            "ip_address":      ip,
        })
        logger.info(
            "[s1] founder promoted → user_id=%s email=%s old_role=%s",
            user["id"], "<redacted>", old_role,
        )
    except Exception as exc:  # noqa: BLE001 — never break login on audit
        logger.warning(f"[s1] founder promotion failed: {exc}")


async def promote_founder_on_boot() -> int:
    """Boot-time migration. Promotes any existing user whose email
    matches ``FOUNDER_SUPER_ADMIN_EMAIL`` to ``super_admin``. Does NOT
    demote existing super_admins. Returns 1 when a promotion landed,
    0 when the founder is missing OR already super_admin. Idempotent.
    """
    if not FOUNDER_SUPER_ADMIN_EMAIL:
        logger.warning(
            "[s1] FOUNDER_SUPER_ADMIN_EMAIL unset — skipping boot migration",
        )
        return 0
    row = await db.users.find_one(
        {"email": FOUNDER_SUPER_ADMIN_EMAIL}, {"_id": 0})
    if not row:
        # Founder hasn't signed up yet — the login-side hook will
        # promote them on first sign-in.
        return 0
    if (row.get("role") or "").lower() == "super_admin":
        return 0
    # Reuse the login-time helper for the actual write + audit row so
    # the two paths never drift.
    await _maybe_promote_founder(dict(row), ip="boot")
    return 1


@router.post("/auth/login")
async def login(request: Request, body: LoginRequest):
    email = body.email.lower()
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent", "") or ""
    # Feb-2026 · Task 4 · Option A account chooser (was: Miguel Munoz
    # "prefer workforce" hardening).
    #
    # A single email can end up on TWO ``users`` records — e.g. a
    # portal customer (role=customer, linked to a ``customers`` doc)
    # who is later added to the team as a technician (role=tech). The
    # old ``find_one({"email":email})`` returned whichever record
    # Mongo served first; the Miguel Munoz fix hardened that to
    # "prefer workforce" but silently DROPPED the customer record so
    # the user could never log into their portal without an admin
    # cleaning up the DB.
    #
    # Option A ships the correct answer: verify the password against
    # EVERY non-deleted record, and if 2+ match, hand the FE a
    # chooser with a short-lived ``choice_token`` that binds the
    # already-verified user_ids.  Behaviour matrix:
    #   * 1 record  → normal login (unchanged; Miguel Munoz preserved
    #     because the "workforce" record is the only surviving one
    #     after the shadow cleanup, or the customer record is the
    #     only one for a normal customer).
    #   * 2+ records but only 1 matches the password → normal login
    #     for that record (also unchanged; enables password-differ
    #     recovery without asking the user to pick).
    #   * 2+ records AND 2+ match the password → chooser branch.
    #
    # No user records are merged or deleted.  Impersonation flow is
    # untouched (it uses ``create_token(..., impersonator_id=...)``
    # directly, not this endpoint).
    non_deleted_q = {
        "email": email,
        "$or": [{"deleted_at": None},
                  {"deleted_at": {"$exists": False}}],
    }
    all_records = await db.users.find(non_deleted_q, {"_id": 0}).to_list(10)
    now = datetime.now(timezone.utc)

    # Generic message to avoid user enumeration.
    # Phase P3 · Feb-2026 — Deliverable 3 ships structured 401
    # detail bodies so the frontend can distinguish
    # ``account_locked`` from ``invalid_credentials`` without
    # string-parsing.  "User not found" collapses into
    # ``invalid_credentials`` so account enumeration is still
    # impossible from the response.
    invalid = HTTPException(
        status_code=401,
        detail={
            "code": "invalid_credentials",
            "message": "Wrong email or password.",
        },
    )

    if not all_records:
        # No non-deleted user — attempt one last-resort find so a
        # deleted-user attempt still triggers the "removed" 401 with
        # the specific detail (matches prior audit shape).
        user = await db.users.find_one({"email": email})
        if not user:
            await _audit_auth("login", email, ip, "failure", "user not found")
            raise invalid
        # fall through to the single-record path below for the
        # "everything is soft-deleted" case so the audit row + error
        # detail stays identical to pre-Task-4.
        all_records = [user]

    # Pick the record we anchor lockout state on.  Prefer a workforce
    # record so a customer duplicate can't reset an admin's lockout
    # by trying random passwords.  This mirrors the pre-Task-4
    # "prefer workforce" ordering for the lockout probe only — the
    # password verification below fans out across ALL records.
    workforce_record = next(
        (r for r in all_records if (r.get("role") or "").lower() in _WORKFORCE_ROLES),
        None,
    )
    lockout_anchor = workforce_record or all_records[0]

    # 1) Account lockout check — on the anchor record.
    lock = lockout_anchor.get("lockout_until")
    if lock:
        lock_dt = lock if isinstance(lock, datetime) else datetime.fromisoformat(lock)
        if lock_dt.tzinfo is None:
            lock_dt = lock_dt.replace(tzinfo=timezone.utc)
        if lock_dt > now:
            await _audit_auth("login_locked", email, ip, "failure", "attempt while locked")
            mins = max(1, int((lock_dt - now).total_seconds() // 60) + 1)
            # Phase P3 · Feb-2026 — structured 401 detail so the FE
            # can render a friendly local-time banner without
            # regex-parsing the ``message`` string.  The status
            # code stays 401 (per the P3 spec) so a single client
            # handler covers both lockout and invalid-credentials.
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "account_locked",
                    "locked_until": lock_dt.isoformat(),
                    "message": f"Account locked. Try again in {mins} minute(s).",
                },
            )

    # 2) Verify password against every non-deleted candidate.  Any
    # candidate that verifies is a "match".
    matches = [r for r in all_records
                if verify_password(body.password, r.get("password_hash", ""))]

    if not matches:
        # 0 matches — bump the anchor's failed-attempt counter.
        attempts = int(lockout_anchor.get("failed_login_attempts", 0)) + 1
        upd = {"failed_login_attempts": attempts}
        if attempts >= MAX_FAILED_ATTEMPTS:
            upd["lockout_until"] = (now + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            await _audit_auth("account_lockout", email, ip, "failure",
                                f"locked {LOCKOUT_MINUTES}m after {attempts} attempts")
        else:
            await _audit_auth("login", email, ip, "failure", f"attempt {attempts}")
        await db.users.update_one({"id": lockout_anchor["id"]}, {"$set": upd})
        raise invalid

    # 3) 2+ matches with divergent roles → chooser branch.
    distinct_roles = {(m.get("role") or "").lower() for m in matches}
    if len(matches) >= 2 and len(distinct_roles) >= 2:
        # Log a warning so admins can still find these accounts via
        # the migrations tool if they want to consolidate — but do
        # NOT force it.  Option A is designed to work indefinitely
        # with parallel records.
        logger.warning(
            "[auth] multi-record chooser served — email=%s roles=%s "
            "user_ids=%s",
            email, sorted(distinct_roles),
            [m["id"] for m in matches],
        )
        # Reset any failed-attempt counters on records that matched;
        # the successful password verification proves the user isn't
        # brute-forcing.  Only ``lockout_anchor`` was touched.
        if lockout_anchor.get("failed_login_attempts") or lockout_anchor.get("lockout_until"):
            await db.users.update_one(
                {"id": lockout_anchor["id"]},
                {"$set": {"failed_login_attempts": 0, "lockout_until": None}},
            )
        matched_ids = [m["id"] for m in matches]
        choice_token = _issue_choice_token(email, matched_ids)
        await _audit_auth(
            "login_choice_required", email, ip, "success",
            f"{len(matches)} matching records, roles={sorted(distinct_roles)}",
        )
        await _audit_multi_account_choice(
            event="required",
            email=email, ip=ip, user_agent=user_agent,
            tenant_id=(workforce_record or matches[0]).get("tenant_id"),
            user_ids=matched_ids,
        )
        return {
            "status": "multi_account_choice_required",
            "email": email,
            "choices": [
                {
                    "account_id": m["id"],
                    "role": m.get("role"),
                    "display": _account_display(m),
                }
                for m in matches
            ],
            "choice_token": choice_token,
        }

    # 4) Exactly 1 match (or 2+ matches with the SAME role — treated
    # as an already-deduplicated record, first wins).  Runs the
    # existing single-record success flow verbatim.
    user = matches[0]
    if len(matches) > 1:
        # 2+ matches, same role — the pre-Task-4 code would have
        # picked one silently too; keep behaviour but audit it.
        #
        # PORTAL-INVITE-EMAIL-COLLISION-FIX · Feb-2026 (P0 #1 + #2)
        # observability add-on.  When the same email resolves to
        # multiple role=customer rows with DISTINCT customer_ids,
        # log the structural details — a single email mapping to
        # multiple customer records in one tenant is the exact
        # duplicate-user pattern the Commit-1 collision guard
        # (``_upsert_customer_user``) prevents for NEW invites.
        # Pre-existing duplicates (from before the guard shipped)
        # still slip through login row-selection; this warning
        # gives ops the signal to trigger the duplicate-user
        # remediation runbook.  No PII beyond user_id/customer_id
        # prefixes in the structured log — the ``email`` arg
        # mirrors the existing warning on the line above so grep
        # behaviour is unchanged.
        role_lc = (user.get("role") or "").strip().lower()
        distinct_customer_ids = {
            (m.get("customer_id") or "") for m in matches
            if m.get("customer_id")
        }
        if role_lc == "customer" and len(distinct_customer_ids) >= 2:
            logger.warning(
                "[auth] PORTAL-INVITE-EMAIL-COLLISION-FIX observability "
                "— duplicate role=customer rows with distinct customer_ids "
                "detected on login — email=%s match_count=%d "
                "distinct_customer_id_count=%d "
                "user_id_prefixes=%s customer_id_prefixes=%s "
                "picked_user_id_prefix=%s picked_customer_id_prefix=%s "
                "action=run_duplicate_user_remediation_runbook",
                email, len(matches), len(distinct_customer_ids),
                sorted({(m.get("id") or "")[:8] for m in matches}),
                sorted({c[:8] for c in distinct_customer_ids}),
                (user.get("id") or "")[:8],
                (user.get("customer_id") or "")[:8],
            )
        else:
            logger.warning(
                "[auth] multi-record same-role login — email=%s role=%s "
                "picked user_id=%s (%d parallel records; consider "
                "consolidation)",
                email, user.get("role"), user["id"], len(matches),
            )
    # Success -> reset counters
    if user.get("failed_login_attempts") or user.get("lockout_until"):
        await db.users.update_one({"id": user["id"]}, {"$set": {"failed_login_attempts": 0, "lockout_until": None}})
    # Soft-deleted accounts cannot obtain a token. ``get_current_user``
    # already hard-401s them ("account_deleted") on the next request, so
    # minting a token here produced a 200-then-401 loop that the mobile
    # client turns into an endless sign-in bounce. Checked here for the
    # audit row; ``create_token`` enforces it for every other issue path.
    if user.get("deleted_at"):
        await _audit_auth("login", email, ip, "failure", "account soft-deleted")
        raise HTTPException(
            status_code=401,
            detail="This account has been removed. Contact your administrator.",
        )
    # SEC-004 hotfix — deactivated accounts cannot obtain a token.
    if user.get("active") is False:
        await _audit_auth("login", email, ip, "failure", "account deactivated")
        raise HTTPException(status_code=403, detail="Account is deactivated")
    # ── Feb-2026 · Temp password fork ─────────────────────────────
    # If the admin (or the seed / provision path) has flagged this
    # user as ``must_change_password_on_next_login=True``, fork
    # BEFORE issuing an access token. The customer gets a 200 with
    # ``status=password_reset_required`` + a 15-min opaque token
    # they must consume via ``/auth/reset-password``. No portal
    # login denorm (last_portal_login_at / first_access_at) is
    # stamped here — the sign-in isn't complete until the reset
    # consummates. Reset counters were reset above.
    #
    # Feb-2026 · P0 loop fix — the fork now requires role=customer
    # AND has_ever_logged_in!=True (via ``_should_fork_temp_password_flow``).
    # Non-customer roles ignore the flag entirely (defense-in-depth
    # per the P0 fix spec). Customers with a stale flag post-first-
    # login get an anomaly audit row and skip the fork.
    if user.get("must_change_password_on_next_login"):
        if _should_fork_temp_password_flow(user):
            payload = await _mint_temp_password_reset_token(user, ip)
            await _audit_auth(
                "login_password_reset_required", email, ip, "success",
                f"user_id={user['id']} ttl_min={_TEMP_PASSWORD_RESET_TTL_MINUTES}",
            )
            return payload
        # Stale-flag anomaly: customer with the flag but already-
        # logged-in. Warn ops via audit, then fall through to normal
        # login (Trigger condition #3 gates the fork).
        if (user.get("role") or "").strip().lower() == "customer":
            await _audit_suspicious_forced_reset_flag(user, ip)
        # Non-customer roles simply fall through — the flag has no
        # meaning outside the customer temp-password flow.
    # Phase S1.1 · Feb-2026 — founder auto-promotion. If the login
    # email matches ``FOUNDER_SUPER_ADMIN_EMAIL`` and the DB row is
    # not already ``super_admin``, promote it in-place before minting
    # the token. Idempotent — repeated logins by an already-super
    # founder are no-ops (one-time promotion + audit row).
    await _maybe_promote_founder(user, ip)
    await _audit_auth("login", email, ip, "success")
    # Feb-2026 Portal Access ship — stamp the customer doc with the
    # last portal login timestamp/IP + write a dedicated ``portal_login``
    # audit row so the admin Portal Access panel can show the customer's
    # recent activity without scanning the raw auth audit stream.
    if user.get("role") == "customer" and user.get("customer_id"):
        try:
            await db.customers.update_one(
                {"id": user["customer_id"], "tenant_id": user.get("tenant_id")},
                {"$set": {
                    "last_portal_login_at": now_iso(),
                    "last_portal_login_ip": ip,
                }},
            )
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": user.get("tenant_id"),
                "event": "portal_login",
                "target_customer_id": user["customer_id"],
                "target_user_id": user["id"],
                "email": email,
                "ip_address": ip,
                "created_at": now_iso(),
            })
        except Exception as e:
            logger.warning(f"portal_login audit skipped: {e}")
    # Feb-2026 · First-access stamp — idempotent (users.has_ever_logged_in
    # gates the write). Applies to every role, but the customer denorm
    # branch inside only fires for customer-role users. Runs AFTER the
    # portal_login audit so the two events share the same ``now_iso``
    # window when the customer signs in for the first time.
    await _stamp_first_access(user, ip)
    return auth_response(user)


# ── Feb-2026 · Task 4 · Option A account chooser ──────────────────
class _SelectAccountBody(BaseModel):
    choice_token: str
    account_id: str


@router.post("/auth/login/select-account")
async def login_select_account(request: Request, body: _SelectAccountBody):
    """Completes a multi-record login after the user picks which
    account they want to sign in as.

    Contract:
      * ``choice_token`` — the short-lived JWT returned by
        ``/auth/login`` when the ``multi_account_choice_required``
        branch fired.  Password was already verified when this token
        was issued; the token binds the exact set of user_ids that
        matched.  No re-verification here — the token is the proof.
      * ``account_id`` — MUST be one of the user_ids in the token's
        ``verified`` claim; any other value returns 401 to prevent
        an attacker with a leaked choice_token from escalating into
        an account that never password-matched.
      * On success, returns the same shape as ``/auth/login`` for a
        single-record success: ``{access_token, token_type, user,
        ...}``.  The FE can persist this identically to a normal
        login response.
    """
    ip = _client_ip(request)
    user_agent = request.headers.get("user-agent", "") or ""
    payload = _decode_choice_token(body.choice_token)
    email = str(payload.get("email") or "").lower()
    verified_ids = list(payload.get("verified") or [])
    if not email or not verified_ids:
        raise HTTPException(status_code=401, detail="Invalid choice token")
    if body.account_id not in verified_ids:
        # Never confirm/deny which id was in the list — the fact
        # that account_id isn't in the verified list is itself the
        # security event we want to audit + reject.
        await _audit_auth(
            "login_choice_selected", email, ip, "failure",
            f"account_id not in verified list ({body.account_id})",
        )
        raise HTTPException(status_code=401, detail="Invalid account selection")
    user = await db.users.find_one({"id": body.account_id}, {"_id": 0})
    if not user or user.get("email") != email:
        await _audit_auth(
            "login_choice_selected", email, ip, "failure",
            f"account row missing or email mismatch ({body.account_id})",
        )
        raise HTTPException(status_code=401, detail="Account not found")
    # Same gate checks as the normal login success path.
    if user.get("deleted_at"):
        await _audit_auth("login_choice_selected", email, ip, "failure",
                            f"account soft-deleted ({body.account_id})")
        raise HTTPException(
            status_code=401,
            detail="This account has been removed. Contact your administrator.",
        )
    if user.get("active") is False:
        await _audit_auth("login_choice_selected", email, ip, "failure",
                            f"account deactivated ({body.account_id})")
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Success — reset counters on THIS record specifically (the
    # anchor's counters were already reset in ``login``).
    if user.get("failed_login_attempts") or user.get("lockout_until"):
        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {"failed_login_attempts": 0, "lockout_until": None}},
        )
    # ── Feb-2026 · Temp password fork (parity with /auth/login) ────
    # If the picked record is a temp-password account, fork BEFORE
    # issuing an access token. Same 200 shape as ``login``.
    #
    # Feb-2026 · P0 loop fix — mirror the ``login`` gate:
    # customer + flag + !has_ever_logged_in. Stale-flag anomaly on
    # customers gets an audit row. Non-customer roles ignore the flag.
    if user.get("must_change_password_on_next_login"):
        if _should_fork_temp_password_flow(user):
            payload = await _mint_temp_password_reset_token(user, ip)
            await _audit_auth(
                "login_choice_password_reset_required", email, ip, "success",
                f"user_id={user['id']} ttl_min={_TEMP_PASSWORD_RESET_TTL_MINUTES}",
            )
            return payload
        if (user.get("role") or "").strip().lower() == "customer":
            await _audit_suspicious_forced_reset_flag(user, ip)
    await _audit_auth("login_choice_selected", email, ip, "success",
                        f"role={user.get('role')} user_id={user['id']}")
    await _audit_multi_account_choice(
        event="selected",
        email=email, ip=ip, user_agent=user_agent,
        tenant_id=user.get("tenant_id"),
        user_ids=verified_ids,
        chosen_user_id=user["id"],
        chosen_role=user.get("role"),
    )
    # Mirror the same portal-login audit trail as ``/auth/login``.
    now_str = now_iso()
    if user.get("role") == "customer" and user.get("customer_id"):
        try:
            await db.customers.update_one(
                {"id": user["customer_id"], "tenant_id": user.get("tenant_id")},
                {"$set": {"last_portal_login_at": now_str,
                            "last_portal_login_ip": ip}},
            )
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": user.get("tenant_id"),
                "event": "portal_login",
                "target_customer_id": user["customer_id"],
                "target_user_id": user["id"],
                "email": email,
                "ip_address": ip,
                "created_at": now_str,
            })
        except Exception as exc:                    # noqa: BLE001
            logger.warning(f"portal_login audit skipped (chooser): {exc}")
    # Feb-2026 · First-access stamp — parity with ``/auth/login``.
    await _stamp_first_access(user, ip)
    return auth_response(user)


@router.post("/auth/signup")
async def signup(request: Request, body: SignupRequest):
    email = body.email.lower()
    ip = _client_ip(request)
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account with this email already exists")
    # Resolve tenant from X-Tenant-Slug header if provided; else default tenant.
    tenant = None
    slug = request.headers.get("x-tenant-slug")
    if slug:
        # Phase 21 · Feb 2026 — tolerate ``slug_aliases`` (e.g. "plofv"
        # resolves to the same tenant as canonical "aquaterra").
        tenant = await db.tenants.find_one(
            {"$or": [{"slug": slug}, {"slug_aliases": slug}], "active": True},
            {"_id": 0},
        )
    if not tenant:
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host:
            tenant = await db.tenants.find_one({"custom_domain": host, "active": True}, {"_id": 0})
    if not tenant:
        tenant = await _ensure_default_tenant()
    tid = tenant["id"]
    # Create a customer record for the new self-signed-up client
    customer = {
        "id": new_id(), "tenant_id": tid, "name": body.name, "email": email,
        "phone": body.phone or "", "address": body.address or "", "notes": "",
        "created_at": now_iso(),
    }
    await db.customers.insert_one(customer)
    user = {
        "id": new_id(), "tenant_id": tid, "name": body.name, "email": email,
        "password_hash": hash_password(body.password), "role": "customer",
        "avatar": "", "technician_id": None, "customer_id": customer["id"],
        "failed_login_attempts": 0, "lockout_until": None,
    }
    await db.users.insert_one(user)
    await _audit_auth("signup", email, ip, "success")
    return auth_response(user)


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    # BUG E — decorate the raw user doc with the server-authoritative
    # ToS gate flag so the frontend gate can read a single source of
    # truth without duplicating the role/version logic client-side.
    from config_tos import compute_must_accept_tos
    payload = {**user, "must_accept_tos": compute_must_accept_tos(user)}

    # Feb-2026 · mobile-flagged gap — detect orphan customer auth users
    # (role=customer but no linked customer record) so the frontend can
    # render a "complete your profile" prompt instead of 500-ing on a
    # missing customer_id downstream. We NEVER silently create records
    # here; a super_admin repair endpoint exists for that
    # (``POST /api/admin/users/{id}/create-customer-record``).
    if user.get("role") == "customer":
        cid = user.get("customer_id")
        cust = None
        if cid:
            cust = await db.customers.find_one(
                {"id": cid, "tenant_id": user.get("tenant_id")},
                {"_id": 0, "id": 1},
            )
        payload["customer_record_missing"] = cust is None

    # Feb-2026 · surface ``auto_clockin_enabled`` in the me payload so
    # the mobile Clock-In screen + web Team page can key off the same
    # authoritative flag. Defaults: True for tech, False otherwise.
    if "auto_clockin_enabled" not in payload:
        payload["auto_clockin_enabled"] = (user.get("role") == "technician")
    # Phase T1.2 · Feb-2026 — attach ``available_tenants`` + the
    # persisted ``active_tenant_id`` so the top-nav switcher can
    # render immediately after boot without an extra roundtrip.
    from services.user_tenants import get_user_tenants
    payload["available_tenants"] = await get_user_tenants(user)
    payload["active_tenant_id"] = (user.get("active_tenant_id")
                                    or user.get("tenant_id"))
    payload["tenant_memberships"] = user.get("tenant_memberships") or []

    # Phase P52 · Feb-2026 — surface ``tenant.default_locale`` in the
    # /auth/me payload so ``auth.jsx`` can hydrate
    # ``localStorage.tenant_default_locale`` on boot.  The frontend
    # i18n detector chain then reads that value as the tenant-scoped
    # fallback between the user's personal ``localStorage.lang`` and
    # the browser navigator.  Falls silently to ``None`` when the
    # tenant record is missing / hasn't been migrated yet — the
    # frontend treats null as "no tenant fallback" and skips that
    # rung of the detector chain.
    tid = payload.get("active_tenant_id") or user.get("tenant_id")
    tenant_default_locale = None
    if tid:
        try:
            t_doc = await db.tenants.find_one(
                {"id": tid}, {"_id": 0, "default_locale": 1},
            )
            if t_doc and t_doc.get("default_locale") in ("en", "es", "fr"):
                tenant_default_locale = t_doc["default_locale"]
        except Exception:                                       # noqa: BLE001
            # Never let the tenant lookup take down /auth/me — auth
            # is a hot path.  A null value degrades gracefully at
            # the frontend detector chain.
            tenant_default_locale = None
    payload["tenant_default_locale"] = tenant_default_locale
    return payload


# ═════════════════════════════════════════════════════════════════════
# Phase T1.3 · Feb-2026 — POST /api/auth/switch-tenant.
# ═════════════════════════════════════════════════════════════════════
class _SwitchTenantBody(BaseModel):
    tenant_id: str


@router.post("/auth/switch-tenant")
async def switch_tenant(
    body: _SwitchTenantBody,
    user: dict = Depends(get_current_user),
):
    """Swap the caller's active tenant.

    Phase S1.2 · Feb-2026 — super_admin only. Multi-tenant switching
    is now an operations-team feature; every other role stays pinned
    to their default tenant even when their JWT carries multiple
    memberships. Non-super_admin → 403
    ``insufficient_role_for_tenant_switch``.

    *   Validates ``tenant_id`` is one of the user's
        ``tenant_memberships`` (legacy single-tenant users
        synthesise a membership from ``tenant_id``).
    *   Persists ``users.active_tenant_id`` so a fresh login on a
        new device remembers the choice (strong UX win, low risk).
    *   Mints a NEW JWT carrying ``active_tenant_id`` — the
        frontend replaces the token in localStorage + hard-refreshes
        the page so every mounted component re-fetches its data.
    """
    if (user.get("role") or "").lower() != "super_admin":
        raise HTTPException(
            status_code=403,
            detail="insufficient_role_for_tenant_switch",
        )
    from services.user_tenants import user_has_membership
    tid = (body.tenant_id or "").strip()
    if not tid or not user_has_membership(user, tid):
        raise HTTPException(
            status_code=403, detail="tenant_not_in_memberships")
    tenant = await db.tenants.find_one(
        {"id": tid, "active": True},
        {"_id": 0, "id": 1, "name": 1, "slug": 1})
    if not tenant:
        raise HTTPException(
            status_code=403, detail="tenant_not_in_memberships")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"active_tenant_id": tid}})
    token = create_token(user, active_tenant_id=tid)
    return {
        "access_token": token,
        "token_type":   "bearer",
        "active_tenant": {
            "id":   tenant["id"],
            "name": tenant.get("name"),
            "slug": tenant.get("slug"),
        },
    }


# ══════════════════════════════════════════════════════════════════════
# Phase 34 · Task O · Feb-2026 — Self-serve password reset
# ══════════════════════════════════════════════════════════════════════
# Two-endpoint flow:
#
#   POST /api/auth/forgot-password  → generic 200 (enum-safe). If the
#     email matches a user, mint a single-use opaque token, persist to
#     ``password_reset_tokens`` with a 30-day expiry, and send a
#     tokenized link via the guarded email adapter (dry-runs in preview
#     unless the recipient is on ``COMMS_TEST_ALLOWLIST_EMAILS`` — see
#     Task L).
#
#   POST /api/auth/reset-password   → accepts ``{token, new_password}``,
#     validates the token, enforces the same password policy the
#     admin change-password form uses, updates the auth-user hash,
#     invalidates the token.
#
# Design choices:
# * Opaque UUID tokens (not JWT) so a stolen backend log line without
#   the DB row can't derive the reset target.
# * Rate limit 5 requests / IP / hour (keyed in memory — good enough
#   for the current single-node preview; a Redis-backed limiter is
#   tracked as a Phase-35 follow-up).
# * Neutral response body — never disclose whether an account exists.
# * Every successful reset invalidates any other pending tokens for
#   the same user and unwinds ``failed_login_attempts`` / ``lockout_until``.
#
from collections import defaultdict, deque

# Password-reset link TTL. Feb-2026 · hotfix widened the window
# from a half-hour (the original 30-min value) to **30 days** per
# product spec (Phase 30 planned 30-day lifecycles; the constant +
# email copy had drifted). Kept as ``_RESET_TTL_MINUTES`` because
# callers already speak minutes and ``timedelta(minutes=…)`` is the
# natural unit for ``password_reset_tokens.expires_at``.
_RESET_TTL_DAYS = 30
_RESET_TTL_MINUTES = _RESET_TTL_DAYS * 24 * 60      # 43200
_RESET_RATE_MAX_PER_HOUR = 5
_RESET_IP_HITS: Dict[str, deque] = defaultdict(deque)  # noqa: F821


def _format_expiry_label(minutes: int) -> str:
    """Render an expiry duration as a human-facing label for email
    copy. Prefers the largest unit that produces a clean integer:

        >>> _format_expiry_label(43200)   # 30 days
        '30 days'
        >>> _format_expiry_label(120)     # 2 hours
        '2 hours'
        >>> _format_expiry_label(30)      # 30 minutes
        '30 minutes'

    Fractional / non-round values fall through to minutes so we
    never lose fidelity."""
    if minutes <= 0:
        return "0 minutes"
    if minutes % (24 * 60) == 0:
        d = minutes // (24 * 60)
        return f"{d} day" if d == 1 else f"{d} days"
    if minutes % 60 == 0:
        h = minutes // 60
        return f"{h} hour" if h == 1 else f"{h} hours"
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def _password_policy_ok(pw: str) -> Optional[str]:
    """Return an error message if ``pw`` fails policy, else None."""
    if not pw or len(pw) < 8:
        return "Password must be at least 8 characters long."
    import re as _re
    if not _re.search(r"[a-z]", pw):
        return "Password must include a lowercase letter."
    if not _re.search(r"[A-Z]", pw):
        return "Password must include an uppercase letter."
    if not _re.search(r"[0-9]", pw):
        return "Password must include a digit."
    return None


def _check_reset_rate_limit(ip: str) -> bool:
    """In-process rolling-window rate limiter. Returns True if the
    request is within budget, False if it has exceeded the cap."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=1)
    q = _RESET_IP_HITS[ip]
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= _RESET_RATE_MAX_PER_HOUR:
        return False
    q.append(now)
    return True


class ForgotPasswordRequest(BaseModel):  # noqa: F405 — models module uses star import
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/auth/forgot-password")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    """Self-serve request-a-reset endpoint.

    Always returns the same neutral 200 payload so callers can't
    enumerate whether an account exists. When the email matches a
    real user we mint a single-use opaque token, persist it to
    ``password_reset_tokens`` (TTL 30 days, ``used_at`` field on
    consumption), and hand a tokenized link to the guarded email
    adapter (dry-run in preview unless the recipient is on
    ``COMMS_TEST_ALLOWLIST_EMAILS``).
    """
    ip = _client_ip(request)
    if not _check_reset_rate_limit(ip):
        await _audit_auth("password_reset_request", (body.email or "").lower(),
                          ip, "failure", "rate_limited")
        # Still return the neutral 200 so a bad actor can't tell the
        # difference between rate-limit and "no such account".
        return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}

    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}

    user = await db.users.find_one({"email": email})
    # Mint + send only if the user actually exists; return the same
    # neutral response either way.
    if user:
        # Invalidate any prior unused tokens for this user so only the
        # most-recent link works.
        await db.password_reset_tokens.update_many(
            {"user_id": user["id"], "used_at": None},
            {"$set": {"invalidated_at": now_iso()}},
        )
        import secrets
        token = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=_RESET_TTL_MINUTES)
        await db.password_reset_tokens.insert_one({
            "id": new_id(),
            "token": token,
            "user_id": user["id"],
            "tenant_id": user.get("tenant_id"),
            "email": email,
            "expires_at": expires_at.isoformat(),
            "used_at": None,
            "invalidated_at": None,
            "created_at": now_iso(),
            "created_ip": ip,
        })

        frontend_url = (os.environ.get("APP_PUBLIC_URL")  # noqa: F821
                        or os.environ.get("FRONTEND_URL")
                        or "").rstrip("/")
        reset_link = f"{frontend_url}/reset-password?token={token}"

        # Send via the guarded adapter. Preview will dry-run for any
        # recipient not on the allow-list; Brian's account IS allow-
        # listed so his link goes live (subject to the Resend key).
        try:
            from services.email.resend_adapter import send as _send_email
            # Feb-2026 · Email Base Template Theming — resolve tenant
            # branding once and wrap the reset-email HTML in the shared
            # shell. Failures fall open to default branding.
            from services.email.theming import wrap_html_in_shell
            from services.tenants.business_settings import (
                get_effective_business_settings,
            )
            try:
                branding = await get_effective_business_settings(
                    db, user.get("tenant_id") or "", absolutize=True,
                )
            except Exception as _be:  # noqa: BLE001
                logger.warning(
                    f"branding resolve failed for reset email: {_be}",
                )
                branding = {}

            first_name = (
                user.get("first_name")
                or (user.get("name") or "").split(" ")[0]
                or "there"
            )
            # Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — DB-first render.
            # ``_resolve_password_reset_email_html`` prefers the
            # ``auth_password_reset_email`` row in ``marketing_templates``
            # over the hardcoded fallback, so tenants that clone + edit
            # the row via the marketing UI see their copy on sends.
            tenant_for_tpl = {"id": user.get("tenant_id") or ""}
            reset_subject, reset_body = (
                await _resolve_password_reset_email_html(
                    tenant=tenant_for_tpl,
                    first_name=first_name,
                    reset_link=reset_link,
                    expiry_minutes=_RESET_TTL_MINUTES,
                )
            )
            html = wrap_html_in_shell(reset_body, branding)
            res = await _send_email(
                to=email,
                subject=reset_subject,
                html=html,
                category="transactional",
                tenant_id=user.get("tenant_id"),
                customer_id=user.get("customer_id"),
                # Phase K72 · Feb-2026 — user-initiated password reset
                # is a transactional, self-triggered flow (the user
                # clicked "forgot"). Bypasses the K72 customer-email
                # kill switch so a customer trying to unlock their
                # portal isn't collateral damage during an incident.
                audience="internal",
            )
            # Always log the reset link (behind INFO) so ops can help
            # a stuck customer out-of-band, and so preview dry-run
            # traffic is visually verifiable per the Task O brief.
            logger.info(
                "[task-o] password_reset link=%s to=%s status=%s attempts=%s",
                reset_link, email,
                res.get("provider_status"), res.get("attempts"),
            )
        except Exception as exc:  # pragma: no cover — never blocks the neutral response
            logger.warning("password_reset email send failed: %s", exc)

        await _audit_auth("password_reset_request", email, ip, "success",
                          f"token_minted expires_in_min={_RESET_TTL_MINUTES}")
    else:
        # No user with that email. Log for ops visibility; still
        # return neutral to the caller.
        await _audit_auth("password_reset_request", email, ip, "success",
                          "no_user_matched")
    return {"ok": True, "message": "If an account exists for that email, a reset link has been sent."}


async def _load_reset_token(tok: str, ip: str) -> dict:
    """Load ``password_reset_tokens`` row for ``tok`` and gate on
    used / invalidated / expired branches. Emits the matching audit
    event and raises ``HTTPException(400)`` with the user-facing
    message on any failure branch; otherwise returns the row dict.

    Feb-2026 · P6 refactor — extracted from ``reset_password`` so the
    orchestrator stays <= 20 lines and each failure branch remains
    independently characterization-testable.
    """
    row = await db.password_reset_tokens.find_one({"token": tok}, {"_id": 0})
    if not row:
        await _audit_auth("password_reset_complete", "", ip, "failure", "unknown_token")
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")
    email = row.get("email", "")
    if row.get("used_at"):
        await _audit_auth("password_reset_complete", email, ip,
                          "failure", "token_reused")
        raise HTTPException(400, "This reset link has already been used. Please request a new one.")
    if row.get("invalidated_at"):
        await _audit_auth("password_reset_complete", email, ip,
                          "failure", "token_invalidated")
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")
    exp_raw = row.get("expires_at")
    try:
        exp_dt = (exp_raw if isinstance(exp_raw, datetime)
                   else datetime.fromisoformat(exp_raw))
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    except Exception:
        # Unparseable expiry — treat as expired (fail-closed).
        exp_dt = datetime.now(timezone.utc) - timedelta(minutes=1)
    if exp_dt < datetime.now(timezone.utc):
        await _audit_auth("password_reset_complete", email, ip,
                          "failure", "token_expired")
        raise HTTPException(400, "This reset link has expired. Please request a new one.")
    return row


async def _apply_new_password(user_id: str, new_password: str) -> None:
    """Persist the new bcrypt hash and clear lockout state so the
    customer can sign in immediately with the new credential.

    Feb-2026 · P43c correction — additionally denorm
    ``portal_password_set_at`` onto the customer document so the
    Customers list "Portal status" filter can distinguish a
    customer who chose their own password from one who only ever
    received a temp password. Admin-created / staff-set passwords
    do NOT go through this helper (see the seed / provision paths),
    so the denorm is a reliable "customer engagement" signal.

    Feb-2026 · P0 loop fix — also flip ``has_ever_logged_in=True``
    and stamp ``first_password_reset_at`` / ``first_access_at``
    (if not previously stamped) so a subsequent login cannot re-
    trigger the temp-password fork (Trigger condition #3). The
    per-user idempotency: ``first_password_reset_at`` is only
    stamped on the FIRST reset — later resets update
    ``password_updated_at`` without touching the first stamp.
    """
    now = now_iso()
    user_row = await db.users.find_one({"id": user_id}, {"_id": 0}) or {}
    first_password_reset_at = (
        user_row.get("first_password_reset_at") or now
    )
    set_fields = {
        "password_hash": hash_password(new_password),
        "failed_login_attempts": 0,
        "lockout_until": None,
        "must_change_password_on_next_login": False,
        "password_updated_at": now,
        "password_customer_set_at": now,
        # P0 loop fix — same-transaction flip so the next login
        # can't loop back into the fork.
        "has_ever_logged_in": True,
        "first_password_reset_at": first_password_reset_at,
    }
    if not user_row.get("first_access_at"):
        set_fields["first_access_at"] = now
    await db.users.update_one(
        {"id": user_id},
        {"$set": set_fields},
    )
    # Mirror the customer-engagement flag to the customer doc for
    # O(index) filter perf on ``GET /customers?portal_activated=…``.
    try:
        user = await db.users.find_one(
            {"id": user_id},
            {"_id": 0, "role": 1, "customer_id": 1, "tenant_id": 1},
        )
        if user and user.get("role") == "customer" and user.get("customer_id"):
            await db.customers.update_one(
                {"id": user["customer_id"],
                  "tenant_id": user.get("tenant_id")},
                {"$set": {"portal_password_set_at": now}},
            )
    except Exception as e:  # pragma: no cover
        logger.warning(f"portal_password_set_at denorm skipped: {e}")


async def _consume_reset_token(tok: str, ip: str, user_id: str) -> None:
    """Mark ``tok`` as used and invalidate any OTHER unused tokens for
    the same user — belt-and-braces so a leaked earlier link can't be
    replayed after the customer resets."""
    await db.password_reset_tokens.update_one(
        {"token": tok},
        {"$set": {"used_at": now_iso(), "used_ip": ip}},
    )
    await db.password_reset_tokens.update_many(
        {"user_id": user_id, "used_at": None, "token": {"$ne": tok}},
        {"$set": {"invalidated_at": now_iso()}},
    )


@router.post("/auth/reset-password")
async def reset_password(request: Request, body: ResetPasswordRequest):
    """Complete a password reset started by ``/auth/forgot-password``.

    Validates the token (exists, not used, not expired, not
    invalidated), enforces the shared password policy, updates the
    auth-user's hash, marks the token used, and clears any
    ``failed_login_attempts`` / ``lockout_until`` so the customer
    can sign in immediately with the new credential.

    Feb-2026 · P0 loop fix — when the consumed token was minted by
    the temp-password login fork (``source == "temp_password_login"``)
    AND the target user is a customer, we auto-issue a fresh access
    token so the FE can drop the caller directly into the portal
    home. This eliminates the "reset → back-to-login → login again"
    UX that was reported as a loop. Non-temp-password callers (the
    ordinary self-serve forgot-password flow) keep the pre-existing
    "please sign in" shape.
    """
    ip = _client_ip(request)
    tok = (body.token or "").strip()
    if not tok:
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")
    err = _password_policy_ok(body.new_password or "")
    if err:
        raise HTTPException(400, err)
    row = await _load_reset_token(tok, ip)
    user = await db.users.find_one({"id": row["user_id"]})
    if not user:
        # Highly unlikely — but defensive.
        raise HTTPException(400, "Invalid or expired reset link. Please request a new one.")
    role = (user.get("role") or "").strip().lower()
    is_temp_flow = row.get("source") == _TEMP_PASSWORD_RESET_SOURCE
    should_auto_login = is_temp_flow and role == "customer"

    # P0 loop fix — stamp first-access denorms BEFORE
    # ``_apply_new_password`` flips ``has_ever_logged_in`` to True,
    # so the ``_stamp_first_access`` idempotency guard (which
    # short-circuits when has_ever_logged_in is already truthy)
    # still runs on the pre-reset state and writes the customer
    # ``portal_first_login_at`` denorm.
    if should_auto_login:
        try:
            await _stamp_first_access(user, ip)
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "[reset-auto-login] first-access stamp skipped uid=%s: %s",
                user.get("id"), exc,
            )
    await _apply_new_password(user["id"], body.new_password)
    await _consume_reset_token(tok, ip, user["id"])
    await _audit_auth("password_reset_complete", user.get("email", ""), ip,
                      "success", f"user_id={user['id']}")

    # P0 loop fix — auto-login the customer after their first-time
    # temp-password reset. Preconditions: source flag on the token
    # AND role=customer (never auto-login staff via this path).
    base = {"ok": True, "message": "Password reset. Please sign in."}
    if not should_auto_login:
        return base
    fresh_user = await db.users.find_one({"id": user["id"]}, {"_id": 0}) or user
    # First-login audit row so ops can attribute the auto-login
    # event to a real password-reset completion.
    try:
        await db.audit_logs.insert_one({
            "id": new_id(),
            "tenant_id": fresh_user.get("tenant_id"),
            "event": "customer.first_login_password_reset",
            "target_user_id": fresh_user.get("id"),
            "target_customer_id": fresh_user.get("customer_id"),
            "email": (fresh_user.get("email") or "").lower(),
            "ip_address": ip,
            "created_at": now_iso(),
        })
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "[first-login-audit] insert failed uid=%s: %s",
            fresh_user.get("id"), exc,
        )
    # Stamp last_portal_login denorms (mirrors ``/auth/login``).
    if fresh_user.get("customer_id"):
        try:
            await db.customers.update_one(
                {"id": fresh_user["customer_id"],
                  "tenant_id": fresh_user.get("tenant_id")},
                {"$set": {"last_portal_login_at": now_iso(),
                            "last_portal_login_ip": ip}},
            )
        except Exception as exc:  # pragma: no cover
            logger.warning(
                "[reset-auto-login] portal denorm skipped uid=%s: %s",
                fresh_user.get("id"), exc,
            )
    auth = auth_response(fresh_user)
    # Merge — keep the existing ``ok``/``message`` for callers
    # still keyed off them + add the JWT/user for auto-login.
    return {**base, "auto_login": True, **auth}


def _password_reset_email_html(*, first_name: str, reset_link: str,
                                 expiry_minutes: int) -> str:
    """Render the Task-O password-reset email body. Kept inline to
    avoid a new template collection; visual polish can graduate to
    the ``email_templates`` seed later (``password_reset_self_serve``).

    Feb-2026 · hotfix — the copy now renders the TTL through
    :func:`_format_expiry_label` so a 43200-minute (30-day) window
    reads as "30 days" instead of "43200 minutes".

    Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — the runtime path
    prefers the ``auth_password_reset_email`` row in
    ``marketing_templates`` when one exists (see
    :func:`_resolve_password_reset_email_html`).  This function is
    now the hardcoded fallback used only when the row is absent /
    the DB lookup fails."""
    expiry_label = _format_expiry_label(expiry_minutes)
    return (
        f"<div style=\"font-family:-apple-system,'Inter',sans-serif;"
        f"color:#0F172A;max-width:560px;margin:0 auto;padding:24px;\">"
        f"<h2 style=\"margin:0 0 12px;\">Reset your password</h2>"
        f"<p style=\"margin:0 0 12px;font-size:15px;line-height:1.55;\">"
        f"Hi {first_name},</p>"
        f"<p style=\"margin:0 0 16px;font-size:15px;line-height:1.55;\">"
        f"We received a request to reset your Pool &amp; Landscaping "
        f"portal password. Click the button below to choose a new one.</p>"
        f"<p style=\"margin:24px 0;\">"
        f"<a href=\"{reset_link}\" "
        f"style=\"display:inline-block;background:#0284C7;color:#fff;"
        f"padding:12px 22px;border-radius:10px;text-decoration:none;"
        f"font-weight:600;\">Reset password</a></p>"
        f"<p style=\"margin:0 0 8px;font-size:13px;color:#475569;\">"
        f"This link expires in {expiry_label}. If you didn't "
        f"request this reset you can safely ignore this email — your "
        f"password won't change.</p>"
        f"<p style=\"margin:16px 0 0;font-size:12px;color:#94A3B8;"
        f"word-break:break-all;\">"
        f"Or copy this link into your browser:<br/>"
        f"<a href=\"{reset_link}\" style=\"color:#475569;\">{reset_link}</a>"
        f"</p></div>"
    )


async def _resolve_password_reset_email_html(
    *,
    tenant: dict,
    first_name: str,
    reset_link: str,
    expiry_minutes: int,
) -> tuple:
    """Phase EMAIL-MIGRATE · Batch 1 · Feb-2026 — DB-first render.

    Tries the ``auth_password_reset_email`` row in
    ``marketing_templates`` first (tenant-specific > global default);
    falls back to :func:`_password_reset_email_html` when the row is
    absent OR the render blows up.  Returns
    ``(subject, html)`` — the caller wraps ``html`` in the branded
    shell before the send.
    """
    tenant_id = (tenant or {}).get("id") or ""
    expiry_label = _format_expiry_label(expiry_minutes)
    fallback_html = _password_reset_email_html(
        first_name=first_name,
        reset_link=reset_link,
        expiry_minutes=expiry_minutes,
    )
    fallback_subject = "Reset your password"
    try:
        from services.marketing_template_lookup import (
            get_template_with_global_fallback,
        )
        tpl = await get_template_with_global_fallback(
            "auth_password_reset_email", tenant_id or None,
        )
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            f"[auth-reset] template lookup failed — using hardcoded "
            f"fallback: {exc}"
        )
        return fallback_subject, fallback_html
    if not tpl or not tpl.get("body"):
        return fallback_subject, fallback_html
    try:
        from services.marketing.merge_tags import render_template
        ctx = {
            "tenant": tenant or {},
            "customer": {},
            "recipient_name": first_name,
            "reset_link": reset_link,
            "expiry_label": expiry_label,
        }
        rendered_subject, _ = render_template(
            tpl.get("subject") or fallback_subject, ctx, missing="empty",
        )
        rendered_body, _ = render_template(
            tpl["body"], ctx, missing="empty",
        )
        return (rendered_subject or fallback_subject,
                 rendered_body or fallback_html)
    except Exception as exc:  # noqa: BLE001 — defensive
        logger.warning(
            f"[auth-reset] template render failed — using hardcoded "
            f"fallback: {exc}"
        )
        return fallback_subject, fallback_html


# ══════════════════════════════════════════════════════════════════════
# Phase 34 · Task O · Feb-2026 — In-portal "Change password" endpoint
# ══════════════════════════════════════════════════════════════════════
class ChangeMyPasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/change-password")
async def change_my_password(request: Request,
                               body: ChangeMyPasswordRequest,
                               user: dict = Depends(get_current_user)):
    """Authenticated portal user updates their own password.

    Requires the current password (enforced via ``verify_password``)
    AND the same strength policy the reset flow uses. Returns 400
    with a clear message on any failure — no silent no-ops.
    """
    ip = _client_ip(request)
    if not body.current_password or not body.new_password:
        raise HTTPException(400, "Current and new password are required.")

    # Fetch WITH password_hash — ``get_current_user`` strips it.
    full = await db.users.find_one({"id": user["id"]})
    if not full or not verify_password(body.current_password,
                                        full.get("password_hash", "")):
        await _audit_auth("password_change", user.get("email", ""), ip,
                          "failure", "bad_current_password")
        raise HTTPException(400, "Current password is incorrect.")

    err = _password_policy_ok(body.new_password)
    if err:
        raise HTTPException(400, err)

    new_hash = hash_password(body.new_password)
    now = now_iso()
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": new_hash,
            "failed_login_attempts": 0,
            "lockout_until": None,
            "must_change_password_on_next_login": False,
            "password_updated_at": now,
            "password_customer_set_at": now,
        }},
    )
    # Feb-2026 · P43c correction — mirror the customer-engagement
    # signal to the customer doc (see ``_apply_new_password`` for
    # the parallel reset-flow write). Kept optional so admin-role
    # or standalone-user change-password calls don't 500.
    if user.get("role") == "customer" and user.get("customer_id"):
        try:
            await db.customers.update_one(
                {"id": user["customer_id"],
                  "tenant_id": user.get("tenant_id")},
                {"$set": {"portal_password_set_at": now}},
            )
        except Exception as e:  # pragma: no cover
            logger.warning(f"portal_password_set_at denorm skipped: {e}")
    await _audit_auth("password_change", user.get("email", ""), ip, "success")
    return {"ok": True, "message": "Password updated."}


@router.post("/admin/impersonate/{customer_id}")
async def impersonate_customer(customer_id: str,
                                tenant_id: Optional[str] = None,
                                admin: dict = Depends(require_admin)):
    """Admin obtains a customer-scoped session token to view the app exactly as the customer.
    The token carries an `act` claim identifying the admin so the session can be reverted.

    Super admins may pass `?tenant_id=X` to impersonate a customer in a different tenant.
    Regular admins are restricted to their own tenant."""
    q = {"id": customer_id}
    if admin.get("role") == "super_admin" and tenant_id:
        q["tenant_id"] = tenant_id
    else:
        # Regular admin — restrict to their own tenant
        q["tenant_id"] = admin.get("tenant_id")
    customer = await db.customers.find_one(q, {"_id": 0})
    if not customer:
        raise HTTPException(404, "Customer not found")
    cust_user_q = {"customer_id": customer_id, "role": "customer",
                   "tenant_id": customer.get("tenant_id")}
    cust_user = await db.users.find_one(cust_user_q, {"_id": 0})
    if not cust_user:
        raise HTTPException(400, "This customer has no login yet. Create a login for them first.")
    await db.audit_logs.insert_one({
        "id": new_id(),
        "tenant_id": customer.get("tenant_id"),
        "event": "impersonation_started",
        "admin_id": admin["id"], "admin_name": admin.get("name", ""),
        "admin_role": admin.get("role"),
        "target_customer_id": customer_id, "target_user_id": cust_user["id"],
        "target_tenant_id": customer.get("tenant_id"),
        "cross_tenant": admin.get("tenant_id") != customer.get("tenant_id"),
        "created_at": now_iso(),
    })
    return auth_response(cust_user, impersonator_id=admin["id"], impersonator_name=admin.get("name", "Admin"))


@router.post("/auth/revert-impersonation")
async def revert_impersonation(user: dict = Depends(get_current_user)):
    """End an impersonation session and restore the original admin session."""
    admin_id = user.get("impersonator_id")
    if not admin_id:
        raise HTTPException(403, "Not an active impersonation session")
    admin_user = await db.users.find_one(
        {"id": admin_id, "role": {"$in": ["admin", "super_admin"]}}, {"_id": 0}
    )
    if not admin_user:
        raise HTTPException(403, "Admin authorization is no longer valid")
    await db.audit_logs.insert_one({
        "id": new_id(),
        "tenant_id": user.get("tenant_id"),
        "event": "impersonation_ended",
        "admin_id": admin_id, "target_user_id": user.get("id"),
        "created_at": now_iso(),
    })
    return auth_response(admin_user)


@router.get("/admin/access-history")
async def access_history(admin: dict = Depends(require_admin),
                          all_tenants: bool = False):
    """Audit trail of admin 'view as customer' sessions.

    SEC-003 hotfix: tenant-scoped by default. Super-admin may pass
    `?all_tenants=true` to cross tenants; that access is itself logged.
    """
    tenant_id = admin.get("tenant_id")
    q: dict = {"event": {"$in": ["impersonation_started", "impersonation_ended"]}}
    role = admin.get("role")
    cross = bool(all_tenants) and role == "super_admin"
    if not cross:
        q["tenant_id"] = tenant_id
    if cross:
        try:
            await db.audit_logs.insert_one({
                "id": new_id(),
                "tenant_id": tenant_id,
                "event": "access_history_cross_tenant",
                "actor_id": admin.get("id"),
                "actor_email": admin.get("email"),
                "created_at": now_iso(),
            })
        except Exception:
            pass
    logs = await db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)
    cust_ids = list({l.get("target_customer_id") for l in logs if l.get("target_customer_id")})
    names: dict = {}
    if cust_ids:
        cust_q = {"id": {"$in": cust_ids}}
        if not cross:
            cust_q["tenant_id"] = tenant_id
        async for c in db.customers.find(cust_q, {"_id": 0, "id": 1, "name": 1}):
            names[c["id"]] = c.get("name", "")
    for l in logs:
        l["customer_name"] = names.get(l.get("target_customer_id"), "")
    return logs



