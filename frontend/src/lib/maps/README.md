# `@/lib/maps` — Web maps abstraction (Phase K39a · Feb-2026)

This module lets the app render tiles + markers via **Google Maps** (default) or **HERE Maps**, gated by a runtime env flag. It is the mandatory import path for every consumer — never import from `@vis.gl/react-google-maps` (or `@here/maps-api-for-javascript`) directly.

## Env flags

| Variable | Values | Default | Purpose |
| --- | --- | --- | --- |
| `REACT_APP_MAPS_PROVIDER` | `"google"` \| `"here"` | `"google"` | Selects the runtime adapter. |
| `REACT_APP_HERE_API_KEY` | string | `""` | HERE JavaScript API key (must be created at developer.here.com and trusted-domain-restricted). |
| `REACT_APP_GOOGLE_MAPS_API_KEY` | string | `""` | Existing Google JS API key (pre-K39a). Untouched. |

Fallback semantics: if `REACT_APP_MAPS_PROVIDER=here` but `REACT_APP_HERE_API_KEY` is empty, a single boot-time `console.warn` fires and the adapter silently falls back to Google. This keeps preview envs safe even if HERE creds haven't been wired.

## API surface

```js
import {
  MapsProviderGate,   // shell wrapper (mount once, in AppLayout)
  useMapsProvider,    // hook: returns "google" | "here"
  Map, MapView,       // main map component (alias)
  AdvancedMarker,     // marker (HTML content)
  Marker,             // alias — Google no longer distinguishes
  InfoWindow,
  Polyline,
  Pin,                // Google-only; renders `null` under HERE
  useMap,             // returns the underlying map instance
  useMapsLibrary,     // Google-only; returns `null` under HERE
} from "@/lib/maps";
```

## Installing HERE (production only)

The HERE JS SDK ships on HERE's **private npm registry** — the yarn public registry does NOT have it. To enable HERE mode in production:

1. Create a HERE **JavaScript API key** at [platform.here.com](https://platform.here.com) → Access Manager → Apps → Credentials. Restrict it by trusted domains.
2. Add to `frontend/.npmrc`:
   ```
   @here:registry=https://repo.platform.here.com/artifactory/api/npm/maps-api-for-javascript/
   ```
3. Install the package:
   ```bash
   cd /app/frontend && yarn add @here/maps-api-for-javascript
   ```
4. Set env:
   ```
   REACT_APP_MAPS_PROVIDER=here
   REACT_APP_HERE_API_KEY=<your JavaScript API key>
   ```
5. Restart the dev server / rebuild.

Until step 3 is done, the runtime `import("@here/maps-api-for-javascript")` fails gracefully and every HERE `Map` renders the "Map unavailable" fallback tile — nothing white-screens the app.

## Boundary contract

The HERE adapter is required to **never throw at render time** (K39a §4). Missing key, missing package, or SDK init crash → fallback tile + `console.warn`. The K37 `PortalErrorBoundary` at the `AppLayout` mount stays intact and above the gate.
