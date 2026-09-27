"""AI Hub · Feb-2026 — 18-employee workforce registry (spec v5).

Immutable in-code source of truth for the 18 shipping personas.
See ``/app/memory/SPEC_AI_HUB_18_EMPLOYEE_WORKFORCE.md`` for the
locked roster + avatar map (v5, 2026-02).

Design fork (from AIHUB-A brief):
- Brief asked for ``human_name`` + ``department`` field names.
- Spec v5 § "Persona doc shape" uses ``name`` (human) +
  ``org_department``.
- Existing ``ai_employees`` collection already uses ``name`` for
  legacy rows' human display name — ``test_marco_seed.py`` locks
  that shape.  So we ship BOTH: ``human_name`` (new field per
  brief) alongside ``org_department`` (spec).  ``name`` stays as
  the legacy display column.  FE + tests read ``human_name``.

Registry layered on top of the legacy ``DEFAULT_EMPLOYEES`` in
``routers/ai_employees.py`` (10 pre-existing personas) — the
seed function unions both.  Existing customizations on any row
are ALWAYS preserved on backfill; only unset new fields get
stamped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


# ═══════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════

# Default monthly action budget for every AI Employee — per AIHUB-A
# brief.  Enforcement is out of scope for this phase (AIHUB-B).
DEFAULT_ACTION_LIMIT_MONTHLY: int = 60000

# Static persona-avatar CDN root (v5 renders — 3D Pixar/Disney
# style, soft blue-teal backgrounds, no watermark).  See spec §
# "Roster — 18 personas total, v5 avatars".
_AVATAR_ROOT: str = (
    "https://static.prod-images.emergentagent.com/jobs/"
    "8d765b01-2ae3-4eff-bc2b-1b1462bdb6ea/images/"
)

# Department vocabulary — locked by spec ruling §3.
DEPT_EXECUTIVE: str = "executive"
DEPT_MARKETING: str = "marketing"
DEPT_OPERATIONS: str = "operations"
ALLOWED_DEPARTMENTS: Tuple[str, ...] = (
    DEPT_EXECUTIVE, DEPT_MARKETING, DEPT_OPERATIONS,
)


# ═══════════════════════════════════════════════════════════════════
# Spec dataclass
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EmployeeSpec:
    """One row in the 18-employee registry.  Frozen — mutation is a
    schema change, not a runtime concern."""

    key: str                          # immutable internal id
    human_name: str                   # display "Sarah", "Amy", …
    codename: str                     # all-caps identifier "NOVA"
    role_title: str                   # "CMO", "SEO Director", …
    org_department: str               # exec | marketing | operations
    hierarchy_order: int              # 1..18
    manager_key: Optional[str]        # None only for executive tier
    orchestrator: bool                # True on marco_executive + nova
    avatar_slug: str                  # url basename (== key)
    avatar_url: str                   # v5 CDN url — full
    # Per-employee defaults on first tenant seed.  Both mutate via
    # ``PATCH /ai-employees/{eid}/authorize`` and the future
    # AIHUB-B quota surface respectively.
    default_authorized_for_public_use: bool = False
    default_action_limit_monthly: int = DEFAULT_ACTION_LIMIT_MONTHLY
    # Initial system-prompt draft.  Free-form; individual employees
    # typically get a richer prompt later via admin edits.  Empty
    # string is fine — the LLM path handles a bare persona.
    system_prompt: str = ""
    # Capability tags — placeholder for AIHUB-B / AIHUB-C wiring.
    # Empty tuple in AIHUB-A; existence of the field lets future
    # phases avoid another schema migration.
    capabilities: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        # Cheap sanity — catches typos at import time rather than at
        # first tenant boot.
        if self.org_department not in ALLOWED_DEPARTMENTS:
            raise ValueError(
                f"EmployeeSpec {self.key!r}: bad org_department "
                f"{self.org_department!r} — must be one of "
                f"{ALLOWED_DEPARTMENTS}"
            )
        if not (1 <= self.hierarchy_order <= 100):
            raise ValueError(
                f"EmployeeSpec {self.key!r}: hierarchy_order "
                f"out of range 1..100"
            )
        if self.avatar_slug != self.key:
            raise ValueError(
                f"EmployeeSpec {self.key!r}: avatar_slug must equal key"
            )
        if not self.avatar_url.startswith("http"):
            raise ValueError(
                f"EmployeeSpec {self.key!r}: avatar_url must be a URL"
            )


def _av(sha256_ish: str) -> str:
    """Assemble the v5 avatar URL for a given CDN filename."""
    return f"{_AVATAR_ROOT}{sha256_ish}"


# ═══════════════════════════════════════════════════════════════════
# Registry — 18 employees, locked v5 order (matches spec
# ``hierarchy_order`` table).  Tuple, not list — immutable.
# ═══════════════════════════════════════════════════════════════════

EMPLOYEES: Tuple[EmployeeSpec, ...] = (
    # ── Executive (2) ──────────────────────────────────────────
    EmployeeSpec(
        key="marco_executive",
        human_name="MARCO",                # spec exception §4 — identity as-is
        codename="MARCO",
        role_title="Executive Assistant / Chief of Staff",
        org_department=DEPT_EXECUTIVE,
        hierarchy_order=1,
        manager_key=None,
        orchestrator=True,
        avatar_slug="marco_executive",
        avatar_url=_av(
            "3e4c26582e9e401f967d0198400f4b431def195270a06b6db3a81ad9d9a897fa.jpeg"
        ),
    ),
    EmployeeSpec(
        key="guard", human_name="Gary", codename="GUARD",
        role_title="Security & Governance Lead",
        org_department=DEPT_EXECUTIVE, hierarchy_order=2,
        manager_key=None, orchestrator=False,
        avatar_slug="guard",
        avatar_url=_av(
            "e9e1d807b51839cb77fb5661c6e78b59e632bce23d69cffe9a7db72063546abc.jpeg"
        ),
    ),

    # ── Marketing (13 — LOCAL back in per v4/v5) ──────────────
    EmployeeSpec(
        key="nova", human_name="Sarah", codename="NOVA",
        role_title="CMO",
        org_department=DEPT_MARKETING, hierarchy_order=3,
        manager_key="marco_executive", orchestrator=True,
        avatar_slug="nova",
        avatar_url=_av(
            "9f150de291b029112804aa2062191694f2d0ba10f99292db9b0c1cfa62cf3346.jpeg"
        ),
    ),
    EmployeeSpec(
        key="rank", human_name="Amy", codename="RANK",
        role_title="SEO Director",
        org_department=DEPT_MARKETING, hierarchy_order=4,
        manager_key="nova", orchestrator=False,
        avatar_slug="rank",
        avatar_url=_av(
            "bcb4e08aaf69b870979299b85885cd262f402a59c4882dcdf159d5809ebfa41c.jpeg"
        ),
    ),
    EmployeeSpec(
        key="geo", human_name="Grace", codename="GEO",
        role_title="AI Search Lead",
        org_department=DEPT_MARKETING, hierarchy_order=5,
        manager_key="nova", orchestrator=False,
        avatar_slug="geo",
        avatar_url=_av(
            "0dee24d972e4abcaed13a8f78ade8404763cea6bbd3ac3a262d044aeff3be836.jpeg"
        ),
    ),
    EmployeeSpec(
        key="local", human_name="Laura", codename="LOCAL",
        role_title="Local SEO Lead",
        org_department=DEPT_MARKETING, hierarchy_order=6,
        manager_key="nova", orchestrator=False,
        avatar_slug="local",
        avatar_url=_av(
            "e2a3dafab895e0451860a140e1b2d9910cf2da49f8c6de93ce0fbc69dc9b94bf.jpeg"
        ),
    ),
    EmployeeSpec(
        key="scribe", human_name="Samuel", codename="SCRIBE",
        role_title="Content Director",
        org_department=DEPT_MARKETING, hierarchy_order=7,
        manager_key="nova", orchestrator=False,
        avatar_slug="scribe",
        avatar_url=_av(
            "5cb863446073fc6d45c47ffe65e57816cb8b73b33a4e32f00378f53dd7f610ef.jpeg"
        ),
    ),
    EmployeeSpec(
        key="social", human_name="Sophia", codename="SOCIAL",
        role_title="Social Media Manager",
        org_department=DEPT_MARKETING, hierarchy_order=8,
        manager_key="nova", orchestrator=False,
        avatar_slug="social",
        avatar_url=_av(
            "75b92361808787c6a0c0be823c724a9dc439a076ccfb0ca0b4d7322475aa49bd.jpeg"
        ),
    ),
    EmployeeSpec(
        key="adam", human_name="Aaron", codename="ADAM",
        role_title="Ads Director",
        org_department=DEPT_MARKETING, hierarchy_order=9,
        manager_key="nova", orchestrator=False,
        avatar_slug="adam",
        avatar_url=_av(
            "e233d00f6c409110745b5ed3255f0fb4cfeea0c44190a67bec119e71af525437.jpeg"
        ),
    ),
    EmployeeSpec(
        key="pulse", human_name="Paul", codename="PULSE",
        role_title="Email / SMS Marketing Lead",
        org_department=DEPT_MARKETING, hierarchy_order=10,
        manager_key="nova", orchestrator=False,
        avatar_slug="pulse",
        avatar_url=_av(
            "487b1749ce7bbebcba0ad8d08ebcec90dd45c27ae03955add5e61236a76add54.jpeg"
        ),
    ),
    EmployeeSpec(
        key="repute", human_name="Rachel", codename="REPUTE",
        role_title="Reputation Manager",
        org_department=DEPT_MARKETING, hierarchy_order=11,
        manager_key="nova", orchestrator=False,
        avatar_slug="repute",
        avatar_url=_av(
            "91f6105d6f7aa13e68173d9eea63d4410f25e894549d053a0d4d23c002e294cf.jpeg"
        ),
    ),
    EmployeeSpec(
        key="creative", human_name="Chloe", codename="CREATIVE",
        role_title="Design Director",
        org_department=DEPT_MARKETING, hierarchy_order=12,
        manager_key="nova", orchestrator=False,
        avatar_slug="creative",
        avatar_url=_av(
            "13c38a737992d2d759b447b032a104218f3afc86587a772e361591b24924453c.jpeg"
        ),
    ),
    EmployeeSpec(
        key="intel", human_name="Isaac", codename="INTEL",
        role_title="Competitor Intel Analyst",
        org_department=DEPT_MARKETING, hierarchy_order=13,
        manager_key="nova", orchestrator=False,
        avatar_slug="intel",
        avatar_url=_av(
            "55a71619959d7de8d1719cc6e0ae5aa9beee030ac6c73e5f09765892da833f21.jpeg"
        ),
    ),
    EmployeeSpec(
        key="convert", human_name="Carla", codename="CONVERT",
        role_title="CRO Specialist",
        org_department=DEPT_MARKETING, hierarchy_order=14,
        manager_key="nova", orchestrator=False,
        avatar_slug="convert",
        avatar_url=_av(
            "c0c2eb109b7f5a93bba3741f5a84a97a2d1f4f4246494dfe7dc6158aaaf36a22.jpeg"
        ),
    ),
    EmployeeSpec(
        key="attrib", human_name="Alan", codename="ATTRIB",
        role_title="Attribution Analyst",
        org_department=DEPT_MARKETING, hierarchy_order=15,
        manager_key="nova", orchestrator=False,
        avatar_slug="attrib",
        avatar_url=_av(
            "8756cbb7c252cc7f1b5f3d3312878a7f48aede74d295fa423e6685a2416d6eff.jpeg"
        ),
    ),

    # ── Operations (3) ────────────────────────────────────────
    EmployeeSpec(
        key="brian", human_name="Ben", codename="BRIAN",
        role_title="Scheduling Coordinator",
        org_department=DEPT_OPERATIONS, hierarchy_order=16,
        manager_key="marco_executive", orchestrator=False,
        avatar_slug="brian",
        avatar_url=_av(
            "f4aacb4b56e009612ea124ec34977a653da50f256b567e4f759982ec67d0b566.jpeg"
        ),
    ),
    EmployeeSpec(
        key="dispatch", human_name="Diana", codename="DISPATCH",
        role_title="Field Operations Lead",
        org_department=DEPT_OPERATIONS, hierarchy_order=17,
        manager_key="marco_executive", orchestrator=False,
        avatar_slug="dispatch",
        avatar_url=_av(
            "bba65bf796ba100f1b1fac67bdf16eb7bc2e361839ef863f96a22775cc93043a.jpeg"
        ),
    ),
    EmployeeSpec(
        key="retain", human_name="Ryan", codename="RETAIN",
        role_title="Retention Specialist",
        org_department=DEPT_OPERATIONS, hierarchy_order=18,
        manager_key="marco_executive", orchestrator=False,
        avatar_slug="retain",
        avatar_url=_av(
            "87b6d62c0c7586cd820b32e9372a4526a3a6f6b3881a118fc7045553c056db70.jpeg"
        ),
    ),
)


# ═══════════════════════════════════════════════════════════════════
# Public helpers
# ═══════════════════════════════════════════════════════════════════

def registry_size() -> int:
    """Length invariant — locked to 18 by ``test_ai_hub_registry``."""
    return len(EMPLOYEES)


def get_spec(key: str) -> Optional[EmployeeSpec]:
    """O(n) — n=18, so a linear scan is cheaper than maintaining a
    dict at module scope for this scale."""
    for e in EMPLOYEES:
        if e.key == key:
            return e
    return None


def to_seed_doc(spec: EmployeeSpec) -> dict:
    """Convert an ``EmployeeSpec`` into the dict shape that
    ``routers.ai_employees.seed_ai_employees_for_tenant`` inserts
    into ``db.ai_employees``.  This is the SEED-only projection —
    fields set by that function itself (``id``, ``tenant_id``,
    ``created_at``, ``updated_at``) are excluded here.
    """
    return {
        "key": spec.key,
        # ``name`` stays as the legacy display column (test_marco_seed
        # + AIDock read from it).  For spec-18 rows we also seed
        # ``human_name`` for the new AI-Hub grouping surface.
        "name": spec.human_name,
        "human_name": spec.human_name,
        "codename": spec.codename,
        "role": spec.role_title,      # legacy alias — keep both
        "role_title": spec.role_title,
        "org_department": spec.org_department,
        "hierarchy_order": spec.hierarchy_order,
        "manager_key": spec.manager_key,
        "orchestrator": spec.orchestrator,
        "avatar_url": spec.avatar_url,
        "avatar_slug": spec.avatar_slug,
        "system_prompt": spec.system_prompt,
        "audience": "admin",          # spec 18 is admin-only
        "authorized_for_public_use":
            spec.default_authorized_for_public_use,
        "action_limit_monthly":
            spec.default_action_limit_monthly,
        "is_legacy": False,
    }
