"""Phase 15A — NPS / CSAT customer satisfaction loop.

- Admin can trigger a survey for a completed job (or auto-schedule 24h out).
- Customer submits via magic-link (no auth).
- Detractor (0-6) → high-priority task + admin notification.
- Promoter (9-10) → enroll in Review Request sequence.
- Passive (7-8) → log only.
"""
import secrets
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from config import db, logger, APP_PUBLIC_URL, RESEND_API_KEY, EMAIL_FROM
from utils import (
    now_iso, new_id, require_admin, get_current_user, notify_customer,
    create_staff_notification, send_sms,
)
from routers.realtime import bus

router = APIRouter()


def _mk_token() -> str:
    return secrets.token_urlsafe(24)


def _survey_url(token: str) -> str:
    base = (APP_PUBLIC_URL or "").rstrip("/")
    return f"{base}/csat/{token}"


async def _send_survey_email(customer: dict, url: str) -> bool:
    if not RESEND_API_KEY or not customer.get("email"):
        return False
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": EMAIL_FROM or "onboarding@resend.dev",
            "to": [customer["email"]],
            "subject": "How did we do?",
            "html": (
                f"<p>Hi {customer.get('name','')},</p>"
                f"<p>Thanks for choosing AquaTerra. A quick 30-second survey helps us serve you better.</p>"
                f"<p><a href='{url}' style='background:#0284C7;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;'>Rate your service</a></p>"
            ),
        })
        return True
    except Exception as e:
        logger.warning(f"CSAT email failed: {e}")
        return False


async def _dispatch_survey(job: dict, channel: str = "email") -> dict:
    """Idempotent per (job_id): if a survey already exists for this job, return it."""
    existing = await db.csat_surveys.find_one({"job_id": job["id"]}, {"_id": 0})
    if existing:
        return existing
    cust = await db.customers.find_one({"id": job.get("customer_id")}, {"_id": 0}) or {}
    if not cust:
        raise HTTPException(400, "Job has no linked customer")
    token = _mk_token()
    doc = {
        "id": new_id(),
        "token": token,
        "customer_id": job.get("customer_id"),
        "customer_name": cust.get("name", ""),
        "job_id": job["id"],
        "job_title": job.get("title") or job.get("service_type", ""),
        "channel": channel,
        "nps_score": None,
        "csat_score": None,
        "comment": "",
        "sent_at": now_iso(),
        "responded_at": None,
        "created_at": now_iso(),
    }
    await db.csat_surveys.insert_one(doc)
    doc.pop("_id", None)
    url = _survey_url(token)
    emailed = False
    if channel == "email":
        emailed = await _send_survey_email(cust, url)
    elif channel == "sms" and cust.get("phone"):
        send_sms(cust["phone"], f"Hi {cust.get('name','')}, how did we do? Rate your visit: {url}")
        emailed = True
    doc["url"] = url
    doc["emailed"] = emailed
    return doc


class SendSurveyIn(BaseModel):
    channel: str = "email"


@router.post("/csat/send/{job_id}")
async def send_csat(job_id: str, body: Optional[SendSurveyIn] = None,
                    admin: dict = Depends(require_admin)):
    job = await db.jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(404, "Job not found")
    channel = (body.channel if body else "email") or "email"
    doc = await _dispatch_survey(job, channel=channel)
    return {"ok": True, "survey": doc}


@router.get("/csat")
async def list_csat(admin: dict = Depends(require_admin),
                    min_nps: Optional[int] = Query(None),
                    max_nps: Optional[int] = Query(None),
                    channel: Optional[str] = Query(None)):
    q: dict = {}
    if channel:
        q["channel"] = channel
    if min_nps is not None:
        q.setdefault("nps_score", {})["$gte"] = min_nps
    if max_nps is not None:
        q.setdefault("nps_score", {})["$lte"] = max_nps
    rows = await db.csat_surveys.find(q, {"_id": 0}).sort("sent_at", -1).to_list(500)
    # Aggregate summary
    responded = [r for r in rows if r.get("nps_score") is not None]
    if responded:
        promoters = sum(1 for r in responded if r["nps_score"] >= 9)
        detractors = sum(1 for r in responded if r["nps_score"] <= 6)
        passives = len(responded) - promoters - detractors
        nps = round(((promoters - detractors) / len(responded)) * 100)
        csat_avg = round(
            sum(r.get("csat_score") or 0 for r in responded if r.get("csat_score"))
            / max(1, sum(1 for r in responded if r.get("csat_score"))),
            2,
        )
    else:
        promoters = detractors = passives = 0
        nps = 0
        csat_avg = 0.0
    summary = {
        "nps_score": nps,
        "csat_avg": csat_avg,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "total_sent": len(rows),
        "total_responded": len(responded),
        "response_rate": round(len(responded) / len(rows) * 100, 1) if rows else 0.0,
    }
    return {"summary": summary, "surveys": rows}


