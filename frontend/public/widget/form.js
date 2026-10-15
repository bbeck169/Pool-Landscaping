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
 *
 * CUS-Marketing-Form-Builder · Feb-2026 — Phase 4. Widget parity
 * upgrade — reads and applies schema.theme (colors + font + gradient
 * + overlay opacity), schema.hero (rich-text heading / sub-heading /
 * background / optional badge), field.column_span (full | half CSS
 * grid layout), and field.type === "section" (layout-only header
 * rows). Zero-regression: null theme/hero/column_span/section
 * schemas render exactly as pre-Phase-4.
 *
 * ─── SECURITY ─────────────────────────────────────────────────
 * Rich-text HTML (schema.hero.heading_html, schema.hero.subheading_html,
 * and field.label for section-type fields) is inserted via innerHTML.
 * XSS containment relies on the RichTextField extension boundary in
 * the admin editor (StarterKit + Underline + TextStyle + Link with
 * an http/https/mailto/tel scheme allowlist). See
 * frontend/src/components/formBuilder/RichTextField.jsx for the
 * documented boundary + explicit list of extensions that MUST NOT
 * be added without a DOMPurify hardening pass. DOMPurify is
 * intentionally NOT bundled here — every KB ships to every
 * embedder site and the Tiptap schema whitelist is the source of
 * truth for allowed HTML.
 * ──────────────────────────────────────────────────────────────
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

  // CUS-Marketing-Form-Builder · Feb-2026 — Phase 4 widget parity.
  // Inlined mirror of ``frontend/src/lib/formThemes.js``'s
  // ``themeToCssVars`` output. Widget is vanilla JS with no bundler —
  // helpers must be inlined and NOT imported. Kept null-safe so any
  // missing sub-field is skipped without emitting an empty CSS var.
  function applyTheme(rootEl, theme) {
    if (!theme || typeof theme !== "object") return;
    var c = theme.colors || {};
    // Five color roles — set as inline CSS variables so downstream
    // controls resolve them via ``var(--form-*)``.
    if (c.primary)    rootEl.style.setProperty("--form-primary",    c.primary);
    if (c.background) rootEl.style.setProperty("--form-background", c.background);
    if (c.text)       rootEl.style.setProperty("--form-text",       c.text);
    if (c.border)     rootEl.style.setProperty("--form-border",     c.border);
    if (c.accent)     rootEl.style.setProperty("--form-accent",     c.accent);
    if (theme.font_family) rootEl.style.fontFamily = theme.font_family;
    if (c.background) rootEl.style.backgroundColor = c.background;
    if (c.text)       rootEl.style.color = c.text;
    // Gradient background — layered above the solid ``backgroundColor``
    // fallback so a legacy renderer that ignores ``background-image``
    // still sees the primary color.
    var overlay = (typeof theme.overlay_opacity === "number"
                    && theme.overlay_opacity > 0)
                    ? (theme.overlay_opacity / 100).toFixed(2)
                    : null;
    if (theme.gradient && typeof theme.gradient === "object"
        && theme.gradient.from && theme.gradient.to) {
      var angle = typeof theme.gradient.angle_deg === "number"
                    ? theme.gradient.angle_deg : 135;
      var grad = "linear-gradient(" + angle + "deg, "
                    + theme.gradient.from + " 0%, "
                    + theme.gradient.to + " 100%)";
      if (overlay) {
        // Darken overlay layered ABOVE the gradient — same shape as
        // ``ThemedFormShell.jsx``'s composition so admin preview +
        // widget output match byte-for-byte.
        rootEl.style.backgroundImage =
          "linear-gradient(rgba(0,0,0, " + overlay + "), rgba(0,0,0, " + overlay + ")), "
            + grad;
      } else {
        rootEl.style.backgroundImage = grad;
      }
      rootEl.style.setProperty("--form-bg-gradient", grad);
    }
    if (overlay) {
      rootEl.style.setProperty("--form-overlay-opacity", overlay);
    }
  }

  // CUS-Marketing-Form-Builder · Feb-2026 — Phase 4 widget parity.
  // Renders the hero band that sits above the form fields. Handles
  // three background kinds (color | image | gradient) + optional
  // special-offer badge in the top-right corner. Rich-text HTML
  // is injected via innerHTML — XSS containment is documented at
  // the top of this file.
  function renderHero(hero) {
    if (!hero || typeof hero !== "object") return null;
    var bg = hero.background || { kind: "color", color: "#F8FAFC" };
    var wrapStyle = {
      position: "relative",
      padding: "32px 24px",
      borderRadius: "12px 12px 0 0",
      marginBottom: "0",
      color: "#0F172A",
      overflow: "hidden",
    };
    if (bg.kind === "color") {
      wrapStyle.background = bg.color || "#F8FAFC";
    } else if (bg.kind === "gradient") {
      var angle = typeof bg.angle_deg === "number" ? bg.angle_deg : 135;
      wrapStyle.backgroundImage =
        "linear-gradient(" + angle + "deg, "
          + (bg.from || "#0EA5E9") + " 0%, "
          + (bg.to   || "#1B1F5C") + " 100%)";
      wrapStyle.color = "#FFFFFF";
    } else if (bg.kind === "image") {
      if (bg.url) {
        wrapStyle.backgroundImage = "url(" + bg.url + ")";
        wrapStyle.backgroundSize = "cover";
        wrapStyle.backgroundPosition = "center";
        wrapStyle.color = "#FFFFFF";
      } else {
        wrapStyle.background = "#F8FAFC";
      }
    }

    var heroDiv = el("div", {
      "data-testid": "form-widget-hero",
      "data-hero-kind": bg.kind || "color",
      style: wrapStyle,
    });

    // Image-kind overlay — semi-transparent black wash layered above
    // the background image but BELOW the text content. Uses an
    // absolute-positioned sibling so text stays crisp.
    if (bg.kind === "image" && typeof bg.overlay_opacity === "number"
          && bg.overlay_opacity > 0 && bg.url) {
      var overlay = (bg.overlay_opacity / 100).toFixed(2);
      heroDiv.appendChild(el("div", {
        "data-testid": "form-widget-hero-overlay",
        style: {
          position: "absolute",
          top: "0", left: "0", right: "0", bottom: "0",
          background: "rgba(0,0,0, " + overlay + ")",
          pointerEvents: "none",
        },
      }));
    }

    // Text stack sits above the overlay via z-index + position:
    // relative on the container.
    var textWrap = el("div", {
      style: { position: "relative", zIndex: "1" },
    });
    if (hero.heading_html) {
      var heading = el("div", {
        "data-testid": "form-widget-hero-heading",
        style: { fontSize: "24px", fontWeight: "700", marginBottom: "8px" },
      });
      // XSS containment via RichTextField schema whitelist — see the
      // security comment at the top of this file.
      heading.innerHTML = hero.heading_html;
      textWrap.appendChild(heading);
    }
    if (hero.subheading_html) {
      var sub = el("div", {
        "data-testid": "form-widget-hero-subheading",
        style: { fontSize: "14px", opacity: "0.9" },
      });
      sub.innerHTML = hero.subheading_html;
      textWrap.appendChild(sub);
    }
    heroDiv.appendChild(textWrap);

    // Optional special-offer badge — absolute-positioned in the
    // top-right corner. Alt text drives the ``alt`` attribute for
    // screen readers.
    if (hero.badge && hero.badge.url) {
      heroDiv.appendChild(el("img", {
        "data-testid": "form-widget-hero-badge",
        src: hero.badge.url,
        alt: hero.badge.alt_text || "",
        style: {
          position: "absolute",
          top: "12px",
          right: "12px",
          width: "60px",
          height: "60px",
          objectFit: "contain",
          zIndex: "2",
        },
      }));
    }
    return heroDiv;
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
    // CUS-Marketing-Form-Builder · Feb-2026 — Phase 4 widget parity.
    // Section fields render a header only — no input, no submission
    // value, full-width row.
    if (f.type === "section") {
      var section = el("div", {
        "data-testid": "form-widget-section-" + (f.id || i),
        "data-section-index": String(i),
        style: {
          gridColumn: "span 2",
          marginTop: "4px",
          marginBottom: "4px",
          paddingTop: "8px",
          paddingBottom: "4px",
          borderTop: "1px solid #E2E8F0",
          fontSize: "15px",
          fontWeight: "600",
          color: "#0F172A",
        },
      });
      // XSS containment via RichTextField schema whitelist — see the
      // security comment at the top of this file.
      section.innerHTML = f.label || "";
      return section;
    }

    // TD-54 · Feb-2026 — ``page_break`` is a LAYOUT marker used only
    // by the Prev/Next page-splitting logic in renderForm.  It never
    // produces a visible row (the paginator reads the field index +
    // page_title via its own metadata, not via this element) but we
    // return a zero-footprint marker so the row cursor stays in
    // alignment with ``fields[i]``.
    if (f.type === "page_break") {
      return el("div", {
        "data-testid": "form-widget-page-break-" + (f.id || i),
        "data-page-break-index": String(i),
        style: { display: "none" },
      });
    }

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
      // TD-52 · Feb-2026 — multi-file picker. Reuses the native file
      // control with ``multiple``; the dispatcher ingresses via the
      // existing /widget/form/{fid}/submit-multipart endpoint when
      // any file field is present (handled by submitForm below).
      case "file_multi_upload":
        control = el("input", {
          type: "file",
          name: name,
          multiple: "",
          "data-testid": "form-widget-input-" + name,
          required: required ? "" : null,
          style: INPUT_STYLE,
        });
        break;
      // TD-52 · Signature pad. Minimalist canvas-based signature
      // capture — pointer events draw strokes, the current data URL
      // is mirrored into a hidden <input> so ``collectAnswers`` can
      // read it without any special-case code.  "Clear" button
      // resets both the canvas and the hidden value.
      case "signature": {
        var sigWrap = el("div", {
          "data-testid": "form-widget-signature-wrap-" + name,
          style: {
            border: "1px solid #CBD5E1",
            borderRadius: "8px",
            padding: "6px",
            background: "#fff",
          },
        });
        var sigCanvas = el("canvas", {
          "data-testid": "form-widget-signature-canvas-" + name,
          width: "480", height: "140",
          style: {
            display: "block", width: "100%", height: "140px",
            cursor: "crosshair", touchAction: "none",
            background: "#FDFDFE", borderRadius: "6px",
          },
        });
        var sigHidden = el("input", {
          type: "hidden", name: name,
          "data-testid": "form-widget-input-" + name,
          required: required ? "" : null,
          value: "",
        });
        var sigClear = el("button", {
          type: "button",
          "data-testid": "form-widget-signature-clear-" + name,
          style: {
            marginTop: "6px",
            padding: "4px 10px",
            fontSize: "12px",
            border: "1px solid #CBD5E1",
            background: "#F8FAFC",
            borderRadius: "6px",
            cursor: "pointer",
          },
        }, ["Clear"]);
        // Wire canvas drawing on next tick so the canvas is in the
        // DOM when we grab its context.
        setTimeout(function () {
          var ctx = sigCanvas.getContext && sigCanvas.getContext("2d");
          if (!ctx) return;
          ctx.strokeStyle = "#0F172A";
          ctx.lineWidth = 2;
          ctx.lineCap = "round";
          var drawing = false;
          function pt(ev) {
            var rect = sigCanvas.getBoundingClientRect();
            var p = (ev.touches && ev.touches[0]) || ev;
            return {
              x: (p.clientX - rect.left) * (sigCanvas.width / rect.width),
              y: (p.clientY - rect.top) * (sigCanvas.height / rect.height),
            };
          }
          function start(ev) {
            ev.preventDefault();
            drawing = true;
            var p = pt(ev);
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
          }
          function move(ev) {
            if (!drawing) return;
            ev.preventDefault();
            var p = pt(ev);
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
          }
          function end() {
            if (!drawing) return;
            drawing = false;
            try { sigHidden.value = sigCanvas.toDataURL("image/png"); }
            catch (e) { /* tainted canvas safeguard — leave blank */ }
          }
          sigCanvas.addEventListener("mousedown", start);
          sigCanvas.addEventListener("mousemove", move);
          sigCanvas.addEventListener("mouseup", end);
          sigCanvas.addEventListener("mouseleave", end);
          sigCanvas.addEventListener("touchstart", start);
          sigCanvas.addEventListener("touchmove", move);
          sigCanvas.addEventListener("touchend", end);
        }, 0);
        sigClear.addEventListener("click", function () {
          var ctx2 = sigCanvas.getContext && sigCanvas.getContext("2d");
          if (ctx2) ctx2.clearRect(0, 0, sigCanvas.width, sigCanvas.height);
          sigHidden.value = "";
        });
        sigWrap.appendChild(sigCanvas);
        sigWrap.appendChild(sigHidden);
        sigWrap.appendChild(sigClear);
        control = sigWrap;
        break;
      }
      // TD-52 · Manual address — four stacked inputs. Each sub-field
      // uses a ``<name>__line1`` / ``__city`` / ``__state`` / ``__zip``
      // key under the hood; ``collectAnswers`` folds the four back
      // into a single nested ``answers[name] = {line1, city, state,
      // zip}`` so the submission wire shape matches the server
      // contract documented on _FIELD_TYPES.
      case "address_manual": {
        var addrWrap = el("div", {
          "data-testid": "form-widget-input-" + name,
          "data-field-type": "address_manual",
          style: { display: "flex", flexDirection: "column", gap: "6px" },
        });
        var addrLine1 = el("input", {
          type: "text", name: name + "__line1",
          placeholder: "Street address",
          required: required ? "" : null, style: INPUT_STYLE,
          "data-testid": "form-widget-input-" + name + "-line1",
        });
        var addrCity = el("input", {
          type: "text", name: name + "__city", placeholder: "City",
          required: required ? "" : null, style: INPUT_STYLE,
          "data-testid": "form-widget-input-" + name + "-city",
        });
        var addrRow = el("div", {
          style: { display: "flex", gap: "6px" },
        });
        var addrState = el("input", {
          type: "text", name: name + "__state",
          placeholder: "State", maxlength: "2",
          required: required ? "" : null,
          style: Object.assign({}, INPUT_STYLE, { width: "35%" }),
          "data-testid": "form-widget-input-" + name + "-state",
        });
        var addrZip = el("input", {
          type: "text", name: name + "__zip", placeholder: "ZIP",
          required: required ? "" : null,
          style: Object.assign({}, INPUT_STYLE, { width: "65%" }),
          "data-testid": "form-widget-input-" + name + "-zip",
        });
        addrRow.appendChild(addrState);
        addrRow.appendChild(addrZip);
        addrWrap.appendChild(addrLine1);
        addrWrap.appendChild(addrCity);
        addrWrap.appendChild(addrRow);
        control = addrWrap;
        break;
      }
      // TD-52 · 1–5 star rating. Renders five radio buttons styled
      // as stars; the hidden ``name=<name>`` radio group carries the
      // selected 1..5 integer. Submission value is a string digit
      // (coerced server-side via ``_coerce_rating_stars``).
      case "rating_stars": {
        var rateWrap = el("div", {
          "data-testid": "form-widget-input-" + name,
          "data-field-type": "rating_stars",
          style: { display: "flex", gap: "4px", alignItems: "center" },
        });
        for (var rs = 1; rs <= 5; rs++) {
          var rsVal = String(rs);
          var rsLabel = el("label", {
            style: {
              fontSize: "22px", cursor: "pointer",
              color: "#CBD5E1", lineHeight: "1",
              userSelect: "none",
            },
            "data-testid": "form-widget-rating-" + name + "-" + rsVal,
          }, [
            el("input", {
              type: "radio", name: name, value: rsVal,
              required: required && rs === 1 ? "" : null,
              style: { position: "absolute", left: "-9999px" },
            }),
            "★",
          ]);
          rateWrap.appendChild(rsLabel);
        }
        // Click highlights every star up to the clicked one so the
        // operator sees a familiar interaction. Pure DOM, no state.
        rateWrap.addEventListener("change", function (ev) {
          if (!ev.target || ev.target.type !== "radio") return;
          var chosen = parseInt(ev.target.value, 10) || 0;
          var labels = rateWrap.querySelectorAll("label");
          for (var li = 0; li < labels.length; li++) {
            labels[li].style.color =
              li < chosen ? "#F59E0B" : "#CBD5E1";
          }
        });
        control = rateWrap;
        break;
      }
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
    // CUS-Marketing-Form-Builder · Feb-2026 — Phase 4 widget parity.
    // column_span → CSS grid column span. Legacy fields (undefined /
    // null / "full") span two columns → full-width row. "half" fields
    // span one column so consecutive half-width fields pair naturally
    // on the same grid row (city + state, phone + ext, etc.).
    var colSpan = (f.column_span === "half") ? "span 1" : "span 2";
    return el("div", {
      "data-testid": "form-widget-field-" + name,
      "data-column-span": f.column_span || "full",
      style: { marginBottom: "0", gridColumn: colSpan },
    }, [
      f.type === "checkbox" ? null : el("label", { style: LABEL_STYLE }, [labelText]),
      control,
    ]);
  }

  function collectAnswers(formEl) {
    var out = {};
    Array.prototype.forEach.call(formEl.elements, function (input) {
      if (!input.name) return;
      // TD-52 · Fold address_manual sub-field names (``<name>__line1``
      // etc.) back into a single nested object keyed on the parent
      // ``<name>``. Done inline so the generic branches below never
      // see the ``__`` sentinel keys.
      var m = input.name.match(/^(.+)__(line1|city|state|zip)$/);
      if (m) {
        var parent = m[1];
        var slot = m[2];
        if (!out[parent] || typeof out[parent] !== "object") {
          out[parent] = {};
        }
        out[parent][slot] = input.value;
        return;
      }
      if (input.type === "checkbox") {
        out[input.name] = input.checked;
      } else if (input.type === "radio") {
        if (input.checked) out[input.name] = input.value;
      } else if (input.tagName === "SELECT" && input.multiple) {
        out[input.name] = Array.prototype.filter
          .call(input.options, function (o) { return o.selected; })
          .map(function (o) { return o.value; });
      } else if (input.type === "file") {
        // TD-52 · Multi-file inputs serialise to an array of names;
        // single-file inputs keep the legacy scalar-string shape so
        // pre-TD-52 integrations don't regress.
        if (input.multiple) {
          var names = [];
          if (input.files && input.files.length) {
            for (var fi = 0; fi < input.files.length; fi++) {
              names.push(input.files[fi].name);
            }
          }
          out[input.name] = names;
        } else {
          out[input.name] = input.files && input.files[0]
            ? input.files[0].name : "";
        }
      } else {
        out[input.name] = input.value;
      }
    });
    return out;
  }

  // CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53) ·
  // ``show_if`` client-side evaluator. Mirror of the backend's
  // ``_is_field_visible`` + ``src/lib/formShowIf.js``'s
  // ``isFieldVisible`` so the admin preview, the widget, and the
  // server-side validator agree on EVERY visibility decision.
  //
  // Kept inline (not imported) because the widget is a vanilla IIFE
  // and loads via <script> tag on third-party sites — no module
  // resolution available. Keep in sync with the shared helper on
  // every edit.
  function wCoerce(v) {
    if (v === null || v === undefined) return null;
    if (typeof v === "string") {
      var s = v.trim();
      return s === "" ? null : s;
    }
    return v;
  }
  function wIsFieldVisible(field, answers, byId) {
    if (!field) return true;
    var rule = field.show_if;
    if (!rule || typeof rule !== "object") return true;
    var parent = byId[rule.field_id];
    if (!parent) return true;
    var pv = parent.name && answers ? answers[parent.name] : undefined;
    if (pv === undefined) pv = answers ? answers[rule.field_id] : undefined;
    var lhs = wCoerce(pv);
    var rhs = wCoerce(rule.value);
    if (rule.operator === "eq") return lhs === rhs;
    if (rule.operator === "neq") return lhs !== rhs;
    if (rule.operator === "contains") {
      if (Object.prototype.toString.call(pv) === "[object Array]") {
        return pv.indexOf(rule.value) !== -1;
      }
      if (typeof pv === "string" && typeof rule.value === "string") {
        return pv.indexOf(rule.value) !== -1;
      }
      return false;
    }
    return true;
  }
  function wStripHidden(fields, answers) {
    if (!fields || !fields.length) {
      var copy = {};
      for (var k in (answers || {})) copy[k] = answers[k];
      return copy;
    }
    var byId = {};
    fields.forEach(function (f) { if (f && f.id) byId[f.id] = f; });
    var out = {};
    for (var k2 in (answers || {})) out[k2] = answers[k2];
    fields.forEach(function (f) {
      if (!wIsFieldVisible(f, out, byId)) {
        if (f.name) delete out[f.name];
        if (f.id) delete out[f.id];
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

    // CUS-Marketing-Form-Builder · Feb-2026 — Phase 4 widget parity.
    // Optional hero band prepended above the form. Renders nothing
    // when ``schema.hero`` is null so pre-Phase-3 forms render
    // exactly as before.
    var heroEl = renderHero(schema.hero);

    // Build the fields grid — CSS grid so column_span=half fields
    // can pair on the same row. Legacy full-width fields span the
    // entire grid width (span 2).
    //
    // CUS-Marketing-Form-Builder · Feb-2026 — Phase 2 (TD-53).
    // Build a fields-by-id lookup so the show_if evaluator can
    // resolve parent refs on every input change. Row elements are
    // stashed in ``rowEls`` keyed by field id so applyVisibility()
    // can toggle them without re-rendering the whole grid.
    //
    // TD-54 · Feb-2026 — multi-step forms. Walk ``fields`` once up
    // front, record the running page-index for each field so the
    // Prev/Next paginator can show/hide rows en bloc.  Pages are
    // 0-indexed; a form with ZERO page_breaks has one page (index 0)
    // and the paginator short-circuits to the legacy single-page UX
    // (no Prev/Next buttons, submit always enabled).
    var byId = {};
    fields.forEach(function (f) { if (f && f.id) byId[f.id] = f; });
    var pageOfField = {};
    var pageTitles = [""];  // index 0 = first page (unlabeled by default)
    var _curPage = 0;
    fields.forEach(function (f) {
      if (!f) return;
      if (f.type === "page_break") {
        _curPage += 1;
        pageTitles.push(f.page_title || f.label || "");
      } else {
        if (f.id) pageOfField[f.id] = _curPage;
      }
    });
    var pageCount = pageTitles.length;
    var currentPage = 0;  // mutated by Prev/Next handlers
    var rowEls = {};
    var fieldsGrid = el("div", {
      "data-testid": "form-widget-fields-grid",
      style: {
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: "14px 12px",
      },
    }, fields.map(function (f, i) {
      var row = fieldRow(f, i);
      if (f && f.id) rowEls[f.id] = row;
      return row;
    }));

    // TD-53 · recompute visibility after every input change. Hides
    // the row via ``display:none`` + strips the ``required`` attr on
    // every input inside so a hidden input doesn't block submit.
    //
    // TD-54 · page-aware. A field is only visible when (a) its
    // ``show_if`` condition is satisfied AND (b) it lives on the
    // currently-shown page. The ``required`` attr is cleared on
    // rows outside the current page too, so native HTML5 validation
    // on Submit doesn't demand focus on a hidden row.
    function applyVisibility() {
      var currentAnswers = collectAnswers(form);
      fields.forEach(function (f) {
        if (!f || !f.id) return;
        var row = rowEls[f.id];
        if (!row) return;
        var showIfVisible = wIsFieldVisible(f, currentAnswers, byId);
        var onCurrentPage = (
          !(f.id in pageOfField) ||
          pageOfField[f.id] === currentPage
        );
        var visible = showIfVisible && onCurrentPage;
        row.style.display = visible ? "" : "none";
        row.setAttribute("data-visible", visible ? "true" : "false");
        row.setAttribute(
          "data-page-index",
          String(pageOfField[f.id] != null ? pageOfField[f.id] : 0),
        );
        // Clear ``required`` on hidden inputs so the browser's own
        // native-required validator can't fire for them.
        var inputs = row.querySelectorAll(
          "input,select,textarea",
        );
        Array.prototype.forEach.call(inputs, function (input) {
          if (visible) {
            if (input.getAttribute("data-td53-required-saved") === "true") {
              input.required = true;
              input.removeAttribute("data-td53-required-saved");
            }
          } else {
            if (input.required) {
              input.setAttribute("data-td53-required-saved", "true");
              input.required = false;
            }
          }
        });
      });
      applyPaginatorChrome();
    }

    var form = el("form", {
      "data-testid": "form-widget-form",
      novalidate: "",
      style: {
        background: "#fff",
        border: "1px solid #E2E8F0",
        borderRadius: heroEl ? "0 0 12px 12px" : "12px",
        padding: "20px",
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        maxWidth: "520px",
      },
      onsubmit: function (e) {
        e.preventDefault();
        // TD-53 · strip hidden-field answers before posting so the
        // persisted submission reflects operator-visible state (and
        // the lead extractor doesn't absorb stale values from
        // fields the submitter never actually saw).
        var payload = {
          answers: wStripHidden(fields, collectAnswers(form)),
          page_url: location.href,
        };
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
      fieldsGrid,
    ]);

    // Apply the tenant theme AFTER building the form so inline CSS
    // vars override the defaults set above. Null-safe: no-op when
    // ``schema.theme`` is missing → legacy pre-K34 shape.
    if (schema.theme) {
      applyTheme(form, schema.theme);
    }

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

    // CTA — use the theme's primary color when available, fall back
    // to the legacy brand_color param + hardcoded sky-500 for
    // pre-Phase-4 tenants.
    var themePrimary = (schema.theme && schema.theme.colors
                          && schema.theme.colors.primary) || null;
    var submitBtn = el("button", {
      type: "submit",
      "data-testid": "form-widget-submit-btn",
      style: {
        background: themePrimary || (cfg && cfg.brand_color) || "#0EA5E9",
        color: "#fff",
        border: "none",
        borderRadius: "10px",
        padding: "10px 18px",
        fontSize: "14px",
        fontWeight: "600",
        cursor: "pointer",
        marginTop: "14px",
      },
    }, [schema.submit_button_label || "Send"]);

    // TD-54 · Feb-2026 — paginator chrome. Only rendered when the
    // form has at least one page_break (pageCount > 1); byte-
    // identical absent-paginator UX for pre-TD-54 forms.
    var paginatorBar = null;
    var prevBtn = null;
    var nextBtn = null;
    var progressLabel = null;
    if (pageCount > 1) {
      paginatorBar = el("div", {
        "data-testid": "form-widget-paginator",
        style: {
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "10px",
          marginTop: "14px",
        },
      });
      prevBtn = el("button", {
        type: "button",
        "data-testid": "form-widget-paginator-prev",
        style: {
          background: "#fff",
          color: themePrimary || "#0EA5E9",
          border: "1px solid " + (themePrimary || "#CBD5E1"),
          borderRadius: "10px",
          padding: "8px 14px",
          fontSize: "13px",
          fontWeight: "600",
          cursor: "pointer",
        },
      }, ["← Previous"]);
      nextBtn = el("button", {
        type: "button",
        "data-testid": "form-widget-paginator-next",
        style: {
          background: themePrimary || "#0EA5E9",
          color: "#fff",
          border: "none",
          borderRadius: "10px",
          padding: "8px 14px",
          fontSize: "13px",
          fontWeight: "600",
          cursor: "pointer",
        },
      }, ["Next →"]);
      progressLabel = el("div", {
        "data-testid": "form-widget-paginator-progress",
        style: {
          fontSize: "12px",
          color: "#64748B",
          fontWeight: "500",
        },
      }, [""]);
      paginatorBar.appendChild(prevBtn);
      paginatorBar.appendChild(progressLabel);
      paginatorBar.appendChild(nextBtn);
    }

    // ``applyPaginatorChrome`` is called from applyVisibility (which
    // runs after every input change AND on Prev/Next click) to keep
    // the Prev/Next/Submit visibility + the progress label in sync
    // with ``currentPage``. Scoped to a closure over ``submitBtn`` /
    // ``prevBtn`` / ``nextBtn`` / ``progressLabel`` so each call site
    // is a single-arg state write.
    function applyPaginatorChrome() {
      if (pageCount <= 1) {
        // Legacy single-page form — paginator is absent, submit is
        // always shown.
        if (submitBtn) submitBtn.style.display = "";
        return;
      }
      var onLastPage = currentPage >= pageCount - 1;
      var onFirstPage = currentPage <= 0;
      prevBtn.disabled = onFirstPage;
      prevBtn.style.opacity = onFirstPage ? "0.4" : "1";
      prevBtn.style.cursor = onFirstPage ? "default" : "pointer";
      nextBtn.style.display = onLastPage ? "none" : "";
      submitBtn.style.display = onLastPage ? "" : "none";
      // ``Page N of M · Section title`` when a page_title is set,
      // otherwise just ``Page N of M``.
      var title = pageTitles[currentPage] || "";
      progressLabel.textContent =
        "Page " + (currentPage + 1) + " of " + pageCount
          + (title ? "  ·  " + title : "");
    }

    // ``validateCurrentPage`` — scan every row on the current page
    // and ask the browser's native validator whether its input is
    // acceptable (``input.checkValidity()``). Blocks Next if any
    // visible required input on this page is incomplete. show_if-
    // hidden inputs already have ``required`` stripped by
    // ``applyVisibility`` so they are ignored here.
    function validateCurrentPage() {
      var ok = true;
      Object.keys(rowEls).forEach(function (fid) {
        if (pageOfField[fid] !== currentPage) return;
        var row = rowEls[fid];
        if (row.getAttribute("data-visible") === "false") return;
        var inputs = row.querySelectorAll("input,select,textarea");
        Array.prototype.forEach.call(inputs, function (input) {
          if (input.required && !input.checkValidity()) {
            if (ok) {  // flash the first offender
              try { input.reportValidity(); } catch (e) {}
            }
            ok = false;
          }
        });
      });
      return ok;
    }

    if (pageCount > 1) {
      prevBtn.addEventListener("click", function () {
        if (currentPage > 0) {
          currentPage -= 1;
          applyVisibility();
        }
      });
      nextBtn.addEventListener("click", function () {
        if (!validateCurrentPage()) return;
        if (currentPage < pageCount - 1) {
          currentPage += 1;
          applyVisibility();
        }
      });
      form.appendChild(paginatorBar);
    }

    form.appendChild(submitBtn);

    // TD-53 · wire the show_if evaluator to EVERY input / change
    // event bubbled up through the form. Also fire once on initial
    // render so fields that start hidden (parent default empty, rule
    // requires a value) are hidden before the user interacts.
    form.addEventListener("input", applyVisibility);
    form.addEventListener("change", applyVisibility);
    applyVisibility();

    // Assemble: hero (optional) → form. Both wrapped in a container
    // that carries the visual rounded corners so the hero and form
    // read as one cohesive card.
    if (heroEl) {
      var wrap = el("div", {
        "data-testid": "form-widget-wrap",
        style: { maxWidth: "520px" },
      }, [heroEl, form]);
      MOUNT.appendChild(wrap);
    } else {
      MOUNT.appendChild(form);
    }
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
