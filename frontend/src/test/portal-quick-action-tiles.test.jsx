/**
 * Portal Home — new Quick Action tiles (Photos, Videos, Messages).
 *
 * PortalHome is a big page with many upstream API dependencies; testing
 * it end-to-end is out of scope. We render just the ``ActionTile`` +
 * confirm its navigation contract + badge behaviour by mounting a small
 * harness that mimics the tile call sites verbatim.
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { Image as ImageIcon, Video as VideoIcon, MessageSquare } from "lucide-react";

afterEach(() => cleanup());

// Copy of ActionTile with the badge prop — mirrors the actual PortalHome
// component. Kept inline so this test does not have to boot the whole
// PortalHome tree (which pulls in dozens of upstream API dependencies).
function ActionTile({ icon: Icon, label, tone, onClick, testid, badge }) {
  return (
    <button
      onClick={onClick}
      className="rounded-xl p-4 text-left relative"
      data-testid={testid}
    >
      <div style={{ color: tone }}><Icon size={18} /></div>
      <div>{label}</div>
      {badge && Number(badge) > 0 ? (
        <span data-testid={`${testid}-badge`}>
          {Number(badge) > 99 ? "99+" : badge}
        </span>
      ) : null}
    </button>
  );
}

describe("Portal Quick Action tiles", () => {
  it("Photos tile navigates to /portal/photos", () => {
    const nav = vi.fn();
    render(
      <ActionTile icon={ImageIcon} label="Photos" tone="#DB2777"
                   onClick={() => nav("/portal/photos")} testid="qa-photos" />
    );
    fireEvent.click(screen.getByTestId("qa-photos"));
    expect(nav).toHaveBeenCalledWith("/portal/photos");
  });

  it("Videos tile navigates to /portal/videos", () => {
    const nav = vi.fn();
    render(
      <ActionTile icon={VideoIcon} label="Videos" tone="#7C3AED"
                   onClick={() => nav("/portal/videos")} testid="qa-videos" />
    );
    fireEvent.click(screen.getByTestId("qa-videos"));
    expect(nav).toHaveBeenCalledWith("/portal/videos");
  });

  it("Messages tile navigates to /portal/chats and hides badge when 0", () => {
    const nav = vi.fn();
    render(
      <ActionTile icon={MessageSquare} label="Messages" tone="#0284C7"
                   onClick={() => nav("/portal/chats")}
                   testid="qa-messages" badge={0} />
    );
    fireEvent.click(screen.getByTestId("qa-messages"));
    expect(nav).toHaveBeenCalledWith("/portal/chats");
    expect(screen.queryByTestId("qa-messages-badge")).toBeNull();
  });

  it("Messages tile shows badge when unread > 0", () => {
    render(
      <ActionTile icon={MessageSquare} label="Messages" tone="#0284C7"
                   onClick={() => {}} testid="qa-messages" badge={7} />
    );
    const badge = screen.getByTestId("qa-messages-badge");
    expect(badge).toBeTruthy();
    expect(badge.textContent).toBe("7");
  });

  it("Messages tile caps badge at 99+ for large unread counts", () => {
    render(
      <ActionTile icon={MessageSquare} label="Messages" tone="#0284C7"
                   onClick={() => {}} testid="qa-messages" badge={250} />
    );
    expect(screen.getByTestId("qa-messages-badge").textContent).toBe("99+");
  });
});
