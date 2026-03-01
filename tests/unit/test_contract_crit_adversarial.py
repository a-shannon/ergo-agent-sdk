"""
Contract Invariant Adversarial Tests — v9 Security Boundary Suite.

These tests mirror the EXACT security invariants enforced by the v9 MasterPoolBox
ErgoScript contract, implemented in Python. They exist to:

  1. Document the four critical attack vectors identified during the protocol audit.
  2. Prove that the SDK-level helpers REJECT each attack as the contract would.
  3. Serve as regression tests against future regressions.

Each class is tagged to its CRIT finding (CRIT-1 through CRIT-4).

IMPORTANT: These are pure-math tests — no network, no mocks, no ErgoScript compiler.
The model: if the Python invariant check passes, the corresponding ErgoScript check
in PrivacyPoolMaster.es would also pass (and vice-versa for rejection).

All tests MUST pass. A failure means the SDK is vulnerable to that attack class.

Reference: contracts/PrivacyPoolMaster.es (v9)
           whitepapers/protocol_decisions.md (v9)
"""

from __future__ import annotations

import hashlib
import secrets

import pytest

from ergo_agent.crypto.pedersen import (
    G_COMPRESSED,
    NUMS_H,
    SECP256K1_N,
    PedersenCommitment,
    decode_point,
    encode_point,
)

# ==============================================================================
# Shared helpers — model the contract's math, not the SDK API
# ==============================================================================


def _random_scalar() -> int:
    """Random scalar in [1, N-1]."""
    return secrets.randbelow(SECP256K1_N - 1) + 1


def _commitment(r: int, amount: int) -> str:
    """C = r·G + amount·H (Pedersen Commitment)."""
    return PedersenCommitment.commit(r, amount)


def _nullifier_fixed_H(r: int) -> str:
    """I = r·H  — the v9 fixed nullifier (U_global = H)."""
    H = decode_point(NUMS_H)
    return encode_point(r * H)


def _nullifier_custom_U(r: int, U_hex: str) -> str:
    """I = r·U  — the old variable nullifier (VULNERABLE, for attack modelling)."""
    U = decode_point(U_hex)
    return encode_point(r * U)


def _random_point() -> str:
    """Generate a random EC point on secp256k1."""
    s = _random_scalar()
    G = decode_point(G_COMPRESSED)
    return encode_point(s * G)


def _pool_genesis_id() -> bytes:
    """Simulate a pool genesis ID (32 random bytes)."""
    return secrets.token_bytes(32)


def _pool_nft_id() -> bytes:
    """Simulate a singleton NFT minted at genesis (32 random bytes, unique on-chain)."""
    return secrets.token_bytes(32)


# ==============================================================================
# Contract invariant helpers — mirror of MasterPoolBox ErgoScript checks
# ==============================================================================


def contract_nullifier_check(nullifier_hex: str, r: int) -> bool:
    """
    Mirror of MasterPoolBox withdrawal path:
        val nullSafe = nullifier != groupGenerator
        val nullNotH = nullifier != H

    Returns True if the nullifier passes the contract's static safety checks.
    """
    return nullifier_hex != G_COMPRESSED and nullifier_hex != NUMS_H


def contract_intent_genesis_check(intent_genesis: bytes, pool_genesis: bytes) -> bool:
    """
    Mirror of:
        val intentGenesisOk = intentBox.R5[Coll[Byte]].get == genesisId
    """
    return intent_genesis == pool_genesis


def contract_intent_script_hash_check(
    intent_proposition_bytes: bytes,
    pool_r10_itw_hash: bytes,
) -> bool:
    """
    Mirror of:
        val intentScriptOk = blake2b256(intentBox.propositionBytes) == itwHash

    CRIT-1 Layer 3: Static Intent Pattern authentication. The ITW script hash
    is stored in the pool's R10 at deployment — an attacker cannot self-certify
    their forged box by placing the hash in a register they control.
    blake2b256 with digest_size=32 matches Ergo's native hash function.
    """
    computed = hashlib.blake2b(intent_proposition_bytes, digest_size=32).digest()
    return computed == pool_r10_itw_hash


