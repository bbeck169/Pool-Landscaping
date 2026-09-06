/**
 * Phase K69 · Feb-2026 — "Sequences" → "Automations" rename.
 *
 * UI-string-only phase. Locks:
 *   1. The route redirects live so bookmarked ``/marketing/sequences``,
 *      ``/marketing/sequences/new``, and ``/marketing/sequences/:id``
 *      redirect to the new ``/marketing/automations`` counterparts.
 *   2. The admin nav item + the marketing landing card use
 *      "Automations".
 *   3. The Automations index page renders "Automations" as the H1
 *      + "New automation" as the create button + "automation" in
 *      empty/singular copy.
 *   4. Backend API paths (``/api/marketing/sequences``) are
 *      UNTOUCHED — the rename is presentation-layer only.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const APP_SRC    = read("src/App.js");
const NAV_SRC    = read("src/nav/adminNav.js");
const LIST_SRC   = read("src/pages/marketing/MarketingSequencesPage.jsx");
const PAGES_SRC  = read("src/pages/marketing/MarketingPages.jsx");


describe("K69 · route wiring + 301-equivalent redirects", () => {
  it("mounts the new /marketing/automations routes", () => {
    expect(APP_SRC).toMatch(
      /path="marketing\/automations"\s+element=\{<AdminOnly><SequencesList\s*\/><\/AdminOnly>\}/,
    );
    expect(APP_SRC).toMatch(
      /path="marketing\/automations\/new"\s+element=\{<AdminOnly><SequenceNew\s*\/><\/AdminOnly>\}/,
    );
    expect(APP_SRC).toMatch(
      /path="marketing\/automations\/:id"\s+element=\{<AdminOnly><SequenceDetail\s*\/><\/AdminOnly>\}/,
    );
    // The admin variant of the list also points at automations.
    expect(APP_SRC).toMatch(
      /path="admin\/marketing\/automations"\s+element=\{<AdminOnly><MarketingSequencesPage\s*\/><\/AdminOnly>\}/,
    );
  });

  it("redirects the old /marketing/sequences* paths to the new URLs (replace-navigate)", () => {
    expect(APP_SRC).toMatch(
      /path="marketing\/sequences"\s+element=\{<Navigate to="\/marketing\/automations" replace \/>\}/,
    );
    expect(APP_SRC).toMatch(
      /path="marketing\/sequences\/new"\s+element=\{<Navigate to="\/marketing\/automations\/new" replace \/>\}/,
    );
    expect(APP_SRC).toMatch(
      /path="admin\/marketing\/sequences"\s+element=\{<Navigate to="\/admin\/marketing\/automations" replace \/>\}/,
    );
    // Param-aware redirect keeps the id in the URL.
    expect(APP_SRC).toMatch(
      /path="marketing\/sequences\/:id"\s+element=\{<SequenceIdRedirect\s*\/>\}/,
    );
    expect(APP_SRC).toMatch(
      /function SequenceIdRedirect\(\)\s*\{\s*const\s*\{\s*id\s*\}\s*=\s*useParams\(\);\s*return\s+<Navigate to=\{`\/marketing\/automations\/\$\{id\}`\}\s*replace\s*\/>;\s*\}/,
    );
  });
});


describe("K69 · admin nav + marketing hub labels", () => {
  it("renames the admin nav item + subsection to Automations", () => {
    expect(NAV_SRC).toMatch(/to:\s*"\/admin\/marketing\/automations"/);
    expect(NAV_SRC).toMatch(/label:\s*"Automations"/);
    expect(NAV_SRC).toMatch(/subsection:\s*"Automations & Templates"/);
    // Regression guard — no stray "Sequences" label survives.
    expect(NAV_SRC).not.toMatch(/label:\s*"Sequences"/);
    expect(NAV_SRC).not.toMatch(/subsection:\s*"Sequences & Templates"/);
  });

  it("marketing hub card links to /marketing/automations", () => {
    expect(PAGES_SRC).toMatch(
      /to:\s*"\/marketing\/automations",\s*label:\s*"Automations"/,
    );
    expect(PAGES_SRC).not.toMatch(/label:\s*"Sequences"/);
  });
});


describe("K69 · Automations page copy", () => {
  it("H1 + counter + empty state read 'Automation(s)'", () => {
    expect(LIST_SRC).toMatch(/Automations\s*</);
    expect(LIST_SRC).toMatch(/automation\{rows\.length === 1 \? "" : "s"\}/);
    expect(LIST_SRC).toMatch(/Click "New automation" to build your first drip\./);
    // Deactivate confirmation copy.
    expect(LIST_SRC).toMatch(/title:\s*"Deactivate this automation\?"/);
    // Modal header when opened.
    expect(LIST_SRC).toMatch(/isNew \? "New automation" : "Edit automation"/);
    // Regression — no stray "sequence" in user-visible strings we
    // migrated. Data-testids like ``sequence-create-btn`` stay
    // (they're QA anchors, not user copy).
    expect(LIST_SRC).not.toMatch(/Click "New sequence"/);
    expect(LIST_SRC).not.toMatch(/Deactivate this sequence\?/);
    expect(LIST_SRC).not.toMatch(/Edit sequence"/);
    expect(LIST_SRC).not.toMatch(/placeholder="Sequence name"/);
  });

  it("New/Edit CTA reads 'New automation'", () => {
    expect(LIST_SRC).toMatch(/New automation\s*</);
    expect(LIST_SRC).not.toMatch(/New sequence\s*</);
  });
});
