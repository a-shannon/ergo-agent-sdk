"""
Advanced Security Tests for privacy pool Protocol (Post-Hardening)
===============================================================
Validates that the hardened SDK correctly BLOCKS all dangerous inputs
identified in the threat model, AND tests remaining attack vectors
(concurrency, liveness, privacy leakage).

Run with: python -m pytest tests/integration/test_privacy_advanced_security.py -v -m integration -s
"""

import os

import pytest

from ergo_agent.core.node import ErgoNode
from ergo_agent.core.wallet import Wallet
from ergo_agent.defi.privacy_pool import PoolValidationError, PrivacyPoolClient

pytestmark = pytest.mark.integration

NODE_URL = os.environ.get("ERGO_NODE_URL", "http://127.0.0.1:9052")
NODE_API_KEY = os.environ.get("ERGO_NODE_API_KEY", "hello")
EXPLORER_URL = os.environ.get("ERGO_EXPLORER_URL", "https://api-testnet.ergoplatform.com")

# secp256k1 generator point (compressed)
GROUP_GENERATOR = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

# The H constant from the contract (line 64)
H_CONSTANT = "02eab569326ae73e525b96643b2c31300e822007c91faf0c356226c4942ebe9eb2"


@pytest.fixture(scope="module")
def node():
    return ErgoNode(node_url=NODE_URL, explorer_url=EXPLORER_URL, api_key=NODE_API_KEY)


@pytest.fixture(scope="module")
def wallet(node):
    import httpx
    headers = {"api_key": NODE_API_KEY}
    r = httpx.get(f"{NODE_URL}/wallet/addresses", headers=headers, timeout=10.0)
    if r.status_code != 200:
        pytest.skip(f"Cannot get wallet addresses from node: {r.text}")
    addresses = r.json()
    addr = addresses[0] if isinstance(addresses, list) else addresses
    return Wallet.from_node_wallet(addr)


@pytest.fixture(scope="module")
def pool_client(node, wallet):
    return PrivacyPoolClient(node=node, wallet=wallet)


def get_pool(pool_client):
    """Helper to get first available pool."""
    pools = pool_client.get_active_pools(denomination=100)
    if not pools:
        pytest.skip("No active pools on testnet")
    return pools[0]


# =====================================================================
# 1. GAME THEORY -- SDK-Level Defenses
# =====================================================================

class TestRingPoisoningDefense:
    """
    Verify that the hardened SDK detects and warns about ring poisoning indicators.
    """

    def test_duplicate_key_blocked_at_sdk(self, pool_client):
        """
        [FIX 2.3] The hardened SDK must reject deposits with keys already in R4.
        """
        pool = get_pool(pool_client)
        pool_box = pool_client.node.get_box_by_id(pool["pool_id"])

        # Extract an existing key from R4 that is NOT a banned key
        r4 = pool_box.additional_registers.get("R4", "")
        if isinstance(r4, dict):
            r4 = r4.get("serializedValue", "")

        if r4.startswith("13") and len(r4) > 4:
            count = PrivacyPoolClient._read_vlq(r4[2:])
            vlq = PrivacyPoolClient._encode_vlq(count)
            data = r4[2 + len(vlq):]

            # Find a key in R4 that isn't a banned constant
            existing_key = None
            for i in range(count):
                start = i * 66
                end = start + 66
                if end <= len(data):
                    candidate = data[start:end].lower()
                    if candidate not in (GROUP_GENERATOR.lower(), H_CONSTANT.lower()):
                        existing_key = candidate
                        break

            if existing_key is None:
                pytest.skip("All keys in R4 are banned constants (pre-hardening deposits)")

            with pytest.raises(PoolValidationError, match="already exists"):
                pool_client.build_deposit_tx(pool["pool_id"], existing_key, 100)

            print(f"\n[FIX 2.3 VERIFIED] Duplicate key {existing_key[:16]}... correctly blocked")
        else:
            pytest.skip("R4 too short to extract keys")

    def test_pool_health_reports_effective_anonymity(self, pool_client):
        """
        [FIX 1.1] evaluate_pool_health() must report effective_anonymity
        separately from ring_size to detect ring poisoning.
        """
        pool = get_pool(pool_client)
        health = pool_client.evaluate_pool_health(pool["pool_id"])

        assert "effective_anonymity" in health
        assert "duplicate_keys" in health
        assert "risk_flags" in health
        assert "privacy_score" in health
        assert health["effective_anonymity"] <= health["ring_size"]

        print("\n[FIX 1.1 VERIFIED] Pool health report:")
        print(f"  Ring size: {health['ring_size']}")
        print(f"  Effective anonymity: {health['effective_anonymity']}")
        print(f"  Duplicate keys: {health['duplicate_keys']}")
        print(f"  Privacy score: {health['privacy_score']}")
        print(f"  Risk flags: {health['risk_flags']}")


