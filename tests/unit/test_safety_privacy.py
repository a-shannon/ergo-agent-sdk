"""
Unit tests for Safety layer extensions relevant to privacy pool operations.
Verifies testnet P2PK whitelisting, privacy pool protocol whitelisting,
dry-run mode, and rate limiting under privacy pool workloads.
"""

import pytest

from ergo_agent.tools.safety import SafetyConfig, SafetyViolation


def test_testnet_p2pk_whitelisted():
    """Testnet P2PK addresses (prefix '3') should be allowed."""
    cfg = SafetyConfig(allowed_contracts=["spectrum"])
    # Should NOT raise — testnet addresses start with "3"
    cfg.validate_send(amount_erg=1.0, destination="3Wywat3mESLP1q5MLZa9ybB3z8yv3KSK27jmdg9gyYjjRk4PKKvy")


def test_mainnet_p2pk_whitelisted():
    """Mainnet P2PK addresses (prefix '9') should be allowed."""
    cfg = SafetyConfig(allowed_contracts=["spectrum"])
    cfg.validate_send(amount_erg=1.0, destination="9fXWbPxxxExampleMainnetAddress")


def test_privacy_pool_protocol_in_default_whitelist():
    """The default SafetyConfig should include 'privacy_pool' in allowed_contracts."""
    cfg = SafetyConfig()
    assert "privacy_pool" in cfg.allowed_contracts
    # Should not raise when sending to "privacy_pool" destination
    cfg.validate_send(amount_erg=0.05, destination="privacy_pool")


def test_unknown_destination_blocked():
    """Non-P2PK, non-whitelisted destinations should be rejected."""
    cfg = SafetyConfig(allowed_contracts=["spectrum", "privacy_pool"])
    with pytest.raises(SafetyViolation, match="not in the allowed"):
        cfg.validate_send(amount_erg=1.0, destination="bc1qxy2kgdygjrsq...")


def test_dry_run_prevents_submission():
    """In dry_run mode, the toolkit should return dry_run status."""
    from unittest.mock import MagicMock
    from ergo_agent.tools.toolkit import ErgoToolkit

    node = MagicMock()
    wallet = MagicMock()
    wallet.address = "3WxTestAddress"
    wallet.read_only = False

    cfg = SafetyConfig(dry_run=True)
    tk = ErgoToolkit(node=node, wallet=wallet, safety=cfg)

    result = tk.deposit_to_privacy_pool(pool_id="test_pool", denomination=100)
    assert result["status"] == "dry_run"


def test_rate_limit_fires_on_rapid_privacy_ops():
    """Rapid privacy pool operations should trigger rate limiting."""
    cfg = SafetyConfig(rate_limit_per_hour=5)

    for _ in range(5):
        cfg.validate_rate_limit()
        cfg.record_action(erg_spent=0.05)

    with pytest.raises(SafetyViolation, match="Rate limit"):
        cfg.validate_rate_limit()
