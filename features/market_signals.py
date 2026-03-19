"""
features/market_signals.py
---------------------------
Extracts market-based signals to overlay on model output.

Market signals are NOT the primary driver of picks.
They serve two purposes:
  1. Validation: confirm or challenge model output with market intelligence
  2. Adjustment: add a small edge signal when sharp books have moved

Sharp vs recreational book divergence is the most actionable signal.
Line movement direction and magnitude is secondary.
CLV track record provides a confidence adjustment for repeat bets.

All market signals are bounded to prevent them from dominating the ensemble.
The maximum market signal contribution to composite score is capped.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Market signal contribution cap (SG-like units)
_MAX_MARKET_SIGNAL = 0.50
_MIN_MARKET_SIGNAL = -0.50


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def build_market_signals(
    field: list[dict],
    markets: dict[str, Any],
) -> dict[str, dict]:
    """
    Build market signal features for all players.

    Args:
        field: list of player dicts
        markets: tracked market data from line_tracker.py

    Returns:
        dict keyed by player_id with market signal features
    """
    results = {}
    for player in field:
        pid = player["id"]
        player_markets = _extract_player_markets(pid, markets)
        results[pid] = _compute_market_signal(pid, player_markets)

    log.info(f"Market signals built for {len(results)} players.")
    return results


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _compute_market_signal(pid: str, player_markets: dict) -> dict:
    """Compute the market edge signal for one player."""

    # Aggregate signals across all market types we have for this player
    sharp_signals = []
    movement_signals = []
    disagreement_signals = []
    stale_flags = []

    for market_type, tracker in player_markets.items():
        if not tracker:
            continue

        # Sharp signal: positive if sharp books have this player shorter than rec books
        sharp = tracker.get("sharp_signal", False)
        sharp_avg = tracker.get("sharp_avg_implied")
        rec_avg   = tracker.get("rec_avg_implied")

        if sharp and sharp_avg and rec_avg:
            # How much are sharp books disagreeing with rec books?
            sharp_delta = sharp_avg - rec_avg
            # Positive sharp_delta = sharp books have higher implied prob = following sharp money
            sharp_signals.append(sharp_delta)

        # Movement: line shortening toward player = market backing them
        movement = tracker.get("line_movement_pct")
        if movement is not None:
            movement_signals.append(movement)

        # Disagreement: high disagreement = potential opportunity
        disagreement = tracker.get("book_disagreement_score", 0)
        disagreement_signals.append(disagreement)

        # Stale flag
        if tracker.get("is_stale"):
            stale_flags.append(market_type)

    # --- Aggregate into single market edge signal ---
    market_edge = 0.0

    # Sharp signal component (most important)
    if sharp_signals:
        avg_sharp = sum(sharp_signals) / len(sharp_signals)
        # Scale: a 5% sharp/rec divergence = +0.20 signal
        sharp_component = min(0.30, max(-0.30, avg_sharp * 4.0))
        market_edge += sharp_component

    # Movement component (secondary)
    if movement_signals:
        avg_movement = sum(movement_signals) / len(movement_signals)
        # Shortening line = slight positive (market agrees with us)
        movement_component = min(0.15, max(-0.15, avg_movement * 1.5))
        market_edge += movement_component

    # Disagreement bonus: high book disagreement = potential market inefficiency
    if disagreement_signals:
        avg_disagreement = sum(disagreement_signals) / len(disagreement_signals)
        if avg_disagreement > 0.04:  # 4% SD across books
            market_edge += 0.05

    # Cap the signal
    market_edge = max(_MIN_MARKET_SIGNAL, min(_MAX_MARKET_SIGNAL, market_edge))

    # Ownership proxy (simplified: infer from sharp vs rec book spread)
    ownership_proxy = _estimate_ownership(sharp_signals, movement_signals)

    # Is there a dominant market type with the best signal?
    best_market_signal = _find_best_market_signal(player_markets)

    return {
        "player_id":            pid,
        "market_edge_signal":   round(market_edge, 5),
        "sharp_signals":        sharp_signals,
        "avg_sharp_delta":      round(sum(sharp_signals)/len(sharp_signals), 5) if sharp_signals else None,
        "avg_line_movement":    round(sum(movement_signals)/len(movement_signals), 5) if movement_signals else None,
        "avg_book_disagreement":round(sum(disagreement_signals)/len(disagreement_signals), 5) if disagreement_signals else 0.0,
        "stale_market_flags":   stale_flags,
        "ownership_proxy":      round(ownership_proxy, 3),
        "best_market_signal":   best_market_signal,
        "has_sharp_signal":     len(sharp_signals) > 0,
        "market_movement_flag": _classify_market_stance(market_edge),
    }


def _estimate_ownership(sharp_signals: list, movement_signals: list) -> float:
    """
    Estimate public ownership proxy (0 = faded, 1 = heavily backed).
    High ownership often means the line has been bet down — less value.
    """
    base = 0.5  # Neutral
    if movement_signals:
        avg_move = sum(movement_signals) / len(movement_signals)
        # Lines shortening a lot = heavily backed by public
        base += min(0.4, avg_move * 2.0)
    # Sharp money counters public (negative sharp_delta = sharp fading a public favorite)
    if sharp_signals:
        avg_sharp = sum(sharp_signals) / len(sharp_signals)
        if avg_sharp < -0.03:
            base += 0.15   # Public backed but sharp fading = high ownership play
    return max(0.0, min(1.0, base))


def _find_best_market_signal(player_markets: dict) -> dict | None:
    """Find the market type with the strongest actionable signal."""
    best = None
    best_score = 0.0
    for market_type, tracker in player_markets.items():
        if not tracker:
            continue
        sharp = tracker.get("sharp_signal", False)
        disagreement = tracker.get("book_disagreement_score", 0)
        score = (0.6 if sharp else 0.0) + disagreement * 5
        if score > best_score:
            best_score = score
            best = {
                "market_type": market_type,
                "best_price":  tracker.get("best_price"),
                "best_book":   tracker.get("best_book"),
                "sharp":       sharp,
                "signal_score":round(score, 3),
            }
    return best


def _classify_market_stance(edge: float) -> str:
    """Human-readable classification of market signal."""
    if edge > 0.20:
        return "strong_sharp_backing"
    elif edge > 0.08:
        return "mild_sharp_backing"
    elif edge < -0.20:
        return "sharp_fading"
    elif edge < -0.08:
        return "mild_sharp_fade"
    return "neutral"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _extract_player_markets(pid: str, markets: dict) -> dict:
    """
    Extract all market trackers for a given player from the markets dict.
    markets structure: {player_id: {market_type: tracker_dict}}
    """
    return markets.get(pid, {})
