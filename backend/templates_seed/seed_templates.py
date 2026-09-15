"""Phase 1 · Templates Library — seed 23 system templates.

Phase 4 · Batch A update: 20 compact templates expanded to full
schemas (4-6 sections, 12-25 fields, tables + signatures where the
document type calls for them). The three previously-rich templates
(Truck Inventory Checklist, Water Chemistry Log, Incident Report Form)
are unchanged.

All content is 100% original in-house wording. Only category names +
template titles mirror pooldial.com/resources/templates; no template
body, prompts, or instructions are copied. Enforced by the IP-safety
blacklist scan at the end.

Run:
  python3 templates_seed/seed_templates.py           # dry-run, no writes
  python3 templates_seed/seed_templates.py --commit  # upsert to Mongo
"""
from __future__ import annotations
import argparse, asyncio, json, os, re, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

# Shared blacklist scanner + upsert helper. Support direct-file invocation.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from training_seed.seed_common import (  # type: ignore
        run_blacklist_scan, upsert_template_definition,
    )
except ImportError:
    from ..training_seed.seed_common import (  # type: ignore
        run_blacklist_scan, upsert_template_definition,
    )


def _f(key, label, type_, **kw):
    d = {"key": key, "label": label, "type": type_, "required": kw.pop("required", False)}
    for k in ("help_text","default","min","max","options","columns"):
        if k in kw: d[k] = kw[k]
    return d


def _sec(title, fields): return {"title": title, "fields": fields}


ADMIN = ["admin","super_admin"]
ADMIN_TECHS = ["admin","super_admin","pool_tech","landscape_tech"]

# Phase 4 · Batch A — Deliverable 3 flag. Definitions marked with
# `is_customer_facing: True` gain a "Share to Customer Portal" action
# on the admin fill screen once the instance is finalized.
CUSTOMER_FACING_CODES = {
    "service_agreement",
    "customer_welcome_packet",
    "customer_satisfaction_survey",
    "subcontractor_agreement",
    "incident_report_form",
    "complaint_response_template",
}


