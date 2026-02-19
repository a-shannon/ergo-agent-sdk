"""
Unit tests for the Safety layer.
These run without network access (pure Python logic).
"""

import pytest

from ergo_agent.tools.safety import SafetyConfig, SafetyViolation


def test_per_tx_limit():
    cfg = SafetyConfig(max_erg_per_tx=5.0)
    with pytest.raises(SafetyViolation, match="per-tx limit"):
        cfg.validate_send(amount_erg=10.0, destination="9fXWbP...")


def test_per_tx_passes_below_limit():
    cfg = SafetyConfig(max_erg_per_tx=10.0)
    cfg.validate_send(amount_erg=5.0, destination="9fXWbP...")  # should not raise


def test_daily_limit():
    cfg = SafetyConfig(max_erg_per_tx=100.0, max_erg_per_day=20.0)
    cfg.record_action(erg_spent=15.0)
    # 15 already spent, trying to spend 10 more → exceeds 20 daily
    with pytest.raises(SafetyViolation, match="daily limit"):
        cfg.validate_send(amount_erg=10.0, destination="9fXWbP...")


def test_daily_limit_passes_within_budget():
    cfg = SafetyConfig(max_erg_per_tx=100.0, max_erg_per_day=20.0)
    cfg.record_action(erg_spent=5.0)
    cfg.validate_send(amount_erg=10.0, destination="9fXWbP...")  # 15 total — ok


def test_contract_whitelist_blocks():
    cfg = SafetyConfig(allowed_contracts=["spectrum"])
    with pytest.raises(SafetyViolation, match="not in the allowed"):
        cfg.validate_send(amount_erg=1.0, destination="some_unknown_contract")


def test_contract_whitelist_allows_p2pk():
    cfg = SafetyConfig(allowed_contracts=["spectrum"])
    # P2PK addresses starting with "9" are always allowed (sending to a person's wallet)
    cfg.validate_send(amount_erg=1.0, destination="9fXWbPxxxExampleAddress")


def test_contract_whitelist_allows_named_protocol():
    cfg = SafetyConfig(allowed_contracts=["spectrum", "sigmausd"])
    cfg.validate_send(amount_erg=1.0, destination="spectrum")


def test_rate_limit():
    cfg = SafetyConfig(rate_limit_per_hour=3)
    for _ in range(3):
        cfg.validate_rate_limit()
        cfg.record_action()
    with pytest.raises(SafetyViolation, match="Rate limit"):
        cfg.validate_rate_limit()


def test_get_status_returns_correct_structure():
    cfg = SafetyConfig(max_erg_per_day=50.0, rate_limit_per_hour=10)
    cfg.record_action(erg_spent=5.0)
    cfg.record_action(erg_spent=3.0)
    status = cfg.get_status()
    assert status["daily_erg_spent"] == pytest.approx(8.0)
    assert status["daily_erg_remaining"] == pytest.approx(42.0)
    assert status["actions_last_hour"] == 2
    assert status["dry_run"] is False


def test_dry_run_field():
    cfg = SafetyConfig(dry_run=True)
    assert cfg.get_status()["dry_run"] is True
