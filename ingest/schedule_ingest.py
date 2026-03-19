"""
ingest/schedule_ingest.py
--------------------------
Detects the current PGA Tour and LIV Golf events for the upcoming week.

Data sources (in priority order):
  1. DataGolf API schedule endpoint
  2. PGA Tour website scraper (fallback)
  3. Manual override: input/schedule_override.json

Auto-detection logic:
  - If today is Monday–Wednesday: current week's event is "upcoming"
  - If today is Thursday–Sunday: current event is "in_progress"
  - Returns the soonest upcoming or current event

Each event object contains the course_key used to load course_profiles.yaml.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SCHEDULE_OVERRIDE_PATH = Path("input/schedule_override.json")
SCHEDULE_CACHE_PATH    = Path("data/raw/schedule_cache.json")


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def detect_current_event() -> dict | None:
    """
    Detect the current or next upcoming event.
    Returns event dict or None if no event found.
    """
    # Manual override takes priority
    override = _load_override()
    if override:
        log.info(f"Schedule override active: {override.get('display_name')}")
        return override

    # Try DataGolf API
    schedule = _fetch_datagolf_schedule()
    if not schedule:
        # Try cache
        schedule = _load_cached_schedule()

    if not schedule:
        log.warning("No schedule data available. Return None.")
        return None

    today = date.today()
    for event in schedule:
        start = _parse_date(event.get("start_date"))
        end   = _parse_date(event.get("end_date"))
        if start and end:
            # Event is current or starts within next 7 days
            if start <= today + timedelta(days=7) and end >= today:
                return _normalize_event(event)

    log.warning("No current or upcoming event found in schedule.")
    return None


def get_upcoming_events(n: int = 4) -> list[dict]:
    """Return the next N upcoming events."""
    schedule = _fetch_datagolf_schedule() or _load_cached_schedule() or []
    today = date.today()
    upcoming = [
        _normalize_event(e)
        for e in schedule
        if _parse_date(e.get("start_date")) and _parse_date(e.get("start_date")) >= today
    ]
    return sorted(upcoming, key=lambda x: x.get("start_date", ""))[:n]


# ---------------------------------------------------------------------------
# Normalizer
# ---------------------------------------------------------------------------

def _normalize_event(raw: dict) -> dict:
    """Normalize a raw event dict into the internal event schema."""
    return {
        "event_id":        raw.get("event_id") or raw.get("dg_id") or raw.get("id"),
        "display_name":    raw.get("event_name") or raw.get("display_name"),
        "tour":            raw.get("tour", "PGA").upper(),
        "tournament_type": _classify_tournament_type(raw),
        "start_date":      raw.get("start_date"),
        "end_date":        raw.get("end_date"),
        "venue":           raw.get("course") or raw.get("venue"),
        "course_key":      raw.get("course_key"),
        "location":        raw.get("location"),
        "purse_usd":       raw.get("purse"),
        "field_size":      raw.get("field_size"),
        "has_cut":         raw.get("has_cut", True),
        "rounds":          raw.get("rounds", 4),
    }


def _classify_tournament_type(raw: dict) -> str:
    name = (raw.get("event_name") or "").lower()
    tour = (raw.get("tour") or "PGA").upper()

    if tour == "LIV":
        return "liv"
    if any(x in name for x in ["masters", "u.s. open", "open championship", "pga championship"]):
        return "major"
    if raw.get("signature") or raw.get("is_signature"):
        return "signature"
    if raw.get("opposite_field") or raw.get("is_opposite_field"):
        return "opposite_field"
    if raw.get("has_cut") is False:
        return "no_cut"
    return "standard"


# ---------------------------------------------------------------------------
# Data fetching stubs (wire to real APIs in Phase 2)
# ---------------------------------------------------------------------------

def _fetch_datagolf_schedule() -> list | None:
    """Fetch schedule from DataGolf API."""
    api_key = os.environ.get("DATAGOLF_API_KEY", "")
    if not api_key or api_key in ("YOUR_DATAGOLF_API_KEY", ""):
        log.debug("DataGolf API key not set. Skipping schedule fetch.")
        return None
    # TODO: implement actual API call in Phase 2
    # GET https://feeds.datagolf.com/get-schedule?tour=pga&file_format=json&key={api_key}
    return None


def _load_cached_schedule() -> list | None:
    """Load last cached schedule from disk."""
    if SCHEDULE_CACHE_PATH.exists():
        try:
            with open(SCHEDULE_CACHE_PATH) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Could not load schedule cache: {e}")
    return None


def _load_override() -> dict | None:
    """Load manual schedule override."""
    if SCHEDULE_OVERRIDE_PATH.exists():
        try:
            with open(SCHEDULE_OVERRIDE_PATH) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Could not load schedule override: {e}")
    return None


def _parse_date(date_str: str | None) -> date | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except Exception:
        return None
