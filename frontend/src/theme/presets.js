/**
 * Phase I1.5.c · Feb-2026 — Client-side mirror of the backend
 * preset registry (``backend/services/theme/presets.py``).
 *
 * Purpose: the ``useTenantTheme`` hook uses the ``default``
 * entry from this file as its offline fallback when the
 * GET /api/tenants/me/theme call errors before the app can
 * paint. Every other consumer should reach the live registry
 * via GET /api/theme-presets or the tenant-persisted theme.
 *
 * Structural parity with the backend registry is contract-
 * locked in ``test/theme-preset-parity.test.js`` — a diff
 * against the imported registry fails the suite loudly.
 * When you edit this file, run
 * ``yarn vitest run src/test/theme-preset-parity.test.js``.
 */
export const CLIENT_PRESETS = {
  "default": {
    "preset": "default",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#1b1f5c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#1b1f5c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#166534"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#166534"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#1b1f5c"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#1b1f5c"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#166534"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#eaf7f0"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#14532d"
      }
    }
  },
  "pool_landscape": {
    "preset": "pool_landscape",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#1b1f5c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#1b1f5c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#166534"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#166534"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#1b1f5c"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#1b1f5c"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#166534"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#eaf7f0"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#14532d"
      }
    }
  },
  "pool": {
    "preset": "pool",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#155e75"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#155e75"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#0e7490"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#0e7490"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#155e75"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#155e75"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#0e7490"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#cffafe"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#164e63"
      }
    }
  },
  "landscape": {
    "preset": "landscape",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#14532d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#14532d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#166534"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#166534"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#14532d"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#166534"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#365314"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#dcfce7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#14532d"
      }
    }
  },
  "hvac": {
    "preset": "hvac",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#1e40af"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#1e40af"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#1e40af"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#1e40af"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#ffedd5"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#7c2d12"
      }
    }
  },
  "plumbing": {
    "preset": "plumbing",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#1e3a8a"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#1e3a8a"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#1d4ed8"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#1d4ed8"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#1e3a8a"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#1e40af"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#1d4ed8"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#dbeafe"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#1e3a8a"
      }
    }
  },
  "electrical": {
    "preset": "electrical",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#713f12"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fef3c7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#713f12"
      }
    }
  },
  "roofing": {
    "preset": "roofing",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#334155"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#334155"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#334155"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#991b1b"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fee2e2"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#991b1b"
      }
    }
  },
  "solar": {
    "preset": "solar",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#075985"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#075985"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#075985"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#075985"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fef3c7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#713f12"
      }
    }
  },
  "cleaning": {
    "preset": "cleaning",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#0369a1"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#0369a1"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#0369a1"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#0369a1"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#075985"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#075985"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#0369a1"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#e0f2fe"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#0c4a6e"
      }
    }
  },
  "pest_control": {
    "preset": "pest_control",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#365314"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#365314"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#4d7c0f"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#4d7c0f"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#365314"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#365314"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#4d7c0f"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#ecfccb"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#365314"
      }
    }
  },
  "moving": {
    "preset": "moving",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#ffedd5"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#7c2d12"
      }
    }
  },
  "painting": {
    "preset": "painting",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#6b21a8"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#6b21a8"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#7e22ce"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#7e22ce"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#6b21a8"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#6b21a8"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#7e22ce"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#f3e8ff"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#581c87"
      }
    }
  },
  "flooring": {
    "preset": "flooring",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#44403c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#44403c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#44403c"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fef3c7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#713f12"
      }
    }
  },
  "drywall": {
    "preset": "drywall",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#3f3f46"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#3f3f46"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#52525b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#52525b"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#3f3f46"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#3f3f46"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#52525b"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#f4f4f5"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#27272a"
      }
    }
  },
  "handyman": {
    "preset": "handyman",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#991b1b"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fee2e2"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#7f1d1d"
      }
    }
  },
  "fencing": {
    "preset": "fencing",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#57534e"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#57534e"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#57534e"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#78350f"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fef3c7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#713f12"
      }
    }
  },
  "appliance_repair": {
    "preset": "appliance_repair",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#1e293b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#1e293b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#1e293b"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#1e293b"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fee2e2"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#7f1d1d"
      }
    }
  },
  "garage_door": {
    "preset": "garage_door",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#334155"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#334155"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#334155"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fee2e2"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#7f1d1d"
      }
    }
  },
  "auto_detail": {
    "preset": "auto_detail",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#3f3f46"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#3f3f46"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#3f3f46"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#f4f4f5"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#18181b"
      }
    }
  },
  "junk_removal": {
    "preset": "junk_removal",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#7c2d12"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#c2410c"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#ffedd5"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#7c2d12"
      }
    }
  },
  "snow_removal": {
    "preset": "snow_removal",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#075985"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#075985"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#0369a1"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#0369a1"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#075985"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#075985"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#0369a1"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#e0f2fe"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#0c4a6e"
      }
    }
  },
  "notary": {
    "preset": "notary",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#7f1d1d"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fef3c7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#713f12"
      }
    }
  },
  "photography": {
    "preset": "photography",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#713f12"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fef3c7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#713f12"
      }
    }
  },
  "salon": {
    "preset": "salon",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#9d174d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#9d174d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#be185d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#be185d"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#9d174d"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#9d174d"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#be185d"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fce7f3"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#831843"
      }
    }
  },
  "spa": {
    "preset": "spa",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#134e4a"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#134e4a"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#0f766e"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#0f766e"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#134e4a"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#115e59"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#0f766e"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#ccfbf1"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#134e4a"
      }
    }
  },
  "dental": {
    "preset": "dental",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#155e75"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#155e75"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#0e7490"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#0e7490"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#155e75"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#155e75"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#0e7490"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#cffafe"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#164e63"
      }
    }
  },
  "medical": {
    "preset": "medical",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#1e3a8a"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#1e3a8a"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#1d4ed8"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#1d4ed8"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#1e3a8a"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#1e40af"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#1d4ed8"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#dbeafe"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#1e3a8a"
      }
    }
  },
  "legal": {
    "preset": "legal",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#14532d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#14532d"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#14532d"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#14532d"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fef3c7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#713f12"
      }
    }
  },
  "real_estate": {
    "preset": "real_estate",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#a16207"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fef3c7"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#713f12"
      }
    }
  },
  "fitness": {
    "preset": "fitness",
    "menu": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "rail": {
      "bg": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "tiles": {
      "bg": {
        "mode": "solid",
        "solid": "#ffffff"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "border": {
        "mode": "solid",
        "solid": "#e5e7eb"
      }
    },
    "buttons": {
      "bg": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "text": {
        "mode": "solid",
        "solid": "#ffffff"
      }
    },
    "accents": {
      "primary": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "secondary": {
        "mode": "solid",
        "solid": "#18181b"
      },
      "text": {
        "mode": "solid",
        "solid": "#0f172a"
      },
      "link": {
        "mode": "solid",
        "solid": "#991b1b"
      },
      "focus_ring": {
        "mode": "solid",
        "solid": "#b91c1c"
      },
      "badge_bg": {
        "mode": "solid",
        "solid": "#fee2e2"
      },
      "badge_text": {
        "mode": "solid",
        "solid": "#7f1d1d"
      }
    }
  }
};

export function getClientPreset(key) {
  const entry = CLIENT_PRESETS[key];
  if (!entry) return JSON.parse(JSON.stringify(CLIENT_PRESETS.default));
  return JSON.parse(JSON.stringify(entry));
}