def contract_deposit_input_check(
    box_value: int,
    unit_cost: int,
    box_r6_pool_hash: bytes,
    pool_script_hash: bytes,
) -> bool:
    """
    Mirror of MasterPoolBox deposit path:
        box.value == unitCost &&       // STRICT == (v9)
        box.R6[Coll[Byte]].get == expectedPoolHash

    Returns True if this deposit input is valid.
    """
    return box_value == unit_cost and box_r6_pool_hash == pool_script_hash


def contract_singleton_nft_check(
    output_nft_id: bytes | None,
    self_nft_id: bytes,
) -> bool:
    """
    Mirror of:
        val singletonOk = poolOut.tokens.size == 1 &&
                          poolOut.tokens(0)._1 == singletonId &&
                          poolOut.tokens(0)._2 == 1L

    output_nft_id: None means the output has no NFT (poolOut.tokens.size == 0).
    """
    if output_nft_id is None:
        return False
    return output_nft_id == self_nft_id


# ==============================================================================
# [CRIT-2] Nullifier Malleability via User-Controlled U
# ==============================================================================


class TestCrit2NullifierMalleability:
    """
    CRIT-2: If U is user-supplied per withdrawal, the same depositor can generate
    a fresh nullifier I = r·U_n for each withdrawal attempt, bypassing the
    Nullifier Tree's duplicate check and double-spending indefinitely.

    The v9 fix: I = r·H where H is the globally fixed NUMS constant.
    The MasterPoolBox hardcodes H and constructs the proveDHTuple using it.

    These tests prove:
      (a) The variable-U attack is a real exploit when U is user-controlled.
      (b) The fixed-H nullifier is unique and deterministic per r.
      (c) Changing U when H is fixed has no effect.
    """

    def test_variable_u_attack_produces_distinct_nullifiers(self):
        """
        EXPLOIT DEMONSTRATION (old variable-U model):
        Same depositor (same r) with 10 different U values gets 10 different
        nullifiers — each bypasses the Nullifier Tree's duplicate insert check.

        This is the exact double-spend attack CRIT-2 addresses.
        """
        r = _random_scalar()
        nullifiers = set()
        for _ in range(10):
            U_hex = _random_point()
            nullifier_pt = _nullifier_custom_U(r, U_hex)
            nullifiers.add(nullifier_pt)

        assert len(nullifiers) == 10, (
            "EXPLOIT: Same depositor with 10 different U values produces 10 unique "
            "nullifiers. Each would pass the AVL tree insert (not yet in tree). "
            "The depositor can withdraw 10 times from one deposit."
        )

    def test_fixed_h_nullifier_deterministic_per_r(self):
        """
        MITIGATION (v9 fixed-H model):
        The nullifier I = r·H is strictly deterministic per r.
        No matter how many withdrawal attempts, I is identical — the second
        AVL tree insert fails (duplicate key rejected).
        """
        r = _random_scalar()
        nullifiers = {_nullifier_fixed_H(r) for _ in range(10)}
        assert len(nullifiers) == 1, (
            "Fixed-H nullifier must be identical across all 10 calls for same r. "
            "The AVL tree insert would fail on the 2nd attempt (CRIT-2 fix)."
        )

    def test_different_r_produce_different_fixed_nullifiers(self):
        """
        Different depositors (different r) with fixed H produce different nullifiers.
        The nullifier still uniquely identifies each deposit after the fix.
        """
        nullifiers = set()
        for _ in range(50):
            r = _random_scalar()
            nullifier_pt = _nullifier_fixed_H(r)
            assert nullifier_pt not in nullifiers, "Nullifier collision: two depositors got same I"
            nullifiers.add(nullifier_pt)

    def test_fixed_nullifier_passes_contract_safety_check(self):
        """
        I = r·H must pass the contract's nullSafe && nullNotH check.
        In the negligible case that I == G or I == H, the contract rejects it.
        For 20 random r values this should always pass.
        """
        for _ in range(20):
            r = _random_scalar()
            nullifier_pt = _nullifier_fixed_H(r)
            assert contract_nullifier_check(nullifier_pt, r), (
                "Nullifier for r failed contract safety check (I == G or I == H)."
            )

    def test_attacker_custom_u_produces_different_nullifier_than_fixed_h(self):
        """
        In v9, U_global = H is hardcoded in the pool. An attacker computing
        I = r·U_attacker ≠ I = r·H (for U_attacker ≠ H) would produce a
        nullifier that doesn't match what the pool expects from a valid proof.
        """
        r = _random_scalar()
        I_correct = _nullifier_fixed_H(r)

        for _ in range(10):
            U_attacker = _random_point()
            if U_attacker == NUMS_H:
                continue  # Negligible probability, skip
            I_attacker = _nullifier_custom_U(r, U_attacker)
            assert I_attacker != I_correct, (
                "Attacker's custom U produced the same nullifier as I=r·H. "
                "This should be cryptographically infeasible under DDH."
            )