@router.get("/csat/{sid}")
async def get_csat(sid: str, admin: dict = Depends(require_admin)):
    doc = await db.csat_surveys.find_one({"id": sid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Survey not found")
    doc["url"] = _survey_url(doc["token"])
    return doc


# ─── Public magic-link ─────────────────────────────────────────────────────
@router.get("/public/csat/{token}")
async def public_get_csat(token: str):
    doc = await db.csat_surveys.find_one({"token": token}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Survey not found")
    return {
        "id": doc["id"],
        "customer_name": doc.get("customer_name", ""),
        "job_title": doc.get("job_title", ""),
        "responded_at": doc.get("responded_at"),
        "nps_score": doc.get("nps_score"),
        "csat_score": doc.get("csat_score"),
        "comment": doc.get("comment", ""),
    }


class SubmitCsatIn(BaseModel):
    nps_score: int = Field(..., ge=0, le=10)
    csat_score: int = Field(..., ge=1, le=5)
    comment: Optional[str] = ""


@router.post("/public/csat/{token}/submit")
async def public_submit_csat(token: str, body: SubmitCsatIn):
    doc = await db.csat_surveys.find_one({"token": token}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Survey not found")
    if doc.get("responded_at"):
        raise HTTPException(400, "Already submitted")

    upd = {
        "nps_score": body.nps_score,
        "csat_score": body.csat_score,
        "comment": (body.comment or "").strip(),
        "responded_at": now_iso(),
    }
    await db.csat_surveys.update_one({"id": doc["id"]}, {"$set": upd})

    # Route promoter / passive / detractor.
    if body.nps_score >= 9:
        await _route_promoter(doc)
    elif body.nps_score <= 6:
        await _route_detractor({**doc, **upd})
    # else: passive — log only via activity_log below
    try:
        await db.activity_log.insert_one({
            "id": new_id(),
            "kind": "csat_response",
            "customer_id": doc.get("customer_id"),
            "job_id": doc.get("job_id"),
            "nps_score": body.nps_score,
            "csat_score": body.csat_score,
            "comment": upd["comment"],
            "created_at": now_iso(),
        })
    except Exception as e:
        logger.warning(f"activity_log write failed: {e}")

    return {"ok": True, "thanks": True}


async def _route_promoter(survey: dict) -> None:
    """Promoter → enroll in Review Request sequence (if seeded) + activity log."""
    seq = await db.sequences.find_one({"slug": "review-request"}, {"_id": 0})
    if seq and survey.get("customer_id"):
        # Idempotent: skip if already actively enrolled
        existing = await db.sequence_enrollments.find_one({
            "sequence_id": seq["id"],
            "customer_id": survey["customer_id"],
            "status": {"$in": ["active", "paused"]},
        }, {"_id": 0})
        if not existing:
            enrollment = {
                "id": new_id(),
                "sequence_id": seq["id"],
                "customer_id": survey["customer_id"],
                "status": "active",
                "current_step": 0,
                "next_action_at": now_iso(),
                "source": "csat-promoter",
                "created_at": now_iso(),
            }
            await db.sequence_enrollments.insert_one(enrollment)


async def _route_detractor(survey: dict) -> None:
    """Detractor → high-priority task + admin notification + realtime push."""
    cust_name = survey.get("customer_name", "customer")
    excerpt = (survey.get("comment") or "")[:200]
    task = {
        "id": new_id(),
        "title": f"Negative feedback from {cust_name}",
        "description": f"NPS {survey.get('nps_score')}. Comment: {excerpt or '(no comment)'}",
        "priority": "high",
        "status": "open",
        "source": "csat-detractor",
        "assigned_to": None,  # left null so first available admin can claim
        "customer_id": survey.get("customer_id"),
        "job_id": survey.get("job_id"),
        "created_at": now_iso(),
    }
    await db.tasks.insert_one(task)
    await create_staff_notification(
        "Negative feedback received",
        f"NPS {survey.get('nps_score')} from {cust_name}. Review and follow up.",
        job_id=survey.get("job_id"),
    )
    # Realtime fan-out to all admins.
    admins = await db.users.find({"role": "admin"}, {"_id": 0, "id": 1}).to_list(100)
    for a in admins:
        await bus.broadcast(a["id"], {
            "type": "csat_detractor",
            "payload": {"task_id": task["id"], "customer_name": cust_name, "nps_score": survey.get("nps_score")},
        })


# ─── Auto-scheduling on job completion ─────────────────────────────────────
async def maybe_schedule_survey_for_job(job: dict) -> None:
    """Called from jobs.py when a job flips to completed. Idempotent."""
    if not job or not job.get("customer_id"):
        return
    # Respect per-customer opt-out via notification_preferences.csat_enabled === false
    cust = await db.customers.find_one({"id": job["customer_id"]}, {"_id": 0}) or {}
    prefs = cust.get("notification_preferences") or {}
    if prefs.get("csat_enabled") is False:
        return
    # Skip if a survey already exists for this job.
    exists = await db.csat_surveys.find_one({"job_id": job["id"]}, {"_id": 0})
    if exists:
        return
    scheduled_for = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    await db.csat_pending.insert_one({
        "id": new_id(),
        "job_id": job["id"],
        "customer_id": job["customer_id"],
        "channel": "email",
        "scheduled_for": scheduled_for,
        "created_at": now_iso(),
    })


async def run_csat_dispatch_tick() -> None:
    """Cron: process any pending CSAT sends whose scheduled_for <= now."""
    now = datetime.now(timezone.utc).isoformat()
    pending = await db.csat_pending.find({"scheduled_for": {"$lte": now}}, {"_id": 0}).to_list(200)
    for p in pending:
        try:
            job = await db.jobs.find_one({"id": p["job_id"]}, {"_id": 0})
            if job:
                await _dispatch_survey(job, channel=p.get("channel", "email"))
        except Exception as e:
            logger.warning(f"CSAT dispatch failed for {p.get('job_id')}: {e}")
        finally:
            await db.csat_pending.delete_one({"id": p["id"]})
