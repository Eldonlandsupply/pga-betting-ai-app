"""
backtests/backtest_runner.py
-----------------------------
Backtesting framework for the PGA Betting AI system.

Tests model performance against historical events using simulated
pre-event picks based on the model as it would have run at the time.

Key design rules:
- No lookahead bias: features are built from data available at bet time
- Test by tournament, market type, tour, course type, and season
- Compare against benchmark strategies
- Track ROI, hit rate, CLV, and probability calibration
- Identify which signal combinations drove real edges

Benchmark strategies:
1. Naive favorites (bet the top-3 ranked players in every market)
2. World ranking strategy (bet by OWGR)
3. Recent form only (SG last 5 events)
4. Market close (simulate betting closing line — measures skill vs luck)
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

BENCHMARK_STRATEGIES = ["naive_favorites", "world_ranking", "recent_form_only", "market_close"]

HISTORICAL_DATA_PATH = Path("data/historical")
BACKTEST_OUTPUT_PATH = Path("backtests/results")


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run_backtest(
    start_season: int,
    end_season: int,
    tour: str = "all",
    market_types: list[str] | None = None,
    model_version: str = "current",
) -> dict:
    """
    Run full backtesting suite over specified seasons.

    Args:
        start_season: Starting year (e.g., 2022)
        end_season: Ending year (e.g., 2024)
        tour: "PGA", "LIV", or "all"
        market_types: list of market types to test (None = all)
        model_version: model version string for labeling output

    Returns:
        Comprehensive backtest results dict
    """
    log.info(f"=== BACKTEST: {start_season}–{end_season} | Tour: {tour} | Version: {model_version} ===")

    if market_types is None:
        market_types = ["outright", "top_5", "top_10", "top_20", "h2h", "make_cut", "frl"]

    # Load historical events
    events = _load_historical_events(start_season, end_season, tour)
    log.info(f"Loaded {len(events)} historical events for backtesting.")

    if not events:
        log.error("No historical events found. Backtest cannot run.")
        return {"error": "No historical events"}

    # Run model backtest
    model_results = _run_model_backtest(events, market_types)

    # Run benchmarks
    benchmark_results = {}
    for benchmark in BENCHMARK_STRATEGIES:
        benchmark_results[benchmark] = _run_benchmark(events, market_types, benchmark)

    # Compute metrics
    model_metrics = _compute_backtest_metrics(model_results)
    benchmark_metrics = {b: _compute_backtest_metrics(r) for b, r in benchmark_results.items()}

    # Signal attribution
    signal_attribution = _compute_signal_attribution(model_results)

    # Calibration check
    calibration = _check_probability_calibration(model_results)

    # By tournament type
    by_tournament_type = _split_by_tournament_type(model_results)

    # By market type
    by_market_type = _split_by_market_type(model_results)

    output = {
        "backtest_id": f"backtest_{start_season}_{end_season}_{model_version}",
        "run_timestamp": datetime.utcnow().isoformat(),
        "config": {
            "start_season": start_season,
            "end_season": end_season,
            "tour": tour,
            "market_types": market_types,
            "model_version": model_version,
            "n_events": len(events),
        },
        "model_metrics": model_metrics,
        "benchmark_metrics": benchmark_metrics,
        "signal_attribution": signal_attribution,
        "calibration": calibration,
        "by_tournament_type": by_tournament_type,
        "by_market_type": by_market_type,
        "beat_close": _did_beat_closing_line(model_results, benchmark_results.get("market_close", [])),
    }

    # Save result
    _save_backtest_output(output)

    _log_summary(output)
    return output


# ---------------------------------------------------------------------------
# Model backtest runner
# ---------------------------------------------------------------------------

def _run_model_backtest(events: list, market_types: list) -> list[dict]:
    """
    For each historical event, reconstruct model picks and grade against results.

    CRITICAL: Uses only data available at the time of the pick.
    No lookahead. Features are built from historical snapshots.
    """
    all_results = []

    for event in events:
        event_id = event["event_id"]
        log.debug(f"Backtesting event: {event_id}")

        picks = event.get("simulated_picks", [])
        results = event.get("final_results", {})

        for pick in picks:
            if pick.get("market_type") not in market_types:
                continue

            grade = _grade_historical_pick(pick, results)
            all_results.append(grade)

    return all_results


def _grade_historical_pick(pick: dict, results: dict) -> dict:
    """Grade a historical pick against known results."""
    pid = pick["player_id"]
    market = pick["market_type"]
    price = pick.get("price", 2.0)
    stake = pick.get("stake_units", 1.0)
    model_prob = pick.get("model_probability", 0.0)

    if pid not in results:
        return {**pick, "grade": "void", "pnl": 0.0}

    final_pos = results[pid].get("final_position")
    made_cut = results[pid].get("made_cut", True)

    if final_pos is None:
        return {**pick, "grade": "void", "pnl": 0.0}

    # Grade
    grade_map = {
        "outright": final_pos == 1,
        "top_5": final_pos <= 5,
        "top_10": final_pos <= 10,
        "top_20": final_pos <= 20,
        "make_cut": made_cut,
        "miss_cut": not made_cut,
        "frl": results[pid].get("r1_position") == 1,
    }

    won = grade_map.get(market, False)
    grade = "win" if won else "loss"
    pnl = stake * (price - 1) if won else -stake
    clv = _compute_clv(price, pick.get("closing_price"))

    return {
        **pick,
        "grade": grade,
        "final_position": final_pos,
        "pnl": round(pnl, 4),
        "ev_expected": round(stake * (model_prob * (price - 1) - (1 - model_prob)), 4),
        "closing_line_value": clv,
    }


# ---------------------------------------------------------------------------
# Benchmark strategies
# ---------------------------------------------------------------------------

def _run_benchmark(events: list, market_types: list, strategy: str) -> list[dict]:
    """Run a benchmark strategy against historical events."""
    if strategy == "naive_favorites":
        return _run_favorites_benchmark(events, market_types)
    elif strategy == "world_ranking":
        return _run_ranking_benchmark(events, market_types)
    elif strategy == "recent_form_only":
        return _run_recent_form_benchmark(events, market_types)
    elif strategy == "market_close":
        return _run_market_close_benchmark(events, market_types)
    return []


def _run_favorites_benchmark(events: list, market_types: list) -> list[dict]:
    """Bet the top 3 favorites in every market for every event."""
    results = []
    for event in events:
        markets = event.get("opening_markets", {})
        final_results = event.get("final_results", {})

        for market_type in market_types:
            if market_type not in markets:
                continue
            sorted_players = sorted(
                markets[market_type].items(),
                key=lambda x: x[1].get("implied_prob", 0),
                reverse=True,
            )[:3]

            for pid, market_data in sorted_players:
                fake_pick = {
                    "player_id": pid,
                    "market_type": market_type,
                    "price": market_data.get("price", 2.0),
                    "model_probability": market_data.get("implied_prob", 0),
                    "stake_units": 1.0,
                    "event_id": event["event_id"],
                }
                grade = _grade_historical_pick(fake_pick, final_results)
                results.append(grade)
    return results


def _run_ranking_benchmark(events: list, market_types: list) -> list[dict]:
    """Bet top-ranked players by OWGR in every market."""
    # Similar to favorites but using OWGR rank as the sort key
    # Implementation analogous to _run_favorites_benchmark
    return []


def _run_recent_form_benchmark(events: list, market_types: list) -> list[dict]:
    """Bet players ranked by their 5-event rolling SG total."""
    return []


def _run_market_close_benchmark(events: list, market_types: list) -> list[dict]:
    """
    Simulate betting at closing line prices.
    This measures what's achievable with perfect market timing.
    If our model beats this, we're adding genuine model value.
    """
    return []


# ---------------------------------------------------------------------------
# Metrics and analysis
# ---------------------------------------------------------------------------

def _compute_backtest_metrics(results: list[dict]) -> dict:
    """Compute comprehensive performance metrics for a backtest run."""
    settled = [r for r in results if r["grade"] in ("win", "loss")]
    if not settled:
        return {"error": "No settled bets"}

    wins = [r for r in settled if r["grade"] == "win"]
    total_staked = sum(r.get("stake_units", 1.0) for r in settled)
    total_pnl = sum(r.get("pnl", 0) for r in settled)
    total_ev_expected = sum(r.get("ev_expected", 0) for r in settled)

    clv_values = [r["closing_line_value"] for r in results if r.get("closing_line_value") is not None]

    return {
        "n_bets": len(settled),
        "n_wins": len(wins),
        "hit_rate_pct": round(100 * len(wins) / len(settled), 2),
        "roi_pct": round(100 * total_pnl / total_staked, 2) if total_staked else 0,
        "total_pnl_units": round(total_pnl, 3),
        "total_ev_expected": round(total_ev_expected, 3),
        "ev_luck_delta": round(total_pnl - total_ev_expected, 3),
        "avg_clv": round(sum(clv_values) / len(clv_values), 4) if clv_values else None,
        "clv_positive_pct": round(100 * sum(1 for c in clv_values if c > 0) / len(clv_values), 1) if clv_values else None,
    }


def _check_probability_calibration(results: list[dict]) -> dict:
    """
    Check if model probabilities are well-calibrated.
    Groups picks into probability buckets and compares predicted vs actual win rates.
    """
    buckets = {
        "0_10": {"predicted": [], "actual": []},
        "10_20": {"predicted": [], "actual": []},
        "20_35": {"predicted": [], "actual": []},
        "35_50": {"predicted": [], "actual": []},
        "50_plus": {"predicted": [], "actual": []},
    }

    for r in results:
        if r["grade"] not in ("win", "loss"):
            continue
        prob = r.get("model_probability", 0) * 100
        won = 1 if r["grade"] == "win" else 0

        if prob < 10:
            bucket = "0_10"
        elif prob < 20:
            bucket = "10_20"
        elif prob < 35:
            bucket = "20_35"
        elif prob < 50:
            bucket = "35_50"
        else:
            bucket = "50_plus"

        buckets[bucket]["predicted"].append(prob / 100)
        buckets[bucket]["actual"].append(won)

    calibration = {}
    for bucket, data in buckets.items():
        n = len(data["actual"])
        if n < 5:
            calibration[bucket] = {"n": n, "status": "insufficient_data"}
            continue
        avg_pred = sum(data["predicted"]) / n
        avg_actual = sum(data["actual"]) / n
        calibration[bucket] = {
            "n": n,
            "avg_predicted_prob": round(avg_pred, 4),
            "avg_actual_rate": round(avg_actual, 4),
            "calibration_error": round(avg_pred - avg_actual, 4),
            "status": "overconfident" if avg_pred > avg_actual + 0.05 else (
                "underconfident" if avg_actual > avg_pred + 0.05 else "calibrated"
            ),
        }

    return calibration


def _compute_signal_attribution(results: list[dict]) -> dict:
    """
    Attribute ROI to signal families to understand which signals drive real edge.
    """
    signal_buckets = {}

    for r in results:
        dominant_signal = r.get("dominant_signal", "unknown")
        if dominant_signal not in signal_buckets:
            signal_buckets[dominant_signal] = {"pnl": 0, "staked": 0, "n": 0}

        signal_buckets[dominant_signal]["pnl"] += r.get("pnl", 0)
        signal_buckets[dominant_signal]["staked"] += r.get("stake_units", 1.0)
        signal_buckets[dominant_signal]["n"] += 1

    return {
        signal: {
            "n": data["n"],
            "roi_pct": round(100 * data["pnl"] / data["staked"], 2) if data["staked"] else 0,
            "total_pnl": round(data["pnl"], 3),
        }
        for signal, data in signal_buckets.items()
    }


def _split_by_tournament_type(results: list[dict]) -> dict:
    """Split ROI by tournament type (major, signature, standard, alternate, LIV)."""
    types = {}
    for r in results:
        t = r.get("tournament_type", "unknown")
        if t not in types:
            types[t] = []
        types[t].append(r)
    return {t: _compute_backtest_metrics(picks) for t, picks in types.items()}


def _split_by_market_type(results: list[dict]) -> dict:
    """Split ROI by market type."""
    markets = {}
    for r in results:
        m = r.get("market_type", "unknown")
        if m not in markets:
            markets[m] = []
        markets[m].append(r)
    return {m: _compute_backtest_metrics(picks) for m, picks in markets.items()}


def _did_beat_closing_line(model_results: list, close_results: list) -> dict:
    """
    Did our model beat the closing line on average?
    Positive CLV = real edge. Negative CLV = we were the public.
    """
    model_clv = [r.get("closing_line_value", 0) for r in model_results if r.get("closing_line_value") is not None]
    if not model_clv:
        return {"status": "no_clv_data"}

    avg_clv = sum(model_clv) / len(model_clv)
    positive_rate = sum(1 for c in model_clv if c > 0) / len(model_clv)

    return {
        "avg_clv": round(avg_clv, 5),
        "positive_clv_rate": round(positive_rate, 3),
        "interpretation": (
            "Positive CLV — model is finding real edge" if avg_clv > 0
            else "Negative CLV — model is betting into value-negative prices"
        ),
    }


def _compute_clv(open_price: float | None, close_price: float | None) -> float | None:
    """Compute closing line value: positive if we got better price than close."""
    if not open_price or not close_price:
        return None
    from markets.line_tracker import _decimal_to_implied_prob
    open_prob = _decimal_to_implied_prob(open_price)
    close_prob = _decimal_to_implied_prob(close_price)
    if close_prob == 0:
        return None
    return round(close_prob - open_prob, 5)  # Positive = we bet before line shortened


# ---------------------------------------------------------------------------
# I/O utilities
# ---------------------------------------------------------------------------

def _load_historical_events(start: int, end: int, tour: str) -> list:
    """Load historical event artifacts from disk."""
    events = []
    for year in range(start, end + 1):
        year_path = HISTORICAL_DATA_PATH / str(year)
        if not year_path.exists():
            continue
        for event_file in sorted(year_path.glob("*.json")):
            try:
                with open(event_file) as f:
                    event = json.load(f)
                if tour == "all" or event.get("tour", "PGA") == tour:
                    events.append(event)
            except Exception as e:
                log.warning(f"Could not load {event_file}: {e}")
    return events


def _save_backtest_output(output: dict):
    """Save backtest output to disk."""
    BACKTEST_OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    out_path = BACKTEST_OUTPUT_PATH / f"{output['backtest_id']}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    log.info(f"Backtest results saved: {out_path}")


def _log_summary(output: dict):
    """Log a clean summary of backtest results."""
    m = output.get("model_metrics", {})
    log.info("=" * 60)
    log.info("BACKTEST SUMMARY")
    log.info(f"  Events: {output['config']['n_events']}")
    log.info(f"  Bets: {m.get('n_bets')}")
    log.info(f"  ROI: {m.get('roi_pct')}%")
    log.info(f"  Hit Rate: {m.get('hit_rate_pct')}%")
    log.info(f"  Avg CLV: {m.get('avg_clv')}")
    log.info(f"  Beat Close: {output.get('beat_close', {}).get('interpretation')}")
    log.info("-" * 60)
    for benchmark, bm in output.get("benchmark_metrics", {}).items():
        log.info(f"  Benchmark ({benchmark}): ROI={bm.get('roi_pct')}%")
    log.info("=" * 60)
