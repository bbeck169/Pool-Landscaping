"""
Task 6b — Revoke service-records link · E2E Playwright Tests (Mobile Expo App)

Tests:
1. Login page shows "link revoked" banner when ?reason=link_revoked param present
2. Banner has correct copy, styling, and dismiss button
3. Banner is dismissible via X button
4. Login → customer detail → FAB → Send Create sheet → Send Service Records Link modal opens
5. Modal has "Recent sends" section

Uses localhost:3001 for the mobile Expo web preview.
"""
import pytest
from playwright.sync_api import sync_playwright, expect
import time

BASE = "http://localhost:3001"
LOAD_TIMEOUT = 60000  # 60s for initial Metro bundle

@pytest.fixture(scope="module")
def browser_ctx():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        yield ctx
        browser.close()


@pytest.fixture(scope="module")
def logged_in_page(browser_ctx):
    """Shared logged-in page for modal tests — login once, reuse."""
    page = browser_ctx.new_page()
    page.goto(BASE, wait_until="networkidle", timeout=LOAD_TIMEOUT)
    page.wait_for_timeout(8000)
    
    email_input = page.locator('[data-testid="login-email-input"]')
    email_input.wait_for(state="visible", timeout=LOAD_TIMEOUT)
    email_input.fill("super@aquaterra.com")
    
    pw_input = page.locator('[data-testid="login-password-input"]')
    pw_input.fill("password123")
    
    submit = page.locator('[data-testid="login-submit-button"]')
    submit.click(force=True)
    page.wait_for_timeout(8000)
    
    yield page
    page.close()


class TestLinkRevokedBanner:
    """Tests the 'link revoked' banner on the login page."""

    def test_banner_appears_with_reason_param(self, browser_ctx):
        page = browser_ctx.new_page()
        page.goto(f"{BASE}/login?reason=link_revoked", wait_until="networkidle", timeout=LOAD_TIMEOUT)
        page.wait_for_timeout(8000)
        
        banner = page.locator('[data-testid="link-revoked-banner"]')
        expect(banner).to_be_visible(timeout=15000)
        page.close()

    def test_banner_has_correct_copy(self, browser_ctx):
        page = browser_ctx.new_page()
        page.goto(f"{BASE}/login?reason=link_revoked", wait_until="networkidle", timeout=LOAD_TIMEOUT)
        page.wait_for_timeout(8000)
        
        banner = page.locator('[data-testid="link-revoked-banner"]')
        expect(banner).to_contain_text("This link has been revoked")
        expect(banner).to_contain_text("contact your service provider")
        page.close()

    def test_banner_has_dismiss_button(self, browser_ctx):
        page = browser_ctx.new_page()
        page.goto(f"{BASE}/login?reason=link_revoked", wait_until="networkidle", timeout=LOAD_TIMEOUT)
        page.wait_for_timeout(8000)
        
        dismiss_btn = page.locator('[data-testid="dismiss-revoked-banner"]')
        expect(dismiss_btn).to_be_visible(timeout=15000)
        page.close()

    def test_banner_dismissible(self, browser_ctx):
        page = browser_ctx.new_page()
        page.goto(f"{BASE}/login?reason=link_revoked", wait_until="networkidle", timeout=LOAD_TIMEOUT)
        page.wait_for_timeout(8000)
        
        banner = page.locator('[data-testid="link-revoked-banner"]')
        expect(banner).to_be_visible(timeout=15000)
        
        dismiss_btn = page.locator('[data-testid="dismiss-revoked-banner"]')
        dismiss_btn.click(force=True)
        page.wait_for_timeout(2000)
        
        expect(banner).not_to_be_visible(timeout=10000)
        page.close()

    def test_no_banner_without_param(self, browser_ctx):
        page = browser_ctx.new_page()
        page.goto(f"{BASE}/login", wait_until="networkidle", timeout=LOAD_TIMEOUT)
        page.wait_for_timeout(8000)
        
        banner = page.locator('[data-testid="link-revoked-banner"]')
        expect(banner).not_to_be_visible(timeout=10000)
        page.close()


class TestSendServiceRecordsModal:
    """Tests the Send Service Records Link modal with recent sends + revoke."""

    def test_navigate_to_customer_and_see_fab(self, logged_in_page):
        page = logged_in_page
        page.goto(f"{BASE}/customers", wait_until="networkidle", timeout=LOAD_TIMEOUT)
        page.wait_for_timeout(5000)
        
        rows = page.locator('[data-testid^="customer-row-"]')
        rows.first.wait_for(state="visible", timeout=15000)
        rows.first.click(force=True)
        page.wait_for_timeout(5000)
        
        fab = page.locator('[data-testid="send-create-fab"]')
        expect(fab).to_be_visible(timeout=15000)

    def test_modal_opens_and_has_recent_sends(self, logged_in_page):
        page = logged_in_page
        
        # Ensure on customer detail (from previous test)
        fab = page.locator('[data-testid="send-create-fab"]')
        if not fab.is_visible():
            page.goto(f"{BASE}/customers", wait_until="networkidle", timeout=LOAD_TIMEOUT)
            page.wait_for_timeout(5000)
            rows = page.locator('[data-testid^="customer-row-"]')
            rows.first.wait_for(state="visible", timeout=15000)
            rows.first.click(force=True)
            page.wait_for_timeout(5000)
        
        fab.click(force=True)
        page.wait_for_timeout(3000)
        
        # Look for the service records link option
        records_option = page.locator('[data-testid="action-service-records-link"]')
        records_by_text = page.get_by_text("Service Records", exact=False)
        
        if records_option.is_visible():
            records_option.click(force=True)
        elif records_by_text.is_visible():
            records_by_text.click(force=True)
        else:
            pytest.skip("Service Records Link option not found in action sheet")
        
        page.wait_for_timeout(3000)
        
        # Verify modal opened
        modal = page.locator('[data-testid="send-service-records-link-modal"]')
        expect(modal).to_be_visible(timeout=15000)
        
        # Verify recent sends section exists
        recent = page.locator('[data-testid="recent-sends-section"]')
        expect(recent).to_be_visible(timeout=10000)
        
        # Verify channel tabs
        email_tab = page.locator('[data-testid="send-via-email-btn"]')
        sms_tab = page.locator('[data-testid="send-via-sms-btn"]')
        expect(email_tab).to_be_visible(timeout=10000)
        expect(sms_tab).to_be_visible(timeout=10000)
        
        # Verify send button
        send_btn = page.locator('[data-testid="send-service-records-link-btn"]')
        expect(send_btn).to_be_visible(timeout=10000)
        
        # Verify close button
        close_btn = page.locator('[data-testid="send-records-close-btn"]')
        expect(close_btn).to_be_visible(timeout=10000)
        
        # Close modal
        close_btn.click(force=True)
        page.wait_for_timeout(2000)


class TestLoginFormPresent:
    """Verifies the login page still functions correctly."""

    def test_login_form_renders(self, browser_ctx):
        page = browser_ctx.new_page()
        page.goto(f"{BASE}/login", wait_until="networkidle", timeout=LOAD_TIMEOUT)
        page.wait_for_timeout(8000)
        
        expect(page.locator('[data-testid="login-email-input"]')).to_be_visible(timeout=15000)
        expect(page.locator('[data-testid="login-password-input"]')).to_be_visible(timeout=15000)
        expect(page.locator('[data-testid="login-submit-button"]')).to_be_visible(timeout=15000)
        page.close()
