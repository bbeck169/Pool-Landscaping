# Iteration 113 — Phase 9-M
- Crews edit: not present on mobile (ComingSoon). Flagged no-op.
- Top-cluster "Portal Invite" button: never existed on mobile customers list. Flagged no-op.
- Chase: button removed from tile; `ChaseStalledInvitesSheet.tsx` stays on disk unimported (web kept its modal too); its own test still passes.
- Mobile tile previously had "Never logged in" (not "Cards on file"); now matches web's 3-card shape. "Never logged in" filter still lives in More filters sheet.
- Divergences: infinite scroll (onEndReached) instead of pager; profile has no tabs → Job History is a collapsible lazy section with summary badge. Invoices/Quotes/Service-report tabs don't exist on mobile profile → not created.
- useCustomerTabCache ported fresh (no generic TTL cache existed; same module-Map idiom as useFormTemplateRuntime).
- Legacy `phase35-customers-pagination.test.tsx` still asserts page_size=100 but was already failing at baseline (theme mock `inputColors`); left unchanged.