class TestPoolCapacityDefense:
    """
    Verify that the SDK pre-checks pool capacity before building deposits.
    """

    def test_enhanced_pool_metadata(self, pool_client):
        """
        [FIX 1.2, 5.2] Pool scan should now include token_balance,
        withdrawable, slots_remaining, and is_full fields.
        """
        pool = get_pool(pool_client)

        assert "token_balance" in pool
        assert "withdrawable" in pool
        assert "slots_remaining" in pool
        assert "is_full" in pool
        assert "nullifiers" in pool

        print("\n[FIX 1.2+5.2 VERIFIED] Enhanced pool metadata:")
        print(f"  Token balance: {pool['token_balance']}")
        print(f"  Withdrawable: {pool['withdrawable']}")
        print(f"  Slots remaining: {pool['slots_remaining']}")
        print(f"  Is full: {pool['is_full']}")
        print(f"  Nullifiers: {pool['nullifiers']}")


# =====================================================================
# 2. CRYPTOGRAPHIC EDGE CASES -- SDK Blocks Dangerous Keys
# =====================================================================

class TestKeyImageDefenses:
    """
    Verify that the hardened SDK blocks all dangerous key image values.
    """

    def test_group_generator_blocked_as_key_image(self, pool_client):
        """
        [FIX 2.1] groupGenerator must be REJECTED as key image.
        Since build_withdrawal_tx now accepts secret_hex and computes key_image
        internally, we test the validation layer directly.
        """
        from ergo_agent.defi.privacy_pool import PoolValidationError

        with pytest.raises(PoolValidationError, match="group generator"):
            pool_client._validate_compressed_point(GROUP_GENERATOR, label="key image")

        print("\n[FIX 2.1 VERIFIED] groupGenerator correctly blocked as key image")

    def test_h_constant_blocked_as_key_image(self, pool_client):
        """
        [FIX 2.1b] H constant must be REJECTED as key image.
        """
        from ergo_agent.defi.privacy_pool import PoolValidationError

        with pytest.raises(PoolValidationError, match="H constant"):
            pool_client._validate_compressed_point(H_CONSTANT, label="key image")

        print("\n[FIX 2.1b VERIFIED] H constant correctly blocked as key image")

    def test_group_generator_blocked_as_deposit_key(self, pool_client):
        """
        [FIX 2.2] groupGenerator must be REJECTED as a stealth deposit key.
        """
        pool = get_pool(pool_client)

        with pytest.raises(PoolValidationError, match="group generator"):
            pool_client.build_deposit_tx(
                pool["pool_id"],
                GROUP_GENERATOR,
                100,
            )

        print("\n[FIX 2.2 VERIFIED] groupGenerator correctly blocked as deposit key")

    def test_h_constant_blocked_as_deposit_key(self, pool_client):
        """
        [FIX 2.2b] H constant must be REJECTED as a stealth deposit key.
        """
        pool = get_pool(pool_client)

        with pytest.raises(PoolValidationError, match="H constant"):
            pool_client.build_deposit_tx(
                pool["pool_id"],
                H_CONSTANT,
                100,
            )

        print("\n[FIX 2.2b VERIFIED] H constant correctly blocked as deposit key")

    def test_invalid_format_blocked(self, pool_client):
        """
        [FIX 2.2] Invalid key formats must be rejected.
        """
        pool = get_pool(pool_client)

        # Wrong prefix (04 = uncompressed)
        with pytest.raises(PoolValidationError, match="must start with 02 or 03"):
            pool_client.build_deposit_tx(pool["pool_id"], "04" + "ab" * 32, 100)

        # Too short
        with pytest.raises(PoolValidationError, match="66 hex chars"):
            pool_client.build_deposit_tx(pool["pool_id"], "02abcd", 100)

        # Not hex
        with pytest.raises(PoolValidationError, match="not valid hex"):
            pool_client.build_deposit_tx(pool["pool_id"], "02" + "zz" * 32, 100)

        print("\n[FIX 2.2c VERIFIED] Invalid key formats correctly rejected")


