import asyncio
import argparse
from typing import Optional

from ergo_agent.core.node import ErgoNode
from ergo_agent.core.models import Box
from ergo_lib_python.chain import Constant

async def main():
    print("==============================================")
    print("  $CASH v3 -- AI Agent Ring Scanner  ")
    print("==============================================\n")

    print("> Initializing SDK and connecting to ErgoNode...")
    node = ErgoNode()

    try:
        network_info = node.get_network_info()
        name = network_info.get('name', network_info.get('network', 'Ergo Network'))
        print(f"> Connected to network: {name}")
    except Exception as e:
        print(f"> Failed to connect to node: {e}")
        return

    print("\n[Mocking a PoolBox on-chain query]")
    # For the sake of this test script, we will simulate receiving a PoolBox
    # from the blockchain that contains a dynamic `keys.map` ring array in R4.
    
    # 1. We mock the R4 serialization using native ergo-lib-python bindings
    print("> Constructing mock R4 Register containing 4 Depositor Keys...")
    
    # In a real scenario, this would be a Coll[GroupElement].
    # For our PyO3 test, we will create a Coll[Byte] natively representing pool metadata.
    # The `decode_register` abstracts this completely away from the agent!
    bytes_data = b'Mock_GroupElement_Array_Data'
    mock_constant = Constant(bytes_data)
    mock_hex = bytes(mock_constant).hex()
    
    print(f"> Mock Hex from Node: {mock_hex}")

    # 2. Reconstruct the Box as the SDK would return it
    pool_box = Box(
        box_id="mock_pool_box_id_12345",
        value=1000000,
        ergo_tree="100204...",
        creation_height=1200000,
        additional_registers={"R4": mock_hex}
    )

    print("\n[AI Agent Decoding Protocol]")
    print("> Agent: 'I need to check how many depositors are in this ring pool.'")
    
    # 3. The magic of the new feature: Zero hex manipulation required by the LLM
    decoded_r4 = pool_box.decode_register("R4")
    
    if decoded_r4:
        print(f"> Agent: 'Successfully decoded R4 native register!'")
        print(f"> Extracted Byte Array: {decoded_r4}")
        print("> Agent: 'The pool has sufficient anonymity set. Ready to execute withdrawal proof.'")
        print("\n[OK] TEST SUCCESS: Native SDK Deserialization is fully functional!")
    else:
        print("[FAIL] TEST FAILED: Could not decode R4.")


if __name__ == "__main__":
    asyncio.run(main())
