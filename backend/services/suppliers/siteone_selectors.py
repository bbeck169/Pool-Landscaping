"""Phase 54c · Feb-2026 — SiteOne CSS selectors (extracted config).

Same data-only approach as ``poolcorp/selectors.py``. Editable
without a code change when the SiteOne B2B portal ships a redesign.
"""
from __future__ import annotations

SITEONE = {
    "login_url":       "https://www.siteone.com/en/pro/login",
    "catalog_url":     "https://www.siteone.com/en/pro/products",
    # Login form
    "input_username":  "input[name='username'], input[name='email'], input#username, input#email",
    "input_password":  "input[name='password'], input#password",
    "btn_submit":      "button[type='submit'], input[type='submit']",
    "logged_in_marker": "[data-testid='pro-user-menu'], .account-menu, a[href*='logout']",
    # Product list — one card per SKU
    "product_card":    "[data-testid='pro-product-card'], .product-tile, li.product-item",
    "field_sku":       "[data-testid='pro-sku'], .product-sku, .sku",
    "field_name":      "[data-testid='pro-name'], .product-name, h3",
    "field_cost":      "[data-testid='pro-price'], .your-price, .price",
    "field_msrp":      "[data-testid='pro-list-price'], .list-price",
    "field_category":  "[data-testid='pro-category'], .breadcrumb",
    "field_uom":       "[data-testid='pro-uom'], .uom",
    "field_description": "[data-testid='pro-description'], .description",
    # Pagination
    "btn_next_page":   "[data-testid='pagination-next'], a[aria-label='Next']",
    "page_indicator":  "[data-testid='pagination-current']",
    # Rate-limit / throttling banner (SiteOne shows one on 429/503).
    # Used only for logging clarity — the connector detects rate
    # limits from HTTP status too.
    "rate_limit_banner": "[data-testid='rate-limit'], .throttle-notice",
}
