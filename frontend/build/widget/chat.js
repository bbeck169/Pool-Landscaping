/*!
 * Feb-2026 · Slice G2 — AquaTerra Chat Widget
 * Self-contained vanilla JS bundle. No React, no framework, no cookies.
 * Embed on tenant marketing sites via:
 *   <script async defer src=".../widget/chat.js" data-widget-key="pk_..."></script>
 *
 * The X-Widget-Key + Origin allowlist are enforced server-side by
 * require_widget_auth; if either fails, the bundle degrades to a
 * "chat unavailable" pill instead of crashing.
 */
(function () {
  "use strict";
  if (window.__AQ_WIDGET_LOADED__) return;
  window.__AQ_WIDGET_LOADED__ = true;

  var CUR_SCRIPT = document.currentScript ||
    (function () {
      var s = document.getElementsByTagName("script");
      return s[s.length - 1];
    })();
  if (!CUR_SCRIPT) return;

  var KEY = CUR_SCRIPT.getAttribute("data-widget-key") || "";
  var API_BASE = (function () {
    try {
      return new URL(CUR_SCRIPT.src).origin;
    } catch (e) {
      return "";
    }
  })();
  if (!KEY || !API_BASE) return;

  var STORAGE_KEY = "aq_widget_conv_" + KEY.slice(-8);
  var STATE = {
    open: false,
    cfg: null,
    conv_id: null,
    messages: [],
    sending: false,
    unavailable: false,
    reason: "",
  };

  // ── DOM helpers ────────────────────────────────────────────────────
  function el(tag, attrs, kids) {
    var e = document.createElement(tag);
    if (attrs) {
      for (var k in attrs) {
        if (k === "style") Object.assign(e.style, attrs[k]);
        else if (k === "html") e.innerHTML = attrs[k];
        else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), attrs[k]);
        else e.setAttribute(k, attrs[k]);
      }
    }
    (kids || []).forEach(function (c) {
      if (c == null) return;
      if (typeof c === "string") e.appendChild(document.createTextNode(c));
      else e.appendChild(c);
    });
    return e;
  }

  // ── API ────────────────────────────────────────────────────────────
  function api(path, method, body) {
    return fetch(API_BASE + path, {
      method: method || "GET",
      headers: {
        "Content-Type": "application/json",
        "X-Widget-Key": KEY,
      },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      if (r.status === 401) throw new Error("unauthorized");
      if (!r.ok) throw new Error("http_" + r.status);
      return r.json();
    });
  }

  function loadConfig() {
    return api("/api/widget/config");
  }
  function startConv() {
    return api("/api/widget/chat/conversations", "POST", {
      page_url: location.href,
      referrer: document.referrer || null,
    });
  }
  function sendMsg(cid, text) {
    return api(
      "/api/widget/chat/conversations/" + encodeURIComponent(cid) + "/messages",
      "POST",
      { text: text }
    );
  }

  // ── Rendering ─────────────────────────────────────────────────────
  var ROOT = null;
  var BUBBLE = null;
  var PANEL = null;
  var THREAD = null;
  var INPUT = null;
  var SEND_BTN = null;

  function ensureRoot() {
    if (ROOT) return;
    ROOT = el("div", {
      id: "aq-widget-root",
      "data-testid": "aq-widget-root",
      style: {
        position: "fixed",
        right: "20px",
        bottom: "20px",
        zIndex: "2147483000",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      },
    });
    document.body.appendChild(ROOT);
  }

  function renderBubble() {
    if (BUBBLE) return;
    var brand = (STATE.cfg && STATE.cfg.brand_color) || "#0EA5E9";
    BUBBLE = el(
      "button",
      {
        "data-testid": "aq-widget-bubble",
        "aria-label": "Open chat",
        onclick: togglePanel,
        style: {
          width: "58px",
          height: "58px",
          borderRadius: "999px",
          border: "none",
          cursor: "pointer",
          background: brand,
          color: "#fff",
          boxShadow: "0 10px 24px rgba(0,0,0,.16)",
          fontSize: "26px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        },
      },
      ["💬"]
    );
    ROOT.appendChild(BUBBLE);
  }

  function panelHeader() {
    var brand = (STATE.cfg && STATE.cfg.brand_color) || "#0EA5E9";
    var name = (STATE.cfg && STATE.cfg.tenant_name) || "Chat";
    return el(
      "div",
      {
        style: {
          padding: "14px 16px",
          background: brand,
          color: "#fff",
          borderTopLeftRadius: "16px",
          borderTopRightRadius: "16px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        },
      },
      [
        el(
          "div",
          {
            style: { fontWeight: "700", fontSize: "15px" },
            "data-testid": "aq-widget-header-name",
          },
          [name]
        ),
        el(
          "button",
          {
            "data-testid": "aq-widget-close-btn",
            "aria-label": "Close chat",
            onclick: togglePanel,
            style: {
              background: "transparent",
              border: "none",
              color: "#fff",
              fontSize: "22px",
              cursor: "pointer",
              lineHeight: "1",
            },
          },
          ["×"]
        ),
      ]
    );
  }

  function renderMessage(m) {
    var isUser = m.role === "user";
    return el(
      "div",
      {
        "data-testid":
          "aq-widget-msg-" + (isUser ? "user" : "assistant"),
        style: {
          display: "flex",
          justifyContent: isUser ? "flex-end" : "flex-start",
          margin: "6px 0",
        },
      },
      [
        el(
          "div",
          {
            style: {
              maxWidth: "80%",
              padding: "8px 12px",
              borderRadius: "14px",
              background: isUser ? "#0EA5E9" : "#F1F5F9",
              color: isUser ? "#fff" : "#0F172A",
              fontSize: "14px",
              whiteSpace: "pre-wrap",
            },
          },
          [m.text || ""]
        ),
      ]
    );
  }

  function refreshThread() {
    if (!THREAD) return;
    THREAD.innerHTML = "";
    STATE.messages.forEach(function (m) {
      THREAD.appendChild(renderMessage(m));
    });
    if (STATE.sending) {
      THREAD.appendChild(
        el(
          "div",
          {
            "data-testid": "aq-widget-typing",
            style: { color: "#64748B", fontSize: "12px", padding: "6px" },
          },
          ["typing…"]
        )
      );
    }
    THREAD.scrollTop = THREAD.scrollHeight;
  }

  function renderPanel() {
    if (PANEL) {
      PANEL.style.display = STATE.open ? "flex" : "none";
      return;
    }
    THREAD = el("div", {
      "data-testid": "aq-widget-thread",
      style: {
        flex: "1",
        overflowY: "auto",
        padding: "12px 14px",
      },
    });

    INPUT = el("textarea", {
      "data-testid": "aq-widget-input",
      placeholder: "Type a message…",
      rows: "2",
      style: {
        flex: "1",
        resize: "none",
        border: "1px solid #E2E8F0",
        borderRadius: "10px",
        padding: "8px 10px",
        fontSize: "14px",
        outline: "none",
        fontFamily: "inherit",
      },
      onkeydown: function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          submitInput();
        }
      },
    });
    SEND_BTN = el(
      "button",
      {
        "data-testid": "aq-widget-send-btn",
        onclick: submitInput,
        style: {
          marginLeft: "8px",
          padding: "8px 14px",
          background: (STATE.cfg && STATE.cfg.brand_color) || "#0EA5E9",
          color: "#fff",
          border: "none",
          borderRadius: "10px",
          cursor: "pointer",
          fontWeight: "600",
          fontSize: "14px",
        },
      },
      ["Send"]
    );

    var composer = el(
      "div",
      {
        style: {
          borderTop: "1px solid #E2E8F0",
          padding: "10px",
          display: "flex",
          alignItems: "flex-end",
          background: "#fff",
          borderBottomLeftRadius: "16px",
          borderBottomRightRadius: "16px",
        },
      },
      [INPUT, SEND_BTN]
    );

    PANEL = el(
      "div",
      {
        "data-testid": "aq-widget-panel",
        style: {
          position: "absolute",
          bottom: "70px",
          right: "0",
          width: "340px",
          maxWidth: "calc(100vw - 40px)",
          height: "460px",
          maxHeight: "calc(100vh - 80px)",
          background: "#fff",
          borderRadius: "16px",
          boxShadow: "0 24px 60px rgba(0,0,0,.24)",
          display: STATE.open ? "flex" : "none",
          flexDirection: "column",
          overflow: "hidden",
        },
      },
      [panelHeader(), THREAD, composer]
    );
    ROOT.appendChild(PANEL);
    refreshThread();
  }

  function renderUnavailable() {
    ensureRoot();
    ROOT.innerHTML = "";
    ROOT.appendChild(
      el(
        "div",
        {
          "data-testid": "aq-widget-unavailable",
          style: {
            background: "#F1F5F9",
            color: "#475569",
            padding: "8px 14px",
            borderRadius: "999px",
            fontSize: "12px",
            boxShadow: "0 6px 20px rgba(0,0,0,.08)",
          },
        },
        ["Chat unavailable"]
      )
    );
  }

  // ── Interaction ────────────────────────────────────────────────────
  function togglePanel() {
    if (STATE.unavailable) return;
    STATE.open = !STATE.open;
    if (STATE.open && !STATE.conv_id) {
      ensureConv().then(function () {
        renderPanel();
      });
    } else {
      renderPanel();
    }
  }

  function ensureConv() {
    // Rehydrate from localStorage first.
    try {
      var saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved) {
        var parsed = JSON.parse(saved);
        if (parsed && parsed.conv_id) {
          STATE.conv_id = parsed.conv_id;
          STATE.messages = parsed.messages || [];
          if ((STATE.cfg || {}).welcome_message && !STATE.messages.length) {
            STATE.messages.push({
              role: "assistant",
              text: STATE.cfg.welcome_message,
            });
          }
          return Promise.resolve();
        }
      }
    } catch (e) {}
    return startConv().then(function (r) {
      STATE.conv_id = r.conversation_id || r.id;
      if ((STATE.cfg || {}).welcome_message) {
        STATE.messages.push({
          role: "assistant",
          text: STATE.cfg.welcome_message,
        });
      }
      persist();
    });
  }

  function persist() {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          conv_id: STATE.conv_id,
          messages: STATE.messages.slice(-30),
        })
      );
    } catch (e) {}
  }

  function submitInput() {
    if (!INPUT) return;
    var text = INPUT.value.trim();
    if (!text || STATE.sending) return;
    INPUT.value = "";
    STATE.messages.push({ role: "user", text: text });
    STATE.sending = true;
    refreshThread();
    sendMsg(STATE.conv_id, text)
      .then(function (r) {
        var reply = (r && r.assistant_message && r.assistant_message.text) || "";
        STATE.messages.push({ role: "assistant", text: reply });
      })
      .catch(function (e) {
        STATE.messages.push({
          role: "assistant",
          text: "Sorry — I hit an error. Please try again in a moment.",
        });
      })
      .then(function () {
        STATE.sending = false;
        persist();
        refreshThread();
      });
  }

  // ── Boot ───────────────────────────────────────────────────────────
  function boot() {
    ensureRoot();
    loadConfig()
      .then(function (cfg) {
        STATE.cfg = cfg;
        renderBubble();
      })
      .catch(function (e) {
        STATE.unavailable = true;
        STATE.reason = e && e.message ? e.message : "error";
        renderUnavailable();
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
