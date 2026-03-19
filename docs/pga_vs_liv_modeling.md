# PGA vs LIV Modeling Differences

## Overview

The PGA Tour and LIV Golf are fundamentally different competitive ecosystems.
Treating them identically is a modeling error that will cost you money.

This document explains every significant difference the system accounts for,
why those differences matter for betting, and how the model handles each one.

---

## 1. Field Size and Finish Distribution

| | PGA Tour | LIV Golf |
|---|---|---|
| Typical field size | 120–156 players | 48 players |
| Standard field | 132 | 48 |
| Signature event field | 70–80 | N/A |
| Majors | 156 | N/A |

**Why this matters for betting:**
- Top 10 probability for a +1000 player in a 156-man field is ~5–8%.
- Top 10 probability for the same player in a 48-man LIV field is ~18–22%.
- Sportsbooks sometimes misprice LIV placements using PGA-style distributions.
- Our simulation uses field-size-adjusted distributions for all finish probabilities.

**Model adjustment:**
```yaml
liv_adjustments:
  field_size_factor: 0.90  # Reduces baseline "difficulty" of achieving placements
```

---

## 2. Cut Line vs No-Cut Structure

**PGA Tour:**
- Standard events: Top 70 + ties make the cut after Round 2
- No-cut events: ~10 per season (small subset)
- Alternate field events: Smaller fields, weaker competition

**LIV Golf:**
- ALL events are no-cut
- All 48 players complete 54 holes

**Why this matters for betting:**
- Make/miss cut markets are PGA-only
- LIV placements (top 5, top 10, top 20) are much more "playable" because
  there is no elimination risk in the final round
- Variance in LIV is compressed in terms of availability but distributed
  differently across rounds
- Model does not offer make/miss cut bets for LIV events

**Model adjustment:**
- `apply_cut` flag in simulation is always `False` for LIV
- Separate finish distribution calibration curves for LIV vs PGA

---

## 3. Scoring Rounds

| | PGA Tour | LIV Golf |
|---|---|---|
| Rounds | 72 holes (4 rounds) | 54 holes (3 rounds) |
| Variance accumulation | 4 rounds × ~3 strokes per round variance | 3 rounds × same |
| Winner's score range | -10 to -25 typical | -8 to -20 typical |

**Why this matters for betting:**
- 54-hole events have meaningfully less variance reduction compared to 72-hole
- "Hot putter for a week" effect is stronger in LIV (fewer rounds to regress)
- First Round Leader bets in LIV carry proportionally higher value
  because the leader is closer to the finish
- Long-term talent advantage is compressed in 54-hole format

**Model adjustment:**
```python
LIV_ROUNDS = 3  # vs PGA_ROUNDS = 4
# Volatility is scaled accordingly in simulation
```

---

## 4. Data Depth and Quality

| | PGA Tour | LIV Golf |
|---|---|---|
| Strokes Gained data | Comprehensive, multi-year | Limited / inconsistently published |
| Historical rounds available | Thousands per top player | Dozens per player |
| Public statistics depth | High (DataGolf, PGA Tour ShotLink) | Low (proprietary or absent) |
| Course history | 20–50 events per common venue | 2–4 events per venue (tour is young) |

**Why this matters for betting:**
- LIV model outputs have inherently wider confidence bands
- "Thin data" flags are common for LIV players
- Recent PGA stats for LIV players must be used with a transfer discount
  (different competition level, different course mix, different mental context)
- Market efficiency is lower for LIV because public data is thin — this creates
  more value opportunities, but also more model uncertainty

**Model adjustment:**
```yaml
liv_adjustments:
  data_depth_penalty: 0.15
  pga_stat_transfer_weight: 0.65
  market_efficiency: 0.70
```

---

## 5. Market Efficiency

**PGA Tour (Signature/Majors):**
- Extremely efficient markets
- Pinnacle and sharp books pricing within 1–2% of "true" probability
- Limited exploitable edges except in niche markets (H2H, placements)

