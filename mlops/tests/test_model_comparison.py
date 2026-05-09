"""Unit tests for model_comparison module."""

import pytest
from tasks.model_comparison import evaluate_comparison_gates


def test_all_gates_pass():
    """Challenger beats champion on all metrics."""
    champion = {"f1_score": 0.85, "precision": 0.80, "recall": 0.90}
    challenger = {"f1_score": 0.87, "precision": 0.82, "recall": 0.91}
    passed, gates = evaluate_comparison_gates(champion, challenger)
    assert passed is True
    assert all(g["passed"] for g in gates)


def test_f1_regression_fails():
    """F1 regression beyond 1% tolerance fails."""
    champion = {"f1_score": 0.85, "precision": 0.80, "recall": 0.90}
    challenger = {"f1_score": 0.80, "precision": 0.82, "recall": 0.91}
    passed, gates = evaluate_comparison_gates(champion, challenger)
    assert passed is False
    assert not gates[0]["passed"]  # f1_score gate


def test_no_champion_metrics():
    """First model (empty champion) should pass all gates."""
    champion = {}
    challenger = {"f1_score": 0.85, "precision": 0.80, "recall": 0.90}
    passed, gates = evaluate_comparison_gates(champion, challenger)
    assert passed is True


def test_precision_within_tolerance():
    """Precision within 5% tolerance passes."""
    champion = {"f1_score": 0.85, "precision": 0.80, "recall": 0.90}
    challenger = {"f1_score": 0.85, "precision": 0.76, "recall": 0.90}
    passed, gates = evaluate_comparison_gates(champion, challenger)
    assert gates[1]["passed"] is True  # 0.76 >= 0.80 * 0.95


def test_precision_below_tolerance_fails():
    """Precision below 5% tolerance fails."""
    champion = {"f1_score": 0.85, "precision": 0.80, "recall": 0.90}
    challenger = {"f1_score": 0.85, "precision": 0.70, "recall": 0.90}
    passed, gates = evaluate_comparison_gates(champion, challenger)
    assert gates[1]["passed"] is False  # 0.70 < 0.80 * 0.95


def test_gate_results_structure():
    """Gate results contain expected fields."""
    champion = {"f1_score": 0.85, "precision": 0.80, "recall": 0.90}
    challenger = {"f1_score": 0.87, "precision": 0.82, "recall": 0.91}
    _, gates = evaluate_comparison_gates(champion, challenger)

    assert len(gates) == 3
    for gate in gates:
        assert "metric" in gate
        assert "champion" in gate
        assert "challenger" in gate
        assert "passed" in gate
        assert "rule" in gate
