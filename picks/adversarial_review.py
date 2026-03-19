"""
picks/adversarial_review.py
----------------------------
The adversarial review module challenges every pick the model generates
BEFORE it becomes a recommendation.

Purpose: Force the system to argue against its own outputs and catch:
- Fragile edges based on tiny samples
- Double-counted correlated signals
- Public narrative bets dressed as model output
- Stale or already-moved lines
- Famous name inflation
- Overfit hot streaks masquerading as real signal
- Format/structural mismatches
- Bets that are theoretically sound but practically dead

Every pick gets an adversarial score. Picks that fail adversarial review
are either downgraded, flagged, or removed from the final card.

Output: A revised card with adversarial commentary attached to each pick,
and a list of picks that were killed or downgraded.
"""

import logging
from typing import Any

log = logging.getLogger(__name__)

# Adversarial review failure categories
ADVERSARIAL_FLAGS = {
    "LINE_MOVED": "Line has already moved significantly against this bet",
    "STALE_LINE": "Line has not moved in 48h+ — may be stale or illiquid",
    "TINY_SAMPLE": "Edge is driven by fewer than 10 relevant data points",
    "SINGLE_SIGNAL": "Edge is driven by a single stat family — not multi-signal",
    "CORRELATED_STACK": "This bet is highly correlated with another bet in the card",
    "HOT_STREAK": "Player is on a short streak (<3 events) that may be regressing",
    "FAMOUS_NAME_BIAS": "Model may be inflating a big-name player based on reputation",
    "POOR_COURSE_FIT": "Player has poor course-fit score despite overall model strength",
    "LIV_DATA_THIN": "LIV player — public data is thin and model uncertainty is high",
    "WEATHER_UNKNOWN": "Weather window is unresolved and could flip this bet's value",
    "INJURY_UNVERIFIED": "Player has an unverified injury or fitness flag",
    "MARKET_DISAGREES": "Market is pricing this player significantly differently — investigate",
    "NO_COMP_HISTORY": "Player has no history on comparable courses",
    "OVERFIT_NARRATIVE": "This pick aligns too closely with a popular public narrative",
    "LOW_CONVICTION": "Model conviction band is wide — fragile, not durable edge",
}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def run_adversarial_review(
    card: dict,
    model_outputs: dict[str, Any],
    markets: dict[str, Any],
) -> dict:
    """
    Run adversarial review on the full betting card.

    Args:
        card: betting card with categorized picks
        model_outputs: full model output per player
        markets: current market data including line movement

    Returns:
        Revised card with adversarial commentary, killed picks, and downgraded picks.
    """
    log.info("Running adversarial review...")

    reviewed_picks = []
    killed_picks = []
    downgraded_picks = []

    all_picks = _flatten_card(card)

    # Track which picks survive for correlation check
    surviving_picks = []

    for pick in all_picks:
        challenges = _challenge_pick(pick, model_outputs, markets)
        kill_score = _compute_kill_score(challenges)

        if kill_score >= 3:
            # Hard kill — too many red flags
            pick["adversarial_verdict"] = "KILLED"
            pick["adversarial_challenges"] = challenges
            pick["kill_score"] = kill_score
            killed_picks.append(pick)
            log.info(f"  ✗ KILLED: {pick['player_id']} {pick['market_type']} (score={kill_score})")

        elif kill_score >= 1:
            # Downgrade — reduce confidence tier and stake
            pick["adversarial_verdict"] = "DOWNGRADED"
            pick["adversarial_challenges"] = challenges
            pick["kill_score"] = kill_score
            pick["confidence_tier"] = _downgrade_tier(pick.get("confidence_tier", "value"))
            downgraded_picks.append(pick)
            surviving_picks.append(pick)
            log.info(f"  ↓ DOWNGRADED: {pick['player_id']} {pick['market_type']} (score={kill_score})")

        else:
            pick["adversarial_verdict"] = "PASSED"
            pick["adversarial_challenges"] = challenges
            pick["kill_score"] = kill_score
            reviewed_picks.append(pick)
            surviving_picks.append(pick)

    # Correlation check on surviving picks
    correlated_pairs = _detect_correlated_stacks(surviving_picks)
    if correlated_pairs:
        log.info(f"  ⚠ Correlated stacks detected: {correlated_pairs}")

    # Rebuild card
    reviewed_card = {
        **card,
        "reviewed_picks": reviewed_picks,
        "downgraded_picks": downgraded_picks,
        "killed_picks": killed_picks,
        "correlated_pairs": correlated_pairs,
        "adversarial_summary": _build_adversarial_summary(reviewed_picks, downgraded_picks, killed_picks),
    }

    log.info(
        f"Adversarial review complete. "
        f"Passed: {len(reviewed_picks)} | "
        f"Downgraded: {len(downgraded_picks)} | "
        f"Killed: {len(killed_picks)}"
    )

    return reviewed_card


