"""Phase 4 · Batch B / Deliverable 6 — Seed 12 handbook sections + 10
onboarding tasks. Uses `training_seed.seed_common` for the shared
blacklist + upsert helpers so vendor / IP contamination can't ship.

Run:
  python3 handbook_seed/seed_handbook.py           # dry-run
  python3 handbook_seed/seed_handbook.py --commit  # upsert to Mongo
"""
from __future__ import annotations
import argparse, asyncio, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

# Support both direct-file + `python3 -m` invocation.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from training_seed.seed_common import run_blacklist_scan  # type: ignore
except ImportError:
    from ..training_seed.seed_common import run_blacklist_scan  # type: ignore


# ─── Handbook sections ────────────────────────────────────────────
HANDBOOK_SECTIONS = [
    {
        "code": "company_overview",
        "title": "Company Overview & Mission",
        "order": 1,
        "markdown_body": """
# Company Overview & Mission

Welcome to the team. This is a family-owned pool and landscape service company that has grown by treating every customer's yard like it was our own and every teammate like a long-term partner rather than a short-term hire.

**What we do.** We install, maintain, and repair residential and commercial swimming pools, along with the surrounding landscape, hardscape, and outdoor-living hardware that makes those spaces enjoyable to be in. Our customers hire us because their pool or yard is one of the largest financial assets on their property and they want it looked after by people who show up on time and do it right the first time.

**Our mission.** To be the most trusted service partner in every neighborhood we serve, so that when someone new moves in and asks who to call, our name is the first one their neighbor recommends without hesitation.

**What we believe.**
- **Show up.** On time, in uniform, with the right tools. Every visit.
- **Do the work you'd want done at your own home.** No shortcuts, no rushed steps, no invented reasons to charge more.
- **Explain what you did.** Customers who understand what you did become customers for life.
- **Take care of each other.** If a teammate is having a rough day, cover their route. If a customer is unhappy, own the fix — no finger-pointing.
- **Grow the pie.** When we win, everyone wins. Referrals, tenure bonuses, and internal promotions come from that.

You are joining a company that values consistency, honesty, and craftsmanship over speed and volume. If you focus on doing your work well and taking care of the people around you, everything else — pay increases, promotions, autonomy — follows naturally.
""".strip(),
    },
    {
        "code": "working_hours",
        "title": "Working Hours & Attendance",
        "order": 2,
        "markdown_body": """
# Working Hours & Attendance

**Standard schedule.** Field teams start at the yard at 6:30 AM on weekdays during peak season (April through October) and 7:00 AM off-peak. Office and dispatch teams start at 7:30 AM. Your specific start time is confirmed by your supervisor and recorded in your employee file.

**Clocking in and out.** All field and office employees clock in and out through the timeclock system. Salaried employees still clock in for benefits/hours tracking; overtime rules do not change. Late clock-ins over 15 minutes without prior notice count against your attendance record.

**Notifying us if you can't make it.** If you can't come to work, call your direct supervisor by phone (not text, not email) at least ninety minutes before your scheduled start. Same-day text messages are acceptable only in true emergencies (car accident, family medical event) — otherwise call. Multiple no-call / no-shows are grounds for termination without further warning.

**Route completion.** Your route is not "done" until every stop is completed with photos uploaded and any issues logged. Leaving stops uncompleted or "we'll come back tomorrow" without supervisor approval creates ripple effects that reach the customer. Finish your route.

**Weather.** In severe weather (thunderstorms, ice, high wind), your supervisor will make a service-day call by 5:30 AM. Check the team communication channel before leaving home during questionable weather. If service is cancelled, hourly employees are still paid for a minimum of half a day.

**Overtime.** Overtime requires supervisor pre-approval. Working past scheduled hours without approval is not a path to more pay — it's a path to a coaching conversation.
""".strip(),
    },
    {
        "code": "pto_and_leave",
        "title": "PTO, Sick Leave & Time Off",
        "order": 3,
        "markdown_body": """
# PTO, Sick Leave & Time Off

**Paid Time Off (PTO).** Full-time employees accrue PTO on a monthly basis starting the first full month after hire. Accrual rates increase at each employment anniversary. Your current balance and rate are visible in the employee portal.

**Requesting PTO.** Submit PTO requests through the portal at least fourteen days in advance. Peak-season requests (May through August) require earlier notice — thirty days is standard. Approvals are granted based on staffing coverage; we try to say yes whenever we can, but we can't approve every crew being out the same week.

**Sick leave.** Sick leave is separate from PTO. Call your supervisor by 6:00 AM if you're too sick to work. A doctor's note is required for any absence of three or more consecutive days. Coming to work sick and getting your teammates sick isn't heroism — it's a hit to the whole route. Stay home, get better, come back stronger.

**Bereavement.** Three paid days for the death of an immediate family member (spouse, child, parent, sibling), one paid day for grandparent, in-law, or aunt/uncle. Additional unpaid time can be requested through your supervisor.

**Jury duty.** Full pay differential (we pay the difference between your regular wages and jury pay) for the first two weeks. Notify your supervisor as soon as you receive a summons.

**Holidays.** We observe six paid holidays: New Year's Day, Memorial Day, Independence Day, Labor Day, Thanksgiving, and Christmas Day. Field routes are compressed the week of each holiday; your supervisor will publish the compressed schedule at least two weeks ahead.

**Unpaid leave.** For life events beyond the standard PTO allowance, unpaid leave requests are considered case-by-case in coordination with HR.
""".strip(),
    },
    {
        "code": "safety_general",
        "title": "Safety Protocols (General)",
        "order": 4,
        "markdown_body": """
# Safety Protocols (General)

Safety is not a policy binder — it's the reason you go home to your family every night in the same shape you came to work. Read this, follow it, and speak up when something looks unsafe.

**Personal Protective Equipment (PPE).** You are issued PPE on your first day. Wear it. Safety glasses on any grinding, cutting, or chemical work. Gloves for any chemical or sharps handling. Hearing protection for any equipment louder than a conversational voice. Steel-toed work boots for all field work. Sun protection (long sleeves, hat, sunscreen) at your discretion; heat illness is a bigger daily risk than most techs realize.

**Chemicals.** All chemical handling is covered in a separate, more detailed section. Short version: never mix chemicals, always add chemical to water (not water to chemical), keep chemical storage locked and labeled, and know the location of your spill kit and eyewash station.

**Vehicles.** Follow the vehicle use policy. No cell phone use while driving unless hands-free. No passengers who aren't scheduled crew. Always secure trailers with safety chains and check tire pressure weekly.

**Equipment.** Use every piece of equipment for its designed purpose. Never bypass a safety guard. If a tool or piece of equipment is damaged, tag it out of service and notify your supervisor — don't just leave it in the truck for the next person to discover.

**Ladders and heights.** Any work above ten feet requires either a proper fall-arrest system or a two-person spotting arrangement. Never overreach from a ladder; move it.

**Reporting.** Any injury, near-miss, or property damage must be reported to your supervisor before end of shift. Small injuries (scrapes, minor burns) get logged; anything requiring more than a Band-Aid triggers the incident-report process.

**Stop-work authority.** Every employee, from apprentice to senior tech, has the authority to stop work if they believe a situation is unsafe. You will not be penalized for stopping work. Restart only after the safety concern is addressed.
""".strip(),
    },
    {
        "code": "chemical_ppe",
        "title": "Chemical Handling & PPE",
        "order": 5,
        "markdown_body": """
# Chemical Handling & PPE

Pool chemistry is the most hazardous part of pool service work. Every year in this industry, techs are seriously injured — sometimes fatally — because of preventable mistakes with chemicals. This section is not optional reading.

**Required PPE for any chemical work.**
- Chemical-splash safety goggles (not just safety glasses)
- Chemical-resistant gloves (nitrile or neoprene — not standard work gloves)
- Long-sleeved shirt or chemical apron
- Closed-toe boots
- Respirator with acid-gas cartridge when working with muriatic acid or with more than a gallon of chlorine

**Storage.**
- Chemical storage areas are locked at all times when not in active use.
- Oxidizers (chlorine, calcium hypochlorite) never share a shelf or cabinet with acids (muriatic, sodium bisulfate). Separate by at least six feet, or use physical separation shelves.
- Every container is labeled with contents and hazard class. Unlabeled containers are treated as hazardous waste — do not open, do not test, escalate to your supervisor.

**Handling rules.**
- Always add chemical to water. Never water to chemical. This is the single rule that prevents the most serious injuries.
- Never combine two different pool chemicals. Chlorine plus acid, chlorine plus ammonia (from urine, sweat, or shocked pools), even different chlorines together can produce toxic chlorine gas.
- Pour outdoors or in well-ventilated spaces only.
- If you spill, use the spill kit. Absorb, contain, dispose per the SDS. Report even minor spills to your supervisor.

**Symptoms of exposure — get to fresh air immediately.**
- Coughing, wheezing, or chest tightness after being near chlorine or acid
- Watery eyes or burning nose
- Skin redness or burning sensation
- Dizziness or nausea

Any exposure symptoms trigger the incident-report process and, depending on severity, an ER visit. Never try to "walk it off" chemical exposure.

**Poison control.** 1-800-222-1222. Save it in your phone right now.

**Transport.** Chemicals in vehicles are secured with tie-downs. Never transport chemicals inside the cab. The bed or a locked trailer only, with fresh-air ventilation.
""".strip(),
    },
    {
        "code": "vehicle_use",
        "title": "Vehicle Use Policy",
        "order": 6,
        "markdown_body": """
# Vehicle Use Policy

**Assigned vehicles.** Field techs are assigned a company vehicle for the duration of their route work. The vehicle is not for personal use unless specifically authorized in writing by your supervisor.

**Pre-trip inspection.** Every day, before you leave the yard, walk around your vehicle. Check tire pressure visually, check for damage that wasn't there yesterday, check that all trailer tie-downs and safety chains are secure, and confirm your fluid levels (oil, coolant, washer fluid) are in range. Log any issue in the vehicle app or paper log.

**Driving.**
- Seatbelts on before the vehicle moves. No exceptions.
- Speed limits are limits, not targets. In residential neighborhoods with kids and dogs, drive well under the posted limit.
- No cell phone use while driving. Hands-free calls are permitted for work-related conversations only. Texting, emailing, and app use behind the wheel are grounds for termination on first offense.
- Backing up: use your camera and your mirrors. When possible, back into the space when you first arrive so leaving is a straight pull-out. Have a spotter in tight spaces.
- Trailers: check safety chains, tie-downs, and running lights every single time before you move the vehicle.

**Fuel.** Fuel is purchased with the company fuel card assigned to your vehicle. Fuel-only, no snacks or personal purchases. Receipts stay in the vehicle or are uploaded through the app.

**Maintenance.** Report any warning light, unusual noise, or handling change to your supervisor and to the shop the same day. Do not "wait for the next oil change" to bring up brake issues.

**Accidents.** Any accident — even a small parking-lot bump with no visible damage — is reported to your supervisor within 30 minutes and to the police if any other vehicle or property is involved. Do not admit fault at the scene. Photograph everything. Exchange insurance information calmly.

**End of day.** Vehicles return to the yard fueled, swept out, with tools accounted for. The next tech assigned to that vehicle should be able to start their day without pre-loading yours.
""".strip(),
    },
    {
        "code": "uniform_presentation",
        "title": "Uniform & Personal Presentation",
        "order": 7,
        "markdown_body": """
# Uniform & Personal Presentation

**Uniform issued on hire.** You receive five shirts, two pairs of work pants or shorts, one jacket, and one hat on your start date. Additional pieces are provided each spring and fall. Damaged uniform is replaced free through your supervisor; lost or worn-through uniform beyond normal wear is replaced at cost.

**Wearing the uniform.**
- Full uniform on every service visit and every customer-facing interaction. The uniform is not optional in front of customers.
- Shirts tucked in unless the shirt is designed to be worn untucked.
- Pants or shorts free of large tears, oil stains, or paint. Small stains from service work are acceptable; a shirt covered in yesterday's algae is not.
- Company hat is optional (weather-appropriate) but if worn must be the issued company hat, not a personal team, band, or slogan hat.

**Personal hygiene.**
- Show up clean and showered. Field work is physical; end-of-day sweaty is normal. Start-of-day smelly is not.
- Facial hair neatly trimmed if worn. Beards must accommodate any required respirator seal (chemical work) — a full beard means no respirator seal and no chemical work assignment for that day.
- Tattoos are welcome. Any tattoo visible to a customer must not be hateful, sexually explicit, or profane — that's a common-sense standard, not a personal-choice restriction.

**Jewelry and accessories.** Wedding bands and small stud earrings are fine. Long chains, dangling earrings, and rings with sharp settings create pinch and snag hazards around equipment; leave them at home for field work.

**Language and behavior on-site.** Customers can hear you from further away than you think. No profanity, no politics, no yelling at teammates within earshot of a customer's home. Music from portable speakers stays at a volume the neighbor can't hear.

**Introduction.** Introduce yourself by name at the first customer-facing visit at a property. "Hi, I'm ___, I'll be taking care of your pool this season" gives the customer a face to a name and starts a relationship. On follow-up visits, a wave and eye contact is enough.
""".strip(),
    },
    {
        "code": "customer_comm",
        "title": "Customer Communication Standards",
        "order": 8,
        "markdown_body": """
# Customer Communication Standards

**Every visit.** Log a photo of the finished work and any observations before leaving the property. Photos are how the office answers customer questions when they call three days later.

**When something is wrong.** If you find a broken pump, low chemical inventory, algae bloom, or anything else that needs attention beyond routine service, message the office through the tech app during the visit. Waiting until end of day means the customer's call to the office beats you to the punch — always bad.

**Talking to customers directly.**
- Be respectful. Use their name if you know it. Answer questions in plain English, not industry jargon.
- If they ask you to do extra work not on the ticket, tell them the office will send a quote for that. Don't quote prices in the field — pricing has too many variables (materials, drive time, additional tests) for a tech to promise a number that dispatch will have to unwind later.
- If they're upset, listen. Don't argue. Say something like "I hear you, let me get the office on the phone right now" and call your supervisor. De-escalation almost always starts with the customer feeling heard.

**On the phone.** Answer with your name and the company. "This is ___ from ___, how can I help?" Ninety percent of the customer experience is tone. Even on a bad day, tone matters more than content.

**Texting.** Company-provided phones and the tech app are the only channels for customer texting. Do not text customers from your personal phone; when you leave the company, the customer relationship goes with the number, and that hurts everyone.

**Escalation.** When to escalate to a supervisor:
- Customer is angry, threatening to cancel, or asking for a refund
- Customer is asking about pricing beyond a standard service visit
- Customer is reporting damage (yours or theirs) that needs a formal report
- Any interaction that makes you uncomfortable — trust your gut

**Reviews.** After a completed job, ask happy customers to leave a Google review. Say "If we did good work for you today, a quick Google review helps our small business a lot." Do not push, do not offer discounts for reviews, do not review-farm.

**Confidentiality.** What you see at customer properties — home layouts, medical devices, family arguments overheard, financial documents on tables — stays private. Full stop.
""".strip(),
    },
    {
        "code": "route_efficiency",
        "title": "Route Efficiency Expectations",
        "order": 9,
        "markdown_body": """
# Route Efficiency Expectations

**Your route is planned.** Dispatch has already ordered your stops for maximum efficiency and minimum drive time. Reorder only for a specific reason (chemical delivery timing, gated community access hours, a customer who needs a specific time window) and only after asking dispatch.

**Target stops per day.** Weekly pool service routes target 18-24 stops per full-time day. Bi-weekly / less frequent routes target 12-16 stops per day due to higher chemical work per stop. Your specific target is set with your supervisor based on the neighborhoods you cover.

**Drive time.** Drive time between stops should average under 8 minutes in dense residential areas and under 15 minutes in more spread-out territories. If your app shows a consistent 20+ minute drive time between two adjacent stops, tell dispatch — there may be a routing issue we can fix.

**Time per stop.** A standard maintenance stop is 20-30 minutes. Under 15 minutes usually means something got skipped; over 40 minutes usually means an issue you should have flagged as an add-on service. Both extremes are worth a supervisor conversation.

**Photos.** Every stop, every visit: before/after photos of the pool surface, a readable close-up of chemistry test results, and any issues (broken tiles, low water level, equipment leak). Photos are your evidence and our shield against disputes.

**Route completion time.** Your route should be complete — every stop logged, every photo uploaded — by 4:00 PM most days. Consistently finishing after 5:00 PM without escalation is a sign we need to rebalance your route.

**Missed stops.** If you cannot complete a stop today (customer not home for gate access, dog issue, storm), log the reason in the app and message dispatch immediately. Dispatch will reschedule, not you. Never quietly move a stop to tomorrow.

**Efficiency wins.** Route efficiency gains — completing your route earlier without cutting quality — are shared with you. Once you're consistently finishing early, we start adding stops (with pay accordingly) or you get to head home early on light days. That's how tenure and skill pay off in this company.
""".strip(),
    },
    {
        "code": "damage_incident",
        "title": "Damage & Incident Reporting",
        "order": 10,
        "markdown_body": """
# Damage & Incident Reporting

**Report everything, immediately.** Any damage — to a customer's property, to your vehicle, to a teammate, to equipment, to yourself — gets reported to your supervisor the same day it happens, ideally within 30 minutes.

**Property damage at a customer's site.**
- Take photos of the damage before you touch anything. Multiple angles. Include a reference object (your phone, a paver, a coin) for scale.
- Notify your supervisor by phone. Do not text; a phone call gets an immediate response.
- Do not admit fault or promise a repair to the customer on the spot. Say "I'm going to get my supervisor on the phone right now to figure out the right way to make this right." That protects both you and the customer's expectation.
- Fill out the Incident Report template in the app with the "who / what / when / where / how" fields before end of shift. Attach the photos.

**Vehicle accidents.** Follow the vehicle-use policy: report within 30 minutes, police report if any second party is involved, do not admit fault, exchange insurance, photograph everything.

**Personal injury.**
- Any injury, even something you think is minor, is reported to your supervisor before you finish the day. Injuries "walked off" today can become workers' comp claims tomorrow with much messier paperwork.
- If the injury requires more than a Band-Aid or ice pack, you go to an urgent care or ER — same day, no exceptions. The company covers the medical costs for work-related injuries.
- Photograph any visible injury (bruise, cut, chemical splash) as soon as safely possible.

**Near-misses.** A near-miss is an incident that could have caused harm but didn't. Missed the pool step and almost fell in. Slipped on wet decking but caught yourself. Chemical container tipped but didn't spill. These are the most important reports we can get because they let us fix a hazard before someone gets hurt. Log every one; you'll never be criticized for reporting a near-miss.

**Customer-caused damage.** Sometimes damage happens on a property that wasn't caused by us — pre-existing cracked tiles, a neighbor's dog on the pool cover, storm damage between visits. Photograph it immediately and note it in the app. This prevents the damage from being attributed to us later.

**No blame culture.** The incident-report process is not a disciplinary tool. Its purpose is prevention. Employees who honestly report an incident they caused will be coached, not fired. Employees who cover up an incident will be terminated when it's discovered — and it will be discovered.
""".strip(),
    },
    {
        "code": "payroll_reviews",
        "title": "Payroll, Bonuses & Reviews",
        "order": 11,
        "markdown_body": """
# Payroll, Bonuses & Reviews

**Pay period.** Bi-weekly. Payroll closes end-of-day Sunday; direct deposit lands the following Friday. Paper checks are available on request but discouraged — direct deposit is faster and safer.

**Time cards.** Your clocked-in hours in the timeclock system are your official record. Review your time card each Monday morning and flag any discrepancies to your supervisor. Once payroll runs, corrections require a formal amendment and take a full pay cycle to reflect.

**Overtime.** Hourly employees earn 1.5× regular rate for any hour over 40 in a work week. Overtime must be pre-approved by a supervisor. Working extra hours without pre-approval doesn't earn you those hours — it earns a coaching conversation.

**Tenure raises.** Every anniversary of your hire date, your rate is reviewed. Meeting expectations means a cost-of-living adjustment. Exceeding expectations (consistent quality scores, referrals from customers, willingness to train new techs) means a raise beyond COLA. Under-performance is discussed openly at the ninety-day and six-month check-ins, well before an anniversary review, so no annual review should ever be a surprise.

**Referral bonuses.**
- **Customer referral.** When a customer you're servicing refers a new customer who signs up and pays their first invoice, you receive a $50 bonus in your next paycheck. No cap.
- **Team member referral.** When you refer someone we hire and who stays for 90 days, you receive a $500 bonus. If they stay a full year, another $500.

**Performance bonuses.** Quarterly performance bonuses are paid for meeting or exceeding your route's quality score (photo compliance, on-time percentage, customer satisfaction scores). The bonus schedule is published at the start of each quarter.

**Quarterly reviews.** Every quarter, you sit down with your supervisor for 20 minutes to talk about how the last three months went. This is a two-way conversation — we ask about your challenges, your goals, and what we can do better as a company. Skipping these reviews without a rescheduling reason is not permitted; they are important.

**Advancement.** Field techs promote to lead tech, then to supervisor, then to route manager. Each promotion has clear published criteria (tenure, certifications earned, quality scores, willingness to train). We fill supervisor and above roles from inside first. Every senior person at this company started as a field tech.
""".strip(),
    },
    {
        "code": "termination_exit",
        "title": "Termination & Exit Procedures",
        "order": 12,
        "markdown_body": """
# Termination & Exit Procedures

**Employment is at-will.** Either the employee or the employer may end the employment relationship at any time, for any lawful reason, with or without notice. We prefer two weeks' notice from resigning employees and try to give equivalent notice for non-cause terminations when circumstances permit.

**Voluntary resignation.** If you decide to leave:
1. Notify your direct supervisor first, in person or by phone (not by text or email).
2. Confirm the notice in writing (email is fine) with your intended last day.
3. Complete an exit interview — 20 minutes, honest conversation about what worked, what didn't, and where you're headed. Exit interviews shape how we treat the next hire.
4. Return company property (uniform, phone, vehicle keys, tools, credit card, laptop) on your last day.
5. Any accrued PTO is paid out on the final paycheck per state law.

**Termination for cause.** The following are grounds for immediate termination without additional warning:
- Theft (including intentional time-card manipulation)
- Assault or threats of violence toward a teammate or customer
- Working under the influence of alcohol or unauthorized substances
- Falsification of records (safety, service, incident, chemical)
- Chronic no-call / no-show (three or more instances)
- Working a second job that directly competes with the company while employed here
- Serious safety violations that endanger a teammate or customer

**Performance termination.** For performance issues (not cause), the sequence is: verbal coaching → written coaching (documented) → performance improvement plan (30 days) → termination if not resolved. This gives every employee a real chance to correct course.

**Layoffs.** In rare cases (major weather event, loss of a large contract, business shutdown), layoffs may occur. We give as much notice as the situation allows and use tenure and role as the primary factors.

**Post-employment.** After your last day:
- Your health-insurance coverage (if any) ends at the end of that month. COBRA information is provided in the exit packet.
- Your 401(k), if any, is yours to roll over or leave in place per plan rules. Fidelity or the current administrator will send instructions.
- Your final paycheck arrives on the next scheduled pay date per state law, including any accrued PTO.
- Non-solicitation of customers and non-recruitment of employees is expected for one year after departure. Signing bonuses for teammates who follow you to a competitor within that year is specifically the kind of behavior that will result in litigation — don't do it.

**Rehire.** Employees who leave in good standing are welcome to reapply after ninety days. Many of our best long-tenure employees are second-time hires.

**Contact after leaving.** Reach out to HR (or your former supervisor) any time you want — a reference call, a check-in on old teammates, or a return to the company. We stay in touch with people who once worked here.
""".strip(),
    },
]


