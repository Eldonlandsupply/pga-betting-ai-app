"""
ingest/market_ingest.py
------------------------
Ingests sportsbook market prices for an event.
Returns normalized structure for line_tracker.py.

Priority:
  1. Manual: input/{event_id}_markets.json  (uses existing event_packet format)
  2. The Odds API (Phase 2)
  3. Manual price entry via event_packet.json markets array

Output format per player_id:
  {
    market_type: {
      book: [ {price, timestamp}, ... ]
    }
  }
"""
from __future__ import annotations
import json, logging, os
from pathlib import Path
log = logging.getLogger(__name__)

def ingest_markets(event_id: str) -> dict[str, dict]:
    """Ingest market prices. Returns per-player, per-market, per-book price history."""
    # Try event_packet format (compatible with existing input/current_event.json)
    packet_path = Path("input/current_event.json")
    if packet_path.exists():
        return _parse_event_packet_markets(packet_path)

    manual = Path(f"input/{event_id}_markets.json")
    if manual.exists():
        return json.loads(manual.read_text())

    api_key = os.environ.get("ODDS_API_KEY", "")
    if api_key and api_key not in ("YOUR_ODDS_API_KEY", ""):
        return _fetch_odds_api(event_id, api_key)

    log.warning("No market data source. Returning empty markets.")
    return {}

def _parse_event_packet_markets(packet_path: Path) -> dict[str, dict]:
    """
    Parse the existing event_packet.json markets array into the
    internal per-player structure expected by line_tracker.py.
    """
    packet = json.loads(packet_path.read_text())
    markets_raw = packet.get("markets", [])

    # Structure: {player_name: {market_type: {book: [{price, timestamp}]}}}
    out: dict = {}
    for entry in markets_raw:
        pid   = entry.get("player", "").lower().replace(" ", "_")
        mtype = entry.get("bet_type", "outright")
        book  = entry.get("sportsbook", "unknown").lower().replace(" ", "_")
        price = entry.get("odds_decimal")
        ts    = entry.get("timestamp", "")

        if not pid or not price:
            continue

        out.setdefault(pid, {}).setdefault(mtype, {}).setdefault(book, []).append(
            {"price": price, "timestamp": ts}
        )

    log.info(f"Parsed markets for {len(out)} players from event_packet.json")
    return out

def _fetch_odds_api(event_id: str, api_key: str) -> dict:
    """Stub: fetch from The Odds API."""
    # TODO Phase 2: GET https://api.the-odds-api.com/v4/sports/golf_pga/odds/
    return {}
