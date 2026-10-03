# SPEC.md: Flood-Aware Route Planner

> Give this file to your AI coding tool at the start of every session.
> Build ONE phase at a time. Do not start the next phase until the current one runs and its tests pass.

---

## 1. What this app does

A web app that finds driving routes that avoid flooded roads, based on the user's **vehicle** and the **flood depth** reported or estimated on each road.

- User picks a vehicle (e.g., sedan, SUV, motorcycle) which sets a **safe wading depth** (cm).
- User picks an origin and destination on a map.
- The app returns the fastest route that is **passable for that vehicle**, and shows the normal (flood-ignorant) route next to it for comparison.
- Users can report floods ("drop a pin + choose depth") and confirm or clear existing reports.

**Initial coverage area:** Malabon, Metro Manila, Philippines (expand to Metro Manila after the MVP works).

## 2. Goals and non-goals

**Goals (MVP)**
1. Flood-aware routing with a vehicle-based cost function
2. Crowdsourced flood reports with automatic expiry
3. A static flood-hazard baseline layer
4. Deployed, public, mobile-friendly web app

**Non-goals (do NOT build these)**
- Turn-by-turn voice navigation
- User accounts / login
- Automatic flood detection from images or satellite
- Nationwide or international coverage
- Native mobile apps

## 3. Tech stack

| Layer | Choice |
|---|---|
| Frontend | React + Vite (TypeScript), MapLibre GL JS |
| Backend | Python 3.11+, FastAPI, Uvicorn |
| Routing | OSMnx + NetworkX (graph held in memory) |
| Database | PostgreSQL + PostGIS (Supabase or Neon free tier) |
| Testing | pytest (backend), Vitest (frontend) |
| CI | GitHub Actions |
| Deploy | Frontend: Vercel. Backend: Render or Fly.io |

## 4. Repository layout

```
flood-router/
├── SPEC.md
├── README.md
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, routes
│   │   ├── routing.py         # graph loading + cost function (CORE LOGIC)
│   │   ├── flood.py           # report aggregation, expiry, snapping
│   │   ├── vehicles.py        # vehicle presets
│   │   ├── models.py          # Pydantic schemas
│   │   └── db.py              # database access
│   ├── tests/
│   │   ├── test_routing.py
│   │   └── test_flood.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/        # Map, VehicleSelector, ReportButton, RoutePanel
│   │   ├── api.ts
│   │   └── App.tsx
│   └── package.json
├── notebooks/
│   └── 01_osmnx_exploration.ipynb
└── .github/workflows/ci.yml
```

## 5. Vehicle profiles

Safe wading depth is a conservative estimate, not a guarantee. Keep the safety margin built in.

| Vehicle | Safe depth (cm) |
|---|---|
| Motorcycle | 15 |
| Sedan / hatchback | 15 |
| Crossover / small SUV | 25 |
| SUV / pickup | 30 |
| Custom | user-entered |

Defined in `vehicles.py` as a dict. The user can also enter a custom clearance in cm.

## 6. Core routing logic (OWN THIS, understand every line)

Each road edge has `length_m`, `speed_kph` (from OSM or defaults), and `flood_depth_cm` (default 0).

```
base_time = length_m / (speed_kph * 1000 / 3600)        # seconds
ratio     = flood_depth_cm / safe_depth_cm

if ratio >= 1.0:   edge is IMPASSABLE   (cost = infinity / edge excluded)
elif ratio >= 0.5: cost = base_time * (1 + 4 * (ratio - 0.5) / 0.5)   # up to 5x slower near the limit
else:              cost = base_time
```

Route = Dijkstra or A* over edges with this cost, per request.

**Edge cases to handle and test**
- No passable route exists: return a clear "no safe route" response, plus the least-risky alternative flagged as UNSAFE
- Origin or destination on a flooded edge: warn the user
- Safe depth of 0 or missing: reject the request (HTTP 422)

## 7. Flood data layers

Final depth per edge = **max** of the following (max is the conservative choice):

1. **Active user reports** (Section 8)
2. **Static hazard baseline** (Phase 4): depth estimate from a flood-hazard map, used only when a "heavy rain" toggle is on
3. *(Stretch)* Rainfall or gauge-based scaling

### Depth levels for reports

| Label | Depth used (cm) |
|---|---|
| Ankle-deep | 10 |
| Half-tire / shin | 20 |
| Knee-deep | 45 |
| Waist-deep | 90 |

## 8. Flood reports

- A report = point (lat, lon), depth level, created_at, optional note.
- **Snapping:** a report affects all edges within **30 m** of the pin (use OSMnx nearest-edge lookup; reject reports with no road within 30 m).
- **Expiry:** a report is *active* for **2 hours** after creation (or after its latest "still flooded" confirmation).
- **Confirm:** "Still flooded" resets the 2-hour timer. Limit one confirm per device per report (use a random ID in localStorage, not a login).
- **Clear:** if **2 or more** "Cleared" votes arrive, the report becomes inactive immediately.
- Basic rate limit: max 10 reports per device per hour.