# =====================================================================
# 3. PRIVACY LEAKAGE -- Informational Tests
# =====================================================================

class TestPrivacyLeakage:
    """
    Tests documenting privacy leakage vectors.
    These are informational -- they confirm the leakage exists and
    document what mitigations the SDK provides.
    """

    def test_deposit_reveals_funding_source(self, pool_client, wallet):
        """
        [FINDING 3.2] Deposit tx reveals wallet address as funding source.
        The SDK cannot prevent this -- it requires protocol-level changes
        (relayer-funded deposits).
        """
        pool = get_pool(pool_client)
        # Use a safe, non-banned key
        safe_key = "02" + "d1" * 32
        pool_client.build_deposit_tx(pool["pool_id"], safe_key, 100)

        print(f"\n[FINDING 3.2] Deposit funded from: {wallet.address}")
        print("  -> Mitigation: Use fresh wallet per deposit or relay-funded deposits")

    def test_note_amount_deterministic(self, pool_client):
        """
        [FINDING 3.5] Note amount always equals the pool's exact denomination (v6: no fee deduction).
        """
        pool = get_pool(pool_client)
        if pool["depositors"] < 2:
            pytest.skip("Pool ring < 2")

        # Use a secret key instead of raw key image
        safe_secret = "d2" * 32
        builder = pool_client.build_withdrawal_tx(
            pool["pool_id"], pool_client.wallet.address, safe_secret,
        )

        # Get actual denomination from the pool box R6 (not the filter param)
        pool_box = pool_client.node.get_box_by_id(pool["pool_id"])
        r6 = pool_box.additional_registers.get("R6", "05c801")
        if isinstance(r6, dict):
            r6 = r6.get("serializedValue", "05c801")
        actual_denom = pool_client._decode_r6_denomination(r6)

        note_amount = builder._outputs[1]["tokens"][0]["amount"]
        # V6: note amount == exact denomination from R6 (no 99% fee)
        assert note_amount == actual_denom

        print(f"\n[FINDING 3.5] Note amount always {note_amount} tokens (deterministic)")

    def test_pool_balance_leaks_activity(self, pool_client, node):
        """
        [FINDING 3.1b] Token balance reveals deposit vs withdrawal ratio.
        evaluate_pool_health() now exposes this clearly.
        """
        pool = get_pool(pool_client)
        health = pool_client.evaluate_pool_health(pool["pool_id"])

        print("\n[FINDING 3.1b] Pool activity analysis via evaluate_pool_health():")
        print(f"  Ring size: {health['ring_size']}")
        print(f"  Token balance: {health['token_balance']}")
        print(f"  Denomination: {health['denomination']}")
        print(f"  Withdrawable: {health['withdrawable']}")
        print(f"  Nullifiers (past withdrawals): {health['nullifier_count']}")


# =====================================================================
# 4. CONCURRENCY / RACE CONDITION TESTS
# =====================================================================

