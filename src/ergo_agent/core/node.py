"""
ErgoNode: REST client for the Ergo public node API and Explorer API.

Docs: https://api.ergoplatform.com/api/v1/docs/
"""

from __future__ import annotations

from typing import Any

import httpx

from ergo_agent.core.models import NANOERG_PER_ERG, Balance, Box, Token, Transaction

# Public mainnet endpoints
PUBLIC_NODE_URL = "https://api.ergoplatform.com"
PUBLIC_EXPLORER_URL = "https://api.ergoplatform.com"

# Token name registry — common well-known tokens
_KNOWN_TOKENS: dict[str, tuple[str, int]] = {
    "03faf2cb329f2e90d6d23b58d91bbb6c046aa143261cc21f52fbe2824bfcbf04": ("SigUSD", 2),
    "003bd19d0187117f130b62e1bcab0939929ff5c7709f843c5c4dd158949285d0": ("SigRSV", 0),
    "d71693c49a84fbbecd4908c94813b46514b18b67a99952dc1e6e4791556de413": ("ERG-USD-Oracle", 0),
}


class ErgoNodeError(Exception):
    """Raised when the Ergo Node API returns an error."""
    pass


class ErgoNode:
    """
    Synchronous client for the Ergo blockchain.
    Uses the public Explorer API by default — no node required.

    Usage:
        node = ErgoNode()  # uses public API
        node = ErgoNode(node_url="http://localhost:9053", api_key="secret")
    """

    def __init__(
        self,
        node_url: str = PUBLIC_NODE_URL,
        explorer_url: str = PUBLIC_EXPLORER_URL,
        api_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.node_url = node_url.rstrip("/")
        self.explorer_url = explorer_url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["api_key"] = api_key
        self._client = httpx.Client(headers=headers, timeout=timeout)

    # ------------------------------------------------------------------
    # Chain info
    # ------------------------------------------------------------------

    def get_height(self) -> int:
        """Return current blockchain height."""
        data = self._get("/api/v1/networkState")
        return int(data["height"])

    def get_network_info(self) -> dict[str, Any]:
        """Return full network state info."""
        return self._get("/api/v1/networkState")

    # ------------------------------------------------------------------
    # Balance & boxes
    # ------------------------------------------------------------------

    def get_balance(self, address: str) -> Balance:
        """
        Return the ERG and token balance for an address.

        Returns:
            Balance: structured balance with ERG float and token list.
        """
        data = self._get(f"/api/v1/addresses/{address}/balance/total")
        erg_nano = int(data["confirmed"]["nanoErgs"])

        tokens: list[Token] = []
        for t in data["confirmed"].get("tokens", []):
            token_id = t["tokenId"]
            name, decimals = _KNOWN_TOKENS.get(token_id, (t.get("name"), t.get("decimals", 0)))
            tokens.append(Token(
                token_id=token_id,
                amount=int(t["amount"]),
                name=name,
                decimals=decimals or 0,
            ))

        return Balance(
            address=address,
            erg=erg_nano / NANOERG_PER_ERG,
            erg_nanoerg=erg_nano,
            tokens=tokens,
        )

    def get_unspent_boxes(self, address: str, limit: int = 50) -> list[Box]:
        """Return unspent boxes (UTXOs) for an address."""
        data = self._get(f"/api/v1/boxes/unspent/byAddress/{address}?limit={limit}")
        return [self._parse_box(b) for b in data.get("items", [])]

    def get_box_by_id(self, box_id: str) -> Box:
        """Return a specific box by ID."""
        data = self._get(f"/api/v1/boxes/{box_id}")
        return self._parse_box(data)

    def get_boxes_by_token_id(self, token_id: str, limit: int = 20) -> list[Box]:
        """Return boxes containing a specific token (useful for finding pool/oracle boxes)."""
        data = self._get(f"/api/v1/boxes/unspent/byTokenId/{token_id}?limit={limit}")
        return [self._parse_box(b) for b in data.get("items", [])]

    def get_boxes_by_ergo_tree(self, ergo_tree_hex: str, limit: int = 20) -> list[Box]:
        """Return boxes matching a specific ErgoTree (P2S address)."""
        data = self._get(f"/api/v1/boxes/unspent/byErgoTree/{ergo_tree_hex}?limit={limit}")
        return [self._parse_box(b) for b in data.get("items", [])]

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    def get_transaction(self, tx_id: str) -> Transaction:
        """Return a transaction by ID."""
        data = self._get(f"/api/v1/transactions/{tx_id}")
        return Transaction(
            tx_id=tx_id,
            inputs=data.get("inputs", []),
            outputs=data.get("outputs", []),
            confirmed=True,
        )

    def get_mempool_transactions(self, address: str) -> list[dict[str, Any]]:
        """Return pending (unconfirmed) transactions for an address."""
        data = self._get(f"/api/v1/mempool/transactions/byAddress/{address}")
        return data.get("items", [])

    def get_transaction_history(
        self, address: str, offset: int = 0, limit: int = 20
    ) -> list[Transaction]:
        """
        Get recent transaction history for an address.

        Args:
            address: Ergo address
            offset: pagination offset
            limit: max transactions to return (default 20)

        Returns:
            list[Transaction]: recent transactions, newest first
        """
        data = self._get(
            f"/api/v1/addresses/{address}/transactions?offset={offset}&limit={limit}"
        )
        txs = []
        for tx_data in data.get("items", []):
            txs.append(Transaction(
                tx_id=tx_data.get("id", ""),
                inputs=tx_data.get("inputs", []),
                outputs=tx_data.get("outputs", []),
                confirmed=True,
            ))
        return txs

    def submit_transaction(self, signed_tx: dict[str, Any]) -> str:
        """
        Submit a signed transaction to the network.

        Args:
            signed_tx: signed transaction as a dict (ErgoTransaction format)

        Returns:
            str: transaction ID
        """
        response = self._client.post(
            f"{self.node_url}/api/v1/transactions",
            json=signed_tx,
        )
        if response.status_code != 200:
            raise ErgoNodeError(
                f"Transaction rejected: {response.status_code} — {response.text}"
            )
        return str(response.json())

    # ------------------------------------------------------------------
    # Script compilation
    # ------------------------------------------------------------------

    def compile_script(
        self,
        source: str,
        compile_node_url: str = "https://node.ergo.watch",
    ) -> dict[str, str]:
        """
        Compile ErgoScript source code into a P2S address.

        This calls the Ergo node's /script/p2sAddress endpoint.
        By default, uses the public node.ergo.watch since the Explorer API
        doesn't expose script compilation.

        Args:
            source: ErgoScript source code
            compile_node_url: URL of an Ergo node that exposes /script/ endpoints.
                              Default: node.ergo.watch (public full node)

        Returns:
            dict with keys:
                - 'address': the P2S address (base58)

        Raises:
            ErgoNodeError: if compilation fails (syntax error, type error, etc.)
        """
        url = f"{compile_node_url.rstrip('/')}/script/p2sAddress"
        response = self._client.post(url, json={"source": source})
        if response.status_code != 200:
            error_detail = response.json().get("detail", response.text)
            raise ErgoNodeError(f"Script compilation failed: {error_detail}")
        return response.json()

    # ------------------------------------------------------------------
    # Oracle
    # ------------------------------------------------------------------

    def get_oracle_pool_box(self, oracle_pool_nft_id: str) -> Box:
        """
        Fetch the live oracle pool box by its NFT ID.
        Used to read ERG/USD price and other data feeds.

        The price is stored in register R4 as nanoERG per 1 USD cent.
        """
        boxes = self.get_boxes_by_token_id(oracle_pool_nft_id, limit=1)
        if not boxes:
            raise ErgoNodeError(f"Oracle pool box not found for NFT: {oracle_pool_nft_id}")
        return boxes[0]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str) -> Any:
        url = f"{self.node_url}{path}"
        response = self._client.get(url)
        if response.status_code != 200:
            raise ErgoNodeError(f"API error {response.status_code} for {url}: {response.text}")
        return response.json()

    def _parse_box(self, data: dict[str, Any]) -> Box:
        tokens = [
            Token(
                token_id=t["tokenId"],
                amount=int(t["amount"]),
                name=t.get("name"),
                decimals=int(t.get("decimals") or 0),
            )
            for t in data.get("assets", [])
        ]
        return Box(
            box_id=data["boxId"],
            value=int(data["value"]),
            ergo_tree=data["ergoTree"],
            address=data.get("address"),
            creation_height=int(data.get("creationHeight", 0)),
            index=int(data.get("index", 0)),
            transaction_id=data.get("transactionId"),
            tokens=tokens,
            additional_registers=data.get("additionalRegisters", {}),
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> ErgoNode:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
