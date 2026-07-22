from datetime import datetime, timezone, timedelta

from config import db, logger
from utils import now_iso, new_id, hash_password, verify_password


import os as _os


DEMO_EMAILS_FOR_AUTOHEAL = [
    "super@aquaterra.com",
    "admin@aquaterra.com",
    "mike@aquaterra.com",
    "carlos@aquaterra.com",
    "customer@aquaterra.com",
]


async def auto_heal_demo_passwords_if_needed():
    """Deliverable (d) · Auto-heal demo-user password drift on startup.

    Rehashes any of the 5 seeded demo accounts whose stored
    ``password_hash`` no longer verifies against the plaintext
    ``password123``. Clears ``failed_login_attempts`` + ``lockout_until``
    while it's at that row. Never rotates to a random token — this only
    heals TO the ``password123`` demo baseline. Use
    ``scripts/rotate_demo_passwords.py`` explicitly for a security
    review's random-token state.

    Gating
    ------
    - ``APP_ENV=production`` → skipped entirely (info log line).
    - ``DEMO_AUTOHEAL=0`` → skipped (info log line).
    - Otherwise runs (default ``DEMO_AUTOHEAL=1`` behavior).
    - The five demo user rows do not have to exist. Missing rows are
      silently skipped so this is safe to call under
      ``SEED_DEMO_USERS=0`` production posture.

    Idempotent and safe to call on every startup.
    """
    if _os.environ.get("APP_ENV", "").lower() == "production":
        logger.info("auto_heal_demo_passwords: skipped (APP_ENV=production)")
        return
    if _os.environ.get("DEMO_AUTOHEAL", "1") != "1":
        logger.info("auto_heal_demo_passwords: skipped (DEMO_AUTOHEAL != 1)")
        return
    healed: list[str] = []
    already_good: list[str] = []
    missing: list[str] = []
    default_pw = "password123"
    for email in DEMO_EMAILS_FOR_AUTOHEAL:
        row = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "password_hash": 1})
        if not row:
            missing.append(email)
            continue
        stored = row.get("password_hash") or ""
        try:
            ok = bool(stored) and verify_password(default_pw, stored)
        except Exception:
            ok = False
        if ok:
            already_good.append(email)
            continue
        await db.users.update_one(
            {"id": row["id"]},
            {"$set": {
                "password_hash": hash_password(default_pw),
                "failed_login_attempts": 0,
                "lockout_until": None,
                "active": True,
            }},
        )
        healed.append(email)
        logger.warning(f"auto_heal_demo_passwords: healed {email} back to password123")
    if healed:
        logger.warning(
            f"auto_heal_demo_passwords: healed {len(healed)}/{len(DEMO_EMAILS_FOR_AUTOHEAL)} demo users. "
            f"Missing rows: {missing or 'none'}")
    else:
        logger.info(
            f"auto_heal_demo_passwords: all {len(already_good)} present demo users already authenticate with default. "
            f"Missing rows: {missing or 'none'}")


async def seed_landscaping_user():
    # SEC-001 hotfix — gate on SEED_DEMO_USERS=1 (default off).
    if _os.environ.get("SEED_DEMO_USERS", "0") != "1":
        from config import logger as _lg
        _lg.warning("SEED_DEMO_USERS=0 — skipping seed.py demo users. Set the flag to seed dev/preview.")
        return
    """Phase 46 — Idempotent seed of a landscaping-department user so the
    landscaping time clock (backend gated by `department == 'landscaping'`)
    can be exercised end-to-end. Runs on every startup via server.py."""
    from utils import hash_password  # local import — module-level already imports
    email = "landscaper@aquaterra.com"
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    # Ensure the account exists and its department is set correctly.
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    tenant_id = tenant["id"] if tenant else None
    if existing:
        upd = {}
        if (existing.get("department") or "").lower() != "landscaping":
            upd["department"] = "landscaping"
        if existing.get("role") not in ("technician", "landscaping_technician"):
            upd["role"] = "technician"
        if tenant_id and existing.get("tenant_id") != tenant_id:
            upd["tenant_id"] = tenant_id
        if not existing.get("active", True):
            upd["active"] = True
        if upd:
            await db.users.update_one({"id": existing["id"]}, {"$set": upd})
        return
    tech_id = new_id()
    await db.technicians.insert_one({
        "id": tech_id, "name": "Luis Marquez", "email": email,
        "phone": "480-555-0166", "specialty": "Landscaping",
        "avatar": "", "active": True, "created_at": now_iso(),
        **({"tenant_id": tenant_id} if tenant_id else {}),
    })
    await db.users.insert_one({
        "id": new_id(),
        "name": "Luis Marquez",
        "email": email,
        "password_hash": hash_password("password123"),
        "role": "technician",
        "department": "landscaping",
        "avatar": "",
        "technician_id": tech_id,
        "active": True,
        "created_at": now_iso(),
        **({"tenant_id": tenant_id} if tenant_id else {}),
    })


