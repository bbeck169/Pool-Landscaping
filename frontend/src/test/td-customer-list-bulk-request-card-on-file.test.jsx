/**
 * TD-customer-list-bulk-request-card-on-file · Feb-2026.
 *
 * FE contract tests for Ticket I's "Request card on file" bulk
 * action in the Customers list toolbar.
 *
 * Two layers:
 *   1. ``CustomersList.jsx`` source assertions — the toolbar action
 *      is wired as the 4th admin-only entry alongside Reassign /
 *      Merge / Mark inactive / Delete.  The modal mounts with the
 *      selected customer_ids array + a clear-selection ``onSent``
 *      callback.  Source-level assertion (same style as the TD-86
 *      companion suite); rendering the full 4-kloc CustomersList
 *      under JSDOM would need >25 provider stubs.
 *   2. ``RequestCardOnFileModal.jsx`` under test — real render,
 *      api mocked.  Covers: tenant-scoped template fetch, auto-
 *      preselection of ``add_card_request_email`` /
 *      ``add_card_request_sms`` by ``code``, live preview call,
 *      send POST body, categorised 403 error panel, success
 *      summary tallies.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import { render, screen, cleanup, waitFor, fireEvent, act } from "@testing-library/react";

const SRC_LIST = fs.readFileSync(
  path.resolve(__dirname, "../pages/customers/CustomersList.jsx"), "utf8",
);


// ─── CustomersList.jsx source-level wiring ───────────────────────
describe("Ticket I · CustomersList toolbar wiring", () => {
  it("imports the RequestCardOnFileModal from the customers module", () => {
    expect(SRC_LIST).toMatch(
      /import RequestCardOnFileModal from "@\/pages\/customers\/RequestCardOnFileModal";/,
    );
  });

  it("declares a requestCardOpen state hook", () => {
    expect(SRC_LIST).toMatch(
      /const \[requestCardOpen, setRequestCardOpen\] = useState\(false\);/,
    );
  });

  it("renders a 'Request card on file' action gated to admin + !selectAllMatching", () => {
    // Admin-only (not isAdminOrManager — matches the Reassign-owner /
    // Merge gates) + skipped when selectAllMatching is on (modal
    // needs concrete ids).
    expect(SRC_LIST).toMatch(
      /isAdmin && !selectAllMatching \? \[\{\s*\n\s*key: "request-card"/,
    );
    expect(SRC_LIST).toMatch(/label: "Request card on file"/);
    expect(SRC_LIST).toMatch(/onClick: \(\) => setRequestCardOpen\(true\)/);
  });

  it("mounts the modal with Array.from(selected) + clear-selection on sent", () => {
    expect(SRC_LIST).toMatch(
      /<RequestCardOnFileModal\s*\n\s*open=\{requestCardOpen\}/,
    );
    expect(SRC_LIST).toMatch(/customerIds=\{Array\.from\(selected\)\}/);
    expect(SRC_LIST).toMatch(
      /onSent=\{\(\) => \{ setSelected\(new Set\(\)\); setSelectAllMatching\(false\); \}\}/,
    );
  });

  it("does NOT reintroduce a legacy auto-prune or sync delete alongside the new action", () => {
    // Negative guard — if someone later adds a filter() against
    // ``selected`` in the modal mount path, the new action loses its
    // "operator-selected is source of truth" contract (same rule as
    // the Ticket G crew-edit ship).
    expect(SRC_LIST).not.toMatch(
      /customerIds=\{Array\.from\(selected\)\.filter\(/,
    );
  });
});


// ─── Modal under test ────────────────────────────────────────────
const getMock = vi.fn();
const postMock = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => getMock(...a),
    post: (...a) => postMock(...a),
    patch: vi.fn().mockResolvedValue({}),
    put: vi.fn().mockResolvedValue({}),
  },
  TOKEN_KEY: "token",
}));

vi.mock("@/components/ui-kit", () => ({
  Button: ({ children, onClick, disabled, "data-testid": tid }) => (
    <button onClick={onClick} disabled={disabled} data-testid={tid}>{children}</button>
  ),
  Modal: ({ open, children, "data-testid": tid }) =>
    open ? <div data-testid={tid}>{children}</div> : null,
}));


import RequestCardOnFileModal from "@/pages/customers/RequestCardOnFileModal";


afterEach(() => {
  cleanup();
  getMock.mockReset();
  postMock.mockReset();
});


function _templatesPayload({ withCardEmail = true, withCardSms = true } = {}) {
  const email = [{ id: "tpl-e-generic", code: "generic", name: "Generic Email" }];
  const sms   = [{ id: "tpl-s-generic", code: "generic", name: "Generic SMS" }];
  if (withCardEmail) email.push({
    id: "tpl-e-card", code: "add_card_request_email", name: "Add Card — Email",
  });
  if (withCardSms) sms.push({
    id: "tpl-s-card", code: "add_card_request_sms", name: "Add Card — SMS",
  });
  return { email, sms };
}


function _wireMocks({ templates = _templatesPayload(), previewByTid = {} } = {}) {
  getMock.mockImplementation((url) => {
    if (String(url).includes("channel=email"))
      return Promise.resolve({ templates: templates.email });
    if (String(url).includes("channel=sms"))
      return Promise.resolve({ templates: templates.sms });
    return Promise.resolve({});
  });
  postMock.mockImplementation((url, body) => {
    if (String(url).startsWith("/marketing/templates/")
        && String(url).endsWith("/preview")) {
      const tid = String(url).split("/")[3];
      return Promise.resolve(previewByTid[tid] || {
        subject: "Please add a card", body: `Preview for ${tid}`,
      });
    }
    if (String(url) === "/customers/bulk-request-card") {
      // Default success response — tests override as needed.
      return Promise.resolve({
        results: body.customer_ids.map((cid) => ({
          customer_id: cid, status: "sent_both",
          email_status: "sent", sms_status: "sent",
        })),
        counts: { email_sent: body.customer_ids.length,
                  sms_sent: body.customer_ids.length,
                  skipped: 0, error: 0 },
      });
    }
    return Promise.resolve({});
  });
}


describe("Ticket I · RequestCardOnFileModal", () => {
  it("fetches tenant-scoped templates on open (both channels)", async () => {
    _wireMocks();
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1"]} onSent={() => {}} />);

    await waitFor(() => {
      const urls = getMock.mock.calls.map((c) => String(c[0]));
      expect(urls.some((u) => u.startsWith("/marketing/templates") && u.includes("channel=email"))).toBe(true);
      expect(urls.some((u) => u.startsWith("/marketing/templates") && u.includes("channel=sms"))).toBe(true);
    });
  });

  it("auto-pre-selects templates matching the card-request codes", async () => {
    _wireMocks({ templates: _templatesPayload() });
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1"]} onSent={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTestId("request-card-email-select").value).toBe("tpl-e-card");
    });
    expect(screen.getByTestId("request-card-sms-select").value).toBe("tpl-s-card");
  });

  it("falls back to no selection when no card-request template exists", async () => {
    _wireMocks({ templates: _templatesPayload({ withCardEmail: false, withCardSms: false }) });
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1"]} onSent={() => {}} />);

    await waitFor(() => {
      expect(screen.getByTestId("request-card-email-select")).toBeTruthy();
    });
    expect(screen.getByTestId("request-card-email-select").value).toBe("");
    expect(screen.getByTestId("request-card-sms-select").value).toBe("");
  });

  it("fires POST /customers/bulk-request-card with the full id array + both template ids", async () => {
    _wireMocks();
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1", "c-2", "c-3"]} onSent={() => {}} />);

    await waitFor(() => expect(screen.getByTestId("request-card-confirm")).toBeTruthy());
    await act(async () => fireEvent.click(screen.getByTestId("request-card-confirm")));

    const sendCall = postMock.mock.calls.find(
      (c) => String(c[0]) === "/customers/bulk-request-card",
    );
    expect(sendCall).toBeTruthy();
    expect(sendCall[1]).toEqual({
      customer_ids: ["c-1", "c-2", "c-3"],
      email_template_id: "tpl-e-card",
      sms_template_id:   "tpl-s-card",
    });
  });

  it("renders the per-row summary + tallies on 200", async () => {
    _wireMocks();
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1", "c-2"]} onSent={() => {}} />);

    await waitFor(() => expect(screen.getByTestId("request-card-confirm")).toBeTruthy());
    await act(async () => fireEvent.click(screen.getByTestId("request-card-confirm")));

    await waitFor(() => expect(screen.getByTestId("request-card-summary")).toBeTruthy());
    expect(screen.getByTestId("summary-email-sent").textContent).toContain("2");
    expect(screen.getByTestId("summary-sms-sent").textContent).toContain("2");
    expect(screen.getByTestId("summary-row-c-1")).toBeTruthy();
    expect(screen.getByTestId("summary-row-c-2")).toBeTruthy();
  });

  it("surfaces categorised errors inline on 403 tenant_isolation_breach", async () => {
    _wireMocks();
    // Override the bulk send to throw a 403 with the categorised shape.
    postMock.mockImplementation((url) => {
      if (String(url) === "/customers/bulk-request-card") {
        const err = new Error("Forbidden");
        err.status = 403;
        err.data = { detail: {
          error: "tenant_isolation_breach",
          errors: [
            { customer_id: "c-foreign", reason: "foreign_tenant", tenant_id: "other" },
            { customer_id: "c-orphan",  reason: "orphan" },
          ],
        }};
        return Promise.reject(err);
      }
      if (String(url).startsWith("/marketing/templates/"))
        return Promise.resolve({ subject: "s", body: "b" });
      return Promise.resolve({});
    });

    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-foreign", "c-orphan"]} onSent={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("request-card-confirm")).toBeTruthy());
    await act(async () => fireEvent.click(screen.getByTestId("request-card-confirm")));

    await waitFor(() =>
      expect(screen.getByTestId("request-card-error-panel")).toBeTruthy(),
    );
    expect(screen.getByTestId("request-card-error-foreign_tenant")).toBeTruthy();
    expect(screen.getByTestId("request-card-error-orphan")).toBeTruthy();
  });

  it("recipient count label matches customerIds.length", async () => {
    _wireMocks();
    render(<RequestCardOnFileModal
      open={true} onClose={() => {}}
      customerIds={["c-1", "c-2", "c-3", "c-4"]} onSent={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("request-card-recipient-count")).toBeTruthy());
    expect(screen.getByTestId("request-card-recipient-count").textContent).toContain("4");
  });
});
