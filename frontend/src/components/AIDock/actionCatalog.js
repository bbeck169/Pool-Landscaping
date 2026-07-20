/**
 * Catalog of AI employee actions surfaced by the AIDock action picker.
 * Keys mirror the exact backend action strings. ``approveGated`` is
 * informational only — the actual gating lives in
 * ``AE3_APPROVE_GATED_ACTIONS`` / ``AE4_APPROVE_GATED_ACTIONS`` /
 * per-employee sets in ``routers/ai_employees.py``.
 */

export const EMPLOYEE_ACTIONS = {
  casey: [
    { key: "casey.draft_directory_submission", approveGated: true, params: [
      { name: "directory_slug", label: "Directory slug (e.g. gbp, yelp)", required: true },
      { name: "directory_name", label: "Directory display name" },
    ]},
    { key: "casey.suggest_directory_updates", approveGated: true, params: [] },
    { key: "casey.draft_outreach_reply", approveGated: true, params: [
      { name: "incoming_text", label: "Outreach email text", required: true, placeholder: "Paste the incoming message" },
    ]},
  ],
  emmie: [
    { key: "emmie.draft_campaign", approveGated: true, params: [
      { name: "name", label: "Campaign name", required: true },
      { name: "channel", label: "Channel (email / sms / email,sms)", required: true, placeholder: "email" },
      { name: "audience_hint", label: "Audience hint" },
      { name: "goal", label: "Goal", required: true },
      { name: "tone", label: "Tone" },
    ]},
    { key: "emmie.suggest_ab_subjects", approveGated: true, params: [
      { name: "campaign_id", label: "Campaign ID", required: true },
    ]},
    { key: "emmie.analyze_campaign", approveGated: false, params: [
      { name: "campaign_id", label: "Campaign ID", required: true },
    ]},
    { key: "emmie.suggest_seasonal_ideas", approveGated: true, params: [
      { name: "season", label: "Season (spring/summer/fall/winter)", required: true },
      { name: "service_types", label: "Service types (comma list)", placeholder: "Pool, Landscape" },
    ]},
    { key: "emmie.rewrite_copy", approveGated: false, params: [
      { name: "text", label: "Copy to rewrite", required: true },
      { name: "tone", label: "Target tone" },
      { name: "goal", label: "Goal" },
    ]},
  ],
  buddy: [
    { key: "buddy.weekly_growth_brief", approveGated: true, params: [
      { name: "days", label: "Window (days)", placeholder: "7" },
    ]},
    { key: "buddy.pipeline_analysis", approveGated: false, params: [
      { name: "days", label: "Window (days)", placeholder: "14" },
    ]},
    { key: "buddy.pricing_recommendation", approveGated: true, params: [] },
  ],
  vizzy: [
    { key: "vizzy.daily_brief", approveGated: false, params: [] },
    { key: "vizzy.prep_call", approveGated: false, params: [
      { name: "customer_id", label: "Customer ID", required: true },
    ]},
    { key: "vizzy.prioritize_today", approveGated: false, params: [] },
  ],
  dexter: [
    { key: "dexter.ad_hoc_query", approveGated: false, params: [
      { name: "question", label: "Ask a question", required: true, placeholder: "How many customers in Peoria?" },
    ]},
    { key: "dexter.top_customers_report", approveGated: false, params: [
      { name: "metric", label: "Metric (revenue / visits / chemicals_cost)", required: true, placeholder: "revenue" },
      { name: "period_days", label: "Period (days)", placeholder: "90" },
    ]},
    { key: "dexter.chemical_profitability_report", approveGated: false, params: [
      { name: "period_days", label: "Period (days)", placeholder: "60" },
    ]},
  ],
  soshie: [
    { key: "soshie.draft_post", approveGated: true, params: [
      { name: "platform", label: "Platform", required: true, placeholder: "instagram" },
      { name: "topic", label: "Topic", required: true },
      { name: "tone", label: "Tone" },
    ]},
    { key: "soshie.schedule_post", approveGated: true, params: [
      { name: "platform", label: "Platform", required: true },
      { name: "scheduled_at", label: "Scheduled at (ISO)", placeholder: "2026-05-01T10:00Z" },
      { name: "caption", label: "Caption", required: true },
    ]},
    { key: "soshie.suggest_content_calendar", approveGated: false, params: [
      { name: "days", label: "Days", placeholder: "14" },
    ]},
    { key: "soshie.analyze_engagement", approveGated: false, params: [
      { name: "days", label: "Days", placeholder: "30" },
    ]},
    { key: "soshie.hashtag_research", approveGated: false, params: [
      { name: "topic", label: "Topic", required: true },
    ]},
  ],
  scouty: [
    { key: "scouty.draft_job_posting", approveGated: true, params: [
      { name: "role", label: "Role title", required: true },
      { name: "location", label: "Location" },
      { name: "pay_range", label: "Pay range" },
    ]},
    { key: "scouty.screen_resume", approveGated: false, params: [
      { name: "role", label: "Role", required: true },
      { name: "resume_text", label: "Resume text", required: true },
    ]},
    { key: "scouty.suggest_interview_questions", approveGated: false, params: [
      { name: "role", label: "Role", required: true },
      { name: "count", label: "Count", placeholder: "8" },
    ]},
    { key: "scouty.generate_offer_letter", approveGated: true, params: [
      { name: "candidate_name", label: "Candidate", required: true },
      { name: "role", label: "Role", required: true },
      { name: "salary", label: "Salary" },
      { name: "start_date", label: "Start date" },
    ]},
    { key: "scouty.pipeline_summary", approveGated: false, params: [] },
  ],
  commet: [
    { key: "commet.draft_funnel_copy", approveGated: true, params: [
      { name: "goal", label: "Funnel goal", required: true },
      { name: "audience", label: "Audience" },
    ]},
    { key: "commet.analyze_conversion", approveGated: false, params: [
      { name: "days", label: "Days", placeholder: "30" },
    ]},
    { key: "commet.suggest_ab_variants", approveGated: true, params: [
      { name: "element", label: "Element (headline / cta / body)", required: true },
      { name: "current_copy", label: "Current copy", required: true },
    ]},
    { key: "commet.recommend_cta_changes", approveGated: false, params: [
      { name: "current_cta", label: "Current CTA", required: true },
    ]},
    { key: "commet.funnel_stage_report", approveGated: false, params: [] },
  ],
};

