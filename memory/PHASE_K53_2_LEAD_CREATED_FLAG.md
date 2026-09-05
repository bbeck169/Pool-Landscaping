# Phase K53.2 · Feb-2026 — Path A `lead_created` response-shape parity

**Status**: Shipped to preview. 9/9 pytest on the affected suite pass.
Tiny cosmetic follow-up to K53.1.

## Problem

Tester noted after K53.1 shipped that Path A's happy-path response
returns `{"ok": true, "redirect_url": null}` — missing the `lead_created`
flag that Path B (`routers/marketing_forms.py`) already surfaces.
Callers had no way to distinguish "created a real lead" from
"submission stored but no lead written" without inspecting the
`redirect_url` heuristic — brittle.

## Fix

`backend/routers/marketing.py::submit_public_form` — happy-path
response now explicitly includes `"lead_created": <bool>` matching
the destination selector:

```py
return {"ok": True, "redirect_url": form.get("redirect_url"),
        "lead_created": dest == "lead"}
```

The guard-skip path (K53.1) already returned
`{"lead_created": False, "reason": "no_contact_captured"}` so no
change there.

The sibling `submit_form` endpoint already returned
`{"ok": True, "lead_created": True}` for its happy path — no edit
needed there.

## Tests

`backend/tests/test_k53_1_lead_pipeline_fix.py` extended with a
new assertion inside
`test_k531_your_email_cell_phone_customer_name_aliases` that pins
`body.get("lead_created") is True` on the Path A happy path.

Guard-skip case already asserts
`body.get("lead_created") is False` — the two cases together lock
in the new contract.

## Files changed

- `backend/routers/marketing.py` — one line: response body includes
  `lead_created`.
- `backend/tests/test_k53_1_lead_pipeline_fix.py` — one added
  assertion.

## Rollback

Single-line revert. Downstream callers that already accept a
missing key remain compatible either way.