async def seed_landscape_tech_carlos():
    """SEC-001 followup · Idempotent seed of `carlos@aquaterra.com`, the
    named landscape-department technician the demo tenant references in
    training, onboarding, and route-assignment fixtures.

    Gated on ``SEED_DEMO_USERS=1`` (default off) — mirrors
    ``seed_landscaping_user``'s security posture. Mirrors mike's row layout
    (technicians row + users row) with the pool ``department`` flipped to
    ``landscaping``. Password is a temporary placeholder that
    ``scripts/rotate_demo_passwords.py`` overwrites via its ``--only``
    filter on first invocation."""
    if _os.environ.get("SEED_DEMO_USERS", "0") != "1":
        from config import logger as _lg
        _lg.warning("SEED_DEMO_USERS=0 — skipping seed.py demo users. Set the flag to seed dev/preview.")
        return
    from utils import hash_password
    email = "carlos@aquaterra.com"
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    tenant_id = tenant["id"] if tenant else None
    existing = await db.users.find_one({"email": email}, {"_id": 0})
    if existing:
        upd = {}
        if (existing.get("department") or "").lower() != "landscaping":
            upd["department"] = "landscaping"
        if existing.get("role") != "technician":
            upd["role"] = "technician"
        if tenant_id and existing.get("tenant_id") != tenant_id:
            upd["tenant_id"] = tenant_id
        if not existing.get("active", True):
            upd["active"] = True
        if upd:
            await db.users.update_one({"id": existing["id"]}, {"$set": upd})
        return
    tech_id = new_id()
    await db.technicians.insert_one({
        "id": tech_id, "name": "Carlos Rivera", "email": email,
        "phone": "480-555-0158", "specialty": "Landscaping",
        "avatar": "", "active": True, "created_at": now_iso(),
        **({"tenant_id": tenant_id} if tenant_id else {}),
    })
    await db.users.insert_one({
        "id": new_id(),
        "name": "Carlos Rivera",
        "email": email,
        "password_hash": hash_password("password123"),
        "role": "technician",
        "department": "landscaping",
        "avatar": "",
        "technician_id": tech_id,
        "active": True,
        "created_at": now_iso(),
        **({"tenant_id": tenant_id} if tenant_id else {}),
    })


# ─────────────────────────────────────────────────────────────────────
# Phase 5A follow-up · Feb 2026 — idempotent test-account alignment.
#
# `mike@aquaterra.com` is documented in /app/memory/test_credentials.md
# as the POOL tech, and `carlos@aquaterra.com` as the LANDSCAPE tech.
# Some deployments drifted (Mike ended up flagged as landscaping when
# an earlier tenant migration mis-set the department). This function
# patches only those two users on every boot, non-destructively.
# ─────────────────────────────────────────────────────────────────────
async def align_demo_tech_departments():
    """Idempotent. Ensures ``mike@aquaterra.com`` sits in the ``pool``
    department and ``carlos@aquaterra.com`` sits in ``landscaping``.
    No-ops for any other user; safe to call on every boot."""
    from config import logger as _lg
    fixes = 0
    _MIKE_DEPT = "pool"
    _CARLOS_DEPT = "landscaping"

    async def _fix(email: str, want: str):
        nonlocal fixes
        row = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "department": 1})
        if not row:
            return
        cur = (row.get("department") or "").lower()
        if cur == want:
            return
        await db.users.update_one(
            {"id": row["id"]},
            {"$set": {"department": want}},
        )
        # Mirror onto the linked technicians doc so schedule / checklist
        # kind derivation stays consistent (see routers/jobs.py).
        tech_email = email
        await db.technicians.update_many(
            {"email": tech_email},
            {"$set": {"department": want}},
        )
        fixes += 1
        _lg.info(f"[phase5a] realigned {email}: department {cur or '(unset)'} → {want}")

    await _fix("mike@aquaterra.com",   _MIKE_DEPT)
    await _fix("carlos@aquaterra.com", _CARLOS_DEPT)
    return {"fixed": fixes}


async def seed_manager_user():
    """Phase 5A follow-up · Feb 2026 — idempotent seed of the
    ``manager@aquaterra.com`` role-gate testing account.

    Password: ``password123`` (matches every other demo account; rotated
    together via scripts/rotate_demo_passwords.py). Only inserts if the
    email is absent — never overwrites the row. Belongs to the same
    aquaterra tenant as the other seeded users."""
    if _os.environ.get("SEED_DEMO_USERS", "0") != "1":
        from config import logger as _lg
        _lg.warning("SEED_DEMO_USERS=0 — skipping manager seed. Set the flag to seed dev/preview.")
        return {"created": False, "reason": "seed_demo_users_disabled"}
    from utils import hash_password
    email = "manager@aquaterra.com"
    existing = await db.users.find_one({"email": email}, {"_id": 0, "id": 1})
    if existing:
        return {"created": False, "reason": "already_seeded"}
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    tenant_id = tenant["id"] if tenant else None
    doc = {
        "id": new_id(),
        "name": "Morgan Manager",
        "email": email,
        "password_hash": hash_password("password123"),
        "role": "manager",
        "avatar": "",
        "technician_id": None,
        "active": True,
        "created_at": now_iso(),
    }
    if tenant_id:
        doc["tenant_id"] = tenant_id
    await db.users.insert_one(doc)
    from config import logger as _lg
    _lg.info("[phase5a] seeded manager@aquaterra.com (role=manager)")
    return {"created": True, "email": email}


