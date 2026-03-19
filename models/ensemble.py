"""
models/ensemble.py
-------------------
Final ensemble scorer combining all feature families into a single
per-player composite score with full transparency breakdown.

Every player's score is decomposable — you can trace exactly how much
each signal family contributed and why.

Flow:
  1. Load feature vectors from all 6 signal families
  2. Apply current config weights (model_weights.yaml)
  3. Apply event-specific adjustments (tournament type, course, format)
  4. Produce composite score per player
  5. Normalize into relative probabilities
  6. Apply market-signal overlay as an adjustment layer
  7. Return full attribution breakdown per player
"""

from __future__ import annotations

import logging
from typing import Any

import yaml

log = logging.getLogger(__name__)

with open("configs/model_weights.yaml") as f:
    _WCFG = yaml.safe_load(f)

_GW = _WCFG["global_weights"]
_PGA = _WCFG["pga_adjustments"]
_LIV = _WCFG["liv_adjustments"]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run_ensemble(event_id: str, features: dict[str, dict]) -> dict[str, dict]:
    """
    Run the full ensemble model for all players.

    Args:
        event_id: event identifier
        features: dict keyed by family name, each a dict keyed by player_id:
            "baseline"      → player_baseline.py output
            "form"          → recent_form.py output
            "course_fit"    → course_fit.py output
            "volatility"    → volatility.py output
            "market_signals"→ market_signals.py output
            "contextual"    → contextual_flags.py output

    Returns:
        dict keyed by player_id with full model output per player
    """
    baselines = features.get("baseline", {})
    form = features.get("form", {})
    course_fit = features.get("course_fit", {})
    volatility = features.get("volatility", {})
    market = features.get("market_signals", {})
    contextual = features.get("contextual", {})

    all_pids = set(baselines) | set(form) | set(course_fit)
    log.info(f"Running ensemble for {len(all_pids)} players | event={event_id}")

    raw_scores: dict[str, dict] = {}
    for pid in all_pids:
        raw_scores[pid] = _score_player(
            pid,
            baselines.get(pid, {}),
            form.get(pid, {}),
            course_fit.get(pid, {}),
            volatility.get(pid, {}),
            market.get(pid, {}),
            contextual.get(pid, {}),
        )

    # Normalize composite scores into relative win probabilities
    outputs = _normalize_to_probabilities(raw_scores)
    log.info(f"Ensemble complete. Top player: {_top_player(outputs)}")
    return outputs


# ---------------------------------------------------------------------------
# Per-player scoring
# ---------------------------------------------------------------------------

