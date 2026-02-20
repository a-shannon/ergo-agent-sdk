from typing import Dict, Any
import httpx
from ergo_agent.core.node import ErgoNode

class SigmaUSD:
    """
    Client for interacting with the SigmaUSD / AgeUSD protocol on Ergo.
    Provides read-only access to bank state, reserve ratio, and prices.
    """
    
    TOKENJAY_API_URL = "https://api.tokenjay.app"
    SIGUSD_TOKEN_ID = "03faf2cb329f2e90d6d23b58d91bbb6c046aa143261cc21f52fbe2824bfcbf04"
    SIGRSV_TOKEN_ID = "003bd19d0187117f130b62e1bcab0939929ff5c7709f843c5c4dd158949285d0"
    
    def __init__(self, node: ErgoNode = None):
        """
        Initialize the SigmaUSD client.
        
        Args:
            node: Optional ErgoNode instance (unused currently as we rely on TokenJay for parsed math, 
                  but included for future-proofing).
        """
        self.node = node or ErgoNode()
        self.client = httpx.Client(timeout=15.0)

    def get_bank_state(self) -> Dict[str, Any]:
        """
        Fetch the current state of the SigmaUSD Bank.
        Returns the reserve ratio, SigUSD price, and SigRSV price in nanoERG.
        
        Returns:
            Dictionary containing reserveRatio, sigUsdPrice, sigRsvPrice.
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
