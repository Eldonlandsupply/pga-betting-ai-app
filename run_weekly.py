"""
run_weekly.py
-------------
Main entry point for the PGA Betting AI weekly pipeline.

Runs in order:
  1. Detect current event
  2. Ingest field, stats, weather, and market data
  3. Build features for all players in field
  4. Run ensemble model
  5. Run tournament simulation
  6. Generate picks card
  7. Run adversarial review
  8. Publish reports
  9. (Post-event) Ingest results and run audit

Usage:
    python run_weekly.py --mode pre_event     # Monday–Wednesday flow
    python run_weekly.py --mode final         # Thursday final card
    python run_weekly.py --mode post_event    # After event completion
    python run_weekly.py --mode audit_only    # Audit without re-running model
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Internal imports
from ingest.schedule_ingest import detect_current_event, get_upcoming_events
from ingest.field_ingest import ingest_field
from ingest.stats_ingest import ingest_player_stats
from ingest.market_ingest import ingest_markets
from ingest.weather_ingest import ingest_weather
from ingest.results_ingest import ingest_results
from features.player_baseline import build_baselines
from features.recent_form import build_form_features
from features.course_fit import build_course_fit_features
from features.volatility import build_volatility_profiles
from features.market_signals import build_market_signals
from features.contextual_flags import build_contextual_flags
from models.ensemble import run_ensemble
from simulations.run_simulation import run_tournament_simulation
from picks.picks_engine import generate_picks
from picks.card_builder import build_betting_card
from picks.adversarial_review import run_adversarial_review
from audit.post_event_audit import run_post_event_audit
from audit.weight_updater import check_and_update_weights
from reports.weekly_card_report import publish_weekly_card
from reports.analyst_report import publish_analyst_report
from reports.post_event_report import publish_post_event_report

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"logs/pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
    ],
)
log = logging.getLogger("run_weekly")


def run_pre_event_pipeline(event_id: str, dry_run: bool = False):
    """
    Runs the full pre-event data ingestion, modeling, and preliminary
    pick generation pipeline.
    """
    log.info(f"=== PRE-EVENT PIPELINE | Event: {event_id} ===")

    # --- STEP 1: FIELD INGESTION ---
    log.info("Step 1/9: Ingesting field data...")
    field = ingest_field(event_id)
    log.info(f"  → {len(field)} players in field")

    # --- STEP 2: STATS INGESTION ---
    log.info("Step 2/9: Ingesting player stats...")
    stats = ingest_player_stats(player_ids=[p["id"] for p in field])
    log.info(f"  → Stats loaded for {len(stats)} players")

    # --- STEP 3: MARKET INGESTION ---
    log.info("Step 3/9: Ingesting sportsbook markets...")
    markets = ingest_markets(event_id)
    log.info(f"  → {len(markets.get('outrights', {}))} outright prices ingested")

    # --- STEP 4: WEATHER INGESTION ---
    log.info("Step 4/9: Ingesting weather data...")
    weather = ingest_weather(event_id)

    # --- STEP 5: FEATURE BUILDING ---
    log.info("Step 5/9: Building feature set...")
    features = {}
    features["baseline"] = build_baselines(field, stats)
    features["form"] = build_form_features(field, stats)
    features["course_fit"] = build_course_fit_features(event_id, field, stats)
    features["volatility"] = build_volatility_profiles(field, stats)
    features["market_signals"] = build_market_signals(field, markets)
    features["contextual"] = build_contextual_flags(field)
    log.info(f"  → Features built for {len(field)} players across 6 signal families")

    # --- STEP 6: ENSEMBLE MODEL ---
    log.info("Step 6/9: Running ensemble model...")
    model_outputs = run_ensemble(event_id, features)

    # --- STEP 7: SIMULATION ---
    log.info("Step 7/9: Running tournament simulation (10,000 trials)...")
    sim_results = run_tournament_simulation(event_id, model_outputs, n_simulations=10000)

    # --- STEP 8: PICKS GENERATION ---
    log.info("Step 8/9: Generating picks card...")
    raw_picks = generate_picks(event_id, model_outputs, sim_results, markets)
    card = build_betting_card(raw_picks)

    # --- STEP 9: ADVERSARIAL REVIEW ---
    log.info("Step 9/9: Running adversarial self-review...")
    reviewed_card = run_adversarial_review(card, model_outputs, markets)

    # --- PUBLISH REPORTS ---
    if not dry_run:
        publish_weekly_card(event_id, reviewed_card)
        publish_analyst_report(event_id, reviewed_card, model_outputs, sim_results, features)
        log.info("Reports published.")
    else:
        log.info("[DRY RUN] Reports not published.")

    log.info("=== PRE-EVENT PIPELINE COMPLETE ===")
    return reviewed_card


def run_post_event_pipeline(event_id: str):
    """
    Runs after event completion:
    - Ingests results
    - Grades all picks
    - Runs post-event audit
    - Updates model weights if evidence threshold met
    """
    log.info(f"=== POST-EVENT PIPELINE | Event: {event_id} ===")

    # --- INGEST RESULTS ---
    log.info("Ingesting event results...")
    results = ingest_results(event_id)

    # --- RUN AUDIT ---
    log.info("Running post-event audit...")
    audit_output = run_post_event_audit(event_id, results)

    # --- UPDATE WEIGHTS ---
    log.info("Checking weight update gates...")
    weight_changes = check_and_update_weights(audit_output)
    if weight_changes:
        log.info(f"  → {len(weight_changes)} weight adjustments applied")
    else:
        log.info("  → No weight changes warranted (insufficient evidence)")

    # --- PUBLISH REPORT ---
    publish_post_event_report(event_id, audit_output, weight_changes)

    log.info("=== POST-EVENT PIPELINE COMPLETE ===")
    return audit_output


def main():
    parser = argparse.ArgumentParser(description="PGA Betting AI — Weekly Pipeline")
    parser.add_argument(
        "--mode",
        choices=["pre_event", "final", "post_event", "audit_only"],
        default="pre_event",
        help="Pipeline mode to run",
    )
    parser.add_argument("--event_id", type=str, default=None, help="Override event ID (auto-detected if not set)")
    parser.add_argument("--dry_run", action="store_true", help="Run without publishing reports")
    args = parser.parse_args()

    # Auto-detect event if not specified
    event_id = args.event_id
    if not event_id:
        event = detect_current_event()
        if not event:
            log.error("No current or upcoming event detected. Check schedule ingest.")
            sys.exit(1)
        event_id = event["event_id"]
        log.info(f"Auto-detected event: {event['display_name']} (ID: {event_id})")

    if args.mode in ("pre_event", "final"):
        run_pre_event_pipeline(event_id, dry_run=args.dry_run)

    elif args.mode == "post_event":
        run_post_event_pipeline(event_id)

    elif args.mode == "audit_only":
        results = ingest_results(event_id)
        audit_output = run_post_event_audit(event_id, results)
        publish_post_event_report(event_id, audit_output, weight_changes=None)


if __name__ == "__main__":
    main()
