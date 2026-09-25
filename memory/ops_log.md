# Ops log · Preview environment

One-line-per-run audit trail for direct-DB ops overrides performed on the preview environment. Never touch production.

## 2026-09-25T00:19:38.956733+00:00 · Task Q · Preview unlock — no Stripe

- tenant_id: `affdfbfa-88b9-4baa-ae45-2ef78531b6e4`
- user_email: `brian@plofv.com`
- features: zillow_data, seo_heatmap, ai_analytics, ai_copilot
- actions: {"zillow_data": "inserted", "seo_heatmap": "already-enabled", "ai_analytics": "inserted", "ai_copilot": "inserted", "settings.ai.analytics_enabled": "set", "user_role": "already-super_admin"}
- operator note: Preview unlock — no Stripe.

## 2026-09-25T00:19:44.118526+00:00 · Task Q · Preview unlock — no Stripe

- tenant_id: `affdfbfa-88b9-4baa-ae45-2ef78531b6e4`
- user_email: `brian@plofv.com`
- features: zillow_data, seo_heatmap, ai_analytics, ai_copilot
- actions: {"zillow_data": "already-enabled", "seo_heatmap": "already-enabled", "ai_analytics": "already-enabled", "ai_copilot": "already-enabled", "settings.ai.analytics_enabled": "unchanged", "user_role": "already-super_admin"}
- operator note: Preview unlock — no Stripe.