async def seed():
    if await db.users.count_documents({}) > 0:
        return
    logger.info("Seeding demo data...")
    av1 = "https://images.unsplash.com/photo-1494790108377-be9c29b29330?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2Njl8MHwxfHNlYXJjaHwyfHxwcm9mZXNzaW9uYWwlMjBwb3J0cmFpdCUyMGZhY2V8ZW58MHx8fHwxNzgzMzc2NTA1fDA&ixlib=rb-4.1.0&q=85&w=200"
    av2 = "https://images.pexels.com/photos/24430436/pexels-photo-24430436.jpeg?auto=compress&cs=tinysrgb&dpr=2&w=200"

    tech1_id, tech2_id = new_id(), new_id()
    techs = [
        {"id": tech1_id, "name": "Mike Rivera", "email": "mike@aquaterra.com", "phone": "480-555-0142",
         "specialty": "Pool Maintenance", "avatar": av1, "active": True, "created_at": now_iso()},
        {"id": tech2_id, "name": "Sara Nguyen", "email": "sara@aquaterra.com", "phone": "480-555-0177",
         "specialty": "Landscaping", "avatar": av2, "active": True, "created_at": now_iso()},
    ]
    await db.technicians.insert_many(techs)

    users = [
        {"id": new_id(), "name": "Alex Admin", "email": "admin@aquaterra.com",
         "password_hash": hash_password("password123"), "role": "admin", "avatar": "", "technician_id": None},
        {"id": new_id(), "name": "Mike Rivera", "email": "mike@aquaterra.com",
         "password_hash": hash_password("password123"), "role": "technician", "avatar": av1, "technician_id": tech1_id},
    ]
    await db.users.insert_many(users)

    house = "https://images.unsplash.com/photo-1777106322601-578dc9213ace?crop=entropy&cs=srgb&fm=jpg&ixid=M3w3NTY2NzZ8MHwxfHNlYXJjaHwxfHxzdWJ1cmJhbiUyMG1vZGVybiUyMGhvdXNlJTIwZXh0ZXJpb3J8ZW58MHx8fHwxNzgzMzc2NTA1fDA&ixlib=rb-4.1.0&q=85&w=800"
    customers = [
        {"id": new_id(), "name": "Jennifer Carson", "email": "jen.carson@gmail.com", "phone": "480-555-0101",
         "address": "12 Vistancia Blvd, Peoria, AZ", "notes": "Gate code 4412. Two dogs.", "created_at": now_iso()},
        {"id": new_id(), "name": "Robert Blake", "email": "rblake@outlook.com", "phone": "480-555-0102",
         "address": "88 Desert Vista Dr, Peoria, AZ", "notes": "Prefers morning service.", "created_at": now_iso()},
        {"id": new_id(), "name": "Maria Gomez", "email": "mgomez@yahoo.com", "phone": "480-555-0103",
         "address": "45 Palm Ridge Ct, Peoria, AZ", "notes": "Saltwater pool.", "created_at": now_iso()},
        {"id": new_id(), "name": "The Whitmore HOA", "email": "hoa@whitmore.org", "phone": "480-555-0104",
         "address": "Whitmore Community Center, Peoria, AZ", "notes": "Commercial account.", "created_at": now_iso()},
    ]
    await db.customers.insert_many(customers)

    # Demo customer login (linked to Jennifer Carson)
    await db.users.insert_one({
        "id": new_id(), "name": customers[0]["name"], "email": "customer@aquaterra.com",
        "password_hash": hash_password("password123"), "role": "customer",
        "avatar": "", "technician_id": None, "customer_id": customers[0]["id"],
    })
    await db.customers.update_one(
        {"id": customers[0]["id"]}, {"$set": {"email": "customer@aquaterra.com", "has_login": True}}
    )

    today = datetime.now(timezone.utc)
    def d(offset):
        return (today + timedelta(days=offset)).date().isoformat()

    jobs = [
        {"id": new_id(), "title": "Weekly Pool Cleaning", "customer_id": customers[0]["id"], "customer_name": customers[0]["name"],
         "technician_id": tech1_id, "technician_name": "Mike Rivera", "technician_avatar": av1,
         "address": customers[0]["address"], "service_type": "Pool Cleaning", "scheduled_date": d(0),
         "notes": "Check chlorine levels.", "price": 120.0, "status": "active", "created_at": now_iso()},
        {"id": new_id(), "title": "Filter Replacement", "customer_id": customers[1]["id"], "customer_name": customers[1]["name"],
         "technician_id": tech1_id, "technician_name": "Mike Rivera", "technician_avatar": av1,
         "address": customers[1]["address"], "service_type": "Repair", "scheduled_date": d(1),
         "notes": "Bring DE filter cartridge.", "price": 340.0, "status": "pending", "created_at": now_iso()},
        {"id": new_id(), "title": "Landscape Trim & Cleanup", "customer_id": customers[2]["id"], "customer_name": customers[2]["name"],
         "technician_id": tech2_id, "technician_name": "Sara Nguyen", "technician_avatar": av2,
         "address": customers[2]["address"], "service_type": "Landscaping", "scheduled_date": d(2),
         "notes": "Trim hedges along back wall.", "price": 260.0, "status": "pending", "created_at": now_iso()},
        {"id": new_id(), "title": "Monthly Pool Service", "customer_id": customers[3]["id"], "customer_name": customers[3]["name"],
         "technician_id": tech2_id, "technician_name": "Sara Nguyen", "technician_avatar": av2,
         "address": customers[3]["address"], "service_type": "Pool Cleaning", "scheduled_date": d(-3),
         "notes": "Completed, all clear.", "price": 480.0, "status": "completed", "created_at": now_iso()},
        {"id": new_id(), "title": "Pump Inspection", "customer_id": customers[0]["id"], "customer_name": customers[0]["name"],
         "technician_id": tech1_id, "technician_name": "Mike Rivera", "technician_avatar": av1,
         "address": customers[0]["address"], "service_type": "Inspection", "scheduled_date": d(-5),
         "notes": "Pump running normally.", "price": 90.0, "status": "completed", "created_at": now_iso()},
    ]
    await db.jobs.insert_many(jobs)

    def months_ago_iso(n):
        return (today - timedelta(days=30 * n)).isoformat()

    def paid_invoice(cust, title, amount, months):
        tax = round(amount * 0.08, 2)
        return {
            "id": new_id(), "customer_id": cust["id"], "customer_name": cust["name"],
            "title": title, "doc_type": "invoice",
            "line_items": [{"description": title, "quantity": 1, "unit_price": amount}],
            "tax_rate": 8.0, "subtotal": amount, "tax": tax, "total": round(amount + tax, 2),
            "status": "accepted", "payment_status": "paid", "notes": "",
            "paid_at": months_ago_iso(months), "created_at": months_ago_iso(months),
        }

    quotes = [
        {"id": new_id(), "customer_id": customers[1]["id"], "customer_name": customers[1]["name"],
         "title": "Filter System Upgrade", "doc_type": "quote",
         "line_items": [{"description": "DE Filter Cartridge", "quantity": 1, "unit_price": 220.0},
                        {"description": "Labor", "quantity": 2, "unit_price": 60.0}],
         "tax_rate": 8.0, "subtotal": 340.0, "tax": 27.2, "total": 367.2,
         "status": "sent", "payment_status": "unpaid", "notes": "", "created_at": now_iso()},
        {"id": new_id(), "customer_id": customers[3]["id"], "customer_name": customers[3]["name"],
         "title": "Monthly Pool Service", "doc_type": "invoice",
         "line_items": [{"description": "Monthly maintenance", "quantity": 1, "unit_price": 480.0}],
         "tax_rate": 8.0, "subtotal": 480.0, "tax": 38.4, "total": 518.4,
         "status": "accepted", "payment_status": "paid", "notes": "", "paid_at": now_iso(), "created_at": now_iso()},
        {"id": new_id(), "customer_id": customers[0]["id"], "customer_name": customers[0]["name"],
         "title": "Weekly Service", "doc_type": "invoice",
         "line_items": [{"description": "Weekly cleaning x4", "quantity": 4, "unit_price": 120.0}],
         "tax_rate": 8.0, "subtotal": 480.0, "tax": 38.4, "total": 518.4,
         "status": "sent", "payment_status": "unpaid", "notes": "", "created_at": now_iso()},
        # Historical paid invoices to populate the 6-month revenue trend
        paid_invoice(customers[0], "Monthly Service", 420.0, 1),
        paid_invoice(customers[2], "Landscape Package", 610.0, 2),
        paid_invoice(customers[1], "Pool Repair", 380.0, 3),
        paid_invoice(customers[3], "Commercial Service", 540.0, 4),
        paid_invoice(customers[0], "Pool Opening", 300.0, 5),
    ]
    await db.quotes.insert_many(quotes)
    logger.info("Seed complete.")


