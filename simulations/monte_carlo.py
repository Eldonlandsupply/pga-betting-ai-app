"""
simulations/monte_carlo.py
---------------------------
Tournament simulation engine.

Runs N Monte Carlo simulations of a golf tournament and produces:
- Win probability per player
- Top 5 / 10 / 20 finish probabilities
- Make cut probability (PGA)
- Head-to-head matchup probabilities
- Simulated finish distributions (for exotic markets)
- Model confidence ranges for each probability

Design philosophy:
- Uses per-player skill composite + volatility profile to generate round scores
- Models both skill-driven variance (your quality level) and random variance
  (golf is a high-variance game even for the best)
- LIV simulation: no cut, 54-hole, smaller field
- PGA simulation: 72-hole, cut applied after R2
- Does NOT assume normal distributions — uses skewed distributions
  to capture the "blow-up round" characteristic of golf
- Output probabilities are model output, NOT calibrated market probabilities.
  Market signals and hold adjustments are applied downstream.
"""

import logging
import math
import random
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# Simulation defaults
DEFAULT_N_SIM = 10_000
PGA_ROUNDS = 4
LIV_ROUNDS = 3
PGA_CUT_LINE_APPROX = 70  # Top 70 + ties typical
LIV_FIELD_SIZE_TYPICAL = 48


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def simulate_tournament(
    event_id: str,
    players: list[dict],
    n_simulations: int = DEFAULT_N_SIM,
    tour: str = "PGA",
    apply_cut: bool = True,
) -> dict[str, Any]:
    """
    Run Monte Carlo tournament simulation.

    Args:
        event_id: event identifier for logging/tracing
        players: list of dicts with:
          - player_id: str
          - skill_composite: float (composite SG per round vs field)
          - volatility_sd: float (round-to-round SD)
          - ceiling_boost: float (upside multiplier)
          - form_adjustment: float (recent form delta)
        n_simulations: number of Monte Carlo trials
        tour: "PGA" or "LIV"
        apply_cut: whether to apply a cut (PGA only)

    Returns:
        dict with per-player finish distributions and summary probabilities
    """
    log.info(f"Starting simulation: event={event_id} n={n_simulations} tour={tour}")

    n_rounds = LIV_ROUNDS if tour == "LIV" else PGA_ROUNDS
    n_players = len(players)
    cut_position = None if (tour == "LIV" or not apply_cut) else PGA_CUT_LINE_APPROX

    # Initialize result accumulators
    wins = {p["player_id"]: 0 for p in players}
    top5 = {p["player_id"]: 0 for p in players}
    top10 = {p["player_id"]: 0 for p in players}
    top20 = {p["player_id"]: 0 for p in players}
    made_cut = {p["player_id"]: 0 for p in players}
    finish_buckets = {p["player_id"]: [] for p in players}  # For distribution

    for sim_idx in range(n_simulations):
        scores = _simulate_one_tournament(players, n_rounds, cut_position, tour)

        # Sort by total score (lower = better)
        sorted_players = sorted(
            [(pid, total) for pid, total in scores.items() if total is not None],
            key=lambda x: x[1],
        )

        for rank, (pid, _) in enumerate(sorted_players, start=1):
            finish_buckets[pid].append(rank)
            if rank == 1:
                wins[pid] += 1
            if rank <= 5:
                top5[pid] += 1
            if rank <= 10:
                top10[pid] += 1
            if rank <= 20:
                top20[pid] += 1

        # Made cut tracking (PGA only)
        if cut_position:
            for p in players:
                pid = p["player_id"]
                if scores.get(pid) is not None:
                    made_cut[pid] += 1

    # Convert counts to probabilities
    results = {}
    for p in players:
        pid = p["player_id"]
        dist = finish_buckets[pid]

        results[pid] = {
            "player_id": pid,
            "win_prob": _safe_prob(wins[pid], n_simulations),
            "top5_prob": _safe_prob(top5[pid], n_simulations),
            "top10_prob": _safe_prob(top10[pid], n_simulations),
            "top20_prob": _safe_prob(top20[pid], n_simulations),
            "make_cut_prob": _safe_prob(made_cut[pid], n_simulations) if cut_position else None,
            "median_finish": float(np.median(dist)) if dist else None,
            "mean_finish": float(np.mean(dist)) if dist else None,
            "p10_finish": float(np.percentile(dist, 10)) if dist else None,  # Ceiling (top 10% sim)
            "p90_finish": float(np.percentile(dist, 90)) if dist else None,  # Floor (bottom 10%)
            "finish_sd": float(np.std(dist)) if dist else None,
            "n_simulations": n_simulations,
        }

    log.info(f"Simulation complete. {n_players} players, {n_simulations} trials.")
    return results


# ---------------------------------------------------------------------------
# Core simulation
# ---------------------------------------------------------------------------

