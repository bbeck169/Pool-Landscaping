# Iteration 1 — Templates Library Phase 3 (Mobile UI)

## What was implemented

### Screens
1. **Templates Library** (`templates/index.tsx`) — Two-tab layout:
   - **Library tab**: Browse template definitions with category filters (All, Pricing & Money, Ops & Checklists, Chemistry, Documents) and search. Each card shows title, description, category badge, system label. "New from template" button creates a draft and navigates to fill page.
   - **My Templates tab**: Grouped by status (Drafts / Finalized). Each row shows title, template name, category badge, status pill, date. Actions: open, duplicate, delete, download PDF (finalized only).

2. **Template Fill** (`templates/[id].tsx`) — Schema-driven form:
   - Loads instance + definition from API
   - Title input (editable for drafts)
   - Section-based field rendering from schema
   - Autosave: debounced (1s) + interval safety net (15s) + flush on unmount
   - Header actions: Finalize, Duplicate, Download PDF, Delete
   - Finalized banner when locked
   - KeyboardAvoidingView for proper keyboard handling

### Components
3. **TemplateCard** — Definition card with category badge, system label, description, create button
4. **TemplateFieldRenderer** — All field types: header, text, long_text, number, date, checkbox, select, signature, table
5. **TemplateTableField** — Horizontal-scrollable table with add/delete rows, supports text/number/checkbox columns
6. **TemplateStatusPill** — Draft (yellow) / Finalized (green) pill

## Web-to-Mobile Mapping
| Web | Mobile |
|-----|--------|
| `/admin/templates` | `/(app)/templates` (via Tools hub tile or More link) |
| `/admin/templates/:id` | `/(app)/templates/[id]` |
| Tabs via web buttons | Tab row with `tab` state |
| CSS grid for cards | ScrollView with vertical cards |
| `<select>` dropdowns | Chip-based selection |
| Browser PDF download | `Linking.openURL` |
| DOM signature canvas | Tap-to-sign with name + timestamp |
| `react-router-dom` `Link` | `router.push` |
| `localStorage` | N/A (API-only state) |

## API Endpoints Used (same as web)
- `GET /api/templates/definitions`
- `GET /api/templates/definitions/:code`
- `GET /api/templates/instances?mine=true`
- `GET /api/templates/instances/:id`
- `POST /api/templates/instances`
- `PATCH /api/templates/instances/:id`
- `POST /api/templates/instances/:id/finalize`
- `POST /api/templates/instances/:id/duplicate`
- `DELETE /api/templates/instances/:id`
- `POST /api/templates/instances/:id/pdf` (via Linking.openURL)

## Dependencies
No new dependencies installed. Used existing: expo-router, @expo/vector-icons, react-native.

## Known Issues
- Expo mobile preview tunnel was unavailable due to inactivity (infrastructure, not code)
- Signature field uses tap-to-sign rather than canvas drawing (mobile simplification)
- PDF download opens in browser via Linking.openURL since Expo can't render PDFs inline

## Navigation Entry Points
- Tools hub → "Templates" tile (both admin and tech roles)
- More screen → "Templates Library" admin link
