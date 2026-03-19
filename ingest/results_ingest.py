"""ingest/results_ingest.py"""
from __future__ import annotations
import json, logging
from pathlib import Path
log = logging.getLogger(__name__)

def ingest_results(event_id: str) -> dict:
    """
    Load final results for a completed event.
    Expects input/{event_id}_results.json with:
      {
        "final_standings": [{player_id, final_position, score_to_par}],
        "cut_results": {player_id: true/false},
        "round_by_round": {player_id: [r1, r2, r3, r4]}
      }
    """
    results_path = Path(f"input/{event_id}_results.json")
    if results_path.exists():
        log.info(f"Loading results: {results_path}")
        return json.loads(results_path.read_text())
    log.warning(f"No results file found for {event_id}.")
    return {"final_standings": [], "cut_results": {}, "round_by_round": {}}