async def seed_extras():
    # Always keep at least one unpaid invoice for the demo customer so the
    # admin Payments widget's "Awaiting payment" list is populated in demos.
    demo = (await db.customers.find_one({"email": "customer@aquaterra.com"}, {"_id": 0})
            or await db.customers.find_one({}, {"_id": 0}))
    if demo:
        has_unpaid = await db.quotes.find_one(
            {"customer_id": demo["id"], "doc_type": "invoice", "payment_status": "unpaid"}
        )
        if not has_unpaid:
            amount = 149.0
            await db.quotes.insert_one({
                "id": new_id(), "customer_id": demo["id"], "customer_name": demo["name"],
                "title": "Monthly Pool Service", "doc_type": "invoice",
                "line_items": [{"description": "Monthly pool maintenance", "quantity": 1, "unit_price": amount}],
                "tax_rate": 0.0, "subtotal": amount, "tax": 0.0, "total": amount,
                "status": "sent", "payment_status": "unpaid", "notes": "", "created_at": now_iso(),
            })
        # Ensure the demo customer also has a landscaping job so the portal shows
        # a landscaping checklist (in addition to their pool jobs).
        has_landscaping = await db.jobs.find_one(
            {"customer_id": demo["id"], "service_type": {"$regex": "landscap", "$options": "i"}}
        )
        if not has_landscaping:
            tech = await db.technicians.find_one({}, {"_id": 0})
            await db.jobs.insert_one({
                "id": new_id(), "title": "Backyard Landscaping Service", "service_type": "Landscaping",
                "customer_id": demo["id"], "customer_name": demo["name"],
                "technician_id": (tech["id"] if tech else None),
                "technician_name": (tech["name"] if tech else None),
                "status": "pending", "scheduled_date": now_iso(), "price": 220.0,
                "address": demo.get("address", ""), "notes": "Monthly landscaping maintenance.",
                "photos": [], "created_at": now_iso(),
            })
    if await db.leads.count_documents({}) == 0:
        leads = [
            {"id": new_id(), "name": "Tom Harker", "phone": "480-555-0199", "email": "tom.h@gmail.com", "source": "Website", "status": "new", "notes": "Wants weekly cleaning quote.", "est_value": 480.0, "address": "12345 N 75th Ave, Peoria, AZ 85383", "lat": 33.7012, "lng": -112.2270, "created_at": now_iso()},
            {"id": new_id(), "name": "Diana Cruz", "phone": "480-555-0155", "email": "dcruz@gmail.com", "source": "Referral", "status": "contacted", "notes": "New pool build, needs startup.", "est_value": 1200.0, "address": "27890 N 67th Dr, Peoria, AZ 85383", "lat": 33.7185, "lng": -112.2101, "created_at": now_iso()},
            {"id": new_id(), "name": "Kevin Lee", "phone": "480-555-0133", "email": "klee@gmail.com", "source": "Google Ads", "status": "quoted", "notes": "Sent quote for equipment upgrade.", "est_value": 860.0, "address": "8921 W Deer Valley Rd, Peoria, AZ 85383", "lat": 33.6829, "lng": -112.2445, "created_at": now_iso()},
        ]
        await db.leads.insert_many(leads)
    if await db.items.count_documents({}) == 0:
        items = [
            {"id": new_id(), "name": "Weekly Pool Cleaning", "category": "Service", "unit": "visit", "unit_price": 120.0, "taxable": True, "created_at": now_iso()},
            {"id": new_id(), "name": "Monthly Maintenance", "category": "Service", "unit": "month", "unit_price": 480.0, "taxable": True, "created_at": now_iso()},
            {"id": new_id(), "name": "DE Filter Cartridge", "category": "Part", "unit": "each", "unit_price": 220.0, "taxable": True, "created_at": now_iso()},
            {"id": new_id(), "name": "Chlorine Tablets (25 lb)", "category": "Chemical", "unit": "bucket", "unit_price": 89.0, "taxable": True, "created_at": now_iso()},
            {"id": new_id(), "name": "Labor", "category": "Service", "unit": "hour", "unit_price": 60.0, "taxable": False, "created_at": now_iso()},
            {"id": new_id(), "name": "Pool Salt (40 lb)", "category": "Chemical", "unit": "bag", "unit_price": 12.0, "taxable": True, "created_at": now_iso()},
        ]
        await db.items.insert_many(items)
    # Auto-billing plans + equipment repairs (seed once)
    if await db.billing_plans.count_documents({}) == 0:
        custs = await db.customers.find({}, {"_id": 0}).to_list(10)
        if custs:
            def nr(days):
                return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
            plans = [
                {"id": new_id(), "customer_id": custs[0]["id"], "customer_name": custs[0]["name"], "service": "Weekly Pool Cleaning", "frequency": "weekly", "amount": 120.0, "next_run": nr(3), "active": True, "created_at": now_iso()},
                {"id": new_id(), "customer_id": custs[3]["id"] if len(custs) > 3 else custs[0]["id"], "customer_name": (custs[3]["name"] if len(custs) > 3 else custs[0]["name"]), "service": "Monthly Commercial Service", "frequency": "monthly", "amount": 480.0, "next_run": nr(12), "active": True, "created_at": now_iso()},
                {"id": new_id(), "customer_id": custs[2]["id"] if len(custs) > 2 else custs[0]["id"], "customer_name": (custs[2]["name"] if len(custs) > 2 else custs[0]["name"]), "service": "Quarterly Landscape Package", "frequency": "quarterly", "amount": 610.0, "next_run": nr(40), "active": False, "created_at": now_iso()},
            ]
            await db.billing_plans.insert_many(plans)
    if await db.repairs.count_documents({}) == 0:
        custs = await db.customers.find({}, {"_id": 0}).to_list(10)
        techs = await db.technicians.find({}, {"_id": 0}).to_list(10)
        if custs:
            t0 = techs[0] if techs else None
            repairs = [
                {"id": new_id(), "customer_id": custs[0]["id"], "customer_name": custs[0]["name"], "equipment": "Pool Pump", "issue": "Pump motor overheating and cutting out.", "technician_id": (t0["id"] if t0 else None), "technician_name": (t0["name"] if t0 else None), "cost": 285.0, "status": "diagnosing", "created_at": now_iso()},
                {"id": new_id(), "customer_id": custs[1]["id"] if len(custs) > 1 else custs[0]["id"], "customer_name": (custs[1]["name"] if len(custs) > 1 else custs[0]["name"]), "equipment": "DE Filter", "issue": "Cracked manifold leaking DE into pool.", "technician_id": None, "technician_name": None, "cost": 0.0, "status": "awaiting_parts", "created_at": now_iso()},
                {"id": new_id(), "customer_id": custs[2]["id"] if len(custs) > 2 else custs[0]["id"], "customer_name": (custs[2]["name"] if len(custs) > 2 else custs[0]["name"]), "equipment": "Heater", "issue": "Gas heater not igniting.", "technician_id": (t0["id"] if t0 else None), "technician_name": (t0["name"] if t0 else None), "cost": 430.0, "status": "repaired", "created_at": now_iso()},
            ]
            await db.repairs.insert_many(repairs)
    # ---- Phase 5 Marketing seed ----
    if await db.forms.count_documents({}) == 0:
        f1 = {"id": new_id(), "name": "Free Pool Estimate", "description": "Landing page lead form", "fields": ["name", "email", "phone", "message"], "created_at": now_iso()}
        f2 = {"id": new_id(), "name": "Service Callback", "description": "Homepage callback widget", "fields": ["name", "phone"], "created_at": now_iso()}
        await db.forms.insert_many([f1, f2])
    if await db.automations.count_documents({}) == 0:
        autos = [
            {"id": new_id(), "name": "Welcome new leads", "trigger": "lead_created", "action": "send_welcome_sms", "active": True, "runs": 12, "created_at": now_iso()},
            {"id": new_id(), "name": "Request review after job", "trigger": "job_completed", "action": "request_review", "active": True, "runs": 34, "created_at": now_iso()},
            {"id": new_id(), "name": "Overdue invoice reminder", "trigger": "invoice_unpaid", "action": "send_reminder", "active": False, "runs": 5, "created_at": now_iso()},
        ]
        await db.automations.insert_many(autos)
    if await db.campaigns.count_documents({}) == 0:
        camps = [
            {"id": new_id(), "channel": "email", "subject": "Summer Pool Special — 15% off", "body": "Book your summer maintenance package today.", "audience": "all_customers", "status": "sent", "sent_count": 4, "sent_at": now_iso(), "created_at": now_iso()},
            {"id": new_id(), "channel": "sms", "subject": "Monsoon cleanup reminder", "body": "Storm season is here — schedule a cleanup.", "audience": "all_customers", "status": "sent", "sent_count": 4, "sent_at": now_iso(), "created_at": now_iso()},
        ]
        await db.campaigns.insert_many(camps)
    if await db.reviews.count_documents({}) == 0:
        revs = [
            {"id": new_id(), "customer_name": "Jennifer Carson", "rating": 5, "text": "Mike is fantastic — pool has never looked better!", "source": "Google", "response": "Thank you Jennifer! — Team Pool & Landscaping", "created_at": now_iso()},
            {"id": new_id(), "customer_name": "Robert Blake", "rating": 4, "text": "Reliable weekly service. Occasionally runs late.", "source": "Yelp", "response": None, "created_at": now_iso()},
            {"id": new_id(), "customer_name": "Maria Gomez", "rating": 5, "text": "Great landscaping work on our back yard.", "source": "Facebook", "response": None, "created_at": now_iso()},
        ]
        await db.reviews.insert_many(revs)
    if await db.checkins.count_documents({}) == 0:
        techs = await db.technicians.find({}, {"_id": 0}).to_list(10)
        if techs:
            t0 = techs[0]
            t1 = techs[1] if len(techs) > 1 else techs[0]
            cks = [
                {"id": new_id(), "technician_id": t0["id"], "technician_name": t0["name"], "job_id": None, "address": "12 Vistancia Blvd, Peoria, AZ", "lat": 33.7392, "lng": -112.3106, "note": "Arrived on site", "created_at": now_iso()},
                {"id": new_id(), "technician_id": t1["id"], "technician_name": t1["name"], "job_id": None, "address": "45 Palm Ridge Ct, Peoria, AZ", "lat": 33.7451, "lng": -112.3288, "note": "Started landscaping", "created_at": now_iso()},
            ]
            await db.checkins.insert_many(cks)
    if await db.rank_grid.count_documents({}) == 0:
        def g(base):
            import random
            return [[max(1, base + random.randint(-2, 3)) for _ in range(3)] for _ in range(3)]
        rg = [
            {"id": new_id(), "keyword": "pool service near me", "grid": g(2), "created_at": now_iso()},
            {"id": new_id(), "keyword": "pool cleaning Peoria AZ", "grid": g(1), "created_at": now_iso()},
            {"id": new_id(), "keyword": "landscaping Vistancia", "grid": g(5), "created_at": now_iso()},
            {"id": new_id(), "keyword": "pool repair Arizona", "grid": g(7), "created_at": now_iso()},
        ]
        await db.rank_grid.insert_many(rg)

    # Phase 4 fix: seed a pending estimate for Jennifer so the portal
    # approve/decline flow has something real to act on. Idempotent — only
    # seeds when Jennifer has zero draft/sent quotes.
    jennifer = await db.customers.find_one({"email": "jennifer@example.com"}, {"_id": 0}) \
        or await db.customers.find_one({"name": {"$regex": "^Jennifer Carson", "$options": "i"}}, {"_id": 0})
    if jennifer:
        existing = await db.quotes.count_documents({
            "customer_id": jennifer["id"],
            "doc_type": "quote",
            "status": {"$in": ["draft", "sent"]},
        })
        if existing == 0:
            from datetime import datetime, timedelta, timezone
            valid = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
            line_items = [
                {"description": "6\" tile replacement (linear ft)", "quantity": 42, "unit_price": 18.5, "category": "Pool"},
                {"description": "Grout & waterline sealant", "quantity": 1, "unit_price": 145, "category": "Pool"},
                {"description": "Labor · half day", "quantity": 4, "unit_price": 65, "category": "Pool"},
            ]
            subtotal = round(sum(li["quantity"] * li["unit_price"] for li in line_items), 2)
            tax_rate = 8.0
            tax = round(subtotal * tax_rate / 100, 2)
            await db.quotes.insert_one({
                "id": new_id(),
                "customer_id": jennifer["id"],
                "customer_name": jennifer.get("name", "Jennifer Carson"),
                "title": "Pool tile replacement estimate",
                "doc_type": "quote",
                "status": "sent",
                "decision": "pending",
                "line_items": line_items,
                "subtotal": subtotal,
                "tax_rate": tax_rate,
                "tax": tax,
                "total": round(subtotal + tax, 2),
                "valid_until": valid,
                "notes": "Waterline tile is chipped along 42 linear feet. Includes grout + sealant. Quote valid 30 days.",
                "created_at": now_iso(),
            })