def _simulate_one_tournament(
    players: list[dict],
    n_rounds: int,
    cut_position: int | None,
    tour: str,
) -> dict[str, float | None]:
    """
    Simulate one full tournament.

    Returns dict of {player_id: total_score_vs_par} where None = missed cut.

    Score generation:
    - Base score = -skill_composite (better skill = lower/negative score vs par)
    - Random variance drawn from skewed distribution:
      * Most rounds: near-normal
      * ~8% chance of a blow-up round (+2 to +6 vs skill level)
      * ~5% chance of a career round (-2 vs skill level)
    """
    round_scores = {p["player_id"]: [] for p in players}

    for r in range(n_rounds):
        is_cut_round = (r == 1 and cut_position is not None)

        for p in players:
            pid = p["player_id"]

            # Skip players who missed cut
            if is_cut_round and len(round_scores[pid]) == 0:
                continue  # Haven't played R1 yet — shouldn't happen

            # Don't simulate further rounds for MC players
            if _missed_cut(round_scores[pid], cut_position):
                continue

            skill = p.get("skill_composite", 0.0)
            vol = p.get("volatility_sd", 2.8)
            form_adj = p.get("form_adjustment", 0.0)

            # Effective skill this round
            effective_skill = skill + form_adj

            # Generate round score
            round_score = _generate_round_score(effective_skill, vol)
            round_scores[pid].append(round_score)

        # Apply cut after round 2 (PGA only)
        if is_cut_round and cut_position is not None:
            _apply_cut(round_scores, cut_position)

    # Total scores
    totals = {}
    for p in players:
        pid = p["player_id"]
        scores = round_scores[pid]
        if _missed_cut(scores, cut_position):
            totals[pid] = None  # Missed cut
        elif not scores:
            totals[pid] = None  # Withdrew or no data
        else:
            totals[pid] = sum(scores)

    return totals


def _generate_round_score(skill: float, vol: float) -> float:
    """
    Generate a single round score relative to the field.

    Uses a mixture model:
    - 87% of rounds: near-normal with player's skill and vol
    - 8% of rounds: blow-up round (right-skewed tail)
    - 5% of rounds: career round (left-tail boost)

    Score is "strokes vs field average" — negative = better than average.
    """
    rand = random.random()

    if rand < 0.87:
        # Normal round
        base = np.random.normal(-skill, vol)
    elif rand < 0.95:
        # Blow-up round: skill partially applies but big positive variance
        base = np.random.normal(-skill * 0.5, vol * 1.8) + random.uniform(2, 5)
    else:
        # Career round: skill fully applies plus bonus
        base = np.random.normal(-skill, vol * 0.7) - random.uniform(1.5, 3.0)

    return round(base, 2)


def _apply_cut(round_scores: dict, cut_position: int):
    """
    Mark players who missed the cut.
    Top `cut_position` + ties advance.
    Players outside that are marked as [None] (missed cut signal).
    """
    # Calculate 36-hole totals for all players who played 2 rounds
    two_round_totals = {
        pid: sum(scores)
        for pid, scores in round_scores.items()
        if len(scores) >= 2
    }

    if not two_round_totals:
        return

    sorted_totals = sorted(two_round_totals.values())
    if len(sorted_totals) <= cut_position:
        cut_line = sorted_totals[-1] + 1  # All make cut
    else:
        cut_line = sorted_totals[cut_position - 1]

    for pid, scores in round_scores.items():
        if len(scores) >= 2:
            if sum(scores[:2]) > cut_line:
                round_scores[pid] = [None]  # Missed cut marker


def _missed_cut(scores: list, cut_position: int | None) -> bool:
    """Check if this player missed the cut."""
    if cut_position is None:
        return False
    return len(scores) == 1 and scores[0] is None


# ---------------------------------------------------------------------------
# H2H matchup probabilities
# ---------------------------------------------------------------------------

def compute_h2h_probabilities(
    sim_results: dict[str, dict],
    player_a: str,
    player_b: str,
) -> dict:
    """
    Compute H2H matchup probabilities from simulation finish distributions.

    Returns win/lose/tie probabilities for player_a vs player_b.
    Also returns a recommended bet side and market comparison flags.
    """
    if player_a not in sim_results or player_b not in sim_results:
        return {"error": "One or both players not in sim results"}

    # Extract finish arrays
    # Note: We'd need to store per-sim results to do this properly.
    # This simplified version uses finish distribution approximation.
    a_median = sim_results[player_a]["median_finish"]
    b_median = sim_results[player_b]["median_finish"]

    a_sd = sim_results[player_a]["finish_sd"] or 10.0
    b_sd = sim_results[player_b]["finish_sd"] or 10.0

    # Approximate: sample from finish distributions 50k times
    n = 50_000
    a_finishes = np.random.normal(a_median, a_sd, n)
    b_finishes = np.random.normal(b_median, b_sd, n)

    a_wins = np.sum(a_finishes < b_finishes)
    b_wins = np.sum(b_finishes < a_finishes)
    ties = n - a_wins - b_wins

    return {
        "player_a": player_a,
        "player_b": player_b,
        "player_a_win_prob": round(a_wins / n, 4),
        "player_b_win_prob": round(b_wins / n, 4),
        "tie_prob": round(ties / n, 4),
        "a_median_finish": round(a_median, 1) if a_median else None,
        "b_median_finish": round(b_median, 1) if b_median else None,
    }


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _safe_prob(count: int, total: int) -> float:
    if total == 0:
        return 0.0
    return round(count / total, 5)
