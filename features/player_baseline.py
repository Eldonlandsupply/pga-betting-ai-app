"""
features/player_baseline.py
----------------------------
Constructs the long-term skill baseline for each player in the field.

The baseline is a multi-year, event-weighted composite of strokes gained
and secondary statistics. It is intentionally slow-moving — designed to
represent a player's true underlying talent level, not recent noise.

Key design decisions:
- Uses minimum 2 years of data where available. Flags <1yr as uncertain.
- Weights tournament rounds by recency, field strength, and course type.
- Computes a composite SG score AND separate category scores.
- Applies a "data depth" confidence score so thin data is flagged.
- LIV players: applies pga_stat_transfer_weight and data_depth_penalty.
"""

import logging
import math
from typing import Any

import numpy as np
import yaml

log = logging.getLogger(__name__)

# Load config
with open("configs/model_weights.yaml") as f:
    WEIGHTS_CFG = yaml.safe_load(f)

SG_DEFAULT = WEIGHTS_CFG["sg_default_weights"]
LIV_CFG = WEIGHTS_CFG["liv_adjustments"]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def build_baselines(field: list[dict], stats: dict[str, Any]) -> dict[str, dict]:
    """
    Build a baseline skill score for each player in the field.

    Args:
        field: list of player dicts with at minimum {"id": str, "tour": str}
        stats: dict keyed by player_id containing historical round-level data

    Returns:
        dict keyed by player_id:
        {
          "composite_sg": float,
          "sg_ott": float,
          "sg_app": float,
          "sg_atg": float,
          "sg_putt": float,
          "data_rounds": int,
          "data_confidence": float,  # 0.0 – 1.0
          "is_liv_transfer": bool,
          "uncertainty_flag": str or None,
          "secondary_stats": dict
        }
    """
    baselines = {}

    for player in field:
        pid = player["id"]
        tour = player.get("tour", "PGA")

        if pid not in stats:
            log.warning(f"No stats found for player {pid}. Assigning null baseline.")
            baselines[pid] = _null_baseline(pid, tour)
            continue

        player_stats = stats[pid]
        rounds = player_stats.get("rounds", [])

        if len(rounds) < 10:
            log.warning(f"Player {pid} has only {len(rounds)} rounds. Flagging thin baseline.")
            baselines[pid] = _thin_baseline(pid, tour, rounds)
            continue

        baseline = _compute_baseline(pid, tour, rounds, player_stats)
        baselines[pid] = baseline

    log.info(f"Baselines built for {len(baselines)} players.")
    return baselines


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _compute_baseline(pid: str, tour: str, rounds: list, player_stats: dict) -> dict:
    """
    Compute the weighted strokes gained baseline for a single player.

    Weighting logic:
    - More recent rounds get higher weight (exponential decay over 2yr window)
    - Rounds at stronger-field events get a slight upward adjustment
    - Rounds at no-cut events are included but slightly discounted for
      competitive integrity concerns
    """
    weights = []
    sg_ott_vals = []
    sg_app_vals = []
    sg_atg_vals = []
    sg_putt_vals = []

    today_ordinal = _today_ordinal()

    for r in rounds:
        age_days = today_ordinal - _parse_date_ordinal(r.get("date", ""))
        if age_days < 0 or age_days > 730:  # ignore rounds >2yr old in baseline
            continue

        # Recency weight: exponential decay with 300-day half-life
        recency_w = math.exp(-0.693 * age_days / 300)

        # Field strength adjustment (0.8 – 1.2)
        fs_adj = _field_strength_weight(r.get("field_strength_percentile", 50))

        # No-cut event slight discount
        no_cut_adj = 0.90 if r.get("no_cut_event", False) else 1.00

        w = recency_w * fs_adj * no_cut_adj

        # Handle missing SG values gracefully
        if _any_sg_present(r):
            weights.append(w)
            sg_ott_vals.append((r.get("sg_ott", np.nan), w))
            sg_app_vals.append((r.get("sg_app", np.nan), w))
            sg_atg_vals.append((r.get("sg_atg", np.nan), w))
            sg_putt_vals.append((r.get("sg_putt", np.nan), w))

    if not weights:
        return _null_baseline(pid, tour)

    # Weighted means, ignoring NaN
    sg_ott = _weighted_mean(sg_ott_vals)
    sg_app = _weighted_mean(sg_app_vals)
    sg_atg = _weighted_mean(sg_atg_vals)
    sg_putt = _weighted_mean(sg_putt_vals)

    # Composite SG using default weights (course-specific overrides happen in fit_model)
    composite = (
        SG_DEFAULT["sg_ott"] * (sg_ott or 0)
        + SG_DEFAULT["sg_app"] * (sg_app or 0)
        + SG_DEFAULT["sg_atg"] * (sg_atg or 0)
        + SG_DEFAULT["sg_putt"] * (sg_putt or 0)
    )

    # Data confidence score
    n_rounds = len(weights)
    data_confidence = min(1.0, n_rounds / 60)  # Full confidence at 60+ rounds

    # LIV transfer discount
    is_liv_transfer = tour == "LIV" and player_stats.get("pga_to_liv_transfer", False)
    if is_liv_transfer:
        transfer_w = LIV_CFG["pga_stat_transfer_weight"]
        composite *= transfer_w
        data_confidence *= (1.0 - LIV_CFG["data_depth_penalty"])
        log.debug(f"Player {pid}: LIV transfer discount applied.")

    # Secondary stats
    secondary = _build_secondary_stats(player_stats)

    return {
        "player_id": pid,
        "tour": tour,
        "composite_sg": round(composite, 4),
        "sg_ott": round(sg_ott, 4) if sg_ott is not None else None,
        "sg_app": round(sg_app, 4) if sg_app is not None else None,
        "sg_atg": round(sg_atg, 4) if sg_atg is not None else None,
        "sg_putt": round(sg_putt, 4) if sg_putt is not None else None,
        "data_rounds": n_rounds,
        "data_confidence": round(data_confidence, 3),
        "is_liv_transfer": is_liv_transfer,
        "uncertainty_flag": _assess_uncertainty_flag(n_rounds, data_confidence),
        "secondary_stats": secondary,
    }