# ─── Phase 16C follow-up · idempotent Mike-today jobs + gate codes ──────
async def seed_tech_today_demo():
    """Ensure Mike (tech) has 2 demo jobs assigned for TODAY so the schedule
    always shows real cards with gate codes on the preview.
    Idempotent — skips inserts when a job with the same (date, customer, tech)
    tuple already exists."""
    from datetime import datetime, timezone
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    if not tenant:
        return
    tid = tenant["id"]
    mike = await db.users.find_one({"email": "mike@aquaterra.com"})
    if not mike:
        return
    uid = mike["id"]

    # Backfill gate codes + notes on the two demo customers.
    await db.customers.update_one(
        {"tenant_id": tid, "name": "Jennifer Carson"},
        {"$set": {"gate_code": "1234#",
                  "notes": "Dog in yard — friendly. Please close pool gate behind you."}},
    )
    await db.customers.update_one(
        {"tenant_id": tid, "name": "The Whitmore HOA"},
        {"$set": {"gate_code": "0713*",
                  "notes": "Enter through south service gate. Skimmer basket in shed by pump."}},
    )

    jen = await db.customers.find_one({"tenant_id": tid, "name": "Jennifer Carson"})
    hoa = await db.customers.find_one({"tenant_id": tid, "name": "The Whitmore HOA"})

    now = datetime.now(timezone.utc)
    today_prefix = now.date().isoformat()  # "YYYY-MM-DD"

    demo_jobs = [
        {
            "customer": jen, "hour_start": 9, "hour_end_h": 10, "hour_end_m": 0,
            "service_type": "Weekly Pool Service",
            "title": "Weekly Pool Service",
        },
        {
            "customer": hoa, "hour_start": 11, "hour_end_h": 12, "hour_end_m": 30,
            "service_type": "Monthly Landscaping",
            "title": "Monthly Landscaping",
        },
    ]
    for d in demo_jobs:
        c = d["customer"]
        if not c:
            continue
        # Idempotency guard: same tech + same customer + same day already scheduled.
        existing = await db.jobs.find_one({
            "tenant_id": tid, "customer_id": c["id"],
            "technician_id": uid,
            "scheduled_date": {"$regex": f"^{today_prefix}"},
        })
        if existing:
            continue
        start_iso = now.replace(hour=d["hour_start"], minute=0, second=0, microsecond=0).isoformat()
        end_iso = now.replace(hour=d["hour_end_h"], minute=d["hour_end_m"], second=0, microsecond=0).isoformat()
        await db.jobs.insert_one({
            "id": new_id(),
            "tenant_id": tid,
            "title": d["title"],
            "service_type": d["service_type"],
            "customer_id": c["id"],
            "customer_name": c["name"],
            "address": c.get("address", ""),
            "assigned_technician_id": uid,
            "technician_id": uid,
            "assigned_to": uid,
            "technician_name": mike.get("name") or "Mike Rivera",
            "scheduled_date": start_iso,
            "scheduled_end": end_iso,
            "status": "scheduled",
            "site_lat": 33.7005, "site_lng": -112.2280,
            "created_at": now_iso(),
        })


