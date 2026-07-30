/**
 * MR1+MR2 · Feb-2026 — Widget script unit tests.
 *
 * The widget is served as a string from the backend at ``/api/widget.js``
 * (see ``backend/routers/public_widget.py``). For the vitest suite we
 * execute the same string in JSDOM using ``new Function`` after
 * stubbing ``fetch`` + ``document.currentScript``. This gives us an
 * end-to-end assertion that the shipped script:
 *
 *   - parses data-* attributes off its own <script> tag,
 *   - fetches the feed URL with the right query params,
 *   - mounts a shadow DOM,
 *   - renders a card per checkin,
 *   - injects a schema.org JSON-LD block into document.head.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";

const WIDGET_JS = fs.readFileSync(
  path.resolve(__dirname, "..", "..", "..", "backend", "routers",
                "public_widget.py"),
  "utf-8",
);

// Extract the JS string between the '_WIDGET_JS = r"""' start marker
// and the closing """.
function extractWidgetJs(py) {
  const start = py.indexOf(`_WIDGET_JS = r"""`);
  if (start === -1) throw new Error("marker not found");
  const jsStart = start + `_WIDGET_JS = r"""`.length;
  const jsEnd = py.indexOf(`"""`, jsStart);
  return py.slice(jsStart, jsEnd);
}

const SCRIPT = extractWidgetJs(WIDGET_JS);

const FEED = {
  tenant: { name: "Aquaterra", slug: "aquaterra",
             logo_url: null, brand_primary: "#0284C7",
             brand_secondary: "#16A34A" },
  checkins: [
    { id: "c1", service_name: "Weekly Pool", service_category: "pool_service",
      description: "Cleaned filter", tags: ["pool"],
      photos: [{ url: "https://x/p.jpg", alt: "front" }],
      location: { street_name: "Main St", city: "Peoria", state: "AZ" },
      completed_at: "2026-02-14T10:00:00Z" },
    { id: "c2", service_name: "Chem Check", service_category: "pool_service",
      description: "Balanced chemistry", tags: [],
      photos: [], location: { street_name: "Oak Ave", city: "Peoria", state: "AZ" },
      completed_at: "2026-02-14T09:00:00Z" },
  ],
  count: 2, as_of: "2026-02-14T10:05:00Z",
  cache_ttl_s: 604800,
};

describe("widget.js runtime", () => {
  let scriptEl, container, fetchStub, timerSpy;

  beforeEach(() => {
    vi.useFakeTimers();
    // Mount a fake <script> tag as currentScript.
    container = document.createElement("div");
    document.body.appendChild(container);
    scriptEl = document.createElement("script");
    scriptEl.setAttribute("data-tenant", "aquaterra");
    scriptEl.setAttribute("data-count", "12");
    scriptEl.setAttribute("data-theme", "light");
    scriptEl.src = "https://backend.test/api/widget.js";
    container.appendChild(scriptEl);
    Object.defineProperty(document, "currentScript",
                            { configurable: true, get: () => scriptEl });

    // Stub fetch.
    fetchStub = vi.fn(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(FEED) }),
    );
    global.fetch = fetchStub;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    document.head.querySelectorAll('[data-emergent-widget-jsonld]')
                    .forEach((n) => n.remove());
  });

  it("fetches feed at the correct URL and mounts shadow DOM + cards", async () => {
    // Execute the IIFE.
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)();

    // Flush enough microtasks for the fetch().then().then() chain.
    for (let i = 0; i < 10; i++) await Promise.resolve();

    // fetch called with expected URL.
    // MR3 note: the widget also fires an impression POST after render,
    // so `fetch` may be called more than once — assert on the feed
    // call specifically (the first call).
    expect(fetchStub).toHaveBeenCalled();
    const calledWith = fetchStub.mock.calls[0][0];
    expect(calledWith).toContain("/api/public/checkins/aquaterra/feed");
    expect(calledWith).toContain("limit=12");

    // Mount div was created after the script tag.
    const mount = document.querySelector('[data-emergent-widget-mount="aquaterra"]');
    expect(mount).toBeTruthy();
    expect(mount.shadowRoot).toBeTruthy();

    // Card per checkin rendered inside shadow DOM.
    const cards = mount.shadowRoot.querySelectorAll('[data-testid^="widget-card-"]');
    expect(cards.length).toBe(2);
    const c0 = mount.shadowRoot.querySelector('[data-testid="widget-card-0"]');
    expect(c0.textContent).toContain("Weekly Pool");
    expect(c0.textContent).toContain("Main St, Peoria, AZ");
    expect(c0.textContent).toContain("Cleaned filter");
    expect(c0.textContent).toContain("pool");  // tag

    // schema.org JSON-LD is injected into document.head.
    const jsonLd = document.head.querySelector('[data-emergent-widget-jsonld="aquaterra"]');
    expect(jsonLd).toBeTruthy();
    const parsed = JSON.parse(jsonLd.textContent);
    expect(parsed["@context"]).toBe("https://schema.org");
    expect(parsed["@type"]).toBe("LocalBusiness");
    expect(parsed.name).toBe("Aquaterra");
    // One Service block per unique service_name.
    const svcs = parsed.makesOffer.map((s) => s.name);
    expect(svcs).toContain("Weekly Pool");
    expect(svcs).toContain("Chem Check");
  });

  it("appends data-category to the feed URL when the attribute is set", async () => {
    scriptEl.setAttribute("data-category", "pool_service");
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)();
    await Promise.resolve(); await Promise.resolve();
    const calledWith = fetchStub.mock.calls[0][0];
    expect(calledWith).toContain("service_category=pool_service");
  });

  it("applies theme-dark class when data-theme='dark'", async () => {
    scriptEl.setAttribute("data-theme", "dark");
    // eslint-disable-next-line no-new-func
    new Function(SCRIPT)();
    await Promise.resolve(); await Promise.resolve();
    const mount = document.querySelector('[data-emergent-widget-mount="aquaterra"]');
    const wrap = mount.shadowRoot.querySelector('[data-testid="emergent-widget-root"]');
    expect(wrap.className).toContain("theme-dark");
  });
});
