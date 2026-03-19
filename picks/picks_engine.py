"""
picks/picks_engine.py
---------------------
Generates the weekly picks card from model outputs, simulation results,
and live market data.

For every player in the field, and every supported market type:
1. Compute model probability (from ensemble + simulation)
2. Find best available market price
3. Compute edge = model_prob - hold_adjusted_implied_prob
4. Check edge and confidence thresholds from risk_policy.yaml
5. Build a pick object if thresholds met
6. Apply stake sizing from staking.yaml
7. Tag with signals, flags, and adversarial review metadata

The picks engine does NOT run adversarial review — that happens downstream
in adversarial_review.py. This module outputs raw candidates.

Output structure (raw_picks):
- safe_bets: high confidence, moderate odds
- value_bets: strong edge at accessible prices
- upside_outrights: win bets with real model edge
- matchup_bets: H2H pairs ranked by edge
- placement_bets: top-5/10/20 value plays
- longshot_bets: >30/1 plays with edge
- avoid_list: overvalued players and traps
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

with open("configs/model_weights.yaml") as f:
    _WCFG = yaml.safe_load(f)

with open("configs/staking.yaml") as f:
    _STAKING = yaml.safe_load(f)

_EDGE_CFG   = _WCFG["edge_thresholds"]
_CONF_TIERS = _WCFG["confidence_tiers"]

# Market type → simulation probability key
_MARKET_SIM_MAP = {
    "outright": "win_prob",
    "top_5":    "top5_prob",
    "top_10":   "top10_prob",
    "top_20":   "top20_prob",
    "make_cut": "make_cut_prob",
    "miss_cut": "miss_cut_prob",
}

SUPPORTED_MARKET_TYPES = ["outright", "top_5", "top_10", "top_20", "make_cut", "h2h", "frl"]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def generate_picks(
    event_id: str,
    model_outputs: dict[str, dict],
    sim_results: dict[str, dict],
    markets: dict[str, Any],
) -> dict:
    """
    Generate raw picks from model + sim + market data.

    Returns categorized raw_picks dict before adversarial review.
    """
    log.info(f"Generating picks for event={event_id}")

    all_candidates = []

    # --- Generate candidates for all non-H2H markets ---
    for pid, model in model_outputs.items():
        sim = sim_results.get(pid, {})
        for market_type in SUPPORTED_MARKET_TYPES:
            if market_type == "h2h":
                continue
            candidate = _build_candidate(pid, market_type, model, sim, markets, event_id)
            if candidate:
                all_candidates.append(candidate)

    # --- Generate H2H matchup candidates ---
    h2h_candidates = _generate_h2h_candidates(model_outputs, sim_results, markets, event_id)
    all_candidates.extend(h2h_candidates)

    # --- Generate avoid list ---
    avoid_list = _generate_avoid_list(model_outputs, markets)

    # --- Categorize by pick type ---
    raw_picks = _categorize_picks(all_candidates)
    raw_picks["avoid_list"] = avoid_list

    # --- Save picks log for audit ---
    _save_picks_log(event_id, all_candidates + avoid_list)

    log.info(
        f"Picks generated: {len(all_candidates)} candidates across "
        f"{len(SUPPORTED_MARKET_TYPES)} market types"
    )
    return raw_picks


# ---------------------------------------------------------------------------
# Candidate builder
# ---------------------------------------------------------------------------

def _build_candidate(
    pid: str,
    market_type: str,
    model: dict,
    sim: dict,
    markets: dict,
    event_id: str,
) -> dict | None:
    """
    Build a single pick candidate if edge and confidence thresholds are met.
    Returns None if this player/market combination doesn't qualify.
    """
    # Get model probability for this market type
    sim_key = _MARKET_SIM_MAP.get(market_type)
    if sim_key and sim_key in sim:
        model_prob = sim[sim_key]        # Simulation is authoritative
    elif market_type == "outright":
        model_prob = model.get("model_win_prob", 0)
    elif market_type == "top_10":
        model_prob = model.get("model_top10_prob", 0)
    elif market_type == "top_20":
        model_prob = model.get("model_top20_prob", 0)
    else:
        model_prob = model.get("model_top10_prob", 0)  # fallback

    if not model_prob or model_prob < 0.005:
        return None

    # Get best market price for this player/market
    player_markets = markets.get(pid, {})
    market_tracker = player_markets.get(market_type)
    if not market_tracker:
        return None

    best_price = market_tracker.get("best_price")
    best_book  = market_tracker.get("best_book")
    if not best_price or best_price <= 1.0:
        return None

    # Implied and hold-adjusted probabilities
    implied_prob = 1.0 / best_price
    hold = 0.05  # Standard 5% hold assumption
    hold_adj_prob = implied_prob / (1 + hold)

    # Edge
    edge = model_prob - hold_adj_prob

    # Check minimum edge threshold
    min_edge = _get_min_edge(market_type, model.get("tour", "PGA"))
    if edge < min_edge:
        return None

    # Data confidence gate
    data_conf = model.get("data_confidence", 0.0)
    if data_conf < 0.30:
        return None   # Not enough data to make this bet

    # Confidence tier
    confidence_tier = _assign_confidence_tier(edge)

    # Stake sizing
    stake = _size_stake(edge, confidence_tier, market_type, model)

    # Supporting narrative
    reasons = _build_supporting_reasons(pid, market_type, model, market_tracker)

    return {
        "pick_id":               f"pick_{event_id}_{pid}_{market_type}",
        "event_id":              event_id,
        "player_id":             pid,
        "player_name":           model.get("display_name", pid),
        "tour":                  model.get("tour", "PGA"),
        "market_type":           market_type,
        "price":                 best_price,
        "book":                  best_book,
        "model_probability":     round(model_prob, 5),
        "implied_probability":   round(implied_prob, 5),
        "hold_adjusted_probability": round(hold_adj_prob, 5),
        "edge_pct":              round(edge * 100, 2),
        "edge_raw":              round(edge, 5),
        "confidence_tier":       confidence_tier,
        "stake_units":           stake,
        "dominant_signal":       model.get("dominant_signal"),
        "signal_diversity_score":model.get("signal_diversity_score", 0),
        "form_driven":           model.get("form_driven", False),
        "supporting_reasons":    reasons,
        "risk_flags":            model.get("risk_flags", []),
        "course_fit_score":      model.get("course_fit_score"),
        "composite_sg":          model.get("composite_sg"),
        "data_confidence":       round(data_conf, 3),
        "world_rank":            model.get("world_rank"),
        "data_rounds":           model.get("data_rounds", 0),
        "form_streak_events":    model.get("form_streak_events", 0),
        "weather_risk_flag":     model.get("weather_risk_flag", False),
        "line_movement_flag":    market_tracker.get("line_movement_flag"),
        "sharp_signal":          market_tracker.get("sharp_signal", False),
        "book_disagreement_score": market_tracker.get("book_disagreement_score", 0),
        "hours_since_line_update": market_tracker.get("hours_since_update"),
        "created_at":            datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# H2H matchup generation
# ---------------------------------------------------------------------------

def _generate_h2h_candidates(
    model_outputs: dict,
    sim_results: dict,
    markets: dict,
    event_id: str,
) -> list[dict]:
    """
    Generate H2H matchup picks by comparing pairs of players.
    Only considers pairs that are explicitly offered in markets.
    """
    from simulations.monte_carlo import compute_h2h_probabilities

    candidates = []
    h2h_markets = markets.get("h2h", {})

    for matchup_key, matchup_data in h2h_markets.items():
        pid_a = matchup_data.get("player_a_id")
        pid_b = matchup_data.get("player_b_id")

        if not pid_a or not pid_b:
            continue
        if pid_a not in sim_results or pid_b not in sim_results:
            continue

        # Simulate H2H
        h2h = compute_h2h_probabilities(sim_results, pid_a, pid_b)
        model_prob_a = h2h.get("player_a_win_prob", 0.5)
        model_prob_b = h2h.get("player_b_win_prob", 0.5)

        # Check each side for edge
        for side, pid, model_prob, price_key in [
            ("a", pid_a, model_prob_a, "price_a"),
            ("b", pid_b, model_prob_b, "price_b"),
        ]:
            price = matchup_data.get(price_key)
            book  = matchup_data.get("book")
            if not price or price <= 1.0:
                continue

            implied_prob = 1.0 / price
            edge = model_prob - implied_prob / 1.05

            min_edge = _get_min_edge("h2h", model_outputs.get(pid, {}).get("tour", "PGA"))
            if edge < min_edge:
                continue

            candidates.append({
                "pick_id":           f"pick_{event_id}_{pid}_h2h",
                "event_id":          event_id,
                "player_id":         pid,
                "opponent_id":       pid_b if side == "a" else pid_a,
                "market_type":       "h2h",
                "price":             price,
                "book":              book,
                "model_probability": round(model_prob, 5),
                "implied_probability": round(implied_prob, 5),
                "edge_pct":          round(edge * 100, 2),
                "edge_raw":          round(edge, 5),
                "confidence_tier":   _assign_confidence_tier(edge),
                "stake_units":       _size_stake(edge, _assign_confidence_tier(edge), "h2h",
                                               model_outputs.get(pid, {})),
                "h2h_median_finish_a": h2h.get("a_median_finish"),
                "h2h_median_finish_b": h2h.get("b_median_finish"),
                "risk_flags":        model_outputs.get(pid, {}).get("risk_flags", []),
                "created_at":        datetime.now(timezone.utc).isoformat(),
            })

    return candidates


# ---------------------------------------------------------------------------
# Avoid list
# ---------------------------------------------------------------------------

def _generate_avoid_list(model_outputs: dict, markets: dict) -> list[dict]:
    """
    Generate the avoid/trap list: players whose market price is significantly
    below our model probability — i.e., the market is overvaluing them.
    """
    avoid = []
    for pid, model in model_outputs.items():
        player_markets = markets.get(pid, {})
        outright = player_markets.get("outright")
        if not outright:
            continue

        best_price = outright.get("best_price")
        if not best_price or best_price <= 1.0:
            continue

        implied_prob = 1.0 / best_price
        model_win = model.get("model_win_prob", 0)

        # Trap: market has player significantly shorter than model suggests
        if implied_prob > model_win * 1.30 and implied_prob > 0.04:
            avoid.append({
                "player_id":         pid,
                "player_name":       model.get("display_name", pid),
                "market_type":       "outright",
                "best_price":        best_price,
                "model_probability": round(model_win, 5),
                "implied_probability": round(implied_prob, 5),
                "overvaluation_pct": round((implied_prob / model_win - 1) * 100, 1) if model_win > 0 else None,
                "avoid_reason":      _classify_avoid_reason(model, outright),
                "revisit_trigger":   "Price lengthens to match or exceed model probability",
                "verdict":           "TRAP",
            })

    return sorted(avoid, key=lambda x: x.get("overvaluation_pct") or 0, reverse=True)


def _classify_avoid_reason(model: dict, outright: dict) -> str:
    """Generate a concise reason why this player is a trap."""
    world_rank = model.get("world_rank", 999)
    course_fit = model.get("course_fit_score", 0)
    line_flag  = outright.get("line_movement_flag", "")

    if world_rank <= 5 and course_fit < 0:
        return "Top-ranked player but poor course fit — reputation premium is mispriced"
    if "shortening" in line_flag:
        return "Line has shortened significantly — public money has compressed the value"
    if model.get("form_driven") and model.get("form_streak_events", 10) < 3:
        return "Recent hot streak is driving odds below fair value — likely to regress"
    return "Market price significantly below model fair value — no edge at current price"


# ---------------------------------------------------------------------------
# Categorization
# ---------------------------------------------------------------------------

def _categorize_picks(candidates: list[dict]) -> dict:
    """Sort picks into card categories."""
    safe_bets      = []
    value_bets     = []
    upside_outrights = []
    matchup_bets   = []
    placement_bets = []
    longshot_bets  = []

    for c in candidates:
        mt    = c["market_type"]
        edge  = c["edge_raw"]
        price = c["price"]

        if mt == "h2h":
            matchup_bets.append(c)
        elif mt == "outright" and price >= 30.0 and edge >= 0.06:
            longshot_bets.append(c)
        elif mt == "outright" and edge >= _EDGE_CFG["strong_edge_threshold"]:
            upside_outrights.append(c)
        elif mt in ("top_10", "top_20", "make_cut") and edge >= _EDGE_CFG["minimum_edge_to_flag"]:
            if c.get("data_confidence", 0) >= 0.65 and c.get("signal_diversity_score", 0) >= 0.50:
                safe_bets.append(c)
            else:
                placement_bets.append(c)
        elif mt in ("top_5", "top_10", "top_20"):
            placement_bets.append(c)
        elif edge >= _EDGE_CFG["strong_edge_threshold"]:
            value_bets.append(c)
        else:
            value_bets.append(c)

    def by_edge(lst):
        return sorted(lst, key=lambda x: x["edge_raw"], reverse=True)

    return {
        "safe_bets":        by_edge(safe_bets)[:8],
        "value_bets":       by_edge(value_bets)[:10],
        "upside_outrights": by_edge(upside_outrights)[:6],
        "matchup_bets":     by_edge(matchup_bets)[:8],
        "placement_bets":   by_edge(placement_bets)[:10],
        "longshot_bets":    by_edge(longshot_bets)[:5],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_min_edge(market_type: str, tour: str) -> float:
    """Get minimum edge threshold for a market type."""
    base_thresholds = {
        "outright": _EDGE_CFG["minimum_edge_to_flag"] * 2,
        "top_5":    _EDGE_CFG["minimum_edge_to_flag"] * 1.25,
        "top_10":   _EDGE_CFG["minimum_edge_to_flag"],
        "top_20":   _EDGE_CFG["minimum_edge_to_flag"],
        "make_cut": _EDGE_CFG["minimum_edge_to_flag"],
        "miss_cut": _EDGE_CFG["minimum_edge_to_flag"] * 1.25,
        "h2h":      _EDGE_CFG["minimum_edge_to_flag"],
        "frl":      _EDGE_CFG["strong_edge_threshold"],
    }
    threshold = base_thresholds.get(market_type, _EDGE_CFG["minimum_edge_to_flag"])
    # LIV gets a slightly higher bar due to model uncertainty
    if tour == "LIV":
        threshold += 0.02
    return threshold


def _assign_confidence_tier(edge: float) -> str:
    """Assign a confidence tier label based on edge magnitude."""
    for tier_name, tier_cfg in _CONF_TIERS.items():
        if edge * 100 >= tier_cfg["edge_min"] * 100:
            return tier_name
    return "tier_4"


def _size_stake(edge: float, tier: str, market_type: str, model: dict) -> float:
    """Apply Kelly-fraction stake sizing from staking.yaml."""
    tier_cfg = _CONF_TIERS.get(tier, _CONF_TIERS["tier_4"])
    base_stake = tier_cfg["max_stake_pct"]

    # Market type multiplier
    mt_adj = _STAKING["market_type_adjustments"].get(market_type, {})
    multiplier = mt_adj.get("stake_multiplier", 1.0)

    # Fragility reductions
    fragility_mult = 1.0
    if model.get("data_confidence", 1.0) < 0.40:
        fragility_mult *= 0.6
    if model.get("signal_diversity_score", 1.0) < 0.30:
        fragility_mult *= 0.7
    if model.get("weather_risk_flag"):
        fragility_mult *= 0.80

    stake = base_stake * multiplier * fragility_mult
    return round(max(0.005, min(stake, _STAKING["bankroll_management"]["max_single_bet_pct"])), 4)


def _build_supporting_reasons(pid: str, market_type: str, model: dict, tracker: dict) -> list[str]:
    """Build a list of supporting reasons for a pick."""
    reasons = []

    composite_sg = model.get("composite_sg")
    if composite_sg and composite_sg > 0.5:
        reasons.append(f"Elite long-term SG baseline: +{composite_sg:.2f} strokes/round vs field")

    sg_app = model.get("sg_app")
    if sg_app and sg_app > 0.8:
        reasons.append(f"Top-tier approach game: SG App +{sg_app:.2f}")

    course_fit = model.get("course_fit_score")
    course_summary = model.get("course_fit_summary", "")
    if course_fit and course_fit > 0.25:
        reasons.append(f"Strong course fit (+{course_fit:.2f}): {course_summary[:80]}")

    if model.get("form_trend") == "improving":
        reasons.append(f"Improving form trend (last 3 events vs prior 3)")

    if tracker.get("sharp_signal"):
        reasons.append("Sharp book movement confirms model direction")

    if tracker.get("book_disagreement_score", 0) > 0.04:
        reasons.append(f"High book disagreement ({tracker['book_disagreement_score']:.3f}) — potential market inefficiency")

    return reasons[:5]  # Cap at 5 reasons for readability


def _save_picks_log(event_id: str, picks: list[dict]):
    """Persist picks log to disk for post-event audit."""
    log_dir = Path("picks/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    out_path = log_dir / f"{event_id}_picks.json"
    with open(out_path, "w") as f:
        json.dump(picks, f, indent=2, default=str)
    log.info(f"Picks log saved: {out_path}")