## 9. Database schema (PostGIS)

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE flood_reports (
  id            SERIAL PRIMARY KEY,
  geom          GEOGRAPHY(Point, 4326) NOT NULL,
  depth_cm      INTEGER NOT NULL CHECK (depth_cm BETWEEN 0 AND 200),
  note          TEXT,
  device_id     TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  clear_votes   INTEGER NOT NULL DEFAULT 0,
  is_cleared    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX flood_reports_geom_idx ON flood_reports USING GIST (geom);

CREATE TABLE report_votes (
  report_id  INTEGER REFERENCES flood_reports(id) ON DELETE CASCADE,
  device_id  TEXT NOT NULL,
  vote       TEXT NOT NULL CHECK (vote IN ('confirm', 'clear')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (report_id, device_id)
);
```

## 10. API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/vehicles` | List vehicle presets |
| POST | `/route` | Compute flood-aware and normal routes |
| GET | `/reports` | Active reports (optionally within a bounding box) |
| POST | `/reports` | Create a report |
| POST | `/reports/{id}/vote` | Confirm or clear a report |

### `POST /route`

Request:
```json
{
  "origin": {"lat": 14.65, "lon": 120.97},
  "destination": {"lat": 14.60, "lon": 121.00},
  "safe_depth_cm": 15,
  "heavy_rain": false
}
```

Response:
```json
{
  "safe_route": {
    "geometry": { "type": "LineString", "coordinates": [] },
    "distance_m": 0,
    "duration_s": 0,
    "max_depth_cm": 0,
    "status": "SAFE"
  },
  "normal_route": {
    "geometry": { "type": "LineString", "coordinates": [] },
    "distance_m": 0,
    "duration_s": 0,
    "max_depth_cm": 0
  },
  "warnings": []
}
```

`status` is one of `SAFE`, `RISKY` (uses edges at 50-100% of safe depth), `NO_SAFE_ROUTE`.

## 11. Frontend screens and components

- **Map view** (full screen, MapLibre + OpenStreetMap tiles)
  - Tap to set origin, tap again to set destination
  - Flood pins colored by depth
  - Safe route (solid, bold) vs. normal route (dashed, gray)
- **Vehicle selector** (dropdown + custom cm input)
- **Route summary panel:** time, distance, max flood depth along route, status badge, warnings
- **Report flood flow:** button, then drop pin, then choose depth, then submit
- **Report popup:** shows depth, age, "Still flooded" and "Cleared" buttons
- **Heavy rain toggle** (Phase 4)
- Must work on a phone-sized screen. Show loading and error states everywhere.

## 12. Build phases (checklist)

**Phase 0: Learn and explore**
- [ ] Notebook: download Malabon road network with OSMnx, plot it, compute a shortest path

**Phase 1: Routing core (plain Python, no UI)**
- [ ] `vehicles.py`, `routing.py` with the cost function from Section 6
- [ ] Function to mark edges as flooded from a dict of {edge: depth_cm}
- [ ] Unit tests: sedan avoids 30 cm; pickup passes 20 cm; no-route case; near-limit penalty applied
- [ ] Script that prints normal vs. safe route for a hard-coded flood

**Phase 2: API**
- [ ] FastAPI app with `/health`, `/vehicles`, `/route`
- [ ] PostGIS database, `/reports` endpoints, snapping and expiry logic
- [ ] Tests for expiry, voting, snapping, and rate limiting

**Phase 3: Frontend**
- [ ] Map, origin/destination selection, vehicle selector
- [ ] Draw safe vs. normal route
- [ ] Report flow and flood pins

**Phase 4: Data realism**
- [ ] Import a static hazard layer, convert it to per-edge baseline depth
- [ ] Heavy-rain toggle
- [ ] Report confirm/clear voting UI

**Phase 5: Polish and ship**
- [ ] Mobile layout, loading and error states
- [ ] CORS configured, rate limiting on, secrets in env vars only
- [ ] GitHub Actions CI (tests on every push)
- [ ] Deploy backend and frontend, set production env vars
- [ ] README: demo GIF, architecture diagram, design decisions, data limitations, disclaimer
- [ ] Evaluation: simulate N random trips with synthetic floods; report % of trips where flood-aware routing avoided impassable segments vs. standard shortest path

## 13. Safety and honesty requirements

- Show a visible disclaimer: *"Flood data is crowdsourced and estimated. Routes are suggestions, not guarantees of safety. Do not drive into floodwater you cannot see the bottom of."*
- Never label a route "safe" if it includes any edge with unknown data AND an active heavy-rain toggle without saying so
- Document the data limitations in the README

## 14. Rules for the AI coding assistant

1. Work on **one phase at a time**. Stop and let me run the code before continuing.
2. Commit-sized changes only. Tell me what files you changed and why.
3. For `routing.py` and `flood.py`: **explain the logic step by step** and write tests that match Section 6 and Section 8 exactly. Do not change the cost function without asking.
4. Never commit secrets. Use `.env` and keep `.env.example` updated.
5. Prefer simple, readable code over clever code. I need to be able to explain it in an interview.
6. If something in this spec is ambiguous or wrong, ask me instead of guessing.

## 15. Definition of done

- Public URL works on mobile and desktop
- Routing tests and report-logic tests pass in CI
- README has demo GIF, architecture diagram, setup instructions, and limitations
- I can explain the cost function, the snapping logic, and the expiry logic without looking at the code
