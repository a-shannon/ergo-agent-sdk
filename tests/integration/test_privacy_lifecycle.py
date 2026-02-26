"""
Integration tests for the privacy pool v7 privacy pool lifecycle.
Requires a running Ergo testnet node at 127.0.0.1:9052 and a funded wallet.

Tests exercise the FULL privacy pool v7 intent-based pipeline:
  1. Pool status & anonymity analysis
  2. Deposit intent creation (PrivacyPoolClient)
  3. Withdrawal proof construction (DHTuple ring sig)
  4. View key export & verification
  5. Anonymity set assessment

Run with: python -m pytest tests/integration/test_privacy_lifecycle.py -v -m integration
"""

import os

import pytest

from ergo_agent.core.node import ErgoNode
from ergo_agent.core.privacy import (
    AnonymityAssessment,
    analyze_anonymity_set,
    check_withdrawal_safety,
)
from ergo_agent.core.wallet import Wallet
from ergo_agent.defi.privacy_client import DepositSecret, PrivacyPoolClient
from ergo_agent.tools.safety import SafetyConfig
from ergo_agent.tools.toolkit import ErgoToolkit

pytestmark = pytest.mark.integration

# Testnet node configuration
NODE_URL = os.environ.get("ERGO_NODE_URL", "http://127.0.0.1:9052")
NODE_API_KEY = os.environ.get("ERGO_NODE_API_KEY", "hello")
EXPLORER_URL = os.environ.get("ERGO_EXPLORER_URL", "https://api-testnet.ergoplatform.com")

# Pool box IDs from deployments_v7.json (updated by deploy scripts)
POOL_1_ERG = os.environ.get("POOL_1_ERG_BOX_ID", "")
POOL_10_ERG = os.environ.get("POOL_10_ERG_BOX_ID", "")
POOL_100_ERG = os.environ.get("POOL_100_ERG_BOX_ID", "")


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
def privacy_client(node):
    return PrivacyPoolClient(node=node)


@pytest.fixture(scope="module")
def toolkit(node, wallet):
    safety = SafetyConfig(dry_run=True, max_erg_per_tx=1.0, max_erg_per_day=5.0)
    return ErgoToolkit(node=node, wallet=wallet, safety=safety)


def _get_pool_box_id():
    """Return the first available pool box ID for testing."""
    for box_id in [POOL_1_ERG, POOL_10_ERG, POOL_100_ERG]:
        if box_id:
            return box_id
    # Try loading from deployments_v7.json
    import json
    deploy_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "deployments_v7.json"
    )
    if os.path.exists(deploy_path):
        data = json.load(open(deploy_path))
        pools = data.get("pools", [])
        if pools:
            return pools[0].get("boxId", "")
    return ""


# --- Pool Status & Anonymity ---

class TestPoolStatus:
    """Test pool status queries and anonymity analysis."""

    def test_pool_status_returns_deposit_count(self, privacy_client):
        """privacy_pool_get_status should return deposit count and privacy score."""
        box_id = _get_pool_box_id()
        if not box_id:
            pytest.skip("No pool box ID configured")

        status = privacy_client.get_pool_status(box_id)
        assert "deposit_count" in status
        assert "denomination" in status
        assert "privacy_score" in status
        assert "risk_level" in status
        assert isinstance(status["deposit_count"], int)
        print(f"\n[+] Pool {box_id[:16]}... deposit_count={status['deposit_count']}, "
              f"privacy_score={status['privacy_score']}/100 ({status['risk_level']})")

    def test_anonymity_assessment_structure(self):
        """Anonymity analysis should return a well-formed AnonymityAssessment."""
        box_id = _get_pool_box_id()
        if not box_id:
            pytest.skip("No pool box ID configured")

        assessment = analyze_anonymity_set(NODE_URL, box_id, NODE_API_KEY)
        assert isinstance(assessment, AnonymityAssessment)
        assert 0 <= assessment.privacy_score <= 100
        assert assessment.risk_level in {"CRITICAL", "POOR", "MODERATE", "GOOD", "EXCELLENT"}
        assert isinstance(assessment.warnings, list)
        print(f"\n[+] Anonymity: score={assessment.privacy_score}/100, "
              f"risk={assessment.risk_level}, deposits={assessment.deposit_count}")

    def test_withdrawal_safety_check(self):
        """check_withdrawal_safety should return (bool, assessment) tuple."""
        box_id = _get_pool_box_id()
        if not box_id:
            pytest.skip("No pool box ID configured")

        is_safe, assessment = check_withdrawal_safety(NODE_URL, box_id, NODE_API_KEY)
        assert isinstance(is_safe, bool)
        assert isinstance(assessment, AnonymityAssessment)
        assert is_safe == assessment.is_safe_to_withdraw
        print(f"\n[+] Withdrawal safety: {'SAFE' if is_safe else 'UNSAFE'} "
              f"(score={assessment.privacy_score})")


# --- Deposit Path ---