def _score_player(
    pid: str,
    baseline: dict,
    form: dict,
    course_fit: dict,
    volatility: dict,
    market: dict,
    contextual: dict,
) -> dict:
    """Compute weighted composite score for one player."""

    # --- Component scores (all on a common SG-like scale) ---
    s_baseline = baseline.get("composite_sg") or 0.0
    s_form = form.get("form_adjusted_sg") or 0.0
    s_course = course_fit.get("course_fit_score") or 0.0
    s_vol = volatility.get("consistency_score") or 0.0   # Higher = more consistent
    s_market = market.get("market_edge_signal") or 0.0   # Positive = sharp money backing
    s_context = contextual.get("contextual_adjustment") or 0.0  # Injury penalty etc.

    # --- Ownership / crowding discount ---
    ownership = market.get("ownership_proxy", 0.5)  # 0 = faded, 1 = heavily backed
    s_ownership = _ownership_discount(ownership)

    # --- Data confidence (used to blend toward field average when thin) ---
    data_conf = baseline.get("data_confidence", 0.5)
    form_conf = form.get("form_confidence", 0.5)

    # --- Weighted composite ---
    w = _GW
    composite = (
        w["skill_baseline"]      * s_baseline * data_conf
        + w["recent_form"]       * s_form     * form_conf
        + w["course_fit"]        * s_course
        + w["volatility_profile"]* s_vol
        + w["market_signal"]     * s_market
        + w["contextual_flags"]  * s_context
        + w["ownership_discount"]* s_ownership
    )

    # --- Tour-specific multiplier ---
    tour = baseline.get("tour", "PGA")
    composite = _apply_tour_adjustment(composite, tour)

    # --- Signal diversity (how many families contributed meaningfully) ---
    contributing = sum([
        abs(s_baseline) > 0.05,
        abs(s_form)     > 0.05,
        abs(s_course)   > 0.05,
        abs(s_vol)      > 0.02,
        abs(s_market)   > 0.02,
        abs(s_context)  > 0.02,
    ])
    signal_diversity = round(contributing / 6, 3)

    # --- Dominant signal (for adversarial review) ---
    contributions = {
        "baseline":   abs(w["skill_baseline"]       * s_baseline * data_conf),
        "form":       abs(w["recent_form"]           * s_form     * form_conf),
        "course_fit": abs(w["course_fit"]            * s_course),
        "volatility": abs(w["volatility_profile"]    * s_vol),
        "market":     abs(w["market_signal"]         * s_market),
        "contextual": abs(w["contextual_flags"]      * s_context),
    }
    dominant_signal = max(contributions, key=contributions.get)
    dominant_pct = (
        contributions[dominant_signal] / sum(contributions.values())
        if sum(contributions.values()) > 0 else 0
    )

    # --- Uncertainty flag ---
    uncertainty_flag = baseline.get("uncertainty_flag")
    if form.get("form_confidence", 1.0) < 0.30:
        uncertainty_flag = uncertainty_flag or "THIN_FORM_DATA"

    return {
        "player_id":          pid,
        "tour":               tour,
        "composite_score":    round(composite, 5),
        "signal_breakdown": {
            "baseline_contribution":   round(w["skill_baseline"] * s_baseline * data_conf, 5),
            "form_contribution":       round(w["recent_form"]    * s_form     * form_conf, 5),
            "course_fit_contribution": round(w["course_fit"]     * s_course,               5),
            "volatility_contribution": round(w["volatility_profile"] * s_vol,              5),
            "market_contribution":     round(w["market_signal"]  * s_market,               5),
            "contextual_contribution": round(w["contextual_flags"]* s_context,             5),
        },
        "raw_components": {
            "s_baseline": round(s_baseline, 4),
            "s_form":     round(s_form, 4),
            "s_course":   round(s_course, 4),
            "s_vol":      round(s_vol, 4),
            "s_market":   round(s_market, 4),
            "s_context":  round(s_context, 4),
        },
        "data_confidence":    round(data_conf, 3),
        "form_confidence":    round(form_conf, 3),
        "signal_diversity_score": signal_diversity,
        "dominant_signal":    dominant_signal,
        "dominant_signal_pct": round(dominant_pct, 3),
        "uncertainty_flag":   uncertainty_flag,
        # Pass through key sub-model outputs for downstream use
        "composite_sg":       baseline.get("composite_sg"),
        "sg_ott":             baseline.get("sg_ott"),
        "sg_app":             baseline.get("sg_app"),
        "sg_atg":             baseline.get("sg_atg"),
        "sg_putt":            baseline.get("sg_putt"),
        "course_fit_score":   course_fit.get("course_fit_score"),
        "course_fit_summary": course_fit.get("course_fit_summary"),
        "form_trend":         form.get("form_trend"),
        "volatility_tier":    volatility.get("volatility_tier"),
        "injury_flag":        contextual.get("injury_flag"),
        "comp_course_rounds": course_fit.get("comp_course_rounds", 0),
        "world_rank":         baseline.get("world_rank"),
        "data_rounds":        baseline.get("data_rounds", 0),
        "form_streak_events": form.get("streak_length", 0),
        "form_driven":        form.get("form_driven", False),
        "weather_risk_flag":  contextual.get("weather_risk_flag", False),
        "risk_flags":         _collect_risk_flags(baseline, form, course_fit, contextual),
    }


