# Event Packet Guide

How to build `event_packet.json` files for any PGA, LIV, DPWT, or Major event.

---

## Overview

An event packet is the structured input that drives the entire analysis pipeline.
The validator (`scripts/validate_event_packet.py`) enforces the contract.
The scanner (`scripts/run_scan.py`) sends it to the LLM with analysis instructions.

**Rule: garbage in, garbage out.** The better your packet, the better your picks.

---

## Required Top-Level Keys

```
event           object    tournament metadata
data_quality    object    freshness and missing field flags
markets         array     current betting lines with timestamps
recommendations array     your pre-formed picks (or empty array [])
```

---

## 1. `event` object

```json
{
  "tournament": "2026 Masters Tournament",
  "tour": "majors",
  "course": "Augusta National Golf Club",
  "format": "72-hole stroke play, cut after 36 holes"
}
```

`tour` must be one of: `pga`, `liv`, `dpwt`, `majors`, `opposite_field`

Optional but useful fields:
```json
{
  "location": "Augusta, Georgia",
  "dates": "2026-04-09 to 2026-04-12",
  "purse_usd": 20000000,
  "field_size": 88,
  "notes": "Any course or context notes"
}
```

---

## 2. `data_quality` object

```json
{
  "source_freshness": "fresh",
  "missing_fields": [],
  "conflicts": []
}
```

`source_freshness` must be: `fresh`, `aging`, or `stale`

- `fresh` = odds and stats under 2 hours old
- `aging` = 2–12 hours old
- `stale` = over 12 hours old

`missing_fields`: list any fields you couldn't find. Examples:
```json
"missing_fields": [
  "players.strokes_gained_detail",
  "weather.wind_forecast",
  "players.injury_status"
]
```

`conflicts`: list any data disagreements between sources:
```json
"conflicts": ["player_status_feed_disagree", "odds_source_spread_wide"]
```

**Important:** If `missing_fields` is non-empty, the validator warns to downgrade confidence.
If `conflicts` is non-empty, the validator warns to suppress fragile picks.

---

## 3. `markets` array

Each entry is one betting line from one sportsbook:

```json
{
  "bet_type": "outright",
  "player": "Scottie Scheffler",
  "sportsbook": "FanDuel",
  "odds_decimal": 5.80,
  "timestamp": "2026-04-08T14:00:00+00:00"
}
```

**Critical:** `timestamp` must be a valid ISO 8601 datetime with timezone.
Lines older than 30 minutes will trigger a stale warning (configurable via `PGA_STALE_LINE_MINUTES`).

`bet_type` can be anything descriptive:
- `outright` — win only
- `top_5`, `top_10`, `top_20` — placement bets
- `matchup` — head-to-head
- `make_cut` / `miss_cut`
- `frl` — first round leader

**Convert American odds to decimal:**
- Positive: decimal = (american / 100) + 1 → +350 = 4.50
- Negative: decimal = (100 / abs(american)) + 1 → -200 = 1.50

At minimum, include outrights for your top candidates plus any placement bets.

---

## 4. `recommendations` array

This is where you provide your pre-formed picks OR leave it as `[]` and let the LLM generate them from the packet.

If you provide picks, each must have all required fields:

```json
{
  "rank": 1,
  "bet_type": "top_10",
  "player": "Collin Morikawa",
  "implied_probability": 0.053,
  "fair_probability": 0.075,
  "edge_percent": 4.2,
  "confidence": 0.64,
  "min_acceptable_odds": 17.00,
  "no_play_below_odds": 15.00,
  "reasoning": "Why this bet has edge.",
  "invalidation_conditions": [
    "Condition that would make this bet wrong"
  ]
}
```

**Computing implied probability from decimal odds:**
```
implied = 1 / odds_decimal
Example: 1 / 19.00 = 0.0526
```

**Computing edge:**
```
edge_percent = (fair_probability - implied_probability) * 100
Example: (0.075 - 0.0526) * 100 = 2.24%
```

**Confidence** is your subjective conviction in the fair probability estimate (0–1).
Lower it when data is sparse, injury status is uncertain, or this is a tour translation.

**Rule from risk_policy.yaml:**
- `outright`: min edge 2.5%, min confidence 0.55
- `placement`: min edge 2.0%, min confidence 0.58
- `matchup`: min edge 1.5%, min confidence 0.60

---

## 5. Optional but strongly recommended fields

### Players section (for richer LLM analysis)

```json
"players": [
  {
    "name": "Scottie Scheffler",
    "world_ranking": 1,
    "form_notes": "Recent results and SG stats narrative",
    "course_history": "History at this specific course",
    "injury_status": "healthy",
    "long_term_skill": 0.96
  }
]
```

`long_term_skill` is a 0–1 score representing career-level ability relative to field.
Rough guide: World top-5 = 0.90+, top-20 = 0.80–0.89, top-50 = 0.70–0.79

### Risk flags

```json
"risk_flags": [
  "McIlroy injury status uncertain",
  "Weather forecast shows 25mph winds Thursday"
]
```

### Passes and traps

```json
"passes_and_traps": [
  {
    "player": "Scottie Scheffler",
    "bet_type": "outright",
    "verdict": "PASS",
    "reason": "Too short at current odds given recent form"
  }
]
```

---

## Quick Template

Copy this and fill in for any event:

```json
{
  "event": {
    "tournament": "EVENT NAME",
    "tour": "pga",
    "course": "COURSE NAME",
    "format": "72-hole stroke play, cut after 36 holes"
  },
  "data_quality": {
    "source_freshness": "fresh",
    "missing_fields": [],
    "conflicts": []
  },
  "markets": [
    {
      "bet_type": "outright",
      "player": "PLAYER NAME",
      "sportsbook": "FanDuel",
      "odds_decimal": 10.00,
      "timestamp": "2026-01-01T12:00:00+00:00"
    }
  ],
  "recommendations": []
}
```

With `recommendations: []`, the LLM will generate picks purely from the event and market data you provide.

---

## Validate before running

Always validate first:

```bash
python scripts/validate_event_packet.py input/current_event.json
```

`PASS` = ready to scan. Any `ERROR` = fix before running.
Stale timestamp warnings are expected if you built the packet earlier in the day — they don't block execution in `run_scan.py`.

---

## Data sources to build packets

| Data type | Free source | Paid source |
|---|---|---|
| Odds | ESPN, CBS Sports, Golf.com | The Odds API |
| Player form / SG | PGA Tour stats page | DataGolf API |
| Course history | PGA Tour stats, Wikipedia | DataGolf |
| World rankings | OWGR.com | — |
| Weather | Weather.gov, Windy.com | — |
| Field | PGA Tour website | — |
