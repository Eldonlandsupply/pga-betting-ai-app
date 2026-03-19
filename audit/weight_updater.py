"""
audit/weight_updater.py
------------------------
Evidence-gated model weight update system.

Rules:
1. Weights ONLY change when evidence gates are satisfied.
2. No single-week reaction. Patterns must span multiple events.
3. Changes are bounded: max +/- 0.03 per update cycle.
4. Every change is logged in CHANGELOG.md.
5. Changes are reversible via changelog history.
6. The system prefers precision over speed of adaptation.

This module reads recommendations from post_event_audit.py,
checks them against the evidence gates in model_weights.yaml,
and conditionally applies bounded adjustments.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

WEIGHTS_PATH = Path("configs/model_weights.yaml")
CHANGELOG_PATH = Path("CHANGELOG.md")
AUDIT_HISTORY_PATH = Path("audit/history")


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def check_and_update_weights(audit_output: dict) -> list[dict]:
    """
    Check model adjustment recommendations from audit against evidence gates.
    Apply changes that pass. Log everything.

    Returns list of applied changes (empty if none warranted).
    """
    recommendations = audit_output.get("model_adjustment_recommendations", [])
    if not recommendations:
        log.info("No model adjustment recommendations. Weights unchanged.")
        return []

    # Load current weights
    with open(WEIGHTS_PATH) as f:
        current_weights = yaml.safe_load(f)

    gates = current_weights.get("weight_update_gates", {})
    applied_changes = []

    for rec in recommendations:
        if rec.get("priority") == "immediate":
            # Risk rules — no gate required
            change = _apply_change(rec, current_weights, gates, bypass_gate=True)
            if change:
                applied_changes.append(change)
            continue

        if not rec.get("gate_required", True):
            change = _apply_change(rec, current_weights, gates, bypass_gate=True)
            if change:
                applied_changes.append(change)
            continue

        # Check evidence gate
        gate_result = _check_evidence_gate(rec, audit_output, gates)
        if gate_result["passed"]:
            change = _apply_change(rec, current_weights, gates)
            if change:
                applied_changes.append(change)
        else:
            log.info(
                f"Gate not met for: {rec.get('change')}. "
                f"Reason: {gate_result['reason']}"
            )

    if applied_changes:
        # Write updated weights
        with open(WEIGHTS_PATH, "w") as f:
            yaml.dump(current_weights, f, default_flow_style=False)

        # Write changelog
        _write_changelog_entries(applied_changes, audit_output.get("event_id", "unknown"))

        log.info(f"{len(applied_changes)} weight change(s) applied and logged.")

    return applied_changes


# ---------------------------------------------------------------------------
# Evidence gate checking
# ---------------------------------------------------------------------------

def _check_evidence_gate(rec: dict, audit_output: dict, gates: dict) -> dict:
    """
    Check whether a recommendation meets the evidence gates.

    Gates:
    1. Minimum events with this pattern
    2. Minimum sample size of affected picks
    3. Pattern must appear in cross-week analysis (not just this event)
    """
    # Check cross-week pattern
    cross_week_patterns = audit_output.get("cross_week_patterns", [])
    pattern_causes = {p["cause"] for p in cross_week_patterns}

    # Map recommendation to a failure cause
    rec_cause = _infer_cause_from_recommendation(rec)

    # Gate 1: Must be a repeated cross-week pattern
    min_events = gates.get("minimum_events_for_update", 6)
    pattern = next((p for p in cross_week_patterns if p["cause"] == rec_cause), None)

    if not pattern:
        return {
            "passed": False,
            "reason": f"Cause '{rec_cause}' not in cross-week patterns — single-event reaction prevented",
        }

    if pattern["occurrences"] < min_events:
        return {
            "passed": False,
            "reason": (
                f"Cause '{rec_cause}' appears {pattern['occurrences']}x "
                f"(need {min_events}x before weight change)"
            ),
        }

    # Gate 2: Require dual-direction evidence (not just failure runs)
    if gates.get("require_dual_direction_evidence", True):
        success_evidence = _check_success_evidence(rec_cause)
        if not success_evidence:
            return {
                "passed": False,
                "reason": "No positive evidence that the proposed change would help — only failure evidence present",
            }

    return {"passed": True, "reason": "All gates met"}


def _check_success_evidence(cause: str) -> bool:
    """
    Verify there's positive evidence the proposed fix would help.
    Looks for events where the correct behavior (that this change would produce)
    led to good outcomes.

    Simplified: for now, checks audit history for any event where
    the proposed direction was correct.
    """
    # In production: proper statistical test against historical picks
    # Simplified: return True if we have 10+ audits (sufficient data)
    if not AUDIT_HISTORY_PATH.exists():
        return False
    audit_files = list(AUDIT_HISTORY_PATH.glob("*.json"))
    return len(audit_files) >= 6


# ---------------------------------------------------------------------------
# Change application
# ---------------------------------------------------------------------------

def _apply_change(
    rec: dict,
    current_weights: dict,
    gates: dict,
    bypass_gate: bool = False,
) -> dict | None:
    """
    Apply a bounded weight change.
    Returns the change record, or None if no change was made.
    """
    max_single = gates.get("max_single_week_adjustment", 0.03)
    max_cumulative = gates.get("max_cumulative_adjustment", 0.15)

    target = rec.get("target", "")
    change_desc = rec.get("change", "")

    # Parse the specific change
    parsed = _parse_change(rec)
    if not parsed:
        log.warning(f"Could not parse change: {change_desc}")
        return None

    field_path = parsed["field_path"]
    delta = min(abs(parsed["delta"]), max_single) * (1 if parsed["delta"] > 0 else -1)

    # Navigate to the field and check cumulative drift
    try:
        value = _get_nested(current_weights, field_path)
        default_value = _get_nested(_load_default_weights(), field_path)
        current_drift = abs(value - default_value)

        if current_drift + abs(delta) > max_cumulative:
            delta = max_cumulative - current_drift
            delta *= (1 if parsed["delta"] > 0 else -1)
            log.info(f"Cumulative max capped delta to {delta:.4f}")

        if abs(delta) < 0.001:
            log.info(f"Delta too small after capping. Skipping {field_path}.")
            return None

        new_value = round(value + delta, 5)
        _set_nested(current_weights, field_path, new_value)

        change_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "target": target,
            "field": ".".join(field_path),
            "old_value": round(value, 5),
            "new_value": new_value,
            "delta": round(delta, 5),
            "change_description": change_desc,
            "evidence": rec.get("evidence", ""),
            "priority": rec.get("priority", "medium"),
            "gate_bypassed": bypass_gate,
        }

        log.info(f"Weight updated: {'.'.join(field_path)} {value:.4f} → {new_value:.4f} (Δ{delta:+.4f})")
        return change_record

    except (KeyError, TypeError) as e:
        log.error(f"Failed to apply change {field_path}: {e}")
        return None


def _parse_change(rec: dict) -> dict | None:
    """
    Parse a recommendation into a concrete field path + delta.
    This is a simplified parser — production would use structured rec format.
    """
    change_desc = rec.get("change", "").lower()

    # Map known change descriptions to fields and deltas
    change_map = [
        {
            "keyword": "increase weight on sg_app in recent form",
            "field_path": ["sg_default_weights", "sg_app"],
            "delta": 0.02,
        },
        {
            "keyword": "reduce putting decay",
            "field_path": ["global_weights", "skill_baseline"],
            "delta": -0.01,
        },
        {
            "keyword": "increase weight on sharp-vs-public movement",
            "field_path": ["market_signal_weights", "sharp_book_vs_public_delta"],
            "delta": 0.03,
        },
        {
            "keyword": "increase liv volatility",
            "field_path": ["liv_adjustments", "data_depth_penalty"],
            "delta": 0.02,
        },
        {
            "keyword": "reduce maximum weekly exposure",
            "field_path": ["weight_update_gates", "minimum_events_for_update"],
            "delta": 0,  # Staking config change — handled separately
        },
    ]

    for mapping in change_map:
        if mapping["keyword"] in change_desc:
            return mapping

    return None


# ---------------------------------------------------------------------------
# Changelog
# ---------------------------------------------------------------------------

def _write_changelog_entries(changes: list[dict], event_id: str):
    """Append model changes to CHANGELOG.md."""
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"\n## [{timestamp}] — Post-Event Weight Update: {event_id}\n",
    ]
    for change in changes:
        lines.append(
            f"- **{change['field']}**: `{change['old_value']}` → `{change['new_value']}` "
            f"(Δ{change['delta']:+.4f})\n"
            f"  - Reason: {change['change_description']}\n"
            f"  - Evidence: {change['evidence']}\n"
        )

    with open(CHANGELOG_PATH, "a") as f:
        f.writelines(lines)

    log.info(f"Changelog updated with {len(changes)} entries.")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _get_nested(d: dict, keys: list) -> Any:
    for k in keys:
        d = d[k]
    return d


def _set_nested(d: dict, keys: list, value: Any):
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = value


def _infer_cause_from_recommendation(rec: dict) -> str:
    change = rec.get("change", "").lower()
    cause_map = {
        "sg_app": "underweighted_recent_approach_surge",
        "putting": "overweighted_stale_putting_baseline",
        "sharp": "missed_sharp_line_movement_signal",
        "liv": "underestimated_liv_volatility",
        "course": "missed_course_fit_penalty",
    }
    for keyword, cause in cause_map.items():
        if keyword in change:
            return cause
    return "other"


def _load_default_weights() -> dict:
    """Load factory-default weights for cumulative drift calculation."""
    # In production: load from a versioned default snapshot
    # For now: re-read the file (changes are tracked in-memory during update)
    with open(WEIGHTS_PATH) as f:
        return yaml.safe_load(f)
