"""
tests/test_audit_and_picks.py
------------------------------
Tests for post-event audit, adversarial review, and picks engine logic.
"""
import sys, unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from audit.post_event_audit import (
    _grade_pick, _grade_by_market, _compute_pnl,
    _compute_expected_ev, _assess_model_direction, _compute_metrics,
)
from picks.adversarial_review import (
    run_adversarial_review, _compute_kill_score, _downgrade_tier,
    _detect_correlated_stacks,
)
from picks.card_builder import build_betting_card, build_markdown_card


# ---------------------------------------------------------------------------
# Audit grading tests
# ---------------------------------------------------------------------------

class TestPickGrading(unittest.TestCase):

    def _base_pick(self, **kwargs):
        base = {
            "player_id": "p1", "market_type": "top_10", "price": 3.0,
            "model_probability": 0.40, "implied_probability": 0.33,
            "stake_units": 1.0, "risk_flags": [], "supporting_signals": {},
        }
        base.update(kwargs)
        return base

    def test_win_grade_top10(self):
        grade = _grade_by_market("top_10", 8, {}, True)
        self.assertEqual(grade, "win")

    def test_loss_grade_top10(self):
        grade = _grade_by_market("top_10", 15, {}, True)
        self.assertEqual(grade, "loss")

    def test_win_grade_outright(self):
        self.assertEqual(_grade_by_market("outright", 1, {}, True), "win")
        self.assertEqual(_grade_by_market("outright", 2, {}, True), "loss")

    def test_make_cut_grade(self):
        self.assertEqual(_grade_by_market("make_cut", 5, {}, True), "win")
        self.assertEqual(_grade_by_market("make_cut", 5, {}, False), "loss")

    def test_miss_cut_grade(self):
        self.assertEqual(_grade_by_market("miss_cut", 5, {}, False), "win")
        self.assertEqual(_grade_by_market("miss_cut", 5, {}, True), "loss")

    def test_pnl_win(self):
        pnl = _compute_pnl("win", price=4.0, stake=1.0)
        self.assertAlmostEqual(pnl, 3.0, places=4)

    def test_pnl_loss(self):
        pnl = _compute_pnl("loss", price=4.0, stake=1.0)
        self.assertAlmostEqual(pnl, -1.0, places=4)

    def test_pnl_push(self):
        self.assertAlmostEqual(_compute_pnl("push", 2.0, 1.0), 0.0, places=4)

    def test_pnl_void(self):
        self.assertAlmostEqual(_compute_pnl("void", 2.0, 1.0), 0.0, places=4)

    def test_expected_ev_positive(self):
        ev = _compute_expected_ev(model_prob=0.50, price=3.0, stake=1.0)
        # EV = 1 * (0.5 * 2 - 0.5) = 0.5
        self.assertAlmostEqual(ev, 0.5, places=4)

    def test_expected_ev_negative(self):
        ev = _compute_expected_ev(model_prob=0.10, price=2.0, stake=1.0)
        # EV = 1 * (0.1 * 1 - 0.9) = -0.8
        self.assertAlmostEqual(ev, -0.8, places=4)

    def test_model_direction_right_right(self):
        pick = {"model_probability": 0.40, "implied_probability": 0.25}
        self.assertEqual(_assess_model_direction("win", 0.40, pick), "right_right")

    def test_model_direction_right_wrong(self):
        pick = {"model_probability": 0.40, "implied_probability": 0.25}
        self.assertEqual(_assess_model_direction("loss", 0.40, pick), "right_wrong")

    def test_model_direction_wrong_right(self):
        pick = {"model_probability": 0.10, "implied_probability": 0.35}
        self.assertEqual(_assess_model_direction("win", 0.10, pick), "wrong_right")

    def test_model_direction_wrong_wrong(self):
        pick = {"model_probability": 0.10, "implied_probability": 0.35}
        self.assertEqual(_assess_model_direction("loss", 0.10, pick), "wrong_wrong")

    def test_grade_pick_full(self):
        pick = self._base_pick()
        position_lookup = {"p1": {"final_position": 7, "made_cut": True}}
        graded = _grade_pick(pick, position_lookup, {})
        self.assertEqual(graded["grade"], "win")
        self.assertGreater(graded["pnl_units"], 0)

    def test_grade_pick_absent_player_void(self):
        pick = self._base_pick(player_id="nobody")
        graded = _grade_pick(pick, {}, {})
        self.assertEqual(graded["grade"], "void")

    def test_compute_metrics_basic(self):
        graded_picks = [
            {"grade": "win",  "pnl_units": 2.0, "ev_expected": 0.5,
             "stake_units": 1.0, "model_directionally_correct": "right_right", "closing_line_value": 0.02},
            {"grade": "loss", "pnl_units": -1.0, "ev_expected": -0.2,
             "stake_units": 1.0, "model_directionally_correct": "right_wrong", "closing_line_value": 0.01},
            {"grade": "win",  "pnl_units": 1.0, "ev_expected": 0.4,
             "stake_units": 1.0, "model_directionally_correct": "right_right", "closing_line_value": None},
        ]
        metrics = _compute_metrics(graded_picks)
        self.assertEqual(metrics["wins"], 2)
        self.assertEqual(metrics["losses"], 1)
        self.assertAlmostEqual(metrics["hit_rate_pct"], 66.7, delta=0.2)
        self.assertGreater(metrics["total_pnl_units"], 0)


