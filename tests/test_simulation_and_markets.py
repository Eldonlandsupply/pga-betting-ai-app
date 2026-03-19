"""
tests/test_simulation.py
tests/test_markets.py
"""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulations.monte_carlo import simulate_tournament, compute_h2h_probabilities
from markets.line_tracker import (
    track_event_lines, compute_edge,
    _decimal_to_implied_prob, _american_to_decimal,
    _hold_adjusted_prob, _compute_disagreement, _classify_movement,
)


# ---------------------------------------------------------------------------
# Monte Carlo simulation tests
# ---------------------------------------------------------------------------

class TestMonteCarlo(unittest.TestCase):

    def _make_players(self, n=10, skill=0.0, vol=2.8):
        return [
            {"player_id": f"p{i}", "skill_composite": skill + (i * 0.1),
             "volatility_sd": vol, "ceiling_boost": 0.0, "form_adjustment": 0.0}
            for i in range(n)
        ]

    def test_probabilities_sum_to_one(self):
        players = self._make_players(20)
        results = simulate_tournament("test_event", players, n_simulations=1000, tour="PGA")
        total_win = sum(r["win_prob"] for r in results.values())
        self.assertAlmostEqual(total_win, 1.0, delta=0.02)

    def test_top20_prob_higher_than_win_prob(self):
        players = self._make_players(50)
        results = simulate_tournament("test_event", players, n_simulations=1000, tour="PGA")
        for pid, r in results.items():
            self.assertGreaterEqual(r["top20_prob"], r["top10_prob"])
            self.assertGreaterEqual(r["top10_prob"], r["top5_prob"])
            self.assertGreaterEqual(r["top5_prob"], r["win_prob"])

    def test_better_player_wins_more(self):
        players = [
            {"player_id": "elite",  "skill_composite": 3.0, "volatility_sd": 2.5,
             "ceiling_boost": 0.0, "form_adjustment": 0.0},
            {"player_id": "average","skill_composite": 0.0, "volatility_sd": 2.8,
             "ceiling_boost": 0.0, "form_adjustment": 0.0},
        ]
        results = simulate_tournament("test", players, n_simulations=5000, tour="LIV")
        self.assertGreater(results["elite"]["win_prob"], results["average"]["win_prob"])

    def test_liv_no_cut_all_players_have_finish(self):
        players = self._make_players(48)
        results = simulate_tournament("test_liv", players, n_simulations=500, tour="LIV", apply_cut=False)
        for pid, r in results.items():
            self.assertIsNone(r["make_cut_prob"])   # LIV: no cut
            self.assertIsNotNone(r["win_prob"])

    def test_pga_cut_reduces_some_players_odds(self):
        # Need enough players that the cut actually eliminates some.
        # 2 players: both always make top-70, so make_cut_prob = 1.0 for both.
        # Use 120 players — cut at 70 means ~50 are eliminated.
        import random
        random.seed(42)
        players = []
        for i in range(120):
            if i == 0:
                skill, vol = 3.0, 2.5    # Star
            elif i == 1:
                skill, vol = -3.0, 4.5   # Weak
            else:
                skill, vol = 0.0, 3.0    # Average field
            players.append({"player_id": f"p{i}", "skill_composite": skill,
                             "volatility_sd": vol, "ceiling_boost": 0.0, "form_adjustment": 0.0})
        results = simulate_tournament("test_pga", players, n_simulations=1000,
                                      tour="PGA", apply_cut=True)
        star_cut = results["p0"].get("make_cut_prob", 1.0)
        weak_cut = results["p1"].get("make_cut_prob", 0.0)
        self.assertGreater(star_cut, weak_cut)

    def test_h2h_probs_sum_near_one(self):
        players = self._make_players(20)
        sim = simulate_tournament("test_h2h", players, n_simulations=2000, tour="PGA")
        h2h = compute_h2h_probabilities(sim, "p0", "p1")
        total = h2h["player_a_win_prob"] + h2h["player_b_win_prob"] + h2h["tie_prob"]
        self.assertAlmostEqual(total, 1.0, delta=0.01)

    def test_h2h_better_player_wins_more(self):
        players = [
            {"player_id": "a_elite",  "skill_composite": 3.0, "volatility_sd": 2.5,
             "ceiling_boost": 0.0, "form_adjustment": 0.0},
            {"player_id": "b_weak",   "skill_composite": -1.0,"volatility_sd": 3.0,
             "ceiling_boost": 0.0, "form_adjustment": 0.0},
        ]
        sim = simulate_tournament("test_h2h2", players, n_simulations=5000, tour="PGA")
        h2h = compute_h2h_probabilities(sim, "a_elite", "b_weak")
        self.assertGreater(h2h["player_a_win_prob"], h2h["player_b_win_prob"])

    def test_simulation_output_keys_present(self):
        players = self._make_players(5)
        results = simulate_tournament("test_keys", players, n_simulations=200, tour="PGA")
        for pid, r in results.items():
            for key in ("win_prob","top5_prob","top10_prob","top20_prob",
                        "median_finish","finish_sd","n_simulations"):
                self.assertIn(key, r, f"Key '{key}' missing for player {pid}")


