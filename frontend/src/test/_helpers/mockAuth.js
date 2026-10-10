/**
 * Shared mock-auth helper for the Phase C.web Bucket A2 sweep.
 *
 * The real ``@/auth`` module reads `localStorage` + context, so any
 * test that mounts a component whose render tree calls ``useAuth()``
 * without wrapping it in an ``<AuthProvider>`` crashes with:
 *
 *   Cannot destructure property 'user' of 'useAuth(...)' as it is null.
 *
 * Rather than pulling the real ``AuthProvider`` into every test
 * fixture (which triggers a chain of ``localStorage`` + ``/auth/me``
 * side-effects that then need THEIR own mocks), each affected test
 * file installs a lightweight ``vi.mock("@/auth", …)`` block that
 * returns the admin-shaped payload below.
 *
 * **Why the mock lives inline per file, not a shared ``vi.mock``:**
 *   ``vi.mock`` is hoisted to the top of the file BEFORE any imports
 *   run, so it cannot reference a shared symbol imported from this
 *   helper directly. The idiomatic solution is to inline the factory
 *   per test file and pull the user-shape constants + the recommended
 *   paste-in snippet from this file for reference.
 *
 * **Paste-in snippet (copy near the top of a test file, after other
 * ``vi.mock`` calls)**:
 *
 * ```js
 * vi.mock("@/auth", () => ({
 *   useAuth: () => ({ user: { id: "u-test-admin", role: "admin",
 *                              email: "admin@test.local" },
 *                       loading: false }),
 *   AuthProvider: ({ children }) => children,
 * }));
 * ```
 *
 * For non-admin role gates, override ``role`` on the inlined block:
 *
 * ```js
 * vi.mock("@/auth", () => ({
 *   useAuth: () => ({ user: { id: "u-tech", role: "technician" },
 *                       loading: false }),
 *   AuthProvider: ({ children }) => children,
 * }));
 * ```
 *
 * **Phase 20/22/23/24/26b/27/28/28b/30/31 regression locks**: this
 * helper is purely additive — it exports constants + documents the
 * paste-in shape. Existing tests that already stand up their own
 * ``vi.mock("@/auth")`` are unaffected.
 */
export const MOCK_ADMIN_USER = Object.freeze({
  id: "u-test-admin",
  role: "admin",
  email: "admin@test.local",
  tenant_id: "t-test",
});

export const MOCK_SUPER_ADMIN_USER = Object.freeze({
  id: "u-test-super",
  role: "super_admin",
  email: "super@test.local",
  tenant_id: "t-test",
});

export const MOCK_TECHNICIAN_USER = Object.freeze({
  id: "u-test-tech",
  role: "technician",
  email: "tech@test.local",
  tenant_id: "t-test",
  technician_id: "t-tech-1",
});

/**
 * Lazy factory for the mocked ``@/auth`` module shape. Used by test
 * files via the dynamic-import pattern that works around vi.mock
 * hoisting:
 *
 * ```js
 * vi.mock("@/auth", async () => {
 *   const { adminAuthModule } = await import("./_helpers/mockAuth");
 *   return adminAuthModule();
 * });
 * ```
 */
export const adminAuthModule = () => ({
  useAuth: () => ({ user: MOCK_ADMIN_USER, loading: false }),
  AuthProvider: ({ children }) => children,
});
