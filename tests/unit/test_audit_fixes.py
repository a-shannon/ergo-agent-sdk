"""
Unit tests for new audit-identified features:
- select_best_pool()
- safety.py Phase V privacy mitigations
- _decode_r7_max_ring edge cases
"""

from unittest.mock import MagicMock, patch

from ergo_agent.defi.privacy_pool import PrivacyPoolClient
from ergo_agent.tools.safety import SafetyConfig

# --- select_best_pool tests ---

class TestSelectBestPool:
    def _make_client(self):
        client = PrivacyPoolClient.__new__(PrivacyPoolClient)
        client.node = MagicMock()
        client.wallet = MagicMock()
        client.MOCK_CASH_V3_POOL_ERGO_TREE = "0008cd02deadbeef"
        client.pool_address = "3WxPoolAddress"
        return client

    def test_returns_none_when_no_pools(self):
        client = self._make_client()
        with patch.object(client, "get_active_pools", return_value=[]):
            result = client.select_best_pool(denomination=100)
            assert result is None

    def test_returns_none_when_all_full(self):
        client = self._make_client()
        pools = [
            {"pool_id": "a", "depositors": 16, "slots_remaining": 0, "is_full": True},
            {"pool_id": "b", "depositors": 16, "slots_remaining": 0, "is_full": True},
        ]
        with patch.object(client, "get_active_pools", return_value=pools):
            result = client.select_best_pool(denomination=100)
            assert result is None

    def test_selects_highest_anonymity(self):
        client = self._make_client()
        pools = [
            {"pool_id": "small", "depositors": 2, "slots_remaining": 14, "is_full": False},
            {"pool_id": "big", "depositors": 8, "slots_remaining": 8, "is_full": False},
            {"pool_id": "mid", "depositors": 5, "slots_remaining": 11, "is_full": False},
        ]
        with patch.object(client, "get_active_pools", return_value=pools):
            result = client.select_best_pool(denomination=100)
            assert result["pool_id"] == "big"

    def test_tiebreaker_on_slots_remaining(self):
        client = self._make_client()
        pools = [
            {"pool_id": "a", "depositors": 4, "slots_remaining": 10, "is_full": False},
            {"pool_id": "b", "depositors": 4, "slots_remaining": 12, "is_full": False},
        ]
        with patch.object(client, "get_active_pools", return_value=pools):
            result = client.select_best_pool(denomination=100)
            assert result["pool_id"] == "b"


# --- Safety Phase V tests ---

class TestSafetyPrivacyMitigations:
    def test_withdrawal_delay_safe(self):
        config = SafetyConfig(min_withdrawal_delay_blocks=100)
        result = config.recommend_withdrawal_delay(deposit_height=1000, current_height=1200)
        assert result["safe"] is True
        assert result["blocks_remaining"] == 0

    def test_withdrawal_delay_too_soon(self):
        config = SafetyConfig(min_withdrawal_delay_blocks=100)
        result = config.recommend_withdrawal_delay(deposit_height=1000, current_height=1050)
        assert result["safe"] is False
        assert result["blocks_remaining"] == 50

    def test_deterministic_change_rounds_down(self):
        # input=100M, output=50M, fee=1M -> raw_change=49M = 49_000_000
        # Rounded to nearest 10M = 40_000_000
        result = SafetyConfig.compute_deterministic_change(100_000_000, 50_000_000, 1_000_000)
        assert result == 40_000_000

    def test_deterministic_change_minimum(self):
        # Very small change should return minimum box value
        result = SafetyConfig.compute_deterministic_change(2_000_000, 1_000_000, 500_000)
        assert result == 1_000_000

    def test_deterministic_change_zero_or_negative(self):
        result = SafetyConfig.compute_deterministic_change(1_000_000, 1_000_000, 0)
        assert result == 0

    def test_randomize_withdrawal_timing_range(self):
        for _ in range(10):
            delay = SafetyConfig.randomize_withdrawal_timing()
            assert 30.0 <= delay <= 300.0

    def test_validate_privacy_ok(self):
        config = SafetyConfig(min_pool_ring_size=4, min_withdrawal_delay_blocks=100)
        warnings = config.validate_privacy_withdrawal(
            pool_ring_size=8, deposit_height=1000, current_height=1200
        )
        assert warnings == []

    def test_validate_privacy_low_ring(self):
        config = SafetyConfig(min_pool_ring_size=4)
        warnings = config.validate_privacy_withdrawal(
            pool_ring_size=2, deposit_height=None, current_height=1200
        )
        assert len(warnings) == 1
        assert "LOW_ANONYMITY" in warnings[0]

    def test_validate_privacy_too_soon(self):
        config = SafetyConfig(min_withdrawal_delay_blocks=100)
        warnings = config.validate_privacy_withdrawal(
            pool_ring_size=8, deposit_height=1150, current_height=1200
        )
        assert len(warnings) == 1
        assert "TOO_SOON" in warnings[0]

    def test_validate_privacy_both_flags(self):
        config = SafetyConfig(min_pool_ring_size=4, min_withdrawal_delay_blocks=100)
        warnings = config.validate_privacy_withdrawal(
            pool_ring_size=2, deposit_height=1150, current_height=1200
        )
        assert len(warnings) == 2


# --- R7 decoder edge cases ---

class TestR7Decoder:
    def _make_client(self):
        client = PrivacyPoolClient.__new__(PrivacyPoolClient)
        client.node = MagicMock()
        client.wallet = MagicMock()
        client.MOCK_CASH_V3_POOL_ERGO_TREE = ""
        client.pool_address = ""
        return client

    def test_empty_string_defaults(self):
        client = self._make_client()
        assert client._decode_r7_max_ring("") == 16

    def test_none_defaults(self):
        client = self._make_client()
        assert client._decode_r7_max_ring(None) == 16

    def test_short_hex_defaults(self):
        client = self._make_client()
        assert client._decode_r7_max_ring("04") == 16

    def test_standard_r7_16(self):
        client = self._make_client()
        # ZigZag: 16 -> 32 (0x20), with Int prefix "04" -> "0420"
        assert client._decode_r7_max_ring("0420") == 16

    def test_standard_r7_32(self):
        client = self._make_client()
        # ZigZag: 32 -> 64 (0x40), with Int prefix "04" -> "0440"
        assert client._decode_r7_max_ring("0440") == 32