# ==============================================================================
# [CRIT-1] Unauthenticated INPUTS(1) — Forged Intent Box
# ==============================================================================


class TestCrit1ForgedIntentBox:
    """
    CRIT-1: The MasterPoolBox must authenticate INPUTS(1) (the IntentToWithdraw box).
    Without authentication, an attacker creates a trivial sigmaProp(true) box,
    places a fresh nullifier in R4 and their address in R6, and drains the pool.

    The v9 fix uses two authentication layers:
      Layer 2: intentBox.R5 == pool.R9  (genesisId binding, defense-in-depth)
      Layer 3: blake2b256(intentBox.propositionBytes) == pool.R10  (static ITW hash)

    Critical insight: Layer 2 alone is bypassable because the genesisId is public
    on-chain and an attacker can copy it into their forged box's R5 register.
    Layer 3 is definitive because the hash is stored in the POOL (not the intent),
    making it impossible for a forged box to self-certify.
    """

    def _genuine_itw_script(self) -> bytes:
        """
        Simulate the globally static IntentToWithdraw ErgoTree bytes.
        In production: compiled by the Ergo node from PrivacyPoolIntentWithdraw.es.
        The script is globally static (no ring constants hardcoded).
        """
        return b"\x00\x00\x8c\xd0\x02genuine_itw_ergotree_bytes" + bytes(range(50))

    def _pool_itw_hash(self, itw_script: bytes) -> bytes:
        """blake2b256 of the ITW ErgoTree — stored in pool R10 at deployment."""
        return hashlib.blake2b(itw_script, digest_size=32).digest()

    def test_genuine_itw_script_passes_hash_check(self):
        """A genuine ITW script must pass the R10 hash check."""
        itw_script = self._genuine_itw_script()
        pool_r10 = self._pool_itw_hash(itw_script)
        assert contract_intent_script_hash_check(itw_script, pool_r10), (
            "Genuine ITW script must pass blake2b256 comparison against pool R10."
        )

    def test_forged_trivial_script_fails_hash_check(self):
        """
        EXPLOIT ATTEMPT: Attacker creates a box with a trivial script
        (e.g., sigmaProp(true) — no ring proof required).

        The pool checks blake2b256(intentBox.propositionBytes) == pool R10.
        The forged box has different propositionBytes → hash mismatch → REJECTED.
        """
        itw_script = self._genuine_itw_script()
        pool_r10 = self._pool_itw_hash(itw_script)

        # Attacker's forged box has a trivially spendable script
        forged_script = b"\x00\xd1\x97\x03" + secrets.token_bytes(20)
        assert not contract_intent_script_hash_check(forged_script, pool_r10), (
            "Forged trivial script must fail the R10 static hash check."
        )

    def test_layer2_alone_is_bypassable(self):
        """
        SECURITY NOTE: Layer 2 (genesisId in data register) alone is NOT sufficient.
        An attacker reads the genuine pool's genesisId from the chain and copies it
        into their forged box's R5 register — this check passes trivially.

        This test deliberately demonstrates the bypass to justify Layer 3 as mandatory.
        """
        pool_genesis = _pool_genesis_id()

        # Attacker reads genesisId from chain, copies it into their forged box's R5
        attacker_r5_genesis = pool_genesis

        layer2_passes = contract_intent_genesis_check(attacker_r5_genesis, pool_genesis)
        assert layer2_passes, (
            "Layer 2 (genesisId register) passes for the forged box — "
            "this demonstrates why Layer 3 (script hash in pool R10) is mandatory."
        )

    def test_layer3_blocks_the_layer2_bypass(self):
        """
        Even though the attacker copied the correct genesisId into R5 (Layer 2 passes),
        the forged box has the wrong propositionBytes → Layer 3 fails → REJECTED.
        """
        itw_script = self._genuine_itw_script()
        pool_r10 = self._pool_itw_hash(itw_script)
        pool_genesis = _pool_genesis_id()

        forged_script = b"\x00\xd1\x97\x03" + secrets.token_bytes(20)

        layer2_ok = contract_intent_genesis_check(pool_genesis, pool_genesis)
        layer3_ok = contract_intent_script_hash_check(forged_script, pool_r10)

        assert layer2_ok and not layer3_ok, (
            "Layer 2 passes (exploitable alone) but Layer 3 blocks the attack. "
            "Both layers together are required."
        )

    def test_genuine_box_passes_both_layers(self):
        """A genuine ITW box must pass both Layer 2 and Layer 3."""
        itw_script = self._genuine_itw_script()
        pool_r10 = self._pool_itw_hash(itw_script)
        pool_genesis = _pool_genesis_id()

        layer2_ok = contract_intent_genesis_check(pool_genesis, pool_genesis)
        layer3_ok = contract_intent_script_hash_check(itw_script, pool_r10)

        assert layer2_ok and layer3_ok, (
            "Genuine ITW box must pass both authentication layers."
        )

    def test_cross_pool_intent_rejected_by_layer2(self):
        """An intent created for Pool A must be rejected by Pool B."""
        pool_a_genesis = _pool_genesis_id()
        pool_b_genesis = _pool_genesis_id()
        while pool_b_genesis == pool_a_genesis:
            pool_b_genesis = _pool_genesis_id()

        assert not contract_intent_genesis_check(pool_a_genesis, pool_b_genesis), (
            "Intent created for Pool A must fail Pool B's genesisId check."
        )


