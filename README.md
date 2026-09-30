# ParkFinder

A lightweight, API-driven, responsive web app for finding parks in any US city, with a **list view** and a **map view**.
Residents type a city ("Austin, TX"), browse its parks on a clustered map or in a keyboard-friendly list, and open a park to
see its name, address, description, amenities, hours and images, when that information exists.

Inspired by [ctparks.com/park-finder](https://ctparks.com/park-finder).

| Layer | Technology |
|---|---|
| Frontend | React 19 · TypeScript · Tailwind CSS 4 · Leaflet (react-leaflet) + marker clustering · Vite |
| Backend | Python 3.11+ · FastAPI · Pydantic v2 · HTTPX (async) |
| Data | OpenStreetMap: **Nominatim** (city → bounding box) and **Overpass API** (parks), with a local sample dataset as fallback |
| Tests | pytest + respx (backend) · Vitest + Testing Library (frontend) |

No database and no CI/CD are included, as the requirements asked.

---

## Contents

1. [Features](#1-features)
2. [Quick start](#2-quick-start)
3. [Architecture](#3-architecture)
4. [Project structure](#4-project-structure)
5. [API reference](#5-api-reference)
6. [Data model and sources](#6-data-model-and-sources)
7. [Architectural considerations](#7-architectural-considerations) (latency, caching, security, geospatial, accessibility)
8. [Error handling and graceful degradation](#8-error-handling-and-graceful-degradation)
   * [Traceability: local API call logs](#traceability-local-api-call-logs)
9. [Configuration](#9-configuration)
10. [Testing](#10-testing)
11. [Known limitations and trade-offs](#11-known-limitations-and-trade-offs)
12. [Extending the app](#12-extending-the-app)
13. [Licensing and attribution](#13-licensing-and-attribution)

---

## 1. Features

### Functional requirements

| # | Requirement | How it is met |
|---|---|---|
| 1 | List the parks in a US city the user enters | `GET /api/v1/parks/by-city?city=…` geocodes the city (US only), then returns every named public park inside its bounds, sorted by name. The list shows name and address and can be filtered by name. |
| 2 | Browse local parks on a map for the chosen city | The map fits to the city and shows clustered markers. Panning or zooming reloads parks for the visible area (`/parks/in-bounds`), debounced, and this can be switched off. |
| 3 | Show park information: name, address, description, amenities, hours, images. Keyboard navigable, visible focus | The details panel shows every available field. Missing fields are labelled "… not available" and **never invented**. Everything works by keyboard, with a high-contrast focus ring (dark outline plus yellow halo). |

### Extra touches
* Result summary and loading state in a polite live region. Errors in an `alert` region with a **Try again** button.
* A "degraded mode" notice when live data is down and sample data is shown instead.
* A "Zoom in" hint instead of a heavy request when the map shows too large an area.
* Mobile: a List / Map toggle. Desktop: list and map side by side.
* **Traceability:** every API call carries a request id, which is logged locally in `backend/logs/api.log` along with each upstream call. Errors show a Reference ID.
* A skip link, focus management (the details heading gets focus, and **Back** returns focus to the same list item), and an error boundary.

---

## 2. Quick start

### Prerequisites
* Python **3.11+** (tested with 3.12)
* Node.js **20+** (tested with 24) and npm

### Backend (terminal 1)

```bash
cd backend
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # optional; set PARKFINDER_CONTACT_EMAIL (Nominatim policy)
uvicorn app.main:app --reload --port 8000
```

Interactive API docs: <http://localhost:8000/docs>

### Frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. In development, Vite proxies `/api/*` to `http://localhost:8000`, so the browser only
ever talks to its own origin.

### Production build

```bash
cd frontend && npm run build      # type-checks, then outputs static files to frontend/dist
```

Serve `dist/` from any static host. Set `VITE_API_BASE_URL` at build time if the API is on another origin, and add that
origin to the backend's `PARKFINDER_CORS_ORIGINS`.

---

## 3. Architecture

```
┌──────────────────────────── Browser ────────────────────────────┐
│  React SPA (TypeScript, Tailwind)                               │
│  SearchBar ─► useParkSearch (abort, dedupe, keep old results)   │
│  ParkList (roving tabindex)  ParkDetails  ParkMap (Leaflet,     │
│  StatusBanner (live regions)              clusters, debounce)   │
└──────────────┬──────────────────────────────────────────────────┘
               │  GET /api/v1/...  (JSON, same origin in dev via proxy)
┌──────────────▼──────────────── FastAPI ─────────────────────────┐
│  Middleware: request id (X-Request-ID) + access log · rate      │
│              limit (token bucket/IP) · security headers ·        │
│              CORS (allow-list, GET only)                         │
│  Routes (validation via Pydantic/Query) ─► ParkService          │
│     ParkService: TTL+LRU cache with single-flight, bbox          │
│                  snapping, de-duplication, fallback policy       │
│        │                   │                        │            │
│  NominatimGeocoder   OverpassParkProvider    SampleParkProvider  │
│  (1 req/s limiter)   (polygons via center)   (assets/*.json)     │
│        └────── request_json(): timeouts, retries, backoff, ──────┘
│                Retry-After, error mapping (HTTPX async),         │
│                upstream-call log ─► backend/logs/api.log (JSON)  │
└──────────────┬───────────────────────┬──────────────────────────┘
               ▼                       ▼
     nominatim.openstreetmap.org   overpass-api.de
```

**Request flow for "Austin, TX":**
1. The frontend validates the input, aborts any request still in flight, and calls `/parks/by-city`.
2. The backend validates `city`, normalises it, and looks up `geo:austin, tx` in the cache. On a miss it calls Nominatim
   (rate-limited to 1 request/second, restricted to the US).
3. The city's bounding box is clamped to a maximum size and snapped outward to a 0.01° grid. This snapped box is the cache
   key. On a miss the backend calls Overpass.
4. OSM elements (points, ways, relations) become `Park` objects. Unusable ones are skipped and duplicates removed.
5. The response carries `parks`, `area`, `sources`, `degraded`, `warnings` and `attribution`.
6. The frontend renders the list and markers, and the map fits to `area.bbox`.

---

## 4. Project structure

```
ParkFinder/
├── assets/
│   └── parks.sample.json          # sample/fallback dataset (the shape given in the brief)
├── backend/
│   ├── app/
│   │   ├── main.py                # app factory, middleware, exception handlers, lifespan (HTTPX client)
│   │   ├── config.py              # Settings (env vars, prefix PARKFINDER_)
│   │   ├── models.py              # Pydantic models: Park, ParksResponse, ErrorResponse …
│   │   ├── errors.py              # domain exceptions → HTTP status + error code
│   │   ├── geo.py                 # BBox, coordinate validation, de-duplication
│   │   ├── cache.py               # TTL + LRU cache with single-flight
│   │   ├── rate_limit.py          # token bucket (clients) + min-interval limiter (Nominatim)
│   │   ├── http_client.py         # resilient request_json (timeouts, retries, Retry-After, upstream-call log)
│   │   ├── logging_config.py      # console + rotating JSON-lines file logging, redaction
│   │   ├── request_context.py     # request id (X-Request-ID) context
│   │   ├── api/routes.py          # /api/v1 endpoints
│   │   ├── services/park_service.py
│   │   └── providers/             # base.py (protocols), nominatim.py, overpass.py, sample.py
│   ├── logs/                      # api.log (+ rotated api.log.1 … .5), created at runtime, git-ignored
│   ├── tests/                     # 180 pytest tests
│   ├── requirements.txt / requirements-dev.txt / pyproject.toml / .env.example
├── frontend/
│   ├── src/
│   │   ├── api/                   # client.ts (fetch wrapper, ApiError), apiLog.ts (client call log), types.ts
│   │   ├── hooks/useParkSearch.ts # search state, abort, dedupe
│   │   ├── components/            # SearchBar, ParkList, ParkDetails, ParkMap, StatusBanner, ErrorBoundary
│   │   ├── utils/                 # format.ts, validation.ts
│   │   ├── App.tsx / main.tsx / index.css
│   │   └── **/*.test.ts(x)        # 80 Vitest tests
│   ├── vite.config.ts / tsconfig.json / .env.example
└── README.md
```

---

## 5. API reference

Base path `/api/v1`. All endpoints are read-only `GET` and return JSON. OpenAPI and Swagger UI are at `/docs`.

### `GET /api/v1/parks/by-city`

| Query | Rules |
|---|---|
| `city` | Required. 2–100 characters. Letters (accents allowed), spaces and `. , ' -`. Examples: `Austin, TX`, `St. Louis, MO`, `Coeur d'Alene`. |

```bash
curl "http://localhost:8000/api/v1/parks/by-city?city=Austin,%20TX"
```

```json
{
  "parks": [
    {
      "id": "osm-way-123456",
      "name": "Adams-Hemphill Neighborhood Park",
      "description": null,
      "location": { "lat": 30.2951, "lng": -97.7375, "address": "201 West 30th Street, Austin, TX 78705" },
      "amenities": ["dogs-allowed"],
      "hours": "Mo-Su 05:00-22:00",
      "images": [],
      "acreage": null,
      "rating": null,
      "website": null,
      "source": "openstreetmap"
    }
  ],
  "count": 427,
  "area": {
    "label": "Austin, Travis County, Texas, United States",
    "bbox": { "south": 30.0985, "west": -97.9368, "north": 30.5166, "east": -97.5605 },
    "center": { "lat": 30.3076, "lng": -97.7486 }
  },
  "sources": ["openstreetmap"],
  "degraded": false,
  "warnings": [],
  "attribution": "Park data © OpenStreetMap contributors (ODbL)"
}
```

### `GET /api/v1/parks/in-bounds`

| Query | Rules |
|---|---|
| `south`, `north` | Required. Numbers in −90…90, with `south < north`. |
| `west`, `east` | Required. Numbers in −180…180, with `west < east` (boxes crossing the antimeridian are not supported). |
| Size | Each side may be at most `PARKFINDER_MAX_BBOX_SPAN_DEG` (default 1.0°). Larger boxes return 422. |

### `GET /api/v1/parks/{park_id}`

`park_id` must match `^[a-z0-9][a-z0-9-]{0,119}$`, for example `osm-way-123456` or `prospect-park`. The park is served from
recent search results, the sample data, or a single Overpass lookup, in that order.

### `GET /api/health`

Returns `{"status": "ok", "version": "0.1.0"}`. Not rate-limited.

### Error envelope

Every error, including validation errors and unknown routes, uses the same shape:

```json
{ "error": { "code": "validation_error", "message": "The request parameters are invalid.",
             "details": [{ "field": "query.city", "message": "String should match pattern …" }] } }
```

| HTTP | `code` | When |
|---|---|---|
| 404 | `city_not_found`, `not_found` | Unknown city (and no sample match), unknown park id, unknown route |
| 405 | `method_not_allowed` | Anything other than GET |
| 422 | `validation_error` | Missing, malformed or out-of-range parameters (raw input is **not** echoed back) |
| 422 | `invalid_request` | Semantic problems: inverted bounding box, area too large |
| 429 | `rate_limited` | Client exceeded our rate limit. Includes a `Retry-After` header. |
| 500 | `internal_error` | Unexpected bug. Generic message; details are only logged on the server. |
| 503 | `service_unavailable` | Upstream failed (timeout, 429, 5xx) **and** no fallback data exists. Passes on the upstream `Retry-After` when known. |

---

## 6. Data model and sources

The `Park` model follows `assets/parks.sample.json` and adds two optional fields, `website` and `source`:

| Field | Type | From OpenStreetMap |
|---|---|---|
| `id` | string | `osm-{node\|way\|relation}-{id}` (stable and unique) |
| `name` | string | `name` tag. **Unnamed parks are skipped.** |
| `description` | string \| null | `description` tag |
| `location.lat/lng` | number | Node coordinates, or the polygon's `center` for ways and relations |
| `location.address` | string \| null | `addr:housenumber`, `addr:street`, `addr:city`, `addr:state`, `addr:postcode` |
| `amenities` | string[] | Only **explicit** tags: `toilets=yes` → restrooms, `drinking_water`, `dog`, `wheelchair`, `lit`, `playground`, `bbq`, `parking` |
| `hours` | string \| null | `opening_hours` (the raw OSM syntax, shown as-is) |
| `images` | string[] | `image` tag, only if it is an http(s) URL |
| `acreage`, `rating` | number \| null | Not available from OSM, so always `null` (sample data may have them) |
| `website` | string \| null | `website` / `contact:website`, only http(s) |
| `source` | `"openstreetmap"` \| `"sample"` | Where the record came from |

**Why OpenStreetMap?** It is free, needs no API key, covers every US city, and represents parks as polygons. That coverage
matters more than the richer data a single city's portal might offer. The trade-off is that community data is uneven:
description, hours and images are often missing, and the UI says so plainly. Municipal open-data APIs can be added as
extra providers (see [§12](#12-extending-the-app)).

**Sample data** (`assets/parks.sample.json`) is used when OSM is unavailable, or when the geocoder does not know a city but
a sample park's address matches it. Each record is validated on its own, so one malformed entry is logged and skipped
rather than breaking the dataset. Sample images point to placeholder URLs. The UI handles images that fail to load by
showing "Image could not be loaded."

---

## 7. Architectural considerations

### A. API latency and timeouts
| Concern | Implementation |
|---|---|
| Asynchronous I/O | One shared `httpx.AsyncClient` per app (connection pooling), created in the FastAPI lifespan. |
| Timeouts | Connect 5 s, read 25 s (configurable). Overpass is asked to stop 2 s before our read timeout. The frontend has its own 30 s timeout. |
| Retries | `request_json` retries timeouts, connection errors and HTTP 429/502/503/504 with exponential backoff, honouring `Retry-After` up to a cap (5 s). Other 4xx and 500 responses are not retried. |
| Duplicate requests when panning | Frontend: `moveend` is **debounced** (600 ms), fits and pans made by the app itself are ignored, and identical viewports (rounded to about 100 m) are skipped. Backend: the snapped bounding box cache key, plus **single-flight** coalescing, means concurrent identical requests make one upstream call. |
| Cancelling outdated requests | Each new search **aborts** the previous `fetch` (`AbortController`), so the newest search wins. The backend shields the shared upstream call so one cancelled client does not cancel it for others. |
| No frozen UI | A spinner in the live region. Previous results stay visible (`aria-busy`) while loading. The map bundle is lazy-loaded, so the list is usable immediately. |

### B. In-memory caching
* A `TTLCache` with LRU eviction and a **maximum size** (`CACHE_MAX_ENTRIES`, default 256).
* **TTL:** 5 minutes for park searches, 24 hours for geocoding (city boundaries rarely change), and 5 minutes for park details.
* **Keys** come from the *normalised* bounding box. It is snapped outward to a 0.01° grid (about 1 km), so small pans reuse
  one entry. City keys are the normalised, lower-cased query.
* **Expiry** is checked on read. `invalidate(key | None)` is available. Failures are **never cached**.
* **Several instances:** the cache is per process. If you scale out, put a shared cache (e.g. Redis) behind the same
  `get` / `set` / `get_or_set` interface. It is only needed when many instances make repeated upstream calls.

### C. API security
| Concern | Implementation |
|---|---|
| Keys stay server-side | All provider calls happen on the backend. Configuration lives in `backend/.env` (git-ignored). The browser never calls Nominatim or Overpass and never sees credentials. The frontend `.env` holds only the public API base URL. |
| CORS | An explicit allow-list (`PARKFINDER_CORS_ORIGINS`), `GET` only, no credentials. |
| Input validation | Pydantic/Query constraints: city pattern and length, lat/lng ranges, finite numbers, `south<north`, `west<east`, maximum box size, park-id pattern. Result count is capped (`MAX_RESULTS`). |
| Rate limiting | A per-IP token bucket (60/min, burst 20 by default) on `/api/v1/*`, with 429 and `Retry-After`. Memory is bounded. Behind a trusted reverse proxy, derive the client IP from `X-Forwarded-For`. |
| Upstream etiquette | An identifying User-Agent, a 1 request/second limiter for Nominatim, and caching, as the OSM usage policies require. |
| Output hardening | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. Only http(s) URLs are accepted for images and websites (no `javascript:`). React escapes all text. External links use `rel="noopener noreferrer"`. |
| Error hygiene | 500 responses show a generic message. Stack traces are only logged. Validation errors never echo raw input. |
| Audit trail | Every request and upstream call is logged locally with a request id, and credential-like parameters are redacted (see [Traceability](#traceability-local-api-call-logs)). |

### D. Geospatial correctness
| Concern | Implementation |
|---|---|
| Parks as polygons | Overpass queries `node`, `way` **and** `relation` (multipolygons) with `out center`, so polygon parks get a representative point. |
| Duplicates | De-duplication first by id, then by the same name within about 200 m (for example a park mapped as both a point and a polygon). The richer record wins. |
| Missing or malformed coordinates | Rejected when non-numeric, NaN/∞, out of range, or (0,0) "null island". Such records are skipped, not guessed. |
| Parks near the edges | Overpass returns polygons that *intersect* the box, even when their centre is outside it. Snapping the box outward adds a margin on top. |
| Very large areas | City boxes larger than the maximum are clamped around their centre, with a warning. Viewport requests that are too large are refused (422), and the UI asks the user to zoom in instead. |
| Many markers | `leaflet.markercluster` groups nearby markers. Selecting a park inside a cluster zooms in to reveal it. |

### E. Accessibility (WCAG 2.2 AA oriented)
* **The list works fully without the map.** A roving tabindex: Tab enters the list at one item; ↑/↓, Home and End move
  between parks; Enter or Space opens one.
* **Visible focus** on every control, including Leaflet markers and zoom buttons: a 3 px dark outline plus a yellow halo.
* **Selection is not shown by colour alone.** List items show a "✓ Selected" badge and a thick left border
  (`aria-current`). The selected map marker is larger, shows a ★ and has a thick dark ring.
* **Accessible labels:** the search `label`, `aria-describedby` hints and errors, `aria-invalid`, labelled map region and
  zoom buttons, marker `title`/`alt` set to the park name, and `aria-pressed` on the mobile view toggle.
* **Announcements:** result counts and loading in `role="status"`, errors in `role="alert"`, and warnings carry a text
  label ("Notice:"), not only a colour.
* **Focus management:** opening details moves focus to its heading. **Back** returns focus to the same list item. There is a
  skip link to the results.
* Reduced motion is respected for the spinner and map animations. Images have alt text. Links that open a new tab say so.

---

## 8. Error handling and graceful degradation

| Situation | Backend behaviour | What the user sees |
|---|---|---|
| Invalid input | 422 with field details | Inline error on the search box (checked on the client first), or an alert |
| Unknown city | 404 `city_not_found`, unless a sample park matches | "No US city matching '…' was found." (no retry button) |
| Nominatim down or throttled | Retries, then **sample data for that city** (`degraded: true`), otherwise 503 with `Retry-After` | Sample results with a notice, or an error with **Try again** |
| Overpass timeout, 429, 5xx or bad JSON | Retries, then **sample data in the same area** (`degraded: true`), otherwise 503 | Same as above |
| No parks in the area (upstream healthy) | 200, `count: 0` | "No parks found in …" |
| Our rate limit hit | 429 + `Retry-After` | "Too many requests. Please wait N seconds…" |
| Unexpected server bug | 500, generic message, full log on the server | "Something went wrong on our side…" |
| Network down or client timeout | n/a | "Unable to reach the server…" or "The request took too long…" |
| Panning fails | n/a | The previous list stays, and an alert is shown |
| Park field missing | `null` / `[]` | "Hours not available", "No images available.", etc. |
| Image URL broken | n/a | "Image could not be loaded." |
| React render bug | n/a | Error boundary with a Reload button |

**Principle:** when the backend cannot know the answer, it never says "no parks". It returns 503 instead of an empty list
that might be false.

### Traceability: local API call logs

Every API call can be traced end to end with a single **request id**:

1. The frontend creates an id (`web-<uuid>`) for each call and sends it as `X-Request-ID`.
2. The backend reuses the id if it is safe (`[A-Za-z0-9._-]{8,64}`), otherwise generates one. The id is stored in a
   context variable, so **every log line written while handling that request carries it**, including upstream calls.
3. The id comes back in the `X-Request-ID` response header and in every error body (`error.request_id`). The UI shows it
   as **"Reference ID"** next to error messages, so a user can report it.

**Backend log file:** `backend/logs/api.log`. It is JSON lines, rotated at 5 MB with 5 backups kept, and also printed in a
readable form on the console.

| `event` | Logged when | Key fields |
|---|---|---|
| `http_request` | Every API request (access log). INFO for 2xx/3xx, WARNING for 4xx, ERROR for 5xx. Health checks at DEBUG. | `method`, `path`, `query`, `status`, `duration_ms`, `client_ip`, `user_agent`, `rate_limited` |
| `upstream_call` | Every attempt to Nominatim or Overpass, **including retries** | `provider`, `method`, `url`, `params` (redacted), `body_bytes`, `status`, `error` (e.g. `ConnectTimeout`), `attempt`, `outcome` (`success` / `retry` / `failed`), `duration_ms` |
| `cache_lookup` | Before a park query | `cache_key`, `hit` |
| `provider_failure` | A provider failed after its retries | `provider`, `error_code` |
| `park_search` | A search completed | `kind` (city/bounds), `query`, `count`, `sources`, `degraded`, `warnings` |
| `unhandled_error` | An unexpected exception | `exception` (full traceback, never sent to the client) |

A real trace from a moment when the public Overpass server was not responding. It is shortened, and the `error` values show
the current format: the original capture predates logging the timeout type and read `"timeout"`.

```json
{"ts":"…22:36:55.960Z","level":"INFO","logger":"parkfinder.upstream","request_id":"web-livecheck-0001","event":"upstream_call","provider":"Nominatim","status":200,"outcome":"success","duration_ms":706.5,"params":{"q":"Boise, ID", "…":"…"}}
{"ts":"…22:36:55.962Z","level":"INFO","logger":"parkfinder.service","request_id":"web-livecheck-0001","event":"cache_lookup","cache_key":"parks:43.5000,-116.3700,43.7000,-116.0900","hit":false}
{"ts":"…22:37:00.968Z","level":"WARNING","logger":"parkfinder.upstream","request_id":"web-livecheck-0001","event":"upstream_call","provider":"Overpass","error":"ConnectTimeout","attempt":1,"outcome":"retry"}
{"ts":"…22:37:12.502Z","level":"WARNING","logger":"parkfinder.upstream","request_id":"web-livecheck-0001","event":"upstream_call","provider":"Overpass","error":"ConnectTimeout","attempt":3,"outcome":"failed"}
{"ts":"…22:37:12.502Z","level":"WARNING","logger":"parkfinder.service","request_id":"web-livecheck-0001","event":"provider_failure","error_code":"upstream_timeout"}
{"ts":"…22:37:12.504Z","level":"ERROR","logger":"parkfinder.access","request_id":"web-livecheck-0001","event":"http_request","path":"/api/v1/parks/by-city","status":503,"duration_ms":17254.7}
```

**Finding a call:**

```powershell
# Windows PowerShell
Select-String -Path backend\logs\api.log -Pattern "web-livecheck-0001"
```
```bash
# macOS / Linux (jq optional)
grep web-livecheck-0001 backend/logs/api.log | jq .
jq 'select(.event=="upstream_call" and .outcome!="success")' backend/logs/api.log   # all upstream problems
```

**Frontend log:** the browser keeps the last 50 calls in memory (`window.__parkfinderApiLog` in DevTools), each with its
request id, URL, status, outcome (`success`, `error`, `aborted`, `timeout`, `network_error`) and duration. In development
each call is also printed to the console as `[api] GET … -> 200 (412 ms) id=web-…`.

**Privacy and safety:** parameters whose names look like credentials (`key`, `token`, `secret`, `password`, `auth`,
`signature`) are masked as `***`. Incoming ids are validated to prevent log injection. Tracebacks stay in the log file.
Client IP addresses are logged for abuse investigation. Remove or hash `client_ip` in `main.py` if your privacy policy
requires it. The log is local to each instance; for several instances, ship the JSON lines to a central log store
(e.g. Loki, ELK or CloudWatch). No format change is needed.

---

## 9. Configuration

Backend settings come from environment variables prefixed `PARKFINDER_` or from `backend/.env`. See
`backend/.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed browser origins (JSON list) |
| `CONTACT_EMAIL` | – | Added to the User-Agent (Nominatim policy) |
| `NOMINATIM_URL` / `OVERPASS_URL` | public OSM endpoints | Point to self-hosted instances if needed |
| `CONNECT_TIMEOUT` / `READ_TIMEOUT` | 5 / 25 s | Upstream timeouts |
| `MAX_RETRIES` | 2 | Upstream retry attempts |
| `CACHE_TTL_SECONDS` / `GEOCODE_CACHE_TTL_SECONDS` | 300 / 86400 | Cache lifetimes |
| `CACHE_MAX_ENTRIES` | 256 | Cache size limit (LRU) |
| `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_BURST` | 60 / 20 | Per-client limits |
| `MAX_BBOX_SPAN_DEG` | 1.0 | Largest area per request (keep `MAX_VIEWPORT_SPAN_DEG` in `App.tsx` in sync) |
| `MAX_RESULTS` | 500 | Cap on parks per upstream query |
| `ENABLE_SAMPLE_FALLBACK` | true | Serve sample data when OSM fails |
| `SAMPLE_DATA_PATH` | `assets/parks.sample.json` | Fallback dataset |
| `LOG_LEVEL` | `INFO` | `DEBUG` also logs health checks |
| `LOG_TO_FILE` / `LOG_DIR` / `LOG_FILE_NAME` | true / `backend/logs` / `api.log` | JSON-lines traceability log |
| `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` | 5 MB / 5 | Rotation: at most about 30 MB on disk |

Frontend: `VITE_API_BASE_URL` (empty in development). **Never put secrets in `VITE_*` variables**, because they are
bundled into the browser code.

---

## 10. Testing

```bash
# Backend: 180 tests
cd backend && .venv/Scripts/python -m pytest -q        # macOS/Linux: .venv/bin/python -m pytest -q

# Frontend: 80 tests, plus type-check
cd frontend && npm test && npm run typecheck
```

Upstream HTTP is mocked with **respx** (backend) and a stubbed `fetch` (frontend). The tests make no real network calls.

| Area | Examples of what is tested |
|---|---|
| Upstream throttling / errors | 429 retried then success, 429 exhausted → `retry_after` passed on, `Retry-After` in seconds and as a date, the backoff cap, 500 not retried, 504, read and connect timeouts, connection refused, invalid JSON, unexpected payload shapes |
| Our API status codes | 200, **422** (missing, malformed, NaN, out-of-range, XSS/SQL-like input, inverted or oversized box, bad park id), 404, 405, **429** with `Retry-After`, **500** without leaking details, **503** with `Retry-After`, CORS allow/deny and preflight, security headers |
| Degradation | Geocoder or Overpass failure → sample fallback, no fallback → 503, fallback disabled, failures not cached, full stack with real providers and Overpass 500 |
| Geospatial | Coordinate validation (NaN, ∞, null island, booleans), box validation, clamping, snapping stability and world limits, edge containment, de-duplication (same id, same name nearby, same name far apart) |
| Caching | TTL expiry, custom TTL, LRU eviction, invalidation, single-flight coalescing, a cancelled caller not cancelling the shared fetch |
| Parsing | OSM node, way and relation; tag mapping; missing fields stay null; unsafe URLs dropped; 10 malformed element shapes; Nominatim city preference; malformed sample records skipped |
| Frontend client | URL encoding, 429/422/500/503/502 (non-JSON) mapping, invalid JSON, network error, caller abort vs timeout |
| Traceability | Request id generated, reused when valid, replaced when unsafe (log injection); X-Request-ID in every response and error body; access-log fields and levels (200 INFO, 4xx WARNING, 5xx ERROR); one id across access, cache, every upstream attempt (incl. retries) and search summary; timeouts logged by type; unhandled errors logged with traceback but not leaked; rate-limited requests logged; credential redaction; handler idempotency; CORS allows/exposes the header; client log (success, error, aborted, timeout, network error, 50-entry cap) |
| Frontend behaviour | Newest request wins (older ones aborted), duplicate viewports skipped, retry, results kept when panning fails, keyboard list navigation (arrows, Home, End, Enter, Space), focus restore, "not available" labels, broken images, live regions, zoom-in hint, follow-map toggle, filter, skip link |

---

## 11. Known limitations and trade-offs

* **OSM data completeness:** descriptions, hours and images are often missing. Acreage and rating are not in OSM. These
  show as "not available" rather than being invented.
* **Hours** are shown in raw OSM `opening_hours` syntax (e.g. `Mo-Su 05:00-22:00`). They are not parsed into "open now".
* **City bounds** come from the geocoder's bounding box, so parks just outside the city limits but inside the box are
  included. Very large results (over 500) are capped, with a "zoom in" warning.
* **Antimeridian:** boxes that cross it are not supported. This does not affect the continental US or Hawaii. It affects
  only the far western Aleutians.
* **Map clusters are mouse and touch oriented.** Keyboard users get the full experience through the list, which the
  requirements call the primary accessible path. Individual markers are focusable.
* **Rate limiting and cache are per process.** Use a shared store (e.g. Redis) when running several instances.
* **Public OSM services** have fair-use limits. For production traffic, self-host Nominatim and Overpass or use a
  commercial provider (the URLs are configurable).
* The full UI flow was verified with automated tests, a headless-browser screenshot and live API calls. It has not been
  tested with a screen reader in this MVP.

---

## 12. Extending the app

* **New data provider** (e.g. a city's Socrata or ArcGIS open-data API): implement `ParkProvider`
  (`parks_in_bbox`, `park_by_id`) in `app/providers/` and wire it in `build_park_service()`. Keep API keys in `Settings`,
  meaning backend env vars only.
* **Enrichment:** join OSM `wikidata` tags to Wikidata or Wikimedia Commons for descriptions and images, cached the same
  way.
* **Filters:** add amenity filters to the Overpass query and the cache key (the key already comes from normalised inputs).
* **Shared cache:** implement the `TTLCache` interface on Redis.

---

## 13. Licensing and attribution

* Map tiles and park data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the
  ODbL. Attribution is shown on the map and in the footer.
* Geocoding by [Nominatim](https://nominatim.org/). Park queries through the [Overpass API](https://overpass-api.de/).
  Please follow their usage policies.
* Open-source dependencies: FastAPI, Pydantic, HTTPX, React, Leaflet, Leaflet.markercluster, Tailwind CSS, Vite, Vitest.
