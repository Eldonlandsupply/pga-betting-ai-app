"""
features/contextual_flags.py
-----------------------------
Builds contextual adjustment features:
- Injury and fitness flags
- Rust (long layoff) penalty
- Travel / timezone burden
- Schedule load (too many events recently)
- Weather risk flag (course-level, not player-level)
- Motivational context flags (use sparingly, evidence-only)

Rules:
- Never invent injury data — only apply if a flag is explicitly provided
- Travel penalties are applied only when we have itinerary evidence
- Schedule load is a small penalty for 4+ events in the last 5 weeks
- No motivational adjustments without 3+ seasons of supporting data
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger(__name__)


# Penalty values (in SG-like units, negative = hurts the player)
_INJURY_PENALTIES = {
    "confirmed_out":   -99.0,   # Not in field — shouldn't appear but safeguard
    "severe":          -1.20,
    "moderate":        -0.60,
    "minor":           -0.25,
    "unverified":      -0.35,   # Uncertainty penalty
    "managing":        -0.15,
    "healthy":          0.00,
}
_RUST_PENALTY        = -0.20   # 5+ weeks since last competitive round
_HEAVY_SCHEDULE_PENALTY = -0.10  # 4+ events in last 5 weeks
_TRAVEL_PENALTY_MAX  = -0.18   # Maximum travel burden penalty


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def build_contextual_flags(field: list[dict]) -> dict[str, dict]:
    """
    Build contextual adjustment features for all players.

    Args:
        field: list of player dicts (with injury_flag, last_event_date, etc.)

    Returns:
        dict keyed by player_id
    """
    results = {}
    for player in field:
        pid = player["id"]
        results[pid] = _compute_context(pid, player)
    log.info(f"Contextual flags built for {len(results)} players.")
    return results


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _compute_context(pid: str, player: dict) -> dict:
    """Compute contextual adjustments for one player."""
    adjustments = []
    flags = []

    # --- INJURY ---
    injury_status = player.get("injury_status", "healthy") or "healthy"
    injury_penalty = _INJURY_PENALTIES.get(injury_status.lower(), -0.20)
    if injury_penalty < 0:
        adjustments.append(injury_penalty)
        flags.append(f"injury:{injury_status}")
    injury_flag = injury_status if injury_status.lower() not in ("healthy", "none") else None

    # --- RUST ---
    last_event_date = player.get("last_event_date")
    weeks_since_last = _weeks_since(last_event_date)
    rust_flag = False
    if weeks_since_last is not None and weeks_since_last >= 5:
        adjustments.append(_RUST_PENALTY)
        flags.append(f"rust:{weeks_since_last:.1f}_weeks")
        rust_flag = True
        log.debug(f"  {pid}: rust penalty ({weeks_since_last:.1f} weeks off)")

    # --- SCHEDULE LOAD ---
    recent_event_count = player.get("recent_event_count_5w", 0) or 0
    schedule_flag = False
    if recent_event_count >= 4:
        adjustments.append(_HEAVY_SCHEDULE_PENALTY)
        flags.append(f"heavy_schedule:{recent_event_count}_events_in_5w")
        schedule_flag = True

    # --- TRAVEL ---
    travel_burden = player.get("travel_burden_score", 0.0) or 0.0
    travel_penalty = -min(abs(travel_burden), abs(_TRAVEL_PENALTY_MAX))
    if travel_penalty < -0.05:
        adjustments.append(travel_penalty)
        flags.append(f"travel:burden={travel_burden:.2f}")

    # --- WEATHER RISK ---
    weather_risk_flag = player.get("weather_risk_flag", False)

    # Total contextual adjustment
    total_adjustment = sum(adjustments)

    return {
        "player_id":             pid,
        "contextual_adjustment": round(total_adjustment, 4),
        "injury_flag":           injury_flag,
        "injury_penalty":        round(injury_penalty, 4),
        "rust_flag":             rust_flag,
        "weeks_since_last_event":weeks_since_last,
        "schedule_flag":         schedule_flag,
        "recent_event_count_5w": recent_event_count,
        "travel_penalty":        round(travel_penalty, 4),
        "weather_risk_flag":     weather_risk_flag,
        "all_flags":             flags,
    }


def _weeks_since(date_str: str | None) -> float | None:
    """Compute weeks since a given date string (YYYY-MM-DD)."""
    if not date_str:
        return None
    try:
        parts = date_str.split("-")
        event_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        delta = date.today() - event_date
        return delta.days / 7.0
    except Exception:
        return None
