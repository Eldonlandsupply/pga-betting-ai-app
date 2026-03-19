"""
features/recent_form.py
------------------------
Constructs recent form features for each player using a decayed
rolling window over their last 8 events.

Key design decisions:
- Uses exponential decay weights from model_weights.yaml form_decay config
- Separates "form trend" (improving/declining) from "form level" (absolute)
- Detects unsustainable hot streaks vs genuine improvement
- Regresses putting spikes toward long-term baseline
- Accounts for field strength of recent results
- Detects form driven by one weak field vs diverse strong fields
- Returns form_confidence to flag thin recent sample

The form score is measured in SG units relative to field average.
A form score of +2.0 means the player has been performing ~2 strokes
per round better than the field average across recent events.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import yaml

log = logging.getLogger(__name__)

with open("configs/model_weights.yaml") as f:
    _WCFG = yaml.safe_load(f)

_DECAY = _WCFG["form_decay"]  # e.g. {"event_1": 0.28, "event_2": 0.22, ...}
_PUTT_REGRESSION = 0.75       # Regress putting spikes by 25% toward baseline

MAX_FORM_EVENTS = 8


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def build_form_features(field: list[dict], stats: dict[str, Any]) -> dict[str, dict]:
    """
    Build recent form features for all players in field.

    Returns dict keyed by player_id.
    """
    results = {}
    for player in field:
        pid = player["id"]
        pstats = stats.get(pid)
        if not pstats:
            results[pid] = _null_form(pid)
            continue
        results[pid] = _compute_form(pid, pstats)

    log.info(f"Form features built for {len(results)} players.")
    return results


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _compute_form(pid: str, player_stats: dict) -> dict:
    """Compute decayed recent form for one player."""
    rounds = player_stats.get("rounds", [])
    if not rounds:
        return _null_form(pid)

    # Group rounds into events (most recent first)
    events = _group_into_events(rounds)
    if not events:
        return _null_form(pid)

    recent_events = events[:MAX_FORM_EVENTS]

    # Compute per-event SG averages
    event_sgs = []
    for ev in recent_events:
        ev_sg = _event_sg_average(ev)
        if ev_sg is not None:
            event_sgs.append({
                "event_id": ev[0].get("event_id", "unknown"),
                "sg_total": ev_sg["sg_total"],
                "sg_putt":  ev_sg["sg_putt"],
                "sg_app":   ev_sg["sg_app"],
                "field_strength_pct": ev[0].get("field_strength_percentile", 50),
                "n_rounds": len(ev),
            })

    if not event_sgs:
        return _null_form(pid)

    # Apply decay weights
    decay_keys = [f"event_{i+1}" for i in range(len(event_sgs))]
    weights = [_DECAY.get(k, 0.01) for k in decay_keys]

    # Field-strength adjustment: weight strong-field events higher
    fs_adjustments = [_fs_weight(e["field_strength_pct"]) for e in event_sgs]
    combined_weights = [w * fs for w, fs in zip(weights, fs_adjustments)]
    total_w = sum(combined_weights)

    if total_w < 1e-6:
        return _null_form(pid)

    # Weighted form SG (before putting regression)
    raw_form_sg = sum(e["sg_total"] * w for e, w in zip(event_sgs, combined_weights)) / total_w

    # Putting regression: regress toward long-term baseline
    baseline_putt = player_stats.get("sg_putt", 0.0) or 0.0
    recent_putt_avg = sum(e["sg_putt"] * w for e, w in zip(event_sgs, combined_weights)) / total_w
    regressed_putt = _regress_putting(recent_putt_avg, baseline_putt)
    putt_correction = regressed_putt - recent_putt_avg

    form_adjusted_sg = raw_form_sg + putt_correction

    # Form trend: comparing first half vs second half of recent window
    form_trend, trend_magnitude = _compute_form_trend(event_sgs, combined_weights)

    # Hot streak detection
    streak_length, is_hot_streak = _detect_hot_streak(event_sgs)

    # Weak-field inflation check
    weak_field_driven = _check_weak_field_inflation(event_sgs)

    # Form confidence: driven by n_events and field quality
    n_events_used = len(event_sgs)
    avg_field_str = sum(e["field_strength_pct"] for e in event_sgs) / n_events_used
    form_confidence = _form_confidence(n_events_used, avg_field_str)

    # Form driven flag (for adversarial review)
    form_driven = form_confidence > 0.6 and abs(form_adjusted_sg - (player_stats.get("sg_total") or 0)) > 0.5

    return {
        "player_id":           pid,
        "form_adjusted_sg":    round(form_adjusted_sg, 4),
        "raw_form_sg":         round(raw_form_sg, 4),
        "recent_putt_avg":     round(recent_putt_avg, 4),
        "regressed_putt":      round(regressed_putt, 4),
        "putting_regression_applied": round(putt_correction, 4),
        "form_trend":          form_trend,         # "improving", "declining", "stable"
        "trend_magnitude":     round(trend_magnitude, 4),
        "streak_length":       streak_length,
        "hot_streak_flag":     is_hot_streak,
        "weak_field_driven":   weak_field_driven,
        "n_events_used":       n_events_used,
        "avg_field_strength":  round(avg_field_str, 1),
        "form_confidence":     round(form_confidence, 3),
        "form_driven":         form_driven,
        "recent_event_log":    event_sgs,
    }


def _event_sg_average(rounds: list[dict]) -> dict | None:
    """Average SG values across all rounds in an event."""
    sg_fields = ["sg_total", "sg_ott", "sg_app", "sg_atg", "sg_putt"]
    totals = {f: [] for f in sg_fields}

    for r in rounds:
        for f in sg_fields:
            val = r.get(f)
            if val is not None:
                totals[f].append(val)

    result = {}
    for f in sg_fields:
        result[f] = sum(totals[f]) / len(totals[f]) if totals[f] else None

    if result.get("sg_total") is None and result.get("sg_app") is None:
        return None
    return result


def _regress_putting(recent: float, baseline: float) -> float:
    """
    Regress recent putting toward long-term baseline.
    Stronger regression for extreme values (>1.5 SD from baseline).
    """
    delta = recent - baseline
    # Hard regression: pull extreme spikes back harder
    if abs(delta) > 1.0:
        regression_rate = 0.65   # Regress 65% of extreme putting spikes
    else:
        regression_rate = _PUTT_REGRESSION
    return baseline + delta * (1 - regression_rate)


def _compute_form_trend(event_sgs: list, weights: list) -> tuple[str, float]:
    """
    Detect whether player is improving, declining, or stable.
    Compares weighted average of recent 3 events vs earlier 3–6 events.
    """
    if len(event_sgs) < 4:
        return "stable", 0.0

    recent_half = event_sgs[:3]
    older_half  = event_sgs[3:min(6, len(event_sgs))]
    recent_w    = weights[:3]
    older_w     = weights[3:min(6, len(weights))]

    recent_avg = sum(e["sg_total"] * w for e, w in zip(recent_half, recent_w)) / sum(recent_w)
    older_avg  = sum(e["sg_total"] * w for e, w in zip(older_half,  older_w))  / sum(older_w)

    delta = recent_avg - older_avg

    if delta > 0.30:
        return "improving", round(delta, 4)
    elif delta < -0.30:
        return "declining", round(delta, 4)
    return "stable", round(delta, 4)


def _detect_hot_streak(event_sgs: list) -> tuple[int, bool]:
    """
    Detect a hot streak: consecutive above-average performances.
    Returns (streak_length, is_concerning_short_streak).
    """
    streak = 0
    for ev in event_sgs:
        if ev["sg_total"] > 1.0:   # > 1 stroke above field average = "hot"
            streak += 1
        else:
            break

    # Concerning if hot streak is very short (1–2 events) and form_driven
    is_concerning = streak in (1, 2)
    return streak, is_concerning


def _check_weak_field_inflation(event_sgs: list) -> bool:
    """
    Flag if most of the recent positive form came in weak fields.
    Risk: performance may not translate to this week's field.
    """
    if len(event_sgs) < 2:
        return False
    weak_field_sgs = [e["sg_total"] for e in event_sgs if e["field_strength_pct"] < 40]
    strong_field_sgs = [e["sg_total"] for e in event_sgs if e["field_strength_pct"] >= 60]

    if not weak_field_sgs or not strong_field_sgs:
        return False

    weak_avg   = sum(weak_field_sgs)   / len(weak_field_sgs)
    strong_avg = sum(strong_field_sgs) / len(strong_field_sgs)

    # Flag if weak-field average is >1 stroke better than strong-field average
    return (weak_avg - strong_avg) > 1.0


def _group_into_events(rounds: list[dict]) -> list[list[dict]]:
    """Group rounds by event_id, sorted most recent first."""
    event_map: dict[str, list] = {}
    for r in rounds:
        eid = r.get("event_id", "unknown")
        event_map.setdefault(eid, []).append(r)

    # Sort events by most recent round date within each event
    def event_date(rounds_list):
        dates = [r.get("date", "") for r in rounds_list if r.get("date")]
        return max(dates) if dates else ""

    sorted_events = sorted(event_map.values(), key=event_date, reverse=True)
    return sorted_events


def _fs_weight(percentile: int) -> float:
    """Convert field strength percentile to weight multiplier (0.75–1.20)."""
    return 0.75 + 0.45 * (percentile / 100)


def _form_confidence(n_events: int, avg_field_str: float) -> float:
    """
    Form confidence = combination of:
    - How many events we have (more = higher confidence up to 8)
    - Average field strength (stronger fields = more reliable signal)
    """
    event_conf = min(1.0, n_events / MAX_FORM_EVENTS)
    field_conf  = 0.6 + 0.4 * (avg_field_str / 100)
    return round(event_conf * field_conf, 3)


def _null_form(pid: str) -> dict:
    return {
        "player_id":        pid,
        "form_adjusted_sg": None,
        "raw_form_sg":      None,
        "form_trend":       "unknown",
        "trend_magnitude":  0.0,
        "streak_length":    0,
        "hot_streak_flag":  False,
        "weak_field_driven":False,
        "n_events_used":    0,
        "form_confidence":  0.0,
        "form_driven":      False,
        "recent_event_log": [],
    }
