/*!
 * Feb-2026 · Slice H3 — AquaTerra Form Widget
 * Self-contained vanilla JS bundle. No React, no cookies.
 * Embed:
 *   <script async defer src=".../widget/form.js"
 *     data-widget-key="pk_..." data-form-id="frm_..."></script>
 *
 * Renders the form inline where the script tag lives — or replaces
 * a <div data-form-mount> container if the tenant provided one.
 *
 * Turnstile is inserted when the tenant has configured a site key
 * (see GET /api/widget/config → turnstile_site_key). Backend
 * gracefully bypasses verification when the secret isn't set.
 */
(function () {
  "use strict";
  var SCR = document.currentScript ||
    (function () {
      var s = document.getElementsByTagName("script");
      return s[s.length - 1];
    })();
  if (!SCR) return;
  var KEY = SCR.getAttribute("data-widget-key") || "";
  var FORM_ID = SCR.getAttribute("data-form-id") || "";
  var API_BASE = (function () {
    try {
      return new URL(SCR.src).origin;
    } catch (e) {
      return "";
    }
  })();
  if (!KEY || !FORM_ID || !API_BASE) return;

  var MOUNT = document.querySelector("div[data-form-mount][data-form-id='" + FORM_ID + "']")
    || document.querySelector("div[data-form-mount]:not([data-form-id])");
  if (!MOUNT) {
    MOUNT = document.createElement("div");
    SCR.parentNode.insertBefore(MOUNT, SCR);
  }

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

  function api(path, method, body) {
    return fetch(API_BASE + path, {
      method: method || "GET",
      headers: {
        "Content-Type": "application/json",
        "X-Widget-Key": KEY,
      },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      return r.json().then(function (payload) {
        if (!r.ok) throw Object.assign(new Error(payload.detail || r.statusText), { payload: payload, status: r.status });
        return payload;
      });
    });
  }

  var LABEL_STYLE = {
    display: "block",
    fontSize: "13px",
    fontWeight: "600",
    color: "#334155",
    marginBottom: "4px",
  };
  var INPUT_STYLE = {
    width: "100%",
    border: "1px solid #CBD5E1",
    borderRadius: "8px",
    padding: "8px 10px",
    fontSize: "14px",
    boxSizing: "border-box",
    fontFamily: "inherit",
    outline: "none",
  };

  function fieldRow(f, i) {
    var name = f.name || f.id || ("field_" + i);
    var required = !!f.required;
    var opts = f.options || [];
    var labelText = (f.label || name) + (required ? " *" : "");
    var control;
    switch (f.type) {
      case "textarea":
        control = el("textarea", {
          name: name,
          "data-testid": "form-widget-input-" + name,
          rows: "4",
          placeholder: f.placeholder || "",
          required: required ? "" : null,
          style: Object.assign({}, INPUT_STYLE, { resize: "vertical" }),
        });
        break;
      case "dropdown":
      case "select":
        control = el("select", {
          name: name,
          "data-testid": "form-widget-input-" + name,
          required: required ? "" : null,
          style: INPUT_STYLE,
        }, [el("option", { value: "" }, [f.placeholder || "— choose —"])].concat(
          opts.map(function (o) {
            return el("option", { value: o }, [o]);
          })
        ));
        break;
      case "multiselect":
        control = el("select", {
          name: name,
          "data-testid": "form-widget-input-" + name,
          multiple: "",
          required: required ? "" : null,
          style: Object.assign({}, INPUT_STYLE, { minHeight: "84px" }),
        }, opts.map(function (o) { return el("option", { value: o }, [o]); }));
        break;
      case "radio":
        control = el("div", {
          "data-testid": "form-widget-input-" + name,
          style: { display: "flex", flexDirection: "column", gap: "4px" },
        }, opts.map(function (o) {
          return el("label", { style: { fontSize: "14px" } }, [
            el("input", { type: "radio", name: name, value: o, required: required ? "" : null,
                          style: { marginRight: "6px" } }),
            o,
          ]);
        }));
        break;
      case "checkbox":
        control = el("label", { style: { fontSize: "14px" } }, [
          el("input", { type: "checkbox", name: name,
                        "data-testid": "form-widget-input-" + name,
                        required: required ? "" : null,
                        style: { marginRight: "6px" } }),
          f.placeholder || "I agree",
        ]);
        break;
      case "file":
        control = el("input", {
          type: "file",
          name: name,
          "data-testid": "form-widget-input-" + name,
          required: required ? "" : null,
          style: INPUT_STYLE,
        });
        break;
      case "date":
        control = el("input", {
          type: "date", name: name,
          "data-testid": "form-widget-input-" + name,
          required: required ? "" : null, style: INPUT_STYLE,
        });
        break;
      case "number":
        control = el("input", {
          type: "number", name: name,
          "data-testid": "form-widget-input-" + name,
          placeholder: f.placeholder || "", required: required ? "" : null, style: INPUT_STYLE,
        });
        break;
      case "url":
        control = el("input", {
          type: "url", name: name,
          "data-testid": "form-widget-input-" + name,
          placeholder: f.placeholder || "https://…",
          required: required ? "" : null, style: INPUT_STYLE,
        });
        break;
      case "email":
        control = el("input", {
          type: "email", name: name,
          "data-testid": "form-widget-input-" + name,
          placeholder: f.placeholder || "you@example.com",
          required: required ? "" : null, style: INPUT_STYLE,
        });
        break;
      case "phone":
        control = el("input", {
          type: "tel", name: name,
          "data-testid": "form-widget-input-" + name,
          placeholder: f.placeholder || "(555) 555-5555",
          required: required ? "" : null, style: INPUT_STYLE,
        });
        break;
      case "address_google":
      default:
        control = el("input", {
          type: "text", name: name,
          "data-testid": "form-widget-input-" + name,
          placeholder: f.placeholder || "",
          required: required ? "" : null, style: INPUT_STYLE,
        });
    }
    return el("div", {
      "data-testid": "form-widget-field-" + name,
      style: { marginBottom: "14px" },
    }, [
      f.type === "checkbox" ? null : el("label", { style: LABEL_STYLE }, [labelText]),
      control,
    ]);
  }

  function collectAnswers(formEl) {
    var out = {};
    Array.prototype.forEach.call(formEl.elements, function (input) {
      if (!input.name) return;
      if (input.type === "checkbox") {
        out[input.name] = input.checked;
      } else if (input.type === "radio") {
        if (input.checked) out[input.name] = input.value;
      } else if (input.tagName === "SELECT" && input.multiple) {
        out[input.name] = Array.prototype.filter
          .call(input.options, function (o) { return o.selected; })
          .map(function (o) { return o.value; });
      } else if (input.type === "file") {
        // Skip binary uploads for now — H3 sends the metadata only.
        out[input.name] = input.files && input.files[0] ? input.files[0].name : "";
      } else {
        out[input.name] = input.value;
      }
    });
    return out;
  }

  function renderThankYou(msg) {
    MOUNT.innerHTML = "";
    MOUNT.appendChild(el("div", {
      "data-testid": "form-widget-thanks",
      style: {
        padding: "18px 20px",
        border: "1px solid #A7F3D0",
        background: "#ECFDF5",
        color: "#065F46",
        borderRadius: "12px",
        fontSize: "14px",
      },
    }, [msg || "Thanks! We'll be in touch shortly."]));
  }

  function renderError(msg) {
    MOUNT.appendChild(el("div", {
      "data-testid": "form-widget-error",
      style: {
        marginTop: "10px",
        padding: "10px 12px",
        borderRadius: "8px",
        background: "#FEF2F2",
        color: "#991B1B",
        fontSize: "13px",
      },
    }, [msg || "Something went wrong. Please try again."]));
  }

  function renderForm(schema, cfg) {
    MOUNT.innerHTML = "";
    var fields = (schema.fields || []).slice().sort(function (a, b) {
      return (a.order || 0) - (b.order || 0);
    });
    var TURNSTILE_KEY = (cfg && cfg.turnstile_site_key) || null;
    var turnstileHolder = null;

    var form = el("form", {
      "data-testid": "form-widget-form",
      novalidate: "",
      style: {
        background: "#fff",
        border: "1px solid #E2E8F0",
        borderRadius: "12px",
        padding: "20px",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        maxWidth: "520px",
      },
      onsubmit: function (e) {
        e.preventDefault();
        var payload = { answers: collectAnswers(form), page_url: location.href };
        if (TURNSTILE_KEY && window.turnstile && turnstileHolder) {
          try {
            payload.turnstile_token = window.turnstile.getResponse(turnstileHolder) || "";
          } catch (err) {}
        }
        submitBtn.disabled = true;
        submitBtn.textContent = "Sending…";
        api("/api/widget/form/" + encodeURIComponent(FORM_ID) + "/submit", "POST", payload)
          .then(function (r) {
            renderThankYou(r.success_message || schema.success_message);
          })
          .catch(function (err) {
            submitBtn.disabled = false;
            submitBtn.textContent = schema.submit_button_label || "Send";
            renderError((err && err.payload && err.payload.detail) || err.message || "Error");
          });
      },
    }, [
      el("h3", {
        "data-testid": "form-widget-title",
        style: {
          margin: "0 0 14px",
          fontSize: "18px",
          fontWeight: "700",
          color: "#0F172A",
        },
      }, [schema.name || ""]),
    ].concat(fields.map(fieldRow)));

    if (TURNSTILE_KEY) {
      turnstileHolder = el("div", {
        "data-testid": "form-widget-turnstile",
        "class": "cf-turnstile",
        "data-sitekey": TURNSTILE_KEY,
        style: { margin: "10px 0" },
      });
      form.appendChild(turnstileHolder);
      var s = document.createElement("script");
      s.async = true;
      s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
      document.head.appendChild(s);
    }

    var submitBtn = el("button", {
      type: "submit",
      "data-testid": "form-widget-submit-btn",
      style: {
        background: (cfg && cfg.brand_color) || "#0EA5E9",
        color: "#fff",
        border: "none",
        borderRadius: "10px",
        padding: "10px 18px",
        fontSize: "14px",
        fontWeight: "600",
        cursor: "pointer",
        marginTop: "6px",
      },
    }, [schema.submit_button_label || "Send"]);
    form.appendChild(submitBtn);
    MOUNT.appendChild(form);
  }

  Promise.all([
    api("/api/widget/config"),
    api("/api/widget/form/" + encodeURIComponent(FORM_ID)),
  ]).then(function (arr) {
    renderForm(arr[1], arr[0]);
  }).catch(function (err) {
    renderThankYou("Form unavailable.");
  });
})();