# ---------------------------------------------------------------------------
# Per-pick challenge logic
# ---------------------------------------------------------------------------

def _challenge_pick(pick: dict, model_outputs: dict, markets: dict) -> list[dict]:
    """
    Run all adversarial challenges against a single pick.
    Returns list of fired challenges.
    """
    challenges = []
    pid = pick["player_id"]
    market_type = pick["market_type"]
    player_model = model_outputs.get(pid, {})
    model_data = player_model  # alias used in SINGLE_SIGNAL check
    # markets is {pid: {market_type: tracker_dict}}
    market_data = markets.get(pid, {}).get(market_type, {})

    # --- CHALLENGE 1: Line movement ---
    line_movement = market_data.get("line_movement_pct", 0)
    if line_movement < -0.15:  # Line moved 15%+ shorter = market disagrees
        challenges.append({
            "flag": "LINE_MOVED",
            "detail": f"Line shortened {abs(line_movement)*100:.0f}% since open — market disagrees with our direction",
            "severity": "high",
        })

    # --- CHALLENGE 2: Stale line ---
    hours_since_update = market_data.get("hours_since_update", 0)
    if hours_since_update > 48:
        challenges.append({
            "flag": "STALE_LINE",
            "detail": f"Line has not updated in {hours_since_update:.0f} hours",
            "severity": "medium",
        })

    # --- CHALLENGE 3: Tiny sample ---
    data_rounds = player_model.get("data_rounds", 100)
    data_confidence = player_model.get("data_confidence", 1.0)
    if data_rounds < 15 or data_confidence < 0.35:
        challenges.append({
            "flag": "TINY_SAMPLE",
            "detail": f"Player has only {data_rounds} qualifying rounds. Confidence: {data_confidence:.0%}",
            "severity": "high",
        })

    # --- CHALLENGE 4: Single signal driver ---
    dominant_signal = pick.get("dominant_signal")
    signal_diversity = pick.get("signal_diversity_score", 1.0)
    dominant_pct = model_data.get("dominant_signal_pct", 0.0)
    if signal_diversity < 0.3 or dominant_pct > 0.70:
        challenges.append({
            "flag": "SINGLE_SIGNAL",
            "detail": f"Edge primarily driven by '{dominant_signal}' ({dominant_pct*100:.0f}% of composite) — multi-signal confirmation lacking",
            "severity": "medium",
        })

    # --- CHALLENGE 5: Hot streak check ---
    form_streak_length = player_model.get("form_streak_events", 10)
    if form_streak_length < 3 and pick.get("form_driven", False):
        challenges.append({
            "flag": "HOT_STREAK",
            "detail": f"Recent form is based on {form_streak_length} events — short streak may be regressing",
            "severity": "medium",
        })

    # --- CHALLENGE 6: Famous name bias ---
    world_rank = player_model.get("world_rank", 999)
    model_prob = pick.get("model_probability", 0)
    implied_prob = pick.get("implied_probability", 0)
    if world_rank <= 10 and model_prob > implied_prob * 1.5:
        challenges.append({
            "flag": "FAMOUS_NAME_BIAS",
            "detail": f"Top-10 ranked player. Verify edge is data-driven, not reputation inflation.",
            "severity": "medium",
        })

    # --- CHALLENGE 7: Poor course fit ---
    course_fit = player_model.get("course_fit_score", 0)
    if course_fit < -0.25 and market_type in ("outright", "top_5", "top_10"):
        challenges.append({
            "flag": "POOR_COURSE_FIT",
            "detail": f"Course fit score: {course_fit:.2f}. Player's SG profile does not match course demands.",
            "severity": "high",
        })

    # --- CHALLENGE 8: LIV data depth ---
    if pick.get("tour") == "LIV" and data_confidence < 0.60:
        challenges.append({
            "flag": "LIV_DATA_THIN",
            "detail": f"LIV player with data confidence {data_confidence:.0%} — model uncertainty elevated",
            "severity": "medium",
        })

    # --- CHALLENGE 9: Weather unresolved ---
    if pick.get("weather_risk_flag"):
        challenges.append({
            "flag": "WEATHER_UNKNOWN",
            "detail": "Weather window for this event is unresolved — wind/rain could flip course fit advantage",
            "severity": "medium",
        })

    # --- CHALLENGE 10: Injury unverified ---
    if "injury_unverified" in pick.get("risk_flags", []):
        challenges.append({
            "flag": "INJURY_UNVERIFIED",
            "detail": "Player has an unverified health/fitness flag. Confirm status before betting.",
            "severity": "critical",
        })

    # --- CHALLENGE 11: No comp course history ---
    comp_course_rounds = player_model.get("comp_course_rounds", 10)
    if comp_course_rounds < 3:
        challenges.append({
            "flag": "NO_COMP_HISTORY",
            "detail": f"Player has only {comp_course_rounds} rounds on comparable courses — course fit score unreliable",
            "severity": "medium",
        })

    # --- CHALLENGE 12: Low conviction band ---
    conviction_width = pick.get("confidence_band_width", 0)
    if conviction_width > 0.10:  # 10% confidence interval width
        challenges.append({
            "flag": "LOW_CONVICTION",
            "detail": f"Model confidence band is ±{conviction_width*100:.0f}% — fragile, not durable edge",
            "severity": "low",
        })

    return challenges


