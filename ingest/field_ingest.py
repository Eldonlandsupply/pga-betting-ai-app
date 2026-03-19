"""
ingest/field_ingest.py
-----------------------
Ingests the player field for a given event.
Fetches: entries, WDs, alternates, WR at time of event.
"""
from __future__ import annotations
import json, logging, os
from pathlib import Path
log = logging.getLogger(__name__)

def ingest_field(event_id: str) -> list[dict]:
    """Return list of player dicts for the event field."""
    # Check for manual field file first
    manual = Path(f"input/{event_id}_field.json")
    if manual.exists():
        log.info(f"Loading manual field file: {manual}")
        return json.loads(manual.read_text())

    # Phase 2: DataGolf field endpoint
    api_key = os.environ.get("DATAGOLF_API_KEY", "")
    if api_key and api_key not in ("YOUR_DATAGOLF_API_KEY", ""):
        return _fetch_datagolf_field(event_id, api_key)

    log.warning(f"No field data source available for {event_id}. Returning empty field.")
    return []

def _fetch_datagolf_field(event_id: str, api_key: str) -> list[dict]:
    """Stub: fetch field from DataGolf API."""
    # TODO Phase 2: GET https://feeds.datagolf.com/field-updates?event_id=...&key=...
    return []