# ---------------------------------------------------------------------------
# Adversarial review tests
# ---------------------------------------------------------------------------

class TestAdversarialReview(unittest.TestCase):

    def _base_pick(self, **kwargs):
        base = {
            "player_id": "p1", "market_type": "top_10", "price": 3.0,
            "model_probability": 0.38, "implied_probability": 0.28,
            "edge_pct": 10.0, "confidence_tier": "strong",
            "risk_flags": [], "adversarial_challenges": [],
            "dominant_signal": "course_fit", "signal_diversity_score": 0.70,
            "form_driven": False, "form_streak_events": 5,
            "weather_risk_flag": False, "tour": "PGA",
            "safe_bets": [], "value_bets": [], "upside_outrights": [],
            "matchup_bets": [], "placement_bets": [], "longshot_bets": [],
        }
        base.update(kwargs)
        return base

    def _base_model(self, **kwargs):
        base = {
            "data_rounds": 50, "data_confidence": 0.85,
            "signal_diversity_score": 0.70, "form_streak_events": 5,
            "form_driven": False, "course_fit_score": 0.3,
            "weather_risk_flag": False, "world_rank": 25,
            "comp_course_rounds": 8, "confidence_band_width": 0.05,
        }
        base.update(kwargs)
        return base

    def _base_market(self, **kwargs):
        base = {
            "line_movement_pct": 0.01, "hours_since_update": 6,
            "sharp_signal": False, "book_disagreement_score": 0.01,
        }
        base.update(kwargs)
        return base

    def test_clean_pick_passes(self):
        card = {"safe_bets": [self._base_pick()],
                "value_bets": [], "upside_outrights": [],
                "matchup_bets": [], "placement_bets": [], "longshot_bets": []}
        model_outputs = {"p1": self._base_model(
            data_rounds=60,
            data_confidence=0.95,
            signal_diversity_score=0.80,
            form_streak_events=5,
            form_driven=False,
            course_fit_score=0.35,
            weather_risk_flag=False,
            world_rank=50,              # Not top-10 → no FAMOUS_NAME_BIAS
            comp_course_rounds=10,
            confidence_band_width=0.03, # Tight band → no LOW_CONVICTION
        )}
        markets = {"p1": {"top_10": self._base_market(
            line_movement_pct=0.02,
            hours_since_update=4,
            sharp_signal=False,
            book_disagreement_score=0.01,
        )}}
        result = run_adversarial_review(card, model_outputs, markets)
        passed = result["adversarial_summary"]["passed"]
        self.assertGreater(passed, 0)
        killed = result["adversarial_summary"]["killed"]
        self.assertEqual(killed, 0)

    def test_injury_unverified_kills_pick(self):
        pick = self._base_pick(risk_flags=["injury_unverified"])
        card = {"safe_bets": [pick], "value_bets": [], "upside_outrights": [],
                "matchup_bets": [], "placement_bets": [], "longshot_bets": []}
        model_outputs = {"p1": self._base_model()}
        markets = {"p1": {"top_10": self._base_market()}}
        result = run_adversarial_review(card, model_outputs, markets)
        self.assertGreater(result["adversarial_summary"]["killed"], 0)

    def test_thin_sample_downgrades(self):
        card = {"safe_bets": [self._base_pick()], "value_bets": [], "upside_outrights": [],
                "matchup_bets": [], "placement_bets": [], "longshot_bets": []}
        model_outputs = {"p1": self._base_model(data_rounds=5, data_confidence=0.20)}
        markets = {"p1": {"top_10": self._base_market()}}
        result = run_adversarial_review(card, model_outputs, markets)
        total_affected = (result["adversarial_summary"]["killed"] +
                          result["adversarial_summary"]["downgraded"])
        self.assertGreater(total_affected, 0)

    def test_kill_score_critical_is_3(self):
        challenges = [{"flag": "INJURY_UNVERIFIED", "severity": "critical"}]
        self.assertEqual(_compute_kill_score(challenges), 3)

    def test_kill_score_multiple_medium_adds(self):
        challenges = [
            {"flag": "HOT_STREAK", "severity": "medium"},
            {"flag": "STALE_LINE", "severity": "medium"},
            {"flag": "NO_COMP_HISTORY", "severity": "medium"},
        ]
        self.assertEqual(_compute_kill_score(challenges), 3)

    def test_tier_downgrade(self):
        self.assertEqual(_downgrade_tier("elite"), "strong")
        self.assertEqual(_downgrade_tier("strong"), "value")
        self.assertEqual(_downgrade_tier("value"), "speculative")
        self.assertEqual(_downgrade_tier("speculative"), "speculative")

    def test_correlated_stack_detection(self):
        picks = [
            {"player_id": "p1", "market_type": "outright"},
            {"player_id": "p1", "market_type": "top_10"},  # Same player
            {"player_id": "p2", "market_type": "top_20"},
        ]
        pairs = _detect_correlated_stacks(picks)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["player_id"], "p1")

    def test_no_false_correlation(self):
        picks = [
            {"player_id": "p1", "market_type": "outright"},
            {"player_id": "p2", "market_type": "outright"},
        ]
        pairs = _detect_correlated_stacks(picks)
        self.assertEqual(len(pairs), 0)


