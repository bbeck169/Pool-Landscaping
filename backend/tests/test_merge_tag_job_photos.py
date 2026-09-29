"""Phase DOOR-HANGER · Feb 2026 — ``{{JOB_PHOTOS}}`` resolver contract.

Pure unit tests for :func:`services.marketing.merge_tags._job_photos_gallery`
and the ``JOB_PHOTOS`` catalog entry.  No MongoDB / no FastAPI —
these tests operate on the resolver + registry directly so a
regression on the merge-tag registration is caught before a full
send-path test wires up.

Contract locked here
--------------------
* Empty / missing photo list  → empty string (no wrapper, no heading).
* 1 photo                     → 1 ``<a><img/></a>`` pair, href = url.
* N photos                    → N pairs, order preserved.
* Every ``<a>`` opens in a new tab (``target="_blank"``) with
  ``rel="noopener"`` for tabnabbing protection.
* Reads ``ctx['_dh_job_photos']`` first (send-path pre-populated
  ``resolve_photo_items(job)`` output — carries ``url_absolute``).
  The key is intentionally underscore-prefixed so it never
  collides with ``render_template``'s flat-key cascade for
  ``{{JOB_PHOTOS}}``.
* Falls back to ``ctx['job']['photos']`` (raw job-doc shape —
  carries ``url`` / ``data_url`` / ``data`` / ``uri``).
* Multi-tenant isolation: the resolver only renders what the caller
  put in the ctx.  Never reaches back into any DB / global state,
  so a caller that scopes ctx to Job A's photos will never leak
  Job B's photos.
* ``{{JOB_PHOTOS}}`` is registered in ``MERGE_TAGS`` and reachable
  via ``render_template``.
"""
from __future__ import annotations


def _resolver():
    from services.marketing.merge_tags import _job_photos_gallery
    return _job_photos_gallery


def test_empty_photos_returns_empty_string():
    r = _resolver()
    assert r({}) == ""
    assert r({"_dh_job_photos": []}) == ""
    assert r({"job": {"photos": []}}) == ""
    assert r({"_dh_job_photos": None}) == ""
    # Non-list _dh_job_photos still yields empty string (defensive).
    assert r({"_dh_job_photos": "not-a-list"}) == ""


def test_single_photo_renders_one_anchor_image_pair():
    r = _resolver()
    html = r({"_dh_job_photos": [
        {"id": "p1", "url_absolute": "https://cdn.example.com/p1.jpg"},
    ]})
    # Wrapper card + heading + one anchor.
    assert "Service Photos" in html
    assert html.count("<a ") == 1
    assert html.count("<img ") == 1
    assert 'href="https://cdn.example.com/p1.jpg"' in html
    assert 'src="https://cdn.example.com/p1.jpg"' in html


def test_multiple_photos_render_in_order():
    r = _resolver()
    photos = [
        {"id": f"p{i}", "url_absolute": f"https://cdn.example.com/p{i}.jpg"}
        for i in range(1, 6)
    ]
    html = r({"_dh_job_photos": photos})
    assert html.count("<a ") == 5
    assert html.count("<img ") == 5
    # Order preserved — p1 appears before p2 which appears before p3, etc.
    positions = [
        html.index(f"p{i}.jpg") for i in range(1, 6)
    ]
    assert positions == sorted(positions), (
        f"photo order not preserved: {positions}"
    )


def test_every_anchor_has_target_blank_and_rel_noopener():
    r = _resolver()
    html = r({"_dh_job_photos": [
        {"id": "p1", "url_absolute": "https://x/1.jpg"},
        {"id": "p2", "url_absolute": "https://x/2.jpg"},
    ]})
    # Both anchors carry the tabnabbing-safe attributes.
    assert html.count('target="_blank"') == 2
    assert html.count('rel="noopener"') == 2


def test_falls_back_to_job_photos_list_when_dh_key_absent():
    """Generic template that only passes ``ctx['job']`` still renders."""
    r = _resolver()
    html = r({"job": {
        "id": "job-a",
        "photos": [
            {"id": "raw1", "url": "https://cdn.example.com/raw1.jpg"},
            {"id": "raw2", "data_url": "data:image/png;base64,AAAA"},
        ],
    }})
    assert html.count("<a ") == 2
    assert 'href="https://cdn.example.com/raw1.jpg"' in html
    # data_url path renders as-is inside the href.
    assert 'href="data:image/png;base64,AAAA"' in html


def test_base64_data_field_upgraded_to_data_uri():
    r = _resolver()
    html = r({"_dh_job_photos": [
        {"id": "b64", "data": "iVBORw0KGgo="},   # bare base64 payload
    ]})
    # Bare base64 without a ``data:`` prefix is upgraded to a PNG URI.
    assert 'href="data:image/png;base64,iVBORw0KGgo="' in html


def test_photo_with_no_usable_url_is_skipped():
    r = _resolver()
    html = r({"_dh_job_photos": [
        {"id": "good", "url_absolute": "https://x/g.jpg"},
        {"id": "no-url"},                # nothing to render — skip
        {"id": "empty-str", "url_absolute": ""},
    ]})
    # Only the one good photo renders — the wrapper still emits.
    assert html.count("<a ") == 1
    assert 'href="https://x/g.jpg"' in html


def test_send_path_override_beats_raw_job_photos():
    """When BOTH keys are populated, ``_dh_job_photos`` wins (send-path
    override with absolute URLs > raw job-doc shape)."""
    r = _resolver()
    html = r({
        "_dh_job_photos": [
            {"id": "override", "url_absolute": "https://cdn.x/over.jpg"},
        ],
        "job": {"photos": [
            {"id": "raw", "url": "https://cdn.x/raw.jpg"},
        ]},
    })
    assert "over.jpg" in html
    assert "raw.jpg" not in html


