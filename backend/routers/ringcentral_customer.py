"""Phase 54 · Customer-scoped RingCentral read endpoints + admin
unmatched queue. Split out of the main `ringcentral` router because
these live under `/api/customers/{id}/...` and `/api/admin/...`."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from config import db
from utils import get_current_user, require_admin, not_deleted_filter as _nd
from routers.tenants import get_current_tenant

router = APIRouter(tags=["ringcentral_customer"])


async def _customer_scoped(cid: str, tenant: dict, user: dict) -> dict:
    # Feb-2026 · P30 nested soft-delete audit — parent-customer guard.
    # Mirrors the P25 read-filter behavior: soft-deleted customers 404
    # (not 403) so techs / clients with a cached id can't fetch the
    # customer's comms after deletion.
    cust = await db.customers.find_one(
        {"id": cid, "tenant_id": tenant["id"], **_nd()}, {"_id": 0},
    )
    if not cust:
        raise HTTPException(404, "customer not found")
    return cust


@router.get("/customers/{cid}/call-logs")
async def customer_call_logs(cid: str,
                                user: dict = Depends(get_current_user),
                                tenant: dict = Depends(get_current_tenant)):
    await _customer_scoped(cid, tenant, user)
    rows = await db.call_logs.find(
        {"customer_id": cid}, {"_id": 0},
    ).sort("started_at", -1).to_list(200)
    return {"items": rows, "count": len(rows)}


@router.get("/customers/{cid}/voicemails")
async def customer_voicemails(cid: str,
                                 user: dict = Depends(get_current_user),
                                 tenant: dict = Depends(get_current_tenant)):
    await _customer_scoped(cid, tenant, user)
    rows = await db.voicemails.find(
        {"matched_customer_id": cid}, {"_id": 0},
    ).sort("received_at", -1).to_list(200)
    return {"items": rows, "count": len(rows)}


@router.get("/customers/{cid}/faxes")
async def customer_faxes(cid: str,
                           user: dict = Depends(get_current_user),
                           tenant: dict = Depends(get_current_tenant)):
    await _customer_scoped(cid, tenant, user)
    rows = await db.faxes.find(
        {"matched_customer_id": cid}, {"_id": 0},
    ).sort("received_at", -1).to_list(200)
    return {"items": rows, "count": len(rows)}


@router.get("/customers/{cid}/sms-threads")
async def customer_sms_threads(cid: str,
                                  user: dict = Depends(get_current_user),
                                  tenant: dict = Depends(get_current_tenant)):
    """Unified inbound + outbound thread for one customer."""
    await _customer_scoped(cid, tenant, user)
    rows = await db.sms_messages.find(
        {"customer_id": cid}, {"_id": 0},
    ).sort("sent_at", 1).to_list(500)
    return {"messages": rows, "count": len(rows)}


@router.get("/admin/unmatched-communications")
async def unmatched_communications(user: dict = Depends(require_admin),
                                       tenant: dict = Depends(get_current_tenant)):
    """Admin queue — calls / faxes / voicemails whose sender phone
    didn't match any customer. Techs use this to attach + create
    customers on the fly."""
    calls = await db.unmatched_calls.find(
        {"resolved": {"$ne": True}}, {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    faxes = await db.unmatched_faxes.find({}, {"_id": 0}).sort("received_at", -1).to_list(200)
    voicemails = await db.voicemails.find(
        {"matched_customer_id": None}, {"_id": 0},
    ).sort("received_at", -1).to_list(200)
    return {
        "calls": calls, "faxes": faxes, "voicemails": voicemails,
        "total": len(calls) + len(faxes) + len(voicemails),
    }
