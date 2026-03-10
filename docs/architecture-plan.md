# Golf Betting Intelligence Architecture Plan

## Most Important System Risk
The system can produce false confidence from sparse or stale tour data, especially LIV and DP World events where public stat coverage is incomplete.

## Design Principles
1. Truth-first, edge-second.
2. No recommendation without explicit price discipline.
3. Tour-native logic, no blind cross-tour stat portability.
4. Confidence is reduced by missingness and source conflicts.
5. No-bet is a valid outcome.

## Core Layers

### 1) Data Ingestion Layer
- Inputs:
  - event metadata (tour, format, course, field)
  - player form and long-term skill stats
  - market prices by bet type and sportsbook
  - weather and travel proxies where available
- Requirements:
  - strict schema validation
  - source timestamps and freshness tags
  - source authority score per feed
  - conflict detection, not averaging by default

### 2) Tour Router Layer
- Routes events to one of:
  - `pga`
  - `liv`
  - `dpwt`
  - `majors`
  - `opposite_field`
- Applies tour-specific weights, volatility assumptions, and data-coverage penalties.

### 3) Player Rating Engine
Composite score components:
- baseline long-term skill
- medium-term form
- short-term trend
- field-strength-adjusted finishing quality
- course-fit score from demand clusters
- cut reliability (cut events only)
- no-cut volatility control (LIV + select events)
- travel and timezone burden penalty
- injury and WD risk penalty
- uncertainty penalty from data quality

Regress aggressively:
- putting spikes
- one-off finishes
- weak-field inflation
- tiny-sample course history

### 4) Course Fit Engine
Event profile vectors:
- yardage, par, altitude
- rough severity, fairway width, hazard density
- wind exposure, links factor
- green type, firmness, and size when available

Demand clusters:
- bomber advantage
- second-shot iron test
- wedge-heavy birdie fest
- links/wind control
- scrambling grind
- long-iron major stress

### 5) Market Edge Engine
For every market candidate:
- model fair probability
- implied market probability
- edge percent
- confidence score
- min acceptable price
- no-play threshold
- invalidation triggers

Suppression rules:
- edge below minimum threshold
- confidence below threshold
- high data conflict flag
- stale line timestamps

### 6) Recommendation Assembly Layer
Outputs deterministic event package:
1. event snapshot
2. ranked edges
3. outright values
4. placement bets
5. matchups
6. high-upside/high-variance plays
7. passes/traps
8. tour-specific risk flags
9. data quality warnings
10. final card
11. price discipline table
12. post-event audit template

### 7) Post-Event Audit Loop
For each pick:
- result grading (win/loss/push)
- CLV win/loss
- model quality grade
- root-cause tag:
  - variance-only loss
  - handicap error
  - data quality miss
  - tour translation miss
  - weather miss
- update weights and guardrail counters
- store lessons artifact

## Trust Controls
- Missing data marked `MISSING`, never imputed silently.
- Contradictory sources trigger suppression or priority-rule resolution.
- Recommendation confidence includes uncertainty decomposition.
- Every pick includes failure modes and invalidation conditions.
- Event-level exposure limits and correlated-risk warnings required.

## Recommended Module Layout
- `config/tour_weights.yaml`: tour-specific model weights and penalties
- `config/risk_policy.yaml`: stake tiers, exposure limits, suppression thresholds
- `schemas/*.schema.json`: strict input and output contracts
- `templates/event_output_template.md`: deterministic output for ChatGPT/Claude
- `templates/post_event_audit_template.md`: mandatory audit artifact
- `scripts/validate_event_packet.py`: schema + business-rule checker
- `tests/test_validate_event_packet.py`: smoke tests for deterministic checks

## Priority Roadmap
1. Establish schemas and config contracts.
2. Build deterministic output templates.
3. Implement validation and suppression guardrails.
4. Add tour-specific scoring config and translator penalties.
5. Add post-event audit ingestion and weight-update scaffolding.
6. Integrate bookmaker line freshness and CLV tracking.
7. Add confidence calibration metrics over rolling windows.