# ─── Onboarding tasks ────────────────────────────────────────────
ONBOARDING_TASKS = [
    {"code": "read_company_overview", "title": "Read: Company Overview & Mission",
     "order": 1, "kind": "read_handbook_section", "related_ref": "company_overview"},
    {"code": "read_working_hours", "title": "Read: Working Hours & Attendance",
     "order": 2, "kind": "read_handbook_section", "related_ref": "working_hours"},
    {"code": "read_safety_general", "title": "Read: Safety Protocols (General)",
     "order": 3, "kind": "read_handbook_section", "related_ref": "safety_general"},
    {"code": "read_vehicle_use", "title": "Read: Vehicle Use Policy",
     "order": 4, "kind": "read_handbook_section", "related_ref": "vehicle_use"},
    {"code": "fill_employee_handbook", "title": "Fill: Employee Handbook acknowledgement form",
     "order": 5, "kind": "form_signature", "related_ref": "employee_handbook"},
    {"code": "fill_subcontractor_agreement", "title": "Fill: Subcontractor Agreement (if applicable)",
     "order": 6, "kind": "form_signature", "related_ref": "subcontractor_agreement",
     "description": "Skip if you're an employee — this task is for 1099 subcontractors only."},
    {"code": "training_cpo_prep", "title": "Complete Training Module: CPO Prep",
     "order": 7, "kind": "training_module", "related_ref": "pool-cpo-prep"},
    {"code": "read_chemical_ppe", "title": "Read: Chemical Handling & PPE",
     "order": 8, "kind": "read_handbook_section", "related_ref": "chemical_ppe"},
    {"code": "fill_new_customer_onboarding", "title": "Fill: New Customer Onboarding walkthrough",
     "order": 9, "kind": "form_signature", "related_ref": "new_customer_onboarding",
     "description": "Practice run — fill out a sample new-customer intake form."},
    {"code": "sign_service_agreement_ack", "title": "Sign: Service Agreement acknowledgement",
     "order": 10, "kind": "form_signature", "related_ref": "service_agreement"},
]