export const ACTION_LABELS = {
  "casey.draft_directory_submission": "Draft directory submission",
  "casey.suggest_directory_updates":  "Suggest directory updates",
  "casey.draft_outreach_reply":       "Draft outreach reply",
  "emmie.draft_campaign":             "Draft campaign",
  "emmie.suggest_ab_subjects":        "Suggest A/B subject lines",
  "emmie.analyze_campaign":           "Analyze campaign",
  "emmie.suggest_seasonal_ideas":     "Suggest seasonal ideas",
  "emmie.rewrite_copy":               "Rewrite copy",
  "buddy.weekly_growth_brief":        "Weekly growth brief",
  "buddy.pipeline_analysis":          "Pipeline analysis",
  "buddy.pricing_recommendation":     "Pricing recommendation",
  "vizzy.daily_brief":                "Daily brief",
  "vizzy.prep_call":                  "Prep a call",
  "vizzy.prioritize_today":           "Prioritize today",
  "dexter.ad_hoc_query":              "Ask a question",
  "dexter.top_customers_report":      "Top customers report",
  "dexter.chemical_profitability_report": "Chemical profitability",
  "soshie.draft_post":                "Draft social post",
  "soshie.schedule_post":             "Schedule social post",
  "soshie.suggest_content_calendar":  "Content calendar",
  "soshie.analyze_engagement":        "Analyze engagement",
  "soshie.hashtag_research":          "Hashtag research",
  "scouty.draft_job_posting":         "Draft job posting",
  "scouty.screen_resume":             "Screen resume",
  "scouty.suggest_interview_questions": "Interview questions",
  "scouty.generate_offer_letter":     "Draft offer letter",
  "scouty.pipeline_summary":          "Pipeline summary",
  "commet.draft_funnel_copy":         "Draft funnel copy",
  "commet.analyze_conversion":        "Analyze funnel conversion",
  "commet.suggest_ab_variants":       "Suggest A/B variants",
  "commet.recommend_cta_changes":     "Recommend CTA changes",
  "commet.funnel_stage_report":       "Funnel stage report",
};