**PGA Tour (Smaller/Alternate Field Events):**
- Moderately efficient
- More bookmaker variance and softer modeling from the public
- Better opportunity for comp-course and course-fit edges

**LIV Golf:**
- Least efficient golf market
- Bookmakers have less data and devote less pricing resource
- Recreational bettors and public narratives move lines
- Model edges are more likely to be real BUT model uncertainty is also higher
- Net effect: treat LIV edges with a confidence discount

**Model adjustment:**
- LIV edges require a slightly higher minimum edge threshold before betting:
  ```yaml
  # Effective minimum edge for LIV = standard threshold + 0.02
  ```

---

## 6. Team Format Overlay (LIV Specific)

LIV uses a concurrent team competition alongside individual scoring.

**Impact:**
- Some players may underperform individually due to team strategy effects
- Some players may perform differently when their team is out of contention
- Team captains may make different risk decisions
- The team scoring system means that certain individual round stats
  (e.g., captain's aggressive birdie chase) may not represent pure
  individual performance

**Model adjustment:**
- `team_overlay: false` by default (minimal current evidence for modeling)
- Flag is available to enable if evidence accumulates

---

## 7. Competition Level Adjustment

The LIV field, while containing elite players, has different competitive depth:
- Top 5–10 players comparable to PGA Tour elite
- Below that: significant drop-off vs PGA Tour depth
- Many LIV players are post-peak or PGA Tour rejects

**Why this matters:**
- SG baselines built purely on LIV data will overstate mid-field player skill
- PGA historical stats need adjustment for field strength when transferring
- A +0.5 SG/round in LIV may not translate to the same rank on PGA Tour

**Model adjustment:**
```yaml
liv_adjustments:
  field_strength_factor: 0.75  # LIV field is ~75% the strength of a PGA Tour field
```

---

## 8. Psychological / Motivational Context

This is the murkiest area. We flag it but do not overweight it.

**Factors that may matter (use cautiously):**
- LIV players who were recently competitive on PGA Tour may maintain
  high motivation at early LIV events
- Players who have been on LIV for 2+ years with declining motivation
  are hard to model
- Players returning to events near their home country may perform
  differently (small, unreliable effect)

**Model policy:**
- Do not include motivation or psychological factors unless supported by
  at least 3 seasons of directional evidence
- Flag where available but do not change stake sizing based on this

---

## 9. Course Overlap and Venue History

**LIV venues:**
- Newer to professional golf (2022+)
- Less historical performance data per player per venue
- Some LIV venues do host PGA Tour events on the same course — 
  this data IS used with a recency and format discount

**Model adjustment:**
- LIV course history is weighted at `0.70 × PGA_weight` at same venue
- Comp course lookup uses broader criteria for LIV events

---

## 10. Recommended Model Separation

The system maintains **separate** model instances for PGA and LIV:

| Component | PGA | LIV |
|---|---|---|
| Baseline skill model | Full SG suite | Discounted transfer + limited LIV data |
| Form model | Standard 6-8 event window | Shorter window (recency weighted higher) |
| Course fit | Full historical suite | Thin, flag as uncertain |
| Simulation | 72-hole + cut | 54-hole, no cut |
| Market efficiency assumption | High (majors) to medium (standard) | Low |
| Data confidence | High | Moderate to low |
| Stake sizing | Standard | Apply additional uncertainty discount |

---

## Summary Table

| Factor | PGA Impact | LIV Impact |
|---|---|---|
| Field size | 132–156 | 48 |
| Rounds | 4 (72 holes) | 3 (54 holes) |
| Cut exists | Yes (most events) | No |
| Data depth | High | Low |
| Market efficiency | Medium-High | Low |
| Model confidence | High | Moderate |
| Team overlay | None | Possible (minor) |
| Transfer discount | N/A | 0.65× PGA stats |
| Stake adjustment | Standard | -0.15 confidence penalty |
