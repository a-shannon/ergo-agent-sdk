"""
Wallet: private key management and transaction signing for Ergo.

This module wraps the Ergo signing logic. Private keys never leave this module —
the agent only ever receives addresses and box IDs.

Note: For signing, we delegate to the Ergo node's wallet API (if available)
or use the ergpy library. In environments where neither is available,
the agent runs in read-only mode (can query but not sign).
"""

from __future__ import annotations

from typing import Any

from ergo_agent.core.address import is_valid_address


class WalletError(Exception):
    pass


class Wallet:
    """
    Ergo wallet — holds the private key material and signs transactions.

    Usage:
        wallet = Wallet.from_mnemonic("word1 word2 ...")
        wallet = Wallet.from_node(node, wallet_password="secret")  # uses node's built-in wallet
        wallet = Wallet.read_only(address="9f...")  # no signing, query only
    """

    def __init__(
        self,
        address: str,
        _private_key_hex: str | None = None,
        _node_wallet: bool = False,
        read_only: bool = False,
    ) -> None:
        self.address = address
        self._private_key_hex = _private_key_hex
        self._node_wallet = _node_wallet
        self.read_only = read_only

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_mnemonic(cls, mnemonic: str, passphrase: str = "") -> Wallet:
        """
        Create a wallet from a BIP39 mnemonic phrase.

        Not yet implemented. Requires ergo-lib (sigma-rust) Python bindings
        for proper BIP32/44 key derivation (path m/44'/429'/0'/0/0).

        For now, use Wallet.from_node_wallet() or Wallet.read_only() instead.
        """
        raise NotImplementedError(
            "Mnemonic wallet not yet implemented. "
            "Use Wallet.from_node_wallet(address) to sign via node, "
            "or Wallet.read_only(address) for read-only access."
        )

    @classmethod
    def from_node_wallet(cls, node_address: str) -> Wallet:
        """
        Use the Ergo node's built-in wallet for signing.
        The node handles key storage and signing -- this SDK just triggers it.

        Args:
            node_address: the address from the node's loaded wallet
        """
        if not is_valid_address(node_address):
            raise WalletError(f"Invalid Ergo address: {node_address}")
        return cls(
            address=node_address,
            _node_wallet=True,
            read_only=False,
        )

    @classmethod
    def read_only(cls, address: str) -> Wallet:
        """
        Read-only wallet -- can query balances and build transactions,
        but cannot sign. Useful for monitoring agents.
        """
        if not is_valid_address(address):
            raise WalletError(f"Invalid Ergo address: {address}")
        return cls(address=address, read_only=True)

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    def sign_transaction(
        self,
        unsigned_tx: dict[str, Any],
        node: Any | None = None,
        secrets: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Sign an unsigned transaction.

        If using a node wallet, the node signs it.
        If using local keys, signs with the private key.

        Args:
            unsigned_tx: the unsigned transaction dict
            node: ErgoNode instance (required for node_wallet mode)
            secrets: Optional signing secrets for protocols requiring
                extra proofs (e.g., ring signatures). Dict with:
                - 'dlog': list of secret hex strings for proveDlog
                - 'dht': list of DH tuple dicts with keys:
                    'secret', 'g', 'h', 'u', 'v' (all compressed hex)

        Returns:
            dict: signed transaction ready for submission
        """
        if self.read_only:
            raise WalletError("This wallet is read-only and cannot sign transactions.")

        if self._node_wallet:
            if node is None:
                raise WalletError("node parameter required for node_wallet signing.")
            return self._sign_via_node(unsigned_tx, node, secrets=secrets)

        # Local signing — requires proper ergo-lib integration
        # TODO: Implement with sigma-rust Python bindings
        raise WalletError(
            "Local signing from mnemonic is not yet implemented. "
            "Use Wallet.from_node_wallet() instead, or sign the transaction "
            "manually using Nautilus wallet or Satergo."
        )

    def _sign_via_node(
        self,
        unsigned_tx: dict[str, Any],
        node: Any,
        secrets: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Sign transaction using the node's wallet API."""
        try:
            import ergo_lib_python.chain as chain
            inputs_raw = []
            for inp in unsigned_tx.get("inputs", []):
                box_id = inp["boxId"]
                # Fetch box from local node first (mempool-aware), then explorer
                box_json = None
                for endpoint in [
                    f"{node.node_url}/utxo/withPool/byId/{box_id}",
                    f"{node.node_url}/utxo/byId/{box_id}",
                    f"{node.explorer_url}/api/v1/boxes/{box_id}",
                ]:
                    try:
                        r = node._client.get(endpoint)
                        if r.status_code == 200:
                            box_json = r.json()
                            break
                    except Exception:
                        continue

                if box_json:
                    try:
                        import json
                        box_json_str = json.dumps(box_json)
                        box = chain.ErgoBox.from_json(box_json_str)
                        inputs_raw.append(bytes(box).hex())
                    except Exception as e:
                        import logging
                        logging.getLogger("ergo_agent.wallet").warning(
                            f"Failed to serialize box {box_id[:16]}... for inputsRaw: {e}"
                        )

            payload = {"tx": unsigned_tx}
            if len(inputs_raw) == len(unsigned_tx.get("inputs", [])):
                payload["inputsRaw"] = inputs_raw
                payload["dataInputsRaw"] = []
            if secrets:
                payload["secrets"] = secrets

            headers = {"Content-Type": "application/json"}
            if hasattr(node, '_api_key') and node._api_key:
                headers["api_key"] = node._api_key

            response = node._client.post(
                f"{node.node_url}/wallet/transaction/sign",
                json=payload,
                headers=headers,
            )
            if response.status_code != 200:
                raise WalletError(f"Node signing failed: {response.text}")
            return response.json()
        except ImportError:
            # Fallback if ergo_lib_python is not installed (should not happen in SDK)
            response = node._client.post(
                f"{node.node_url}/wallet/transaction/sign",
                json={"tx": unsigned_tx},
            )
            if response.status_code != 200:
                raise WalletError(f"Node signing failed: {response.text}") from None
            return response.json()

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        mode = "read-only" if self.read_only else "node-wallet" if self._node_wallet else "local"
        return f"Wallet(address={self.address!r}, mode={mode!r})"


# ------------------------------------------------------------------
# BIP39 seed derivation (minimal — standard BIP39 PBKDF2)
# ------------------------------------------------------------------

def _mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """Derive a 64-byte seed from a BIP39 mnemonic + optional passphrase."""
    import hashlib
    mnemonic_bytes = mnemonic.encode("utf-8")
    salt = ("mnemonic" + passphrase).encode("utf-8")
    return hashlib.pbkdf2_hmac("sha512", mnemonic_bytes, salt, 2048)
