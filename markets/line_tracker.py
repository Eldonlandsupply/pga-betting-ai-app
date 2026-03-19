"""
markets/line_tracker.py
------------------------
Tracks sportsbook lines from opening through closing, including:
- Opening line per book
- Current best available line
- Line movement direction and magnitude
- Sharp book vs recreational book divergence
- Book disagreement across the market
- Stale line detection
- Hold-adjusted implied probability

Market efficiency assumption:
- Pinnacle/Circa are considered sharp books — follow their movement
- DraftKings/FanDuel/BetMGM/Caesars are recreational (larger hold, public-facing)
- When sharp book moves and rec book doesn't → sharp signal
- When all books agree and move together → broad market consensus

Key outputs per player:
- best_price: best available current odds across tracked books
- opening_price: odds at market open (Monday/Tuesday)
- model_vs_market_delta: our model prob vs hold-adjusted market prob
- line_movement_flag: "shortening", "lengthening", "stable", "volatile"
- sharp_signal: True if Pinnacle/Circa moved significantly vs rec books
- book_disagreement_score: variance across books (high = potential value)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Book tiers
SHARP_BOOKS = {"pinnacle", "circa", "bookmaker_eu"}
REC_BOOKS = {"draftkings", "fanduel", "betmgm", "caesars", "bet365", "pointsbet"}

STALE_THRESHOLD_HOURS = 48
SIGNIFICANT_MOVEMENT_PCT = 0.08  # 8% implied probability shift = significant


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def track_event_lines(event_id: str, raw_markets: dict) -> dict[str, dict]:
    """
    Process raw market data into tracked line objects per player.

    Args:
        event_id: event identifier
        raw_markets: dict of {market_type: {player_id: {book: {price, timestamp}}}}

    Returns:
        dict of {player_id: {market_type: line_tracking_object}}
    """
    tracked = {}

    for market_type, player_prices in raw_markets.items():
        for pid, book_prices in player_prices.items():
            if pid not in tracked:
                tracked[pid] = {}

            tracked[pid][market_type] = _build_line_tracker(
                pid, market_type, book_prices, event_id
            )

    return tracked


def get_best_price(line_tracker: dict, market_type: str, player_id: str) -> dict | None:
    """Get best available price for a player/market combination."""
    player_lines = line_tracker.get(player_id, {})
    market_lines = player_lines.get(market_type)
    if not market_lines:
        return None
    return {
        "price": market_lines.get("best_price"),
        "book": market_lines.get("best_book"),
        "hold_adjusted_prob": market_lines.get("best_hold_adjusted_prob"),
    }


def compute_edge(model_prob: float, implied_prob: float, hold: float = 0.05) -> float:
    """
    Compute edge as: model_prob - hold_adjusted_implied_prob.
    A positive edge means we have value.
    """
    hold_adjusted = implied_prob / (1 + hold)
    return round(model_prob - hold_adjusted, 5)


# ---------------------------------------------------------------------------
# Core line tracker builder
# ---------------------------------------------------------------------------

def _build_line_tracker(pid: str, market_type: str, book_prices: dict, event_id: str) -> dict:
    """
    Build a complete line tracking object from raw book prices.
    """
    if not book_prices:
        return _empty_tracker(pid, market_type)

    # Separate sharp and rec book prices
    sharp_prices = {b: v for b, v in book_prices.items() if b.lower() in SHARP_BOOKS}
    rec_prices = {b: v for b, v in book_prices.items() if b.lower() in REC_BOOKS}
    all_prices = book_prices

    # Current prices (latest timestamp per book)
    current_by_book = {
        book: _get_latest_price(price_history)
        for book, price_history in all_prices.items()
    }

    # Opening prices (earliest timestamp per book)
    opening_by_book = {
        book: _get_opening_price(price_history)
        for book, price_history in all_prices.items()
    }

    # Best available current price
    best_book, best_price = _find_best_price(current_by_book)

    # Implied probabilities (decimal odds assumed internally)
    current_implied_probs = {
        book: _decimal_to_implied_prob(price)
        for book, price in current_by_book.items()
        if price
    }

    # Market consensus (average)
    avg_implied = (
        sum(current_implied_probs.values()) / len(current_implied_probs)
        if current_implied_probs else None
    )

    # Sharp vs rec divergence
    sharp_avg = _avg_implied_from_books(sharp_prices)
    rec_avg = _avg_implied_from_books(rec_prices)
    sharp_signal = _detect_sharp_signal(sharp_avg, rec_avg)

    # Line movement
    opening_implied = _avg_implied_from_books(opening_by_book)
    movement_pct = _compute_movement(opening_implied, avg_implied)
    movement_flag = _classify_movement(movement_pct)

    # Hold-adjusted best price
    best_hold_adjusted = _hold_adjusted_prob(best_price) if best_price else None

    # Book disagreement
    disagreement_score = _compute_disagreement(current_implied_probs)

    # Staleness
    latest_update = _get_latest_timestamp(all_prices)
    hours_since_update = _compute_hours_since(latest_update)
    is_stale = hours_since_update > STALE_THRESHOLD_HOURS

    return {
        "player_id": pid,
        "market_type": market_type,
        "best_price": best_price,
        "best_book": best_book,
        "best_hold_adjusted_prob": best_hold_adjusted,
        "current_by_book": current_by_book,
        "opening_by_book": opening_by_book,
        "avg_implied_prob": round(avg_implied, 5) if avg_implied else None,
        "sharp_avg_implied": round(sharp_avg, 5) if sharp_avg else None,
        "rec_avg_implied": round(rec_avg, 5) if rec_avg else None,
        "sharp_signal": sharp_signal,
        "line_movement_pct": round(movement_pct, 5) if movement_pct is not None else None,
        "line_movement_flag": movement_flag,
        "book_disagreement_score": round(disagreement_score, 5),
        "hours_since_update": round(hours_since_update, 1),
        "is_stale": is_stale,
        "latest_update": latest_update,
    }


# ---------------------------------------------------------------------------
# Hold and probability utilities
# ---------------------------------------------------------------------------

def _decimal_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to raw implied probability."""
    if not decimal_odds or decimal_odds <= 1.0:
        return 0.0
    return round(1.0 / decimal_odds, 6)