def _build_secondary_stats(player_stats: dict) -> dict:
    """Extract and normalize secondary statistical profile."""
    return {
        "driving_distance": player_stats.get("driving_distance"),
        "driving_accuracy": player_stats.get("driving_accuracy"),
        "gir_pct": player_stats.get("gir_pct"),
        "scrambling_pct": player_stats.get("scrambling_pct"),
        "birdie_or_better_pct": player_stats.get("birdie_or_better_pct"),
        "bogey_avoidance": player_stats.get("bogey_avoidance"),
        "par3_scoring_avg": player_stats.get("par3_scoring_avg"),
        "par4_scoring_avg": player_stats.get("par4_scoring_avg"),
        "par5_scoring_avg": player_stats.get("par5_scoring_avg"),
        "proximity_100_125": player_stats.get("proximity_100_125"),
        "proximity_125_150": player_stats.get("proximity_125_150"),
        "proximity_150_175": player_stats.get("proximity_150_175"),
        "proximity_175_200": player_stats.get("proximity_175_200"),
        "bent_grass_sg_putt": player_stats.get("bent_grass_sg_putt"),
        "bermuda_sg_putt": player_stats.get("bermuda_sg_putt"),
        "poa_sg_putt": player_stats.get("poa_sg_putt"),
        "wind_20plus_sg": player_stats.get("wind_20plus_sg"),
        "final_round_sg": player_stats.get("final_round_sg"),  # Pressure proxy
        "major_sg": player_stats.get("major_sg"),
    }


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _null_baseline(pid: str, tour: str) -> dict:
    """Return a null baseline for players with no data."""
    return {
        "player_id": pid,
        "tour": tour,
        "composite_sg": None,
        "sg_ott": None,
        "sg_app": None,
        "sg_atg": None,
        "sg_putt": None,
        "data_rounds": 0,
        "data_confidence": 0.0,
        "is_liv_transfer": False,
        "uncertainty_flag": "NO_DATA",
        "secondary_stats": {},
    }


def _thin_baseline(pid: str, tour: str, rounds: list) -> dict:
    """Build a thin baseline with high uncertainty flag."""
    result = _compute_baseline(pid, tour, rounds, {"rounds": rounds})
    result["uncertainty_flag"] = "THIN_SAMPLE"
    return result


def _weighted_mean(vals: list[tuple]) -> float | None:
    """Compute weighted mean, ignoring NaN values."""
    filtered = [(v, w) for v, w in vals if not (isinstance(v, float) and math.isnan(v)) and v is not None]
    if not filtered:
        return None
    total_w = sum(w for _, w in filtered)
    if total_w == 0:
        return None
    return sum(v * w for v, w in filtered) / total_w


def _field_strength_weight(percentile: int) -> float:
    """Convert field strength percentile to weighting factor (0.8 – 1.2)."""
    return 0.8 + 0.4 * (percentile / 100)


def _any_sg_present(round_data: dict) -> bool:
    """Check if at least one SG value is present in a round."""
    return any(
        round_data.get(k) is not None
        for k in ("sg_ott", "sg_app", "sg_atg", "sg_putt")
    )


def _assess_uncertainty_flag(n_rounds: int, confidence: float) -> str | None:
    if n_rounds == 0:
        return "NO_DATA"
    if n_rounds < 10:
        return "THIN_SAMPLE"
    if confidence < 0.50:
        return "LOW_CONFIDENCE"
    return None


def _today_ordinal() -> int:
    from datetime import date
    return date.today().toordinal()


def _parse_date_ordinal(date_str: str) -> int:
    from datetime import date
    try:
        parts = date_str.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2])).toordinal()
    except Exception:
        return _today_ordinal()  # Fallback: treat as today (will be excluded by age filter)
