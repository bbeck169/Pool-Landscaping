from playwright.sync_api import sync_playwright
import json, time
URL = "https://poolscape-audit.preview.emergentagent.com/"
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path="/root/bin/chromium",
                                args=["--no-sandbox","--disable-dev-shm-usage"])
    page = browser.new_context().new_page()
    page.goto(URL, wait_until="networkidle", timeout=45000)
    time.sleep(2)
    js = """() => {
      const roles = ['Super Admin','Admin','Customer','Landscape Tech','Pool Tech'];
      const all = Array.from(document.querySelectorAll('button, [role="button"], a, div'));
      const matches = [];
      for (const el of all) {
        const t = (el.innerText||'').trim();
        if (roles.some(r => t === r)) matches.push({ tag: el.tagName, text: t });
      }
      return { role_matches: matches.slice(0,20), body_len: document.body.innerText.length };
    }"""
    print(json.dumps(page.evaluate(js), indent=2))
    page.screenshot(path="/app/test_artifacts/baseline.png", full_page=True)
    browser.close()
