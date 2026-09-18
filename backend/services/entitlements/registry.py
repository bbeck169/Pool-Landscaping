"""Sprint 3c · Feb-2026 — Feature Marketplace registry.

Hardcoded source of truth for the four add-ons surfaced in the
Feature Marketplace tab. Prices are placeholders — the real prices
live in Stripe (env-driven). If the Stripe price ID env var is
unset for a feature, that feature surfaces as ``not_configured``
(browsable but not enable-able) — never crashes.

Backlog items (P1 · i): Zillow Data, SEO Rank Heatmap, AI
Analytics, AI Copilot.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple


FEATURE_ZILLOW = "zillow_data"
FEATURE_SEO_HEATMAP = "seo_heatmap"
FEATURE_AI_ANALYTICS = "ai_analytics"
FEATURE_AI_COPILOT = "ai_copilot"


FEATURE_REGISTRY: Dict[str, Dict[str, Any]] = {
    FEATURE_ZILLOW: {
        "display_name": "Zillow Data",
        "description": (
            "Enrich customer + prospect records with Zestimate + "
            "property details (year built, lot size, bed/bath). "
            "Powers accurate quote sizing on the D2D and prospect "
            "enrichment flows."
        ),
        "monthly_price_cents": 4900,       # $49/mo placeholder
        "stripe_price_id_env": "STRIPE_PRICE_ID_ZILLOW",
        "billing_cadence": "monthly",
        "icon": "home",                    # frontend hint
    },
    FEATURE_SEO_HEATMAP: {
        "display_name": "SEO Rank Heatmap",
        "description": (
            "Grid-based local rank tracking across up to 25 map "
            "pins per keyword. Includes weekly refresh + trend "
            "delta reports."
        ),
        "monthly_price_cents": 9900,       # $99/mo placeholder
        "stripe_price_id_env": "STRIPE_PRICE_ID_SEO_HEATMAP",
        "billing_cadence": "monthly",
        "icon": "map",
    },
    FEATURE_AI_ANALYTICS: {
        "display_name": "AI Analytics",
        "description": (
            "AI-generated churn risk, revenue anomaly detection, "
            "tech productivity coaching, and 12-week revenue "
            "forecast — powered by your CRM data + LLM analysis."
        ),
        "monthly_price_cents": 4900,       # $49/mo placeholder
        "stripe_price_id_env": "STRIPE_PRICE_ID_AI_ANALYTICS",
        "billing_cadence": "monthly",
        "icon": "trending-up",
    },
    FEATURE_AI_COPILOT: {
        "display_name": "AI Copilot",
        "description": (
            "Persistent AI Employees that respond to customer "
            "inbound and draft outbound with your brand voice + "
            "Knowledge Base. Includes conversation history + "
            "approval-first action queue."
        ),
        "monthly_price_cents": 14900,      # $149/mo placeholder
        "stripe_price_id_env": "STRIPE_PRICE_ID_AI_COPILOT",
        "billing_cadence": "monthly",
        "icon": "bot",
    },
}

FEATURE_KEYS: Tuple[str, ...] = tuple(FEATURE_REGISTRY.keys())


def get_feature(feature_key: str) -> Optional[Dict[str, Any]]:
    return FEATURE_REGISTRY.get(feature_key)


def resolve_stripe_price_id(feature_key: str) -> Optional[str]:
    """Read the env var for the feature's Stripe price id.

    Returns ``None`` when the env is unset — caller should surface
    ``availability="not_configured"`` in the marketplace GET and 503
    ``feature_not_configured`` on POST enable.
    """
    feat = FEATURE_REGISTRY.get(feature_key)
    if not feat:
        return None
    env_key = feat.get("stripe_price_id_env")
    if not env_key:
        return None
    return (os.environ.get(env_key) or "").strip() or None


def env_status() -> Dict[str, bool]:
    """Snapshot of which Stripe price IDs are configured — used
    by the ``availability`` field of the marketplace GET response
    and by the ops runbook."""
    return {
        k: bool(resolve_stripe_price_id(k))
        for k in FEATURE_KEYS
    }
