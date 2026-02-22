"""Unit tests for TransactionBuilder extensions — explicit inputs + context extensions."""

from __future__ import annotations

import pytest

from ergo_agent.core.builder import (
    MIN_BOX_VALUE_NANOERG,
    TransactionBuilder,
    TransactionBuilderError,
)
from ergo_agent.core.models import Box, Token

# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

class MockNode:
    """Minimal mock Ergo node for testing."""

    def __init__(
        self,
        height: int = 100_000,
        unspent: list[Box] | None = None,
        boxes_by_id: dict[str, Box] | None = None,
    ) -> None:
        self._height = height
        self._unspent = unspent or []
        self._boxes_by_id = boxes_by_id or {}
        self.node_url = "https://mock.node"

    def get_height(self) -> int:
        return self._height

    def get_unspent_boxes(self, address: str, limit: int = 50) -> list[Box]:
        return self._unspent

    def get_box_by_id(self, box_id: str) -> Box | None:
        return self._boxes_by_id.get(box_id)


class MockWallet:
    """Minimal mock wallet for testing."""

    def __init__(self, address: str = "9mock_wallet_address") -> None:
        self.address = address


def _mock_builder(node: MockNode, wallet: MockWallet) -> TransactionBuilder:
    """Create a TransactionBuilder with _resolve_ergo_tree patched out."""
    builder = TransactionBuilder(node, wallet)
    # Patch out address validation — return a static ErgoTree for any address
    builder._resolve_ergo_tree = lambda addr: "0008cd0000000000000000000000000000000000000000000000000000000000000000"  # noqa: E501
    return builder


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_box(
    box_id: str = "abc123",
    value: int = 10_000_000_000,
    ergo_tree: str = "0008cd...",
    tokens: list[Token] | None = None,
    registers: dict | None = None,
) -> Box:
    return Box(
        box_id=box_id,
        value=value,
        ergo_tree=ergo_tree,
        creation_height=99_000,
        tokens=tokens or [],
        additional_registers=registers or {},
    )


def _make_wallet_box(value: int = 10_000_000_000) -> Box:
    return _make_box(box_id="wallet_box_1", value=value)


# ---------------------------------------------------------------------------
# Tests: with_input()
# ---------------------------------------------------------------------------

class TestWithInput:
    """Test explicit input box selection."""

    def test_with_input_box_object(self) -> None:
        """with_input(Box) stores the box and its ID."""
        pool_box = _make_box(box_id="pool_box_001", value=5_000_000_000)
        node = MockNode(unspent=[_make_wallet_box()])
        wallet = MockWallet()
        builder = TransactionBuilder(node, wallet)

        builder.with_input(pool_box)

        assert len(builder._explicit_inputs) == 1
        assert builder._explicit_inputs[0]["box_id"] == "pool_box_001"
        assert builder._explicit_inputs[0]["box"] is pool_box
        assert builder._explicit_inputs[0]["extension"] == {}

    def test_with_input_string_id(self) -> None:
        """with_input(str) stores the ID for later resolution."""
        node = MockNode(unspent=[_make_wallet_box()])
        wallet = MockWallet()
        builder = TransactionBuilder(node, wallet)

        builder.with_input("pool_box_002")

        assert len(builder._explicit_inputs) == 1
        assert builder._explicit_inputs[0]["box_id"] == "pool_box_002"
        assert builder._explicit_inputs[0]["box"] is None

    def test_with_input_context_extension(self) -> None:
        """with_input() attaches context extension variables."""
        pool_box = _make_box(box_id="pool_box_003")
        node = MockNode(unspent=[_make_wallet_box()])
        wallet = MockWallet()

        extension = {"0": "deadbeef", "1": "cafebabe"}
        builder = TransactionBuilder(node, wallet)
        builder.with_input(pool_box, extension=extension)

        assert builder._explicit_inputs[0]["extension"] == {
            "0": "deadbeef",
            "1": "cafebabe",
        }

    def test_with_input_fluent_api(self) -> None:
        """with_input() returns self for chaining."""
        pool_box = _make_box()
        node = MockNode(unspent=[_make_wallet_box()])
        wallet = MockWallet()
        builder = TransactionBuilder(node, wallet)

        result = builder.with_input(pool_box)
        assert result is builder


