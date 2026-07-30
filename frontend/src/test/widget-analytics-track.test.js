/**
 * MR3 · Feb-2026 — Widget analytics tracking unit tests.
 *
 * Verifies the analytics additions to the shipped `_WIDGET_JS` string
 * (see `backend/routers/public_widget.py`):
 *   • impression fires exactly ONCE per session per widget mount
 *   • dedupe: reloading the widget in the same session does NOT
 *     re-emit an impression
 *   • click on a card fires a `click` event with the correct
 *     `checkin_id`
 *   • analytics failures never break the widget render (silent fail)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";

const WIDGET_PY = fs.readFileSync(
  path.resolve(__dirname, "..", "..", "..", "backend", "routers",
                "public_widget.py"),
  "utf-8",
);
function extractWidgetJs(py) {
  const start = py.indexOf(`_WIDGET_JS = r"""`);
  if (start === -1) throw new Error("marker not found");
  const jsStart = start + `_WIDGET_JS = r"""`.length;
  const jsEnd = py.indexOf(`"""`, jsStart);
  return py.slice(jsStart, jsEnd);
}
const SCRIPT = extractWidgetJs(WIDGET_PY);

const FEED = {
  tenant: { name: "Aquaterra", slug: "aquaterra" },
  checkins: [
    { id: "ck-1", service_name: "Pool Service",
      description: "Cleaned filter", tags: [],
      photos: [], location: { city: "Peoria", state: "AZ" },
      completed_at: "2026-02-14T10:00:00Z" },
    { id: "ck-2", service_name: "Chem Check",
      description: "Balanced pH", tags: [],
      photos: [], location: {},
      completed_at: "2026-02-14T09:00:00Z" },
  ],
  count: 2, as_of: "2026-02-14T10:05:00Z",
};

function setupDom(tenant = "aquaterra") {
  document.body.innerHTML = "";
  document.head.querySelectorAll('[data-emergent-widget-jsonld]')
                  .forEach((n) => n.remove());
  const container = document.createElement("div");
  document.body.appendChild(container);
  const scriptEl = document.createElement("script");
  scriptEl.setAttribute("data-tenant", tenant);
  scriptEl.setAttribute("data-count", "12");
  scriptEl.src = "https://backend.test/api/widget.js";
  container.appendChild(scriptEl);
  Object.defineProperty(document, "currentScript",
                          { configurable: true, get: () => scriptEl });
  return scriptEl;
}

function stubFetch() {
  const calls = [];
  const stub = vi.fn((url, opts) => {
    calls.push({ url: String(url), opts });
    if (String(url).includes("/api/public/checkins/")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(FEED) });
    }
    // /api/public/widget/analytics/track → 204 no-body
    return Promise.resolve({ ok: true, status: 204,
                              json: () => Promise.resolve({}) });
  });
  global.fetch = stub;
  return { stub, calls };
}

async function flush(n = 20) {
  for (let i = 0; i < n; i++) await Promise.resolve();
}

describe("widget.js MR3 analytics", () => {
  beforeEach(() => {
    // Clean slate for localStorage every test so session ids don't
    // leak between them (they're stored under a stable key).
    window.localStorage.clear();
    // Make sure sendBeacon is undefined — force the fetch fallback so
    // we can inspect calls easily.
    Object.defineProperty(window.navigator, "sendBeacon",
                            { configurable: true, value: undefined });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    document.head.querySelectorAll('[data-emergent-widget-jsonld]')
                    .forEach((n) => n.remove());
    window.localStorage.clear();
    delete window.__EmergentWidget;
  });

  it("fires exactly ONE impression per session per widget mount", async () => {
    setupDom("aquaterra");
    const { calls } = stubFetch();
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)();
    await flush();

    const trackCalls = calls.filter((c) => c.url.includes("/analytics/track"));
    expect(trackCalls.length).toBe(1);
    const body = JSON.parse(trackCalls[0].opts.body);
    expect(body.event_type).toBe("impression");
    expect(body.widget_id).toBe("aquaterra");
    expect(body.checkin_id).toBeNull();
    expect(typeof body.session_id).toBe("string");
    expect(body.session_id.length).toBeGreaterThanOrEqual(6);
  });

  it("dedupes impressions across mounts within the 24h session window", async () => {
    // First mount → one impression.
    setupDom("aquaterra");
    const first = stubFetch();
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)();
    await flush();
    expect(first.calls.filter((c) => c.url.includes("/analytics/track")).length).toBe(1);

    // Second mount, same tab (localStorage persists). New fetch stub
    // to isolate call counts.
    setupDom("aquaterra");
    delete window.__EmergentWidget;
    const second = stubFetch();
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)();
    await flush();
    // Second mount MUST NOT re-emit an impression.
    const trackCalls2 = second.calls.filter((c) => c.url.includes("/analytics/track"));
    expect(trackCalls2.length).toBe(0);
  });

  it("fires a click event with the correct checkin_id when a card is clicked", async () => {
    setupDom("aquaterra");
    const { calls } = stubFetch();
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)();
    await flush();

    // Click the first card.
    const mount = document.querySelector('[data-emergent-widget-mount="aquaterra"]');
    const card0 = mount.shadowRoot.querySelector('[data-testid="widget-card-0"]');
    expect(card0).toBeTruthy();
    expect(card0.getAttribute("data-checkin-id")).toBe("ck-1");
    card0.click();
    await flush();

    const clickCalls = calls.filter((c) => {
      if (!c.url.includes("/analytics/track")) return false;
      const b = JSON.parse(c.opts.body);
      return b.event_type === "click";
    });
    expect(clickCalls.length).toBe(1);
    const clickBody = JSON.parse(clickCalls[0].opts.body);
    expect(clickBody.checkin_id).toBe("ck-1");
    expect(clickBody.widget_id).toBe("aquaterra");
  });

  it("does not break the widget when the analytics endpoint rejects", async () => {
    setupDom("aquaterra");
    // Fetch: feed OK, track rejects.
    const calls = [];
    global.fetch = vi.fn((url, opts) => {
      calls.push({ url: String(url) });
      if (String(url).includes("/api/public/checkins/")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(FEED) });
      }
      return Promise.reject(new Error("network broken"));
    });
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)();
    await flush();

    // Widget must still render its cards, even though the tracker rejected.
    const mount = document.querySelector('[data-emergent-widget-mount="aquaterra"]');
    const cards = mount.shadowRoot.querySelectorAll('[data-testid^="widget-card-"]');
    expect(cards.length).toBe(2);
    // And a track call was attempted (fire-and-forget).
    expect(calls.some((c) => c.url.includes("/analytics/track"))).toBe(true);
  });
});