# ─── 23 templates ────────────────────────────────────────────────────
TEMPLATES = [
    # ═══ 1. Truck Inventory Checklist (already rich — unchanged)
    {"code":"truck_inventory_checklist","title":"Truck Inventory Checklist","category":"pricing_money","allowed_roles":ADMIN_TECHS,
     "description":"Daily pre-route inventory verification for service trucks.",
     "schema":[
       _sec("Vehicle Info",[_f("truck_id","Truck ID","text",required=True),_f("driver","Driver","text",required=True),_f("date","Date","date",required=True),_f("odometer","Odometer","number")]),
       _sec("Chemicals On Board",[_f("chemicals","","table",columns=[{"key":"item","label":"Chemical"},{"key":"qty","label":"Qty","type":"number"},{"key":"unit","label":"Unit"},{"key":"min_par","label":"Min Par","type":"number"},{"key":"restock","label":"Restock Needed","type":"checkbox"}])]),
       _sec("Tools",[_f("tools","","table",columns=[{"key":"item","label":"Tool"},{"key":"present","label":"Present","type":"checkbox"},{"key":"condition","label":"Condition"}])]),
       _sec("Safety",[_f("fire_ext","Fire extinguisher charged","checkbox"),_f("first_aid","First-aid kit stocked","checkbox"),_f("spill_kit","Spill kit present","checkbox"),_f("ppe","PPE (gloves/goggles/apron) available","checkbox")]),
       _sec("Notes",[_f("notes","Notes","long_text")]),
       _sec("Sign-off",[_f("signature","Driver signature","signature")]),
     ]},

    # ═══ 2. New Customer Onboarding — EXPANDED
    {"code":"new_customer_onboarding","title":"New Customer Onboarding","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Structured intake for a new residential or commercial account.",
     "schema":[
       _sec("Contact",[
         _f("name","Full name","text",required=True),
         _f("phone","Primary phone","text",required=True),
         _f("alt_phone","Alternate phone","text"),
         _f("email","Email","text"),
         _f("preferred_contact","Preferred contact method","select",options=["Phone","Text","Email"]),
         _f("referred_by","How did you hear about us?","select",options=["Google search","Friend / neighbor","Yard sign","Social media","Postcard","Other"]),
       ]),
       _sec("Service Address",[
         _f("address","Street address","text",required=True),
         _f("city","City","text"),
         _f("zip","ZIP","text"),
         _f("subdivision","Subdivision or HOA","text"),
       ]),
       _sec("Property Details",[
         _f("pool_type","Pool type","select",options=["Residential","Commercial","Landscape only","Other"]),
         _f("pool_gallons","Pool gallons","number",min=0),
         _f("weekly_or_bi","Service frequency","select",options=["Weekly","Bi-weekly","Monthly","On-call"]),
         _f("start_date","Requested service start","date"),
       ]),
       _sec("Access",[
         _f("gate_code","Gate / access code","text"),
         _f("dog_on_property","Dog on property?","checkbox"),
         _f("dog_notes","Dog description or restraint notes","text"),
         _f("access_notes","Other access notes","long_text"),
       ]),
       _sec("Billing",[
         _f("billing_email","Billing email","text"),
         _f("billing_address","Billing address (if different)","long_text"),
         _f("billing_method","Preferred method","select",options=["Card on file","ACH","Check","Invoice"]),
         _f("auto_pay_ok","Enroll in auto-pay","checkbox"),
       ]),
       _sec("Acknowledgement",[
         _f("terms_accepted","Customer acknowledges service terms","checkbox",required=True),
         _f("signature","Customer signature","signature"),
       ]),
     ]},

    # ═══ 3. Seasonal Opening & Closing Tracker — EXPANDED
    {"code":"seasonal_opening_closing_tracker","title":"Seasonal Opening & Closing Tracker","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Roster-level tracker of properties opened, closed, or winterized in a season.",
     "schema":[
       _sec("Season",[
         _f("season","Season type","select",required=True,options=["Spring open","Fall close","Winterize","De-winterize"]),
         _f("year","Year","number",required=True,min=2000,max=2100),
         _f("scheduler","Scheduler / lead","text"),
         _f("target_start","Target start date","date"),
         _f("target_finish","Target finish date","date"),
         _f("weather_window","Weather window","text"),
       ]),
       _sec("Route Assignments",[
         _f("crews","","table",columns=[
           {"key":"crew","label":"Crew"},
           {"key":"lead_tech","label":"Lead tech"},
           {"key":"props_assigned","label":"Properties","type":"number"},
           {"key":"props_done","label":"Completed","type":"number"},
         ]),
         _f("routing_notes","Routing notes","long_text"),
       ]),
       _sec("Properties",[
         _f("rows","","table",columns=[
           {"key":"customer","label":"Customer"},
           {"key":"address","label":"Address"},
           {"key":"scheduled","label":"Scheduled date","type":"date"},
           {"key":"completed","label":"Completed date","type":"date"},
           {"key":"tech","label":"Tech"},
           {"key":"invoiced","label":"Invoiced","type":"checkbox"},
           {"key":"balance_due","label":"Balance due","type":"number"},
         ]),
         _f("total_properties","Total properties","number",min=0),
         _f("total_completed","Total completed","number",min=0),
       ]),
       _sec("Materials Consumed",[
         _f("materials","","table",columns=[
           {"key":"item","label":"Item"},
           {"key":"qty","label":"Qty","type":"number"},
           {"key":"unit","label":"Unit"},
           {"key":"unit_cost","label":"Unit cost","type":"number"},
         ]),
         _f("supplier","Primary supplier","text"),
         _f("po_number","Purchase order #","text"),
       ]),
       _sec("Notes",[
         _f("issues","Issues encountered","long_text"),
         _f("next_season_notes","Notes for next season","long_text"),
         _f("closed_by","Reviewed by","text"),
       ]),
     ]},

    # ═══ 4. Capacity Planner — EXPANDED
    {"code":"capacity_planner","title":"Capacity Planner","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Weekly route capacity versus active-customer load, per crew and per tech.",
     "schema":[
       _sec("Window",[
         _f("week_of","Week of","date",required=True),
         _f("prepared_by","Prepared by","text"),
         _f("service_line","Service line","select",options=["Pool","Landscape","Both"]),
       ]),
       _sec("Demand",[
         _f("active_accounts","Active accounts this week","number",min=0),
         _f("weekly_accounts","Weekly-frequency accounts","number",min=0),
         _f("biweekly_accounts","Bi-weekly accounts","number",min=0),
         _f("one_off_jobs","One-off jobs booked","number",min=0),
         _f("waitlisted","Waitlisted accounts","number",min=0),
       ]),
       _sec("Techs",[
         _f("rows","","table",columns=[
           {"key":"tech","label":"Tech"},
           {"key":"target_stops","label":"Target stops/day","type":"number"},
           {"key":"actual_stops","label":"Actual stops/day","type":"number"},
           {"key":"drive_time_hrs","label":"Drive hrs/day","type":"number"},
           {"key":"open_slots","label":"Open slots","type":"number"},
         ]),
       ]),
       _sec("Coverage Risks",[
         _f("pto_this_week","PTO / call-outs this week","long_text"),
         _f("weather_risk","Weather risk","select",options=["None","Rain","High wind","Heat advisory","Freeze"]),
         _f("mitigation_plan","Mitigation plan","long_text"),
       ]),
       _sec("Notes",[
         _f("notes","Notes","long_text"),
       ]),
     ]},

    # ═══ 5. Equipment Maintenance Schedule — EXPANDED
    {"code":"equipment_maintenance_schedule","title":"Equipment Maintenance Schedule","category":"pricing_money","allowed_roles":ADMIN_TECHS,
     "description":"Preventive-maintenance schedule for pumps, filters, salt cells, heaters, and vehicles.",
     "schema":[
       _sec("Header",[
         _f("period","Reporting period","text",required=True),
         _f("prepared_by","Prepared by","text"),
         _f("shop_location","Shop / yard location","text"),
         _f("review_date","Next review date","date"),
       ]),
       _sec("Pool Equipment",[
         _f("pool_rows","","table",columns=[
           {"key":"equipment","label":"Equipment"},
           {"key":"customer","label":"Customer / location"},
           {"key":"last_serviced","label":"Last serviced","type":"date"},
           {"key":"interval_months","label":"Interval (mo)","type":"number"},
           {"key":"next_due","label":"Next due","type":"date"},
           {"key":"notes","label":"Notes"},
         ]),
         _f("pool_open_items","Open pool-side items","number",min=0),
       ]),
       _sec("Landscape Equipment",[
         _f("landscape_rows","","table",columns=[
           {"key":"equipment","label":"Equipment"},
           {"key":"hours","label":"Hours on machine","type":"number"},
           {"key":"last_serviced","label":"Last serviced","type":"date"},
           {"key":"next_due","label":"Next due","type":"date"},
           {"key":"status","label":"Status"},
         ]),
         _f("landscape_open_items","Open landscape items","number",min=0),
       ]),
       _sec("Vehicles",[
         _f("vehicles","","table",columns=[
           {"key":"vehicle","label":"Vehicle"},
           {"key":"odometer","label":"Odometer","type":"number"},
           {"key":"oil_change_due","label":"Oil due at","type":"number"},
           {"key":"insp_due","label":"Insp. due","type":"date"},
         ]),
         _f("vehicles_pulled_from_service","Vehicles pulled from service","number",min=0),
       ]),
       _sec("Follow-ups",[
         _f("parts_ordered","Parts ordered","long_text"),
         _f("estimated_downtime","Estimated downtime","text"),
         _f("assigned_to","Assigned to","text"),
         _f("supervisor_ack","Supervisor acknowledged","checkbox"),
       ]),
     ]},

    # ═══ 6. Lead Tracking Sheet — EXPANDED
    {"code":"lead_tracking_sheet","title":"Lead Tracking Sheet","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Sales pipeline snapshot from initial contact through won or lost.",
     "schema":[
       _sec("Period",[
         _f("period","Reporting period","text",required=True),
         _f("owner","Pipeline owner","text"),
         _f("region","Region / territory","text"),
       ]),
       _sec("Funnel Totals",[
         _f("new_leads","New leads","number",min=0),
         _f("contacted","Contacted","number",min=0),
         _f("quoted","Quoted","number",min=0),
         _f("won","Won","number",min=0),
         _f("lost","Lost","number",min=0),
       ]),
       _sec("Leads",[
         _f("rows","","table",columns=[
           {"key":"name","label":"Name"},
           {"key":"source","label":"Source"},
           {"key":"contacted","label":"Contacted date","type":"date"},
           {"key":"quoted","label":"Quoted","type":"checkbox"},
           {"key":"quote_amount","label":"Quote $","type":"number"},
           {"key":"status","label":"Status"},
           {"key":"next_action","label":"Next action"},
           {"key":"next_action_date","label":"Next date","type":"date"},
         ]),
       ]),
       _sec("Deal Analysis",[
         _f("hottest_source","Hottest lead source","text"),
         _f("cold_source","Coldest lead source","text"),
         _f("avg_deal_size","Average deal size","number",min=0),
       ]),
       _sec("Notes",[
         _f("notes","Notes","long_text"),
       ]),
     ]},

    # ═══ 7. Referral Program Tracker — EXPANDED
    {"code":"referral_program_tracker","title":"Referral Program Tracker","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Track customer referrals, reward eligibility, and payout status.",
     "schema":[
       _sec("Program Setup",[
         _f("program_name","Program name","text",required=True),
         _f("effective_date","Effective date","date"),
         _f("expiration_date","Expiration date","date"),
         _f("reward_type","Reward type","select",options=["Account credit","Cash","Free service visit","Gift card","Other"]),
         _f("reward_amount","Reward amount","number",min=0),
         _f("requires_paid_first_invoice","Requires paid first invoice","checkbox"),
       ]),
       _sec("Referrals",[
         _f("rows","","table",columns=[
           {"key":"referrer","label":"Referring customer"},
           {"key":"referred","label":"Referred customer"},
           {"key":"date","label":"Date","type":"date"},
           {"key":"converted","label":"Converted","type":"checkbox"},
           {"key":"first_invoice","label":"First invoice #"},
           {"key":"reward_status","label":"Reward status"},
           {"key":"paid_date","label":"Reward paid","type":"date"},
         ]),
         _f("total_referrals","Total referrals","number",min=0),
         _f("total_conversions","Total conversions","number",min=0),
       ]),
       _sec("Top Referrers",[
         _f("top_rows","","table",columns=[
           {"key":"referrer","label":"Referring customer"},
           {"key":"count","label":"# referrals","type":"number"},
           {"key":"lifetime_value","label":"Lifetime value","type":"number"},
         ]),
         _f("hall_of_fame","Hall-of-fame customer","text"),
       ]),
       _sec("Payouts",[
         _f("total_paid","Total paid this period","number",min=0),
         _f("outstanding","Outstanding rewards","number",min=0),
         _f("payout_notes","Payout notes","long_text"),
       ]),
       _sec("Notes",[
         _f("program_notes","Program notes","long_text"),
       ]),
     ]},

    # ═══ 8. Employee Time & Payroll — EXPANDED
    {"code":"employee_time_payroll","title":"Employee Time & Payroll","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Weekly hours and gross-pay summary per employee, with deductions rollup.",
     "schema":[
       _sec("Pay Period",[
         _f("pay_period","Pay period","text",required=True),
         _f("start_date","Start date","date"),
         _f("end_date","End date","date"),
         _f("payroll_date","Payroll date","date"),
         _f("processed_by","Processed by","text"),
       ]),
       _sec("Employees",[
         _f("rows","","table",columns=[
           {"key":"employee","label":"Employee"},
           {"key":"regular_hours","label":"Regular hrs","type":"number"},
           {"key":"overtime_hours","label":"OT hrs","type":"number"},
           {"key":"pto_hours","label":"PTO hrs","type":"number"},
           {"key":"rate","label":"Rate","type":"number"},
           {"key":"gross","label":"Gross","type":"number"},
         ]),
       ]),
       _sec("Deductions & Taxes",[
         _f("deductions","","table",columns=[
           {"key":"category","label":"Category"},
           {"key":"amount","label":"Amount","type":"number"},
           {"key":"notes","label":"Notes"},
         ]),
       ]),
       _sec("Totals",[
         _f("total_gross","Total gross","number",min=0),
         _f("total_deductions","Total deductions","number",min=0),
         _f("total_net","Total net","number",min=0),
       ]),
       _sec("Sign-off",[
         _f("approved_by","Approved by","text"),
         _f("approved_date","Approval date","date"),
       ]),
     ]},

    # ═══ 9. Tax Deduction Tracker — EXPANDED
    {"code":"tax_deduction_tracker","title":"Tax Deduction Tracker","category":"pricing_money","allowed_roles":ADMIN,
     "description":"Business-expense categorization worksheet for annual tax preparation.",
     "schema":[
       _sec("Header",[
         _f("tax_year","Tax year","number",required=True,min=2000,max=2100),
         _f("business_name","Business name","text",required=True),
         _f("ein","EIN / Tax ID","text"),
         _f("prepared_by","Prepared by","text"),
       ]),
       _sec("Expenses",[
         _f("rows","","table",columns=[
           {"key":"category","label":"Category"},
           {"key":"date","label":"Date","type":"date"},
           {"key":"vendor","label":"Vendor"},
           {"key":"amount","label":"Amount","type":"number"},
           {"key":"deductible","label":"Deductible","type":"checkbox"},
           {"key":"receipt_on_file","label":"Receipt on file","type":"checkbox"},
           {"key":"notes","label":"Notes"},
         ]),
       ]),
       _sec("Vehicle Mileage",[
         _f("mileage_rows","","table",columns=[
           {"key":"vehicle","label":"Vehicle"},
           {"key":"business_miles","label":"Business mi","type":"number"},
           {"key":"personal_miles","label":"Personal mi","type":"number"},
           {"key":"start_odo","label":"Start odo","type":"number"},
           {"key":"end_odo","label":"End odo","type":"number"},
         ]),
       ]),
       _sec("Home Office",[
         _f("home_sqft","Home sqft","number",min=0),
         _f("office_sqft","Office sqft","number",min=0),
         _f("utilities_total","Utilities total","number",min=0),
         _f("home_office_notes","Notes","long_text"),
       ]),
       _sec("Rollup",[
         _f("total_deductions","Total deductions","number",min=0),
         _f("cpa_notes","CPA notes","long_text"),
       ]),
     ]},

    # ═══ 10. Chemical Cost Tracker — EXPANDED
    {"code":"chemical_cost_tracker","title":"Chemical Cost Tracker","category":"operations_checklists","allowed_roles":ADMIN,
     "description":"Cost-per-pool chemical usage tracking and vendor comparison.",
     "schema":[
       _sec("Header",[
         _f("period","Reporting period","text",required=True),
         _f("prepared_by","Prepared by","text"),
         _f("target_cost_per_stop","Target cost / stop","number",min=0),
         _f("budget_ceiling","Budget ceiling","number",min=0),
       ]),
       _sec("Purchases",[
         _f("rows","","table",columns=[
           {"key":"chemical","label":"Chemical"},
           {"key":"qty","label":"Qty","type":"number"},
           {"key":"unit","label":"Unit"},
           {"key":"unit_cost","label":"Unit cost","type":"number"},
           {"key":"total","label":"Total","type":"number"},
           {"key":"vendor","label":"Vendor"},
           {"key":"date","label":"Date","type":"date"},
         ]),
         _f("total_purchases","Total purchases","number",min=0),
       ]),
       _sec("Vendor Comparison",[
         _f("vendor_rows","","table",columns=[
           {"key":"vendor","label":"Vendor"},
           {"key":"chemical","label":"Chemical"},
           {"key":"price_this_month","label":"Price this month","type":"number"},
           {"key":"price_last_month","label":"Price last month","type":"number"},
           {"key":"delta_pct","label":"Δ %","type":"number"},
         ]),
         _f("preferred_vendor","Preferred vendor","text"),
       ]),
       _sec("Usage per Stop",[
         _f("total_pool_visits","Total pool visits","number",min=0),
         _f("total_chemical_cost","Total chemical cost","number",min=0),
         _f("actual_cost_per_stop","Actual cost / stop","number",min=0),
         _f("variance_pct","Variance vs target %","number"),
       ]),
       _sec("Notes",[
         _f("notes","Notes","long_text"),
         _f("reviewed_by","Reviewed by","text"),
       ]),
     ]},

    # ═══ 11. Water Chemistry Log (unchanged — already rich)
    {"code":"water_chemistry_log","title":"Water Chemistry Log","category":"chemicals_chemistry","allowed_roles":ADMIN_TECHS,
     "description":"Per-visit water chemistry readings and chemicals added.",
     "schema":[
       _sec("Pool Info",[_f("customer","Customer","text",required=True),_f("pool_id","Pool ID","text"),_f("date","Date","date",required=True),_f("visit_type","Visit type","select",options=["Weekly","Bi-weekly","On-call","Opening","Closing"])]),
       _sec("Readings",[_f("readings","","table",columns=[{"key":"time","label":"Time"},{"key":"free_chlorine","label":"Free Cl (ppm)","type":"number"},{"key":"ph","label":"pH","type":"number"},{"key":"alkalinity","label":"Alk (ppm)","type":"number"},{"key":"cya","label":"CYA (ppm)","type":"number"},{"key":"calcium_hardness","label":"CaHardness (ppm)","type":"number"},{"key":"temp_f","label":"Temp (°F)","type":"number"}])]),
       _sec("Chemicals Added",[_f("chems","","table",columns=[{"key":"chemical","label":"Chemical"},{"key":"amount","label":"Amount"},{"key":"unit","label":"Unit"}])]),
       _sec("Observations",[_f("clarity","Water clarity","select",options=["Clear","Hazy","Cloudy","Green"]),_f("issues","Issues observed","long_text")]),
       _sec("Technician",[_f("tech_name","Technician","text"),_f("signature","Signature","signature")]),
     ]},

    # ═══ 12. CPO Commercial Pool Log — EXPANDED
    {"code":"cpo_commercial_pool_log","title":"CPO Commercial Pool Log","category":"chemicals_chemistry","allowed_roles":ADMIN_TECHS,
     "description":"CPO-compliant commercial pool operations log with twice-daily readings.",
     "schema":[
       _sec("Facility",[
         _f("facility","Facility","text",required=True),
         _f("facility_id","Facility ID / permit #","text"),
         _f("date","Date","date",required=True),
         _f("cpo_operator","CPO operator on duty","text",required=True),
         _f("cpo_cert","CPO certification #","text"),
         _f("hours_open","Hours open today","text"),
       ]),
       _sec("Readings",[
         _f("readings","","table",columns=[
           {"key":"time","label":"Time"},
           {"key":"free_chlorine","label":"Free Cl","type":"number"},
           {"key":"combined_chlorine","label":"Combined Cl","type":"number"},
           {"key":"ph","label":"pH","type":"number"},
           {"key":"alkalinity","label":"Alk","type":"number"},
           {"key":"flow_gpm","label":"Flow (GPM)","type":"number"},
           {"key":"filter_psi","label":"Filter PSI","type":"number"},
           {"key":"bathers","label":"Bathers","type":"number"},
         ]),
       ]),
       _sec("Chemicals Fed",[
         _f("chems","","table",columns=[
           {"key":"chemical","label":"Chemical"},
           {"key":"start_reading","label":"Start reading","type":"number"},
           {"key":"end_reading","label":"End reading","type":"number"},
           {"key":"fed_amount","label":"Fed amount"},
         ]),
       ]),
       _sec("Actions & Incidents",[
         _f("actions","Adjustments made","long_text"),
         _f("closure_events","Closure events during shift","long_text"),
         _f("chemical_delivery","Chemical delivery received","checkbox"),
       ]),
       _sec("Facility Checks",[
         _f("safety_signs_posted","Safety signs posted","checkbox"),
         _f("rescue_equipment","Rescue equipment on deck","checkbox"),
         _f("emergency_phone_working","Emergency phone tested","checkbox"),
         _f("chemical_room_locked","Chemical room secured at close","checkbox"),
       ]),
       _sec("Sign-off",[
         _f("signature","Operator signature","signature"),
       ]),
     ]},

    # ═══ 13. Commercial Pool Log Book — EXPANDED
    {"code":"commercial_pool_log_book","title":"Commercial Pool Log Book","category":"operations_checklists","allowed_roles":ADMIN_TECHS,
     "description":"Monthly rollup log for a commercial pool operation.",
     "schema":[
       _sec("Header",[
         _f("facility","Facility","text",required=True),
         _f("permit_number","Health permit #","text"),
         _f("month","Month","text",required=True),
         _f("year","Year","number",required=True,min=2000,max=2100),
         _f("manager_on_record","Manager on record","text"),
       ]),
       _sec("Daily Entries",[
         _f("entries","","table",columns=[
           {"key":"date","label":"Date","type":"date"},
           {"key":"open_time","label":"Open"},
           {"key":"close_time","label":"Close"},
           {"key":"free_cl","label":"Free Cl","type":"number"},
           {"key":"ph","label":"pH","type":"number"},
           {"key":"alk","label":"Alk","type":"number"},
           {"key":"psi","label":"Filter PSI","type":"number"},
           {"key":"bathers","label":"Bathers","type":"number"},
           {"key":"initials","label":"Initials"},
         ]),
         _f("total_bathers_month","Total bathers this month","number",min=0),
       ]),
       _sec("Backwashes & Cleanings",[
         _f("backwashes","","table",columns=[
           {"key":"date","label":"Date","type":"date"},
           {"key":"action","label":"Action"},
           {"key":"initials","label":"Initials"},
         ]),
         _f("backwash_count","Backwashes this month","number",min=0),
       ]),
       _sec("Inspections",[
         _f("insp_rows","","table",columns=[
           {"key":"date","label":"Date","type":"date"},
           {"key":"inspector","label":"Inspector"},
           {"key":"result","label":"Result"},
           {"key":"notes","label":"Notes"},
         ]),
         _f("open_violations","Open violations","number",min=0),
       ]),
       _sec("Month-end Sign-off",[
         _f("supervisor","Supervisor","text"),
         _f("supervisor_notes","Supervisor notes","long_text"),
         _f("signature","Supervisor signature","signature"),
       ]),
     ]},

    # ═══ 14. Residential Pool Log Book — EXPANDED
    {"code":"residential_pool_log_book","title":"Residential Pool Log Book","category":"operations_checklists","allowed_roles":ADMIN_TECHS,
     "description":"Homeowner-friendly monthly log for a residential pool.",
     "schema":[
       _sec("Pool",[
         _f("customer","Customer","text",required=True),
         _f("address","Address","text"),
         _f("pool_gallons","Pool gallons","number",min=0),
         _f("month","Month","text",required=True),
         _f("year","Year","number",required=True,min=2000,max=2100),
       ]),
       _sec("Weekly Entries",[
         _f("entries","","table",columns=[
           {"key":"date","label":"Date","type":"date"},
           {"key":"free_cl","label":"Free Cl","type":"number"},
           {"key":"ph","label":"pH","type":"number"},
           {"key":"alk","label":"Alk","type":"number"},
           {"key":"vacuumed","label":"Vacuumed","type":"checkbox"},
           {"key":"skimmed","label":"Skimmed","type":"checkbox"},
           {"key":"basket_emptied","label":"Basket","type":"checkbox"},
           {"key":"notes","label":"Notes"},
         ]),
       ]),
       _sec("Chemicals Added",[
         _f("chems","","table",columns=[
           {"key":"date","label":"Date","type":"date"},
           {"key":"chemical","label":"Chemical"},
           {"key":"amount","label":"Amount"},
         ]),
       ]),
       _sec("Equipment Notes",[
         _f("pump_ok","Pump running quietly","checkbox"),
         _f("filter_psi","Filter PSI trend","text"),
         _f("equipment_issues","Equipment issues","long_text"),
       ]),
       _sec("Tech Sign-off",[
         _f("tech","Tech","text"),
         _f("signature","Tech signature","signature"),
       ]),
     ]},

    # ═══ 15. Employee Handbook — EXPANDED
    {"code":"employee_handbook","title":"Employee Handbook","category":"documents","allowed_roles":ADMIN,
     "description":"Company handbook cover sheet with policy sections and employee acknowledgement.",
     "schema":[
       _sec("Cover",[
         _f("company","Company","text",required=True),
         _f("effective_date","Effective date","date",required=True),
         _f("version","Handbook version","text"),
         _f("hr_contact","HR contact","text"),
       ]),
       _sec("Welcome & Mission",[
         _f("welcome_message","Welcome message","long_text",help_text="Written by the tenant in their own voice."),
         _f("mission","Mission statement","long_text"),
         _f("values","Core values","long_text"),
       ]),
       _sec("Policies",[
         _f("code_of_conduct","Code of conduct","long_text"),
         _f("attendance","Attendance & tardiness","long_text"),
         _f("dress_code","Uniform & dress code","long_text"),
         _f("safety_policy","Safety & PPE policy","long_text"),
         _f("harassment_policy","Anti-harassment policy","long_text"),
       ]),
       _sec("Time Off & Benefits",[
         _f("time_off","Time off / leave","long_text"),
         _f("holidays","Recognized holidays","long_text"),
         _f("benefits","Benefits overview","long_text"),
       ]),
       _sec("Discipline & Termination",[
         _f("discipline","Progressive discipline","long_text"),
         _f("termination","Termination policy","long_text"),
         _f("at_will","At-will employment acknowledged","checkbox"),
       ]),
       _sec("Acknowledgement",[
         _f("employee_name","Employee name","text",required=True),
         _f("hire_date","Hire date","date"),
         _f("received_copy","Employee received a copy of this handbook","checkbox",required=True),
         _f("signature","Employee signature","signature"),
       ]),
     ]},

    # ═══ 16. Service Agreement — EXPANDED (customer-facing)
    {"code":"service_agreement","title":"Service Agreement","category":"documents","allowed_roles":ADMIN,
     "description":"Recurring-service contract between the tenant and a customer.",
     "schema":[
       _sec("Parties",[
         _f("provider","Service provider","text",required=True),
         _f("provider_address","Provider address","long_text"),
         _f("provider_license","License / certification #","text"),
         _f("customer","Customer name","text",required=True),
         _f("customer_address","Customer address","long_text",required=True),
         _f("effective_date","Effective date","date",required=True),
       ]),
       _sec("Scope",[
         _f("service_scope","Scope of service","long_text",required=True),
         _f("frequency","Frequency","select",required=True,options=["Weekly","Bi-weekly","Monthly","Seasonal"]),
         _f("day_of_week","Preferred day of week","select",options=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Any"]),
         _f("visit_window","Typical visit window","text"),
         _f("exclusions","Exclusions","long_text"),
       ]),
       _sec("Pricing & Terms",[
         _f("price_per_visit","Price per visit","number",min=0,required=True),
         _f("billing_frequency","Billing frequency","select",options=["Per visit","Monthly","Quarterly","Annual"]),
         _f("chemical_billing","Chemicals billed separately","checkbox"),
         _f("term_months","Term (months)","number",min=1),
         _f("cancel_notice_days","Cancellation notice (days)","number",min=0),
         _f("late_fee","Late fee","text"),
       ]),
       _sec("Access & Safety",[
         _f("gate_code","Gate / access code","text"),
         _f("dog_notes","Dog / pet notes","text"),
         _f("liability_disclaimer","Liability disclaimer accepted","checkbox"),
       ]),
       _sec("Signatures",[
         _f("provider_name","Provider signer name","text"),
         _f("provider_sig","Provider signature","signature"),
         _f("customer_signer","Customer signer name","text"),
         _f("customer_sig","Customer signature","signature"),
       ]),
     ]},

    # ═══ 17. Customer Welcome Packet — EXPANDED (customer-facing)
    {"code":"customer_welcome_packet","title":"Customer Welcome Packet","category":"documents","allowed_roles":ADMIN,
     "description":"First-visit welcome letter with expectations and contact info for a new customer.",
     "schema":[
       _sec("Customer",[
         _f("customer","Customer name","text",required=True),
         _f("service_address","Service address","long_text"),
         _f("account_number","Account #","text"),
         _f("service_start","Service start date","date"),
       ]),
       _sec("What To Expect",[
         _f("visit_day","Typical visit day","text"),
         _f("visit_window","Time window","text"),
         _f("what_we_do","What we do each visit","long_text",required=True),
         _f("what_we_dont","What is not included","long_text"),
         _f("weather_policy","Weather policy","long_text"),
         _f("holiday_policy","Holiday policy","long_text"),
       ]),
       _sec("Access & Prep",[
         _f("gate_code","Gate / access code","text"),
         _f("dogs","Dogs on property","text"),
         _f("pool_ready_checklist","Please have the pool ready by removing…","long_text"),
       ]),
       _sec("Contacts",[
         _f("office_phone","Office phone","text"),
         _f("emergency_contact","Emergency after-hours contact","text"),
         _f("billing_email","Billing email","text"),
         _f("technician_intro","Your primary technician","text"),
       ]),
       _sec("Onboarding Checklist",[
         _f("card_on_file","Card on file","checkbox"),
         _f("access_confirmed","Access confirmed","checkbox"),
         _f("photos_taken","Property photos taken","checkbox"),
         _f("intro_email_sent","Intro email sent","checkbox"),
       ]),
       _sec("Signatures",[
         _f("welcomed_by","Welcomed by","text"),
         _f("signature","Team signature","signature"),
       ]),
     ]},

    # ═══ 18. Job Posting Template — EXPANDED
    {"code":"job_posting_template","title":"Job Posting Template","category":"documents","allowed_roles":ADMIN,
     "description":"Reusable job listing skeleton for hiring new team members.",
     "schema":[
       _sec("Position",[
         _f("job_title","Job title","text",required=True),
         _f("department","Department","select",options=["Pool","Landscaping","Both","Office","Sales"]),
         _f("employment_type","Employment type","select",options=["Full-time","Part-time","Seasonal","1099 subcontractor"]),
         _f("location","Location","text"),
         _f("reports_to","Reports to","text"),
       ]),
       _sec("About the Role",[
         _f("summary","Summary","long_text",required=True),
         _f("day_in_the_life","A day in the life","long_text"),
       ]),
       _sec("Responsibilities & Requirements",[
         _f("responsibilities","Responsibilities","long_text",required=True),
         _f("qualifications","Qualifications","long_text",required=True),
         _f("physical_requirements","Physical requirements","long_text"),
         _f("driving_required","Driving required","checkbox"),
         _f("cdl_required","CDL required","checkbox"),
       ]),
       _sec("Compensation & Benefits",[
         _f("comp_range","Compensation range","text"),
         _f("bonus_structure","Bonus / incentive structure","long_text"),
         _f("benefits_offered","Benefits offered","long_text"),
       ]),
       _sec("How to Apply",[
         _f("apply_email","Apply to (email)","text",required=True),
         _f("apply_url","Apply URL","text"),
         _f("close_date","Application close date","date"),
         _f("eeo_statement","Equal-opportunity statement","long_text"),
       ]),
     ]},

    # ═══ 19. Chemical Safety Card — EXPANDED
    {"code":"chemical_safety_card","title":"Chemical Safety Card","category":"documents","allowed_roles":ADMIN_TECHS,
     "description":"Portable safety reference card kept with each chemical carried on the truck.",
     "schema":[
       _sec("Chemical Identity",[
         _f("name","Chemical name","text",required=True),
         _f("cas_number","CAS number","text"),
         _f("hazard_class","Hazard class","text"),
         _f("physical_state","Physical state","select",options=["Solid","Liquid","Gas","Granular"]),
         _f("odor","Odor","text"),
       ]),
       _sec("Hazards",[
         _f("primary_hazards","Primary hazards","long_text"),
         _f("incompatible_with","Do not mix with","long_text",required=True),
         _f("fire_explosion","Fire / explosion notes","long_text"),
       ]),
       _sec("Handling",[
         _f("ppe_required","Required PPE","long_text",required=True),
         _f("storage","Storage requirements","long_text"),
         _f("transport_notes","Vehicle transport notes","long_text"),
       ]),
       _sec("Emergency Response",[
         _f("first_aid","First aid","long_text",required=True),
         _f("spill_response","Spill response","long_text",required=True),
         _f("fire_response","Fire response","long_text"),
       ]),
       _sec("Emergency Contacts",[
         _f("poison_control","Poison control phone","text",default="1-800-222-1222"),
         _f("chemtrec","CHEMTREC phone","text",default="1-800-424-9300"),
         _f("supervisor_phone","Supervisor phone","text"),
         _f("sds_url","SDS URL","text"),
       ]),
     ]},

    # ═══ 20. Complaint Response Template — EXPANDED (customer-facing)
    {"code":"complaint_response_template","title":"Complaint Response Template","category":"documents","allowed_roles":ADMIN,
     "description":"Structured worksheet for logging and resolving a customer complaint.",
     "schema":[
       _sec("Complaint Intake",[
         _f("customer","Customer","text",required=True),
         _f("account_number","Account #","text"),
         _f("date_received","Date received","date",required=True),
         _f("channel","Channel","select",required=True,options=["Phone","Email","In-person","Text","Review site","Portal"]),
         _f("received_by","Received by","text"),
         _f("severity","Severity","select",options=["Low","Medium","High","Urgent"]),
       ]),
       _sec("Summary",[
         _f("summary","Complaint summary","long_text",required=True),
         _f("root_cause","Suspected root cause","long_text"),
         _f("visits_involved","Related visit(s)","text"),
       ]),
       _sec("Response",[
         _f("assigned_to","Assigned to","text"),
         _f("initial_response","Initial response given","long_text"),
         _f("resolution","Resolution offered","long_text"),
         _f("credit_amount","Account credit issued","number",min=0),
         _f("follow_up_date","Follow-up date","date"),
       ]),
       _sec("Outcome",[
         _f("resolved","Resolved","checkbox"),
         _f("customer_satisfied","Customer satisfied","checkbox"),
         _f("prevent_recurrence","Preventive action for recurrence","long_text"),
       ]),
       _sec("Sign-off",[
         _f("resolver","Resolver","text"),
         _f("signature","Resolver signature","signature"),
       ]),
     ]},

    # ═══ 21. Customer Satisfaction Survey — EXPANDED (customer-facing)
    {"code":"customer_satisfaction_survey","title":"Customer Satisfaction Survey","category":"documents","allowed_roles":ADMIN,
     "description":"Post-visit or annual satisfaction survey with quantitative and qualitative feedback.",
     "schema":[
       _sec("Customer",[
         _f("customer","Customer name","text",required=True),
         _f("account_number","Account #","text"),
         _f("date","Date","date"),
         _f("last_visit_date","Last visit date","date"),
         _f("survey_type","Survey type","select",options=["Post-visit","Quarterly","Annual","Cancellation exit"]),
       ]),
       _sec("Ratings (1 = Poor, 5 = Excellent)",[
         _f("overall","Overall satisfaction","number",required=True,min=1,max=5),
         _f("timeliness","Timeliness","number",min=1,max=5),
         _f("professionalism","Professionalism","number",min=1,max=5),
         _f("quality","Quality of work","number",min=1,max=5),
         _f("communication","Communication","number",min=1,max=5),
         _f("value","Value for money","number",min=1,max=5),
       ]),
       _sec("Net Promoter",[
         _f("nps","Likelihood to recommend (0-10)","number",min=0,max=10),
         _f("nps_reason","Why did you pick that number?","long_text"),
       ]),
       _sec("Feedback",[
         _f("best_thing","What did we do best?","long_text"),
         _f("improve","What could we improve?","long_text"),
         _f("technician_shoutout","Technician shout-out","text"),
       ]),
       _sec("Follow-up",[
         _f("would_refer","Would you refer us?","checkbox"),
         _f("ok_to_publish_review","OK to publish this feedback as a public review","checkbox"),
         _f("wants_callback","Wants a callback","checkbox"),
         _f("callback_phone","Callback phone","text"),
       ]),
     ]},

    # ═══ 22. Subcontractor Agreement — EXPANDED (customer-facing / partner-facing)
    {"code":"subcontractor_agreement","title":"Subcontractor Agreement","category":"documents","allowed_roles":ADMIN,
     "description":"1099-style subcontractor scope and payment terms.",
     "schema":[
       _sec("Parties",[
         _f("contractor","Contractor (tenant)","text",required=True),
         _f("contractor_address","Contractor address","long_text"),
         _f("subcontractor","Subcontractor legal name","text",required=True),
         _f("subcontractor_business","Subcontractor DBA","text"),
         _f("subcontractor_address","Subcontractor address","long_text"),
         _f("effective_date","Effective date","date",required=True),
         _f("expiration_date","Expiration date","date"),
       ]),
       _sec("Scope of Work",[
         _f("scope","Scope of work","long_text",required=True),
         _f("service_area","Service area","text"),
         _f("start_date","Start date","date"),
         _f("target_completion","Target completion","date"),
       ]),
       _sec("Compensation",[
         _f("rate_type","Rate type","select",options=["Hourly","Per job","Percent of contract","Fixed bid"]),
         _f("rate","Rate","text"),
         _f("payment_terms","Payment terms","long_text"),
         _f("invoicing_frequency","Invoicing frequency","select",options=["Weekly","Bi-weekly","Monthly","On completion"]),
       ]),
       _sec("Compliance",[
         _f("insurance_required","Insurance required","checkbox"),
         _f("insurance_cert_on_file","COI on file","checkbox"),
         _f("w9_on_file","W-9 on file","checkbox"),
         _f("license_required","License required","checkbox"),
         _f("license_number","License #","text"),
         _f("independent_contractor_ack","Independent-contractor status acknowledged","checkbox",required=True),
       ]),
       _sec("Signatures",[
         _f("contractor_signer","Contractor signer","text"),
         _f("contractor_sig","Contractor signature","signature"),
         _f("sub_signer","Subcontractor signer","text"),
         _f("sub_sig","Subcontractor signature","signature"),
       ]),
     ]},

    # ═══ 23. Incident Report Form (unchanged — already rich, customer-facing flag added below)
    {"code":"incident_report_form","title":"Incident Report Form","category":"documents","allowed_roles":ADMIN_TECHS,
     "description":"Field-safety incident capture and follow-up log.",
     "schema":[
       _sec("Incident",[_f("date","Date","date",required=True),_f("time","Time","text"),_f("location","Location","long_text",required=True),_f("incident_type","Incident type","select",options=["Injury","Property damage","Chemical exposure","Vehicle","Near-miss","Other"])]),
       _sec("People Involved",[_f("people","","table",columns=[{"key":"name","label":"Name"},{"key":"role","label":"Role"},{"key":"phone","label":"Phone"},{"key":"injured","label":"Injured","type":"checkbox"}])]),
       _sec("Description",[_f("what_happened","What happened","long_text",required=True),_f("contributing_factors","Contributing factors","long_text")]),
       _sec("Actions Taken",[_f("actions","Actions taken on-scene","long_text",required=True)]),
       _sec("Follow-up",[_f("follow_up_required","Follow-up required?","checkbox"),_f("follow_up_notes","Follow-up notes","long_text"),_f("reported_to_authorities","Reported to authorities?","checkbox")]),
       _sec("Reporter",[_f("reporter_name","Reporter","text",required=True),_f("signature","Reporter signature","signature")]),
     ]},
]


# Attach `is_customer_facing: true` to the 6 customer/partner-facing codes.
for _t in TEMPLATES:
    if _t["code"] in CUSTOMER_FACING_CODES:
        _t["is_customer_facing"] = True


# ─── IP-safety blacklist (word-boundary regex) ───────────────────────
# Templates-specific extras layered on top of shared DEFAULT_BLACKLIST
# in seed_common. Kept here so the template author sees them in-file.
_TEMPLATE_EXTRAS = [re.compile(p, re.IGNORECASE) for p in [
    r"\bexcerpted from\b",
]]


def _blacklist_check(templates):
    for t in templates:
        blob = json.dumps(t, ensure_ascii=False)
        hits = run_blacklist_scan(blob, extra_patterns=_TEMPLATE_EXTRAS)
        if hits:
            raise SystemExit(f"IP-SAFETY VIOLATION in template '{t['code']}': matches '{hits[0]}'")


async def _seed_to_db(templates):
    from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    for t in templates:
        unchanged = {"truck_inventory_checklist","water_chemistry_log","incident_report_form"}
        default_version = 1 if t["code"] in unchanged else 2
        doc = {**t,
                "is_system": True,
                "tenant_id": None,
                "version": default_version}
        await upsert_template_definition(db, doc)
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
