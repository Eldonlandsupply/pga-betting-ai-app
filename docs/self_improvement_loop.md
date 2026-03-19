# Self-Improvement Loop

The system improves itself week over week through a structured evidence-gated feedback cycle.

---

## The Loop in Full

```
Event Week
   │
   ├── Monday/Tuesday
   │     ingest field, stats, opening markets
   │     build features (6 signal families)
   │     run ensemble + simulation
   │     generate raw picks
   │     run adversarial review → kill/downgrade weak picks
   │     publish betting card + analyst report
   │
   ├── Thursday AM
   │     final card published
   │     stakes logged to picks/logs/{event_id}_picks.json
   │
   ├── During Event
   │     track line movement
   │     flag CLV divergences
   │
   └── Post-Event (Sunday/Monday)
         ingest results
         ↓
         post_event_audit.py
         ├── Grade every pick (win/loss/push/partial/void)
         ├── Compute ROI, hit rate, CLV
         ├── Separate model-right from model-wrong outcomes
         ├── Classify failure causes (taxonomy)
         ├── Check cross-week patterns (last 8 events)
         ├── Generate "What We Missed" report
         └── → recommendations to weight_updater.py
               ↓
               weight_updater.py
               ├── Check evidence gates
               │     min 6 events with pattern
               │     min 40 picks per signal
               │     dual-direction evidence required
               │     max Δ0.03 per cycle
               │     max cumulative drift 0.15 from default
               ├── Apply changes if gates met
               ├── Write CHANGELOG.md entry
               └── → repeat next week
```

---

## Evidence Gates — Why They Exist

Golf is a high-variance sport. One bad week can be pure noise.
Changing weights after a single event creates an overfit, reactive system
that chases its own tail and degrades over time.

The gates enforce discipline:

| Gate | Value | Rationale |
|---|---|---|
| Minimum events with pattern | 6 | Single-event reaction is noise |
| Minimum picks per weight | 40 | Small sample is not statistical evidence |
| Dual-direction evidence | Required | Must see both success and failure directions |
| Max single-cycle change | ±0.03 | Prevents violent weight swings |
| Max cumulative drift | ±0.15 | Prevents slow drift away from calibrated defaults |
| Changelog required | Always | Every change is traceable and reversible |

---

## What the Audit Detects

### Structural Model Errors
Situations where the model was predictably wrong, not just unlucky:
- `underweighted_recent_approach_surge` — ignoring a genuine SG Approach breakout
- `overweighted_stale_putting_baseline` — trusting outdated putting averages
- `missed_course_fit_penalty` — not penalizing poor course-fit archetypes
- `missed_sharp_line_movement_signal` — sharp money moved; we didn't follow

### Variance Losses (Not Model Errors)
Situations where model was right but the outcome was a normal probability miss:
- Flagged as `right_wrong` in the directional breakdown
- These do NOT trigger weight changes
- These ARE counted in calibration tracking

### Dangerous Accidental Successes
Situations where the model was wrong but got lucky:
- Flagged as `wrong_right`
- Particularly dangerous because they can create false confidence
- Tracked separately and investigated if pattern persists

---

## What Changes When Gates Are Met

| Pattern | Target | Change |
|---|---|---|
| Repeated approach surge misses | `sg_default_weights.sg_app` | +0.01 to +0.02 |
| Repeated stale putting overweight | Form decay half-life | Reduce by 10–15% |
| Sharp signal misses | `market_signal_weights.sharp_book_vs_public_delta` | +0.02 to +0.03 |
| LIV volatility underestimate | `liv_adjustments.data_depth_penalty` | +0.01 to +0.02 |
| Course fit misses | `course_fit_weights.comp_course_history` | +0.02 to +0.03 |
| Bankroll drawdown trigger | Staking config | Immediate 50% stake reduction |

---

## What Never Changes Automatically

- Core architecture (SG families, simulation structure)
- Maximum exposure limits (require manual review)
- Kill switch thresholds (require manual review)
- Tour classification logic
- Course profile database (edited manually as new data arrives)

---

## Reversibility

Every change is documented in CHANGELOG.md with:
- Exact field changed
- Old value → new value
- Delta
- Evidence basis
- Event that triggered it

To revert to any previous state: scan CHANGELOG.md for the relevant entry
and manually restore the values in model_weights.yaml.

---

## Failure Pattern Taxonomy

The `_classify_failure_cause()` function in post_event_audit.py assigns
every losing pick to one of these categories:

```
underweighted_recent_approach_surge
overweighted_stale_putting_baseline
mispriced_wind_specialist
missed_course_fit_penalty
underestimated_liv_volatility
overrated_big_name_reputation
failed_fade_on_poor_comp_course_fit
missed_sharp_line_movement_signal
injury_flag_not_captured
overfit_recent_hot_streak
small_field_effect_not_modeled
format_adjustment_insufficient
data_thin_player_mispriced
correlated_bets_double_counted
market_had_significant_edge_we_missed
other
```

---

## Calibration Tracking

Separate from weight updates, the system tracks probability calibration weekly:

| Bucket | Predicted Win% | Actual Win% | Status |
|---|---|---|---|
| 0–10% | — | — | — |
| 10–20% | — | — | — |
| 20–35% | — | — | — |
| 35–50% | — | — | — |
| 50%+ | — | — | — |

A calibration bucket with >5% error for 3+ consecutive weeks
triggers an `overfit_guard` kill switch review.

---

## "What We Missed" Report

Generated after every event in `audit/post_event_audit.py`.

Captures:
1. Top finishers we did not bet (with investigation prompts)
2. Structural failures with cause codes
3. Cross-week pattern alerts
4. Questions the analyst should answer before next week's picks
5. Model adjustment candidates (pending gate review)

This report is the primary mechanism for human-in-the-loop review.
The system identifies patterns; the analyst decides whether to apply them.
