# Backlog #2 · Deferred: `react-hooks/rules-of-hooks` structural refactors

35 lint errors remain after the Backlog #2 cleanup, all in the same
category: **hooks called after an early `return`**. Both files use the
same anti-pattern — an `if (isAdmin) return <Redirect .../>` (or
equivalent) placed BEFORE the hook calls. The correct fix requires
moving the hook calls above the early return and gating the render
via a conditional JSX expression (or moving the redirect into a
`useEffect`). Each is a > 10-line refactor per file → deferred per
the Backlog #2 non-goal ("Do NOT rewrite component logic beyond
satisfying the lint rule").

## Deferred items

### 1. `mobile/app/(app)/jobs.tsx` — 7 errors (lines 43-114)

Root cause: L36-41 declares role predicates and does
`if (isAdmin) return <Redirect href="/(app)/schedule/calendar" />;`
BEFORE calling `useCallback` (L43), `useFocusEffect` (L66),
`useEffect` (L78), `useMemo` (L96), and 2 more `useCallback` (L107,
L114). If `user.role` flips between renders (login/logout), hook
order changes → React breaks.

Refactor sketch (~15 lines):
```tsx
// Move ALL hooks above the redirect. Use conditional JSX after them.
const isAdmin = /* ... */;
const load = useCallback(/* ... */, [/* deps */]);
useFocusEffect(useCallback(() => { load(filter); }, [filter, load]));
useEffect(/* ... */);
// ...
if (isAdmin) return <Redirect href="/(app)/schedule/calendar" />;
return <View>{/* ... */}</View>;
```

Risk: LOW. The early-return path never invokes the hook side effects
(that's the whole point of the early return), so moving hooks above
just means they run then unmount — no behavior change beyond a
transient extra render for admin sessions. Should ship with a
dedicated render test to lock the admin-redirect + tech-list flows.

### 2. `mobile/app/(app)/schedule/calendar.tsx` — 28 errors

Root cause: same pattern, much wider. Multiple early returns
inside the component body before hook calls. Requires reading the
full component to plan the hook-lift correctly.

Refactor size: estimated **60-100 lines** of restructuring across
the component. Not a single-file mechanical fix.

Recommend a dedicated micro-phase (call it **Backlog #2b** or
**Phase 41.3c**) that:
1. Adds a render test for calendar.tsx covering both the
   admin-visible and tech-visible flows first.
2. Lifts all hooks above the early returns.
3. Re-runs the render test to lock parity.

## Why these were NOT force-fixed in Backlog #2

The task's rules of engagement explicitly said:
> Structural issues (a whole component that violates rules-of-hooks
> by defining a hook inside a conditional) → surface as "needs
> manual refactor" and DEFER rather than force-fix. Better to leave
> a documented deferred item than to silently rewrite component
> logic.

Both files match that criterion exactly.

## Non-hook cleanup shipped in Backlog #2

- 30 × `react/no-unescaped-entities` — fixed mechanically (22 files).
- 1 × `react/jsx-no-undef` (`TextInput` missing import in
  `app/invoice/[id].tsx`) — fixed by adding the import.
- 1 × `import/no-unresolved` (`@/src/components/measure/MeasureMap`,
  which resolves at runtime via Metro's `.native.tsx` / `.web.tsx`
  extensions) — fixed with a targeted `eslint-disable-next-line`
  with a reason comment.
- 1 × `react-hooks/rules-of-hooks` in `app/seo/index.tsx` — root
  cause was a **name collision**, not a real hook: a local closure
  named `useKeyword` (a verb — "use this keyword") tripped
  ESLint's "any function starting with `use` = a hook" heuristic.
  Renamed to `applyKeyword`.