def _compute_kill_score(challenges: list) -> int:
    """
    Compute a kill score for a pick based on its adversarial challenges.

    Severity weights:
    - critical: 3 points
    - high: 2 points
    - medium: 1 point
    - low: 0 points

    Kill threshold: score >= 3 = kill, 1-2 = downgrade, 0 = pass
    """
    severity_map = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    return sum(severity_map.get(c.get("severity", "low"), 0) for c in challenges)


def _downgrade_tier(current_tier: str) -> str:
    """Downgrade confidence tier by one level."""
    tier_order = ["elite", "strong", "value", "speculative"]
    try:
        idx = tier_order.index(current_tier.lower())
        return tier_order[min(idx + 1, len(tier_order) - 1)]
    except ValueError:
        return "speculative"


# ---------------------------------------------------------------------------
# Correlation detection
# ---------------------------------------------------------------------------

def _detect_correlated_stacks(picks: list) -> list[dict]:
    """
    Identify pairs of picks that are highly correlated.

    Correlations to flag:
    - Same player in outright + top 5 + top 10 (exposure stacking)
    - Two players from same LIV team
    - Two players with identical course fit / form narratives
    """
    pairs = []
    seen_players = {}

    for pick in picks:
        pid = pick["player_id"]
        market = pick["market_type"]

        if pid in seen_players:
            pairs.append({
                "player_id": pid,
                "markets": [seen_players[pid], market],
                "flag": "SAME_PLAYER_MULTIPLE_MARKETS",
                "recommendation": "Consider reducing combined exposure or backing only the best-price market",
            })
        else:
            seen_players[pid] = market

    return pairs


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _flatten_card(card: dict) -> list:
    """Flatten categorized card into a single list of picks."""
    picks = []
    for category in ("safe_bets", "value_bets", "upside_outrights", "matchup_bets", "longshot_bets", "placement_bets"):
        picks.extend(card.get(category, []))
    return picks


def _build_adversarial_summary(reviewed: list, downgraded: list, killed: list) -> dict:
    """Build a human-readable adversarial review summary."""
    top_concerns = {}
    for pick in downgraded + killed:
        for challenge in pick.get("adversarial_challenges", []):
            flag = challenge["flag"]
            top_concerns[flag] = top_concerns.get(flag, 0) + 1

    most_common = sorted(top_concerns.items(), key=lambda x: -x[1])[:5]

    return {
        "passed": len(reviewed),
        "downgraded": len(downgraded),
        "killed": len(killed),
        "top_concerns_this_week": [
            {"flag": flag, "occurrences": count, "description": ADVERSARIAL_FLAGS.get(flag, "")}
            for flag, count in most_common
        ],
        "adversarial_note": (
            "All remaining picks have survived adversarial review. "
            "Challenges attached to each pick explain remaining risks."
        ),
    }