# ─── Phase 51.0 · Prior readings seed for outlier median coverage ─────
async def seed_prior_readings():
    """Insert 2 additional prior service reports per Jennifer Carson &
    Robert Blake so `/api/service-reports/last-readings` returns
    `recent_readings` arrays of length ≥ 2 — the median check in the
    Phase 50.B submit-time recheck confirmation requires that.

    Idempotent: guarded by a marker on the customer document."""
    from datetime import datetime, timezone, timedelta
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    if not tenant:
        return
    tid = tenant["id"]
    mike = await db.users.find_one({"email": "mike@aquaterra.com"})
    if not mike:
        return

    seed_config = [
        {"customer_name": "Jennifer Carson", "days_ago": [7, 14],
         "readings": [
            {"ph": 7.5, "free_chlorine": 3.0, "combined_chlorine": 0.1,
             "total_alkalinity": 100, "cyanuric_acid": 40},
            {"ph": 7.4, "free_chlorine": 3.1, "combined_chlorine": 0.15,
             "total_alkalinity": 105, "cyanuric_acid": 42},
         ]},
        {"customer_name": "Robert Blake", "days_ago": [10, 21],
         "readings": [
            {"ph": 7.6, "free_chlorine": 2.8, "combined_chlorine": 0.2,
             "total_alkalinity": 95, "cyanuric_acid": 45},
            {"ph": 7.5, "free_chlorine": 2.9, "combined_chlorine": 0.1,
             "total_alkalinity": 100, "cyanuric_acid": 50},
         ]},
    ]
    for cfg in seed_config:
        cust = await db.customers.find_one({"tenant_id": tid, "name": cfg["customer_name"]})
        if not cust:
            continue
        if cust.get("phase51_prior_readings_seeded"):
            continue
        for i, days in enumerate(cfg["days_ago"]):
            past = datetime.now(timezone.utc) - timedelta(days=days)
            past_iso = past.date().isoformat()
            # Create a completed job for that date (idempotency guard is
            # the customer flag above — we only run this once per customer).
            job_id = new_id()
            await db.jobs.insert_one({
                "id": job_id, "tenant_id": tid, "title": "Weekly Pool Service (prior)",
                "service_type": "Weekly Pool Service",
                "customer_id": cust["id"], "customer_name": cust["name"],
                "address": cust.get("address", ""),
                "technician_id": mike["id"], "technician_name": mike.get("name") or "Mike Rivera",
                "scheduled_date": past_iso, "status": "completed",
                "created_at": now_iso(), "price": 120,
                "service_report_submitted_at": past.isoformat(),
            })
            # Build the reading list in the shape stored by service_reports.
            readings = cfg["readings"][i]
            reading_rows = [
                {"key": k, "name": k.replace("_", " ").title(),
                  "value": v, "unit": "ppm" if k != "ph" else ""}
                for k, v in readings.items()
            ]
            await db.service_reports.insert_one({
                "id": new_id(), "tenant_id": tid, "job_id": job_id,
                "tech_id": mike["id"], "template": "pool",
                "chemical_readings": reading_rows,
                "chemicals_added": [], "checklist_items": [],
                "not_tested_flags": {}, "notes": "",
                "photos": [], "started_at": past.isoformat(),
                "submitted_at": past.isoformat(),
                "created_at": past.isoformat(), "updated_at": past.isoformat(),
            })
        await db.customers.update_one(
            {"id": cust["id"]},
            {"$set": {"phase51_prior_readings_seeded": True}},
        )


