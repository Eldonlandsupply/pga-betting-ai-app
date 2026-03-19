# PGA Betting AI — Professional Golf Betting Intelligence System

> A statistically advanced, self-improving weekly betting intelligence engine for PGA Tour and LIV Golf.

---

## What This Is

This is not a picks app. This is a professional-grade golf betting intelligence system that:

- Ingests and normalizes PGA + LIV event data weekly
- Models player performance across 10 statistical + contextual signal families
- Generates a weekly betting card with full edge transparency
- Tracks all picks, outcomes, and return on investment
- Runs adversarial post-event audits after every tournament
- Updates its own weights, flags, and heuristics based on accumulated evidence
- Improves itself week over week without overfitting or becoming unstable

---

## Core Design Principles

1. **Audit first.** No assumption of existing logic being correct.
2. **Model quality over dashboards.** Edge detection is the product.
3. **Do not trust sportsbook odds as truth.** They are pricing signals, not ground truth.
4. **Never overfit small-sample narratives.** Require evidence before weight changes.
5. **Never rely on one stat family.** Multi-signal modeling only.
6. **Treat PGA and LIV as different ecosystems.** Different distributions, markets, and data depth.
7. **Recent form never fully overrides long-term talent.** Balance both.
8. **Long-term baselines must respect recent swing changes and injuries.**
9. **Every model decision must be traceable.** No black boxes.
10. **Every pick must be explainable in plain English.**

---

## Repository Structure

```
pga-betting-ai/
├── README.md
├── CHANGELOG.md
├── configs/
│   ├── model_weights.yaml         # Tunable signal weights per market type
│   ├── course_profiles.yaml       # Course intelligence database
│   ├── data_sources.yaml          # API keys, endpoints, scraper configs
│   ├── staking.yaml               # Edge tier → stake sizing rules
│   └── kill_switches.yaml         # Sub-model degradation thresholds
├── data/
│   ├── raw/                       # Unprocessed ingested data
│   ├── processed/                 # Normalized, validated, joined datasets
│   └── historical/                # All past event artifacts
├── ingest/
│   ├── schedule_ingest.py         # Weekly PGA + LIV schedule detection
│   ├── field_ingest.py            # Player entries, WDs, alternates
│   ├── stats_ingest.py            # SG, driving, approach, putting stats
│   ├── market_ingest.py           # Sportsbook line ingestion + normalization
│   ├── weather_ingest.py          # Weather window ingestion
│   └── results_ingest.py          # Post-event score/result ingestion
├── features/
│   ├── player_baseline.py         # Long-term skill baseline construction
│   ├── recent_form.py             # Rolling form windows + decay
│   ├── course_fit.py              # Course-to-player fit scoring
│   ├── volatility.py              # Ceiling/floor/consistency profiling
│   ├── market_signals.py          # Implied probability, CLV, movement
│   ├── format_adjustments.py      # PGA vs LIV format factors
│   ├── contextual_flags.py        # Injury, rust, travel, pressure flags
│   └── feature_registry.py       # Central feature catalog + versioning
├── models/
│   ├── baseline/
│   │   └── skill_model.py         # Long-term weighted skill estimate
│   ├── form/
│   │   └── form_model.py          # Decayed recent form model
│   ├── course_fit/
│   │   └── fit_model.py           # Course demand vs player skill match
│   ├── simulation/
│   │   └── monte_carlo.py         # Tournament simulation engine
│   ├── market/
│   │   └── edge_calculator.py     # Model prob vs implied prob edge
│   └── ensemble.py                # Final ensemble scorer + confidence
├── simulations/
│   ├── run_simulation.py          # Main simulation runner
│   ├── finish_distributions.py    # Per-player finish prob distributions
│   └── uncertainty.py            # Confidence interval estimation
├── markets/
│   ├── line_tracker.py            # Opening / current / best line tracking
│   ├── movement_detector.py       # Significant line move detection
│   ├── hold_calculator.py         # Vig and hold-adjusted probability
│   └── stale_line_detector.py     # Flag broken/stale market lines
├── picks/
│   ├── picks_engine.py            # Weekly pick generation
│   ├── card_builder.py            # Safe / value / upside / longshot cards
│   ├── avoid_engine.py            # Overvalued / trap bet detection
│   ├── adversarial_review.py      # Self-challenge engine
│   └── stake_sizer.py             # Kelly-adjusted stake recommendations
├── backtests/
│   ├── backtest_runner.py         # Historical simulation vs market
│   ├── roi_tracker.py             # ROI, hit rate, CLV tracking
│   ├── calibration.py             # Model probability calibration checks
│   ├── benchmark_compare.py       # Compare vs naive strategies
│   └── signal_attribution.py     # Which signals drove edge
├── audit/
│   ├── post_event_audit.py        # Full post-event grading + analysis
│   ├── miss_reporter.py           # "What We Missed" weekly report
│   ├── weight_updater.py          # Evidence-gated weight adjustment
│   ├── pattern_detector.py        # Cross-week failure pattern detection
│   └── model_changelog.py         # Immutable audit log of all changes
├── reports/
│   ├── weekly_card_report.py      # Concise betting card output
│   ├── analyst_report.py          # Full deep-dive analyst report
│   ├── course_profile_report.py   # Course intelligence summary
│   └── post_event_report.py       # Post-event audit report
├── ui/
│   ├── app.py                     # Main Streamlit/FastAPI app entry
│   ├── dashboard/
│   │   ├── event_dashboard.py     # Current event overview
│   │   ├── value_board.py         # Edge board by bet type
│   │   ├── line_movement.py       # Live line movement tracker
│   │   ├── audit_dashboard.py     # Post-event audit view
│   │   └── roi_dashboard.py       # Historical ROI + calibration
│   └── components/
│       ├── player_card.py         # Individual player deep-dive card
│       ├── bet_card.py            # Pick with full supporting context
│       └── avoid_card.py          # Trap/avoid flagged bets
├── docs/
│   ├── setup.md
│   ├── data_sources.md
│   ├── schema.md
│   ├── model_logic.md
│   ├── audit_logic.md
│   ├── backtesting.md
│   ├── self_improvement_loop.md
│   ├── pga_vs_liv_modeling.md
│   ├── limitations.md
│   └── roadmap.md
└── tests/
    ├── test_ingest.py
    ├── test_features.py
    ├── test_models.py
    ├── test_simulation.py
    ├── test_markets.py
    ├── test_picks.py
    └── test_audit.py
```

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
cp configs/data_sources.yaml.example configs/data_sources.yaml
# Edit with your DataGolf, The Odds API, Sportradar keys

