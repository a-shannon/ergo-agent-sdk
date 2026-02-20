from typing import Dict, Any, Tuple
import httpx
from ergo_agent.core.node import ErgoNode
from ergo_agent.core.builder import TransactionBuilder, MIN_BOX_VALUE_NANOERG

class SigmaUSD:
    """
    Client for interacting with the SigmaUSD / AgeUSD protocol on Ergo.
    Provides read-only access to bank state, reserve ratio, prices,
    and transaction builders for minting/redeeming stablecoins.
    """
    
    TOKENJAY_API_URL = "https://api.tokenjay.app"
    SIGUSD_TOKEN_ID = "03faf2cb329f2e90d6d23b58d91bbb6c046aa143261cc21f52fbe2824bfcbf04"
    SIGRSV_TOKEN_ID = "003bd19d0187117f130b62e1bcab0939929ff5c7709f843c5c4dd158949285d0"
    BANK_NFT_ID = "011d3364de07e5a26f0c4eef0852cddb387039a921b7154ef3cab22c6eda887f"
    ORACLE_NFT_ID = "011d3364de07e5a26f0c4eef0852cddb387039a921b7154ef3cab22c6eda887f" # Simplified, actual implementation parses ErgoTree
    BANK_ADDRESS = "4MQyML64GnzMxZgm"
    
    def __init__(self, node: ErgoNode = None):
        """Initialize the SigmaUSD client."""
        self.node = node or ErgoNode()
        self.client = httpx.Client(timeout=15.0)

    def get_bank_state(self) -> Dict[str, Any]:
        """
        Fetch the current state of the SigmaUSD Bank.
        Returns the reserve ratio, SigUSD price, and SigRSV price in nanoERG.
        """
        try:
            response = self.client.get(f"{self.TOKENJAY_API_URL}/ageusd/info")
            response.raise_for_status()
            data = response.json()
            
            # Format nicely for the agent
            return {
                "reserve_ratio_percent": data.get("reserveRatio", 0),
                "sigusd_price_nanoerg": data.get("sigUsdPrice", 0),
                "sigusd_price_erg": data.get("sigUsdPrice", 0) / 1e9,
                "sigrsv_price_nanoerg": data.get("sigRsvPrice", 0),
                "sigrsv_price_erg": data.get("sigRsvPrice", 0) / 1e9,
                "status": "Healthy" if 400 <= data.get("reserveRatio", 0) <= 800 else "Warning (Minting restricted)",
            }
        except Exception as e:
            raise Exception(f"Failed to fetch SigmaUSD bank state: {str(e)}")

    def build_mint_sigusd_tx(self, amount_sigusd: int, wallet: Any) -> Dict[str, Any]:
        """
        Build an unsigned transaction to mint SigUSD in exchange for ERG.
        
        Args:
            amount_sigusd: The integer amount of SigUSD cents to mint (e.g. 100 for 1.00 SigUSD).
            wallet: The Wallet instance of the user.
            
        Returns:
            Dict: Unsigned transaction dict ready for signing.
        """
        state = self.get_bank_state()
        
        # Check reserve ratio (Minting SigUSD is blocked if ratio < 400%)
        ratio = state["reserve_ratio_percent"]
        if ratio < 400:
            raise Exception(f"Cannot mint SigUSD: Reserve Ratio is currently {ratio}%, which is below the 400% minimum threshold.")
            
        # Calculate ERG cost (Price + 2% protocol fee)
        base_cost = amount_sigusd * state["sigusd_price_nanoerg"]
        protocol_fee = int(base_cost * 0.02)
        total_cost_nanoerg = base_cost + protocol_fee
        
        # In a full-node implementation, we would construct the P2S output here
        # matching the AgeUSD mathematical invariants in the Bank Script.
        # Since we are an SDK, we abstract this complexity into a raw output builder.
        builder = TransactionBuilder(self.node, wallet)
        
        # We need to send the ERG to a proxy contract or directly interact with the Bank box
        # For SDK simulation purposes, we emulate a Proxy Contract deployment (like TokenJay does).
        proxy_contract_address = "4MQyML64GnzMxZgm" # Placeholder for proxy P2S
        
        builder.add_output_raw(
            ergo_tree=self.node._resolve_address_to_tree(proxy_contract_address),
            value_nanoerg=total_cost_nanoerg + MIN_BOX_VALUE_NANOERG,
            tokens=[],
            registers={}
        )
        
        return builder.build()

    def build_mint_sigrsv_tx(self, amount_sigrsv: int, wallet: Any) -> Dict[str, Any]:
        """
        Build an unsigned transaction to mint SigRSV (Reserve coins).
        """
        state = self.get_bank_state()
        
        # Check reserve ratio (Minting SigRSV is blocked if ratio > 800%)
        ratio = state["reserve_ratio_percent"]
        if ratio > 800:
            raise Exception(f"Cannot mint SigRSV: Reserve Ratio is currently {ratio}%, which is above the 800% max threshold.")
            
        base_cost = amount_sigrsv * state["sigrsv_price_nanoerg"]
        protocol_fee = int(base_cost * 0.02)
        total_cost_nanoerg = base_cost + protocol_fee
        
        builder = TransactionBuilder(self.node, wallet)
        proxy_contract_address = "4MQyML64GnzMxZgm"
        
        builder.add_output_raw(
            ergo_tree=self.node._resolve_address_to_tree(proxy_contract_address),
            value_nanoerg=total_cost_nanoerg + MIN_BOX_VALUE_NANOERG,
            tokens=[],
            registers={}
        )
        
        return builder.build()

    def build_redeem_sigusd_tx(self, amount_sigusd: int, wallet: Any) -> Dict[str, Any]:
        """
        Build an unsigned transaction to redeem SigUSD for ERG.
        """
        state = self.get_bank_state()
        
        base_value = amount_sigusd * state["sigusd_price_nanoerg"]
        protocol_fee = int(base_value * 0.02)
        expected_erg_return = base_value - protocol_fee
        
        builder = TransactionBuilder(self.node, wallet)
        proxy_contract_address = "4MQyML64GnzMxZgm"
        
        builder.add_output_raw(
            ergo_tree=self.node._resolve_address_to_tree(proxy_contract_address),
            value_nanoerg=MIN_BOX_VALUE_NANOERG * 2,
            tokens=[{"tokenId": self.SIGUSD_TOKEN_ID, "amount": amount_sigusd}],
            registers={}
        )
        
        return builder.build()

    def build_redeem_sigrsv_tx(self, amount_sigrsv: int, wallet: Any) -> Dict[str, Any]:
        """
        Build an unsigned transaction to redeem SigRSV for ERG.
        """
        state = self.get_bank_state()
        
        ratio = state["reserve_ratio_percent"]
        if ratio < 400:
            raise Exception(f"Cannot redeem SigRSV: Reserve Ratio is currently {ratio}%, which is below the 400% minimum threshold for Reserve redemption.")
            
        builder = TransactionBuilder(self.node, wallet)
        proxy_contract_address = "4MQyML64GnzMxZgm"
        
        builder.add_output_raw(
            ergo_tree=self.node._resolve_address_to_tree(proxy_contract_address),
            value_nanoerg=MIN_BOX_VALUE_NANOERG * 2,
            tokens=[{"tokenId": self.SIGRSV_TOKEN_ID, "amount": amount_sigrsv}],
            registers={}
        )
        
        return builder.build()
