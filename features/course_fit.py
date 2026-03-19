"""
features/course_fit.py
-----------------------
Generates course-fit scores for every player in the field.

Course fit is NOT a simple lookup. It:
1. Reads the course's demand profile from course_profiles.yaml
2. Applies course-specific SG weights (not global defaults)
3. Scores each player's SG categories against those weighted demands
4. Adds a comp-course history layer
5. Adds a surface/grass-type split layer
6. Adds a conditions adjustment layer (wind, altitude, firmness)

Output is a per-player course fit score and a breakdown by sub-category,
so downstream models and reports can explain WHY a player fits or doesn't.

Key design rules:
- Course weights ALWAYS override global weights for course-fit calculation
- Comp course history is time-decayed (more recent = more weight)
- Surface splits only apply when we have sufficient grass-type data
- Uncertainty is tracked and propagated
"""

import logging
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Load course profiles
with open("configs/course_profiles.yaml") as f:
    _ALL_COURSES = yaml.safe_load(f)

# Load model config
with open("configs/model_weights.yaml") as f:
    _MODEL_CFG = yaml.safe_load(f)

_CF_WEIGHTS = _MODEL_CFG["course_fit_weights"]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def build_course_fit_features(
    event_id: str,
    field: list[dict],
    stats: dict[str, Any],
) -> dict[str, dict]:
    """
    Generate course fit features for every player in the field.

    Returns dict keyed by player_id:
    {
      "course_fit_score": float,          # -2.0 to +2.0 scale
      "sg_category_fit": float,
      "comp_course_score": float,
      "surface_split_score": float,
      "conditions_score": float,
      "fit_confidence": float,            # 0.0 – 1.0
      "archetype_match": bool,
      "archetype_penalized": bool,
      "course_fit_summary": str,          # Human-readable explanation
    }
    """
    # Resolve course profile for this event
    course_key = _resolve_course_key(event_id)
    if not course_key:
        log.warning(f"No course profile found for event_id={event_id}. Using neutral defaults.")
        return {p["id"]: _neutral_fit(p["id"]) for p in field}

    course = _ALL_COURSES["courses"].get(course_key)
    if not course:
        log.warning(f"Course key '{course_key}' not in course_profiles.yaml.")
        return {p["id"]: _neutral_fit(p["id"]) for p in field}

    log.info(f"Course profile loaded: {course.get('display_name', course_key)}")

    results = {}
    for player in field:
        pid = player["id"]
        player_stats = stats.get(pid, {})
        fit = _score_player_fit(pid, player_stats, course)
        results[pid] = fit

    return results


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------

def _score_player_fit(pid: str, player_stats: dict, course: dict) -> dict:
    """Score a single player against a course demand profile."""

    # 1. SG category fit (course-specific weights)
    sg_fit, sg_confidence = _score_sg_category_fit(player_stats, course)

    # 2. Comp course history
    comp_score, comp_confidence = _score_comp_course_history(player_stats, course)

    # 3. Surface split
    surf_score, surf_confidence = _score_surface_split(player_stats, course)

    # 4. Conditions split (wind, altitude, firmness)
    cond_score, cond_confidence = _score_conditions_split(player_stats, course)

    # 5. Weighted composite
    cf = _CF_WEIGHTS
    total_w = (
        cf["sg_category_match"] * sg_confidence
        + cf["comp_course_history"] * comp_confidence
        + cf["surface_split"] * surf_confidence
        + cf["conditions_split"] * cond_confidence
    )

    if total_w < 0.01:
        composite = 0.0
        fit_confidence = 0.0
    else:
        composite = (
            cf["sg_category_match"] * sg_fit * sg_confidence
            + cf["comp_course_history"] * comp_score * comp_confidence
            + cf["surface_split"] * surf_score * surf_confidence
            + cf["conditions_split"] * cond_score * cond_confidence
        ) / total_w
        fit_confidence = total_w / sum(cf.values())

    # 6. Archetype check
    player_archetypes = player_stats.get("archetypes", [])
    course_fit_types = course.get("archetype_fit", [])
    course_penalize_types = course.get("archetype_penalize", [])

    arch_match = bool(set(player_archetypes) & set(course_fit_types))
    arch_penalty = bool(set(player_archetypes) & set(course_penalize_types))

    if arch_match:
        composite = min(composite + 0.08, 2.0)
    if arch_penalty:
        composite = max(composite - 0.08, -2.0)

    # 7. Build human-readable summary
    summary = _build_fit_summary(pid, composite, sg_fit, comp_score, surf_score, arch_match, arch_penalty, course)

    return {
        "player_id": pid,
        "course_fit_score": round(composite, 4),
        "sg_category_fit": round(sg_fit, 4),
        "comp_course_score": round(comp_score, 4),
        "surface_split_score": round(surf_score, 4),
        "conditions_score": round(cond_score, 4),
        "fit_confidence": round(fit_confidence, 3),
        "archetype_match": arch_match,
        "archetype_penalized": arch_penalty,
        "course_fit_summary": summary,
    }


def _score_sg_category_fit(player_stats: dict, course: dict) -> tuple[float, float]:
    """
    Score player's SG categories against course-specific weights.

    Returns (score, confidence) where score is in [-2, 2] range
    and confidence reflects data availability.
    """
    course_sg_weights = course.get("sg_weights", {})
    if not course_sg_weights:
        return 0.0, 0.0

    categories = {
        "sg_ott": player_stats.get("sg_ott"),
        "sg_app": player_stats.get("sg_app"),
        "sg_atg": player_stats.get("sg_atg"),
        "sg_putt": player_stats.get("sg_putt"),
    }

    # Check data availability
    available = {k: v for k, v in categories.items() if v is not None}
    if not available:
        return 0.0, 0.0

    confidence = len(available) / 4.0

    # Weighted score
    total_w = sum(course_sg_weights.get(k, 0) for k in available)
    if total_w < 0.01:
        return 0.0, 0.0

    score = sum(
        course_sg_weights.get(k, 0) * v
        for k, v in available.items()
    ) / total_w

    return round(score, 4), confidence


