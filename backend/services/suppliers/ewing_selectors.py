"""Phase 54d · Feb-2026 — Ewing Irrigation CSS selectors (extracted config).

Same data-only approach as ``poolcorp/selectors.py`` and
``siteone_selectors.py``. Editable without a code change when the
Ewing B2B portal ships a redesign.
"""
from __future__ import annotations

EWING = {
    "login_url":       "https://www.ewingoutdoorsupply.com/customer/account/login",
    "catalog_url":     "https://www.ewingoutdoorsupply.com/products",
    # Login form
    "input_username":  "input[name='login[username]'], input[name='email'], input#email",
    "input_password":  "input[name='login[password]'], input[name='password'], input#pass",
    "btn_submit":      "button[type='submit'], button.action.login, input[type='submit']",
    "logged_in_marker": "[data-testid='customer-menu'], .customer-menu, a[href*='logout']",
    # Product list — one card per SKU
    "product_card":    "[data-testid='product-item'], .product-item, li.product",
    "field_sku":       "[data-testid='sku'], .product-sku, .sku",
    "field_name":      "[data-testid='name'], .product-item-name, .product-name, h3",
    "field_cost":      "[data-testid='member-price'], .member-price, .price-final_price .price",
    "field_msrp":      "[data-testid='list-price'], .list-price, .msrp",
    "field_category":  "[data-testid='category'], .breadcrumbs .item",
    "field_uom":       "[data-testid='uom'], .uom, .unit-of-measure",
    "field_description": "[data-testid='description'], .product-description, .short-description",
    # Pagination
    "btn_next_page":   "[data-testid='pagination-next'], a.action.next, li.item.pages-item-next a",
    "page_indicator":  "[data-testid='pagination-current'], .item.current",
    # Rate-limit / throttling banner
    "rate_limit_banner": "[data-testid='rate-limit'], .throttle-notice",
}
