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

from __future__ import annotations

import hashlib

import httpx

# Base58 alphabet (same as Bitcoin)
_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_ALPHABET_MAP = {char: i for i, char in enumerate(_ALPHABET)}


class AddressError(Exception):
    """Raised for invalid Ergo addresses."""

    pass


def validate_address(address: str) -> bool:
    """
    Validate an Ergo address (checksum + network byte check).

    Args:
        address: Ergo address string (Base58 encoded)

    Returns:
        True if valid

    Raises:
        AddressError: if the address is malformed or has a bad checksum
    """
    try:
        raw = _base58_decode(address)
    except Exception as e:
        raise AddressError(f"Invalid Base58 encoding: {e}") from None

    if len(raw) < 5:
        raise AddressError(f"Address too short: {len(raw)} bytes (minimum 5)")

    # Split into content + checksum
    content = raw[:-4]
    checksum = raw[-4:]

    # Verify checksum: Blake2b-256 of content, first 4 bytes
    expected = _blake2b256(content)[:4]
    if checksum != expected:
        raise AddressError(
            f"Checksum mismatch: got {checksum.hex()}, expected {expected.hex()}"
        )

    # Check network byte
    network_byte = raw[0]
    if network_byte not in (0x01, 0x02, 0x03, 0x10, 0x11, 0x12):
        raise AddressError(f"Unknown network byte: 0x{network_byte:02x}")

    return True


def is_valid_address(address: str) -> bool:
    """
    Check if an Ergo address is valid without raising exceptions.

    Returns:
        bool: True if valid, False otherwise
    """
    try:
        return validate_address(address)
    except AddressError:
        return False


def is_mainnet_address(address: str) -> bool:
    """Check if address is a mainnet address."""
    try:
        raw = _base58_decode(address)
        return raw[0] in (0x01, 0x02, 0x03)
    except Exception:
        return False


def is_p2pk_address(address: str) -> bool:
    """Check if address is a P2PK (pay-to-public-key) address."""
    try:
        raw = _base58_decode(address)
        return raw[0] in (0x01, 0x10)  # mainnet or testnet P2PK
    except Exception:
        return False


def get_address_type(address: str) -> str:
    """Return a human-readable address type."""
    try:
        raw = _base58_decode(address)
    except Exception:
        return "invalid"

    byte = raw[0]
    types = {
        0x01: "mainnet-P2PK",
        0x02: "mainnet-P2SH",
        0x03: "mainnet-P2S",
        0x10: "testnet-P2PK",
        0x11: "testnet-P2SH",
        0x12: "testnet-P2S",
    }
    return types.get(byte, f"unknown-0x{byte:02x}")


def address_to_ergo_tree(address: str, node_url: str = "https://api.ergoplatform.com") -> str:
    """
    Convert an Ergo address to its ErgoTree hex representation.

    Uses the Ergo node/explorer API for reliable conversion.
    For P2PK addresses, the ErgoTree has a known format that can be
    derived directly. For P2S/P2SH we must use the API.

    Args:
        address: valid Ergo address
        node_url: Ergo node or explorer API URL

    Returns:
        str: ErgoTree hex string
    """
    validate_address(address)

    raw = _base58_decode(address)
    network_byte = raw[0]

    # For P2PK addresses, we can construct the ErgoTree directly
    # P2PK ErgoTree format: 0008cd{33-byte-pubkey}
    if network_byte in (0x01, 0x10):
        # P2PK: content = network_byte + pubkey (33 bytes)
        pubkey_bytes = raw[1:-4]  # strip network byte and checksum
        if len(pubkey_bytes) == 33:
            return "0008cd" + pubkey_bytes.hex()

    # For P2S/P2SH addresses, query the API
    # The Explorer API returns ErgoTree in box data, but we can also
    # try to decode from the address directly
    if network_byte in (0x02, 0x11):
        # P2SH: needs API lookup — fall through to fallback below
        pass

    if network_byte in (0x03, 0x12):
        # P2S: content = network_byte + serialized_script
        script_bytes = raw[1:-4]
        return script_bytes.hex()

    # Fallback: query the explorer for a box from this address to get the ErgoTree
    return _ergo_tree_from_api(address, node_url)


def address_to_ergo_tree_via_boxes(
    address: str, client: httpx.Client, node_url: str
) -> str:
    """
    Get the ErgoTree for an address by looking up one of its boxes.
    This is a fallback method when direct derivation isn't possible.
    """
    response = client.get(
        f"{node_url}/api/v1/boxes/unspent/byAddress/{address}?limit=1",
        timeout=15.0,
    )
    if response.status_code == 200:
        items = response.json().get("items", [])
        if items:
            return str(items[0]["ergoTree"])

    raise AddressError(f"Could not determine ErgoTree for address: {address}")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _ergo_tree_from_api(address: str, node_url: str) -> str:
    """Query the explorer to get ErgoTree from address via box lookup."""
    client = httpx.Client(timeout=15.0)
    try:
        return address_to_ergo_tree_via_boxes(address, client, node_url)
    finally:
        client.close()


def _blake2b256(data: bytes) -> bytes:
    """Compute Blake2b-256 hash."""
    return hashlib.blake2b(data, digest_size=32).digest()


def _base58_decode(s: str) -> bytes:
    """Decode a Base58-encoded string to bytes."""
    n = 0
    for char in s.encode("ascii"):
        n = n * 58 + _ALPHABET_MAP[char]

    # Convert int to bytes using int.to_bytes for exact length
    if n == 0:
        result = b""
    else:
        byte_length = (n.bit_length() + 7) // 8
        result = n.to_bytes(byte_length, "big")

    # Preserve leading zeros (each leading '1' in Base58 = 0x00 byte)
    pad_size = 0
    for char in s.encode("ascii"):
        if char == _ALPHABET[0]:
            pad_size += 1
        else:
            break

    return b"\x00" * pad_size + result


def _base58_encode(data: bytes) -> str:
    """Encode bytes to a Base58 string."""
    n = int.from_bytes(data, "big")
    result = []
    while n > 0:
        n, remainder = divmod(n, 58)
        result.append(_ALPHABET[remainder:remainder + 1])
    result.reverse()

    # Preserve leading zeros
    pad_size = 0
    for byte in data:
        if byte == 0:
            pad_size += 1
        else:
            break

    return (b"1" * pad_size + b"".join(result)).decode("ascii")