# ─── Phase 51.K · Vendor bills + user hourly rates seed ──────────────
async def seed_phase51k_finance():
    """Backfill users.hourly_rate_cents (tech: 2500, landscape: 3000)
    idempotently, and seed 8 sample vendor_bills across aging buckets.
    Guarded by tenant-level markers so the second run inserts 0 rows."""
    from datetime import datetime, timezone, timedelta
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    if not tenant:
        return
    tid = tenant["id"]
    # 1) Backfill hourly_rate_cents on users lacking one.
    async for u in db.users.find(
        {"hourly_rate_cents": None, "tenant_id": tid},
        {"_id": 0, "id": 1, "role": 1, "department": 1},
    ):
        dept = (u.get("department") or "").lower()
        role = u.get("role")
        if dept == "landscaping":
            rate = 3000
        elif role == "technician":
            rate = 2500
        else:
            rate = 0
        await db.users.update_one({"id": u["id"]}, {"$set": {"hourly_rate_cents": rate}})
    # 2) Seed 8 sample vendor bills — spread across aging buckets.
    marker = await db.tenants.find_one({"id": tid}, {"_id": 0, "phase51k_bills_seeded": 1})
    if (marker or {}).get("phase51k_bills_seeded"):
        return
    today = datetime.now(timezone.utc).date()
    samples = [
        {"vendor_name": "Poolmart Wholesale",  "due_offset_days":  10, "amount_cents":  45000, "status": "open"},
        {"vendor_name": "AZ Chem Supply",       "due_offset_days":   5, "amount_cents":  28000, "status": "open"},
        {"vendor_name": "Home Depot",            "due_offset_days":  -3, "amount_cents":  15000, "status": "open"},
        {"vendor_name": "Fleet Fuel Co.",        "due_offset_days": -12, "amount_cents":  32000, "status": "open"},
        {"vendor_name": "State Insurance",       "due_offset_days": -35, "amount_cents": 125000, "status": "open"},
        {"vendor_name": "Marketing Agency",      "due_offset_days": -55, "amount_cents":  60000, "status": "partial", "paid_amount_cents": 20000},
        {"vendor_name": "Legacy Uniforms Co.",   "due_offset_days": -75, "amount_cents":  18000, "status": "open"},
        {"vendor_name": "Old Vendor (write-off?)","due_offset_days": -120,"amount_cents":  9500,  "status": "open"},
    ]
    for s in samples:
        due = today + timedelta(days=s["due_offset_days"])
        bill_date = due - timedelta(days=30)
        await db.vendor_bills.insert_one({
            "id": new_id(),
            "tenant_id": tid,
            "vendor_name": s["vendor_name"],
            "bill_date": bill_date.isoformat(),
            "due_date": due.isoformat(),
            "amount_cents": s["amount_cents"],
            "paid_amount_cents": s.get("paid_amount_cents", 0),
            "status": s["status"],
            "notes": "Seeded sample bill",
            "created_at": now_iso(),
        })
    await db.tenants.update_one(
        {"id": tid}, {"$set": {"phase51k_bills_seeded": True}}
    )