# 3. Run weekly pipeline (auto-detects current event)
python run_weekly.py

# 4. Launch UI
streamlit run ui/app.py
```

---

## Weekly Workflow

```
Monday/Tuesday   → Detect event, ingest field, pull opening lines
Wednesday        → Run models, generate preliminary picks
Thursday AM      → Final picks card published, stakes logged
Thursday-Sunday  → Track live market movement
Post-event       → Ingest results, run audit, update weights
```

---

## Bet Categories Covered

| Category | PGA | LIV |
|---|---|---|
| Outrights (Win) | ✅ | ✅ |
| Top 5 / Top 10 / Top 20 | ✅ | ✅ |
| Head-to-Head Matchups | ✅ | ✅ |
| Make/Miss Cut | ✅ | N/A (no cut) |
| First Round Leader | ✅ | ✅ |
| Placement Props | ✅ | ✅ |
| Longshot Value | ✅ | ✅ |
| Group/Nationality Markets | Where available | Where available |

---

## Model Signal Families

1. Long-term skill baseline (SG composite, multi-year)
2. Recent form (decayed rolling windows)
3. Course + surface fit
4. Statistical fit to course demands
5. Field strength adjustment
6. Volatility / ceiling / consistency profile
7. Market pricing efficiency gap
8. Contextual / psychological adjustment
9. Format adjustment (PGA vs LIV)
10. Ownership proxy / market crowding

---

## Self-Improvement Loop

Every week after an event:
- All picks graded (win/loss/push/partial/void)
- Expected value vs actual outcome compared
- Directional accuracy separated from result variance
- Structural model errors identified
- Repeated failure patterns flagged across weeks
- Weights updated only when evidence threshold is met
- Full changelog entry written
- "What We Missed" report published

---

## Backtesting Benchmarks

The system is compared weekly against:
- Market close (closing line value)
- Naive favorites strategy
- World Ranking-based strategy
- Recent form-only strategy

---

## License

Private — internal use only.
