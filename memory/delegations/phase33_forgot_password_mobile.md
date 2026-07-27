## Delegation Brief · Phase 34 (web) → Phase 33 (mobile)
### "Forgot password?" Screen (Stub) + Login Link

**From:** Web team · Phase 34 · Feb 2026
**To:** e1_expo_frontend_dev
**Priority:** P2
**Language:** All comments, tests, and copy in **English**.
**Status:** Web shipped as a UI-only stub. Mobile parity outstanding.
Backend endpoint (`POST /api/auth/forgot-password`) is **still to be built** —
tracked in `/app/memory/todo_password_reset.md`.

---

### What changed on the web

1. **New page:** `/app/frontend/src/pages/ForgotPassword.jsx`
   - Route: `/forgot-password`
   - Renders a single-field form (email) + submit button.
   - On submit it currently does **NOT** hit any endpoint — it just
     flips local state and shows a neutral confirmation:
     _"If an account exists for that email, a reset link has been sent."_
   - The neutral copy is deliberate to prevent user-enumeration.
   - "Back to sign in" link routes back to `/login`.
2. **Login page update:** `/app/frontend/src/pages/Login.jsx`
   - Added a right-aligned link labelled **"Forgot password?"** just below
     the password field. Routes to `/forgot-password`.
   - `data-testid="login-forgot-password-link"`.

### `data-testid`s on web

| Element                           | testid                              |
|-----------------------------------|-------------------------------------|
| Page wrapper                      | `forgot-password-page`              |
| Title                             | `forgot-password-title`             |
| Form                              | `forgot-password-form`              |
| Email input                       | `forgot-password-email`             |
| Submit button                     | `forgot-password-submit`            |
| Confirmation banner (post-submit) | `forgot-password-confirmation`      |
| Back-to-login link                | `forgot-password-back-to-login`     |
| Login page link                   | `login-forgot-password-link`        |

---

### What we need from mobile

`/app/mobile/app/forgot-password.tsx` (new file, sibling of `login.tsx`).

1. Register the route in `/app/mobile/app/_layout.tsx` (or the
   `expo-router` stack config used by the project).
2. Mirror the web behaviour exactly:
   - One email input (`textContentType="emailAddress"`,
     `keyboardType="email-address"`, `autoCapitalize="none"`,
     `autoComplete="email"`).
   - Submit button primary-styled (same brand gradient as web).
   - **Do not** call any endpoint yet. Show the neutral confirmation
     banner immediately on submit. Add a `TODO:` code comment noting
     that when `POST /api/auth/forgot-password` ships, the handler
     becomes a one-line `fetch(...)` swap.
3. **Login screen link:** on `/app/mobile/app/login.tsx`, add a
   right-aligned "Forgot password?" `Pressable` under the password
   field. Same styling weight as the "Sign in" CTA but ghost.
4. `testID` parity: use the same values as the web `data-testid`s
   above (React Native's `testID` maps 1:1).
5. English-only copy — do NOT localize the neutral confirmation.

### Backend contract (for when it lands — do not build now)

```
POST /api/auth/forgot-password
Body: { "email": "user@example.com" }
Response (always 200):
  { "ok": true }
```

The endpoint must NOT reveal whether an account exists (enum-safe).
Rate-limit at 5 req / 15 min per IP + email combo.

### Guardrails

- Do NOT implement the actual reset flow (token generation, email
  send). Web hasn't either — this is a UI-only stub.
- Do NOT call `/api/auth/*` from the "Forgot password?" screen.
- Do NOT localize; English only.
- Neutral copy is a security requirement, not a UX preference — keep it.

---

### Reference paths

- Web page:     `/app/frontend/src/pages/ForgotPassword.jsx`
- Web login:    `/app/frontend/src/pages/Login.jsx` (link at ~line 200)
- Web Vitest:   `/app/frontend/src/test/phase34-forgot-password.test.jsx`
- Backlog TODO: `/app/memory/todo_password_reset.md`

### Deploy

- Mobile: OTA / EAS update after merge. No native modules required.