# ---------------------------------------------------------------------------
# Line tracker / market tests
# ---------------------------------------------------------------------------

class TestLineTracker(unittest.TestCase):

    def test_decimal_to_implied_prob(self):
        self.assertAlmostEqual(_decimal_to_implied_prob(2.0), 0.5, places=4)
        self.assertAlmostEqual(_decimal_to_implied_prob(4.0), 0.25, places=4)
        self.assertAlmostEqual(_decimal_to_implied_prob(10.0), 0.10, places=4)

    def test_decimal_to_implied_invalid(self):
        self.assertEqual(_decimal_to_implied_prob(1.0), 0.0)
        self.assertEqual(_decimal_to_implied_prob(0.5), 0.0)

    def test_american_to_decimal_positive(self):
        self.assertAlmostEqual(_american_to_decimal(300), 4.0, places=2)
        self.assertAlmostEqual(_american_to_decimal(100), 2.0, places=2)

    def test_american_to_decimal_negative(self):
        self.assertAlmostEqual(_american_to_decimal(-200), 1.5, places=2)
        self.assertAlmostEqual(_american_to_decimal(-100), 2.0, places=2)

    def test_hold_adjusted_prob_lower_than_raw(self):
        raw = _decimal_to_implied_prob(5.0)
        adj = _hold_adjusted_prob(5.0, hold=0.05)
        self.assertLess(adj, raw)

    def test_compute_edge_positive(self):
        # Model says 30% win prob, market says 20% (after hold) → edge exists
        edge = compute_edge(model_prob=0.30, implied_prob=0.20, hold=0.05)
        self.assertGreater(edge, 0)

    def test_compute_edge_negative(self):
        # Market is more confident than model → negative edge
        edge = compute_edge(model_prob=0.10, implied_prob=0.25, hold=0.05)
        self.assertLess(edge, 0)

    def test_disagreement_zero_for_single_book(self):
        score = _compute_disagreement({"book_a": 0.20})
        self.assertEqual(score, 0.0)

    def test_disagreement_higher_for_divergent_books(self):
        low  = _compute_disagreement({"a": 0.20, "b": 0.21})
        high = _compute_disagreement({"a": 0.10, "b": 0.30})
        self.assertGreater(high, low)

    def test_movement_classification(self):
        self.assertEqual(_classify_movement(0.15), "shortening_significant")
        self.assertEqual(_classify_movement(-0.15), "lengthening_significant")
        self.assertEqual(_classify_movement(0.01), "stable")
        self.assertIn(_classify_movement(None), ("unknown",))

    def test_track_event_lines_returns_per_player_structure(self):
        from datetime import datetime, timezone, timedelta
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        raw_markets = {
            "outright": {
                "player_a": {
                    "fanduel": [{"price": 8.0, "timestamp": ts}],
                    "draftkings": [{"price": 8.5, "timestamp": ts}],
                }
            }
        }
        tracked = track_event_lines("test_event", raw_markets)
        self.assertIn("player_a", tracked)
        self.assertIn("outright", tracked["player_a"])
        outright = tracked["player_a"]["outright"]
        self.assertEqual(outright["best_price"], 8.5)
        self.assertEqual(outright["best_book"], "draftkings")
        self.assertFalse(outright["is_stale"])

    def test_stale_line_detected(self):
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        raw_markets = {
            "outright": {
                "old_player": {
                    "fanduel": [{"price": 5.0, "timestamp": old_ts}]
                }
            }
        }
        tracked = track_event_lines("test_stale", raw_markets)
        self.assertTrue(tracked["old_player"]["outright"]["is_stale"])


if __name__ == "__main__":
    unittest.main()
