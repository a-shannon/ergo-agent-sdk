"""
Unit tests for VLQ encoding/decoding and R6 denomination parsing.
Tests the internal helpers in PrivacyPoolClient that handle Ergo's
Coll[GroupElement] serialization format.
"""

import pytest

from ergo_agent.defi.privacy_pool import PrivacyPoolClient


# --- VLQ Roundtrip Tests ---

@pytest.mark.parametrize("n", [0, 1, 16, 50, 100, 127])
def test_vlq_roundtrip_single_byte(n):
    """VLQ encode/decode should roundtrip for values 0–127 (single byte)."""
    encoded = PrivacyPoolClient._encode_vlq(n)
    decoded = PrivacyPoolClient._read_vlq(encoded)
    assert decoded == n
    assert len(encoded) == 2  # single byte = 2 hex chars


@pytest.mark.parametrize("n", [128, 200, 255, 1000, 16383, 65535])
def test_vlq_roundtrip_multi_byte(n):
    """VLQ encode/decode should roundtrip for values ≥128 (multi-byte)."""
    encoded = PrivacyPoolClient._encode_vlq(n)
    decoded = PrivacyPoolClient._read_vlq(encoded)
    assert decoded == n
    assert len(encoded) > 2  # multi-byte


def test_vlq_encode_zero():
    """VLQ encoding of 0 should be '00'."""
    assert PrivacyPoolClient._encode_vlq(0) == "00"


def test_vlq_encode_128():
    """128 = 0x80 → VLQ: [0x80, 0x01] → '8001'."""
    encoded = PrivacyPoolClient._encode_vlq(128)
    assert PrivacyPoolClient._read_vlq(encoded) == 128


# --- R6 Denomination Decoding ---

def test_r6_decode_100():
    """Standard pool denomination: '05c801' → zigzag → 100."""
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._decode_r6_denomination("05c801") == 100


def test_r6_decode_empty():
    """Empty R6 should return safe default of 100."""
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._decode_r6_denomination("") == 100


def test_r6_decode_none_like():
    """Short/malformed R6 should return safe default."""
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._decode_r6_denomination("05") == 100


def test_r6_decode_malformed():
    """Completely invalid hex should return safe default."""
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._decode_r6_denomination("zzzz") == 100


# --- _count_group_elements ---

def test_count_empty_collection():
    """'1300' means Coll[GroupElement] with 0 elements."""
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._count_group_elements("1300") == 0


def test_count_one_element():
    """1 GroupElement = 33 bytes (02 prefix + 32 coord bytes)."""
    fake_ge = "02" + "aa" * 32
    hex_str = "1301" + fake_ge
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._count_group_elements(hex_str) == 1


def test_count_16_elements():
    """Full ring of 16 elements."""
    fake_ge = "02" + "bb" * 32
    hex_str = "1310" + fake_ge * 16  # 0x10 = 16
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._count_group_elements(hex_str) == 16


def test_count_from_dict():
    """Explorer API returns register as a dict with 'serializedValue' key."""
    fake_ge = "02" + "cc" * 32
    r4_dict = {"serializedValue": "1302" + fake_ge * 2}
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._count_group_elements(r4_dict) == 2


def test_count_empty_string():
    """Empty string should return 0."""
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._count_group_elements("") == 0


def test_count_non_collection():
    """Non-Coll type prefix should return 0."""
    client = PrivacyPoolClient.__new__(PrivacyPoolClient)
    assert client._count_group_elements("0e1234") == 0
