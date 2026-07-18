"""Phase 1 · Templates Library — seed 23 system templates.

All content is 100% original in-house wording. Only category names + template
titles mirror pooldial.com/resources/templates; no template body, prompts, or
instructions are copied. Enforced by the IP-safety blacklist scan at the end.

Run:
  python3 templates_seed/seed_templates.py           # dry-run, no writes
  python3 templates_seed/seed_templates.py --commit  # upsert to Mongo
"""
from __future__ import annotations
import argparse, asyncio, json, os, re, sys, uuid
from datetime import datetime, timezone
from pathlib import Path


def _f(key, label, type_, **kw):
    d = {"key": key, "label": label, "type": type_, "required": kw.pop("required", False)}
    for k in ("help_text","default","min","max","options","columns"):
        if k in kw: d[k] = kw[k]
    return d


def _sec(title, fields): return {"title": title, "fields": fields}


ADMIN = ["admin","super_admin"]
ADMIN_TECHS = ["admin","super_admin","pool_tech","landscape_tech"]


# ─── 23 templates ────────────────────────────────────────────────────
TEMPLATES = [
    # ═══ 1. Truck Inventory Checklist (rich)
    {"code":"truck_inventory_checklist","title":"Truck Inventory Checklist","category":"pricing_money","allowed_roles":ADMIN_TECHS,
     "description":"Daily pre-route inventory verification for service trucks.",
     "schema":[
       _sec("Vehicle Info",[_f("truck_id","Truck ID","text",required=True),_f("driver","Driver","text",required=True),_f("date","Date","date",required=True),_f("odometer","Odometer","number")]),
       _sec("Chemicals On Board",[_f("chemicals","","table",columns=[{"key":"item","label":"Chemical"},{"key":"qty","label":"Qty"},{"key":"unit","label":"Unit"},{"key":"min_par","label":"Min Par"},{"key":"restock","label":"Restock Needed"}])]),
       _sec("Tools",[_f("tools","","table",columns=[{"key":"item","label":"Tool"},{"key":"present","label":"Present"},{"key":"condition","label":"Condition"}])]),
       _sec("Safety",[_f("fire_ext","Fire extinguisher charged","checkbox"),_f("first_aid","First-aid kit stocked","checkbox"),_f("spill_kit","Spill kit present","checkbox"),_f("ppe","PPE (gloves/goggles/apron) available","checkbox")]),
       _sec("Notes",[_f("notes","Notes","long_text")]),
       _sec("Sign-off",[_f("signature","Driver signature","signature")]),
     ]},

    # ═══ 2-9 Pricing & Money
    {"code":"new_customer_onboarding","title":"New Customer Onboarding","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Structured intake for new residential/commercial customers.",
     "schema":[
       _sec("Customer",[_f("name","Full name","text",required=True),_f("phone","Phone","text",required=True),_f("email","Email","text"),_f("address","Service address","long_text",required=True)]),
       _sec("Pool / Property",[_f("pool_type","Pool type","select",options=["Residential","Commercial","Landscape only","Other"]),_f("pool_gallons","Pool gallons","number"),_f("weekly_or_bi","Service frequency","select",options=["Weekly","Bi-weekly","Monthly","On-call"])]),
       _sec("Access",[_f("gate_code","Gate/access code","text"),_f("dog_on_property","Dog on property?","checkbox"),_f("access_notes","Access notes","long_text")]),
       _sec("Billing",[_f("billing_email","Billing email","text"),_f("billing_method","Preferred method","select",options=["Card on file","ACH","Check","Invoice"])]),
       _sec("Sign-off",[_f("signature","Customer signature","signature")]),
     ]},
    {"code":"seasonal_opening_closing_tracker","title":"Seasonal Opening & Closing Tracker","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Roster-level tracker of which properties are opened / closed each season.",
     "schema":[
       _sec("Season",[_f("season","Season","select",options=["Spring open","Fall close","Winterize","De-winterize"]),_f("year","Year","number")]),
       _sec("Properties",[_f("rows","","table",columns=[{"key":"customer","label":"Customer"},{"key":"address","label":"Address"},{"key":"scheduled","label":"Scheduled date"},{"key":"completed","label":"Completed date"},{"key":"tech","label":"Tech"},{"key":"invoiced","label":"Invoiced"}])]),
     ]},
    {"code":"capacity_planner","title":"Capacity Planner","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Weekly route capacity vs. active-customer load, per tech.",
     "schema":[
       _sec("Week",[_f("week_of","Week of","date",required=True)]),
       _sec("Techs",[_f("rows","","table",columns=[{"key":"tech","label":"Tech"},{"key":"target_stops","label":"Target stops/day"},{"key":"actual_stops","label":"Actual stops/day"},{"key":"open_slots","label":"Open slots"}])]),
       _sec("Notes",[_f("notes","Notes","long_text")]),
     ]},
    {"code":"equipment_maintenance_schedule","title":"Equipment Maintenance Schedule","category":"pricing_money","allowed_roles":ADMIN_TECHS,
     "description":"Preventive schedule for pumps, filters, salt cells, heaters.",
     "schema":[
       _sec("Equipment",[_f("rows","","table",columns=[{"key":"equipment","label":"Equipment"},{"key":"last_serviced","label":"Last serviced"},{"key":"interval_months","label":"Interval (mo)"},{"key":"next_due","label":"Next due"},{"key":"notes","label":"Notes"}])]),
     ]},
    {"code":"lead_tracking_sheet","title":"Lead Tracking Sheet","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Sales pipeline from initial contact through won/lost.",
     "schema":[
       _sec("Leads",[_f("rows","","table",columns=[{"key":"name","label":"Name"},{"key":"source","label":"Source"},{"key":"contacted","label":"Contacted date"},{"key":"quoted","label":"Quoted"},{"key":"status","label":"Status"},{"key":"next_action","label":"Next action"}])]),
     ]},
    {"code":"referral_program_tracker","title":"Referral Program Tracker","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Customer referrals + reward status.",
     "schema":[
       _sec("Referrals",[_f("rows","","table",columns=[{"key":"referrer","label":"Referring customer"},{"key":"referred","label":"Referred customer"},{"key":"date","label":"Date"},{"key":"converted","label":"Converted"},{"key":"reward_status","label":"Reward status"}])]),
     ]},
    {"code":"employee_time_payroll","title":"Employee Time & Payroll","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Weekly hours + pay summary per employee.",
     "schema":[
       _sec("Period",[_f("pay_period","Pay period","text",required=True),_f("date","Payroll date","date")]),
       _sec("Employees",[_f("rows","","table",columns=[{"key":"employee","label":"Employee"},{"key":"regular_hours","label":"Regular hrs"},{"key":"overtime_hours","label":"OT hrs"},{"key":"rate","label":"Rate"},{"key":"gross","label":"Gross"}])]),
     ]},
    {"code":"tax_deduction_tracker","title":"Tax Deduction Tracker","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Business expense categorization for tax preparation.",
     "schema":[
       _sec("Year",[_f("tax_year","Tax year","number",required=True)]),
       _sec("Expenses",[_f("rows","","table",columns=[{"key":"category","label":"Category"},{"key":"date","label":"Date"},{"key":"vendor","label":"Vendor"},{"key":"amount","label":"Amount"},{"key":"deductible","label":"Deductible"},{"key":"notes","label":"Notes"}])]),
     ]},

    # ═══ 10-14 Operations & Chemistry
    {"code":"chemical_cost_tracker","title":"Chemical Cost Tracker","category":"operations_checklists","allowed_roles":ADMIN,
     "description":"Cost-per-pool chemical usage tracking.",
     "schema":[
       _sec("Purchases",[_f("rows","","table",columns=[{"key":"chemical","label":"Chemical"},{"key":"qty","label":"Qty"},{"key":"unit","label":"Unit"},{"key":"unit_cost","label":"Unit cost"},{"key":"total","label":"Total"},{"key":"vendor","label":"Vendor"},{"key":"date","label":"Date"}])]),
     ]},

    # ═══ 11. Water Chemistry Log (rich)
    {"code":"water_chemistry_log","title":"Water Chemistry Log","category":"chemicals_chemistry","allowed_roles":ADMIN_TECHS,
     "description":"Per-visit water chemistry readings and chemicals added.",
     "schema":[
       _sec("Pool Info",[_f("customer","Customer","text",required=True),_f("pool_id","Pool ID","text"),_f("date","Date","date",required=True),_f("visit_type","Visit type","select",options=["Weekly","Bi-weekly","On-call","Opening","Closing"])]),
       _sec("Readings",[_f("readings","","table",columns=[{"key":"time","label":"Time"},{"key":"free_chlorine","label":"Free Cl (ppm)"},{"key":"total_chlorine","label":"Total Cl (ppm)"},{"key":"ph","label":"pH"},{"key":"alkalinity","label":"Alk (ppm)"},{"key":"cya","label":"CYA (ppm)"},{"key":"calcium_hardness","label":"CaHardness (ppm)"},{"key":"temp_f","label":"Temp (°F)"}])]),
       _sec("Chemicals Added",[_f("chems","","table",columns=[{"key":"chemical","label":"Chemical"},{"key":"amount","label":"Amount"},{"key":"unit","label":"Unit"}])]),
       _sec("Observations",[_f("clarity","Water clarity","select",options=["Clear","Hazy","Cloudy","Green"]),_f("issues","Issues observed","long_text")]),
       _sec("Technician",[_f("tech_name","Technician","text"),_f("signature","Signature","signature")]),
     ]},
    {"code":"cpo_commercial_pool_log","title":"CPO Commercial Pool Log","category":"chemicals_chemistry","allowed_roles":ADMIN_TECHS,
     "description":"CPO-compliant commercial log (2x/day readings when open).",
     "schema":[
       _sec("Facility",[_f("facility","Facility","text",required=True),_f("date","Date","date",required=True),_f("cpo_operator","CPO operator on duty","text",required=True)]),
       _sec("Readings",[_f("readings","","table",columns=[{"key":"time","label":"Time"},{"key":"free_chlorine","label":"Free Cl"},{"key":"combined_chlorine","label":"Combined Cl"},{"key":"ph","label":"pH"},{"key":"alkalinity","label":"Alk"},{"key":"flow_gpm","label":"Flow (GPM)"},{"key":"filter_psi","label":"Filter PSI"},{"key":"bathers","label":"Bather load"}])]),
       _sec("Actions",[_f("actions","Adjustments made","long_text")]),
       _sec("Sign-off",[_f("signature","Operator signature","signature")]),
     ]},
    {"code":"commercial_pool_log_book","title":"Commercial Pool Log Book","category":"operations_checklists","allowed_roles":ADMIN_TECHS,
     "description":"Long-form commercial pool operations log.",
     "schema":[
       _sec("Header",[_f("facility","Facility","text",required=True),_f("month","Month","text"),_f("year","Year","number")]),
       _sec("Daily entries",[_f("entries","","table",columns=[{"key":"date","label":"Date"},{"key":"free_cl","label":"Free Cl"},{"key":"ph","label":"pH"},{"key":"alk","label":"Alk"},{"key":"psi","label":"Filter PSI"},{"key":"bathers","label":"Bathers"},{"key":"initials","label":"Initials"}])]),
     ]},
    {"code":"residential_pool_log_book","title":"Residential Pool Log Book","category":"operations_checklists","allowed_roles":ADMIN_TECHS,
     "description":"Homeowner-friendly residential pool log.",
     "schema":[
       _sec("Pool",[_f("customer","Customer","text",required=True),_f("month","Month","text")]),
       _sec("Weekly entries",[_f("entries","","table",columns=[{"key":"date","label":"Date"},{"key":"free_cl","label":"Free Cl"},{"key":"ph","label":"pH"},{"key":"alk","label":"Alk"},{"key":"vacuumed","label":"Vacuumed"},{"key":"notes","label":"Notes"}])]),
     ]},

    # ═══ 15-22 Documents
    {"code":"employee_handbook","title":"Employee Handbook","category":"documents","allowed_roles":ADMIN,
     "description":"Company handbook cover sheet + policy sections.",
     "schema":[
       _sec("Cover",[_f("company","Company","text",required=True),_f("effective_date","Effective date","date"),_f("version","Version","text")]),
       _sec("Policies",[_f("policies","Policies","long_text",help_text="Enter tenant-authored policy text here."),_f("code_of_conduct","Code of conduct","long_text"),_f("time_off","Time off / leave","long_text"),_f("benefits","Benefits","long_text")]),
       _sec("Acknowledgement",[_f("employee_name","Employee name","text"),_f("signature","Employee signature","signature")]),
     ]},
    {"code":"service_agreement","title":"Service Agreement","category":"documents","allowed_roles":ADMIN,
     "description":"Recurring-service contract between tenant and customer.",
     "schema":[
       _sec("Parties",[_f("provider","Service provider","text",required=True),_f("customer","Customer","text",required=True),_f("effective_date","Effective date","date",required=True)]),
       _sec("Terms",[_f("service_scope","Scope of service","long_text",required=True),_f("frequency","Frequency","select",options=["Weekly","Bi-weekly","Monthly"]),_f("price_per_visit","Price per visit","number"),_f("term_months","Term (months)","number"),_f("cancel_notice_days","Cancellation notice (days)","number")]),
       _sec("Signatures",[_f("provider_sig","Provider signature","signature"),_f("customer_sig","Customer signature","signature")]),
     ]},
    {"code":"customer_welcome_packet","title":"Customer Welcome Packet","category":"documents","allowed_roles":ADMIN,
     "description":"First-visit welcome and expectations letter.",
     "schema":[
       _sec("Welcome",[_f("customer","Customer name","text",required=True),_f("service_start","Service start date","date")]),
       _sec("What to expect",[_f("visit_day","Typical visit day","text"),_f("visit_window","Time window","text"),_f("what_we_do","What we do each visit","long_text"),_f("what_we_dont","What is not included","long_text")]),
       _sec("Contact",[_f("office_phone","Office phone","text"),_f("emergency_contact","Emergency contact","text")]),
     ]},
    {"code":"job_posting_template","title":"Job Posting Template","category":"documents","allowed_roles":ADMIN,
     "description":"Reusable job listing skeleton for hiring.",
     "schema":[
       _sec("Position",[_f("job_title","Job title","text",required=True),_f("department","Department","select",options=["Pool","Landscaping","Both","Office"]),_f("location","Location","text")]),
       _sec("Content",[_f("summary","Summary","long_text",required=True),_f("responsibilities","Responsibilities","long_text",required=True),_f("qualifications","Qualifications","long_text",required=True),_f("comp_range","Compensation range","text")]),
       _sec("Apply",[_f("apply_email","Apply to","text"),_f("close_date","Application close date","date")]),
     ]},
    {"code":"chemical_safety_card","title":"Chemical Safety Card","category":"documents","allowed_roles":ADMIN_TECHS,
     "description":"Portable safety reference card per chemical carried on truck.",
     "schema":[
       _sec("Chemical",[_f("name","Chemical name","text",required=True),_f("cas_number","CAS number","text"),_f("hazard_class","Hazard class","text")]),
       _sec("Handling",[_f("ppe_required","Required PPE","long_text"),_f("first_aid","First aid","long_text"),_f("spill_response","Spill response","long_text"),_f("storage","Storage requirements","long_text")]),
       _sec("Contacts",[_f("poison_control","Poison control phone","text",default="1-800-222-1222"),_f("sds_url","SDS URL","text")]),
     ]},
    {"code":"complaint_response_template","title":"Complaint Response Template","category":"documents","allowed_roles":ADMIN,
     "description":"Structured customer-complaint response worksheet.",
     "schema":[
       _sec("Complaint",[_f("customer","Customer","text",required=True),_f("date_received","Date received","date",required=True),_f("channel","Channel","select",options=["Phone","Email","In-person","Text","Review site"]),_f("summary","Complaint summary","long_text",required=True)]),
       _sec("Response",[_f("assigned_to","Assigned to","text"),_f("resolution","Resolution offered","long_text"),_f("follow_up_date","Follow-up date","date")]),
       _sec("Sign-off",[_f("resolver","Resolver","text"),_f("signature","Signature","signature")]),
     ]},
    {"code":"customer_satisfaction_survey","title":"Customer Satisfaction Survey","category":"documents","allowed_roles":ADMIN,
     "description":"Post-visit or annual satisfaction survey form.",
     "schema":[
       _sec("Customer",[_f("customer","Customer name","text"),_f("date","Date","date")]),
       _sec("Ratings",[_f("overall","Overall satisfaction (1-5)","number",min=1,max=5),_f("timeliness","Timeliness (1-5)","number",min=1,max=5),_f("professionalism","Professionalism (1-5)","number",min=1,max=5),_f("quality","Quality of work (1-5)","number",min=1,max=5)]),
       _sec("Comments",[_f("comments","Comments","long_text"),_f("would_refer","Would you refer us?","checkbox")]),
     ]},
    {"code":"subcontractor_agreement","title":"Subcontractor Agreement","category":"documents","allowed_roles":ADMIN,
     "description":"1099-style subcontractor scope + terms.",
     "schema":[
       _sec("Parties",[_f("contractor","Contractor (tenant)","text",required=True),_f("subcontractor","Subcontractor","text",required=True),_f("effective_date","Effective date","date",required=True)]),
       _sec("Scope",[_f("scope","Scope of work","long_text",required=True),_f("rate","Rate","text"),_f("payment_terms","Payment terms","long_text")]),
       _sec("Signatures",[_f("contractor_sig","Contractor signature","signature"),_f("sub_sig","Subcontractor signature","signature")]),
     ]},

    # ═══ 23. Incident Report Form (rich)
    {"code":"incident_report_form","title":"Incident Report Form","category":"documents","allowed_roles":ADMIN_TECHS,
     "description":"Field-safety incident capture and follow-up log.",
     "schema":[
       _sec("Incident",[_f("date","Date","date",required=True),_f("time","Time","text"),_f("location","Location","long_text",required=True),_f("incident_type","Incident type","select",options=["Injury","Property damage","Chemical exposure","Vehicle","Near-miss","Other"])]),
       _sec("People Involved",[_f("people","","table",columns=[{"key":"name","label":"Name"},{"key":"role","label":"Role"},{"key":"phone","label":"Phone"},{"key":"injured","label":"Injured"}])]),
       _sec("Description",[_f("what_happened","What happened","long_text",required=True),_f("contributing_factors","Contributing factors","long_text")]),
       _sec("Actions Taken",[_f("actions","Actions taken on-scene","long_text",required=True)]),
       _sec("Follow-up",[_f("follow_up_required","Follow-up required?","checkbox"),_f("follow_up_notes","Follow-up notes","long_text"),_f("reported_to_authorities","Reported to authorities?","checkbox")]),
       _sec("Reporter",[_f("reporter_name","Reporter","text",required=True),_f("signature","Reporter signature","signature")]),
     ]},
]


