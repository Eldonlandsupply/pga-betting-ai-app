"""
audit/post_event_audit.py
--------------------------
The post-event audit is the core self-improvement mechanism.

After every event it:
1. Grades every pick (win/loss/push/partial/void)
2. Computes realized EV vs expected EV
3. Separates model directional accuracy from result variance
4. Identifies structural model failures vs bad luck
5. Flags repeated cross-week failure patterns
6. Generates the "What We Missed" report
7. Feeds evidence to weight_updater.py

Design rules:
- One blown pick is NOT evidence to change a weight.
- A repeated directional miss across 6+ events IS evidence.
- "We were right but lost" is NOT a failure — record it as such.
- "We were wrong but won" is a dangerous success — flag it.
- Every failure has a cause category, not just "bad pick."
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Failure cause taxonomy
FAILURE_CAUSES = [
    "underweighted_recent_approach_surge",
    "overweighted_stale_putting_baseline",
    "mispriced_wind_specialist",
    "missed_course_fit_penalty",
    "underestimated_liv_volatility",
    "overrated_big_name_reputation",
    "failed_fade_on_poor_comp_course_fit",
    "missed_sharp_line_movement_signal",
    "injury_flag_not_captured",
    "overfit_recent_hot_streak",
    "small_field_effect_not_modeled",
    "format_adjustment_insufficient",
    "data_thin_player_mispriced",
    "correlated_bets_double_counted",
    "market_had_significant_edge_we_missed",
    "other",
]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run_post_event_audit(event_id: str, results: dict) -> dict:
    """
    Run the full post-event audit for a completed tournament.

    Args:
        event_id: event identifier
        results: dict containing:
            - "final_standings": list of {player_id, final_position, score_to_par}
            - "picks_log": list of picks made pre-event (loaded from picks log)
            - "cut_results": dict {player_id: made_cut bool} (PGA only)

    Returns:
        audit_output dict with grades, metrics, failure analysis, and recommendations
    """
    log.info(f"=== POST-EVENT AUDIT: {event_id} ===")

    # Load pre-event picks from log
    picks = _load_picks_log(event_id)
    if not picks:
        log.warning(f"No picks log found for event {event_id}. Audit incomplete.")
        return {"event_id": event_id, "error": "No picks log found"}

    standings = results.get("final_standings", [])
    cut_results = results.get("cut_results", {})

    # Build position lookup
    position_lookup = {r["player_id"]: r for r in standings}

    # --- GRADE ALL PICKS ---
    graded_picks = []
    for pick in picks:
        graded = _grade_pick(pick, position_lookup, cut_results)
        graded_picks.append(graded)

    # --- COMPUTE AGGREGATE METRICS ---
    metrics = _compute_metrics(graded_picks)

    # --- IDENTIFY FAILURES ---
    failures = _identify_failures(graded_picks, position_lookup)

    # --- IDENTIFY SUCCESSES (especially "right for right reasons") ---
    successes = _identify_successes(graded_picks)

    # --- DETECT CROSS-WEEK PATTERNS ---
    patterns = _detect_cross_week_patterns(event_id, failures)

    # --- GENERATE "WHAT WE MISSED" REPORT ---
    missed_report = _generate_missed_report(event_id, graded_picks, failures, position_lookup)

    # --- MODEL ADJUSTMENT RECOMMENDATIONS ---
    recommendations = _generate_recommendations(failures, patterns, metrics)

    # Compile output
    audit_output = {
        "event_id": event_id,
        "audit_timestamp": datetime.utcnow().isoformat(),
        "picks_graded": len(graded_picks),
        "metrics": metrics,
        "graded_picks": graded_picks,
        "failures": failures,
        "successes": successes,
        "cross_week_patterns": patterns,
        "missed_report": missed_report,
        "model_adjustment_recommendations": recommendations,
    }

    # Save audit artifact
    _save_audit_artifact(event_id, audit_output)

    log.info(
        f"Audit complete. ROI: {metrics['realized_roi_pct']:.1f}% | "
        f"Hit rate: {metrics['hit_rate_pct']:.1f}% | "
        f"CLV: {metrics['avg_clv']:.3f}"
    )

    return audit_output


# ---------------------------------------------------------------------------
# Pick grading
# ---------------------------------------------------------------------------

def _grade_pick(pick: dict, position_lookup: dict, cut_results: dict) -> dict:
    """
    Grade a single pick as win/loss/push/partial/void.

    Also records:
    - Whether model was directionally correct (right call, bad variance)
    - Whether model was structurally wrong (bad call, got lucky)
    - EV realized vs EV expected
    """
    pid = pick["player_id"]
    market_type = pick["market_type"]
    price = pick["price"]  # American odds or decimal
    model_prob = pick["model_probability"]
    stake = pick.get("stake_units", 1.0)

    if pid not in position_lookup:
        return {**pick, "grade": "void", "reason": "Player withdrew or no result"}

    final_pos = position_lookup[pid]["final_position"]

    # Grade by market type
    grade = _grade_by_market(market_type, final_pos, pick, cut_results.get(pid))
    pnl = _compute_pnl(grade, price, stake)
    ev_expected = _compute_expected_ev(model_prob, price, stake)
    ev_realized = pnl

    # Was model directionally correct?
    model_direction = _assess_model_direction(grade, model_prob, pick)

    # Failure cause (if loss)
    failure_cause = None
    if grade == "loss":
        failure_cause = _classify_failure_cause(pick, final_pos, position_lookup)

    return {
        **pick,
        "final_position": final_pos,
        "grade": grade,
        "pnl_units": round(pnl, 4),
        "ev_expected": round(ev_expected, 4),
        "ev_realized": round(ev_realized, 4),
        "model_directionally_correct": model_direction,
        "failure_cause": failure_cause,
    }


def _grade_by_market(market_type: str, final_pos: int, pick: dict, made_cut: bool | None) -> str:
    """Return 'win', 'loss', 'push', or 'void' based on market type and result."""
    if market_type == "outright":
        return "win" if final_pos == 1 else "loss"
    elif market_type == "top_5":
        return "win" if final_pos <= 5 else "loss"
    elif market_type == "top_10":
        return "win" if final_pos <= 10 else "loss"
    elif market_type == "top_20":
        return "win" if final_pos <= 20 else "loss"
    elif market_type == "make_cut":
        if made_cut is None:
            return "void"
        return "win" if made_cut else "loss"
    elif market_type == "miss_cut":
        if made_cut is None:
            return "void"
        return "win" if not made_cut else "loss"
    elif market_type == "h2h":
        opponent_id = pick.get("opponent_id")
        # H2H grading requires comparing two players' positions
        return "void"  # Resolved separately in H2H grader
    elif market_type == "frl":
        return "win" if final_pos == 1 else "loss"  # Simplified — FRL is R1 only
    else:
        return "void"


def _compute_pnl(grade: str, price: float, stake: float) -> float:
    """Compute profit/loss in units. Price assumed decimal odds."""
    if grade == "win":
        return stake * (price - 1)
    elif grade == "loss":
        return -stake
    else:
        return 0.0


def _compute_expected_ev(model_prob: float, price: float, stake: float) -> float:
    """Expected value in units based on model probability."""
    return stake * (model_prob * (price - 1) - (1 - model_prob))


def _assess_model_direction(grade: str, model_prob: float, pick: dict) -> str:
    """
    Assess whether the model was directionally correct.

    Categories:
    - "right_right": Model had edge, we won → good
    - "right_wrong": Model had edge, we lost → variance, not model failure
    - "wrong_right": Model was incorrect, we won → lucky, dangerous
    - "wrong_wrong": Model was incorrect, we lost → structural failure
    """
    implied_prob = pick.get("implied_probability", 0.0)
    had_edge = model_prob > implied_prob

    if had_edge and grade == "win":
        return "right_right"
    elif had_edge and grade == "loss":
        return "right_wrong"
    elif not had_edge and grade == "win":
        return "wrong_right"
    else:
        return "wrong_wrong"


def _classify_failure_cause(pick: dict, final_pos: int, position_lookup: dict) -> str:
    """
    Classify WHY a losing pick failed.
    This is a heuristic classifier — flagged causes are reviewed by weight_updater.
    """
    flags = pick.get("risk_flags", [])
    model_signals = pick.get("supporting_signals", {})

    if "injury_unverified" in flags:
        return "injury_flag_not_captured"
    if model_signals.get("form_signal_age_days", 999) < 14 and pick.get("form_driven", False):
        return "overfit_recent_hot_streak"
    if pick.get("course_fit_score", 0) < -0.2:
        return "missed_course_fit_penalty"
    if pick.get("data_confidence", 1.0) < 0.40:
        return "data_thin_player_mispriced"
    if pick.get("market_movement_flag") == "against_model":
        return "missed_sharp_line_movement_signal"
    if pick.get("tour") == "LIV":
        return "underestimated_liv_volatility"

    return "other"


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------

def _compute_metrics(graded_picks: list) -> dict:
    """Compute aggregate pick performance metrics."""
    wins = [p for p in graded_picks if p["grade"] == "win"]
    losses = [p for p in graded_picks if p["grade"] == "loss"]
    pushes = [p for p in graded_picks if p["grade"] == "push"]
    voids = [p for p in graded_picks if p["grade"] == "void"]

    n_settled = len(wins) + len(losses) + len(pushes)
    total_pnl = sum(p.get("pnl_units", 0) for p in graded_picks)
    total_staked = sum(p.get("stake_units", 1.0) for p in graded_picks if p["grade"] != "void")
    total_ev_expected = sum(p.get("ev_expected", 0) for p in graded_picks)

    right_right = len([p for p in graded_picks if p.get("model_directionally_correct") == "right_right"])
    right_wrong = len([p for p in graded_picks if p.get("model_directionally_correct") == "right_wrong"])
    wrong_right = len([p for p in graded_picks if p.get("model_directionally_correct") == "wrong_right"])
    wrong_wrong = len([p for p in graded_picks if p.get("model_directionally_correct") == "wrong_wrong"])

    # Closing line value: did our picks beat closing price?
    clv_values = [
        p.get("closing_line_value", 0)
        for p in graded_picks
        if p.get("closing_line_value") is not None
    ]

    return {
        "total_picks": len(graded_picks),
        "settled_picks": n_settled,
        "wins": len(wins),
        "losses": len(losses),
        "pushes": len(pushes),
        "voids": len(voids),
        "hit_rate_pct": round(100 * len(wins) / n_settled, 1) if n_settled else 0,
        "realized_roi_pct": round(100 * total_pnl / total_staked, 1) if total_staked else 0,
        "total_pnl_units": round(total_pnl, 3),
        "total_ev_expected": round(total_ev_expected, 3),
        "ev_luck_factor": round(total_pnl - total_ev_expected, 3),  # Positive = got lucky
        "model_right_pct": round(100 * (right_right + right_wrong) / n_settled, 1) if n_settled else 0,
        "directional_breakdown": {
            "right_right": right_right,
            "right_wrong": right_wrong,
            "wrong_right": wrong_right,
            "wrong_wrong": wrong_wrong,
        },
        "avg_clv": round(sum(clv_values) / len(clv_values), 4) if clv_values else None,
    }


# ---------------------------------------------------------------------------
# Failure and success identification
# ---------------------------------------------------------------------------

def _identify_failures(graded_picks: list, position_lookup: dict) -> list:
    """Extract and analyze structural model failures."""
    structural_failures = []

    for pick in graded_picks:
        if pick.get("model_directionally_correct") in ("wrong_wrong", "wrong_right"):
            failure_entry = {
                "player_id": pick["player_id"],
                "market_type": pick["market_type"],
                "model_probability": pick.get("model_probability"),
                "implied_probability": pick.get("implied_probability"),
                "final_position": pick.get("final_position"),
                "failure_cause": pick.get("failure_cause"),
                "direction_flag": pick.get("model_directionally_correct"),
            }
            structural_failures.append(failure_entry)

    return structural_failures


def _identify_successes(graded_picks: list) -> list:
    """Identify picks that were right for the right reasons."""
    return [
        {
            "player_id": p["player_id"],
            "market_type": p["market_type"],
            "grade": p["grade"],
            "edge_pct": p.get("edge_pct"),
            "closing_line_value": p.get("closing_line_value"),
        }
        for p in graded_picks
        if p.get("model_directionally_correct") == "right_right"
    ]


def _detect_cross_week_patterns(event_id: str, current_failures: list) -> list:
    """
    Check current failures against historical audit logs to detect repeated patterns.
    Returns patterns that have appeared 3+ times.
    """
    cause_counts = {}

    # Load last 8 event audit logs
    audit_dir = Path("audit/history")
    if audit_dir.exists():
        for audit_file in sorted(audit_dir.glob("*.json"))[-8:]:
            try:
                with open(audit_file) as f:
                    prev_audit = json.load(f)
                for failure in prev_audit.get("failures", []):
                    cause = failure.get("failure_cause", "other")
                    cause_counts[cause] = cause_counts.get(cause, 0) + 1
            except Exception as e:
                log.warning(f"Could not load audit file {audit_file}: {e}")

    # Add current event
    for failure in current_failures:
        cause = failure.get("failure_cause", "other")
        cause_counts[cause] = cause_counts.get(cause, 0) + 1

    # Return causes appearing 3+ times as patterns
    return [
        {"cause": cause, "occurrences": count, "flag": "REPEATED_PATTERN"}
        for cause, count in cause_counts.items()
        if count >= 3
    ]


# ---------------------------------------------------------------------------
# Reports and recommendations
# ---------------------------------------------------------------------------

def _generate_missed_report(
    event_id: str,
    graded_picks: list,
    failures: list,
    position_lookup: dict,
) -> dict:
    """Generate the 'What We Missed' narrative report."""

    # Top winners we didn't bet
    all_player_ids = {p["player_id"] for p in graded_picks}
    top_performers = [
        r for r in position_lookup.values()
        if r["final_position"] <= 10 and r["player_id"] not in all_player_ids
    ]

    missed_summary = []
    for performer in sorted(top_performers, key=lambda x: x["final_position"])[:5]:
        missed_summary.append({
            "player_id": performer["player_id"],
            "final_position": performer["final_position"],
            "reason_missed": "Not in our picks — investigate why model undervalued this player",
        })

    return {
        "event_id": event_id,
        "report_type": "what_we_missed",
        "structural_failures": [f["failure_cause"] for f in failures if f.get("failure_cause")],
        "top_performers_we_missed": missed_summary,
        "key_questions": [
            "Were there line movements we missed that predicted the winner?",
            "Did our course-fit model undervalue any top finisher?",
            "Were we overweight on any stat category that underperformed?",
            "Were there injury/condition flags we failed to capture?",
            "Were we systematically too conservative or too aggressive?",
        ],
    }


def _generate_recommendations(
    failures: list,
    patterns: list,
    metrics: dict,
) -> list:
    """Generate model adjustment recommendations based on audit evidence."""
    recommendations = []

    # Pattern-based recommendations
    cause_set = {p["cause"] for p in patterns}

    if "underweighted_recent_approach_surge" in cause_set:
        recommendations.append({
            "target": "form_model.py",
            "change": "Increase weight on sg_app in recent form window",
            "evidence": "Repeated miss on approach surge players",
            "priority": "high",
            "gate_required": True,
        })

    if "overweighted_stale_putting_baseline" in cause_set:
        recommendations.append({
            "target": "features/player_baseline.py",
            "change": "Reduce putting decay half-life from 300 to 240 days",
            "evidence": "Stale putting baselines overriding recent form",
            "priority": "medium",
            "gate_required": True,
        })

    if "missed_sharp_line_movement_signal" in cause_set:
        recommendations.append({
            "target": "features/market_signals.py",
            "change": "Increase weight on sharp-vs-public movement in edge calculation",
            "evidence": "Sharp money predicted results we missed",
            "priority": "high",
            "gate_required": True,
        })

    if "underestimated_liv_volatility" in cause_set:
        recommendations.append({
            "target": "configs/model_weights.yaml → liv_adjustments",
            "change": "Increase LIV volatility_sd multiplier from 1.0 to 1.15",
            "evidence": "LIV placement bets consistently over-confident",
            "priority": "medium",
            "gate_required": True,
        })

    # ROI-based recommendations
    if metrics.get("realized_roi_pct", 0) < -10:
        recommendations.append({
            "target": "configs/staking.yaml",
            "change": "Reduce maximum weekly exposure from 15% to 12% until model stabilizes",
            "evidence": f"Weekly ROI at {metrics['realized_roi_pct']}% — drawdown protection triggered",
            "priority": "immediate",
            "gate_required": False,  # Risk rule — implement immediately
        })

    return recommendations


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_picks_log(event_id: str) -> list:
    """Load pre-event picks log from disk."""
    log_path = Path(f"picks/logs/{event_id}_picks.json")
    if not log_path.exists():
        log.warning(f"Picks log not found: {log_path}")
        return []
    with open(log_path) as f:
        return json.load(f)


def _save_audit_artifact(event_id: str, audit_output: dict):
    """Save audit output to the audit history directory."""
    audit_dir = Path("audit/history")
    audit_dir.mkdir(parents=True, exist_ok=True)
    out_path = audit_dir / f"{event_id}_audit.json"
    with open(out_path, "w") as f:
        json.dump(audit_output, f, indent=2, default=str)
    log.info(f"Audit artifact saved: {out_path}")