# ---------------------------------------------------------------------------
# Tests: build() with explicit inputs
# ---------------------------------------------------------------------------

class TestBuildWithExplicitInputs:
    """Test that build() correctly handles explicit inputs."""

    def test_explicit_input_in_transaction(self) -> None:
        """Explicit input appears in the built transaction."""
        pool_box = _make_box(box_id="pool_box_004", value=10_000_000_000)
        node = MockNode(unspent=[_make_wallet_box()])
        wallet = MockWallet()

        tx = (
            _mock_builder(node, wallet)
            .with_input(pool_box, extension={"0": "aabb"})
            .add_output_raw(
                ergo_tree="0008cd...",
                value_nanoerg=MIN_BOX_VALUE_NANOERG,
            )
            .build()
        )

        # First input should be the explicit one
        assert tx["inputs"][0]["boxId"] == "pool_box_004"
        assert tx["inputs"][0]["extension"] == {"0": "aabb"}

    def test_explicit_input_covers_outputs_no_wallet_needed(self) -> None:
        """If explicit inputs have enough ERG, no wallet UTXOs are selected."""
        big_box = _make_box(box_id="big_box", value=100_000_000_000)
        node = MockNode(unspent=[])  # No wallet UTXOs available
        wallet = MockWallet()

        tx = (
            _mock_builder(node, wallet)
            .with_input(big_box)
            .add_output_raw(
                ergo_tree="0008cd...",
                value_nanoerg=MIN_BOX_VALUE_NANOERG,
            )
            .build()
        )

        # Only the explicit input should be present
        assert len(tx["inputs"]) == 1
        assert tx["inputs"][0]["boxId"] == "big_box"

    def test_mixed_inputs_explicit_plus_wallet(self) -> None:
        """When explicit inputs aren't enough, wallet UTXOs are auto-selected."""
        small_pool = _make_box(box_id="small_pool", value=500_000)
        wallet_box = _make_wallet_box(value=10_000_000_000)
        node = MockNode(unspent=[wallet_box])
        wallet = MockWallet()

        tx = (
            _mock_builder(node, wallet)
            .with_input(small_pool)
            .add_output_raw(
                ergo_tree="0008cd...",
                value_nanoerg=MIN_BOX_VALUE_NANOERG,
            )
            .build()
        )

        # Both inputs should be present
        assert len(tx["inputs"]) == 2
        assert tx["inputs"][0]["boxId"] == "small_pool"
        assert tx["inputs"][1]["boxId"] == "wallet_box_1"

    def test_explicit_input_resolved_by_id(self) -> None:
        """with_input(str) resolves the box at build() time."""
        remote_box = _make_box(box_id="remote_001", value=10_000_000_000)
        node = MockNode(
            unspent=[_make_wallet_box()],
            boxes_by_id={"remote_001": remote_box},
        )
        wallet = MockWallet()

        tx = (
            _mock_builder(node, wallet)
            .with_input("remote_001")
            .add_output_raw(ergo_tree="0008cd...", value_nanoerg=MIN_BOX_VALUE_NANOERG)
            .build()
        )

        assert tx["inputs"][0]["boxId"] == "remote_001"

    def test_explicit_input_not_found_raises(self) -> None:
        """with_input(str) raises if the box can't be found."""
        node = MockNode(unspent=[_make_wallet_box()], boxes_by_id={})
        wallet = MockWallet()

        with pytest.raises(TransactionBuilderError, match="Box not found"):
            (
                _mock_builder(node, wallet)
                .with_input("nonexistent_box")
                .add_output_raw(ergo_tree="0008cd...", value_nanoerg=MIN_BOX_VALUE_NANOERG)
                .build()
            )

    def test_wallet_boxes_exclude_explicit(self) -> None:
        """Auto-selection excludes boxes already explicitly included."""
        shared_box = _make_box(box_id="shared", value=5_000_000_000)
        wallet_box = _make_box(box_id="wallet_only", value=5_000_000_000)
        node = MockNode(unspent=[shared_box, wallet_box])
        wallet = MockWallet()

        tx = (
            _mock_builder(node, wallet)
            .with_input(shared_box)
            .add_output_raw(ergo_tree="0008cd...", value_nanoerg=2_000_000_000)
            .build()
        )

        box_ids = [inp["boxId"] for inp in tx["inputs"]]
        assert "shared" in box_ids
        # shared should not appear twice
        assert box_ids.count("shared") == 1


