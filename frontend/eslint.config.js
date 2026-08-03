// Phase 40b hotfix guardrail (Feb 2026) — flags any `@/lib/*` import path
// that would fail webpack at compile time.
//
// Background
// ----------
// The `@` alias resolves to `frontend/src/` (see `craco.config.js`).
// The `src/lib/` directory only contains three modules:
//   - `@/lib/utils` (cn helper for shadcn UI components)
//   - `@/lib/stripeConfig`
//   - `@/lib/checklistType`
//
// Every other `@/lib/*` path (e.g. `@/lib/api`, `@/lib/http`, `@/lib/router`)
// resolves to nothing and breaks the webpack build. Phase 40b shipped with
// two files that mistakenly imported `@/lib/api` (should be `@/api`) — this
// guardrail would have caught that regression at lint stage.
//
// Scope
// -----
// Intentionally minimal. This is NOT the full ESLint 9 migration for the
// frontend workspace — it only exists to enable the single
// `no-restricted-imports` rule below. Other rules will land in a
// dedicated ESLint 9 migration phase.
//
// See: CHANGELOG.md — 2026-02-XX — Phase 40b hotfix.

const reactHooks = require("eslint-plugin-react-hooks");
const importPlugin = require("eslint-plugin-import");

module.exports = [
  {
    files: ["src/**/*.{js,jsx}"],
    plugins: {
      // Registered as no-op so inline `/* eslint-disable react-hooks/... */`
      // directives across the codebase don't error with "rule not found".
      // The rules themselves are set to "off" — nothing new is enforced.
      "react-hooks": reactHooks,
      // Same story for `import/first` disable directives in test files.
      import: importPlugin,
    },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    linterOptions: {
      // Legacy `// eslint-disable-next-line no-new-func` directives litter
      // the widget scripts; treat unused ones as neutral, not fatal.
      reportUnusedDisableDirectives: "off",
    },
    rules: {
      "react-hooks/rules-of-hooks": "off",
      "react-hooks/exhaustive-deps": "off",
      "import/first": "off",
      "no-restricted-imports": ["error", {
        patterns: [{
          // Ban everything under `@/lib/*` EXCEPT the three real modules.
          group: [
            "@/lib/*",
            "!@/lib/utils",
            "!@/lib/stripeConfig",
            "!@/lib/checklistType",
          ],
          message:
            "The '@/lib/*' alias only exposes utils, stripeConfig, and checklistType. " +
            "Use '@/api' for the API client, '@/hooks/*', '@/components/*', or the correct relative path. " +
            "See CHANGELOG Phase 40b hotfix.",
        }],
      }],
    },
  },
];
