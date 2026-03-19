"""ingest/weather_ingest.py"""
from __future__ import annotations
import json, logging
from pathlib import Path
log = logging.getLogger(__name__)

def ingest_weather(event_id: str) -> dict:
    manual = Path(f"input/{event_id}_weather.json")
    if manual.exists():
        return json.loads(manual.read_text())
    packet = Path("input/current_event.json")
    if packet.exists():
        data = json.loads(packet.read_text())
        return data.get("weather", {})
    log.warning(f"No weather data for {event_id}.")
    return {}
