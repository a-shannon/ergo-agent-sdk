def serialize_string(s: str) -> str:
    """Serialize a python string to Ergo Coll[Byte] hex."""
    b = s.encode("utf-8")
    length = len(b)
    # 0e is Coll[Byte], followed by VLQ encoded length
    # Note: simple VLQ for length < 128
    return "0e" + f"{length:02x}" + b.hex()

def serialize_int(i: int) -> str:
    """Serialize a python int to Ergo Int (SInt = 04)."""
    # 04 is Int type. Followed by ZigZag VLQ.
    # For i >= 0 and i < 64:
    zigzag = i * 2
    return "04" + f"{zigzag:02x}"

def serialize_string_r6(s: str) -> str:
    # Some tokens use Coll[Byte] for R6.
    return serialize_string(s)

print("R4 kushti:", serialize_string("kushti"))
print("R6 (int 0):", serialize_int(0))
print("R6 (int 2):", serialize_int(2))
print("R6 (string '0'):", serialize_string("0"))
