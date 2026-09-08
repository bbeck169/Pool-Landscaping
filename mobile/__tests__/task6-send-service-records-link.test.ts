/**
 * Task 6 · Send Service Records Link — unit tests.
 *
 * 1. Modal renders with correct testIDs.
 * 2. Calls the correct backend endpoints.
 * 3. SendCreateSheet includes the "Service records link" action.
 */
import * as fs from "fs";
import * as path from "path";

describe("Task 6 — Send Service Records Link (mobile parity)", () => {
  const modalSource = fs.readFileSync(
    path.resolve(__dirname, "../src/components/customers/SendServiceRecordsLinkModal.tsx"),
    "utf-8",
  );
  const sheetSource = fs.readFileSync(
    path.resolve(__dirname, "../src/components/customers/SendCreateSheet.tsx"),
    "utf-8",
  );
  const custDetailSource = fs.readFileSync(
    path.resolve(__dirname, "../app/customer/[id].tsx"),
    "utf-8",
  );

  it("modal has the correct testID", () => {
    expect(modalSource).toContain('testID="send-service-records-link-modal"');
  });

  it("modal has send-via-email-btn and send-via-sms-btn tabs", () => {
    expect(modalSource).toContain('testID="send-via-email-btn"');
    expect(modalSource).toContain('testID="send-via-sms-btn"');
  });

  it("modal has copy-link-btn for portal URL", () => {
    expect(modalSource).toContain('testID="copy-link-btn"');
  });

  it("modal has send-service-records-link-btn for the send action", () => {
    expect(modalSource).toContain('testID="send-service-records-link-btn"');
  });

  it("modal calls POST /customers/{cid}/send-service-records-link", () => {
    expect(modalSource).toContain("/send-service-records-link");
    expect(modalSource).toContain("api.post");
    // Body should contain channel
    expect(modalSource).toContain("channel");
  });

  it("modal calls GET /customers/{cid}/service-records-link-status for throttle", () => {
    expect(modalSource).toContain("/service-records-link-status");
    expect(modalSource).toContain("sends_remaining");
  });

  it("modal handles consent flags (email_marketing / sms_marketing / is_muted)", () => {
    expect(modalSource).toContain("email_marketing");
    expect(modalSource).toContain("sms_marketing");
    expect(modalSource).toContain("isMuted");
    expect(modalSource).toContain("Customer opted out of email");
    expect(modalSource).toContain("Customer opted out of SMS");
    expect(modalSource).toContain("Customer is muted");
  });

  it("modal shows throttle-exceeded warning", () => {
    expect(modalSource).toContain('testID="send-records-throttle-exceeded"');
    expect(modalSource).toContain("Hourly send limit reached");
  });

  it("modal shows success alerts with correct copy", () => {
    expect(modalSource).toContain("Sent by email");
    expect(modalSource).toContain("Sent by text");
  });

  it("SendCreateSheet includes service-records-link action", () => {
    expect(sheetSource).toContain("service-records-link");
    expect(sheetSource).toContain("Service Records Link");
    expect(sheetSource).toContain("onServiceRecordsLink");
  });

  it("customer detail screen imports and mounts the modal", () => {
    expect(custDetailSource).toContain("SendServiceRecordsLinkModal");
    expect(custDetailSource).toContain("serviceRecordsLinkOpen");
  });

  it("customer detail screen passes consent props to the modal", () => {
    expect(custDetailSource).toContain("channelOptIn");
    expect(custDetailSource).toContain("isMuted");
  });
});