class TestConcurrency:
    """
    Tests for UTXO contention and stale reference handling.
    """

    def test_competing_deposits_both_build(self, pool_client):
        """
        [FINDING 4.1] Two deposits against the same pool UTXO both build OK.
        Only one can succeed on-chain. The SDK should guide users to retry.
        """
        pool = get_pool(pool_client)

        key1 = "02" + "c1" * 32
        key2 = "03" + "c2" * 32

        builder1 = pool_client.build_deposit_tx(pool["pool_id"], key1, 100)
        builder2 = pool_client.build_deposit_tx(pool["pool_id"], key2, 100)

        assert len(builder1._outputs) >= 1
        assert len(builder2._outputs) >= 1

        print("\n[FINDING 4.1] Two competing deposits built against same UTXO")
        print("  -> Both build OK, conflict happens at submission only")
        print("  -> RECOMMENDATION: SDK should auto-retry with fresh UTXO on failure")

    def test_competing_deposit_and_withdrawal(self, pool_client):
        """
        [FINDING 4.1b] A deposit and withdrawal against the same pool
        UTXO cannot both succeed.
        """
        pool = get_pool(pool_client)
        if pool["depositors"] < 2:
            pytest.skip("Pool ring < 2")

        dep_key = "02" + "c3" * 32
        wit_secret = "c4" * 32  # V6: pass secret instead of key image

        builder_dep = pool_client.build_deposit_tx(pool["pool_id"], dep_key, 100)
        builder_wit = pool_client.build_withdrawal_tx(
            pool["pool_id"], pool_client.wallet.address, wit_secret,
        )

        assert len(builder_dep._outputs) >= 1
        assert len(builder_wit._outputs) >= 1

        print("\n[FINDING 4.1b] Competing deposit + withdrawal built against same UTXO")
        print("  -> Both build OK, only one can succeed on-chain")


# =====================================================================
# 5. LIVENESS TESTS
# =====================================================================

class TestLiveness:
    """
    Tests for protocol availability and degradation.
    """

    def test_pool_health_reports_liquidity(self, pool_client):
        """
        [FIX 5.2] Pool health must report actual withdrawable liquidity,
        not just ring size.
        """
        pool = get_pool(pool_client)
        health = pool_client.evaluate_pool_health(pool["pool_id"])

        assert health["withdrawable"] >= 0
        assert health["token_balance"] >= 0

        if health["withdrawable"] < health["ring_size"]:
            assert any("LOW_LIQUIDITY" in f for f in health["risk_flags"])
            print("\n[FIX 5.2 VERIFIED] Low liquidity detected and flagged")
        else:
            print(f"\n[FIX 5.2 VERIFIED] Liquidity adequate: "
                  f"{health['withdrawable']} withdrawals available")

    def test_self_serve_withdrawal_builds(self, pool_client, wallet):
        """
        [FINDING 5.1] Self-serve withdrawal (user pays gas) must still work.
        Relayer is needed for privacy, not for liveness.
        """
        pool = get_pool(pool_client)
        if pool["depositors"] < 2:
            pytest.skip("Pool ring < 2")

        safe_secret = "c5" * 32  # V6: pass secret instead of key image
        builder = pool_client.build_withdrawal_tx(
            pool["pool_id"], wallet.address, safe_secret,
        )
        assert len(builder._outputs) == 2

        print("\n[FINDING 5.1] Self-serve withdrawal builds OK")
        print("  -> User CAN withdraw without relayer (but privacy is reduced)")

    def test_safety_config_timing_fields(self):
        """
        [FIX 3.1] Safety config must include withdrawal delay recommendation.
        """
        from ergo_agent.tools.safety import SafetyConfig

        cfg = SafetyConfig()
        assert hasattr(cfg, "min_withdrawal_delay_blocks")
        assert cfg.min_withdrawal_delay_blocks == 100
        assert hasattr(cfg, "min_pool_ring_size")
        assert cfg.min_pool_ring_size == 4

        print("\n[FIX 3.1 VERIFIED] Safety timing fields present:")
        print(f"  min_withdrawal_delay_blocks: {cfg.min_withdrawal_delay_blocks}")
        print(f"  min_pool_ring_size: {cfg.min_pool_ring_size}")