# ---------------------------------------------------------------------------
# Card builder tests
# ---------------------------------------------------------------------------

class TestCardBuilder(unittest.TestCase):

    def _sample_pick(self, pid="p1", mt="top_10", price=3.0, edge=8.5):
        return {
            "pick_id": f"pick_{pid}_{mt}",
            "player_id": pid, "player_name": f"Player {pid}",
            "tour": "PGA", "market_type": mt, "price": price,
            "book": "fanduel", "model_probability": 0.38,
            "implied_probability": 0.28, "hold_adjusted_probability": 0.267,
            "edge_pct": edge, "edge_raw": edge / 100,
            "confidence_tier": "strong", "stake_units": 0.015,
            "dominant_signal": "course_fit", "signal_diversity_score": 0.70,
            "form_driven": False, "supporting_reasons": ["Strong SG profile"],
            "risk_flags": [], "sharp_signal": True, "line_movement_flag": "stable",
            "adversarial_verdict": "PASSED", "adversarial_challenges": [],
            "course_fit_score": 0.45, "composite_sg": 2.1, "data_confidence": 0.88,
        }

    def test_build_card_has_all_categories(self):
        raw = {
            "safe_bets": [self._sample_pick("p1", "top_10")],
            "value_bets": [self._sample_pick("p2", "top_20")],
            "upside_outrights": [self._sample_pick("p3", "outright", price=15.0)],
            "matchup_bets": [],
            "placement_bets": [],
            "longshot_bets": [],
            "avoid_list": [],
        }
        card = build_betting_card(raw)
        for key in ("safe_bets", "value_bets", "upside_outrights",
                    "matchup_bets", "placement_bets", "longshot_bets", "avoid_list"):
            self.assertIn(key, card)

    def test_build_card_total_count(self):
        raw = {
            "safe_bets": [self._sample_pick()],
            "value_bets": [self._sample_pick("p2"), self._sample_pick("p3")],
            "upside_outrights": [], "matchup_bets": [],
            "placement_bets": [], "longshot_bets": [], "avoid_list": [],
        }
        card = build_betting_card(raw)
        self.assertEqual(card["total_candidates"], 3)

    def test_markdown_card_renders(self):
        raw = {"safe_bets": [self._sample_pick()], "value_bets": [],
               "upside_outrights": [], "matchup_bets": [],
               "placement_bets": [], "longshot_bets": [], "avoid_list": []}
        card = build_betting_card(raw)
        card["adversarial_summary"] = {"passed": 1, "downgraded": 0,
                                        "killed": 0, "top_concerns_this_week": []}
        card["correlated_pairs"] = []
        md = build_markdown_card("test_event", card)
        self.assertIn("Weekly Betting Card", md)
        self.assertIn("Player p1", md)
        self.assertIn("Model Notes", md)

    def test_avoid_list_in_markdown(self):
        raw = {"safe_bets": [], "value_bets": [], "upside_outrights": [],
               "matchup_bets": [], "placement_bets": [], "longshot_bets": [],
               "avoid_list": [{"player_id": "star", "player_name": "Big Name Star",
                               "market_type": "outright", "best_price": 4.0,
                               "model_probability": 0.10, "implied_probability": 0.25,
                               "overvaluation_pct": 150.0,
                               "avoid_reason": "Overbet by public"}]}
        card = build_betting_card(raw)
        card["adversarial_summary"] = {"passed": 0, "downgraded": 0,
                                        "killed": 0, "top_concerns_this_week": []}
        card["correlated_pairs"] = []
        md = build_markdown_card("test_event", card)
        self.assertIn("Big Name Star", md)
        self.assertIn("Avoid", md)


if __name__ == "__main__":
    unittest.main()
