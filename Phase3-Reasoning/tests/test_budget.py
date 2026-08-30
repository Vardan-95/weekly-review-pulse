import pytest

from pulse.budget import BudgetGuard


def test_has_budget_true_initially():
    guard = BudgetGuard(max_tokens=1000, max_cost_usd=1.0)
    assert guard.has_budget() is True


def test_record_accumulates():
    guard = BudgetGuard(max_tokens=1000, max_cost_usd=1.0)
    guard.record(tokens=100, cost_usd=0.1)
    guard.record(tokens=50, cost_usd=0.05)
    assert guard.tokens_used == 150
    assert guard.cost_usd == pytest.approx(0.15)


def test_has_budget_false_when_tokens_exceeded():
    guard = BudgetGuard(max_tokens=100, max_cost_usd=10.0)
    guard.record(tokens=150, cost_usd=0.01)
    assert guard.has_budget() is False


def test_has_budget_false_when_cost_exceeded():
    guard = BudgetGuard(max_tokens=10000, max_cost_usd=0.1)
    guard.record(tokens=10, cost_usd=0.2)
    assert guard.has_budget() is False


def test_mark_truncated():
    guard = BudgetGuard(max_tokens=100, max_cost_usd=1.0)
    assert guard.truncated is False
    guard.mark_truncated()
    assert guard.truncated is True
