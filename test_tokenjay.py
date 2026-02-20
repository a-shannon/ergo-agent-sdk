import urllib.request
import json
import httpx

# TokenJay API for AgeUSD
url = "https://api.tokenjay.app/ageusd/buy/sigusd?amount=100"
headers = {"Accept": "application/json"}
req = urllib.request.Request(url, headers=headers)

try:
    with urllib.request.urlopen(req) as response:
        data = response.read().decode()
        print(json.dumps(json.loads(data), indent=2))
except Exception as e:
    print(f"Error: {e}")