def _american_to_decimal(american: int) -> float:
    """Convert American odds to decimal."""
    if american > 0:
        return round(1 + american / 100, 4)
    else:
        return round(1 + 100 / abs(american), 4)


def _hold_adjusted_prob(decimal_odds: float, hold: float = 0.05) -> float:
    """Return hold-adjusted implied probability for a price."""
    raw = _decimal_to_implied_prob(decimal_odds)
    return round(raw / (1 + hold), 6)


def _compute_disagreement(implied_probs: dict) -> float:
    """
    Compute book disagreement as the standard deviation of implied probabilities.
    Higher = more disagreement = potential market inefficiency.
    """
    if len(implied_probs) < 2:
        return 0.0
    values = list(implied_probs.values())
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return variance ** 0.5


# ---------------------------------------------------------------------------
# Movement detection
# ---------------------------------------------------------------------------

def _compute_movement(opening_implied: float | None, current_implied: float | None) -> float | None:
    """Compute % change in implied probability from open to current."""
    if opening_implied is None or current_implied is None or opening_implied == 0:
        return None
    return (current_implied - opening_implied) / opening_implied


def _classify_movement(movement_pct: float | None) -> str:
    """Classify line movement direction and magnitude."""
    if movement_pct is None:
        return "unknown"
    if movement_pct > SIGNIFICANT_MOVEMENT_PCT:
        return "shortening_significant"  # Line shortened (player getting bet)
    elif movement_pct > 0.03:
        return "shortening_mild"
    elif movement_pct < -SIGNIFICANT_MOVEMENT_PCT:
        return "lengthening_significant"  # Line drifting (market fading)
    elif movement_pct < -0.03:
        return "lengthening_mild"
    else:
        return "stable"


def _detect_sharp_signal(sharp_avg: float | None, rec_avg: float | None) -> bool:
    """
    Returns True if sharp books have moved significantly vs rec books.
    Indicates professional money may be at work.
    """
    if sharp_avg is None or rec_avg is None:
        return False
    # If sharp books price player shorter (higher implied) than rec books by 5%+
    delta = sharp_avg - rec_avg
    return abs(delta) > 0.05


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_latest_price(price_history: list | dict) -> float | None:
    """Get the most recent price from a price history list."""
    if isinstance(price_history, (int, float)):
        return float(price_history)
    if isinstance(price_history, list) and price_history:
        latest = sorted(price_history, key=lambda x: x.get("timestamp", ""), reverse=True)[0]
        return latest.get("price")
    return None


def _get_opening_price(price_history: list | dict) -> float | None:
    """Get the opening (earliest) price from a price history list."""
    if isinstance(price_history, (int, float)):
        return float(price_history)
    if isinstance(price_history, list) and price_history:
        earliest = sorted(price_history, key=lambda x: x.get("timestamp", ""))[0]
        return earliest.get("price")
    return None


def _find_best_price(current_by_book: dict) -> tuple[str | None, float | None]:
    """Find the book offering the best (highest decimal odds) price."""
    if not current_by_book:
        return None, None
    valid = {b: p for b, p in current_by_book.items() if p and p > 1.0}
    if not valid:
        return None, None
    best_book = max(valid, key=lambda b: valid[b])
    return best_book, valid[best_book]


def _avg_implied_from_books(books: dict) -> float | None:
    """Calculate average implied probability across a set of book prices."""
    if not books:
        return None
    prices = [_get_latest_price(v) for v in books.values()]
    probs = [_decimal_to_implied_prob(p) for p in prices if p]
    if not probs:
        return None
    return sum(probs) / len(probs)


def _get_latest_timestamp(all_prices: dict) -> str | None:
    """Find the most recent timestamp across all books and prices."""
    timestamps = []
    for book, price_history in all_prices.items():
        if isinstance(price_history, list):
            for entry in price_history:
                ts = entry.get("timestamp")
                if ts:
                    timestamps.append(ts)
    return max(timestamps) if timestamps else None


def _compute_hours_since(timestamp: str | None) -> float:
    """Compute hours since a given ISO timestamp."""
    if not timestamp:
        return 999.0
    try:
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        return delta.total_seconds() / 3600
    except Exception:
        return 999.0


def _empty_tracker(pid: str, market_type: str) -> dict:
    return {
        "player_id": pid,
        "market_type": market_type,
        "best_price": None,
        "best_book": None,
        "best_hold_adjusted_prob": None,
        "avg_implied_prob": None,
        "sharp_signal": False,
        "line_movement_flag": "no_data",
        "book_disagreement_score": 0.0,
        "hours_since_update": 999.0,
        "is_stale": True,
    }