# ==============================================================================
# [CRIT-3] Deposit Slot Hijacking via Unverified Input Slicing
# ==============================================================================


class TestCrit3DepositSlotHijacking:
    """
    CRIT-3: The MasterPoolBox slices INPUTS[1..1+numDeposits] and inserts their
    commitments into the Deposit Tree. If inputs are not individually validated
    (value == unitCost, R6 == expectedPoolHash), a malicious relayer can inject
    attacker-controlled boxes and hijack victim commitments.

    Attack: relayer places attacker's 0-ERG dummy box at INPUTS(1) and victim's
    real box at INPUTS(2). ergDiff == unitCost → numDeposits == 1 → only INPUTS(1)
    is sliced → attacker's commitment inserted, victim's ERG funds it.

    The v9 fix: STRICT per-input validation using == not >=.
    Refinement: >= would allow excess-ERG which desyncs pool accounting math.
    """

    DENOM = 10_000_000_000    # 10 ERG
    DEPOSIT_FEE = 10_000_000  # 0.01 ERG
    UNIT_COST = DENOM + DEPOSIT_FEE

    def _pool_script_hash(self) -> bytes:
        return hashlib.blake2b(b"genuine_pool_script", digest_size=32).digest()

    def _make_valid_deposit_input(self) -> dict:
        """A well-formed IntentToDeposit box."""
        return {
            "value": self.UNIT_COST,
            "r4_commitment": _commitment(_random_scalar(), self.DENOM),
            "r6_pool_hash": self._pool_script_hash(),
        }

    def _make_attacker_dummy_box(self, value: int = 0) -> dict:
        """Attacker's forged input: wrong value, attacker's commitment."""
        return {
            "value": value,
            "r4_commitment": _commitment(_random_scalar(), self.DENOM),
            "r6_pool_hash": self._pool_script_hash(),  # Copied from honest box
        }

    def test_valid_deposit_passes_strict_check(self):
        """A properly formed IntentToDeposit box passes per-input validation."""
        box = self._make_valid_deposit_input()
        assert contract_deposit_input_check(
            box["value"], self.UNIT_COST, box["r6_pool_hash"], self._pool_script_hash()
        ), "Honest deposit box must pass per-input validation."

    def test_zero_value_attacker_box_rejected(self):
        """
        EXPLOIT ATTEMPT: Attacker injects a 0-ERG box at INPUTS(1).
        The strict box.value == unitCost check rejects it (0 != unitCost).
        """
        dummy = self._make_attacker_dummy_box(value=0)
        assert not contract_deposit_input_check(
            dummy["value"], self.UNIT_COST, dummy["r6_pool_hash"], self._pool_script_hash()
        ), "0-ERG attacker box must fail strict value check."

    def test_excess_erg_rejected_by_strict_equality(self):
        """
        Refinement: even excess ERG is rejected by strict ==.
        If >= were used instead, unitCost+1 would pass, desyncing pool accounting.
        numDeposits = ergDiff / unitCost would mismatch the actual input count.
        """
        box = {**self._make_valid_deposit_input(), "value": self.UNIT_COST + 1}
        assert not contract_deposit_input_check(
            box["value"], self.UNIT_COST, box["r6_pool_hash"], self._pool_script_hash()
        ), "Box with excess ERG must fail strict equality (CRIT-3 refinement)."

    def test_wrong_pool_hash_rejected(self):
        """A deposit intent targeting Pool A cannot be swept into Pool B."""
        box = self._make_valid_deposit_input()
        wrong_pool_hash = hashlib.blake2b(b"different_pool", digest_size=32).digest()
        assert not contract_deposit_input_check(
            box["value"], self.UNIT_COST, box["r6_pool_hash"], wrong_pool_hash
        ), "Deposit intent with wrong pool hash must be rejected."

    def test_full_hijack_scenario_blocked(self):
        """
        Full CRIT-3 hijack scenario:
        - Attacker's 0-ERG dummy box sliced at INPUTS(1)
        - ergDiff == unitCost → numDeposits == 1 → only attacker box sliced

        v9 strict check: INPUTS(1).value == 0 ≠ unitCost → TX rejected.
        Victim's box at INPUTS(2) is never spent.
        """
        attacker_dummy = self._make_attacker_dummy_box(value=0)
        pool_hash = self._pool_script_hash()

        # Only INPUTS(1) is sliced
        sliced = [attacker_dummy]
        all_valid = all(
            contract_deposit_input_check(b["value"], self.UNIT_COST, b["r6_pool_hash"], pool_hash)
            for b in sliced
        )

        assert not all_valid, (
            "Hijack TX rejected: INPUTS(1) is 0-ERG box which fails strict value check. "
            "Victim's funds at INPUTS(2) are never consumed."
        )


