"""Unit tests for the 30-second sliding-window RiskScorer."""

from src.scoring.risk_scorer import RiskScorer


def test_risk_scorer_levels_and_cap():
    scorer = RiskScorer()

    # Low: < 30 (hand movement = 10)
    res_low = scorer.update(1, [("unusual_hand_movement", "Fast hand")], timestamp_sec=5.0)
    assert res_low.score == 10
    assert res_low.level == "Low"

    # Medium: 30-59 (add repeated_side_look = 25 -> total 35)
    res_med = scorer.update(1, [("repeated_side_look", "3 side-looks")], timestamp_sec=10.0)
    assert res_med.score == 35
    assert res_med.level == "Medium"

    # High: >= 60 (add phone_visible = 40 -> total 75)
    res_high = scorer.update(1, [("phone_visible", "Phone 3+ s")], timestamp_sec=15.0)
    assert res_high.score == 75
    assert res_high.level == "High"
    assert len(res_high.reasons) == 3

    # Cap at 100 even when all 5 indicators (sum 105) are active
    res_cap = scorer.update(
        1,
        [("possible_talking", "Lip motion"), ("close_interaction", "Close")],
        timestamp_sec=20.0,
    )
    assert res_cap.score == 100
    assert res_cap.level == "High"


def test_risk_scorer_window_expiry():
    scorer = RiskScorer(window_sec=30.0)
    scorer.update(2, [("phone_visible", "Phone 3+ s")], timestamp_sec=10.0)

    # At t=41.0, indicator from t=10.0 has expired (> 30s)
    res = scorer.update(2, [], timestamp_sec=41.0)
    assert res.score == 0
    assert res.level == "Low"
    assert res.reasons == []