# ---------------------------------------------------------------------------
# Tests: privacy module constants
# ---------------------------------------------------------------------------

class TestPrivacyConstants:
    """Test that privacy module constants are well-formed."""

    def test_nums_h_hex_length(self) -> None:
        """NUMS H should be a 33-byte compressed point (66 hex chars)."""
        from ergo_agent.core.privacy import NUMS_H_HEX
        assert len(NUMS_H_HEX) == 66
        assert NUMS_H_HEX.startswith("02") or NUMS_H_HEX.startswith("03")

    def test_pool_withdraw_script_contains_ring_proof(self) -> None:
        """Withdrawal script should contain the ring signature construction."""
        from ergo_agent.core.privacy import POOL_WITHDRAW_SCRIPT
        assert "atLeast(1," in POOL_WITHDRAW_SCRIPT
        assert "proveDlog" in POOL_WITHDRAW_SCRIPT
        assert "proveDHTuple" in POOL_WITHDRAW_SCRIPT
        assert "keyImage" in POOL_WITHDRAW_SCRIPT

    def test_pool_deposit_script_checks_key_append(self) -> None:
        """Deposit script should check that keys grow by one."""
        from ergo_agent.core.privacy import POOL_DEPOSIT_SCRIPT
        assert "keys.size + 1" in POOL_DEPOSIT_SCRIPT
        assert "spaceOk" in POOL_DEPOSIT_SCRIPT

    def test_note_contract_has_denomination_check(self) -> None:
        """Note contract should validate denominations."""
        from ergo_agent.core.privacy import NOTE_CONTRACT_SCRIPT
        assert "denomValid" in NOTE_CONTRACT_SCRIPT
        assert "proveDlog" in NOTE_CONTRACT_SCRIPT

    def test_nums_h_embedded_in_withdraw_script(self) -> None:
        """The NUMS H hex should appear in the withdrawal script."""
        from ergo_agent.core.privacy import NUMS_H_HEX, POOL_WITHDRAW_SCRIPT
        assert NUMS_H_HEX in POOL_WITHDRAW_SCRIPT

# ---------------------------------------------------------------------------
# Tests: Token Minting
# ---------------------------------------------------------------------------

class TestMintToken:
    """Test EIP-004 token minting transaction building."""

    def test_mint_token_creates_correct_output(self) -> None:
        """mint_token() should create an output with the correct assets and registers."""
        wallet_box = _make_wallet_box(value=10_000_000_000)
        node = MockNode(unspent=[wallet_box])
        wallet = MockWallet()
        builder = _mock_builder(node, wallet)

        tx = builder.mint_token(
            name="AgentTestToken",
            description="Testing mint token",
            amount=1_000_000,
            decimals=4,
        ).build()

        # The new token ID is the ID of the first input
        new_token_id = tx["inputs"][0]["boxId"]
        assert new_token_id == "wallet_box_1"

        # The output box (index 0) should hold the minted token
        mint_output = tx["outputs"][0]
        assert mint_output["assets"][0]["tokenId"] == new_token_id
        assert mint_output["assets"][0]["amount"] == 1_000_000

        # Check registers (R4, R5, R6)
        regs = mint_output["additionalRegisters"]

        # "AgentTestToken" -> bytes length 14 (hex 0e)
        assert regs["R4"] == "0e" + f"{14:02x}" + b"AgentTestToken".hex()
        # "Testing mint token" -> bytes length 18 (hex 12)
        assert regs["R5"] == "0e" + f"{18:02x}" + b"Testing mint token".hex()
        # Decimals "4" -> bytes length 1 (hex 01)
        assert regs["R6"] == "0e0134"
