import json
from ergo_agent import ErgoNode
node = ErgoNode()
bank_nft = "0fb1eca4646950743bc5a8c341c16871a0ad9b4077e3b276bf93855d51a042d1"
import httpx
import httpx
try:
    resp = httpx.get("https://api.tokenjay.app/ageusd/info")
    print(resp.json())
except Exception as e:
    print(f"Error: {e}")