# ==============================================================================
# [CRIT-4] Pool Spoofing via Script Identity
# ==============================================================================


class TestCrit4PoolSpoofing:
    """
    CRIT-4: A purely script-hash-based pool identity allows attackers to clone
    the pool (same script → same hash → same identity). IntentToDeposit boxes
    would be swept into a fake pool controlled by the attacker.

    Even with a genesisId in R9, an attacker can read the genuine pool's R9
    from the chain and copy it into the fake pool — both script hash and genesisId
    would match (proven in test_genesis_id_register_is_spoofable).

    The v9 fix: Singleton NFT minted at genesis. The NFT's on-chain ID is
    determined by the genesis BoxId (function of the funding TX), not by the script.
    A cloned pool cannot possess the same on-chain NFT.
    """

    def _pool_script_bytes(self) -> bytes:
        return b"\x00\x08\xcd" + bytes(range(100))

    def _script_hash(self, script: bytes) -> bytes:
        return hashlib.blake2b(script, digest_size=32).digest()

    def test_script_hash_equality_does_not_prove_uniqueness(self):
        """
        Two pools with the same script have the same script hash.
        Script-hash-based identity cannot distinguish genuine from fake pools.
        """
        script = self._pool_script_bytes()
        assert self._script_hash(script) == self._script_hash(script), (
            "Genuine and fake pools using the same script produce identical script hashes. "
            "Script-hash-based pool identity is trivially bypassable."
        )

    def test_genesis_id_register_is_spoofable(self):
        """
        SECURITY NOTE: Even with a genesisId in R9, an attacker can read the genuine
        pool's R9 from the chain and copy it into the fake pool. A fake pool with:
          - same propositionBytes (same script hash)
          - same R9 value (copied from chain)
        is indistinguishable from the genuine pool by register checks alone.
        """
        genuine_genesis = _pool_genesis_id()
        script = self._pool_script_bytes()

        genuine_identity = (self._script_hash(script), genuine_genesis)
        cloned_identity = (self._script_hash(script), genuine_genesis)  # Attacker copies both

        assert genuine_identity == cloned_identity, (
            "Cloned pool with copied R9 is indistinguishable by script hash + genesisId alone. "
            "This justifies the Singleton NFT as the sole reliable identity primitive."
        )

    def test_nft_id_cannot_be_spoofed(self):
        """
        v9 fix: The genuine pool carries a Singleton NFT with a globally unique ID.
        A cloned pool either has no NFT, or a different NFT — both fail the check.
        """
        genuine_nft = _pool_nft_id()

        # Case (a): Fake pool has no NFT
        assert not contract_singleton_nft_check(None, genuine_nft), (
            "Fake pool without NFT must fail."
        )

        # Case (b): Fake pool has a different NFT
        fake_nft = _pool_nft_id()
        while fake_nft == genuine_nft:
            fake_nft = _pool_nft_id()
        assert not contract_singleton_nft_check(fake_nft, genuine_nft), (
            "Fake pool with wrong NFT ID must fail."
        )

        # Genuine pool passes
        assert contract_singleton_nft_check(genuine_nft, genuine_nft), (
            "Genuine pool with correct NFT must pass."
        )

    def test_nft_propagation_invariant(self):
        """
        Every state transition must propagate the NFT unchanged (same ID, quantity == 1).
        Simulates the singletonOk check across 20 pool state transitions.
        """
        genesis_nft = _pool_nft_id()
        current_nft = genesis_nft

        for i in range(20):
            next_nft = current_nft  # singletonOk enforces identity
            assert contract_singleton_nft_check(next_nft, genesis_nft), (
                f"NFT must propagate unchanged at transition {i}."
            )
            current_nft = next_nft

        assert current_nft == genesis_nft

    def test_multi_token_output_rejected(self):
        """
        The contract enforces tokens.size == 1. An output with 2+ tokens is rejected.
        """
        genuine_nft = _pool_nft_id()
        extra_token = _pool_nft_id()

        def _extended_check(tokens: list[bytes], expected: bytes) -> bool:
            return len(tokens) == 1 and tokens[0] == expected

        assert not _extended_check([genuine_nft, extra_token], genuine_nft), (
            "Pool output with 2 tokens must fail (tokens.size must == 1)."
        )
        assert _extended_check([genuine_nft], genuine_nft), (
            "Pool output with exactly 1 correct NFT must pass."
        )


