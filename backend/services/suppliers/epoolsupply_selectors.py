"""Phase 54e · Feb-2026 — ePoolSupply CSS selectors."""
from __future__ import annotations

EPOOLSUPPLY = {
    "login_url":       "https://www.epoolsupply.com/customer/account/login/",
    "catalog_url":     "https://www.epoolsupply.com/shop",
    "input_username":  "input[name='login[username]'], input[name='email'], input#email",
    "input_password":  "input[name='login[password]'], input#pass",
    "btn_submit":      "button[type='submit'], .action.login, input[type='submit']",
    "logged_in_marker": "[data-testid='customer-menu'], .customer-welcome, a[href*='logout']",
    "product_card":    "[data-testid='product-item'], .product-item, li.item.product",
    "field_sku":       "[data-testid='sku'], .product-item-sku, .sku",
    "field_name":      "[data-testid='name'], .product-item-name, .product-name, h3",
    "field_cost":      "[data-testid='member-price'], .member-price, .price-final_price .price",
    "field_msrp":      "[data-testid='list-price'], .list-price, .msrp",
    "field_category":  "[data-testid='category'], .breadcrumbs .item",
    "field_uom":       "[data-testid='uom'], .uom",
    "field_description": "[data-testid='description'], .product-item-description",
    "btn_next_page":   "[data-testid='pagination-next'], a.action.next, li.pages-item-next a",
    "page_indicator":  "[data-testid='pagination-current'], .item.current",
    "rate_limit_banner": "[data-testid='rate-limit'], .throttle-notice",
}
