from typing import Dict, Any, List
import httpx

class RosenBridge:
    """
    Client for interacting with Rosen Bridge data.
    Provides read-only access to global TVL and supported chains via DefiLlama.
    """
    
    API_URL = "https://api.llama.fi/protocol/rosen-bridge"
    
    def __init__(self):
        self.client = httpx.Client(timeout=15.0)

    def get_bridge_status(self) -> Dict[str, Any]:
        """
        Fetch the current status and TVL of the Rosen Bridge.
        
        Returns:
            Dictionary containing global TVL, chain-specific TVLs, and supported networks.
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
                "supported_chains": data.get("chains", []),
                "chain_tvls_usd": chain_tvls,
                "url": data.get("url")
            }
        except Exception as e:
            raise Exception(f"Failed to fetch Rosen Bridge status: {str(e)}")