def test_multi_tenant_isolation_only_ctx_photos_render():
    """Resolver is stateless — it renders ONLY what the caller
    passes in ctx.  This test demonstrates that a ctx scoped to
    Tenant A's job cannot pull in Tenant B's photos.
    """
    r = _resolver()
    tenant_a_photos = [
        {"id": "t-a-1", "url_absolute": "https://cdn.tenant-a/1.jpg"},
        {"id": "t-a-2", "url_absolute": "https://cdn.tenant-a/2.jpg"},
    ]
    tenant_b_photos = [
        {"id": "t-b-1", "url_absolute": "https://cdn.tenant-b/1.jpg"},
    ]
    html_a = r({"_dh_job_photos": tenant_a_photos})
    html_b = r({"_dh_job_photos": tenant_b_photos})
    # Tenant A render only mentions Tenant A URLs.
    assert "tenant-a/1.jpg" in html_a and "tenant-a/2.jpg" in html_a
    assert "tenant-b" not in html_a
    # Tenant B render only mentions Tenant B URLs.
    assert "tenant-b/1.jpg" in html_b
    assert "tenant-a" not in html_b


def test_alt_attribute_escapes_double_quotes():
    """Photo labels with a double-quote must not break the alt
    attribute — the resolver replaces ``"`` with ``&quot;``."""
    r = _resolver()
    html = r({"_dh_job_photos": [
        {"id": "q1", "url_absolute": "https://x/q.jpg",
         "label": 'Before "cleaning"'},
    ]})
    assert 'alt="Before &quot;cleaning&quot;"' in html


def test_registry_exposes_job_photos_tag():
    """``JOB_PHOTOS`` is in the ``MERGE_TAGS`` catalog under a
    stable token so the UI palette + render_template both find it."""
    from services.marketing.merge_tags import MERGE_TAGS
    tokens = {t["token"] for t in MERGE_TAGS}
    assert "JOB_PHOTOS" in tokens


def test_render_template_substitutes_job_photos_from_dh_key():
    """End-to-end: ``{{JOB_PHOTOS}}`` in a template body is
    substituted by the resolver output.  Uses the underscore-
    prefixed send-path key so the flat-key cascade doesn't
    intercept the raw list."""
    from services.marketing.merge_tags import render_template
    body = "<p>Header</p>{{JOB_PHOTOS}}<p>Footer</p>"
    rendered, unresolved = render_template(body, {
        "_dh_job_photos": [
            {"id": "j1", "url_absolute": "https://cdn.example.com/j1.jpg"},
        ],
    })
    assert "JOB_PHOTOS" not in unresolved
    assert "j1.jpg" in rendered
    assert "Service Photos" in rendered   # gallery card heading
    assert "<p>Header</p>" in rendered
    assert "<p>Footer</p>" in rendered
    # Literal token must have been consumed.
    assert "{{JOB_PHOTOS}}" not in rendered


def test_render_template_substitutes_job_photos_from_job_dict():
    """Same as above but through the ``ctx['job']['photos']``
    fallback path.  Generic template previews use this shape."""
    from services.marketing.merge_tags import render_template
    body = "{{JOB_PHOTOS}}"
    rendered, _ = render_template(body, {"job": {"photos": [
        {"id": "j2", "url": "https://cdn.example.com/j2.jpg"},
    ]}})
    assert "j2.jpg" in rendered
    assert "Service Photos" in rendered


def test_render_template_job_photos_empty_when_no_photos():
    """Empty photos collapse ``{{JOB_PHOTOS}}`` to nothing — the
    "no orphan section" contract."""
    from services.marketing.merge_tags import render_template
    body = "<p>Header</p>{{JOB_PHOTOS}}<p>Footer</p>"
    rendered, _ = render_template(body, {"_dh_job_photos": []})
    assert "{{JOB_PHOTOS}}" not in rendered
    assert "Service Photos" not in rendered
    assert rendered == "<p>Header</p><p>Footer</p>"


# ═════════════════════════════════════════════════════════════════════
# WATER_TEST_RESULTS alias — same contract as DOOR_HANGER_WATER_TEST_HTML.
# ═════════════════════════════════════════════════════════════════════
def test_water_test_results_alias_registered():
    from services.marketing.merge_tags import MERGE_TAGS
    tokens = {t["token"] for t in MERGE_TAGS}
    assert "WATER_TEST_RESULTS" in tokens
    assert "DOOR_HANGER_WATER_TEST_HTML" in tokens


def test_water_test_results_alias_resolves_identically():
    """The alias reads the same pre-rendered HTML the canonical tag
    reads.  A tenant can swap ``{{DOOR_HANGER_WATER_TEST_HTML}}``
    for ``{{WATER_TEST_RESULTS}}`` in the door-hanger template body
    and get byte-identical output."""
    from services.marketing.merge_tags import render_template
    ctx = {"dh_water_test_html": "<div>WT-PRE-RENDERED</div>"}
    canonical, _ = render_template("{{DOOR_HANGER_WATER_TEST_HTML}}", ctx)
    alias, _ = render_template("{{WATER_TEST_RESULTS}}", ctx)
    assert canonical == alias
    assert "WT-PRE-RENDERED" in alias


def test_water_test_results_alias_empty_when_ctx_missing():
    from services.marketing.merge_tags import render_template
    rendered, _ = render_template("{{WATER_TEST_RESULTS}}", {})
    assert rendered == ""
