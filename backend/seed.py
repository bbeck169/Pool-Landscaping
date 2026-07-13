from datetime import datetime, timezone, timedelta

from config import db, logger
from utils import now_iso, new_id, hash_password


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
            {"id": new_id(), "customer_name": "Jennifer Carson", "rating": 5, "text": "Mike is fantastic — pool has never looked better!", "source": "Google", "response": "Thank you Jennifer! — Team AquaTerra", "created_at": now_iso()},
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