def _apply_tour_adjustment(score: float, tour: str) -> float:
    """Apply tour-specific score multiplier."""
    if tour == "LIV":
        return score * _LIV["field_strength_factor"]
    return score * _PGA["field_strength_factor"]


def _ownership_discount(ownership: float) -> float:
    """
    Apply a small discount for highly owned (public-backed) players.
    Returns a negative adjustment for ownership > 0.65 (crowded bets).
    """
    if ownership > 0.65:
        return -(ownership - 0.65) * 0.3
    return 0.0


def _collect_risk_flags(baseline: dict, form: dict, course_fit: dict, contextual: dict) -> list[str]:
    """Aggregate all risk flags from across feature families."""
    flags = []
    if baseline.get("uncertainty_flag"):
        flags.append(f"baseline:{baseline['uncertainty_flag']}")
    if form.get("form_confidence", 1.0) < 0.35:
        flags.append("form:thin_sample")
    if course_fit.get("fit_confidence", 1.0) < 0.40:
        flags.append("course_fit:low_confidence")
    if contextual.get("injury_flag"):
        flags.append(f"injury:{contextual['injury_flag']}")
    if contextual.get("rust_flag"):
        flags.append("context:rust_flag")
    if contextual.get("weather_risk_flag"):
        flags.append("context:weather_unresolved")
    return flags


# ---------------------------------------------------------------------------
# Normalization to probabilities
# ---------------------------------------------------------------------------

def _normalize_to_probabilities(raw_scores: dict[str, dict]) -> dict[str, dict]:
    """
    Convert composite scores to relative probabilities using softmax.
    Also computes placement probabilities by field position approximation.
    """
    pids = list(raw_scores.keys())
    scores = [raw_scores[p]["composite_score"] for p in pids]

    # Softmax normalization for win probability
    win_probs = _softmax(scores, temperature=2.0)

    # Placement probabilities: approximate via rank-weighted combination
    # (Full simulation in monte_carlo.py is the authoritative source)
    n = len(pids)
    top5_probs  = _placement_prob_approx(scores, k=5,  n=n)
    top10_probs = _placement_prob_approx(scores, k=10, n=n)
    top20_probs = _placement_prob_approx(scores, k=20, n=n)

    outputs = {}
    for i, pid in enumerate(pids):
        player_out = dict(raw_scores[pid])
        player_out["model_win_prob"]   = round(win_probs[i], 6)
        player_out["model_top5_prob"]  = round(top5_probs[i], 6)
        player_out["model_top10_prob"] = round(top10_probs[i], 6)
        player_out["model_top20_prob"] = round(top20_probs[i], 6)
        outputs[pid] = player_out

    return outputs


def _softmax(scores: list[float], temperature: float = 1.0) -> list[float]:
    """Compute softmax probabilities with temperature scaling."""
    scaled = [s / temperature for s in scores]
    max_s = max(scaled) if scaled else 0
    exps = [2.718281828 ** (s - max_s) for s in scaled]
    total = sum(exps)
    return [e / total for e in exps] if total > 0 else [1 / len(scores)] * len(scores)


def _placement_prob_approx(scores: list[float], k: int, n: int) -> list[float]:
    """
    Approximate top-k probability for each player.
    Uses a simple rank-based allocation:
    P(top-k) ≈ (k/n) × relative_skill_factor
    This is a fast approximation; monte_carlo.py produces the calibrated version.
    """
    if n == 0:
        return []
    base_rate = k / n
    # Scale by relative score (softmax with higher temperature = less differentiation)
    relative = _softmax(scores, temperature=4.0)
    # Blend toward base_rate to prevent extreme values
    blend = 0.4
    return [
        min(1.0, blend * base_rate + (1 - blend) * r * k)
        for r in relative
    ]


def _top_player(outputs: dict) -> str:
    """Return the player_id with the highest model win probability."""
    if not outputs:
        return "unknown"
    return max(outputs, key=lambda p: outputs[p].get("model_win_prob", 0))
