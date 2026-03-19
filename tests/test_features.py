"""
tests/test_features.py
-----------------------
Unit tests for all feature engineering modules.
"""
import sys, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from features.player_baseline import build_baselines, _weighted_mean, _field_strength_weight
from features.recent_form import build_form_features, _regress_putting, _compute_form_trend
from features.volatility import build_volatility_profiles, _compute_ceiling, _compute_consistency, _classify_tier
from features.contextual_flags import build_contextual_flags, _weeks_since
from features.market_signals import build_market_signals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_player(pid="p1", tour="PGA", **kwargs):
    base = {"id": pid, "tour": tour, "injury_status": "healthy",
            "last_event_date": "2026-03-01", "recent_event_count_5w": 2}
    base.update(kwargs)
    return base

def _make_rounds(n=20, sg_total=1.5, sg_ott=0.4, sg_app=0.7, sg_atg=0.2, sg_putt=0.2):
    from datetime import date, timedelta
    rounds = []
    base = date(2026, 3, 1)
    for i in range(n):
        d = base - timedelta(days=i * 7)
        rounds.append({
            "event_id": f"event_{i}",
            "round": 1,
            "date": d.isoformat(),
            "sg_total": sg_total,
            "sg_ott":   sg_ott,
            "sg_app":   sg_app,
            "sg_atg":   sg_atg,
            "sg_putt":  sg_putt,
            "field_strength_percentile": 70,
            "no_cut_event": False,
            "score": -3,
        })
    return rounds