class TestDeposit:
    """Test deposit intent creation."""

    def test_create_deposit_returns_secret(self, privacy_client):
        """create_deposit should return a valid DepositSecret."""
        secret = privacy_client.create_deposit("1_erg")
        assert isinstance(secret, DepositSecret)
        assert secret.blinding_factor > 0
        assert len(secret.commitment_hex) == 66  # 33 bytes compressed
        assert secret.tier == "1_erg"
        print(f"\n[+] Deposit secret generated: C={secret.commitment_hex[:16]}...")

    def test_create_deposit_invalid_tier_raises(self, privacy_client):
        """Invalid tier should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown tier"):
            privacy_client.create_deposit("999_erg")

    def test_deposit_intent_box_spec(self, privacy_client):
        """build_deposit_intent should return valid box spec."""
        secret = privacy_client.create_deposit("10_erg")
        ergo_tree = "0008cd" + "02" + "ab" * 32  # Synthetic depositor tree
        intent = privacy_client.build_deposit_intent(secret, ergo_tree)

        assert intent["registers"]["R4"].startswith("07")  # GroupElement type
        assert intent["meta"]["type"] == "IntentToDeposit"
        assert intent["meta"]["tier"] == "10_erg"
        print(f"\n[+] Intent box: value={intent['value']}, R4={intent['registers']['R4'][:20]}...")

    def test_toolkit_deposit_dry_run(self, toolkit):
        """toolkit.privacy_pool_deposit in dry_run mode should return status=dry_run."""
        result = toolkit.privacy_pool_deposit(tier="1_erg")
        assert result["status"] == "dry_run"
        assert "commitment" in result
        print(f"\n[+] Dry run deposit: commitment={result['commitment'][:16]}...")


# --- Withdrawal Path ---

class TestWithdrawal:
    """Test withdrawal proof construction."""

    def test_build_withdrawal_proof(self, privacy_client):
        """build_withdrawal_proof should return a valid WithdrawalProof."""
        # Create a deposit first
        secret = privacy_client.create_deposit("1_erg")

        # Generate some synthetic decoy commitments
        decoys = []
        for _ in range(4):
            decoy_secret = privacy_client.create_deposit("1_erg")
            decoys.append(decoy_secret.commitment_hex)

        payout_tree = "0008cd" + "02" + "cc" * 32  # Synthetic recipient

        proof = privacy_client.build_withdrawal_proof(secret, decoys, payout_tree)
        assert len(proof.nullifier_hex) == 66
        assert len(proof.secondary_gen_hex) == 66
        assert proof.ring_size >= 2
        assert proof.payout_ergo_tree == payout_tree
        print(f"\n[+] Withdrawal proof: nullifier={proof.nullifier_hex[:16]}..., "
              f"ring_size={proof.ring_size}")

    def test_build_withdrawal_intent(self, privacy_client):
        """build_withdrawal_intent should return valid box spec."""
        secret = privacy_client.create_deposit("1_erg")
        decoys = [privacy_client.create_deposit("1_erg").commitment_hex for _ in range(3)]
        payout = "0008cd" + "02" + "dd" * 32

        proof = privacy_client.build_withdrawal_proof(secret, decoys, payout)
        intent = privacy_client.build_withdrawal_intent(proof)

        assert intent["registers"]["R4"].startswith("07")  # Nullifier
        assert intent["registers"]["R5"].startswith("07")  # Secondary gen U
        assert intent["meta"]["type"] == "IntentToWithdraw"
        print(f"\n[+] Withdrawal intent: nullifier R4={intent['registers']['R4'][:20]}...")


# --- View Key (Compliance) ---

class TestViewKey:
    """Test view key export and verification."""

    def test_export_view_key(self, privacy_client):
        """View key export should include blinding factor and commitment."""
        secret = privacy_client.create_deposit("10_erg")
        view_key = PrivacyPoolClient.export_view_key(secret)

        assert "blinding_factor_hex" in view_key
        assert "commitment" in view_key
        assert view_key["commitment"] == secret.commitment_hex
        print(f"\n[+] View key exported for commitment {secret.commitment_hex[:16]}...")

    def test_verify_view_key(self, privacy_client):
        """View key verification should pass for valid disclosure."""
        secret = privacy_client.create_deposit("1_erg")
        is_valid = PrivacyPoolClient.verify_view_key(
            secret.commitment_hex, secret.blinding_factor, secret.amount
        )
        assert is_valid is True
        print("\n[+] View key verification: PASSED")

    def test_verify_view_key_wrong_amount_fails(self, privacy_client):
        """View key with wrong amount should fail verification."""
        secret = privacy_client.create_deposit("1_erg")
        is_valid = PrivacyPoolClient.verify_view_key(
            secret.commitment_hex, secret.blinding_factor, secret.amount + 1
        )
        assert is_valid is False
        print("\n[+] Wrong-amount view key: correctly rejected")


# --- Bearer Note Transfer ---

class TestBearerNote:
    """Test bearer note export/import."""

    def test_bearer_note_roundtrip(self, privacy_client):
        """Export → import roundtrip should produce identical DepositSecret."""
        secret = privacy_client.create_deposit("100_erg")
        note = PrivacyPoolClient.export_bearer_note(secret)

        assert note["type"] == "privacy_bearer_note"
        assert note["version"] == 1

        imported = PrivacyPoolClient.import_bearer_note(note)
        assert imported.blinding_factor == secret.blinding_factor
        assert imported.commitment_hex == secret.commitment_hex
        assert imported.amount == secret.amount
        assert imported.tier == secret.tier
        print("\n[+] Bearer note roundtrip: OK")

    def test_bearer_note_tampered_fails(self, privacy_client):
        """Tampered bearer note should raise ValueError."""
        secret = privacy_client.create_deposit("1_erg")
        note = PrivacyPoolClient.export_bearer_note(secret)
        note["amount"] = note["amount"] + 1  # Tamper

        with pytest.raises(ValueError, match="integrity check failed"):
            PrivacyPoolClient.import_bearer_note(note)
        print("\n[+] Tampered bearer note: correctly rejected")
