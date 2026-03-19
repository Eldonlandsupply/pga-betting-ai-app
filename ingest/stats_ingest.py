"""
ingest/stats_ingest.py — Player strokes gained and stat ingestion.
"""
from __future__ import annotations
import json, logging, os
from pathlib import Path
log = logging.getLogger(__name__)

def ingest_player_stats(player_ids: list[str]) -> dict[str, dict]:
    """Fetch historical stats for all players. Returns dict keyed by player_id."""
    stats = {}
    manual = Path("input/player_stats.json")
    if manual.exists():
        all_stats = json.loads(manual.read_text())
        for pid in player_ids:
            if pid in all_stats:
                stats[pid] = all_stats[pid]
        log.info(f"Stats loaded from manual file for {len(stats)}/{len(player_ids)} players.")
        return stats

    api_key = os.environ.get("DATAGOLF_API_KEY", "")
    if api_key and api_key not in ("YOUR_DATAGOLF_API_KEY", ""):
        return _fetch_datagolf_stats(player_ids, api_key)

    log.warning("No stats data source available. Returning empty stats.")
    return {pid: {} for pid in player_ids}

def _fetch_datagolf_stats(player_ids: list[str], api_key: str) -> dict[str, dict]:
    """Stub: fetch from DataGolf API."""
    # TODO Phase 2: DataGolf player skill decomposition endpoint
    return {}
