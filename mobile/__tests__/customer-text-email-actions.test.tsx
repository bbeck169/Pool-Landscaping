/**
 * Ticket 1 · Customer detail Text + Email actions + CustomerEmailComposeSheet
 * (web SendComposeModal email parity minus attachments / AI draft — D1a).
 * Screen wiring is source-locked; the sheet is fully rendered.
 */
import React from "react";
import fs from "fs";
import path from "path";
import { render, fireEvent, waitFor } from "@testing-library/react-native";

const mockGet = jest.fn();
const mockPost = jest.fn();
const mockToast = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockGet(...a), post: (...a: any[]) => mockPost(...a) },
  ApiError: class ApiError extends Error { detail: any; },
}));
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockToast }) }));

import CustomerEmailComposeSheet from "@/src/components/customers/CustomerEmailComposeSheet";

const CUST = { id: "c1", name: "Jane Pool" };
const TPL = { id: "t1", name: "Welcome", subject: "Hi {{customer.first_name}}", body: "Welcome aboard" };

function mount(onClose = jest.fn(), onSent = jest.fn()) {
  const r = render(<CustomerEmailComposeSheet customer={CUST} to="jane@x.com" onClose={onClose} onSent={onSent} />);
  return { r, onClose, onSent };
}

beforeEach(() => {
  mockGet.mockReset(); mockPost.mockReset(); mockToast.mockReset();
  mockGet.mockResolvedValue({ templates: [TPL] });
});

describe("CustomerEmailComposeSheet", () => {
  it("loads active email templates; picking fills subject + body; Custom clears", async () => {
    const { r } = mount();
    await waitFor(() => r.getByTestId("customer-email-compose-template-t1"));
    expect(mockGet).toHaveBeenCalledWith("/marketing/templates?channel=email&active=true");
    fireEvent.press(r.getByTestId("customer-email-compose-template-t1"));
    expect(r.getByTestId("customer-email-compose-subject").props.value).toBe(TPL.subject);
    expect(r.getByTestId("customer-email-compose-body").props.value).toBe(TPL.body);
    fireEvent.press(r.getByTestId("customer-email-compose-template-custom"));
    expect(r.getByTestId("customer-email-compose-body").props.value).toBe("");
  });

  it("empty template list shows empty hint (Custom still available)", async () => {
    mockGet.mockResolvedValueOnce({ templates: [] });
    const { r } = mount();
    await waitFor(() => r.getByTestId("customer-email-compose-templates-empty"));
    expect(r.getByTestId("customer-email-compose-template-custom")).toBeTruthy();
  });

  it("Preview posts {channel, subject, body} and renders the result + unresolved tokens", async () => {
    mockPost.mockResolvedValueOnce({ channel: "email", subject_rendered: "Hi Jane", body_rendered: "Welcome aboard", unresolved_tokens: ["JOB_DATE"] });
    const { r } = mount();
    await waitFor(() => r.getByTestId("customer-email-compose-template-t1"));
    fireEvent.press(r.getByTestId("customer-email-compose-template-t1"));
    fireEvent.press(r.getByTestId("customer-email-compose-preview-btn"));
    await waitFor(() => r.getByTestId("customer-email-compose-preview"));
    expect(mockPost).toHaveBeenCalledWith("/customers/c1/preview-message", { channel: "email", subject: TPL.subject, body: TPL.body });
    expect(r.getByTestId("customer-email-compose-preview-subject").props.children).toBe("Hi Jane");
    expect(r.getByTestId("customer-email-compose-preview-unresolved").props.children).toContain("JOB_DATE");
  });

  it("Preview with empty body does not call the BE", async () => {
    const { r } = mount();
    await waitFor(() => r.getByTestId("customer-email-compose-templates"));
    fireEvent.press(r.getByTestId("customer-email-compose-preview-btn"));
    expect(mockPost).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith("Nothing to preview", "error");
  });

  it("Send is disabled until body has text", async () => {
    const { r } = mount();
    await waitFor(() => r.getByTestId("customer-email-compose-templates"));
    fireEvent.press(r.getByTestId("customer-email-compose-send"));
    expect(mockPost).not.toHaveBeenCalled();
  });

  it("Send posts send-email with subject fallback, toasts, closes", async () => {
    mockPost.mockResolvedValueOnce({ ok: true });
    const { r, onClose, onSent } = mount();
    await waitFor(() => r.getByTestId("customer-email-compose-templates"));
    fireEvent.changeText(r.getByTestId("customer-email-compose-body"), "See you Tuesday");
    fireEvent.press(r.getByTestId("customer-email-compose-send"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(mockPost).toHaveBeenCalledWith("/customers/c1/send-email", {
      to: "jane@x.com", subject: "Message from Jane Pool", body: "See you Tuesday", customer_id: "c1",
    });
    expect(mockToast).toHaveBeenCalledWith("Message sent", "success");
    expect(onSent).toHaveBeenCalled();
  });

  it("Send failure surfaces the BE detail and keeps the sheet open", async () => {
    mockPost.mockRejectedValueOnce(Object.assign(new Error("x"), { detail: "recipient not among the customer's emails" }));
    const { r, onClose } = mount();
    await waitFor(() => r.getByTestId("customer-email-compose-templates"));
    fireEvent.changeText(r.getByTestId("customer-email-compose-body"), "Hello");
    fireEvent.press(r.getByTestId("customer-email-compose-send"));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith("recipient not among the customer's emails", "error"));
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("Customer detail action row wiring (source lock)", () => {
  const SRC = fs.readFileSync(path.join(__dirname, "../app/customer/[id].tsx"), "utf8");
  const row = SRC.slice(SRC.indexOf('testID="customer-action-row"'), SRC.indexOf('testID="customer-delete-button"') + 40);
  it("D3a order: Edit · Call · Text · Email · Switch · Issue Credit · Delete", () => {
    const ids = ["customer-action-edit", "customer-action-call", "customer-action-text", "customer-action-email",
      "impersonate-customer-button", "customer-action-issue-credit", "customer-delete-button"];
    const pos = ids.map((id) => row.indexOf(`testID="${id}"`));
    pos.forEach((p, i) => expect([ids[i], p > -1]).toEqual([ids[i], true]));
    expect([...pos].sort((a, b) => a - b)).toEqual(pos);
  });
  it("Text → native sms: with the same primaryPhone gate as Call", () => {
    expect(row).toMatch(/\{primaryPhone \? \(\s*<TouchableOpacity[\s\S]{0,200}Linking\.openURL\(`sms:\$\{String\(primaryPhone\)[\s\S]{0,80}testID="customer-action-text"/);
  });
  it("Email gated on isAdmin && primaryEmail and opens the sheet", () => {
    expect(row).toMatch(/\{isAdmin && primaryEmail \? \(\s*<TouchableOpacity[\s\S]{0,120}onPress=\{\(\) => setEmailComposeOpen\(true\)\}\s*testID="customer-action-email"/);
    expect(SRC).toContain("<CustomerEmailComposeSheet customer={c} to={primaryEmail} onClose={() => setEmailComposeOpen(false)} />");
  });
});
