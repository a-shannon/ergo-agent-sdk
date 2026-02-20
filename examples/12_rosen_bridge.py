"""
Example 12: Rosen Bridge Status
This script demonstrates how to read the current TVL and chain support 
for the Rosen Bridge using the DefiLlama API wrapper.
"""
from ergo_agent.defi import RosenBridge

def main():
    print("Fetching Rosen Bridge Status...")
    rosen = RosenBridge()
    state = rosen.get_bridge_status()
    
    print("\n--- [Bridge] Rosen Bridge Stats ---")
    print(f"Name                 : {state['name']}")
    print(f"Global TVL           : ${state['global_tvl_usd']:,.2f}")
    print(f"Supported Chains     : {', '.join(state['supported_chains'])}")
    
    print("\n--- [TVL per Chain] ---")
    for chain, tvl in state['chain_tvls_usd'].items():
        # Clean up chain names if DefiLlama appended "-borrowed" or similar
        clean_chain = chain.replace("-borrowed", "").replace("-staking", "")
        if "pool2" not in clean_chain:
            print(f"{clean_chain.ljust(15)}: ${tvl:,.2f}")
            
    print("-----------------------------------\n")

if __name__ == "__main__":
    main()
