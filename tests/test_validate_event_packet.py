import unittest
from datetime import datetime, timedelta, timezone

from scripts.validate_event_packet import validate_packet


class ValidateEventPacketTests(unittest.TestCase):
    def test_valid_packet(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        packet = {
            "event": {
                "tournament": "Sample Open",
                "tour": "pga",
                "course": "Sample Course",
                "format": "72-hole stroke play",
            },
            "data_quality": {"source_freshness": "fresh", "missing_fields": [], "conflicts": []},
            "markets": [
                {
                    "bet_type": "top_20",
                    "player": "Player A",
                    "sportsbook": "Book A",
                    "odds_decimal": 2.4,
                    "timestamp": (now - timedelta(minutes=5)).isoformat(),
                }
            ],
            "recommendations": [
                {
                    "rank": 1,
                    "bet_type": "top_20",
                    "player": "Player A",
                    "implied_probability": 0.42,
                    "fair_probability": 0.47,
                    "edge_percent": 5.0,
                    "confidence": 0.66,
                    "min_acceptable_odds": 2.3,
                    "no_play_below_odds": 2.1,
                    "reasoning": "Ball-striking stability and course-fit signal.",
                    "invalidation_conditions": ["wind shifts above forecast"],
                }
            ],
        }

        errors = validate_packet(packet, now=now)
        self.assertEqual(errors, [])

    def test_rejects_stale_markets_and_bad_thresholds(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        packet = {
            "event": {
                "tournament": "Sample Open",
                "tour": "liv",
                "course": "Sample Course",
                "format": "54-hole no cut",
            },
            "data_quality": {
                "source_freshness": "aging",
                "missing_fields": ["players.wind_split"],
                "conflicts": ["player_status_feed_disagree"],
            },
            "markets": [
                {
                    "bet_type": "outright",
                    "player": "Player B",
                    "sportsbook": "Book B",
                    "odds_decimal": 15.0,
                    "timestamp": (now - timedelta(minutes=120)).isoformat(),
                }
            ],
            "recommendations": [
                {
                    "rank": 1,
                    "bet_type": "outright",
                    "player": "Player B",
                    "implied_probability": 0.07,
                    "fair_probability": 0.09,
                    "edge_percent": 2.0,
                    "confidence": 0.54,
                    "min_acceptable_odds": 14.0,
                    "no_play_below_odds": 14.5,
                    "reasoning": "Translation from major form.",
                    "invalidation_conditions": ["travel fatigue indicator worsens"],
                }
            ],
        }

        errors = validate_packet(packet, now=now)
        self.assertTrue(any("stale line timestamp" in error for error in errors))
        self.assertTrue(any("invalid thresholds" in error for error in errors))
        self.assertTrue(any("MISSING fields present" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
