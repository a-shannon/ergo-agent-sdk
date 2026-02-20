"""
Example 11: SigmaUSD Bank State
This script demonstrates how to read the current state of the AgeUSD
protocol (SigmaUSD/SigmaRSV) on Ergo.
"""
from ergo_agent.defi import SigmaUSD

def main():
    print("Fetching SigmaUSD Bank State...")
    sigmausd = SigmaUSD()
    state = sigmausd.get_bank_state()
    
    print("\n--- [Bank] SigmaUSD Protocol State ---")
    print(f"Status               : {state['status']}")
    print(f"Reserve Ratio        : {state['reserve_ratio_percent']}%")
    print("\n--- [Prices] ---")
    print(f"SigUSD Minting Price : {state['sigusd_price_erg']:.4f} ERG")
    print(f"SigRSV Minting Price : {state['sigrsv_price_erg']:.6f} ERG")
    print("----------------------------------\n")

if __name__ == "__main__":
    main()
