# CHANGELOG — PGA Betting AI Model

All model weight changes, logic updates, and system improvements are recorded here.
This is an append-only log. Never delete entries.

Format per entry:
- Date + Event trigger
- What changed and why
- Evidence basis
- Magnitude of change
- Reversibility note

---

## [2025-01-01] — Initial Configuration

- **Event**: System initialization
- **Change**: All weights set to research-based defaults
- **Evidence**: Pre-season configuration based on DataGolf research, academic literature, and market analysis
- **Affected**: All global weights in `configs/model_weights.yaml`
- **Reversible**: Yes — delete all subsequent entries to restore this state

### Initial weight rationale:

**global_weights.skill_baseline = 0.30**
Long-term skill is the most predictive single signal in golf betting.
Sources: DataGolf research, academic literature on SG predictability.

**global_weights.recent_form = 0.22**
Recent form adds genuine signal but is noisier than baseline.
Capped below skill to prevent overreaction to hot streaks.

**global_weights.course_fit = 0.20**
Course fit is the most actionable weekly edge.
Strong evidence from historical win/placement correlation with fit scores.

**global_weights.market_signal = 0.10**
Markets contain real information. Sharp money is informative.
Not the primary signal — a secondary validation/adjustment layer.

**sg_default_weights.sg_app = 0.32 (highest)**
Approach game is the most consistent and predictable SG category.
Source: Multiple DataGolf analyses showing sg_app as highest R² predictor.

**sg_default_weights.sg_ott = 0.24**
Driving is highly venue-dependent but generally important.
Weighted equally to putting at default; course overrides handle venue specifics.

**form_decay.event_1 = 0.28**
Most recent event gets largest single-event weight.
Balanced to prevent overreaction to one outlier result.

---
<!-- Future entries appended below this line by weight_updater.py -->
