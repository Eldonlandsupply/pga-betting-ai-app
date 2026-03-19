"""
features/volatility.py
-----------------------
Builds volatility, ceiling, and consistency profiles for each player.

Volatility in golf is not purely bad — high-ceiling players can win
outrights even with lower average performance. The volatility profile
helps the picks engine correctly size stakes and choose market types:

- High-floor, low-ceiling players → target placement bets (top 10/20)
- High-ceiling, high-variance players → target outrights and longshots
- Consistent steady players → target make-cut, top-20, matchups

Key metrics:
- round_to_round_sd: standard deviation of round scores
- cut_rate: historical make-cut % (PGA events only)
- top10_rate: historical top-10 finish % across career
- bogey_avoidance: strokes gained on bogey avoidance
- ceiling_score: probability-weighted upside (top-3 finish rate)
- consistency_score: risk-adjusted performance metric
- volatility_tier: "elite_consistent", "high_ceiling", "boom_bust", "grinder", "volatile"
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger(__name__)


# Tier classification thresholds
_TIER_RULES = [
    # (label, min_consistency, min_ceiling, max_sd, description)
    ("elite_consistent", 0.70, 0.35, 2.8, "High floor and high ceiling — elite all-rounder"),
    ("high_ceiling",     0.45, 0.40, 3.4, "Boom potential but can miss cut — target outrights"),
    ("grinder",          0.65, 0.18, 2.6, "Consistent, rarely wins — target placements and cut bets"),
    ("boom_bust",        0.35, 0.30, 3.8, "Very high variance — small stakes outrights only"),
    ("volatile",         0.0,  0.0,  9.9, "Unpredictable — no model conviction"),
]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def build_volatility_profiles(field: list[dict], stats: dict[str, Any]) -> dict[str, dict]:
    """Build volatility profiles for all players in the field."""
    results = {}
    for player in field:
        pid = player["id"]
        pstats = stats.get(pid)
        if not pstats:
            results[pid] = _null_profile(pid)
            continue
        results[pid] = _compute_profile(pid, pstats)
    log.info(f"Volatility profiles built for {len(results)} players.")
    return results


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _compute_profile(pid: str, player_stats: dict) -> dict:
    """Compute full volatility profile for a single player."""
    rounds = player_stats.get("rounds", [])

    # Round-to-round SD
    scores = [r.get("score") for r in rounds if r.get("score") is not None]
    round_sd = float(_std(scores)) if len(scores) >= 10 else None

    # Cut rate (PGA only — rounds with cut_event=True)
    cut_events = [r for r in rounds if r.get("tournament_type") not in ("liv",)]
    cut_rate = player_stats.get("make_cut_rate")

    # Top-10 and win rates
    top10_rate = player_stats.get("top10_rate")
    win_rate   = player_stats.get("win_rate")

    # Bogey avoidance (SG on bogey prevention)
    bogey_avoidance = player_stats.get("bogey_avoidance")

    # Final-round SG (pressure performance)
    final_rd_sg = player_stats.get("final_round_sg")

    # Ceiling score: estimated probability of a top-3 result
    # Approximation: (win_rate + top10_rate * 0.3) adjusted for variance
    ceiling_score = _compute_ceiling(win_rate, top10_rate, round_sd)

    # Consistency score: combines cut_rate, bogey_avoidance, round_sd
    consistency_score = _compute_consistency(cut_rate, bogey_avoidance, round_sd)

    # Volatility tier classification
    vol_tier = _classify_tier(consistency_score, ceiling_score, round_sd)

    # Best market type recommendation based on profile
    recommended_markets = _recommend_markets(vol_tier)

    return {
        "player_id":            pid,
        "round_to_round_sd":    round(round_sd, 3) if round_sd is not None else None,
        "cut_rate":             round(cut_rate, 3) if cut_rate is not None else None,
        "top10_rate":           round(top10_rate, 3) if top10_rate is not None else None,
        "win_rate":             round(win_rate, 3) if win_rate is not None else None,
        "bogey_avoidance":      round(bogey_avoidance, 3) if bogey_avoidance is not None else None,
        "final_round_sg":       round(final_rd_sg, 3) if final_rd_sg is not None else None,
        "ceiling_score":        round(ceiling_score, 4),
        "consistency_score":    round(consistency_score, 4),
        "volatility_tier":      vol_tier,
        "recommended_markets":  recommended_markets,
        "stake_tier_hint":      _stake_hint(vol_tier),
    }


def _compute_ceiling(win_rate: float | None, top10_rate: float | None, sd: float | None) -> float:
    """
    Estimate a player's upside ceiling as a normalized 0–1 score.
    Higher = more likely to contend/win when in form.
    """
    base = 0.0
    if win_rate is not None:
        base += win_rate * 3.0         # Wins are heavily weighted
    if top10_rate is not None:
        base += top10_rate * 0.4       # Top-10 rate adds upside signal
    if sd is not None and sd > 3.2:
        base += 0.05                   # High variance = occasional blowup upside

    return min(1.0, base)


def _compute_consistency(
    cut_rate: float | None,
    bogey_avoidance: float | None,
    sd: float | None,
) -> float:
    """
    Estimate consistency as a normalized 0–1 score.
    Higher = more reliable floor, less variance.
    """
    score = 0.0
    weight = 0.0

    if cut_rate is not None:
        # Cut rate 0.85+ → near full consistency contribution
        score  += min(1.0, cut_rate / 0.85) * 0.40
        weight += 0.40

    if bogey_avoidance is not None:
        # Map bogey_avoidance SG to 0–1 (typical range: -0.5 to +0.3)
        normalized_ba = min(1.0, max(0.0, (bogey_avoidance + 0.5) / 0.8))
        score  += normalized_ba * 0.35
        weight += 0.35

    if sd is not None:
        # Lower SD = higher consistency
        normalized_sd = min(1.0, max(0.0, 1.0 - (sd - 2.0) / 3.0))
        score  += normalized_sd * 0.25
        weight += 0.25

    return (score / weight) if weight > 0 else 0.5


def _classify_tier(consistency: float, ceiling: float, sd: float | None) -> str:
    """Classify player into a volatility tier."""
    effective_sd = sd if sd is not None else 3.2

    for label, min_cons, min_ceil, max_sd, _ in _TIER_RULES[:-1]:
        if consistency >= min_cons and ceiling >= min_ceil and effective_sd <= max_sd:
            return label

    return "volatile"


def _recommend_markets(tier: str) -> list[str]:
    """Recommend best bet market types for this volatility profile."""
    market_map = {
        "elite_consistent": ["top_5", "top_10", "top_20", "outright", "h2h"],
        "high_ceiling":     ["outright", "top_5", "frl"],
        "grinder":          ["top_10", "top_20", "make_cut", "h2h"],
        "boom_bust":        ["outright", "longshot"],
        "volatile":         [],
    }
    return market_map.get(tier, [])


def _stake_hint(tier: str) -> str:
    """Hint for stake sizing based on volatility tier."""
    hints = {
        "elite_consistent": "standard",
        "high_ceiling":     "reduced_on_placements",
        "grinder":          "standard_to_moderate",
        "boom_bust":        "small_units_only",
        "volatile":         "no_bet",
    }
    return hints.get(tier, "standard")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _std(values: list[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _null_profile(pid: str) -> dict:
    return {
        "player_id":         pid,
        "round_to_round_sd": None,
        "cut_rate":          None,
        "top10_rate":        None,
        "win_rate":          None,
        "bogey_avoidance":   None,
        "ceiling_score":     0.0,
        "consistency_score": 0.0,
        "volatility_tier":   "volatile",
        "recommended_markets": [],
        "stake_tier_hint":   "no_bet",
    }
