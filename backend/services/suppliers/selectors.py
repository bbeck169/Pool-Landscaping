"""Phase 54b · Feb-2026 — Pool360 CSS selectors (extracted config).

Kept as data instead of hardcoded strings so a future site-layout
change is a config patch, not a code change. Each key documents
what page + element the selector targets.
"""
from __future__ import annotations

POOL360 = {
    "login_url":       "https://www.pool360.com/pool360/login",
    "catalog_url":     "https://www.pool360.com/pool360/product-search",
    # Login form
    "input_username":  "input[name='username'], input#username",
    "input_password":  "input[name='password'], input#password",
    "btn_submit":      "button[type='submit'], input[type='submit']",
    "logged_in_marker": "[data-testid='user-menu'], .user-account, a[href*='logout']",
    # Product list — one card per SKU
    "product_card":    "[data-testid='product-card'], .product-card, li.product-item",
    "field_sku":       "[data-testid='sku'], .sku, .product-sku",
    "field_name":      "[data-testid='name'], .product-name, h3",
    "field_cost":      "[data-testid='dealer-price'], .dealer-price, .price",
    "field_msrp":      "[data-testid='msrp'], .msrp",
    "field_category":  "[data-testid='category'], .breadcrumb",
    "field_uom":       "[data-testid='uom'], .uom",
    "field_description": "[data-testid='description'], .description",
    # Pagination
    "btn_next_page":   "[data-testid='pagination-next'], a[aria-label='Next']",
    "page_indicator":  "[data-testid='pagination-current']",
}
