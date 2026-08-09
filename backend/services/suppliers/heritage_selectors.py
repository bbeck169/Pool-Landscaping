"""Phase 54e · Feb-2026 — Heritage Pool Plus CSS selectors."""
from __future__ import annotations

HERITAGE = {
    "login_url":       "https://www.heritagepoolplus.com/customer/login",
    "catalog_url":     "https://www.heritagepoolplus.com/products",
    "input_username":  "input[name='username'], input[name='email'], input#username, input#email",
    "input_password":  "input[name='password'], input#password",
    "btn_submit":      "button[type='submit'], input[type='submit']",
    "logged_in_marker": "[data-testid='account-menu'], .my-account, a[href*='logout']",
    "product_card":    "[data-testid='product-card'], .product-card, li.product-item",
    "field_sku":       "[data-testid='sku'], .sku, .product-sku",
    "field_name":      "[data-testid='name'], .product-name, h3",
    "field_cost":      "[data-testid='dealer-price'], .dealer-price, .price",
    "field_msrp":      "[data-testid='msrp'], .msrp",
    "field_category":  "[data-testid='category'], .breadcrumb",
    "field_uom":       "[data-testid='uom'], .uom",
    "field_description": "[data-testid='description'], .description",
    "btn_next_page":   "[data-testid='pagination-next'], a[aria-label='Next']",
    "page_indicator":  "[data-testid='pagination-current']",
    "rate_limit_banner": "[data-testid='rate-limit'], .throttle-notice",
}