def _now_iso() -> str: return datetime.now(timezone.utc).isoformat()


def _blacklist_all(sections, tasks) -> None:
    for s in sections:
        hits = run_blacklist_scan(s["markdown_body"])
        if hits:
            raise SystemExit(f"IP-SAFETY VIOLATION in section '{s['code']}': {hits[0]}")
    for t in tasks:
        blob = f"{t.get('title','')} {t.get('description','')}"
        hits = run_blacklist_scan(blob)
        if hits:
            raise SystemExit(f"IP-SAFETY VIOLATION in task '{t['code']}': {hits[0]}")


async def _seed(sections, tasks) -> None:
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    now = _now_iso()
    for s in sections:
        existing = await db.company_handbook_sections.find_one(
            {"code": s["code"], "is_system": True}, {"_id": 0, "id": 1})
        doc = {**s, "is_system": True, "tenant_id": None,
                "version": 1, "updated_at": now,
                "updated_by": "system",
                "id": (existing or {}).get("id") or str(uuid.uuid4())}
        await db.company_handbook_sections.update_one(
            {"code": s["code"], "is_system": True}, {"$set": doc}, upsert=True)
    for t in tasks:
        existing = await db.onboarding_tasks.find_one(
            {"code": t["code"], "is_system": True}, {"_id": 0, "id": 1})
        doc = {**t, "is_system": True, "tenant_id": None,
                "updated_at": now,
                "id": (existing or {}).get("id") or str(uuid.uuid4())}
        await db.onboarding_tasks.update_one(
            {"code": t["code"], "is_system": True}, {"$set": doc}, upsert=True)
    # indexes
    await db.company_handbook_sections.create_index([("tenant_id", 1), ("code", 1)])
    await db.company_handbook_sections.create_index("code")
    await db.onboarding_tasks.create_index([("tenant_id", 1), ("code", 1)])
    await db.onboarding_tasks.create_index("code")
    await db.onboarding_progress.create_index([("tenant_id", 1), ("user_id", 1), ("task_code", 1)])
    client.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    _blacklist_all(HANDBOOK_SECTIONS, ONBOARDING_TASKS)
    print(f"Handbook sections: {len(HANDBOOK_SECTIONS)}")
    print(f"Onboarding tasks:  {len(ONBOARDING_TASKS)}")
    if args.commit:
        asyncio.run(_seed(HANDBOOK_SECTIONS, ONBOARDING_TASKS))
        print("Committed.")
    else:
        print("\nDRY-RUN — no database writes. Pass --commit to seed.")


if __name__ == "__main__":
    main()
