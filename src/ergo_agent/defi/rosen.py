from typing import Any

import httpx
from ergo_lib_python.chain import Constant

from ergo_agent.core.builder import TransactionBuilder
from ergo_agent.core.node import ErgoNode


class RosenBridge:
    """
    Client for interacting with the Rosen Bridge.
    Provides read-only access to global TVL and transaction builders
    for sending assets cross-chain to Cardano, Bitcoin, etc.
    """

    API_URL = "https://api.llama.fi/protocol/rosen-bridge"
    # The dedicated Ergo P2S address for the Rosen Bank Watchers
    ROSEN_BANK_ADDRESS = "9erHqBtsj1FWeQJm8yZEDWj8b8b3zGvM6u7e9Pndn6p6vSjR2cM"

    def __init__(self, node: ErgoNode = None):
        self.node = node or ErgoNode()
        self.client = httpx.Client(timeout=15.0)

    def get_bridge_status(self) -> dict[str, Any]:
        """
        Fetch the current status and TVL of the Rosen Bridge.
        """
        try:
            response = self.client.get(self.API_URL)
            response.raise_for_status()
            data = response.json()

            chain_tvls = data.get("currentChainTvls", {})
            return {
                "name": data.get("name"),
                "description": data.get("description"),
                "global_tvl_usd": sum(chain_tvls.values()),
                "supported_chains": ["Cardano", "Bitcoin", "Ethereum"], # Hardcoded from docs
                "chain_tvls_usd": chain_tvls,
                "url": data.get("url")
            }
        except Exception as e:
            raise ValueError(f"Failed to fetch Rosen Bridge status: {str(e)}")

    def build_bridge_tx(self, to_chain: str, to_address: str, amount_erg: float, tokens: dict[str, int], wallet: Any) -> dict[str, Any]:
        """
        Build an unsigned transaction to bridge assets via Rosen.

        Args:
            to_chain: Destination network (e.g. "Cardano", "Bitcoin")
            to_address: Destination address on the target network
            amount_erg: ERG amount to send
            tokens: Dictionary of Ergo native tokens to send
            wallet: User's Wallet instance
        """
        if to_chain not in ["Cardano", "Bitcoin", "Ethereum", "Binance"]:
            raise Exception(f"Unsupported destination chain: {to_chain}")

        # Bridge fee calculation (simplified, typically requires an Oracle lookup for rsToken fees)
        bridge_fee_nanoerg = 20_000_000 # 0.02 ERG
        network_fee_nanoerg = 2_000_000 # 0.002 ERG

        total_erg_required_nanoerg = int(amount_erg * 1e9) + bridge_fee_nanoerg + network_fee_nanoerg

        builder = TransactionBuilder(self.node, wallet)

        # When bridging via Rosen, the destination chain and address are encoded in the R4 and R5 box registers
        registers = {
            "R4": bytes(Constant(to_chain.encode("utf-8"))).hex(),
            "R5": bytes(Constant(to_address.encode("utf-8"))).hex()
        }

        token_list = [{"tokenId": t_id, "amount": amt} for t_id, amt in tokens.items()]

        builder.add_output_raw(
            ergo_tree=self.node._resolve_address_to_tree(self.ROSEN_BANK_ADDRESS),
            value_nanoerg=total_erg_required_nanoerg,
            tokens=token_list,
            registers=registers
        )

        return builder.build()