# ─── IP-safety blacklist (word-boundary regex) ───────────────────────
IP_BLACKLIST_REGEX = [
    r"\breproduced with permission\b",
    r"\bcopyright pooldial\b",
    r"\bcopyright cpo\b",
    r"\b\u00a9 pooldial\b",
    r"\ball rights reserved\b",
    r"\bexcerpted from\b",
]


def _blacklist_check(templates):
    for t in templates:
        # scan title + description + help_text + labels — anywhere text lives.
        blob = json.dumps(t, ensure_ascii=False).lower()
        for pat in IP_BLACKLIST_REGEX:
            if re.search(pat, blob):
                raise SystemExit(f"IP-SAFETY VIOLATION in template '{t['code']}': matches '{pat}'")


async def _seed_to_db(templates):
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc).isoformat()
    for t in templates:
        existing = await db.template_definitions.find_one(
            {"code": t["code"], "is_system": True}, {"_id": 0, "id": 1})
        doc = {**t,
                "is_system": True,
                "tenant_id": None,
                "version": 1,
                "created_at": now,
                "updated_at": now,
                "id": (existing or {}).get("id") or str(uuid.uuid4())}
        await db.template_definitions.update_one(
            {"code": t["code"], "is_system": True}, {"$set": doc}, upsert=True)
    # indexes
    await db.template_definitions.create_index("code")
    await db.template_definitions.create_index([("tenant_id", 1), ("code", 1)])
    await db.template_instances.create_index([("tenant_id", 1), ("template_code", 1)])
    await db.template_instances.create_index([("tenant_id", 1), ("status", 1)])
    client.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    _blacklist_check(TEMPLATES)
    cats = {}
    for t in TEMPLATES: cats[t["category"]] = cats.get(t["category"], 0) + 1
    print(f"Templates ready: {len(TEMPLATES)}")
    for c, n in sorted(cats.items()):
        print(f"  {c}: {n}")
    if args.commit:
        asyncio.run(_seed_to_db(TEMPLATES))
        print("Committed.")
    else:
        print("\nDRY-RUN — no database writes. Pass --commit to seed.")


if __name__ == "__main__":
    main()
