# Iteration 50 — F7 Line Items Editor (Mobile Parity)

## Date: 2026-08-31

## What was implemented

### New Files
| File | LOC | Purpose |
|------|-----|---------|
| `src/api/lineItems.ts` | 108 | API helpers for line item CRUD + pricebook + categories + error parser |
| `src/components/jobs/LineItemsSection.tsx` | 1152 | Full CRUD line-items editor (list, add sheet, edit sheet, delete, offline, row errors, totals) |
| `__tests__/mobile-line-items-list.test.tsx` | 122 | List rendering, empty state, tech read-only, custom price hint |
| `__tests__/mobile-line-items-add.test.tsx` | 129 | Sheet open, pricebook picker, POST with F7 fields, custom price hint |
| `__tests__/mobile-line-items-edit.test.tsx` | 103 | Edit sheet prefill, PATCH with changed fields, description readonly |
| `__tests__/mobile-line-items-error-inline.test.tsx` | 116 | archived_category error in sheet + row highlight, retry works |
| `__tests__/mobile-line-items-offline.test.tsx` | 66 | Offline banner, disabled actions |

### Modified Files
| File | Change |
|------|--------|
| `app/job/[id].tsx` | Removed inline line items display + liStyles, imported and mounted `LineItemsSection` component |

## Web-to-Mobile Mapping
| Web Pattern | Mobile Equivalent |
|-------------|-------------------|
| `LineItemsSection.jsx` table | `LineItemsSection.tsx` card rows |
| `PricebookPickerModal` | Inline searchable list in add sheet |
| `CategoryPicker` dropdown | Horizontal chip selector |
| Inline qty/price editing | Bottom sheet form |
| `<input type="checkbox">` (writeback) | `<Switch>` |
| `Toast` | `Alert.alert()` |
| `data-testid` | `testID` (same naming: `job-lineitem-{id}`) |
| `parseErr()` | `parseLineItemError()` (same JSON parsing logic) |

## API Endpoints Used (matching web exactly)
- `GET /api/jobs/{jid}/line-items` — list + totals
- `POST /api/jobs/{jid}/line-items` — add (pricebook_item_id, description, quantity, unit_price, category, pricebook_writeback)
- `PATCH /api/jobs/{jid}/line-items/{lid}` — edit (quantity, unit_price, category, pricebook_writeback)
- `DELETE /api/jobs/{jid}/line-items/{lid}` — remove
- `GET /api/pricebook-items?q=...` — pricebook item picker
- `GET /api/pricebook/categories?active=true` — category list

## Test Results
| Suite | Tests | Status |
|-------|-------|--------|
| mobile-line-items-list | 5/5 | ✅ |
| mobile-line-items-add | 4/4 | ✅ |
| mobile-line-items-edit | 3/3 | ✅ |
| mobile-line-items-error-inline | 2/2 | ✅ |
| mobile-line-items-offline | 2/2 | ✅ |
| **Total** | **16/16** | ✅ |

## No regressions
- Subscriptions mobile tests: 15/15 ✅
- Metro bundled successfully: 2212 modules, no errors

## Mobile Primitives Reused vs Added
| Primitive | Status |
|-----------|--------|
| `Sheet` from `ui.tsx` | Not reused — built custom Modal sheet (more control over footer layout) |
| `useAuth` from `auth.ts` | Reused |
| `useOnline` from `offline.ts` | Reused |
| `api` from `api.ts` | Reused (via lineItems.ts wrapper) |
| `money` from `theme.ts` | Reused |
| `colors, spacing, radius, font, fontSize` | Reused |
| `Ionicons` | Reused |
| `CategoryChip` | New (horizontal chip selector) |

## Known Issues
- Expo preview tunnel sleeping (pre-existing, not a code issue)
- Metro warns about expo-image-manipulator version mismatch (pre-existing)