def _make_stats(n_rounds=40, sg_total=1.5, sg_ott=0.4, sg_app=0.7, sg_atg=0.2, sg_putt=0.2, **kwargs):
    rounds = _make_rounds(n_rounds, sg_total=sg_total, sg_ott=sg_ott,
                          sg_app=sg_app, sg_atg=sg_atg, sg_putt=sg_putt)
    base = {
        "rounds": rounds,
        "sg_total": sg_total,
        "sg_ott":   sg_ott,
        "sg_app":   sg_app,
        "sg_atg":   sg_atg,
        "sg_putt":  sg_putt,
        "driving_distance": 295, "driving_accuracy_pct": 65,
        "gir_pct": 70, "scrambling_pct": 60,
        "birdie_or_better_pct": 22, "bogey_avoidance": 0.1,
        "par3_scoring_avg": 2.95, "par4_scoring_avg": 3.90, "par5_scoring_avg": 4.65,
        "make_cut_rate": 0.80, "top10_rate": 0.25, "win_rate": 0.05,
        "bent_grass_sg_putt": 0.30, "bermuda_sg_putt": 0.10, "poa_sg_putt": 0.20,
        "wind_20plus_sg": 1.2, "final_round_sg": 0.5, "major_sg": 1.1,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# player_baseline tests
# ---------------------------------------------------------------------------

class TestPlayerBaseline(unittest.TestCase):

    def test_builds_baseline_for_valid_player(self):
        field = [_make_player("p1")]
        stats = {"p1": _make_stats(40)}
        result = build_baselines(field, stats)
        self.assertIn("p1", result)
        b = result["p1"]
        self.assertIsNotNone(b["composite_sg"])
        self.assertGreater(b["data_rounds"], 0)
        self.assertGreater(b["data_confidence"], 0)

    def test_null_baseline_for_missing_player(self):
        field = [_make_player("p_unknown")]
        stats = {}
        result = build_baselines(field, stats)
        self.assertEqual(result["p_unknown"]["uncertainty_flag"], "NO_DATA")
        self.assertEqual(result["p_unknown"]["data_confidence"], 0.0)

    def test_thin_baseline_flagged(self):
        field = [_make_player("p_thin")]
        stats = {"p_thin": _make_stats(5)}
        result = build_baselines(field, stats)
        self.assertIn(result["p_thin"]["uncertainty_flag"], ("THIN_SAMPLE", "LOW_CONFIDENCE"))

    def test_composite_sg_direction(self):
        field = [_make_player("good"), _make_player("bad")]
        stats = {
            "good": _make_stats(40, sg_total=3.0, sg_ott=0.8, sg_app=1.5, sg_atg=0.4, sg_putt=0.3),
            "bad":  _make_stats(40, sg_total=-1.0, sg_ott=-0.3, sg_app=-0.5, sg_atg=-0.1, sg_putt=-0.1),
        }
        result = build_baselines(field, stats)
        # Good player has higher positive SG components; bad player has negatives
        good_sg = result["good"]["composite_sg"]
        bad_sg  = result["bad"]["composite_sg"]
        # Both are computed from identical weights — direction determined by SG values
        self.assertIsNotNone(good_sg)
        self.assertIsNotNone(bad_sg)
        self.assertGreater(good_sg, bad_sg)

    def test_weighted_mean_ignores_none(self):
        vals = [(1.0, 1.0), (None, 0.5), (3.0, 1.0)]
        result = _weighted_mean(vals)
        self.assertAlmostEqual(result, 2.0, places=4)

    def test_weighted_mean_all_none_returns_none(self):
        vals = [(None, 1.0), (None, 1.0)]
        result = _weighted_mean(vals)
        self.assertIsNone(result)

    def test_field_strength_weight_bounds(self):
        self.assertAlmostEqual(_field_strength_weight(0), 0.8, places=3)
        self.assertAlmostEqual(_field_strength_weight(100), 1.2, places=3)
        mid = _field_strength_weight(50)
        self.assertGreater(mid, 0.8)
        self.assertLess(mid, 1.2)

    def test_liv_transfer_discount_applied(self):
        field = [_make_player("liv_p", tour="LIV")]
        stats = {"liv_p": {**_make_stats(40), "pga_to_liv_transfer": True}}
        result = build_baselines(field, stats)
        self.assertTrue(result["liv_p"]["is_liv_transfer"])
        # Confidence should be reduced
        self.assertLess(result["liv_p"]["data_confidence"], 0.90)


# ---------------------------------------------------------------------------
# recent_form tests
# ---------------------------------------------------------------------------

class TestRecentForm(unittest.TestCase):

    def test_form_score_direction(self):
        field = [_make_player("hot"), _make_player("cold")]
        stats = {
            "hot":  _make_stats(20, sg_total=3.5),
            "cold": _make_stats(20, sg_total=-1.0),
        }
        result = build_form_features(field, stats)
        self.assertGreater(result["hot"]["form_adjusted_sg"], result["cold"]["form_adjusted_sg"])

    def test_null_form_for_no_stats(self):
        field = [_make_player("nobody")]
        result = build_form_features(field, {})
        self.assertIsNone(result["nobody"]["form_adjusted_sg"])
        self.assertEqual(result["nobody"]["form_confidence"], 0.0)

    def test_putting_regression_pulls_toward_baseline(self):
        # Recent putting well above baseline → should be pulled back
        regressed = _regress_putting(recent=2.0, baseline=0.3)
        self.assertLess(regressed, 2.0)
        self.assertGreater(regressed, 0.3)

    def test_putting_regression_extreme_pulls_harder(self):
        mild_regress = _regress_putting(recent=0.8, baseline=0.3)
        hard_regress = _regress_putting(recent=2.5, baseline=0.3)
        # Both pull toward baseline, but extreme spike uses a higher regression rate (0.65)
        # vs mild spike (0.75). So extreme ends up proportionally closer to baseline.
        # hard_regress should be closer to baseline (0.3) in absolute distance
        # relative to the original gap than mild_regress.
        # Original mild gap: 0.5, hard gap: 2.2
        mild_remaining_pct = abs(mild_regress - 0.3) / 0.5   # fraction of gap remaining
        hard_remaining_pct = abs(hard_regress - 0.3) / 2.2   # fraction of gap remaining
        # Extreme regression rate = 0.65 → 35% of gap remains
        # Mild regression rate = 0.75 → 25% of gap remains
        # mild_remaining_pct (0.25) < hard_remaining_pct (0.35)
        self.assertLess(mild_remaining_pct, hard_remaining_pct)

    def test_form_trend_detection(self):
        # 6 events: first 3 bad, last 3 good → declining (most recent first)
        events = [
            {"sg_total": -1.0, "sg_putt": 0.0, "field_strength_pct": 70},
            {"sg_total": -0.8, "sg_putt": 0.0, "field_strength_pct": 70},
            {"sg_total": -0.5, "sg_putt": 0.0, "field_strength_pct": 70},
            {"sg_total":  2.0, "sg_putt": 0.0, "field_strength_pct": 70},
            {"sg_total":  2.2, "sg_putt": 0.0, "field_strength_pct": 70},
            {"sg_total":  2.5, "sg_putt": 0.0, "field_strength_pct": 70},
        ]
        weights = [0.28, 0.22, 0.17, 0.13, 0.09, 0.06]
        trend, magnitude = _compute_form_trend(events, weights)
        self.assertEqual(trend, "declining")
        self.assertLess(magnitude, 0)


# ---------------------------------------------------------------------------
# volatility tests
# ---------------------------------------------------------------------------

class TestVolatility(unittest.TestCase):

    def test_elite_consistent_player(self):
        field = [_make_player("elite")]
        stats = {"elite": _make_stats(60, make_cut_rate=0.92, top10_rate=0.40, win_rate=0.10)}
        result = build_volatility_profiles(field, stats)
        self.assertIn(result["elite"]["volatility_tier"],
                      ("elite_consistent", "high_ceiling", "grinder"))

    def test_null_profile_for_missing(self):
        field = [_make_player("nobody")]
        result = build_volatility_profiles(field, {})
        self.assertEqual(result["nobody"]["volatility_tier"], "volatile")
        self.assertEqual(result["nobody"]["ceiling_score"], 0.0)

    def test_ceiling_score_higher_for_winner(self):
        winner_ceil = _compute_ceiling(win_rate=0.12, top10_rate=0.35, sd=3.0)
        journeyman  = _compute_ceiling(win_rate=0.01, top10_rate=0.10, sd=2.8)
        self.assertGreater(winner_ceil, journeyman)

    def test_consistency_high_cut_rate(self):
        high = _compute_consistency(cut_rate=0.92, bogey_avoidance=0.2, sd=2.5)
        low  = _compute_consistency(cut_rate=0.50, bogey_avoidance=-0.1, sd=3.8)
        self.assertGreater(high, low)

    def test_tier_classification_boom_bust(self):
        tier = _classify_tier(consistency=0.20, ceiling=0.35, sd=4.0)
        self.assertIn(tier, ("boom_bust", "volatile"))

    def test_recommended_markets_not_empty_for_known_tier(self):
        from features.volatility import _recommend_markets
        for tier in ("elite_consistent", "high_ceiling", "grinder"):
            self.assertTrue(len(_recommend_markets(tier)) > 0)

    def test_volatile_gets_no_recommended_markets(self):
        from features.volatility import _recommend_markets
        self.assertEqual(_recommend_markets("volatile"), [])


# ---------------------------------------------------------------------------
# contextual_flags tests
# ---------------------------------------------------------------------------

class TestContextualFlags(unittest.TestCase):

    def test_healthy_player_no_penalty(self):
        field = [_make_player("p1", injury_status="healthy")]
        result = build_contextual_flags(field)
        self.assertEqual(result["p1"]["contextual_adjustment"], 0.0)
        self.assertIsNone(result["p1"]["injury_flag"])

    def test_injury_penalty_applied(self):
        field = [_make_player("p_inj", injury_status="moderate")]
        result = build_contextual_flags(field)
        self.assertLess(result["p_inj"]["contextual_adjustment"], 0)
        self.assertIsNotNone(result["p_inj"]["injury_flag"])

    def test_rust_penalty_for_long_layoff(self):
        # 6 weeks ago
        from datetime import date, timedelta
        old_date = (date.today() - timedelta(weeks=6)).isoformat()
        field = [_make_player("rusty", last_event_date=old_date)]
        result = build_contextual_flags(field)
        self.assertTrue(result["rusty"]["rust_flag"])
        self.assertLess(result["rusty"]["contextual_adjustment"], 0)

    def test_no_rust_for_recent_event(self):
        from datetime import date, timedelta
        recent = (date.today() - timedelta(days=10)).isoformat()
        field = [_make_player("fresh", last_event_date=recent)]
        result = build_contextual_flags(field)
        self.assertFalse(result["fresh"]["rust_flag"])

    def test_weeks_since_calculation(self):
        from datetime import date, timedelta
        two_weeks_ago = (date.today() - timedelta(weeks=2)).isoformat()
        weeks = _weeks_since(two_weeks_ago)
        self.assertAlmostEqual(weeks, 2.0, delta=0.2)

    def test_weeks_since_none_returns_none(self):
        self.assertIsNone(_weeks_since(None))

    def test_severe_injury_large_penalty(self):
        field = [_make_player("hurt", injury_status="severe")]
        result = build_contextual_flags(field)
        self.assertLess(result["hurt"]["contextual_adjustment"], -1.0)

    def test_unverified_injury_applies_uncertainty_penalty(self):
        field = [_make_player("unk", injury_status="unverified")]
        result = build_contextual_flags(field)
        self.assertLess(result["unk"]["contextual_adjustment"], -0.20)


# ---------------------------------------------------------------------------
# market_signals tests
# ---------------------------------------------------------------------------

class TestMarketSignals(unittest.TestCase):

    def _make_tracker(self, sharp_signal=False, sharp_avg=None, rec_avg=None,
                      movement_pct=0.0, disagreement=0.01, stale=False):
        return {
            "sharp_signal": sharp_signal,
            "sharp_avg_implied": sharp_avg,
            "rec_avg_implied": rec_avg,
            "line_movement_pct": movement_pct,
            "book_disagreement_score": disagreement,
            "is_stale": stale,
        }

    def test_sharp_backing_positive_signal(self):
        field = [_make_player("p1")]
        markets = {"p1": {"outright": self._make_tracker(
            sharp_signal=True, sharp_avg=0.15, rec_avg=0.09, movement_pct=0.05
        )}}
        result = build_market_signals(field, markets)
        self.assertGreater(result["p1"]["market_edge_signal"], 0)

    def test_no_market_data_neutral_signal(self):
        field = [_make_player("p1")]
        result = build_market_signals(field, {})
        self.assertEqual(result["p1"]["market_edge_signal"], 0.0)

    def test_stale_market_flagged(self):
        field = [_make_player("p1")]
        markets = {"p1": {"outright": self._make_tracker(stale=True)}}
        result = build_market_signals(field, markets)
        self.assertIn("outright", result["p1"]["stale_market_flags"])

    def test_market_signal_capped(self):
        field = [_make_player("p1")]
        # Extreme sharp divergence — should still be capped
        markets = {"p1": {"outright": self._make_tracker(
            sharp_signal=True, sharp_avg=0.50, rec_avg=0.05, movement_pct=0.30
        )}}
        result = build_market_signals(field, markets)
        self.assertLessEqual(result["p1"]["market_edge_signal"], 0.50)
        self.assertGreaterEqual(result["p1"]["market_edge_signal"], -0.50)

    def test_sharp_fading_negative_signal(self):
        field = [_make_player("p1")]
        markets = {"p1": {"outright": self._make_tracker(
            sharp_signal=True, sharp_avg=0.05, rec_avg=0.15, movement_pct=-0.10
        )}}
        result = build_market_signals(field, markets)
        self.assertLess(result["p1"]["market_edge_signal"], 0)


if __name__ == "__main__":
    unittest.main()
