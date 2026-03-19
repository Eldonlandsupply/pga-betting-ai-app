# Data Sources

## Current Data Architecture (Phase 1)

All data is provided manually via `input/current_event.json`.
The system is fully functional without any API connections.

---

## Phase 2 Data Sources (Roadmap)

### DataGolf API
- **Purpose**: Player strokes gained stats, historical rounds, player ratings, field lists
- **Key endpoints**:
  - `/field-updates` — current event field with world rankings
  - `/preds/skill-decompositions` — multi-year SG decompositions per player
  - `/historical-raw-data` — round-level SG data for backtesting
  - `/get-schedule` — PGA + LIV schedule
- **Ingest module**: `ingest/stats_ingest.py` (stub ready)
- **Priority**: HIGH — this is the most valuable data source for model quality
- **Cost**: Subscription required

### The Odds API
- **Purpose**: Real-time sportsbook prices across major books
- **Key endpoints**:
  - `/sports/golf_pga/odds/` — PGA outrights, placements, H2H
  - `/sports/golf_liv/odds/` — LIV markets (if available)
- **Ingest module**: `ingest/market_ingest.py` (stub ready)
- **Priority**: HIGH — live lines essential for real edge detection
- **Cost**: Freemium (limited calls/month free; paid for live data)

### PGA Tour Stats Website (Scraper)
- **Purpose**: Supplemental SG, proximity, scrambling data
- **Priority**: MEDIUM — DataGolf is cleaner, but this is free
- **Note**: Scraping is subject to ToS changes

### OWGR (Official World Golf Ranking)
- **Purpose**: World rankings as baseline field strength signal
- **URL**: https://www.owgr.com/ranking
- **Priority**: LOW — DataGolf provides rankings; OWGR is a cross-check

### Weather (Phase 2)
- **Purpose**: Wind forecast for course-fit adjustments
- **Source**: Weather.gov (free) or Windy.com API
- **Ingest module**: `ingest/weather_ingest.py` (stub ready)
- **Priority**: MEDIUM — material for wind-heavy courses (Sawgrass, links events)

---

## Manual Input Schema

When using manual mode, build `input/current_event.json` following:
- Full schema: `docs/schema.md`
- Field guide: `docs/event_packet_guide.md` (inherited from existing repo)
- Quick template: `input/current_event.json` (example with Players Championship data)

---

## Recommended Free Data Workflow (Pre-Phase 2)

| Data type | Free source | How to get it |
|---|---|---|
| Strokes Gained | PGA Tour Stats page | Manual lookup per player |
| World Rankings | OWGR.com | Weekly CSV download |
| Sportsbook Odds | FanDuel, DraftKings websites | Manual entry |
| Field | PGA Tour tournament page | Manual entry |
| Course history | PGA Tour stats, DataGolf free tier | Manual lookup |
| Weather | Weather.gov or Windy.com | Manual check |

---

## Data Quality Flags

All data inputs must include a `data_quality` block (see schema.md).
The validator enforces quality flags and the model degrades confidence
when fields are missing or stale.

Key quality signals the model uses:
- `source_freshness`: fresh/aging/stale (affects market signal weight)
- `missing_fields`: listed fields get confidence penalty
- `conflicts`: conflicting sources suppress fragile picks
- Market `timestamp`: stale lines trigger suppression warnings