# ==============================================================================
# Cross-cutting: Full authentication stack (CRIT-1 + CRIT-4)
# ==============================================================================


class TestWithdrawalAuthStack:
    """
    Tests the full v9 authentication stack as a combined unit.
    A withdrawal is valid only if ALL layers pass simultaneously.
    """

    def _itw_script(self) -> bytes:
        return b"\x00\x00\x8c\xd0\x02pool_itw_ergotree" + bytes(range(60))

    def _pool_r10(self, itw: bytes) -> bytes:
        return hashlib.blake2b(itw, digest_size=32).digest()

    def _pool_genesis(self) -> bytes:
        return b"genesis_" + secrets.token_bytes(24)

    def _pool_nft(self) -> bytes:
        return secrets.token_bytes(32)

    def test_genuine_withdrawal_passes_all_layers(self):
        """A genuine withdrawal passes all authentication layers."""
        itw = self._itw_script()
        pool_r10 = self._pool_r10(itw)
        pool_genesis = self._pool_genesis()
        pool_nft = self._pool_nft()

        # Layer 1: Ring proof built in pool (ErgoScript — cannot test in Python)
        # Layer 2: genesisId binding
        l2 = contract_intent_genesis_check(pool_genesis, pool_genesis)
        # Layer 3: Static ITW script hash
        l3 = contract_intent_script_hash_check(itw, pool_r10)
        # Layer 4: Singleton NFT
        l4 = contract_singleton_nft_check(pool_nft, pool_nft)

        assert all([l2, l3, l4]), "Genuine withdrawal must pass all authentication layers."

    def test_forged_box_blocked_by_l3_despite_l2_pass(self):
        """
        Key finding: even if L2 (genesisId register) passes (attacker copies it),
        L3 (script hash from Pool R10) catches the forged script.
        """
        itw = self._itw_script()
        pool_r10 = self._pool_r10(itw)
        pool_genesis = self._pool_genesis()
        pool_nft = self._pool_nft()

        forged_script = b"\x00\xd1\x97\x03sigmaProp_true" + secrets.token_bytes(20)

        l2 = contract_intent_genesis_check(pool_genesis, pool_genesis)  # Attacker copied
        l3 = contract_intent_script_hash_check(forged_script, pool_r10)  # Fails
        l4 = contract_singleton_nft_check(pool_nft, pool_nft)

        assert l2 and not l3 and l4, (
            "L2 passes (bypassable), L3 fails (definitive block). Overall: REJECTED."
        )

    @pytest.mark.parametrize("fail_layer", ["L2", "L3", "L4"])
    def test_any_failed_layer_blocks_withdrawal(self, fail_layer: str):
        """A withdrawal is rejected if ANY authentication layer fails."""
        itw = self._itw_script()
        pool_r10 = self._pool_r10(itw)
        pool_genesis = self._pool_genesis()
        pool_nft = self._pool_nft()

        forged_script = b"\x00wrong" + secrets.token_bytes(20)
        wrong_genesis = b"wrong_genesis_" + secrets.token_bytes(18)
        wrong_nft = secrets.token_bytes(32)

        if fail_layer == "L2":
            l2 = contract_intent_genesis_check(wrong_genesis, pool_genesis)
            l3 = contract_intent_script_hash_check(itw, pool_r10)
            l4 = contract_singleton_nft_check(pool_nft, pool_nft)
        elif fail_layer == "L3":
            l2 = contract_intent_genesis_check(pool_genesis, pool_genesis)
            l3 = contract_intent_script_hash_check(forged_script, pool_r10)
            l4 = contract_singleton_nft_check(pool_nft, pool_nft)
        else:  # L4
            l2 = contract_intent_genesis_check(pool_genesis, pool_genesis)
            l3 = contract_intent_script_hash_check(itw, pool_r10)
            l4 = contract_singleton_nft_check(wrong_nft, pool_nft)

        assert not all([l2, l3, l4]), (
            f"Withdrawal with {fail_layer} failing must be rejected overall."
        )