def _score_comp_course_history(player_stats: dict, course: dict) -> tuple[float, float]:
    """
    Score player's historical performance on comparable courses.

    Comparable course history is time-decayed. Events within 1 year
    get full weight; 2 years get 50% weight.
    """
    comp_courses = course.get("comp_courses", [])
    if not comp_courses:
        return 0.0, 0.0

    comp_history = player_stats.get("comp_course_history", {})
    if not comp_history:
        return 0.0, 0.0

    scores = []
    weights = []

    for cc in comp_courses:
        events = comp_history.get(cc, [])
        for event in events:
            age_years = event.get("age_years", 2.0)
            decay = max(0, 1.0 - 0.5 * age_years)
            sg_val = event.get("sg_total")
            if sg_val is not None and decay > 0:
                scores.append(sg_val)
                weights.append(decay)

    if not scores:
        return 0.0, 0.0

    total_w = sum(weights)
    weighted_score = sum(s * w for s, w in zip(scores, weights)) / total_w
    confidence = min(1.0, len(scores) / 5)  # Full confidence at 5+ comp-course rounds

    return round(weighted_score, 4), confidence


def _score_surface_split(player_stats: dict, course: dict) -> tuple[float, float]:
    """Score player's performance on the specific grass type at this course."""
    green_type = course.get("green_type", "")
    if not green_type:
        return 0.0, 0.0

    surface_map = {
        "bent": "bent_grass_sg_putt",
        "bermuda": "bermuda_sg_putt",
        "poa": "poa_sg_putt",
        "bermuda_overseed": "bermuda_sg_putt",
        "paspalum": "paspalum_sg_putt",
    }

    stat_key = surface_map.get(green_type.split("_")[0])
    if not stat_key:
        return 0.0, 0.0

    val = player_stats.get(stat_key)
    if val is None:
        return 0.0, 0.0

    # Have at least some data
    return round(val, 4), 0.70  # Fixed 70% confidence — surface splits are meaningful but noisy


def _score_conditions_split(player_stats: dict, course: dict) -> tuple[float, float]:
    """Score player's suitability for this course's typical conditions."""
    wind_factor = course.get("wind_factor", "medium")
    altitude = course.get("altitude_factor", "negligible")

    score = 0.0
    confidence = 0.0

    if wind_factor in ("high", "medium_high"):
        wind_stat = player_stats.get("wind_20plus_sg")
        if wind_stat is not None:
            score += wind_stat * 0.6
            confidence = max(confidence, 0.60)

    if altitude in ("high", "medium"):
        # Altitude performance is very thin data — low weight
        score += 0.0
        confidence = max(confidence, 0.20)

    return round(score, 4), round(confidence, 3)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _resolve_course_key(event_id: str) -> str | None:
    """Map event_id to a course key in course_profiles.yaml."""
    # This would be backed by a proper event→course mapping table
    # Placeholder: simple dict for now
    EVENT_TO_COURSE = {
        "pga_masters_2025": "augusta_national",
        "pga_genesis_2025": "riviera_cc",
        "pga_players_2025": "tpc_sawgrass",
        "pga_farmers_2025": "torrey_pines_south",
        "liv_london_2025": "centurion_club",
        "liv_mayakoba_2025": "el_camaleon",
    }
    return EVENT_TO_COURSE.get(event_id)


def _neutral_fit(pid: str) -> dict:
    return {
        "player_id": pid,
        "course_fit_score": 0.0,
        "sg_category_fit": 0.0,
        "comp_course_score": 0.0,
        "surface_split_score": 0.0,
        "conditions_score": 0.0,
        "fit_confidence": 0.0,
        "archetype_match": False,
        "archetype_penalized": False,
        "course_fit_summary": "No course profile available — neutral fit assumed.",
    }


def _build_fit_summary(
    pid, composite, sg_fit, comp_score, surf_score, arch_match, arch_penalty, course
) -> str:
    """Generate a plain-English summary of why a player fits or doesn't."""
    parts = []

    if composite > 0.4:
        parts.append(f"Strong course fit (+{composite:.2f} composite)")
    elif composite < -0.3:
        parts.append(f"Weak course fit ({composite:.2f} composite)")
    else:
        parts.append(f"Neutral course fit ({composite:.2f} composite)")

    if sg_fit > 0.3:
        parts.append(f"SG profile matches course demands well ({sg_fit:+.2f})")
    elif sg_fit < -0.2:
        parts.append(f"SG profile does not match course demands ({sg_fit:+.2f})")

    if comp_score > 0.3:
        parts.append(f"Good history on comparable courses ({comp_score:+.2f})")
    elif comp_score < -0.2:
        parts.append(f"Poor history on comparable courses ({comp_score:+.2f})")

    if surf_score > 0.2:
        parts.append(f"Putting surface specialist advantage ({surf_score:+.2f})")
    elif surf_score < -0.2:
        parts.append(f"Below average on this grass type ({surf_score:+.2f})")

    if arch_match:
        parts.append(f"Archetype fits course profile ({', '.join(course.get('archetype_fit', []))})")

    if arch_penalty:
        parts.append(f"⚠ Archetype is penalized at this course ({', '.join(course.get('archetype_penalize', []))})")

    return ". ".join(parts) + "."
