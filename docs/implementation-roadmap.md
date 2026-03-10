# Implementation Roadmap (Priority Order)

## Single Biggest Risk
Without strict data quality gating, the model will issue confident picks on weak inputs.

## Phase 1, Contracts and Determinism
- Deliverables:
  1. Tour weight config.
  2. Risk policy config.
  3. Event packet schema.
  4. Event output and audit templates.
- Acceptance criteria:
  - `scripts/validate_event_packet.py` rejects stale lines and missing critical fields.
  - Output sections always present in deterministic order.

## Phase 2, Scoring and Routing
- Deliverables:
  1. Tour router selecting weight profile by event tour and format.
  2. Player score combiner with explicit component contributions.
  3. Cross-tour translation penalty module.
- Acceptance criteria:
  - Every score has component-level attribution.
  - LIV, DPWT, majors do not share identical weighting.

## Phase 3, Market Edge and Card Construction
- Deliverables:
  1. Implied probability conversion + vig-aware normalization.
  2. Fair-probability calculator and edge computation.
  3. Stake tier mapping and correlated exposure checks.
- Acceptance criteria:
  - No pick emitted without min acceptable and no-play thresholds.
  - Suppression triggers produce explicit pass reasons.

## Phase 4, Post-Event Audit Loop
- Deliverables:
  1. Pick grading pipeline.
  2. CLV tracker.
  3. Bias/failure taxonomy counters and weekly report.
- Acceptance criteria:
  - Every event generates an audit file.
  - Weight-change proposals link to documented failure tags.

## Phase 5, Calibration and Drift Controls
- Deliverables:
  1. Confidence calibration checks.
  2. Tour-level drift dashboards.
  3. Guardrail auto-tightening rules when calibration degrades.
- Acceptance criteria:
  - Confidence bins are empirically tracked.
  - Overconfidence triggers automatic confidence cap reductions.
