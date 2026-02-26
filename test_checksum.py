import sys

def base58_decode(s):
    # Same as bitcoin base58 alphabet
    ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    ALPHABET_MAP = {char: i for i, char in enumerate(ALPHABET)}
    
    n = 0
    for char in s.encode("ascii"):
        n = n * 58 + ALPHABET_MAP[char]

    if n == 0:
        return b""
    byte_length = (n.bit_length() + 7) // 8
    result = n.to_bytes(byte_length, "big")

    pad_size = 0
    for char in s.encode("ascii"):
        if char == ALPHABET[0]:
            pad_size += 1
        else:
            break
    return b"\x00" * pad_size + result

import hashlib
def blake2b256(data): return hashlib.blake2b(data, digest_size=32).digest()

s = "9eiUhEJPqumE2uLhZt2tX3r91HhBvD1oK5EebjQZ4iGfKZYgQ6W"
print("Testing:", s)

raw = base58_decode(s)
print("Raw bytes len:", len(raw))
content, checksum = raw[:-4], raw[-4:]
expected = blake2b256(content)[:4]

print("Prefix byte:", raw[0])
print("Checksum:", checksum.hex())
print("Expected Checksum:", expected.hex())
print("Match:", checksum == expected)

import ergo_lib_python as elp
try:
    addr = elp.chain.Address(s)
    print("Ergo-Lib: OK", addr.to_str(elp.chain.NetworkPrefix.Mainnet))
except Exception as e:
    print("Ergo-Lib Error:", e)

