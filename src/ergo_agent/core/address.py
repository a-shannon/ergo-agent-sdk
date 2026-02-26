"""
Ergo address utilities: validation, encoding, ErgoTree resolution.

Ergo uses a custom Base58 encoding with Blake2b-256 checksums.
Address format: network_byte + content_bytes + checksum (4 bytes)

Network types:
  - 0x01 = mainnet P2PK
  - 0x02 = mainnet P2SH
  - 0x03 = mainnet P2S
  - 0x10 = testnet P2PK
  etc.

Reference: https://docs.ergoplatform.com/dev/wallet/address/
"""

try:
    import ergo_lib_python.chain as ergo_chain
except ImportError:
    ergo_chain = None  # type: ignore[assignment]


class AddressError(Exception):
    """Raised for invalid Ergo addresses."""
    pass

def validate_address(address: str) -> bool:
    """
    Validate an Ergo address using the native Sigma-Rust bindings.

    Args:
        address: Ergo address string (Base58 encoded)

    Returns:
        True if valid

    Raises:
        AddressError: if the address is malformed or has a bad checksum
    """
    try:
        ergo_chain.Address(address)
        return True
    except Exception as e:
        raise AddressError(f"Invalid Ergo Address: {e}") from None

def is_valid_address(address: str) -> bool:
    """Check if an Ergo address is valid without raising exceptions."""
    try:
        return validate_address(address)
    except AddressError:
        return False

def is_mainnet_address(address: str) -> bool:
    """Check if address is a mainnet address."""
    try:
        addr = ergo_chain.Address(address)
        # Attempt to re-encode it using the mainnet prefix. If it serializes
        # back exactly to the original input string, it's a mainnet address.
        return addr.to_str(ergo_chain.NetworkPrefix.Mainnet) == address
    except Exception:
        return False

def is_p2pk_address(address: str) -> bool:
    """Check if address is a P2PK (pay-to-public-key) address."""
    try:
        addr = ergo_chain.Address(address)
        tree_hex = bytes(addr.ergo_tree()).hex()
        return tree_hex.startswith("0008cd")
    except Exception:
        return False

def get_address_type(address: str) -> str:
    """Return a human-readable address type."""
    try:
        addr = ergo_chain.Address(address)

        network = "mainnet" if is_mainnet_address(address) else "testnet"
        tree_hex = bytes(addr.ergo_tree()).hex()

        if tree_hex.startswith("0008cd"):
            addr_type = "P2PK"
        elif addr.to_str(ergo_chain.NetworkPrefix.Mainnet).startswith("8") or addr.to_str(ergo_chain.NetworkPrefix.Testnet).startswith("8"):
            # Highly simplified inference for P2SH
            addr_type = "P2SH"
        else:
            addr_type = "P2S"

        return f"{network}-{addr_type}"
    except Exception:
        return "invalid"

def address_to_ergo_tree(address: str, node_url: str = "ignored") -> str:
    """
    Convert an Ergo address to its ErgoTree hex representation.

    Uses natively compiled `ergo_lib` rust bindings to generate the exact ErgoTree
    offline, eliminating the need to query the node API.

    Args:
        address: valid Ergo address
        node_url: Kept for backwards compatibility but ignored.

    Returns:
        str: ErgoTree hex string
    """
    try:
        addr = ergo_chain.Address(address)
        return bytes(addr.ergo_tree()).hex()
    except Exception as e:
        raise AddressError(f"Failed to generate ErgoTree from address: {e}") from None
