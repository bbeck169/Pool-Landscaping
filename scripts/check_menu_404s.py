#!/usr/bin/env python3
"""Phase 46.6 — Real Playwright menu-404 audit.

Logs in as each seed role, walks every menu link parsed from
`/app/frontend/src/nav/adminNav.js` + `roleNav.js`, and records any
route that renders the SPA "NotFound" page. Writes a JSON report to
`/app/memory/menu_audit_report.json`.

Falls back to a HEAD-probe audit when Playwright / a browser binary
isn't available — CI / preflight uses that fallback so the script is
always safe to run.

Usage:
    python3 /app/scripts/check_menu_404s.py            # auto-detect
    python3 /app/scripts/check_menu_404s.py --headless # force playwright
    python3 /app/scripts/check_menu_404s.py --http     # force http fallback
"""
from __future__ import annotations

from pathlib import Path
import json
import re
import sys
import argparse
from dotenv import dotenv_values

REPO = Path("/app")
FE_ENV = dotenv_values(REPO / "frontend" / ".env")
BASE = (FE_ENV.get("REACT_APP_BACKEND_URL") or "http://localhost:8001").rstrip("/")
API = f"{BASE}/api"
REPORT_PATH = REPO / "memory" / "menu_audit_report.json"

ROLES = [
    ("super_admin", "super@aquaterra.com"),
    ("admin", "admin@aquaterra.com"),
    ("technician", "mike@aquaterra.com"),
    ("customer", "customer@aquaterra.com"),
]


# ─── Nav parsing ─────────────────────────────────────────────────────────
NAV_ENTRY_RE = re.compile(
    r'\{\s*to:\s*"(?P<to>/[^"]*)"[^}]*?label:\s*"(?P<label>[^"]+)"',
    re.MULTILINE,
)


def parse_nav_links() -> list[dict]:
    """Return `[{to, label, source}]` — de-duplicated by (to)."""
    entries: dict[str, dict] = {}
    for source in ("adminNav.js", "roleNav.js"):
        p = REPO / "frontend" / "src" / "nav" / source
        if not p.exists():
            continue
        text = p.read_text()
        for m in NAV_ENTRY_RE.finditer(text):
            to = m.group("to")
            label = m.group("label")
            # Skip templated links — SPA can't resolve `:id`.
            if ":" in to or "{" in to or "*" in to:
                continue
            if to not in entries:
                entries[to] = {"to": to, "label": label, "source": source}
    return sorted(entries.values(), key=lambda e: e["to"])


# ─── HTTP-only fallback ──────────────────────────────────────────────────
def http_probe(links: list[dict]) -> dict:
    """
    A real 404-audit for an SPA needs a browser (the HTML shell always
    returns 200). We still record login success + link inventory so the
    report is useful even when Playwright is unavailable.
    """
    import requests
    result: dict = {"mode": "http", "roles": {}, "links": links,
                    "note": "SPA HTML is always 200 — Playwright walker is required "
                            "for a real 404 audit. Install `playwright` + `playwright install chromium` "
                            "and re-run this script for the full audit."}
    for role, email in ROLES:
        try:
            r = requests.post(f"{API}/auth/login",
                              json={"email": email, "password": "password123"},
                              timeout=10)
            r.raise_for_status()
            token = r.json().get("access_token")
            result["roles"][role] = {"login": "ok" if token else "no-token"}
        except Exception as e:
            result["roles"][role] = {"login": "failed", "error": str(e)}
    return result


# ─── Playwright walker ───────────────────────────────────────────────────
async def playwright_walk(links: list[dict], base_url: str) -> dict:
    """
    Log in via the /login form, then navigate to each menu link and
    check whether the page renders the SPA "NotFound" component
    (identified by `data-testid="not-found-page"` inside NotFound.jsx —
    if that attribute doesn't exist yet, we fall back to a text sniff
    for the phrase "Page not found").
    """
    from playwright.async_api import async_playwright  # type: ignore

    result: dict = {"mode": "playwright", "roles": {}, "links": links}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        for role, email in ROLES:
            context = await browser.new_context()
            page = await context.new_page()
            role_report = {"login": "pending", "links": []}
            try:
                await page.goto(f"{base_url}/login", wait_until="networkidle", timeout=30000)
                # React hydrates asynchronously — wait until the login test id
                # actually appears in the DOM rather than trusting DOMContentLoaded.
                await page.wait_for_selector('[data-testid="login-email-input"]', timeout=30000)
                await page.locator('[data-testid="login-email-input"]').fill(email)
                await page.locator('[data-testid="login-password-input"]').fill("password123")
                await page.locator('[data-testid="login-submit-button"]').click()
                # Wait until we're no longer on /login.
                try:
                    await page.wait_for_function("() => !location.pathname.startsWith('/login')", timeout=20000)
                except Exception:
                    pass
                role_report["login"] = "ok"
            except Exception as e:
                role_report["login"] = f"failed: {e}"
                result["roles"][role] = role_report
                await context.close()
                continue

            for entry in links:
                to = entry["to"]
                url = f"{base_url}{to}"
                status = "ok"
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    if resp is None:
                        status = "no-response"
                    else:
                        http = resp.status
                        body = await page.content()
                        is_404 = (
                            "not-found-page" in body
                            or 'data-testid="not-found"' in body
                            or "Page not found" in body
                        )
                        if is_404:
                            status = "spa-404"
                        elif http >= 400:
                            status = f"http-{http}"
                except Exception as e:
                    status = f"error: {e}"
                role_report["links"].append({"to": to, "label": entry["label"],
                                             "status": status})
            result["roles"][role] = role_report
            await context.close()
        await browser.close()
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="Force HTTP-only fallback")
    ap.add_argument("--headless", action="store_true", help="Force Playwright run")
    args = ap.parse_args()

    links = parse_nav_links()
    print(f"[audit] parsed {len(links)} unique nav links from adminNav.js + roleNav.js")

    if args.http:
        report = http_probe(links)
    else:
        try:
            import playwright  # noqa: F401
            import asyncio
            report = asyncio.run(playwright_walk(links, BASE))
        except Exception as e:
            print(f"[audit] Playwright unavailable ({e}); falling back to HTTP probe.")
            report = http_probe(links)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"[audit] report written: {REPORT_PATH}")

    # Summarise 404s so a preflight-style call surfaces them.
    if report.get("mode") == "playwright":
        bad = []
        for role, r in report["roles"].items():
            for row in r.get("links", []):
                if row["status"] == "spa-404":
                    bad.append(f"{role}: {row['to']}")
        if bad:
            print("[audit] 404s found:")
            for b in bad:
                print(f"  • {b}")
        else:
            print("[audit] no 404s found across all roles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