# ─── Phase 52.0 · Ensure mike has ONE today-dated job (idempotent) ────
async def seed_mike_today_job():
    """Guarantee that mike@aquaterra.com has at least one incomplete
    `scheduled_date == today` job so the 50.E "Next Job" chip has data
    to render. If mike already has any incomplete job today, no-op.
    Otherwise, bumps the earliest scheduled future job to today (or
    creates a synthetic one when he has none).

    Phase 52 fix — matches by the user's linked `technician_id` field
    (canonical after Phase 15D). `scope_jobs_query` filters GET /jobs
    for techs on that field, not on `user.id`, so we must bump / seed
    against it or the Next Job chip will still find zero rows."""
    from datetime import datetime, timezone
    tenant = await db.tenants.find_one({"slug": "aquaterra"}, {"_id": 0})
    if not tenant:
        return
    tid = tenant["id"]
    mike = await db.users.find_one({"email": "mike@aquaterra.com"})
    if not mike:
        return
    tech_link = mike.get("technician_id") or mike["id"]
    today = datetime.now(timezone.utc).date().isoformat()
    existing = await db.jobs.find_one({
        "tenant_id": tid,
        "technician_id": tech_link,
        "scheduled_date": {"$regex": f"^{today}"},
        "status": {"$nin": ["completed", "cancelled", "canceled"]},
    }, {"_id": 0, "id": 1})
    if existing:
        return  # idempotent no-op
    # Try to bump an existing future scheduled job.
    future = await db.jobs.find_one({
        "tenant_id": tid,
        "technician_id": tech_link,
        "status": {"$in": ["scheduled", "pending", "in_progress"]},
    }, sort=[("scheduled_date", 1)])
    if future:
        await db.jobs.update_one(
            {"id": future["id"]},
            {"$set": {
                "scheduled_date": f"{today}T09:00:00+00:00",
                "scheduled_start": f"{today}T09:00:00+00:00",
                "updated_at": now_iso(),
                "phase52_today_bumped": True,
            }},
        )
        return
    # Fallback — create a minimal synthetic job.
    cust = await db.customers.find_one({"tenant_id": tid}, {"_id": 0, "id": 1, "name": 1, "address": 1})
    if not cust:
        return
    await db.jobs.insert_one({
        "id": new_id(), "tenant_id": tid,
        "title": "Weekly Pool Service",
        "service_type": "Weekly Pool Service",
        "customer_id": cust["id"], "customer_name": cust["name"],
        "address": cust.get("address", ""),
        "technician_id": tech_link,
        "technician_name": mike.get("name") or "Mike Rivera",
        "scheduled_date": f"{today}T09:00:00+00:00",
        "scheduled_start": f"{today}T09:00:00+00:00",
        "status": "scheduled", "price": 130, "created_at": now_iso(),
    })

