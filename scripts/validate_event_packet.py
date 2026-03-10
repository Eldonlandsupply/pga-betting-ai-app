#!/usr/bin/env python3
"""Validate golf betting event packets for structural trust guardrails."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ALLOWED_TOURS = {"pga", "liv", "dpwt", "majors", "opposite_field"}
REQUIRED_EVENT_KEYS = {"tournament", "tour", "course", "format"}
REQUIRED_RECOMMENDATION_KEYS = {
    "rank",
    "bet_type",
    "player",
    "implied_probability",
    "fair_probability",
    "edge_percent",
    "confidence",
    "min_acceptable_odds",
    "no_play_below_odds",
    "reasoning",
    "invalidation_conditions",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_iso8601(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def validate_packet(packet: dict[str, Any], now: datetime, stale_line_minutes: int = 30) -> list[str]:
    errors: list[str] = []

    event = packet.get("event")
    if not isinstance(event, dict):
        return ["MISSING event object"]

    missing_event = REQUIRED_EVENT_KEYS - set(event.keys())
    for field in sorted(missing_event):
        errors.append(f"MISSING event.{field}")

    tour = event.get("tour")
    if tour not in ALLOWED_TOURS:
        errors.append(f"invalid event.tour '{tour}'")

    recommendations = packet.get("recommendations")
    if not isinstance(recommendations, list):
        errors.append("MISSING recommendations list")
        recommendations = []

    for idx, rec in enumerate(recommendations, start=1):
        if not isinstance(rec, dict):
            errors.append(f"recommendations[{idx}] is not object")
            continue
        missing_rec = REQUIRED_RECOMMENDATION_KEYS - set(rec.keys())
        for key in sorted(missing_rec):
            errors.append(f"MISSING recommendations[{idx}].{key}")

        implied = rec.get("implied_probability")
        fair = rec.get("fair_probability")
        confidence = rec.get("confidence")
        if not _is_number(implied):
            errors.append(f"recommendations[{idx}] implied_probability must be number")
        elif not 0 <= implied <= 1:
            errors.append(f"recommendations[{idx}] implied_probability out of range")
        if not _is_number(fair):
            errors.append(f"recommendations[{idx}] fair_probability must be number")
        elif not 0 <= fair <= 1:
            errors.append(f"recommendations[{idx}] fair_probability out of range")
        if not _is_number(confidence):
            errors.append(f"recommendations[{idx}] confidence must be number")
        elif not 0 <= confidence <= 1:
            errors.append(f"recommendations[{idx}] confidence out of range")

        min_odds = rec.get("min_acceptable_odds")
        no_play_odds = rec.get("no_play_below_odds")
        if isinstance(min_odds, (int, float)) and isinstance(no_play_odds, (int, float)):
            if no_play_odds > min_odds:
                errors.append(
                    f"recommendations[{idx}] invalid thresholds: no_play_below_odds > min_acceptable_odds"
                )

    data_quality = packet.get("data_quality")
    if not isinstance(data_quality, dict):
        errors.append("MISSING data_quality object")
        data_quality = {}

    source_freshness = data_quality.get("source_freshness")
    if source_freshness is None:
        errors.append("MISSING data_quality.source_freshness")
    elif source_freshness not in {"fresh", "aging", "stale"}:
        errors.append("invalid data_quality.source_freshness")

    if "missing_fields" not in data_quality:
        errors.append("MISSING data_quality.missing_fields")

    missing_fields = data_quality.get("missing_fields")
    if missing_fields is not None and not isinstance(missing_fields, list):
        errors.append("data_quality.missing_fields must be list")
    elif isinstance(missing_fields, list) and missing_fields:
        errors.append("MISSING fields present, confidence should be downgraded")

    conflicts = data_quality.get("conflicts")
    if isinstance(conflicts, list) and conflicts:
        errors.append("source conflicts present, suppress fragile picks")

    markets = packet.get("markets")
    if not isinstance(markets, list) or not markets:
        errors.append("MISSING markets list")
        return errors

    for idx, market in enumerate(markets, start=1):
        if not isinstance(market, dict):
            errors.append(f"markets[{idx}] is not object")
            continue
        for key in ("bet_type", "player", "sportsbook", "odds_decimal", "timestamp"):
            if key not in market:
                errors.append(f"MISSING markets[{idx}].{key}")
        timestamp = market.get("timestamp")
        if timestamp is None:
            continue
        if not isinstance(timestamp, str):
            errors.append(f"markets[{idx}] timestamp must be string")
            continue
        try:
            ts = _parse_iso8601(timestamp)
        except ValueError:
            errors.append(f"markets[{idx}] invalid timestamp format")
            continue
        age_minutes = (now - ts.astimezone(timezone.utc)).total_seconds() / 60
        if age_minutes > stale_line_minutes:
            errors.append(f"markets[{idx}] stale line timestamp")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet_json", type=Path)
    parser.add_argument("--stale-line-minutes", type=int, default=30)
    args = parser.parse_args()

    packet = json.loads(args.packet_json.read_text(encoding="utf-8"))
    errors = validate_packet(packet, now=datetime.now(timezone.utc), stale_line_minutes=args.stale_line_minutes)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("PASS: event packet validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
